#!/usr/bin/env python3
"""The code-writing pipeline behind the local_llm_code tool: a change request and the files it applies to in, the
changed code and a report out. Three stages around the model, each there to stop it inventing names:

  1. Context: the declarations (signatures, no bodies) of what the change can call are attached to the prompt: the
     types of the files themselves, the project types the request and code name, the declared types of the members
     the code uses, their base types, the compiled APIs (Unity, Fusion, packages, .NET) the code names, and what the
     model itself asks to see in one ask-first pass (`NEED: Fusion.NetworkObject`, `NEED: how a death is announced`).
  2. Compile and retry: the answer is spliced into a scratch copy and compiled as the whole assembly; on errors, one
     more try with the compiler's messages and the declarations of every type they name.
  3. Several tries: N tries are sent at once and each is compiled; the first that compiles is returned, or the one
     with the fewest errors, marked as not compiling.

A compile check catches invented names, not wrong behaviour: the report says which tries compiled and how they
differ, and the caller still reviews the answer.

`run` is the pipeline on a prepared task (the held-out test calls it with its own splicing); `tool` is the MCP tool,
which prepares the task from files on disk. The model is reached only through the `send` function passed in
(local_llm_mcp.send), so this module holds no rig logic. Standard library only.
"""

import collections
import concurrent.futures
import difflib
import hashlib
import os
import random
import re
import shutil
import time

import code_compile
import code_index

DEFAULT_SYSTEM = (
    "You write C# for a Unity project. You are given a change request and the code it applies to: either a whole file "
    "or the parts of it involved. Answer with that code after the change, each file in its own ```csharp block whose "
    "first line is `// FILE: <name>`: the whole file when you were given the whole file, otherwise only the excerpts "
    "you were given, in the same order, separated by `// ...` lines. Use only APIs you can see or Unity's and .NET's "
    "public API, and match the surrounding style.")
ASK_SYSTEM = "You are preparing to change C# code in a Unity project. You do not write the code yet."
ASK_INSTRUCTIONS = (
    "Do not write the change yet. First list what else you would need to see so that you do not have to guess a name "
    "or how something works: at most {limit} lines, most important first, each one of\n"
    "NEED: <Type>            the members of a type that is not shown above\n"
    "NEED: <Type>.<Member>   the code of a method or field of this project that is not shown above, or the exact "
    "signature of a Unity, Fusion or package member\n"
    "NEED: <a few words>     something whose name you do not know, e.g. NEED: how the player's death is announced\n"
    "Ask only for what this change needs and is not shown above; one name per line, no explanations. "
    "If you need nothing more, answer NEED: nothing. Answer with the NEED lines only.")
PROJECT_INTRO = ("Declarations of the project types involved (signatures only, bodies left out). Use these names "
                 "exactly; a member that is not listed here or in the code above does not exist:")
API_INTRO = ("Unity, Fusion and package APIs involved, as compiled into this project (public members; names only where "
             "marked). A member not listed for a type is not declared on it (it may be inherited from the base type "
             "named, unless the list ends in `more members`):")
NEED_INTRO = ("Also from this project and its libraries, looked up for this change (declarations, and the code of "
              "some members):")

SEPARATOR = "// ..."
BLOCK = re.compile(r"```(?:csharp|cs|c#)?[ \t]*\n(.*?)\n```", re.S)
FILE_LINE = re.compile(r"\s*//\s*FILE:\s*(\S+)")
PROJECT_BUDGET = 9000        # characters of project declarations attached up front
OWN_TYPE_BUDGET = 3600
TYPE_BUDGET = 1800
API_BUDGET = 3500            # characters of compiled-API member lists attached up front
API_TYPE_BUDGET = 700
NEED_BUDGET = 7000           # characters attached from the ask-first pass
BODY_BUDGET = 1500           # characters of one member's code
NEED_LIMIT = 6
RETRY_BUDGET = 5000          # characters of declarations attached to a retry
MAX_ERRORS = 12
ASK_MAX_TOKENS = 400
WHOLE_FILE_CHARS = 16000     # a larger file must be sent as line ranges
DEFAULT_TRIES = 3
MAX_TRIES = 8
KEPT_RUNS = 20
# Types every model knows, or that say nothing about a change: attached only when asked for or named by an error
COMMON = set("""Object GameObject Transform MonoBehaviour Component Behaviour ScriptableObject Vector2 Vector3 Vector4
    Vector2Int Vector3Int Quaternion Color Color32 Debug Time List Dictionary HashSet Queue Stack IEnumerator IEnumerable
    IList ICollection IDictionary KeyValuePair Action Func Coroutine Exception Type Attribute Array Nullable Task String
    Boolean Int32 Single Double Enum Delegate EventArgs IDisposable WaitForSeconds WaitForEndOfFrame WaitUntil Tuple
    Nullable Predicate Comparison StringBuilder Regex Linq Enumerable Text UI Events Collections Generic System
    UnityEngine Fusion Rendering""".split())


# The namespaces a new file is taken to import, when there is no file yet to read usings from
FALLBACK_NAMESPACES = ["UnityEngine", "UnityEngine.UI", "UnityEngine.Events", "Fusion", "TMPro", "System",
                       "System.Collections.Generic"]


class PipelineError(Exception):
    pass


# ---------------------------------------------------------------- answers

def code_blocks(text):
    """The fenced code blocks of an answer: those after the last </think> when thinking leaked into it."""
    after = text[text.rfind("</think>") + 8:] if "</think>" in text else text
    found = BLOCK.findall(after) or BLOCK.findall(text)   # a stray </think> after the code must not hide it
    return [block.strip("\n") for block in found]


