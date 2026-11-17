# eval: can a rig model write the game's code?

A fixed coding test for the models the rigs serve, asked by the owner on 2026-11-03: could a local model take over
code writing for The Classrooms (the Unity game in `McGunn/TheSneedRooms`)? Six frozen tasks from that game's code,
graded by Claude reading every answer, compiling it against the game's own assemblies and, for t1, running a test
harness. Results: [RESULTS.md](RESULTS.md).

Moved here from `TheSneedRooms/Tools/LocalModelEval` on 2026-11-08: it measures the rig's models, uses this repo's
client, and needs nothing from the game but its compiled assemblies (`UNITY_PROJECT`, below).

## What you need

- **A reachable rig** with the model to test loaded. `local_llm_status` names it, or `curl -s http://<rig>:11434/api/ps`.
  The owner switches models in the rig's flight sheet (`model=`, `num_ctx=65536`, `num_parallel=2`); never change the
  rig yourself. `run.py` reads `OLLAMA_URLS` from the local-llm server's `env` in `~/.claude.json`.
- **A checkout of TheSneedRooms whose editor has compiled once**, for `compile.sh` (it uses `Library/Bee` and
  `Library/ScriptAssemblies`; the editor may be closed). Default `D:/Dev/TheSneedRooms/master/TheSneedRooms`; another
  one with `UNITY_PROJECT=<path>`. Unity is found from that project's `ProjectSettings/ProjectVersion.txt`.
- **The .NET 8 SDK** (`dotnet`) for the t1 test, **Python 3**, **Git Bash** for the `.sh` scripts.

## Files

| Path | What |
|---|---|
| `run.py <task> [--think] [--run <n>] [--rules <file>]` | Sends the task to the rig through `../client/local_llm_mcp.py` (logged in its stats like any call). Saves `results/<model>/<task>[-think][-r<n>]/answer.md`, named after the model in the answer's footer, and extracts the C# next to it. Run from anywhere. |
| `check.sh <results/<model>> [folder...]` | The mechanical half of grading, for every answer folder or the ones named: extract, t1 test, compile (t4/t5 with the class renamed), t4/t5 diff against the input, the footer. |
| `extract.py <dir>` | Code out of `answer.md`: fenced blocks, or bare code split at `// FILE:` lines. |
| `compile.sh <Assembly-CSharp\|Assembly-CSharp-Editor> <file.cs>...` | Offline compile with the game's own compiler arguments, in about a second. |
| `rules.txt` | The system prompt: the game's rules boiled down. **v2**, used for every comparable set. `rules.v1.txt` is the first version (its wording made a model delete a needed `using Fusion`). |
| `tasks/<task>/` | `prompt.txt`, `files.txt` (inputs, relative to this folder) and the frozen inputs in `inputs/`. `tasks/t1/test` is the dotnet test for t1. |
| `results/<model>/` | Every answer, kept. `results/qwen3.5-27b/SCORECARD.md` is the first trial's own notes (partly wrong: see RESULTS.md). |

## The tasks

