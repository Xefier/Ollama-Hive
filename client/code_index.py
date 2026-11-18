#!/usr/bin/env python3
"""A signature index of what a Unity project's code can call: its own C# types and the compiled APIs it references.

Two halves, both cached on disk and rebuilt only for the files whose size or time changed:
  - Source: every type declared in the .cs files Unity compiles under Assets/, with every member's signature and no
    bodies (`signatures`, a small C# scanner).
  - Compiled: the public types and members of every assembly the code's own assembly references (the -r: lines of its
    Library/Bee rsp: Unity's modules, the packages' and asmdefs' assemblies, Fusion and other plugin DLLs, .NET), read
    by the apidump tool beside this file (System.Reflection.Metadata; built once with the .NET SDK), with the summaries
    from an .xml documentation file beside the assembly where there is one.

Standard library only. The apidump tool needs `dotnet` on the PATH; without it the compiled half is empty.

  python code_index.py --project <Unity project> [name ...]     builds the index and prints the named types
"""

import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree

import code_compile

TOOL_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apidump")
TOOL_BUILD_TIMEOUT_SECONDS = 600
TOOL_RUN_TIMEOUT_SECONDS = 600
SOURCE_CACHE_VERSION = 2
TYPE_DECL = re.compile(r"\b(class|struct|interface|enum|record)\s+([A-Za-z_]\w*)")
IDENTIFIER = re.compile(r"[A-Za-z_]\w*")
# Namespaces tried in this order when a simple name is in several and the code's usings don't decide
NAMESPACE_ORDER = ("UnityEngine", "Fusion", "Unity", "TMPro", "System.Collections.Generic", "System")
# Visual Scripting declares a type for nearly every common word (Add, If, Update, Variables) and Unity adds its using
# to new scripts: a bare name in code is taken to mean one of its types only when written out in full
UNMEANT_NAMESPACES = ("Unity.VisualScripting.",)

_lock = threading.Lock()
_memo = {}


def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as file:
        return file.read().replace("﻿", "").replace("\r\n", "\n")


# ---------------------------------------------------------------- C# source scanner

def blank(text):
    """The text with comments, strings, chars and preprocessor lines blanked (same length), so that braces and
    semicolons can be trusted."""
    out, i, n = list(text), 0, len(text)
    while i < n:
        c, d = text[i], text[i + 1] if i + 1 < n else ""
        if c == "/" and d == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
        elif c == "/" and d == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
        elif c == '"' or (c in "@$" and re.match(r'[@$]{1,2}"', text[i:i + 3])):
            quote = text.index('"', i)
            verbatim = "@" in text[i:quote]
            j = quote + 1
            while j < n:
                if verbatim and text[j] == '"' and text[j + 1:j + 2] == '"':
                    j += 2
                    continue
                if not verbatim and text[j] == "\\":
                    j += 2
                    continue
                if text[j] == '"' or (not verbatim and text[j] == "\n"):
                    j += 1
                    break
                j += 1
        elif c == "'":
            match = re.match(r"'(\\.[^']*|[^'\\])'", text[i:i + 12])
            j = i + (match.end() if match else 1)
        elif c == "#" and not text[text.rfind("\n", 0, i) + 1:i].strip():
            j = text.find("\n", i)
            j = n if j < 0 else j
        else:
            i += 1
            continue
        for k in range(i, min(j, n)):
            if out[k] != "\n":
                out[k] = " "
        i = j
    return "".join(out)


