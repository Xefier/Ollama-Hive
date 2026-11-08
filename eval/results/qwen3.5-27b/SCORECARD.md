# Local model coding trial, 2026-11-03 (qwen3.5:27b Q4_K_M, 64k context, 4090)

Harness (this folder): `rules.txt` (system prompt: project rules), `run.py <task-dir> [--think]` (sends
`prompt.txt` + `files.txt` through the local-llm client, logs stats, saves `answer.md`; run it from the project root
with OLLAMA_URLS and LOCAL_LLM_ROOTS set as in ~/.claude.json), `extract.py <task-dir>` (code out of answer.md),
`compile.sh <Assembly-CSharp|Assembly-CSharp-Editor> <file.cs>` (offline compile against the editor's own Bee rsp,
~1 s), `t1test/` (dotnet test harness for task 1).

| Task | Think off | Think on |
|---|---|---|
| t1 RollingStats (pure C#, ring buffer, tests) | compiles, **fails tests**: index offset added twice, crash | **all tests pass** (7.3k tokens, 2.5 min) |
| t2 `tilefind` console command | **compiles first try, correct**; help example wrong ("Big Tile" said to match "BigTile_03") | not run |
| t3 Script Carriers editor window | unusable: invented IMGUI `ObjectField.Draw`, `MonoScript.GetPath`, `EditorApplication.currentUpdate` | 2 compile errors (invented path overload of `TryGetGUIDAndLocalFileIdentifier`, ternary type), rest right |
| t4 fix from a given diagnosis (real commit 0ab93cbc89b) | right 3 call sites; used bare `activeSelf`: no compile, and wrong check (misses an inactive parent). With `gameObject.activeInHierarchy` = the real fix | not run |
| t5 remove `FindObjectsOfType` (trap: `LightService` registry exists) | **found `LightService`**; deleted `using Fusion` that `SerializableDictionary` needs (over-applied the "no Fusion in SP" rule) | not run |

Compiled first try: 1 of 5 (think off). Right after Claude's 1-2 line repairs: 4 of 5 (think off), 5 of 5 with think.
Rig: 7 calls, 31k prompt tokens, 17k answer tokens, ~11 min.

Lessons: think on for code, always. Every result needs compile + Claude review: the defects are invented APIs and
quiet semantic slips (activeSelf), not syntax. It ignores the fence instruction (extract.py copes). Rule wording
matters: "don't reference Fusion" made it delete a needed using; say "don't add". Saving is real only where the code
is long and mechanical; prompt writing + review + repair eat much of it on small tasks.

## Real task: Apparel Editor window (ClickUp 86e3yg62q), 2026-11-03, think on

One call, `w1` in session ce4afa88's scratchpad: prompt 3.7k tokens (a ~110-line spec naming every IMGUI call to
use, plus ApparelObj.cs), answer 10.7k tokens (mostly thinking), 47 tok/s, ~4 min. Claude wrote the design-heavy half
(the Not-done status and its filtering, 10 files) itself.

| Measure | Result |
|---|---|
| Compile errors | 6: missing `using System` / `System.Linq` (4), `Editor.CreateCachedEditor` used as if it returned the editor (it fills a `ref`), `scrObj_Apparel.Apparel` (a struct) compared to null |
| Critical defects | 2: list rows could not be clicked (no MouseDown handling: the window was unusable except by arrow keys); no status tags in the list |
| Major | 2: `OnProjectChange` left empty and its `EditorApplication.projectChanged` hook never subscribed (no reload on project change), after it wrongly claimed EditorWindow has no `OnProjectChange`; a second, dead list-drawing method (`DrawListScrollView`) |
| Minor | stream-of-consciousness comments left in the code ("Correction: ...", "I need to redraw the list properly"); unused locals; slot shown as `-1` for a slotless item; arrow keys also stolen from the search field |
| Kept verbatim | 118 of the final 234 non-blank lines: toolbar, filters, `ItemMatches`, details pane, `MarkDone` (correct first time, including the body-version pairing and per-asset save) |
| Claude wrote | 116 lines (list pane, toolbar wiring, reload, keyboard, cleanup) |
| Playtest | passed: new asset arrives Not done, store refuses it, customizer hides a free and a paid hat, Mark done brings both back |

**Verdict: no usage saved on this one.** Writing the spec took about as long as writing the window would have, and
the repair was half the file, because the model lost the thread mid-answer: it wrote the list loop, noticed it had
no click handling, said so in comments, started a second version, and abandoned both. The parts that are one method
with a clear contract (`MarkDone`, `ItemMatches`) came out right; the part that needs a held layout/event design
across a 300-line `OnGUI` did not. That matches the earlier IMGUI result (t3).

**Next time:** give it units of one method each with a stated signature (`DrawList()`, `DrawToolbar()`, `ItemMatches`,
`MarkDone`), and write `OnGUI` and the fields yourself; or give it the skeleton file with `// TODO` bodies. Ask for
no comments beyond doc comments. Keep think on. Add to rules.txt: "never leave notes to yourself in code; if a part
is wrong, rewrite it before answering".