| Task | What it asks | What a correct answer looks like |
|---|---|---|
| t1 | Pure C# `RollingStats`: ring buffer with mean, min, max, nearest-rank percentile, allocation-free | `tasks/t1/test` prints `ALL PASS` |
| t2 | `tilefind` console command (DunGen tiles by name, `-count` trailing option) | compiles; `JoinArgs(args, 0, ...)` (the args don't include the command), `Console.Log`, no `Find*`; correct help example |
| t3 | "Script Carriers" `EditorWindow`: counts the prefabs referencing a script GUID | compiles in Assembly-CSharp-Editor; progress bar every 200 files, cleared in a `finally`; no invented APIs |
| t4 | Fix a bug from a given diagnosis (coroutines started on an inactive Tail Controller) | the real fix, TheSneedRooms `0ab93cbc89b`: guard the 3 `StartCoroutine` calls with `gameObject.activeInHierarchy` |
| t5 | Remove 4 `FindObjectsOfType<Light_Base>()` calls. Trap: the registry `LightService` already exists | iterate `LightService.Instance`, cast to `Light_Base`; no new registry; no deleted `using` |
| w1 | The real task: the Apparel Editor window (ClickUp 86e3yg62q), from a ~110-line spec | TheSneedRooms `4804f45fa9a`, `Assets/_LiminalLabs/Integrations/CharacterCustomizer/Editor/ApparelEditorWindow.cs`, 234 non-blank lines |

Inputs: t2 and t5 from TheSneedRooms `820e4acd532`, t4 from `0ab93cbc89b~1` (the bug before its fix), w1's
`ApparelObj.cs` from `4804f45fa9a` (the closest committed version to what the first model saw).

## Testing a rig model

From the repo root, in Git Bash. Each task twice, think on, rules v2 (the comparable conditions):

```bash
for t in t1 t2 t3 t4 t5 w1; do python eval/run.py $t --think --run 1; done
```

```bash
for t in t1 t2 t3 t4 t5 w1; do python eval/run.py $t --think --run 2; done
```

The rig serves `num_parallel` requests at once, so the two loops can run side by side (in the background: a think-on
answer takes 0.5–5 minutes). If a call fails with `unreachable (timed out)`, the rig's status probe timed out while
it was busy: rerun that task. Then:

```bash
eval/check.sh eval/results/<model-folder>
```

and read every answer. `local_llm_ask` is not a reviewer.

## Testing a Claude model (baseline)

Claude is run as a subagent of the session (Agent tool, `model: haiku` / `sonnet` / ...), one agent per task and run,
all in parallel, each with this prompt (fill in `<task>` and `<folder>`, e.g. `t2` and `t2-r2`):

```
You are the subject of a coding evaluation. Work alone and answer from what you read; this is a closed-book test.

Root: <absolute path of eval/>
Task: <task>

1. Read rules.txt (the system prompt you must follow), tasks/<task>/prompt.txt (the task), and every file listed in
   tasks/<task>/files.txt if that file exists (paths in it are relative to the root).
2. Read NOTHING else: no other files, no Glob/Grep/search, no git, no compiling or running code, no web. Other folders
   hold reference answers; looking at them invalidates the test.
3. Write your answer, exactly as rules.txt's OUTPUT section says (complete files in ```csharp blocks whose first line
   is `// FILE: <name>`, then at most 5 bullets), to results/<claude-model-id>/<folder>/answer.md using the Write tool.
   Write it once; do not revise it after writing.
4. Reply with only "done".
```

Then `check.sh` on its folder as above. Differences from the rig runs, to state in its Notes bullet: the subagent's context
also holds Claude Code's own system prompt, it reads the inputs through tool calls, and its token counts are not
reported (estimate them from the answer sizes, about 3.4 characters per token).

## Rubric (the same for every set)

For each answer:

1. **Compiles first try:** yes, or the number of errors (a floor when the compiler stopped early).
2. **Right after at most 2 one-line repairs:** a missing `using`, a bare member that needs `gameObject.`, an API used
   with the wrong return shape, a wrong argument. Anything bigger is a no.
3. **Defects:** **critical** (wrong behaviour, unusable, would ship a bug), **major** (a missing requirement, dead or
   duplicate code), **minor** (style, comments, unused locals).
4. **Task checks:** t1 tests pass; t4 guards with `activeInHierarchy` (not `activeSelf`, not `isActiveAndEnabled`);
   t5 reuses `LightService` and deletes no `using`; w1 has clickable rows, status tags in the list, the project-change
   reload, and how much is usable as written.
5. **From the footer:** prompt and answer tokens, tokens/s. **From `/api/ps`:** VRAM at 64k context. **From the owner:** the GPU and its power
   limit, and the flight sheet's `kv_cache_type`.

Single runs are noisy (the client sends no seed or temperature), so every new set has two runs per task, both
recorded when they differ.

## Adding a result set to RESULTS.md

One set per model × quant × rig setup (GPU, power limit, `kv_cache_type`, `num_ctx`) × think × rules version, in
**Comparable sets**. Give it a short name (e.g. `Q8 · 5090 · q8 KV`) and add it in three places: a row in **Setup**,
a row in **Scores**, and a column in **Per task**, where each cell is the compile result, then the verdict, both runs
(`✓ pass / ✗1 fixable`). Verdicts: `pass`, `minor` (right, minor defects only), `fixable` (right after ≤2 one-line
repairs), `unusable`. Keep long remarks out of the tables: one bullet under **Notes**, and the per-task grading
under **Grading notes**. Update **Closest Claude (est.)** and the **Verdict** when the new set changes them. Commit
`results/<model>/` with it.