def segments(code):
    """The excerpts of a block: its text split at `// ...` lines, empty pieces dropped."""
    found, current = [], []
    for line in code.split("\n"):
        if line.strip() == SEPARATOR:
            found.append(current)
            current = []
        else:
            current.append(line)
    found.append(current)
    return ["\n".join(piece).strip("\n") for piece in found if "".join(piece).strip()]


def normalise(answer, parts):
    """(values, None) or (None, "format: ..."). values has one entry per part, in order: a list of excerpts for an
    excerpts part, the file's text for a whole or new file. Forgiving where the intent is clear: blocks are matched
    to files by their `// FILE:` line, a file answered twice counts once (the last), and one file's excerpts split
    over several blocks are joined; a given file with no block at all is taken as left unchanged (part["shown"])."""
    blocks = code_blocks(answer)
    if not blocks:
        return None, "format: no code block in the answer"
    by_name = dict((part["name"].lower(), at) for at, part in enumerate(parts))
    labelled, unlabelled = collections.defaultdict(list), []
    for block in blocks:
        first, _newline, rest = block.partition("\n")
        match = FILE_LINE.match(first)
        if match:
            at = by_name.get(os.path.basename(match.group(1).replace("\\", "/")).lower())
            if at is not None:
                labelled[at].append(rest)
            elif len(parts) == 1:
                labelled[0].append(rest)     # one file was asked for: a misspelt name is still that file
        else:
            unlabelled.append(block)
    # Blocks without a FILE line stand for the files that have none, in order
    missing = [at for at in range(len(parts)) if at not in labelled]
    if missing and unlabelled:
        if len(missing) == 1:
            labelled[missing[0]] = unlabelled
        elif len(unlabelled) == len(missing):
            for at, block in zip(missing, unlabelled):
                labelled[at] = [block]
    if not labelled:
        return None, "format: no code block for {} ({} blocks for {} files)".format(parts[0]["name"], len(blocks), len(parts))
    values = []
    for at, part in enumerate(parts):
        given = labelled.get(at)
        if not given:
            # A file given but not answered, while others were, is a file the model left as it is
            if part.get("shown") is not None:
                values.append(part["shown"])
                continue
            return None, "format: no code block for {} ({} blocks for {} files)".format(part["name"], len(blocks), len(parts))
        if part["kind"] != "excerpts":
            values.append(given[-1].strip("\n") + "\n")
            continue
        want = part["segments"]
        last, every = segments(given[-1]), [piece for block in given for piece in segments(block)]
        if len(last) == want:
            values.append(last)
        elif len(every) == want:
            values.append(every)
        elif len(given) > 1 and len(every) > want and len(every) % want == 0:
            values.append(every[-want:])
        else:
            return None, "format: {} excerpts for the {} given of {}".format(len(last), want, part["name"])
    return values, None


def canonical(values, parts):
    """The answer in the one agreed layout: a block per file, FILE line first, excerpts separated by `// ...`."""
    blocks = []
    for value, part in zip(values, parts):
        code = ("\n" + SEPARATOR + "\n").join(value) if isinstance(value, list) else value.rstrip("\n")
        blocks.append("```csharp\n// FILE: {}\n{}\n```".format(part["name"], code))
    return "\n\n".join(blocks)


def squeeze(text):
    return [" ".join(line.split()) for line in text.split("\n") if line.strip()]


# ---------------------------------------------------------------- stage 1: context

def split_body(body):
    """(prose, code) of a request: the text outside its fenced blocks, and inside them."""
    code = "\n".join(BLOCK.findall(body))
    return BLOCK.sub("\n", body), code


TYPE_USE = re.compile(r"(?<![\w.])(?:(new)\s+)?([A-Z]\w*)\b(\s*\()?")


def type_names(code):
    """The capitalised names code uses as types, most used first: not a name after a dot (a member) and not one
    called like a method (unless after `new`); comments and strings are not read."""
    try:
        clean = code_index.blank(code)
    except Exception:
        clean = code
    counts = collections.Counter(
        match.group(2) for match in TYPE_USE.finditer(clean) if match.group(1) or not match.group(3))
    return [name for name, _count in counts.most_common()]


def prose_names(prose):
    """The names a request's prose gives: anything in backticks, and words shaped like identifiers (two capitals or
    an underscore: EntityRespawnReset, Light_Base, DebugX), in order. A plain capitalised word is not one."""
    found = []
    for quoted in re.findall(r"`([^`\n]+)`", prose):
        found += [name for name in re.findall(r"[A-Za-z_]\w*", quoted) if name[0].isupper()]
    found += re.findall(r"\b[A-Z][a-z0-9]+(?:[A-Z_][A-Za-z0-9_]*)+\b", prose)
    return list(dict.fromkeys(found))