def signatures(text):
    """{type name: {"head": declaration, "kind", "ns": namespace, "members": [signature, ...]}} for every type in a
    C# file."""
    code, types, stack, start = blank(text), {}, [], 0   # stack of ("ns" | "type", name)
    i, n = 0, len(code)
    scoped = re.search(r"^\s*namespace\s+([A-Za-z_][\w.]*)\s*;", code, re.M)   # a file-scoped namespace

    def namespace():
        names = ([scoped.group(1)] if scoped else []) + [name for kind, name in stack if kind == "ns"]
        return ".".join(names)

    def header(end):
        head = " ".join(code[start:end].split())
        return re.sub(r"^(\[[^\]]*\]\s*)+", "", head)

    def in_type():
        return stack and stack[-1][0] == "type"

    while i < n:
        c = code[i]
        if c == "{":
            head = header(i)
            match = TYPE_DECL.search(head)
            if match and "(" not in head.split(match.group(0))[0] and (not stack or stack[-1][0] in ("ns", "type")):
                types.setdefault(match.group(2), {"head": head, "members": [], "kind": match.group(1), "ns": namespace()})
                stack.append(("type", match.group(2)))
            elif re.match(r"namespace\b", head) and (not stack or stack[-1][0] == "ns"):
                stack.append(("ns", head.split()[1] if len(head.split()) > 1 else ""))
            else:
                if in_type() and head:
                    left = re.split(r"\s=(?:\s|$)", head)[0]     # `int[] T = { 1, 2 }`: the name, not the initialiser
                    types[stack[-1][1]]["members"].append(head if "(" in left else left)
                depth, j = 1, i + 1                              # skip the whole body
                while j < n and depth:
                    depth += code[j] == "{"
                    depth -= code[j] == "}"
                    j += 1
                i = j
                # `int X { get; } = 1;` or `};`: swallow what follows up to the statement end on the same line
                rest = re.match(r"[ \t]*(=[^;{]*)?;", code[i:])
                if rest:
                    i += rest.end()
                start = i
                continue
            start = i + 1
        elif c == "}":
            if stack:
                kind, name = stack.pop()
                if kind == "type" and types[name]["kind"] == "enum" and code[start:i].strip():
                    types[name]["members"] = [" ".join(code[start:i].split())[:300]]
            start = i + 1
        elif c == ";":
            if in_type():
                head = header(i)
                if head and types[stack[-1][1]]["kind"] != "enum":
                    types[stack[-1][1]]["members"].append(re.split(r"\s=(?:\s|$)", head)[0])
            elif not stack and re.match(r"namespace\b", header(i)):
                pass                                             # the file-scoped namespace line
            start = i + 1
        elif c == "=" and code[i + 1:i + 2] == ">" and in_type():
            head = header(i)
            if head:
                types[stack[-1][1]]["members"].append(head)
            depth, j = 0, i + 2
            while j < n and not (code[j] == ";" and depth == 0):
                depth += code[j] in "{("
                depth -= code[j] in "})"
                j += 1
            i = j + 1
            start = i
            continue
        i += 1
    return types


def usings(text):
    """The namespaces a C# file imports, and the ones it declares."""
    found = re.findall(r"^\s*using\s+(?:static\s+)?([A-Za-z_][\w.]*)\s*;", text, re.M)
    return found + re.findall(r"^\s*namespace\s+([A-Za-z_][\w.]*)", text, re.M)


def member_name(signature):
    """The name a member signature declares: the identifier before its parameter list, accessor block or end."""
    left = re.split(r"\s*(?:\(|\{|=>|=(?!=))", signature, maxsplit=1)[0]
    left = re.sub(r"<[^<>]*>$", "", left.strip())
    names = IDENTIFIER.findall(left)
    return names[-1] if names else ""


def bases_of(head):
    """The base type and interface names in a declaration line, without generic arguments or namespaces."""
    if ":" not in head:
        return []
    after = head.split(":", 1)[1].split(" where ")[0]
    after = re.sub(r"<[^<>]*(?:<[^<>]*>[^<>]*)*>", "", after)
    return [name.strip().split(".")[-1] for name in after.split(",") if name.strip()]


# ---------------------------------------------------------------- source half

