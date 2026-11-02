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

Run directly with --stats [days] [--json] it prints the usage summary instead of serving, and with
--calibrate <percent_used> [--reset <ISO> | --since <ISO>] [--json] it prices this PC's Claude Code usage (from the
transcripts under ~/.claude/projects) to find how many API dollars one percent of the weekly subscription limit is.
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

# USD per million tokens (input, output, cache read, cache write 5m): API list prices as of 2026-11-01, used only as a
# weighting to turn mixed-model token counts into one number for calibrating the subscription's weekly percent; the
# plan does not bill at these prices. The first row whose substring is in the model id wins, so specific ids come
# first. A 5-minute cache write is 1.25 x input (the last column); a 1-hour cache write is 2 x input
# (CACHE_WRITE_1H_FACTOR), priced from the input column when the transcript splits the writes by duration.
CLAUDE_PRICES = (
    (("fable",), (10.0, 50.0, 0.25, 12.5)),
    (("opus-5-5", "opus-5.5"), (4.0, 20.0, 0.20, 5.0)),
    (("opus",), (5.0, 25.0, 0.50, 6.25)),
    (("sonnet-5-5", "sonnet-5"), (2.0, 10.0, 0.20, 2.5)),
    (("sonnet",), (3.0, 15.0, 0.30, 3.75)),
    (("haiku-5-5",), (0.10, 0.50, 0.01, 0.125)),
    (("haiku",), (1.0, 5.0, 0.10, 1.25)),
)
UNKNOWN_MODEL_PRICE = (4.0, 20.0, 0.20, 5.0)  # Opus 5.5's
CACHE_WRITE_1H_FACTOR = 2.0
TERMS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
WEEK = datetime.timedelta(days=7)

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


def model_price(model):
    """The price row for a model id, and whether the id was recognised."""
    for names, price in CLAUDE_PRICES:
        if any(name in model for name in names):
            return price, True
    return UNKNOWN_MODEL_PRICE, False


def parse_time(text):
    """An ISO time (Z or an offset; none means UTC) as an aware UTC datetime. Raises ValueError."""
    text = text.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    # Python 3.8's fromisoformat takes neither "Z" nor more than 6 fraction digits
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    value = datetime.datetime.fromisoformat(text)
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc)


def iso(value):
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def transcript_files(folder, since_epoch):
    """The *.jsonl files under folder, subfolders included, changed since since_epoch: an older one holds nothing newer."""
    for current, _folders, names in os.walk(folder):
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(current, name)
            try:
                if os.path.getmtime(path) < since_epoch:
                    continue
            except OSError:
                continue
            yield path


def claude_usage(since, until):
    """Every assistant message's usage in Claude Code's transcripts between since and until, once per message.id
    (a streamed message is written as several lines that repeat its usage: the last line seen is kept).
    Returns ({message_id: (model, input, output, cache_read, cache_write_5m, cache_write_1h)}, skipped lines or
    files). Cache writes are split by duration from usage.cache_creation; without it they all count as 5-minute."""
    folder = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    messages, skipped = {}, 0
    for path in transcript_files(folder, since.timestamp()):
        try:
            with open(path, "rb") as file:
                for line in file:
                    # Most lines are tool results and user turns: skip them before paying for a JSON parse
                    if b'"usage"' not in line:
                        continue
                    try:
                        entry = json.loads(line.decode("utf-8"))
                        if entry.get("type") != "assistant":
                            continue
                        message = entry.get("message") or {}
                        usage = message.get("usage")
                        if not isinstance(usage, dict):
                            continue
                        stamp = parse_time(entry["timestamp"])
                        if stamp < since or stamp > until:
                            continue
                        key = message.get("id") or entry.get("uuid") or "{}#{}".format(path, len(messages))
                        split = usage.get("cache_creation")
                        if isinstance(split, dict) and ("ephemeral_5m_input_tokens" in split
                                                        or "ephemeral_1h_input_tokens" in split):
                            write_5m = int(split.get("ephemeral_5m_input_tokens") or 0)
                            write_1h = int(split.get("ephemeral_1h_input_tokens") or 0)
                        else:
                            write_5m, write_1h = int(usage.get("cache_creation_input_tokens") or 0), 0
                        messages[key] = (str(message.get("model") or "unknown"),
                                         int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0),
                                         int(usage.get("cache_read_input_tokens") or 0), write_5m, write_1h)
                    except (ValueError, KeyError, TypeError, AttributeError):
                        skipped += 1
        except OSError:
            skipped += 1
    return messages, skipped


