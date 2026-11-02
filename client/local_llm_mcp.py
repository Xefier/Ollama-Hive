#!/usr/bin/env python3
"""MCP server (stdio) that lets a Claude session delegate one question to Ollama on a rig on the LAN.

It reads the files itself and returns only the answer, so a file handed to the model never costs Claude the tokens of
reading it. Standard library only.

Environment:
  OLLAMA_URLS       Rigs to try in order, comma separated. Switching a rig's flight sheet takes it out of this list's
                    reach and the next one that has a model loaded is used.
  LOCAL_LLM_ROOTS   More folders files may be read from besides the working directory, separated by the OS path
                    separator (local-llm.ps1 adds the Unity editor logs and Claude's scratch folders).
  LOCAL_LLM_STATS   The usage log, one JSON line per call. Default %LOCALAPPDATA%\local-llm\stats.jsonl
                    (~/.local-llm/stats.jsonl where LOCALAPPDATA is not set).

Run directly with --stats [days] [--json] it prints the usage summary instead of serving.
"""

import datetime
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request

SERVER_NAME = "local-llm"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-06-18"
STATUS_TIMEOUT_SECONDS = 3
ANSWER_TIMEOUT_SECONDS = 900
MAX_FILE_BYTES = 2 * 1024 * 1024
# A cautious estimate for source code, to refuse early rather than have the model silently lose the start of its prompt
CHARS_PER_TOKEN = 3.0
RESERVED_ANSWER_TOKENS = 2048
STATS_DAYS = 14

TOOLS = [
    {
        "name": "local_llm_status",
        "description": "Shows which local Ollama rigs are reachable, the model each has loaded, its context size and how much is on the GPU.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "local_llm_ask",
        "description": (
            "Sends one self-contained question to the local Ollama model and returns its answer. Pass files by path: "
            "they are read here, and their contents never enter this conversation. Weaker than Claude: use for log "
            "triage, summarising large files and first-pass searches, and verify what it says before acting on it. "
            "It remembers nothing between calls and cannot use tools."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The question, with everything the model needs to know."},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Paths of text files to include."},
                "system": {"type": "string", "description": "Optional system prompt."},
                "think": {"type": "boolean", "description": "Let the model reason first: slower, default false."},
                "max_tokens": {"type": "integer", "description": "Longest answer allowed. Default: no limit set."},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "local_llm_stats",
        "description": (
            "Usage of the local model on this PC: calls, tokens it read, tokens saved (prompt minus answer), "
            "refusals and errors, per project and per day."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Days covered by the per-project and per-day lines. Default 14."},
                "json": {"type": "boolean", "description": "Return the aggregate as JSON (for the dashboard sync)."},
            },
        },
    },
]


class ToolError(Exception):
    pass


def urls():
    configured = os.environ.get("OLLAMA_URLS", "http://127.0.0.1:11434")
    return [url.strip().rstrip("/") for url in configured.split(",") if url.strip()]


def roots():
    folders = [os.getcwd()] + os.environ.get("LOCAL_LLM_ROOTS", "").split(os.pathsep)
    return [os.path.realpath(os.path.expandvars(folder)) for folder in folders if folder]


def request_json(url, payload=None, timeout=STATUS_TIMEOUT_SECONDS):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def loaded_model(url):
    """The rig's loaded model, or None when it is reachable with nothing loaded. Raises when it is unreachable."""
    models = request_json(url + "/api/ps").get("models") or []
    return models[0] if models else None


def find_rig():
    problems = []
    for url in urls():
        try:
            model = loaded_model(url)
        except (urllib.error.URLError, OSError, ValueError) as error:
            problems.append("{}: unreachable ({})".format(url, error))
            continue
        if model:
            return url, model
        problems.append("{}: no model loaded yet".format(url))
    raise ToolError("No local model is available. " + "; ".join(problems))