class SourceIndex(object):
    """types: {simple name: {"path", "head", "kind", "members"}}: for a name declared in several files, the declaration
    with the most members."""

    def __init__(self, types):
        self.types = types
        self._members = None

    def get(self, name):
        return self.types.get(name)

    def with_member(self, member):
        """Names of the types that declare a member of this name."""
        if self._members is None:
            table = {}
            for name, entry in self.types.items():
                for signature in entry["members"]:
                    table.setdefault(member_name(signature), []).append(name)
            self._members = table
        return self._members.get(member, [])


def merge_types(files):
    """{type name: entry with its path} from {path: {type name: entry}}: of several declarations the fullest."""
    types = {}
    for path in sorted(files):
        for name, found in files[path].items():
            if name not in types or len(found["members"]) > len(types[name]["members"]):
                types[name] = dict(found, path=path)
    return types


def source_index(project, cache_folder, overlay=None, overlay_key=None):
    """The SourceIndex of every .cs file Unity compiles under Assets/. Per-file results are cached in
    <cache_folder>/source.json keyed by size and time.

    overlay: {path: text, or None for a file that is not there} describes the project in another state than the one
    on disk (the held-out test indexes the code as it was before a task); those files are scanned from the overlay
    instead. overlay_key names that state, so that its index is built once per process."""
    table = code_compile.source_table(project)
    paths = sorted(path for path in table if path.startswith("Assets/"))
    cache_path = os.path.join(cache_folder, "source.json")
    with _lock:
        memo = _memo.get(("source", project))
        if memo is None:
            try:
                with open(cache_path, encoding="utf-8") as file:
                    memo = json.load(file)
                if memo.get("version") != SOURCE_CACHE_VERSION:
                    memo = None
            except (OSError, ValueError):
                memo = None
            memo = memo or {"version": SOURCE_CACHE_VERSION, "files": {}}
        files, changed, seen = memo["files"], 0, set()
        for path in paths:
            try:
                stat = os.stat(os.path.join(project, path))
            except OSError:
                continue
            seen.add(path)
            stamp = [stat.st_size, stat.st_mtime_ns]
            entry = files.get(path)
            if entry and entry[0] == stamp:
                continue
            try:
                found = signatures(read_text(os.path.join(project, path)))
            except Exception:
                found = {}   # a file the scanner cannot follow has no entry rather than stopping the index
            files[path] = [stamp, found]
            changed += 1
        for path in [path for path in files if path not in seen]:
            del files[path]
            changed += 1
        if changed or "index" not in memo:
            if changed:
                os.makedirs(cache_folder, exist_ok=True)
                temporary = cache_path + ".{}.tmp".format(os.getpid())
                with open(temporary, "w", encoding="utf-8") as file:
                    json.dump({"version": SOURCE_CACHE_VERSION, "files": files}, file)
                os.replace(temporary, cache_path)
            memo["index"] = SourceIndex(merge_types(dict((path, entry[1]) for path, entry in files.items())))
        _memo[("source", project)] = memo
        if not overlay:
            return memo["index"]
        if overlay_key is not None and ("overlay", project, overlay_key) in _memo:
            return _memo[("overlay", project, overlay_key)]
        state = dict((path, entry[1]) for path, entry in files.items())
        for path, text in overlay.items():
            if not path.startswith("Assets/"):
                continue
            if not text:
                state.pop(path, None)
                continue
            try:
                state[path] = signatures(text)
            except Exception:
                state.pop(path, None)
        index = SourceIndex(merge_types(state))
        if overlay_key is not None:
            _memo[("overlay", project, overlay_key)] = index
        return index


# ---------------------------------------------------------------- compiled half

