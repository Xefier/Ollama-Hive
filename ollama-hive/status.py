#!/usr/bin/env python3
"""Serves the progress page of a training run, and this rig's part of its data. h-train.sh runs it.

Every rig serves the same page (status.html) and its own history. The page, opened from any rig, asks all rigs of
the run for theirs and draws them together, so it works with whichever rigs are on the flight sheet: a rig that is
rented doesn't answer and shows as away.

  /          the page
  /status    what this rig is doing now, and the addresses of the rigs of the run that it has heard (meet.py)
  /history   the lines train.py wrote since byte ?from=, for a page that keeps asking

Read-only, and anything that can reach the port can read it. Standard library only.
"""

import argparse
import http.server
import json
import os
import time
import urllib.parse

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
                self.send_json({"address": args.me, "port": args.port, "rigs": rigs_heard(args.rigs_file, args.me),
                                "run": args.run_name, "version": args.version, "time": round(time.time()),
                                "state": read_line(args.state_file), "status": read_line(args.status_file)})
            elif url.path == "/history":
                query = urllib.parse.parse_qs(url.query)
                try:
                    start = max(0, int(query.get("from", ["0"])[0]))
                except ValueError:
                    start = 0
                self.send_json(history_since(os.path.join(args.run_dir, "history.jsonl"), start))
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