class Context(object):
    """What stage 1 knows about one task: the two indexes, the namespaces in scope and the types of the task's files."""

    def __init__(self, project, parts, cache_folder, use_api=True, overlay=None, overlay_key=None):
        self.project, self.parts, self.overlay = project, parts, overlay or {}
        self.source = code_index.source_index(project, cache_folder, overlay, overlay_key)
        paths = [part["path"] for part in parts]
        self.api, self.note = None, None
        if use_api:
            try:
                self.api = code_index.api_index(project, code_compile.rsp_of(paths, project), cache_folder)
                self.note = self.api.note
            except (code_compile.CompileError, OSError, ValueError) as error:
                self.note = "compiled APIs not indexed: {}".format(error)
        self.namespaces, self.own = [], collections.OrderedDict()
        for part in parts:
            text = part.get("text")
            if not text:
                continue
            self.namespaces += code_index.usings(text)
            if part["kind"] == "excerpts":       # a whole file is all there already; a new file has nothing yet
                try:
                    found = code_index.signatures(text)
                except Exception:
                    found = {}
                for name, entry in found.items():
                    self.own[name] = dict(entry, path=part["path"])
        self.own_paths = set(paths)

    def project_type(self, name):
        entry = self.source.get(name)
        return entry if entry and entry["path"] not in self.own_paths else None

    def api_type(self, name, strict=False):
        """A compiled type by name. strict: only what the files' own usings bring into scope (for names picked up
        from code; a name the model or the compiler gave is looked up wherever it is)."""
        if not self.api:
            return None
        return self.api.get(name, self.namespaces or FALLBACK_NAMESPACES, strict=strict)

    def source_text(self, name):
        """(text, path) of the file that declares a project type: the task's own copy for the files' own types."""
        if name in self.own:
            path = self.own[name]["path"]
            for part in self.parts:
                if part["path"] == path:
                    return part.get("text"), path
        entry = self.project_type(name)
        if not entry:
            return None, None
        if entry["path"] in self.overlay:
            return self.overlay[entry["path"]], entry["path"]
        try:
            return code_index.read_text(os.path.join(self.project, entry["path"])), entry["path"]
        except OSError:
            return None, None

    def shadowed(self, name):
        """Whether the files' usings give this name to a .NET or Unity type: then a project type that happens to
        share the name (a third-party `Dictionary`, an `Image`) is not what the code means."""
        entry = self.api_type(name, strict=True)
        return bool(entry and entry["full"].startswith(("System.", "UnityEngine.", "UnityEditor.", "TMPro.")))

    def is_attribute(self, entry):
        return any(base.endswith("Attribute") for base in entry.get("b", []))


def select(context, body):
    """The declarations attached up front: (project blocks, API blocks, attached) where attached lists what was
    chosen, for the report. Order, most relevant first, each group within its budget: the task's own types in full;
    project types the request and code name; the declared types of the own members the code uses; base types; then
    the compiled types the files inherit from and the code names, as member-name lists."""
    prose, code = split_body(body)
    used = set(re.findall(r"[A-Za-z_]\w*", code))
    after_dot = set(re.findall(r"\.\s*([A-Za-z_]\w*)", code))
    own_members = set(code_index.member_name(signature) for entry in context.own.values() for signature in entry["members"])
    in_code = [name for name in type_names(code) if name not in own_members]
    named = list(dict.fromkeys(in_code + prose_names(prose)))
    member_types, bases = [], []
    for name, entry in context.own.items():
        bases += code_index.bases_of(entry["head"])
        for signature in entry["members"]:
            if code_index.member_name(signature) in used:
                member_types += [found for found in type_names(signature.split("(")[0]) + type_names(
                    signature.partition("(")[2]) if found != code_index.member_name(signature)]
    own_bases = list(dict.fromkeys(bases))
    for name in named[:12]:
        entry = context.project_type(name)
        if entry:
            bases += code_index.bases_of(entry["head"])
    ordered = list(dict.fromkeys(named + member_types + bases))

    attached = {"own": [], "project": [], "api": [], "left_out": []}
    blocks, spent = [], 0
    for name, entry in context.own.items():
        block = code_index.render_source(name, entry, everything=True, budget=OWN_TYPE_BUDGET, wanted=used)
        if spent + len(block) > PROJECT_BUDGET and blocks:
            attached["left_out"].append(name)
            continue
        blocks.append(block)
        spent += len(block)
        attached["own"].append(name)
    for name in ordered:
        entry = context.project_type(name) if name not in context.own and name not in COMMON else None
        if not entry or context.shadowed(name):
            continue
        block = code_index.render_source(name, entry, budget=TYPE_BUDGET, wanted=after_dot | used)
        if spent + len(block) > PROJECT_BUDGET:
            attached["left_out"].append(name)
            continue
        blocks.append(block)
        spent += len(block)
        attached["project"].append(name)

    api_blocks, api_spent = [], 0
    if context.api:
        # What the files' types inherit from comes first (inherited members are the ones most often guessed), with
        # one more level of base; then the types the code names, then those of the members it uses
        inherited = []
        for name in own_bases:
            entry = context.api_type(name, strict=True) if not context.source.get(name) else None
            if entry and name not in COMMON:
                inherited += [name] + [base for base in entry.get("b", [])
                                       if base not in COMMON and not re.match(r"I[A-Z]", base)]
        for name in dict.fromkeys(inherited + in_code + prose_names(prose) + member_types + bases):
            simple = name.split(".")[-1]
            if simple in COMMON or name in context.own or (context.source.get(simple) and not context.shadowed(simple)):
                continue
            entry = context.api_type(name, strict=True)
            if not entry or context.is_attribute(entry) or entry["full"] in attached["api"]:
                continue
            block = code_index.render_api(entry, budget=API_TYPE_BUDGET, wanted=after_dot, names_only=True)
            if api_spent + len(block) > API_BUDGET:
                attached["left_out"].append(entry["full"])
                continue
            api_blocks.append(block)
            api_spent += len(block)
            attached["api"].append(entry["full"])
    return blocks, api_blocks, attached