def tool_path(cache_folder):
    """The built apidump.dll, building it when its source changed. None when it cannot be built (no dotnet)."""
    digest = hashlib.sha1()
    for name in ("Program.cs", "apidump.csproj"):
        with open(os.path.join(TOOL_FOLDER, name), "rb") as file:
            digest.update(file.read())
    folder = os.path.join(cache_folder, "apidump-" + digest.hexdigest()[:12])
    built = os.path.join(folder, "apidump.dll")
    if os.path.exists(built):
        return built
    try:
        result = subprocess.run(
            ["dotnet", "build", os.path.join(TOOL_FOLDER, "apidump.csproj"), "-c", "Release", "-o", folder,
             "--artifacts-path", folder + "-obj", "-nologo", "-v", "q"],
            capture_output=True, timeout=TOOL_BUILD_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return built if result.returncode == 0 and os.path.exists(built) else None


def assembly_key(path):
    stat = os.stat(path)
    text = "{}|{}|{}".format(code_compile.norm(path).lower(), stat.st_size, stat.st_mtime_ns)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:20]


class ApiIndex(object):
    """names: {simple type name: [[full name, assembly key, is nested], ...]}; an assembly's types are loaded when
    first asked."""

    def __init__(self, folder, names, paths, note=None):
        self.folder, self.names, self.paths, self.note = folder, names, paths, note
        self._assemblies, self._docs = {}, {}

    def _assembly(self, key):
        if key not in self._assemblies:
            with open(os.path.join(self.folder, key + ".json"), encoding="utf-8") as file:
                data = json.load(file)
            self._assemblies[key] = dict((join_name(entry["ns"], plain(entry["n"])), entry) for entry in data["types"])
        return self._assemblies[key]

    def _summaries(self, key):
        """{documentation id: first sentence of its summary} from the .xml beside the assembly, {} without one."""
        if key not in self._docs:
            found, path = {}, os.path.splitext(self.paths.get(key, ""))[0] + ".xml"
            if os.path.exists(path):
                try:
                    for member in xml.etree.ElementTree.parse(path).getroot().iter("member"):
                        summary = member.find("summary")
                        if summary is not None:
                            text = " ".join(doc_text(summary).split())
                            if text:
                                found[member.get("name", "")] = re.split(r"(?<=[.!?])\s", text)[0][:160]
                except (xml.etree.ElementTree.ParseError, OSError):
                    pass
            self._docs[key] = found
        return self._docs[key]

    def candidates(self, name):
        """[[full name, assembly key]] for a simple name, a nested Outer.Inner or a full Namespace.Type."""
        simple = name.split(".")[-1]
        found = self.names.get(simple, [])
        if "." in name:
            exact = [item for item in found if item[0] == name or item[0].endswith("." + name)]
            return exact
        return found

    def get(self, name, namespaces=(), strict=False):
        """The type of this name, or None. A simple name in several namespaces goes to the code's usings first, then
        NAMESPACE_ORDER. With strict, a simple name is only a top-level type of one of the given namespaces (what the
        code can really mean by it); a dotted name is always taken as written. Returns a copy with "full", "assembly"
        and, where documented, "doc"."""
        found = self.candidates(name)
        if "." not in name:
            found = [item for item in found if not item[0].startswith(UNMEANT_NAMESPACES)]
        if strict and "." not in name:
            found = [item for item in found if not item[2] and
                     (item[0].rsplit(".", 1)[0] if "." in item[0] else "") in tuple(namespaces) + ("",)]
        if not found:
            return None

        def rank(item):
            namespace = item[0].rsplit(".", 1)[0] if "." in item[0] else ""
            if namespace in namespaces:
                # In scope twice (System.Console and a package's Console): the code means the narrower one
                return (0, namespace == "System" or namespace.startswith("System."))
            for at, prefix in enumerate(NAMESPACE_ORDER):
                if namespace == prefix or namespace.startswith(prefix + "."):
                    return (1, at)
            return (2, 0)

        full, key = min(found, key=rank)[:2]
        entry = self._assembly(key).get(full)
        if entry is None:
            return None
        entry = dict(entry, full=full, assembly=os.path.basename(self.paths.get(key, "")))
        docs = self._summaries(key)
        if docs:
            entry["doc"] = docs.get("T:" + full)
            entry["member_docs"] = dict(
                (name, text) for name, text in ((member[0], member_doc(docs, full, member[0])) for member in entry["m"])
                if text)
        return entry