def read_file(path):
    real = os.path.realpath(path)
    allowed = roots()
    if not any(real == root or real.startswith(root + os.sep) for root in allowed):
        raise ToolError("{} is outside the allowed folders: {}".format(path, os.pathsep.join(allowed)))
    try:
        if os.path.getsize(real) > MAX_FILE_BYTES:
            raise ToolError("{} is over {} MB: send the part that matters".format(path, MAX_FILE_BYTES // (1024 * 1024)))
        with open(real, "r", encoding="utf-8", errors="replace") as file:
            return file.read()
    except OSError as error:
        raise ToolError("Could not read {}: {}".format(path, error))


def stats_path():
    configured = os.environ.get("LOCAL_LLM_STATS")
    if configured:
        return configured
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return os.path.join(base, "local-llm", "stats.jsonl")
    return os.path.join(os.path.expanduser("~"), ".local-llm", "stats.jsonl")


def project_name():
    folder = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return os.path.basename(os.path.normpath(folder)) or folder


def log_call(entry):
    """Appends one line to the usage log. Never raises: a logging problem must not cost the answer."""
    try:
        line = {
            "ts": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "pc": socket.gethostname(),
            "project": project_name(),
            # The PC's own calendar day, which the stats group by: a UTC date would put an evening's calls on tomorrow
            "day": datetime.date.today().isoformat(),
        }
        line.update(entry)
        path = stats_path()
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "a", encoding="utf-8") as file:
            file.write(json.dumps(line) + "\n")
    except Exception:
        pass


def files_size(files):
    total = 0
    for path in files or []:
        try:
            total += os.path.getsize(os.path.realpath(path))
        except OSError:
            pass
    return total


def build_prompt(prompt, files):
    parts = []
    for path in files or []:
        parts.append('<file path="{}">\n{}\n</file>'.format(path, read_file(path)))
    parts.append(prompt)
    return "\n\n".join(parts)


def status(_arguments):
    lines = []
    for url in urls():
        try:
            model = loaded_model(url)
        except (urllib.error.URLError, OSError, ValueError) as error:
            lines.append("{}: unreachable ({})".format(url, error))
            continue
        if not model:
            lines.append("{}: reachable, no model loaded yet".format(url))
            continue
        size = model.get("size") or 0
        on_gpu = 100 * (model.get("size_vram") or 0) // size if size else 0
        lines.append("{}: {}, context {}, {}% on GPU".format(
            url, model.get("name"), model.get("context_length", "unknown"), on_gpu))
    return "\n".join(lines)


def ask(arguments):
    prompt = arguments.get("prompt")
    if not prompt:
        raise ToolError("prompt is required")
    started = time.time()
    files = arguments.get("files") or []
    content = build_prompt(prompt, files)
    think = bool(arguments.get("think", False))
    record = {"rig": None, "model": None, "prompt_tokens": 0, "answer_tokens": 0, "file_bytes": files_size(files),
              "files": len(files), "think": think, "cut_off": False, "saved_tokens": 0}

    def failed(**extra):
        record["seconds"] = round(time.time() - started, 1)
        record.update(extra)
        log_call(record)

    try:
        url, model = find_rig()
    except ToolError:
        failed(error=True)
        raise
    record["rig"] = url
    record["model"] = model.get("name")

    context = model.get("context_length")
    if isinstance(context, int) and context > 0:
        estimate = int(len(content) / CHARS_PER_TOKEN)
        if estimate > context - RESERVED_ANSWER_TOKENS:
            failed(refused=True, estimate=estimate, context=context)
            raise ToolError(
                "About {} tokens would not fit the model's context of {}, and the model would lose part of it. "
                "Send less, or raise num_ctx in the rig's flight sheet.".format(estimate, context))

    messages = []
    if arguments.get("system"):
        messages.append({"role": "system", "content": arguments["system"]})
    messages.append({"role": "user", "content": content})

    # No num_ctx here: a different value than the rig's own would make Ollama reload the model
    payload = {
        "model": model["name"],
        "messages": messages,
        "stream": False,
        "think": think,
        "keep_alive": -1,
    }
    if arguments.get("max_tokens"):
        payload["options"] = {"num_predict": int(arguments["max_tokens"])}

    try:
        reply = request_json(url + "/api/chat", payload, ANSWER_TIMEOUT_SECONDS)
    except (urllib.error.URLError, OSError, ValueError) as error:
        failed(error=True)
        raise ToolError("The request to {} failed: {}".format(url, error))

    record["prompt_tokens"] = reply.get("prompt_eval_count") or 0
    record["answer_tokens"] = reply.get("eval_count") or 0
    record["saved_tokens"] = max(0, record["prompt_tokens"] - record["answer_tokens"])
    record["cut_off"] = reply.get("done_reason") == "length"
    answer = (reply.get("message") or {}).get("content", "")
    if not answer.strip():
        failed(error=True)
        raise ToolError("{} returned an empty answer (done_reason: {})".format(model["name"], reply.get("done_reason")))

    record["seconds"] = round(time.time() - started, 1)
    log_call(record)

    seconds = (reply.get("eval_duration") or 0) / 1e9
    produced = reply.get("eval_count") or 0
    rate = "{:.0f} tokens/s".format(produced / seconds) if seconds > 0 else "unknown speed"
    note = "\n\n[{} on {}: {} prompt tokens, {} answer tokens, {}".format(
        model["name"], url, reply.get("prompt_eval_count", "?"), produced, rate)
    if reply.get("done_reason") == "length":
        note += ", CUT OFF at the token limit"
    return answer + note + "]"


def row_id(*parts):
    """pc+project+date as a dashboard document id: the store allows only letters, digits and _-.~:@+ in one."""
    return "+".join(re.sub(r"[^A-Za-z0-9_.~:@-]", "_", part) for part in parts)


COUNTS = ("calls", "prompt_tokens", "answer_tokens", "saved_tokens", "file_bytes", "refusals", "errors")


def read_log():
    entries = []
    try:
        with open(stats_path(), "r", encoding="utf-8", errors="replace") as file:
            for line in file:
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if isinstance(entry, dict) and entry.get("ts"):
                    entries.append(entry)
    except OSError:
        pass
    return entries


def add_entry(totals, entry):
    totals["calls"] += 1
    for key in ("prompt_tokens", "answer_tokens", "saved_tokens", "file_bytes"):
        value = entry.get(key) or 0
        totals[key] += value if isinstance(value, int) else 0
    totals["refusals"] += 1 if entry.get("refused") else 0
    totals["errors"] += 1 if entry.get("error") else 0


def aggregate(days):
    """All-time totals, plus per project, per day and per pc|project|day (the dashboard's rows) for the last days.
    Days are the logging PC's local dates."""
    first_day = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
    totals = dict.fromkeys(COUNTS, 0)
    projects, dates, rows = {}, {}, {}
    for entry in read_log():
        add_entry(totals, entry)
        date = str(entry.get("day") or entry["ts"])[:10]
        if date < first_day:
            continue
        pc, project = entry.get("pc") or "?", entry.get("project") or "?"
        for table, key, fields in ((projects, project, {"project": project}), (dates, date, {"date": date}),
                                   (rows, row_id(pc, project, date),
                                    {"pc": pc, "project": project, "date": date})):
            if key not in table:
                table[key] = dict(fields, **dict.fromkeys(COUNTS, 0))
            add_entry(table[key], entry)
    return {
        "file": stats_path(), "days": days, "since": first_day, "totals": totals,
        "projects": sorted(projects.values(), key=lambda item: -item["saved_tokens"]),
        "dates": [dates[key] for key in sorted(dates)],
        "rows": [dict(rows[key], id=key) for key in sorted(rows)],
    }


def short(number):
    for size, suffix in ((1e9, "G"), (1e6, "M"), (1e3, "k")):
        if abs(number) >= size:
            return "{:.1f}{}".format(number / size, suffix)
    return str(number)


def describe(counts):
    text = "{} calls, {} read, {} answered, {} saved, {:.1f} MB files".format(
        counts["calls"], short(counts["prompt_tokens"]), short(counts["answer_tokens"]), short(counts["saved_tokens"]),
        counts["file_bytes"] / 1e6)
    if counts["refusals"]:
        text += ", {} refused".format(counts["refusals"])
    if counts["errors"]:
        text += ", {} errors".format(counts["errors"])
    return text


def stats(arguments):
    try:
        days = max(1, int(arguments.get("days") or STATS_DAYS))
    except (TypeError, ValueError):
        raise ToolError("days must be a whole number")
    summary = aggregate(days)
    if arguments.get("json"):
        return json.dumps(summary, separators=(",", ":"))
    if not summary["totals"]["calls"]:
        return "No calls logged yet in {}.".format(summary["file"])
    lines = ["All time: " + describe(summary["totals"]),
             "Since {} ({} days), by project:".format(summary["since"], days)]
    lines += ["  {}: {}".format(item["project"], describe(item)) for item in summary["projects"]] or ["  none"]
    lines.append("By day:")
    lines += ["  {}: {}".format(item["date"], describe(item)) for item in summary["dates"]] or ["  none"]
    return "\n".join(lines)


HANDLERS = {"local_llm_status": status, "local_llm_ask": ask, "local_llm_stats": stats}


def handle(message):
    """The response to one JSON-RPC message, or None for a notification."""
    method = message.get("method")
    request_id = message.get("id")
    if request_id is None:
        return None

    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        handler = HANDLERS.get(params.get("name"))
        if handler is None:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32602, "message": "Unknown tool: {}".format(params.get("name"))}}
        try:
            result = {"content": [{"type": "text", "text": handler(params.get("arguments") or {})}]}
        except ToolError as error:
            result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": "Method not found: {}".format(method)}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main():
    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        try:
            response = handle(json.loads(line.decode("utf-8")))
        except ValueError as error:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(error)}}
        if response is not None:
            sys.stdout.buffer.write(json.dumps(response).encode("utf-8") + b"\n")
            sys.stdout.buffer.flush()


def print_stats(argv):
    """--stats [days] [--json], which local-llm.ps1 stats runs."""
    numbers = [arg for arg in argv if arg.isdigit()]
    try:
        print(stats({"days": int(numbers[0]) if numbers else STATS_DAYS, "json": "--json" in argv}))
    except ToolError as error:
        print(error)
        return 1
    return 0


if __name__ == "__main__":
    if "--stats" in sys.argv[1:]:
        sys.exit(print_stats(sys.argv[1:]))
    main()