def parse_needs(answer, limit=NEED_LIMIT):
    found = []
    for line in answer.split("\n"):
        match = re.match(r"\s*(?:[-*]\s*)?NEED:\s*(.+?)\s*$", line)
        if match:
            need = match.group(1).strip("`'\" .")
            if need and need.lower() not in ("nothing", "none", "n/a") and need not in found:
                found.append(need)
    return found[:limit]


def resolve_need(context, need, already):
    """[(label, block or None)] for one NEED line. `already` holds the labels attached so far, so nothing is attached
    twice; a block of None is a note for the report (already attached).

    A line that starts with a name either index knows is that name, whatever commentary follows it: a type gives its
    members, Type.Member the code of that member for a project type (its signature is attached already, so the body is
    what is missing) or its full signatures for a compiled one. Anything else is a description: the names in it that
    resolve are attached, a "quoted literal" is searched for in the project's source, and only when neither finds
    anything are its words matched against the project's type and member names."""
    found = []

    def add(label, block):
        if label in already:
            if not found:
                found.append((label + " (already attached)", None))
        else:
            found.append((label, block))
            already.add(label)

    def is_project(name):
        return name in context.own or (context.project_type(name) is not None and not context.shadowed(name))

    def add_project(name, wanted=()):
        entry = context.own.get(name) or context.project_type(name)
        add("project " + name, code_index.render_source(name, entry, everything=name in context.own,
                                                        budget=TYPE_BUDGET, wanted=wanted))

    def add_api(entry, wanted=()):
        add("api " + entry["full"], code_index.render_api(entry, budget=TYPE_BUDGET, wanted=wanted))

    def add_code(type_name, member):
        text, path = context.source_text(type_name)
        code = code_index.member_source(text, type_name, member, BODY_BUDGET) if text else None
        if code:
            add("code of {}.{}".format(type_name, member), "// {}: {}.{}\n{}".format(path, type_name, member, code))
        return bool(code)

    def exact(name, wanted=()):
        """Attaches what a name stands for; False when neither index knows it."""
        pieces = [piece for piece in re.sub(r"[<(].*$", "", name).split(".") if piece]
        # The type is the longest leading run of the name that either index knows; what follows is a member
        for cut in range(len(pieces), 0, -1):
            dotted, members = ".".join(pieces[:cut]), pieces[cut:]
            entry = context.api_type(dotted) if pieces[cut - 1] not in COMMON or members else None
            if is_project(pieces[cut - 1]):
                if not (members and add_code(pieces[cut - 1], members[0])):
                    add_project(pieces[cut - 1], list(members) + list(wanted))
                # A Unity or Fusion type of the same name (the project's own `Volume` and Unity's): the model may
                # mean either, so both are shown
                if entry and cut == 1 and entry["full"].startswith(("UnityEngine.", "Fusion.")):
                    add_api(entry, list(members) + list(wanted))
                return True
            if entry:
                add_api(entry, list(members) + list(wanted))
                return True
        # Not a type: a member of the files' own types gives its code, of another project type that type
        if len(pieces) == 1:
            owners = [owner for owner in context.own if any(
                code_index.member_name(signature) == pieces[0] for signature in context.own[owner]["members"])]
            if owners:
                add_code(owners[0], pieces[0])
                return True
        return False

    def literals():
        """A "quoted literal" in the need: the project types whose source has it, with the line."""
        # The task's own files are left out of the searches: they are in the prompt already (and in the held-out test
        # the checkout's copy holds the accepted fix)
        for literal in re.findall(r'"([^"\n]{3,40})"', need)[:2]:
            for path, line in code_index.search_literal(context.project, context.source, literal, context.own_paths, limit=2,
                                                         overlay=context.overlay):
                declared = [name for name, entry in context.source.types.items() if entry["path"] == path]
                in_line = re.findall(r"[A-Za-z_]\w*", line)
                owner = ([name for name in declared if any(
                    code_index.member_name(signature) in in_line for signature in context.source.types[name]["members"])]
                    or sorted(declared, key=lambda name: -len(context.source.types[name]["members"])))[:1]
                for name in owner:
                    add("project " + name, "// {} has: {}\n{}".format(path, line.strip()[:200], code_index.render_source(
                        name, context.source.types[name], budget=TYPE_BUDGET, wanted=in_line)))

    literals()
    head = re.match(r"\s*`?([A-Za-z_][\w.]*)`?(.*)$", need)
    if head and (head.group(1)[0].isupper() or "." in head.group(1)) and exact(head.group(1)):
        # Members of that type named in the commentary: their code too
        type_name = head.group(1).split(".")[0]
        if type_name in context.own or context.project_type(type_name):
            entry = context.own.get(type_name) or context.project_type(type_name)
            members = set(code_index.member_name(signature) for signature in entry["members"])
            for name in list(dict.fromkeys(re.findall(r"[A-Za-z_]\w*", head.group(2))))[:8]:
                if name in members and len(found) < 3:
                    add_code(type_name, name)
        return found

    words = code_index.query_words(need)
    names = prose_names(need) + re.findall(r"\b[A-Z][A-Za-z0-9_]+\b", re.sub(r'"[^"]*"', " ", need))
    for name in list(dict.fromkeys(names))[:6]:
        if name not in COMMON and len(found) < 3:
            exact(name, words)
    if not found:
        for name, members in code_index.search_source(context.source, need, limit=6):
            if context.project_type(name) and len(found) < 2:
                add_project(name, members)
    return found


