#!/usr/bin/env python3
"""Serves the progress page of a training run, and this rig's part of its data. h-train.sh runs it.

Every rig serves the same page (status.html) and its own history. The page, opened from any rig, asks all rigs of
the run for theirs and draws them together, so it works with whichever rigs are on the flight sheet: a rig that is
rented doesn't answer and shows as away.

  /          the page
  /status    what this rig is doing now, what stops it if something does (problem.py), its GPUs and what is using
             their memory, now and when the miner had the most of it lately, and the addresses of the rigs of the
             run that it has heard (meet.py)
  /history   the lines train.py wrote since byte ?from=, for a page that keeps asking
  /log       the end of the miner log, for finding out from another PC why a rig isn't training
  /adapter   what this rig has of the run's adapter, and /adapter/<file> each of its files: export-run.sh on a rig
             that serves fetches it here, to make the model the run has trained so far

Read-only, and anything that can reach the port can read it. Standard library only.
"""

import argparse
import glob
import http.server
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request

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
LOOK_EVERY = 3            # seconds between looks at the GPUs
FULLEST_FOR = 30 * 60     # how long the look with the most of this miner on the GPUs is kept
# The latest look at the GPUs, and the one where this miner held the most memory: an attempt that fails is gone from
# the GPU within seconds, and what it looked like at its fullest is what says why
looks = {"now": {"at": 0, "gpus": [], "processes": [], "memory": [], "models": []}, "fullest": None}


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


def models_served(ollama):
    """What this rig's Ollama has loaded: the name, the context each request gets, the bytes it takes and how many of
    them are on the GPU. A model that isn't all there runs partly on the CPU, far slower, which nothing else shows."""
    if not ollama:
        return []
    try:
        with urllib.request.urlopen(ollama + "/api/ps", timeout=3) as answer:
            loaded = json.load(answer).get("models") or []
        return [{"name": model.get("name"), "context": model.get("context_length"), "size": model.get("size"),
                 "on_gpu": model.get("size_vram")} for model in loaded]
    except (OSError, ValueError, AttributeError):
        return []


def look(memory_file, ollama):
    """gpus: a line per GPU as nvidia-smi gives it (name, MiB used, MiB in all, % busy, degrees, watts, id).
    processes: those computing on them: which GPU, the process, its MiB, what it is, and whether this miner runs
    it. The display server and the like hold GPU memory without being listed, so the processes need not add up.
    memory: what this miner's workers say theirs goes to. models: see models_served."""
    cards = nvidia_smi("gpu", GPU_FIELDS)
    ids = [gpu[-1] for gpu in cards]
    processes = []
    for gpu, pid, used, name in (row for row in nvidia_smi("compute-apps", PROCESS_FIELDS) if len(row) == 4):
        command = command_of(pid, name)
        processes.append({"gpu": ids.index(gpu) if gpu in ids else 0, "pid": pid,
                          "mib": int(used) if used.isdigit() else None,
                          "command": command[:300], "ours": OURS in command})
    return {"at": round(time.time()), "gpus": cards, "processes": processes, "memory": memory_reports(memory_file),
            "models": models_served(ollama)}


def ours_in(seen):
    return sum(process["mib"] or 0 for process in seen["processes"] if process["ours"])


def keep_looking(memory_file, ollama):
    while True:
        seen = looks["now"] = look(memory_file, ollama)
        fullest = looks["fullest"]
        if ours_in(seen) and (not fullest or ours_in(seen) >= ours_in(fullest) or seen["at"] - fullest["at"] > FULLEST_FOR):
            looks["fullest"] = seen
        time.sleep(LOOK_EVERY)


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


def adapter_listing(run_dir, run_name, full_base):
    """The adapter as lines of text, which a shell script reads easily: the run, the full-precision base if the
    flight sheet names it, the examples it was trained on, and a line per file with its size. None without one."""
    folder = os.path.join(run_dir, "adapter")
    seen = read_line(os.path.join(folder, "examples-seen"))
    if not seen:
        return None
    lines = [f"run {run_name}"] + ([f"full_base {full_base}"] if full_base else []) + [f"seen {seen}"]
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and ADAPTER_FILE.match(name):
            lines.append(f"file {name} {os.path.getsize(path)}")
    return "\n".join(lines) + "\n"


ADAPTER_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")  # a name in the adapter's folder, and nothing above it


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
    parser.add_argument("--full-base", default="")
    parser.add_argument("--ollama", default="", help="http://address:port of this rig's Ollama, on a flight sheet that serves")
    parser.add_argument("--mode", default="train", help="the flight sheet's: train, serve or export")
    parser.add_argument("--export-files", default="", help="export-run.sh's state and status files, less -state and -status")
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
                seen = looks["now"]
                exporting = read_line(args.export_files + "-state") if args.export_files else ""
                self.send_json({"address": args.me, "mode": args.mode,
                                "export": {"state": exporting, "status": read_line(args.export_files + "-status")}
                                if exporting else None, "port": args.port, "rigs": rigs_heard(args.rigs_file, args.me),
                                "run": args.run_name, "version": args.version, "time": round(time.time()),
                                "state": read_line(args.state_file), "status": read_line(args.status_file),
                                "problem": problem.read(args.problem_file), "gpus": seen["gpus"], "processes": seen["processes"],
                                "memory": seen["memory"], "fullest": looks["fullest"], "models": seen["models"],
                                "log": bool(args.log_file)})
            elif url.path == "/history":
                query = urllib.parse.parse_qs(url.query)
                try:
                    start = max(0, int(query.get("from", ["0"])[0]))
                except ValueError:
                    start = 0
                self.send_json(history_since(os.path.join(args.run_dir, "history.jsonl"), start))
            elif url.path == "/adapter":
                listing = adapter_listing(args.run_dir, args.run_name, args.full_base)
                if listing is None:
                    self.send_error(404, "No adapter yet: this rig has not trained a step of the run")
                else:
                    self.send(listing.encode(), "text/plain; charset=utf-8")
            elif url.path.startswith("/adapter/") and ADAPTER_FILE.match(url.path[len("/adapter/"):]):
                try:
                    with open(os.path.join(args.run_dir, "adapter", url.path[len("/adapter/"):]), "rb") as handle:
                        # Hundreds of MB: passed on as it is read
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Length", str(os.fstat(handle.fileno()).st_size))
                        self.end_headers()
                        shutil.copyfileobj(handle, self.wfile, 1024 * 1024)
                except OSError:
                    self.send_error(404)
            elif url.path == "/log" and args.log_file:
                self.send(end_of(args.log_file, LOG_END), "text/plain; charset=utf-8")
            else:
                self.send_error(404)

        def log_message(self, *_):
            pass  # a request every few seconds per open page would fill the miner log

    threading.Thread(target=keep_looking, args=(args.memory_file, args.ollama), daemon=True).start()
    http.server.ThreadingHTTPServer.daemon_threads = True
    try:
        server = http.server.ThreadingHTTPServer((args.me, args.port), Handler)
    except OSError as error:
        raise SystemExit(f"[status] Can't serve the progress page on {args.me}:{args.port} ({error})")
    server.serve_forever()


if __name__ == "__main__":
    main()
