#!/usr/bin/env python3
"""Keeps this rig's training worker in step with whichever other rigs are training now. h-train.sh runs it.

Rigs come and go as rentals take them, so the group that trains together changes during a run. One rig hosts the
meeting: the others tell it every few seconds that they are there, and it answers with the current group. Every time
the group changes it gets a new number, and each rig then stops its worker (train.py saves first) and starts one for
the new group, with the addresses and ranks PyTorch's distributed training reads from the environment.

No rig is special. A rig looks for a peer that is hosting and hosts itself if none is; when the host leaves, the
others notice within seconds and one of them takes over. Two that started hosting at the same moment sort it out by
address: the higher one gives way.

Standard library only.
"""

import argparse
import json
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time

BEAT = 2            # seconds between a rig's messages to the host
GONE_AFTER = 15     # a rig silent this long has left
SETTLE = 12         # wait this long after a change for more changes, so rigs arriving together form one group
HOST_LOST = 10      # seconds without an answer before a rig looks for another host
STOP_GRACE = 40     # seconds a worker gets to save and leave
PORT_SPREAD = 8     # each group's workers meet on one of this many ports after the meeting port


def log(text):
    print(f"[meet] {text}", flush=True)


def ask(address, port, message, timeout=3):
    """One request to a host. None when nobody answers there."""
    try:
        with socket.create_connection((address, port), timeout=timeout) as connection:
            connection.sendall((json.dumps(message) + "\n").encode())
            reply = connection.makefile().readline()
        return json.loads(reply) if reply else None
    except (OSError, ValueError):
        return None