def doc_text(element):
    """An XML documentation element as text, a <see cref="T:Fusion.NetworkObject"/> written as NetworkObject."""
    text = element.text or ""
    for child in element:
        reference = child.get("cref") or child.get("name") or child.get("langword")
        text += doc_text(child) or (re.sub(r"\(.*$", "", reference).split(":")[-1].split(".")[-1] if reference else "")
        text += child.tail or ""
    return text


def member_doc(docs, full, name):
    for kind in ("P", "F", "E"):
        if kind + ":" + full + "." + name in docs:
            return docs[kind + ":" + full + "." + name]
    prefix = "M:" + full + "." + ("#ctor" if name == ".ctor" else name)
    for key, text in docs.items():
        if key == prefix or key.startswith(prefix + "(") or key.startswith(prefix + "`"):
            return text
    return None


def plain(name):
    """A type's display name without its generic parameter list: List<T> -> List."""
    return re.sub(r"<.*>$", "", name)


def join_name(namespace, name):
    return namespace + "." + name if namespace else name


def api_assemblies(project, rsp):
    """The assemblies the code compiled by this rsp can use: its -r: references. A project whose rsp names none falls
    back to the folders they normally come from."""
    found = [path for path in code_compile.references(rsp, project) if os.path.exists(path)]
    if found:
        return found
    import glob
    folders = [os.path.join(project, "Library", "ScriptAssemblies"),
               os.path.join(project, "Assets", "Photon", "Fusion", "Assemblies")]
    try:
        folders.append(os.path.join(code_compile.editor_data(project), "Managed", "UnityEngine"))
    except code_compile.CompileError:
        pass
    return [code_compile.norm(path) for folder in folders for path in sorted(glob.glob(os.path.join(folder, "*.dll")))]


def api_index(project, rsp, cache_folder):
    """The ApiIndex of the assemblies the rsp references. Each assembly's types are cached in
    <cache_folder>/api/<key>.json, the key made of its path, size and time; the name table per set of assemblies."""
    folder = os.path.join(cache_folder, "api")
    with _lock:
        paths, keys = {}, []
        for path in api_assemblies(project, rsp):
            try:
                key = assembly_key(path)
            except OSError:
                continue
            paths[key] = path
            keys.append(key)
        set_key = hashlib.sha1("\n".join(sorted(keys)).encode("utf-8")).hexdigest()[:20]
        memo = _memo.get(("api", set_key))
        if memo is not None:
            return memo
        os.makedirs(folder, exist_ok=True)
        missing = [key for key in keys if not os.path.exists(os.path.join(folder, key + ".json"))]
        note = None
        if missing:
            tool = tool_path(cache_folder)
            if tool is None:
                note = "compiled APIs not indexed: the apidump tool could not be built (is the .NET SDK installed?)"
            else:
                listing = os.path.join(folder, "list-{}.txt".format(os.getpid()))
                with open(listing, "w", encoding="utf-8") as file:
                    for key in missing:
                        file.write("{}\t{}\n".format(paths[key], os.path.join(folder, key + ".json")))
                try:
                    subprocess.run(["dotnet", tool, listing], capture_output=True, timeout=TOOL_RUN_TIMEOUT_SECONDS)
                except (OSError, subprocess.TimeoutExpired) as error:
                    note = "compiled APIs partly indexed: apidump failed ({})".format(error)
                finally:
                    try:
                        os.remove(listing)
                    except OSError:
                        pass
        names_path = os.path.join(folder, "names2-{}.json".format(set_key))
        names = None
        if not missing:
            try:
                with open(names_path, encoding="utf-8") as file:
                    names = json.load(file)
            except (OSError, ValueError):
                names = None
        if names is None:
            names = {}
            for key in keys:
                try:
                    with open(os.path.join(folder, key + ".json"), encoding="utf-8") as file:
                        data = json.load(file)
                except (OSError, ValueError):
                    continue
                for entry in data["types"]:
                    name = plain(entry["n"])
                    item = [join_name(entry["ns"], name), key, "." in name]
                    listed = names.setdefault(name.split(".")[-1], [])
                    # The same type from two assemblies (a facade and its implementation): the one with members wins
                    same = [other for other in listed if other[0] == item[0]]
                    if not same:
                        listed.append(item)
            if note is None:
                temporary = names_path + ".{}.tmp".format(os.getpid())
                with open(temporary, "w", encoding="utf-8") as file:
                    json.dump(names, file)
                os.replace(temporary, names_path)
        index = ApiIndex(folder, names, paths, note)
        _memo[("api", set_key)] = index
        return index


