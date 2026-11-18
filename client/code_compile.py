#!/usr/bin/env python3
"""Compiles changed copies of a Unity project's C# files, offline, as the whole assembly they belong to.

Uses the compiler arguments Unity itself wrote for that assembly (Library/Bee/artifacts/*.dag/<assembly>.rsp) with the
given files swapped for the changed copies, so every other file of the assembly is compiled with them, and an invented
member, a broken caller or a missing using all show up as they would in the editor. About 11 s for Assembly-CSharp, no
editor. Nothing in the project's folder is written: copies and output go to a scratch folder. Needs a checkout whose
editor has compiled once. Standard library only.

  compile({"Assets/.../Foo.cs": "<new text>"}, project, scratch) -> (ok, [error lines])
  python code_compile.py --project <Unity project>        (compiles Assembly-CSharp unchanged)
"""

import glob
import hashlib
import os
import re
import subprocess
import sys
import time

EDITOR_FOLDERS = ("C:/Program Files/Unity/{}/Editor/Data", "C:/Program Files/Unity/Hub/Editor/{}/Editor/Data",
                  "D:/Unity/Hub/Editor/{}/Editor/Data")
DEFAULT_ASSEMBLY = "Assembly-CSharp"
COMPILE_TIMEOUT_SECONDS = 600

_tables = {}


class CompileError(Exception):
    """The project cannot be compiled offline at all (no compiler arguments, no editor): not an error in the code."""


def norm(path):
    return path.replace("\\", "/")


def dag_folder(project):
    """The newest Library/Bee/artifacts/*.dag folder that has the default assembly's compiler arguments."""
    dags = [dag for dag in glob.glob(os.path.join(project, "Library", "Bee", "artifacts", "*.dag"))
            if os.path.exists(os.path.join(dag, DEFAULT_ASSEMBLY + ".rsp"))]
    if not dags:
        raise CompileError("No {}.rsp under {}/Library/Bee/artifacts: let the editor compile the project once".format(
            DEFAULT_ASSEMBLY, norm(project)))
    return max(dags, key=os.path.getmtime)


def source_table(project):
    """{source path as written in an rsp: rsp file} for every assembly of the project. Reread when the .dag folder's
    rsp files change (the editor rewrites them when scripts are added)."""
    dag = dag_folder(project)
    rsps = [rsp for rsp in glob.glob(os.path.join(dag, "*.rsp")) if not rsp.endswith(".mvfrm.rsp")]
    stamp = (dag, len(rsps), max(os.path.getmtime(rsp) for rsp in rsps))
    cached = _tables.get(project)
    if cached and cached[0] == stamp:
        return cached[1]
    table = {}
    for rsp in rsps:
        with open(rsp, encoding="utf-8", errors="replace") as file:
            for line in file:
                line = line.strip().strip('"')
                if line.endswith(".cs"):
                    table[norm(line)] = rsp
    _tables[project] = (stamp, table)
    return table


def default_rsp(project):
    return os.path.join(dag_folder(project), DEFAULT_ASSEMBLY + ".rsp")


def rsp_of(paths, project):
    """The rsp of the assembly the project-relative paths belong to. A path no assembly has (a new file) joins the
    others'; with none known, the default assembly. Raises CompileError when they belong to different assemblies."""
    table = source_table(project)
    found = sorted(set(table[norm(path)] for path in paths if norm(path) in table))
    if len(found) > 1:
        raise CompileError("The files belong to different assemblies ({}): send one assembly's files per call".format(
            ", ".join(os.path.basename(rsp)[:-4] for rsp in found)))
    return found[0] if found else default_rsp(project)


def references(rsp, project):
    """The assemblies an rsp references (-r:), as absolute paths."""
    found = []
    with open(rsp, encoding="utf-8", errors="replace") as file:
        for line in file:
            match = re.match(r'-r(?:eference)?:"?([^"\r\n]+)"?', line.strip())
            if match:
                path = match.group(1)
                found.append(norm(path if os.path.isabs(path) else os.path.join(project, path)))
    return found