def ask_first(context, body, declarations, attached, system, chat, calls, think=True):
    """The one ask-first pass: the model reads the request, the code and what is attached so far, and says what else
    it needs. Returns (blocks, needs) where needs is [(NEED text, [labels attached] or [])]."""
    prompt = body + declarations + "\n\n" + ASK_INSTRUCTIONS.format(limit=NEED_LIMIT)
    try:
        reply = chat(ASK_SYSTEM, prompt, think, None if think else ASK_MAX_TOKENS, "ask", calls)
    except Exception as error:
        return [], [("ask-first pass failed: {}".format(str(error)[:160]), [])]
    already = set(["project " + name for name in attached["own"] + attached["project"]])
    blocks, needs, spent = [], [], 0
    for need in parse_needs(reply["answer"]):
        labels = []
        for label, block in resolve_need(context, need, already):
            if block is None:
                labels.append(label)
                continue
            if spent + len(block) > NEED_BUDGET:
                labels.append(label + " (left out: budget)")
                already.discard(label)
                continue
            blocks.append(block)
            spent += len(block)
            labels.append(label)
        needs.append((need, labels))
    return blocks, needs


def declarations_text(project_blocks, api_blocks, need_blocks):
    text = ""
    for intro, blocks in ((PROJECT_INTRO, project_blocks), (API_INTRO, api_blocks), (NEED_INTRO, need_blocks)):
        if blocks:
            text += "\n\n" + intro + "\n```csharp\n" + "\n\n".join(blocks) + "\n```"
    return text


# ---------------------------------------------------------------- stage 2: compile and retry

def error_names(errors):
    """The quoted names in compiler messages, simple names last-part first: (type or member names, in order)."""
    names = []
    for error in errors:
        for quoted in re.findall(r"'([^']+)'", error):
            names += re.findall(r"[A-Za-z_]\w*", re.sub(r"\(.*\)", "", quoted))
    return list(dict.fromkeys(names))


def retry_prompt(context, user, answer, check):
    """The first prompt, the answer, why it failed and the real declarations of what the failure names."""
    errors = check.get("errors") or []
    blocks = code_blocks(answer)
    previous = "\n".join("```csharp\n{}\n```".format(block) for block in blocks) if blocks else answer[-3000:]
    if check["status"] == "format":
        return (user + "\n\nYour previous answer:\n" + previous + "\n\nIt is not in the format asked for ("
                + check.get("detail", "format") + "). Answer again, complete: one ```csharp block per file, its first "
                "line `// FILE: <name>`, with exactly the excerpts you were given, in the same order, separated by "
                "`// ...` lines.")
    names = error_names(errors)
    unknown = set(error_names([error for error in errors if re.search(r"CS0(103|246|234)\b", error)]))
    blocks, spent, shown = [], 0, set()
    if context is not None:
        if any("CS0103" in error or "CS0117" in error or "CS1061" in error for error in errors):
            for name, entry in context.own.items():
                block = code_index.render_source(name, entry, everything=True, budget=TYPE_BUDGET, wanted=names)
                if spent + len(block) <= RETRY_BUDGET:
                    blocks.append(block)
                    spent += len(block)
                    shown.add(name)
        for name in names:
            if name in shown:
                continue
            entry = context.project_type(name)
            if entry:
                block = code_index.render_source(name, entry, budget=TYPE_BUDGET, wanted=names)
            else:
                # A name the compiler could not find at all may be a type whose using is missing: looked up
                # anywhere. Any other name is a type only if the files' usings make it one
                entry = context.api_type(name, strict=name not in unknown)
                block = code_index.render_api(entry, budget=TYPE_BUDGET, wanted=names) if entry else None
            if block and spent + len(block) <= RETRY_BUDGET:
                blocks.append(block)
                spent += len(block)
                shown.add(name)
    short = [re.sub(r"^.*?\((\d+),\d+\): ", r"line \1: ", error)[:260] for error in errors[:MAX_ERRORS]]
    if len(errors) > MAX_ERRORS:
        short.append("... and {} more errors".format(len(errors) - MAX_ERRORS))
    # A type that exists in a namespace the file does not import: say so, since excerpts cannot add a using
    for name in sorted(unknown) if context is not None else []:
        declared = context.project_type(name)
        if declared:
            namespace = declared.get("ns") or ""
        else:
            entry = context.api_type(name) or context.api_type(name + "Attribute")
            namespace = entry["full"].rsplit(".", 1)[0] if entry and "." in entry["full"] else ""
        if namespace and namespace not in context.namespaces:
            if any(part["kind"] == "excerpts" for part in context.parts):
                short.append("`{0}` is in namespace {1}, which this file does not import, and the using lines are not "
                             "among the excerpts: write `{1}.{0}`.".format(name, namespace))
            else:
                short.append("`{0}` is in namespace {1}: the file needs `using {1};`.".format(name, namespace))
    return (user + "\n\nYour previous answer:\n" + previous + "\n\nIt does not compile:\n" + "\n".join(short)
            + ("\n\nThe real declarations of the types involved (signatures only):\n```csharp\n" + "\n\n".join(blocks)
               + "\n```" if blocks else "")
            + "\n\nAnswer again, complete and in the same format, using only names that exist.")


# ---------------------------------------------------------------- the pipeline