# ---------------------------------------------------------------- rendering

def order_members(members, wanted, name_of):
    """The members with the wanted names first (then names close to a wanted one), the rest in declaration order."""
    if not wanted:
        return list(members)
    names = [name_of(member) for member in members]
    close = set()
    for want in wanted:
        close.update(difflib.get_close_matches(want, set(names), n=4, cutoff=0.6))
        close.update(name for name in set(names) if want.lower() in name.lower() or (name and name.lower() in want.lower()))
    first = [member for member, name in zip(members, names) if name in wanted]
    second = [member for member, name in zip(members, names) if name not in wanted and name in close]
    rest = [member for member, name in zip(members, names) if name not in wanted and name not in close]
    return first + second + rest


def render_source(name, entry, everything=False, budget=1800, wanted=()):
    """A project type as a C# declaration block: its public, protected and internal members (every member with
    `everything`), the wanted ones first, up to the budget in characters."""
    members = [member for member in entry["members"]
               if everything or entry["kind"] == "interface" or re.search(r"\b(public|protected|internal)\b", member)]
    members = order_members(members or entry["members"][:1], wanted, member_name)
    lines, used = [], 0
    for at, member in enumerate(members):
        if used + len(member) > budget:
            lines.append("    // ... {} more members".format(len(members) - at))
            break
        lines.append("    " + member + ("" if entry["kind"] == "enum" else ";"))
        used += len(member) + 6
    where = entry.get("path", "") + (" (namespace {})".format(entry["ns"]) if entry.get("ns") else "")
    return "// {}\n{}\n{{\n{}\n}}".format(where, entry["head"], "\n".join(lines))


def render_api(entry, budget=1800, wanted=(), names_only=False):
    """A compiled type as a C# declaration block with its full name in the comment above. names_only lists the member
    names on a few lines instead of their signatures."""
    namespace = entry["full"].rsplit(".", 1)[0] if "." in entry["full"] else ""
    title = "// {}{}".format(entry["full"], " (namespace {})".format(namespace) if namespace else "")
    if entry.get("doc"):
        title += "\n// " + entry["doc"]
    members = order_members(entry["m"], wanted, lambda member: member[0])
    if entry["k"] == "enum":
        return "{}\n{} {{ {} }}".format(title, entry["h"], (members[0][1] if members else "")[:budget])
    if names_only:
        names = []
        for name, signature in members:
            if name == ".ctor":
                continue
            shown = name + ("()" if "(" in signature and "{" not in signature.split("(")[0] else "")
            if shown not in names:
                names.append(shown)
        text, more = "", 0
        for at, shown in enumerate(names):
            if len(text) + len(shown) > budget:
                more = len(names) - at
                break
            text += (", " if text else "") + shown
        lines = []
        while text:                                   # wrap at about 110 characters, on a comma
            cut = len(text) if len(text) <= 110 else (text.rfind(", ", 0, 110) + 1 or len(text))
            lines.append("    // " + text[:cut].strip())
            text = text[cut:].strip()
        if more:
            lines.append("    // ... {} more members".format(more))
        return "{}\n{}\n{{\n    // member names only:\n{}\n}}".format(title, entry["h"], "\n".join(lines))
    docs = entry.get("member_docs") or {}
    lines, used, documented = [], 0, set()
    for at, (name, signature) in enumerate(members):
        if used + len(signature) > budget:
            lines.append("    // ... {} more members".format(len(members) - at))
            break
        if name in wanted and name in docs and name not in documented:
            lines.append("    // " + docs[name])
            used += len(docs[name]) + 8
            documented.add(name)
        lines.append("    " + signature + ("" if signature.endswith("}") else ";"))
        used += len(signature) + 6
    return "{}\n{}\n{{\n{}\n}}".format(title, entry["h"], "\n".join(lines))


