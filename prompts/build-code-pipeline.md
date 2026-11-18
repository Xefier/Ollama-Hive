Build a code-writing pipeline into the Ollama-Hive client so the local model's answers for The Classrooms are
correct more often. Work in D:/Xefier/Ollama-Hive (client/local_llm_mcp.py is the MCP server Claude sessions call;
eval/ is its coding test). Branch from eval/classrooms-tuned-row, do not push, and never change a rig's settings
(the owner switches models and context).

## Why

Measured on real fixes from the game (D:/Xefier/TheClassrooms/TheClassrooms-training/results/HELDOUT-RESULTS.md,
read it first), the model fails mostly because the fix needs a member or mechanism the prompt does not show, and it
guesses a name. Fine-tuning did not change that (tuned and untuned: 35 of 68 answers usable each). What did help,
in prototype form:

- attaching the declarations (signatures, no bodies) of the project types involved: usable answers 7 -> 12 of 28;
- compiling the answer and giving the errors back once: compiling answers 6 -> 17 of 28.

What is still missing: Unity, Fusion and package APIs are not attached (most invented names are now there:
`RenderTexture.GetPixel`, `NetworkObject.Parent`, `Math.Ceil`, Input System binding calls), project types the
request never names are not attached, and nothing uses the fact that two runs of the same prompt often differ.

## What to build

One new MCP tool, `local_llm_code`, beside `local_llm_ask` (which stays as it is). Input: the change request, the
paths of the files it applies to, the Unity project root. Output: the changed code per file plus a short report
(what was attached, how many tries, compile result). Inside it, three stages:

1. **Context: give the model the API it needs.**
   - A signature index of the project's C# types. The prototype is `tools/arms.py` in TheClassrooms-training
     (`signatures`, `build_index`, `mentioned`, `declarations`, `render`); move the logic here rather than
     importing across repos.
   - Extend the index beyond project source to compiled APIs, read locally from the checkout, not from GitHub:
     `<project>/Library/ScriptAssemblies/*.dll` (every package and asmdef, 500 assemblies), the Unity modules under
     `<Unity>/Editor/Data/Managed/UnityEngine/*.dll` (the editor is found from ProjectSettings/ProjectVersion.txt,
     as eval/compile.sh does; on this PC it is under D:/Unity/Hub/Editor), and Fusion under
     `Assets/Photon/Fusion/Assemblies/*.dll` with their `.xml` docs. Read public types and members with a small
     .NET tool using System.Reflection.Metadata (only the .NET 10 SDK is installed here), cached on disk and keyed
     by each file's size and time so it rebuilds only what changed.
   - Selection, most relevant first, within a character budget: types named in the request and the code; the
     declared types of the fields, parameters and locals the code uses; base types; then one **ask-first pass**:
     the model gets the request and code and replies only with the types or members it needs to see
     (`NEED: Fusion.NetworkObject`, `NEED: how the player's death is announced`); exact names are looked up in the
     index, descriptions are searched for in the index and the source (ripgrep), and what is found is attached.
     Cap it at one such pass.
2. **Compile and retry.** Splice the answer into a scratch copy and compile the whole assembly offline (prototype:
   `tools/compile_check.py`, about 11 s, no editor). On errors, one more try with the compiler's messages and the
   declarations of every type those messages name (prototype: `retry_prompt` in arms.py). Never write into the
   project's own folders.
3. **Several tries.** Send N tries at once (default the rig's `num_parallel`, from the server's settings or a
   parameter), compile each, return the first that compiles; if none does, the one with the fewest errors, marked
   as not compiling. A compile check catches invented names, not wrong behaviour, so the report says which tries
   compiled and how they differ, and the caller still reviews the answer.

Also: a request that comes back empty with `done_reason: length` (thinking used the whole context) is retried once
with thinking off instead of failing.

## How to know it works

Use the held-out set in TheClassrooms-training: `tools/arms.py --arm base --run 1,2 --parallel 3` runs its 35
tasks and compile-checks them; the baseline answers and verdicts for the untuned and the tuned model are in
`results/`. Add an arm that goes through `local_llm_code` and compare on the same tasks: answers that compile, and
(by reading them against `reference.md`) answers that are the accepted fix or close to it. The held-out prompts
already carry project declarations, so strip the declaration block from the user message and let the pipeline
attach its own. Report per stage (context only, + retry, + N tries), with the token cost of each. Do not use
`heldout-eval.jsonl` or the six eval tasks for anything but testing.

## Rules

- The game repo is at D:/Xefier/TheClassrooms/TheClassrooms: read-only here. Do not open or drive the Unity editor.
- Rigs: http://192.168.1.182:11434 (untuned qwen3.8:27b) and http://192.168.1.189:11434 (tuned qwen3.8-unity:27b),
  both at 30,000 context with `num_parallel=3` today; check `local_llm_status` before a run and ask the owner
  before any long one.
- Commit on the branch when a stage works and is measured; do not push.