def make_chat(send):
    """chat(system, user, think, max_tokens, kind, calls) -> the reply, logged in calls. A reply that comes back empty
    because thinking used the whole context (done_reason: length) is asked for once more with thinking off."""
    def chat(system, user, think, max_tokens, kind, calls):
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]

        def one(thinking, label):
            started = time.time()
            reply = send(messages, think=thinking, max_tokens=max_tokens, empty_ok=True)
            calls.append({"kind": label, "prompt_tokens": reply.get("prompt_tokens") or 0,
                          "answer_tokens": reply.get("answer_tokens") or 0, "seconds": round(time.time() - started, 1),
                          "model": reply.get("model"), "rig": reply.get("url"), "done_reason": reply.get("done_reason")})
            return reply

        reply = one(think, kind)
        if not (reply.get("answer") or "").strip():
            if think and reply.get("done_reason") == "length":
                reply = one(False, kind + " (thinking off after an empty answer)")
                reply["think_off"] = True
            if not (reply.get("answer") or "").strip():
                raise PipelineError("empty answer (done_reason: {})".format(reply.get("done_reason")))
        return reply
    return chat


def run(body, parts, project, send, cache_folder, check, system=None, tries=DEFAULT_TRIES, retry=True,
        ask=True, ask_think=True, use_api=True, use_context=True, think=True, retry_all=False, progress=None,
        overlay=None, overlay_key=None):
    """The pipeline on one prepared task.

    body     the change request followed by the code, as the model should read it (no declarations)
    parts    [{"kind": excerpts|whole|new, "path", "name", "segments": count for excerpts, "text": the file before
             the change or None, "shown": the code as given (a list of excerpts, or the file's text)}], in the order
             of the code in body
    check    check(values, scratch name) -> {"status": compiles|errors|format|not checkable, "errors": [...],
             "detail"}: splices one normalised answer and compiles it
    retry_all  retry every failing try even when another try compiled (for measuring the stages; costs tokens)
    overlay    {path: text or None}: project files to index and search in this state instead of the one on disk
               (the held-out test: the code before the task), overlay_key naming the state

    Returns {"tries": [...], "chosen": index or None, "context": {...}, "calls": [...], "prompt": the user message}.
    Each try: {"answer" (canonical, or raw when the format failed), "status", "errors", "values", "first": the try
    before its retry or None, "retry": the retry itself (the try is the better of the two)}."""
    started = time.time()
    calls, chat = [], make_chat(send)
    system = DEFAULT_SYSTEM if system is None else system
    note = lambda text: progress(text) if progress else None

    context, report = None, {"own": [], "project": [], "api": [], "left_out": [], "needs": [], "note": None}
    user = body
    if use_context:
        context = Context(project, parts, cache_folder, use_api=use_api, overlay=overlay, overlay_key=overlay_key)
        project_blocks, api_blocks, attached = select(context, body)
        report.update(attached, note=context.note)
        need_blocks = []
        if ask:
            need_blocks, report["needs"] = ask_first(context, body, declarations_text(project_blocks, api_blocks, []),
                                                     attached, system, chat, calls, think=ask_think)
        user = body + declarations_text(project_blocks, api_blocks, need_blocks)
        note("context: {} own, {} project, {} api, {} asked for".format(
            len(attached["own"]), len(attached["project"]), len(attached["api"]), len(need_blocks)))

    def attempt(at, prompt, kind):
        """One model call, normalised and checked."""
        result = {"at": at, "kind": kind, "status": "no answer", "errors": [], "answer": "", "raw": "", "values": None}
        try:
            reply = chat(system, prompt, think, None, "{} {}".format(kind, at + 1), calls)
        except Exception as error:
            result["detail"] = str(error)[:300]
            return result
        result["raw"] = reply["answer"]
        result["cut_off"] = bool(reply.get("cut_off"))
        result["think_off"] = bool(reply.get("think_off"))
        values, problem = normalise(reply["answer"], parts)
        if problem:
            result.update(status="format", detail=problem, answer=reply["answer"])
            return result
        result.update(values=values, answer=canonical(values, parts))
        try:
            result.update(check(values, "{}{}".format("retry" if kind == "retry" else "try", at + 1)))
        except code_compile.CompileError as error:
            result.update(status="not checkable", detail=str(error)[:300], errors=[])
        note("{} {}: {}".format(kind, at + 1, result["status"]))
        return result

    tries = max(1, min(MAX_TRIES, int(tries)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=tries) as pool:
        firsts = list(pool.map(lambda at: attempt(at, user, "try"), range(tries)))
        results = [dict(first, first=None) for first in firsts]
        failing = [first for first in firsts if first["status"] in ("errors", "format")]
        if retry and failing and (retry_all or not any(first["status"] == "compiles" for first in firsts)):
            def again(first):
                return attempt(first["at"], retry_prompt(context, user, first["raw"], first), "retry")
            for second in pool.map(again, failing):
                first = firsts[second["at"]]
                # A retry that is no better than what it retried (more errors, or no code at all) is not kept
                worse = second["status"] != "compiles" and error_count(first) <= error_count(second)
                results[second["at"]] = dict(first if worse else second, first=first, retry=second)

    return {"tries": results, "chosen": choose(results), "context": report, "calls": calls, "prompt": user,
            "seconds": round(time.time() - started, 1)}


def error_count(result):
    if result["status"] == "errors":
        return len(result["errors"])
    return {"compiles": 0, "not checkable": 0}.get(result["status"], 10 ** 6)


def choose(results):
    """The try to return: the first that compiled without a retry, else the first that compiled after one, else (none
    compiles) the one with the fewest errors; an answer that could not be checked counts as no errors found. None when
    no try gave code."""
    usable = [result for result in results if result["values"] is not None]
    if not usable:
        return None
    best = min(usable, key=lambda result: (result["status"] != "compiles", result["status"] == "compiles" and
                                           result["first"] is not None, error_count(result), result["at"]))
    return best["at"]


def differences(results, chosen):
    """How the other compiling tries differ from the chosen one: a line per try."""
    lines = []
    base = squeeze(results[chosen]["answer"])
    for result in results:
        if result["at"] == chosen or result["status"] != "compiles":
            continue
        other = squeeze(result["answer"])
        if other == base:
            lines.append("try {} is the same code".format(result["at"] + 1))
            continue
        removed = added = 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, other, autojunk=False).get_opcodes():
            if tag != "equal":
                removed += i2 - i1
                added += j2 - j1
        lines.append("try {} differs in {} of the chosen answer's {} lines (it has {} lines there instead)".format(
            result["at"] + 1, removed, len(base), added))
    return lines


