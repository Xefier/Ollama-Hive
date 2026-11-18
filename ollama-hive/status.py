#!/usr/bin/env python3
"""Serves the progress page of a training run, and this rig's part of its data. h-train.sh runs it.

Every rig serves the same page (status.html) and its own history. The page, opened from any rig, asks all rigs of
the run for theirs and draws them together, so it works with whichever rigs are on the flight sheet: a rig that is
rented doesn't answer and shows as away.

  /          the page
  /status    what this rig is doing now, what stops it if something does (problem.py), its GPUs and what is using
             their memory, and the addresses of the rigs of the run that it has heard (meet.py)
  /history   the lines train.py wrote since byte ?from=, for a page that keeps asking
  /log       the end of the miner log, for finding out from another PC why a rig isn't training

Read-only, and anything that can reach the port can read it. Standard library only.
"""

import argparse
import glob
import http.server
import json
import os
import subprocess
import time
import urllib.parse

import problem

HERE = os.path.dirname(os.path.abspath(__file__))


def read_line(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def rigs_heard(path, me):
    try:
        with open(path, encoding="utf-8") as handle:
            return sorted(set(json.load(handle)) | {me})
    except (OSError, ValueError, TypeError):
        return [me]


LOG_END = 64 * 1024  # bytes of the miner log that /log gives


def end_of(path, length):
    try:
        with open(path, "rb") as handle:
            handle.seek(max(0, os.path.getsize(path) - length))
            return handle.read()
    except OSError:
        return b""


GPU_FIELDS = "name,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw,uuid"
PROCESS_FIELDS = "gpu_uuid,pid,used_memory,process_name"
OURS = "ollama-hive"  # in the command line of everything this miner runs: its folder, and its data folder
gpus_asked = [0, [], []]  # when, and the answers: several pages open don't each start nvidia-smi


def nvidia_smi(query, fields):
    try:
        answer = subprocess.run(["nvidia-smi", f"--query-{query}={fields}", "--format=csv,noheader,nounits"],
                                capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [[field.strip() for field in line.split(",", fields.count(","))] for line in answer.splitlines() if line.strip()]


def command_of(pid, otherwise):
    """The command line of a process, which says more than the program's name: every Python script is python."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            return handle.read().replace(b"\0", b" ").decode("utf-8", "replace").strip() or otherwise
    except OSError:
        return otherwise


def gpus():
    """A line per GPU as nvidia-smi gives it (name, MiB used, MiB in all, % busy, degrees, watts, id), and the
    processes computing on them: which GPU, the process, its MiB, what it is, and whether this miner runs it. The
    display server and the like hold GPU memory without being listed, so the processes need not add up."""
    if time.time() - gpus_asked[0] > 5:
        gpus_asked[1] = nvidia_smi("gpu", GPU_FIELDS)
        ids = [gpu[-1] for gpu in gpus_asked[1]]
        processes = []
        for gpu, pid, used, name in (row for row in nvidia_smi("compute-apps", PROCESS_FIELDS) if len(row) == 4):
            command = command_of(pid, name)
            processes.append({"gpu": ids.index(gpu) if gpu in ids else 0, "pid": pid,
                              "mib": int(used) if used.isdigit() else None,
                              "command": command[:300], "ours": OURS in command})
        gpus_asked[2] = processes
        gpus_asked[0] = time.time()
    return gpus_asked[1], gpus_asked[2]


def memory_reports(prefix):
    """What each of this rig's training workers says its GPU memory goes to (train.py), by process."""
    reports = []
    for path in glob.glob(glob.escape(prefix) + "-*") if prefix else []:
        try:
            with open(path, encoding="utf-8") as handle:
                reports.append(json.load(handle))
        except (OSError, ValueError):
            pass
    return reports


def history_since(path, start):
    """The whole lines after byte start, and where the next call should start. From 0 again when the file is
    shorter than start: the run folder was started anew."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return {"next": 0, "lines": "", "reset": start > 0}
    reset = start > size
    if reset:
        start = 0
    with open(path, "rb") as handle:
        handle.seek(start)
        data = handle.read()
    # A line train.py is still writing waits for the next call
    data = data[:data.rfind(b"\n") + 1]
    return {"next": start + len(data), "lines": data.decode("utf-8", "replace"), "reset": reset}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--me", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--rigs-file", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--run-name", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--status-file", required=True)
    parser.add_argument("--log-file", default="")
    parser.add_argument("--problem-file", default="")
    parser.add_argument("--memory-file", default="")
    args = parser.parse_args()

    class Handler(http.server.BaseHTTPRequestHandler):
        def send(self, body, kind):
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            # The page comes from one rig and asks the others
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, value):
            self.send(json.dumps(value).encode(), "application/json")

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path == "/":
                with open(os.path.join(HERE, "status.html"), "rb") as handle:
                    self.send(handle.read(), "text/html; charset=utf-8")
            elif url.path == "/status":
                cards, processes = gpus()
                self.send_json({"address": args.me, "port": args.port, "rigs": rigs_heard(args.rigs_file, args.me),
                                "run": args.run_name, "version": args.version, "time": round(time.time()),
                                "state": read_line(args.state_file), "status": read_line(args.status_file),
                                "problem": problem.read(args.problem_file), "gpus": cards, "processes": processes,
                                "memory": memory_reports(args.memory_file),
                                "log": bool(args.log_file)})
            elif url.path == "/history":
                query = urllib.parse.parse_qs(url.query)
                try:
                    start = max(0, int(query.get("from", ["0"])[0]))
                except ValueError:
                    start = 0
                self.send_json(history_since(os.path.join(args.run_dir, "history.jsonl"), start))
            elif url.path == "/log" and args.log_file:
                self.send(end_of(args.log_file, LOG_END), "text/plain; charset=utf-8")
            else:
                self.send_error(404)

        def log_message(self, *_):
            pass  # a request every few seconds per open page would fill the miner log

    http.server.ThreadingHTTPServer.daemon_threads = True
    try:
        server = http.server.ThreadingHTTPServer((args.me, args.port), Handler)
    except OSError as error:
        raise SystemExit(f"[status] Can't serve the progress page on {args.me}:{args.port} ({error})")
    server.serve_forever()


if __name__ == "__main__":
    main()
