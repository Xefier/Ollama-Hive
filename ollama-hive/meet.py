#!/usr/bin/env python3
"""Keeps this rig's training worker in step with whichever other rigs are training now. h-train.sh runs it.

Rigs come and go as rentals take them, so the group that trains together changes during a run. One rig hosts the
meeting: the others tell it every few seconds that they are there, and it answers with the current group. Every time
the group changes it gets a new number, and each rig then stops its worker (train.py saves first) and starts one for
the new group, with the addresses and ranks PyTorch's distributed training reads from the environment.

No rig is special and none is listed anywhere: every rig says on the LAN every few seconds that it is here for this
run (Radio), so the flight sheet can go onto a rig or come off one and the others find out by themselves. A rig joins
the host it hears and hosts itself if it hears none; when the host leaves, the others notice within seconds and one
of them takes over. Two that started hosting at the same moment sort it out by address: the higher one gives way.

A rig that is told to stop says so on the LAN at once, and the rigs training with it stop their workers there and
then: the workers meet once per step, and without this the others would finish their part of the step first while
the leaving rig, which has a rental waiting for its GPU, stands by.

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

import problem

BEAT = 2            # seconds between a rig's messages to the host
GONE_AFTER = 15     # a rig silent this long has left
SETTLE = 12         # wait this long after a change for more changes, so rigs arriving together form one group
HOST_LOST = 10      # seconds without an answer before a rig looks for another host
STOP_GRACE = 40     # seconds a worker gets to save and leave
PORT_SPREAD = 8     # each group's workers meet on one of this many ports after the meeting port
LISTEN = 5          # seconds a rig listens for a host before it hosts itself
HEARD_FOR = 3 * BEAT        # a host not heard for this long isn't one to join
FORGET = 7 * 24 * 3600      # a rig not heard for this long is no longer one of the run's rigs
# A rig whose worker keeps failing takes the others' workers down with it at every attempt. From REST_FROM failures in
# a row it sits out between attempts, REST_STEP seconds longer per failure and REST_MOST at most.
REST_FROM, REST_STEP, REST_MOST = 3, 30, 600


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


def ending(code):
    """What a worker's exit code says, for when the worker itself said nothing."""
    if code >= 0:
        return f"The worker ended with code {code}: see the miner log"
    name = signal.Signals(-code).name if -code in signal.Signals._value2member_map_ else f"signal {-code}"
    hint = ": the system may have run out of memory" if name == "SIGKILL" else ""
    return f"The worker was ended by {name}{hint}: see the miner log"


def by_address(address):
    return socket.inet_aton(address)


class Radio:
    """How the rigs of a run find each other. Every rig says every BEAT that it is here, and whether it hosts the
    meeting: to the whole LAN by broadcast, and to the addresses of peers= one by one for a network that doesn't
    carry broadcasts between the rigs. The rigs heard, with when, are kept in a file for the progress page."""

    def __init__(self, me, port, run, targets, rigs_file):
        self.me = me
        self.run = run
        self.targets = [(target, port) for target in targets if target != me]
        self.rigs_file = rigs_file
        self.hosting = False
        self.leaving = False
        self.heard = {}  # address -> when, and whether it was hosting or leaving
        self.known = {}  # address -> when last heard, as in the file
        try:
            with open(rigs_file, encoding="utf-8") as handle:
                self.known = {address: float(when) for address, when in json.load(handle).items()}
        except (OSError, ValueError, AttributeError, TypeError):
            pass
        self.written = None
        self.receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.receiver.bind(("", port))
        # From this rig's LAN address, so it leaves by that interface and not by a Docker bridge
        self.sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sender.bind((me, 0))
        self.started = time.time()
        threading.Thread(target=self.listen, daemon=True).start()
        threading.Thread(target=self.speak, daemon=True).start()

    def say(self):
        message = json.dumps({"run": self.run, "address": self.me, "hosting": self.hosting,
                              "leaving": self.leaving}).encode()
        for target in self.targets:
            try:
                self.sender.sendto(message, target)
            except OSError:
                pass  # the network is down for a moment, or that address can't be reached from here

    def speak(self):
        while True:
            self.say()
            self.known[self.me] = time.time()
            self.write_rigs()
            time.sleep(BEAT)

    def listen(self):
        while True:
            try:
                message = json.loads(self.receiver.recv(2048))
                if message["run"] != self.run or message["address"] == self.me:
                    continue
                by_address(message["address"])
                now = time.time()
                self.heard[message["address"]] = {"at": now, "hosting": bool(message["hosting"]),
                                                  "leaving": bool(message.get("leaving"))}
                self.known[message["address"]] = now
            except (OSError, ValueError, KeyError, TypeError):
                pass  # something else on the LAN uses this port

    def write_rigs(self):
        """When the rigs of the run change, and every minute for the times."""
        now = time.time()
        known = {address: round(when) for address, when in list(self.known.items()) if now - when < FORGET}
        if self.written and set(known) == self.written[0] and now - self.written[1] < 60:
            return
        try:
            with open(self.rigs_file + ".tmp", "w", encoding="utf-8") as handle:
                json.dump(known, handle)
            os.replace(self.rigs_file + ".tmp", self.rigs_file)
            self.written = (set(known), now)
        except OSError:
            pass

    def leavers(self):
        """The rigs that said just now that they are stopping."""
        now = time.time()
        return [address for address, heard in list(self.heard.items())
                if heard["leaving"] and now - heard["at"] < HEARD_FOR]

    def host(self, lower_only=False):
        """The rig to join: the lowest address heard hosting just now. None when there is none."""
        now = time.time()
        hosts = [address for address, heard in list(self.heard.items())
                 if heard["hosting"] and not heard["leaving"] and now - heard["at"] < HEARD_FOR
                 and not (lower_only and by_address(address) > by_address(self.me))]
        return min(hosts, key=by_address, default=None)


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
                members = sorted(self.members.items(), key=lambda item: by_address(item[0]))
                self.group = {
                    "number": f"{self.me}/{os.getpid()}/{self.count}",
                    "members": [[address, member["workers"]] for address, member in members],
                    "port": self.port + 1 + self.count % PORT_SPREAD,
                }
                self.pending = False
                log(f"Group {self.count}: {', '.join(address for address, _ in members)}")
            return self.group