def describe_try(result):
    def one(item):
        text = item["status"]
        if item["status"] == "errors":
            text += " ({})".format(len(item["errors"]))
        if item.get("think_off"):
            text += ", thinking off"
        if item.get("cut_off"):
            text += ", cut off"
        return text
    if result["first"] is not None:
        retry = result.get("retry") or result
        return "try {}: {} -> retry: {}{}".format(
            result["at"] + 1, one(result["first"]), one(retry),
            " (no better: first answer kept)" if result["status"] != "compiles" and result["raw"] == result["first"]["raw"] else "")
    return "try {}: {}".format(result["at"] + 1, one(result))


def totals(calls):
    return (sum(call["prompt_tokens"] for call in calls), sum(call["answer_tokens"] for call in calls))


# ---------------------------------------------------------------- the MCP tool

def parse_ranges(spec, count):
    """[(first, last)] 1-based inclusive line ranges from "120-180, 300-340", in order and not overlapping."""
    ranges = []
    for piece in str(spec).split(","):
        match = re.match(r"^\s*(\d+)\s*(?:-\s*(\d+))?\s*$", piece)
        if not match:
            raise PipelineError("lines must look like \"120-180, 300-340\": got \"{}\"".format(spec))
        first, last = int(match.group(1)), int(match.group(2) or match.group(1))
        if first < 1 or last < first or last > count:
            raise PipelineError("lines {}-{} are outside the file's {} lines".format(first, last, count))
        ranges.append((first, last))
    ranges.sort()
    if any(ranges[at][0] <= ranges[at - 1][1] for at in range(1, len(ranges))):
        raise PipelineError("line ranges overlap: {}".format(spec))
    return ranges


def prepare(request, files, project):
    """(body, parts) for the files of one call: each a path, or {"path", "lines"} to send only those line ranges."""
    parts, sections, seen = [], [], set()
    for item in files:
        path, lines = (item, None) if isinstance(item, str) else (item.get("path"), item.get("lines"))
        if not path:
            raise PipelineError("every file needs a path")
        full = os.path.realpath(path if os.path.isabs(path) else os.path.join(project, path))
        relative = code_compile.norm(os.path.relpath(full, project))
        if relative.startswith(".."):
            raise PipelineError("{} is not inside the project {}".format(path, code_compile.norm(project)))
        name = os.path.basename(relative)
        if name.lower() in seen:
            raise PipelineError("two files named {}: send them in separate calls".format(name))
        seen.add(name.lower())
        if not os.path.exists(full):
            parts.append({"kind": "new", "path": relative, "name": name, "text": None})
            sections.append("New file: {}".format(relative))
            continue
        text = code_index.read_text(full)
        if lines:
            all_lines = text.split("\n")
            ranges = parse_ranges(lines, len(all_lines))
            shown = ("\n" + SEPARATOR + "\n").join("\n".join(all_lines[first - 1:last]) for first, last in ranges)
            parts.append({"kind": "excerpts", "path": relative, "name": name, "text": text, "ranges": ranges,
                          "segments": len(ranges),
                          "shown": ["\n".join(all_lines[first - 1:last]) for first, last in ranges]})
            sections.append("Excerpts from {}:\n```csharp\n// FILE: {}\n{}\n```".format(relative, name, shown))
        else:
            if len(text) > WHOLE_FILE_CHARS:
                raise PipelineError(
                    "{} is {} lines ({} characters): too long to rewrite whole. Send the parts the change touches as "
                    "{{\"path\": ..., \"lines\": \"120-180, 300-340\"}} (whole methods; the rest of the file's "
                    "declarations are attached automatically).".format(relative, text.count("\n") + 1, len(text)))
            parts.append({"kind": "whole", "path": relative, "name": name, "text": text, "shown": text})
            sections.append("Whole file {}:\n```csharp\n// FILE: {}\n{}\n```".format(relative, name, text.strip("\n")))
    return request.strip() + "\n\n" + "\n\n".join(sections), parts


def splice(values, parts):
    """{path: new file text} for one normalised answer."""
    overrides = {}
    for value, part in zip(values, parts):
        if part["kind"] != "excerpts":
            overrides[part["path"]] = value
            continue
        lines = part["text"].split("\n")
        for (first, last), piece in sorted(zip(part["ranges"], value), reverse=True):
            lines[first - 1:last] = piece.split("\n")
        overrides[part["path"]] = "\n".join(lines)
    return overrides


def prune_runs(folder):
    try:
        runs = sorted(name for name in os.listdir(folder) if os.path.isdir(os.path.join(folder, name)))
    except OSError:
        return
    for name in runs[:-KEPT_RUNS]:
        shutil.rmtree(os.path.join(folder, name), ignore_errors=True)