def editor_data(project):
    """The Editor/Data folder of the Unity version the project uses."""
    with open(os.path.join(project, "ProjectSettings", "ProjectVersion.txt"), encoding="utf-8") as file:
        match = re.search(r"m_EditorVersion: (\S+)", file.read())
    if not match:
        raise CompileError("No m_EditorVersion in {}/ProjectSettings/ProjectVersion.txt".format(norm(project)))
    version = match.group(1)
    candidates = [folder.format(version) for folder in EDITOR_FOLDERS]
    if os.environ.get("UNITY_EDITOR_DATA"):
        candidates.append(os.environ["UNITY_EDITOR_DATA"])
    for folder in candidates:
        if os.path.isdir(folder):
            return folder
    raise CompileError("Unity {} not found: set UNITY_EDITOR_DATA to its Editor/Data folder".format(version))


def compile(overrides, project, scratch, timeout=COMPILE_TIMEOUT_SECONDS):
    """overrides: {project-relative path: new text}, all of one assembly. Returns (ok, errors): the compiler's
    `error CS...` lines, with the scratch copy's path put back to the project's."""
    table = source_table(project)
    rsp = rsp_of(overrides, project)
    os.makedirs(scratch, exist_ok=True)
    swap, extra = {}, []
    for path, text in overrides.items():
        path = norm(path)
        copy = norm(os.path.join(scratch, hashlib.sha1(path.encode("utf-8")).hexdigest()[:10] + "_" + os.path.basename(path)))
        with open(copy, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
        if path in table:
            swap[path] = copy
        else:
            extra.append((path, copy))
    lines = []
    with open(rsp, encoding="utf-8", errors="replace") as file:
        for line in file:
            bare = norm(line.strip().strip('"'))
            if bare in swap:
                lines.append('"{}"\n'.format(swap[bare]))
            elif not line.startswith(("-out:", "-refout:", "-analyzer:", "-additionalfile:")):
                lines.append(line if line.endswith("\n") else line + "\n")
    lines += ['"{}"\n'.format(copy) for _path, copy in extra]
    lines.append('-out:"{}"\n'.format(norm(os.path.join(scratch, "out.dll"))))
    new_rsp = os.path.join(scratch, "check.rsp")
    with open(new_rsp, "w", encoding="utf-8") as file:
        file.writelines(lines)
    editor = editor_data(project)
    try:
        result = subprocess.run(
            [editor + "/NetCoreRuntime/dotnet.exe", "exec", editor + "/DotNetSdkRoslyn/csc.dll", "-nologo", "-noconfig",
             "@" + new_rsp], cwd=project, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CompileError("The compiler could not be run: {}".format(error))
    output = (result.stdout + result.stderr).decode("utf-8", "replace")
    back = dict((copy, path) for path, copy in list(swap.items()) + extra)
    errors = []
    for line in output.splitlines():
        if re.search(r"\berror CS\d+", line):
            for copy, real in back.items():
                line = line.replace(copy, real).replace(copy.replace("/", "\\"), real)
            errors.append(line.strip())
    if result.returncode != 0 and not errors:
        raise CompileError("The compiler failed without an error line: {}".format(output.strip()[-400:]))
    try:
        os.remove(os.path.join(scratch, "out.dll"))
    except OSError:
        pass
    return not errors, sorted(set(errors))


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--project":
        sys.exit("usage: code_compile.py --project <Unity project>")
    import tempfile
    started = time.time()
    ok, errors = compile({}, sys.argv[2], tempfile.mkdtemp(prefix="code_compile_"))
    print("ok" if ok else "FAILED", "{:.0f}s".format(time.time() - started), len(errors), "errors")
    for error in errors[:10]:
        print(" ", error[:300])