class Rig:
    def __init__(self, args, command, radio):
        self.args = args
        self.command = command
        self.radio = radio
        self.workers = []
        self.members = []    # the rigs the workers train with
        self.running = None  # the number of the group the workers were started for
        self.failed = None
        self.stopping = False
        self.rest_until = 0

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
        self.members = addresses
        self.running = group["number"]

    def end_group(self, why):
        """Stops this rig's workers for good as far as their group goes, and has the host make a new one."""
        log(f"{why}: asking for a new group")
        number = self.running
        self.stop_workers()
        self.running = number
        self.failed = number

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
            leaving = [address for address in self.radio.leavers() if address in self.members]
            if any(code not in (None, 0) for code in codes):
                # Ended without finishing: the rest of this rig's workers go too, and the host is told
                code = [code for code in codes if code][0]
                self.end_group(f"A worker ended with code {code}")
                # 75 and 76 are train.py's for stopping because another rig's worker did, or went away. Anything
                # else went wrong on this rig.
                if code not in (75, 76):
                    failures = problem.failed(self.args.problem_file, ending(code))
                    if failures >= REST_FROM:
                        rest = min(REST_MOST, REST_STEP * failures)
                        self.rest_until = time.time() + rest
                        log(f"Failed {failures} times in a row: sitting out for {rest} s, so the other rigs can train")
            elif leaving:
                # The workers save at once, without finishing a step the leaving rig has dropped
                self.end_group(f"{', '.join(leaving)} is stopping")
        return False

    def resting(self):
        return time.time() < self.rest_until

    def host_session(self):
        try:
            host = Host(self.args.me, self.args.workers, self.args.port)
        except OSError as error:
            log(f"Can't host on {self.args.me}:{self.args.port} ({error})")
            time.sleep(5)
            return False
        log(f"No other rig is training: hosting the run on {self.args.me}:{self.args.port}")
        self.radio.hosting = True
        try:
            while not self.stopping:
                for address in self.radio.leavers():
                    host.answer({"op": "leave", "address": address})
                with host.lock:
                    host.failed(self.failed)
                if self.follow(host.tick()):
                    return True
                if self.resting():
                    return False
                lower = self.radio.host(lower_only=True)
                if lower:
                    log(f"{lower} is hosting the run too: giving way to it")
                    return False
                time.sleep(1)
        finally:
            self.radio.hosting = False
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
                    if self.resting():
                        break
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
            self.radio.leaving = True
            self.radio.say()

        signal.signal(signal.SIGTERM, on_stop)
        signal.signal(signal.SIGINT, on_stop)
        # Long enough to hear a host that is there
        while not self.stopping and time.time() - self.radio.started < LISTEN:
            time.sleep(0.5)
        while not self.stopping:
            if self.resting():
                # As good as gone to the others, so they train without this rig meanwhile
                self.radio.leaving = True
                time.sleep(1)
                continue
            self.radio.leaving = False
            host = self.radio.host()
            finished = self.member_session(host) if host else self.host_session()
            if finished:
                return 0
        return 75


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--me", required=True, help="this rig's address")
    parser.add_argument("--run", required=True, help="name of the run: rigs of another run are not heard")
    parser.add_argument("--broadcast", default="255.255.255.255", help="broadcast address of this rig's LAN")
    parser.add_argument("--peers", default="", help="rigs to tell one by one as well, comma-separated")
    parser.add_argument("--rigs-file", required=True, help="where to keep the rigs heard, for status.py")
    parser.add_argument("--problem-file", required=True, help="where failures are counted, for status.py")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--workers", type=int, default=1, help="GPUs this rig trains on")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="-- then the worker's command line")
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("need a worker command")
    try:
        radio = Radio(args.me, args.port, args.run, [args.broadcast] + [peer for peer in args.peers.split(",") if peer],
                      args.rigs_file)
    except OSError as error:
        sys.exit(f"[meet] Can't listen for the other rigs on port {args.port} ({error})")
    sys.exit(Rig(args, command, radio).run())


if __name__ == "__main__":
    main()