class Host:
    """The meeting, on the rig that hosts it."""

    def __init__(self, me, workers, port):
        self.me = me
        self.port = port
        self.lock = threading.Lock()
        self.members = {me: {"workers": workers, "last": None}}
        self.group = None
        self.count = 0
        self.changed = time.time()
        self.pending = True
        host = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    message = json.loads(self.rfile.readline())
                    reply = host.answer(message)
                    self.wfile.write((json.dumps(reply) + "\n").encode())
                except (OSError, ValueError, KeyError, TypeError):
                    pass  # a stray connection, or a peer that went away mid-message

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server((me, port), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def change(self):
        self.pending = True
        self.changed = time.time()

    def answer(self, message):
        with self.lock:
            address = message.get("address")
            if message["op"] == "beat":
                known = self.members.get(address)
                if not known or known["workers"] != message["workers"]:
                    self.change()
                self.members[address] = {"workers": message["workers"], "last": time.time()}
                self.failed(message.get("failed"))
            elif message["op"] == "leave":
                if self.members.pop(address, None):
                    self.change()
            return {"host": self.me, "group": self.group}

    def failed(self, number):
        """A worker of the current group ended on its own (a peer vanished, an error): everyone starts again."""
        if number is not None and self.group and number == self.group["number"] and not self.pending:
            self.change()

    def tick(self):
        with self.lock:
            now = time.time()
            for address, member in list(self.members.items()):
                if member["last"] is not None and now - member["last"] > GONE_AFTER:
                    del self.members[address]
                    log(f"{address} is gone")
                    self.change()
            if self.pending and now - self.changed >= SETTLE:
                self.count += 1
                members = sorted(self.members.items(), key=lambda item: socket.inet_aton(item[0]))
                self.group = {
                    "number": f"{self.me}/{os.getpid()}/{self.count}",
                    "members": [[address, member["workers"]] for address, member in members],
                    "port": self.port + 1 + self.count % PORT_SPREAD,
                }
                self.pending = False
                log(f"Group {self.count}: {', '.join(address for address, _ in members)}")
            return self.group


class Rig:
    def __init__(self, args, command):
        self.args = args
        self.command = command
        self.peers = sorted(set(args.peers.split(",")), key=socket.inet_aton)
        self.workers = []
        self.running = None  # the number of the group the workers were started for
        self.failed = None
        self.stopping = False

    def find_host(self, lower_only=False):
        for peer in self.peers:
            if peer == self.args.me:
                if lower_only:
                    return None
                continue
            reply = ask(peer, self.args.port, {"op": "ping"}, timeout=2)
            if reply and reply.get("host") == peer:
                return peer
        return None

    def stop_workers(self):
        for worker in self.workers:
            if worker.poll() is None:
                worker.terminate()
        deadline = time.time() + STOP_GRACE
        for worker in self.workers:
            try:
                worker.wait(max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait()
        self.workers = []
        self.running = None
        self.failed = None

    def start_workers(self, group):
        members = group["members"]
        addresses = [address for address, _ in members]
        if self.args.me not in addresses:
            return
        first = sum(count for address, count in members[:addresses.index(self.args.me)])
        world = sum(count for _, count in members)
        log(f"Starting for a group of {len(members)} rigs ({world} GPUs): {', '.join(addresses)}")
        for local in range(self.args.workers):
            environment = dict(os.environ, MASTER_ADDR=addresses[0], MASTER_PORT=str(group["port"]),
                               WORLD_SIZE=str(world), RANK=str(first + local), LOCAL_RANK=str(local))
            self.workers.append(subprocess.Popen(self.command, env=environment))
        self.running = group["number"]

    def finished(self):
        return bool(self.workers) and all(worker.poll() == 0 for worker in self.workers)

    def follow(self, group):
        """Brings the workers in line with the host's current group. True when the run has finished."""
        if self.finished():
            return True
        if group and group["number"] != self.running:
            self.stop_workers()
            self.start_workers(group)
        if self.workers and self.failed is None:
            codes = [worker.poll() for worker in self.workers]
            if any(code not in (None, 0) for code in codes):
                # Ended without finishing: the rest of this rig's workers go too, and the host is told
                log(f"A worker ended with code {[code for code in codes if code][0]}: asking for a new group")
                number = self.running
                self.stop_workers()
                self.running = number
                self.failed = number
        return False

    def host_session(self):
        try:
            host = Host(self.args.me, self.args.workers, self.args.port)
        except OSError as error:
            log(f"Can't host on {self.args.me}:{self.args.port} ({error})")
            time.sleep(5)
            return False
        log(f"No other rig is training: hosting the run on {self.args.me}:{self.args.port}")
        checked = time.time()
        try:
            while not self.stopping:
                with host.lock:
                    host.failed(self.failed)
                if self.follow(host.tick()):
                    return True
                if time.time() - checked > 10:
                    checked = time.time()
                    lower = self.find_host(lower_only=True)
                    if lower:
                        log(f"{lower} is hosting a run too: giving way to it")
                        return False
                time.sleep(1)
        finally:
            host.close()
            self.stop_workers()
        return False

    def member_session(self, host):
        log(f"Joining the run hosted on {host}:{self.args.port}")
        answered = time.time()
        try:
            while not self.stopping:
                reply = ask(host, self.args.port, {"op": "beat", "address": self.args.me,
                                                   "workers": self.args.workers, "failed": self.failed})
                if reply and reply.get("host") == host:
                    answered = time.time()
                    if self.follow(reply.get("group")):
                        return True
                elif self.finished():
                    # The host finished too and closed the meeting
                    return True
                elif time.time() - answered > HOST_LOST:
                    log(f"{host} no longer answers")
                    return False
                time.sleep(BEAT)
            ask(host, self.args.port, {"op": "leave", "address": self.args.me})
        finally:
            self.stop_workers()
        return False

    def run(self):
        def on_stop(*_):
            self.stopping = True

        signal.signal(signal.SIGTERM, on_stop)
        signal.signal(signal.SIGINT, on_stop)
        while not self.stopping:
            host = self.find_host()
            finished = self.member_session(host) if host else self.host_session()
            if finished:
                return 0
        return 75


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--peers", required=True, help="addresses of all rigs of the run, comma-separated")
    parser.add_argument("--me", required=True, help="this rig's address, one of the peers")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--workers", type=int, default=1, help="GPUs this rig trains on")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- then the worker's command line")
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.me not in args.peers.split(","):
        parser.error("need a worker command, and --me must be one of --peers")
    sys.exit(Rig(args, command).run())


if __name__ == "__main__":
    main()