def calibrate(percent_used, since=None, reset=None):
    """API-rate dollars of this PC's Claude Code usage in the window, and dollars per percent of the weekly limit."""
    if percent_used <= 0:
        raise ToolError("percent_used must be above 0")
    now = datetime.datetime.now(datetime.timezone.utc)
    if since is not None:
        window = "from --since"
    elif reset is not None:
        since = reset - WEEK
        window = "the week before the reset at {}".format(iso(reset))
    else:
        since = now - WEEK
        window = "the last 7 days: no --reset or --since given, pass the usage card's reset time for the real window"
    until = min(now, reset) if reset is not None and reset > since else now
    messages, skipped = claude_usage(since, until)
    by_model, by_term, unknown, total, counted = {}, dict.fromkeys(TERMS, 0.0), set(), 0.0, 0
    token_totals = dict.fromkeys(TERMS, 0)
    for model, *tokens in messages.values():
        if not any(tokens):
            continue  # "<synthetic>" error messages and the like
        price, known = model_price(model)
        if not known:
            unknown.add(model)
        rates = price + (price[0] * CACHE_WRITE_1H_FACTOR,)
        usd = 0.0
        for term, count, rate in zip(TERMS, tokens, rates):
            token_totals[term] += count
            by_term[term] += count * rate / 1e6
            usd += count * rate / 1e6
        by_model[model] = by_model.get(model, 0.0) + usd
        total += usd
        counted += 1
    # What a million tokens entering Claude's context really cost over the window: each is written to the cache once
    # and then re-read on every later turn of the session, so it is priced as (cache write + cache read dollars) per
    # million tokens written. That is the value of a million tokens the local model read instead, and what the
    # dashboard's price field (meta.price_per_m) should be set to.
    written = token_totals["cache_write_5m"] + token_totals["cache_write_1h"]
    read = token_totals["cache_read"]
    cache_usd = by_term["cache_write_5m"] + by_term["cache_write_1h"] + by_term["cache_read"]
    return {
        "since": iso(since), "until": iso(until), "window": window, "percent_used": percent_used,
        "usd_total": round(total, 2),
        "usd_by_model": {model: round(usd, 2) for model, usd in sorted(by_model.items(), key=lambda item: -item[1])},
        "usd_by_term": {term: round(usd, 2) for term, usd in by_term.items()},
        "cache_write_tokens": written, "cache_read_tokens": read,
        "reads_per_written_token": round(read / written, 2) if written else None,
        "usd_per_m_in_context": round(cache_usd / (written / 1e6), 2) if written else None,
        "messages": counted, "usd_per_pct": round(total / percent_used, 4),
        "unknown_models": sorted(unknown), "skipped": skipped,
    }


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


def option(argv, name):
    """The value after --name, or None when it is not given."""
    if name not in argv:
        return None
    index = argv.index(name)
    if index + 1 >= len(argv):
        raise ToolError("{} needs a value".format(name))
    return argv[index + 1]


def print_calibration(argv):
    """--calibrate <percent_used> [--reset <ISO> | --since <ISO>] [--json], which local-llm.ps1 calibrate runs."""
    try:
        rest = argv[argv.index("--calibrate") + 1:]
        if not rest or rest[0].startswith("--"):
            raise ToolError("Usage: --calibrate <percent_used> [--reset <ISO> | --since <ISO>] [--json]")
        try:
            percent = float(rest[0].rstrip("%"))
        except ValueError:
            raise ToolError("Not a percentage: {}".format(rest[0]))
        times = {}
        for name in ("--since", "--reset"):
            text = option(argv, name)
            if text is not None:
                try:
                    times[name] = parse_time(text)
                except ValueError:
                    raise ToolError("{} is not an ISO time: {}".format(name, text))
        result = calibrate(percent, times.get("--since"), times.get("--reset"))
    except ToolError as error:
        print(error)
        return 1
    if "--json" in argv:
        print(json.dumps(result, separators=(",", ":")))
        return 0
    print("Window: {} to {} ({})".format(result["since"], result["until"], result["window"]))
    print("{} messages, API-rate value by model:".format(result["messages"]))
    for model, usd in result["usd_by_model"].items():
        print("  {}: ${:,.2f}".format(model, usd))
    print("By term: " + ", ".join("{} ${:,.2f}".format(term, usd) for term, usd in result["usd_by_term"].items()))
    if result["cache_write_tokens"]:
        print("Context: {} tokens written to the cache, {} read back ({:.1f} reads per written token), so a million "
              "tokens entering Claude's context cost ${:,.2f} over the window, written once and re-read on every later "
              "turn. That is the value of a million tokens the local model read instead: set the dashboard's "
              "price_per_m to it.".format(short(result["cache_write_tokens"]), short(result["cache_read_tokens"]),
                                          result["reads_per_written_token"], result["usd_per_m_in_context"]))
    print("Total: ${:,.2f} for {:g}% used, so 1% is about ${:,.2f}".format(
        result["usd_total"], result["percent_used"], result["usd_per_pct"]))
    if result["unknown_models"]:
        print("Warning: unknown models, priced at Opus 5.5 rates: " + ", ".join(result["unknown_models"]))
    if result["skipped"]:
        print("Skipped {} unreadable lines or files.".format(result["skipped"]))
    return 0


if __name__ == "__main__":
    if "--calibrate" in sys.argv[1:]:
        sys.exit(print_calibration(sys.argv[1:]))
    if "--stats" in sys.argv[1:]:
        sys.exit(print_stats(sys.argv[1:]))
    main()