def project_cache(data_folder, project):
    key = hashlib.sha1(code_compile.norm(os.path.realpath(project)).lower().encode("utf-8")).hexdigest()[:12]
    return os.path.join(data_folder, "code", key)


def tool(arguments, send, data_folder, allowed_roots, default_tries):
    """local_llm_code: the text returned to the caller. Raises PipelineError for a request that cannot be run."""
    request, files, project = arguments.get("request"), arguments.get("files") or [], arguments.get("project")
    if not request or not files or not project:
        raise PipelineError("request, files and project are required")
    project = os.path.realpath(project)
    if not os.path.isdir(os.path.join(project, "Assets")):
        raise PipelineError("{} is not a Unity project root (no Assets folder)".format(project))
    if not any(project == root or project.startswith(root + os.sep) for root in allowed_roots):
        raise PipelineError("{} is outside the allowed folders: {}".format(project, os.pathsep.join(allowed_roots)))
    body, parts = prepare(request, files, project)
    cache = project_cache(data_folder, project)
    runs = os.path.join(cache, "runs")
    scratch = os.path.join(runs, "{}-{:04x}".format(time.strftime("%Y%m%d-%H%M%S"), random.getrandbits(16)))
    os.makedirs(scratch, exist_ok=True)
    prune_runs(runs)
    try:
        code_compile.rsp_of([part["path"] for part in parts], project)
        compilable = None
    except code_compile.CompileError as error:
        compilable = str(error)

    def check(values, name):
        if compilable:
            return {"status": "not checkable", "errors": [], "detail": compilable}
        ok, errors = code_compile.compile(splice(values, parts), project, os.path.join(scratch, name))
        return {"status": "compiles" if ok else "errors", "errors": errors}

    tries = arguments.get("tries") or default_tries
    result = run(body, parts, project, send, cache, check, system=arguments.get("system"), tries=tries,
                 think=arguments.get("think", True) is not False)
    return render(result, parts, project, scratch)


def render(result, parts, project, scratch):
    """The tool's answer: the verdict, the report, then each file's change as a diff, with the whole files on disk."""
    results, chosen, context = result["tries"], result["chosen"], result["context"]
    prompt_tokens, answer_tokens = totals(result["calls"])
    models = sorted(set("{} on {}".format(call["model"], call["rig"]) for call in result["calls"] if call.get("model")))
    lines = []
    if chosen is None:
        lines.append("NO ANSWER: none of the {} tries gave code in the format asked for.".format(len(results)))
    else:
        best = results[chosen]
        if best["status"] == "compiles":
            lines.append("COMPILES: try {}{} compiles as the whole assembly. That shows the names exist, not that the "
                         "change is right: review it.".format(chosen + 1, " (after one retry with the compiler's errors)"
                                                               if best["first"] is not None else ""))
        elif best["status"] == "errors":
            lines.append("DOES NOT COMPILE: no try compiled; try {} has the fewest errors ({}):".format(
                chosen + 1, len(best["errors"])))
            lines += ["  " + error[:300] for error in best["errors"][:MAX_ERRORS]]
        else:
            lines.append("NOT COMPILE-CHECKED: {} (try {} returned as it is).".format(
                best.get("detail", best["status"]), chosen + 1))
    lines.append("Tries: " + "; ".join(describe_try(item) for item in results))
    for item in results:
        if item["values"] is None and item.get("detail"):
            lines.append("  try {}: {}".format(item["at"] + 1, item["detail"]))
    if chosen is not None:
        lines += ["  " + line for line in differences(results, chosen)]
    attached = []
    if context["own"]:
        attached.append("the files' own types in full ({})".format(", ".join(context["own"])))
    if context["project"]:
        attached.append("project types ({})".format(", ".join(context["project"])))
    if context["api"]:
        attached.append("API member names ({})".format(", ".join(context["api"])))
    lines.append("Attached: " + ("; ".join(attached) or "nothing"))
    for need, labels in context["needs"]:
        lines.append("  model asked: {} -> {}".format(need, ", ".join(labels) or "nothing found"))
    if context["left_out"]:
        lines.append("  left out (budget): " + ", ".join(context["left_out"][:12]))
    if context["note"]:
        lines.append("  " + context["note"])
    lines.append("Cost: {} model calls, {} prompt tokens, {} answer tokens, {:.0f} s ({}).".format(
        len(result["calls"]), prompt_tokens, answer_tokens, result["seconds"], "; ".join(models) or "no rig answered"))
    if chosen is None:
        return "\n".join(lines)

    overrides = splice(results[chosen]["values"], parts)
    out = os.path.join(scratch, "result")
    lines.append("")
    lines.append("Changed files, whole, are in {} (nothing in the project was written):".format(code_compile.norm(out)))
    for part in parts:
        new = overrides[part["path"]]
        target = os.path.join(out, part["path"])
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as file:
            file.write(new)
        old = part["text"] or ""
        diff = list(difflib.unified_diff(old.split("\n"), new.split("\n"), "a/" + part["path"], "b/" + part["path"],
                                         lineterm="", n=2))
        lines.append("")
        if part["kind"] == "new":
            lines.append("New file {}:\n```csharp\n{}\n```".format(part["path"], new.rstrip("\n")))
        elif not diff:
            lines.append("{}: unchanged".format(part["path"]))
        else:
            lines.append("```diff\n{}\n```".format("\n".join(diff)))
    return "\n".join(lines)
