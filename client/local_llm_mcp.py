#!/usr/bin/env python3
"""MCP server (stdio) that lets a Claude session delegate one question to Ollama on a rig on the LAN.

It reads the files itself and returns only the answer, so a file handed to the model never costs Claude the tokens of
reading it. Standard library only.

Environment:
  OLLAMA_URLS       Rigs to try in order, comma separated. Switching a rig's flight sheet takes it out of this list's
                    reach and the next one that has a model loaded is used.
  LOCAL_LLM_ROOTS   Folders files may be read from, separated by the OS path separator. Default: the working directory.
"""

import json
import os
import sys
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
]


class ToolError(Exception):
    pass


def urls():
    configured = os.environ.get("OLLAMA_URLS", "http://127.0.0.1:11434")
    return [url.strip().rstrip("/") for url in configured.split(",") if url.strip()]


def roots():
    configured = os.environ.get("LOCAL_LLM_ROOTS")
    folders = configured.split(os.pathsep) if configured else [os.getcwd()]
    return [os.path.realpath(folder) for folder in folders if folder]


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
    content = build_prompt(prompt, arguments.get("files"))
    url, model = find_rig()

    context = model.get("context_length")
    if isinstance(context, int) and context > 0:
        estimate = int(len(content) / CHARS_PER_TOKEN)
        if estimate > context - RESERVED_ANSWER_TOKENS:
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
        "think": bool(arguments.get("think", False)),
        "keep_alive": -1,
    }
    if arguments.get("max_tokens"):
        payload["options"] = {"num_predict": int(arguments["max_tokens"])}

    try:
        reply = request_json(url + "/api/chat", payload, ANSWER_TIMEOUT_SECONDS)
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise ToolError("The request to {} failed: {}".format(url, error))

    answer = (reply.get("message") or {}).get("content", "")
    if not answer.strip():
        raise ToolError("{} returned an empty answer (done_reason: {})".format(model["name"], reply.get("done_reason")))

    seconds = (reply.get("eval_duration") or 0) / 1e9
    produced = reply.get("eval_count") or 0
    rate = "{:.0f} tokens/s".format(produced / seconds) if seconds > 0 else "unknown speed"
    note = "\n\n[{} on {}: {} prompt tokens, {} answer tokens, {}".format(
        model["name"], url, reply.get("prompt_eval_count", "?"), produced, rate)
    if reply.get("done_reason") == "length":
        note += ", CUT OFF at the token limit"
    return answer + note + "]"


HANDLERS = {"local_llm_status": status, "local_llm_ask": ask}


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


if __name__ == "__main__":
    main()