# ---------------------------------------------------------------- searching by description

STOP_WORDS = set("a an the of to in on at is are was be been how what which where when who that this it its for and or "
                 "with from by as not no do does did can could should would will get gets set sets use uses used using "
                 "need needs type types member members method methods class classes field fields property code value "
                 "values name names called call calls current new".split())


def stem(word):
    word = word.lower()
    for ending in ("ing", "ed", "es", "s"):
        if len(word) > len(ending) + 3 and word.endswith(ending):
            return word[:-len(ending)]
    return word


def words_of(identifier):
    """The stemmed words of a CamelCase or snake_case identifier."""
    return set(stem(word) for word in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", identifier) if len(word) > 1)


def query_words(description):
    return [word for word in dict.fromkeys(stem(word) for word in re.findall(r"[A-Za-z]{3,}", description))
            if word not in STOP_WORDS]


def search_source(source, description, limit=3):
    """[(type name, [member names that matched])] for the project types whose name or members share the most words
    with the description. A word in the type's name counts 3, in a member's name 1; one matching word is not enough
    for a description of several."""
    wanted = query_words(description)
    if not wanted:
        return []
    scored = []
    for name, entry in source.types.items():
        in_name = words_of(name)
        score, matched, hit = 0, set(), []
        for word in wanted:
            if word in in_name:
                score += 3
                matched.add(word)
        for signature in entry["members"]:
            member = member_name(signature)
            shared = words_of(member).intersection(wanted)
            if shared:
                matched.update(shared)
                score += len(shared)
                hit.append(member)
        # At least two of the words, one of them in the type's own name: a large type has some member for any word
        if len(matched) >= min(2, len(wanted)) and in_name.intersection(wanted):
            # every distinct word found is worth more than one word found many times
            scored.append((len(matched) * 10 + min(score, 9), name, hit))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(name, hit) for _score, name, hit in scored[:limit]]


def member_source(text, type_name, member, limit=1800):
    """The code of a type's members of this name (every overload), each from its declaration to the end of its body,
    cut at `limit` characters in all. None when the type or member is not in the text."""
    try:
        code = blank(text)
    except Exception:
        return None
    declared = re.search(r"\b(?:class|struct|interface|record)\s+" + re.escape(type_name) + r"\b[^{;]*\{", code)
    if not declared:
        return None
    start, depth, end = declared.end(), 1, declared.end()
    while end < len(code) and depth:
        depth += code[end] == "{"
        depth -= code[end] == "}"
        end += 1
    # Positions inside the type's body at its own member level
    level, at_level = 0, []
    for at in range(start, end):
        if code[at] == "{":
            level += 1
        elif code[at] == "}":
            level -= 1
        at_level.append(level == 0)
    pieces, used = [], 0
    for match in re.finditer(r"(?<![\w.])" + re.escape(member) + r"\b\s*(?:<[^<>(){};]*>\s*)?(\(|\{|=>|=(?!=)|;)", code[start:end]):
        at = start + match.start()
        if not at_level[match.start()] or not re.search(r"([\w\]?]|(?<!=)>)\s*$", code[start:at]):
            continue     # inside a body, or not preceded by a type: a call or an assignment, not a declaration
        first = max(code.rfind(";", start, at), code.rfind("}", start, at), code.rfind("{", start - 1, at)) + 1
        last, level = start + match.end() - 1, 0
        while last < end:
            if code[last] == "{":
                level += 1
            elif code[last] == "}":
                level -= 1
                if level == 0 and "=>" not in code[at:last]:
                    last += 1
                    break
            elif code[last] == ";" and level == 0:
                last += 1
                break
            last += 1
        piece = text[first:last].strip("\n")
        piece = re.sub(r"\A(\s*\n)+", "", piece)
        if used + len(piece) > limit:
            room = limit - used
            if room > 200:
                pieces.append(piece[:room].rsplit("\n", 1)[0] + "\n        // ... (cut)")
            break
        pieces.append(piece)
        used += len(piece)
    return "\n\n".join(pieces) or None


def search_literal(project, source, literal, exclude=(), limit=2, timeout=20, overlay=None):
    """[(path, line)] for the project source files that have this text as a string literal, lines that declare
    something (const, static, readonly) first. Uses ripgrep when it is installed, otherwise reads the files here.
    Files in the overlay ({path: text or None}) are read from it, not from disk."""
    quoted = '"' + literal + '"'
    overlay = overlay or {}
    paths = sorted(set(entry["path"] for entry in source.types.values()) - set(exclude))
    on_disk = [path for path in paths if path not in overlay]
    hits = []
    for path in paths:
        if overlay.get(path) and quoted in overlay[path]:
            hits += [(path, line) for line in overlay[path].split("\n") if quoted in line]
    try:
        result = subprocess.run(["rg", "--no-heading", "--no-line-number", "--with-filename", "-F", "-g", "*.cs", "-e",
                                 quoted, "Assets"], cwd=project, capture_output=True, timeout=timeout)
        known = set(on_disk)
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            path, _colon, text = line.partition(":")
            if code_compile.norm(path) in known:
                hits.append((code_compile.norm(path), text))
    except (OSError, subprocess.TimeoutExpired):
        deadline = time.time() + timeout
        for path in on_disk:
            if time.time() > deadline:
                break
            try:
                text = read_text(os.path.join(project, path))
            except OSError:
                continue
            if quoted in text:
                hits += [(path, line) for line in text.split("\n") if quoted in line]
    hits.sort(key=lambda hit: (not re.search(r"\b(const|static|readonly)\b", hit[1]), hit[0]))
    found, seen = [], set()
    for path, line in hits:
        if path not in seen:
            seen.add(path)
            found.append((path, line))
    return found[:limit]


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "--project":
        sys.exit("usage: code_index.py --project <Unity project> [type name ...]")
    sys.stdout.reconfigure(encoding="utf-8")
    root = sys.argv[2]
    cache = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "local-llm", "code",
                         hashlib.sha1(code_compile.norm(os.path.realpath(root)).lower().encode("utf-8")).hexdigest()[:12])
    started = time.time()
    built_source = source_index(root, cache)
    print("source: {} types, {:.1f}s".format(len(built_source.types), time.time() - started))
    started = time.time()
    built_api = api_index(root, code_compile.default_rsp(root), cache)
    print("compiled: {} type names from {} assemblies, {:.1f}s{}".format(
        len(built_api.names), len(built_api.paths), time.time() - started,
        " ({})".format(built_api.note) if built_api.note else ""))
    for wanted_name in sys.argv[3:]:
        found_source, found_api = built_source.get(wanted_name), built_api.get(wanted_name)
        if found_source:
            print(render_source(wanted_name, found_source))
        if found_api:
            print(render_api(found_api))
            print(render_api(found_api, names_only=True))
        if not found_source and not found_api:
            print(wanted_name, "not found; by its words:", search_source(built_source, wanted_name))
