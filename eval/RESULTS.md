# Local model coding results

Can a local model on the LAN rig take over code writing? (owner, 2026-11-03). Six frozen tasks (`tasks/`), graded
by Claude reading every answer, compiling it offline (`compile.sh`) and, for t1, running `tasks/t1/test`. Tasks and
rubric: `README.md` in this folder.

Each result set has a short name, used as its column in the per-task tables. Within a section, every set ran under
the same conditions (the section heading).

- **Setup:** the rig's card and the power limit it runs under (tokens/s depends on both), `kv_cache_type` (f16 is
  Ollama's default) and `num_ctx`. VRAM is from `/api/ps` at that context.
- **Per-task cells:** compile result, then verdict. `✓` compiles first try, `✗n` n compile errors (a floor when the
  compiler stopped early). Verdicts: `pass` (correct), `minor` (correct, only minor defects), `fixable` (right after at
  most 2 one-line repairs), `unusable`. Two results are two runs of the same task (the client sends no seed, so runs
  differ). `—` not run.
- **Closest Claude (est.)** is the Claude model and version whose code on tasks like these the set's results are
  closest to: a judgement by the grader (Claude Opus 5.5, 2026-11-07) from the failure kinds (invented APIs, wrong
  checks, missed requirements, first-try compile rate), not a measurement. Claude Haiku 5.5 has its own measured set,
  which anchors the column; the other entries are still estimates.

## Comparable sets (think on, rules v2, two runs per task)

### Setup

| Set | Model | Quant | GPU (power limit) | KV cache | Context | VRAM | tok/s |
|---|---|---|---|---|---|---|---|
| **Q4 · 4090** | qwen3.8:27b | Q4_K_M | RTX 4090 (400 W) | f16 | 64k | 17.6 GB | 111–130 |
| **Q8 · 5090 · f16** | qwen3.8:27b | Q8_0 | RTX 5090 (520 W) | f16 | 50k | 31.1 GB | 49–53 |
| **Q8 · 5090 · q8 KV** | qwen3.8:27b | Q8_0 | RTX 5090 (520 W) | q8_0 | 64k | 30.4 GB | 51–52 |
| **Haiku 5.5** | claude-haiku-5-5 | API | — | — | — | — | — |
| **Classrooms-tuned v1** | qwen3.8-unity:27b (LoRA on qwen3.8:27b) | Q4_K_M | rig 192.168.1.182 (card and power limit not recorded) | not recorded | 64k | 21.0 GB, 15.2 GB of it on the GPU | 22–34 |

### Scores (12 answers each)

| Set | First-try compiles | Right after ≤2 one-line repairs | Correct as written | Answer tokens | Closest Claude (est.) |
|---|---|---|---|---|---|
| **Q4 · 4090** | 10/12 | 10/12 | 4/12 | 60,261 | Claude 3.5 Sonnet; below Haiku 5.5 |
| **Q8 · 5090 · f16** | 7/12 | 10/12 | 5/12 | 58,450 | Claude 3.5 Sonnet; below Haiku 5.5 |
| **Q8 · 5090 · q8 KV** | 8/12 | 12/12 | 6/12 | 60,700 | Claude 3.5 Sonnet; below Haiku 5.5 |
| **Haiku 5.5** | 12/12 | 12/12 | 12/12 | ~22,000 (est.) | itself |
| **Classrooms-tuned v1** | 5/12 | 9/12 | 3/12 | 80,249 | Claude 3 Sonnet to 3.5 Sonnet; below the untuned Q4 · 4090 |

### Per task (run 1 / run 2)

| Task | Q4 · 4090 | Q8 · 5090 · f16 | Q8 · 5090 · q8 KV | Haiku 5.5 | Classrooms-tuned v1 |
|---|---|---|---|---|---|
| t1 ring buffer | ✓ unusable / ✓ unusable | ✓ pass / ✓ pass | ✓ pass / ✓ pass | ✓ pass / ✓ pass | ✓ pass / ✓ fixable |
| t2 console command | ✓ fixable / ✗4 fixable | ✓ pass / ✓ fixable | ✓ pass / ✓ pass | ✓ minor / ✓ minor | ✗3 fixable / ✓ minor |
| t3 editor window | ✓ minor / ✓ fixable | ✗1 fixable / ✗4 fixable | ✗1 fixable / ✗1 fixable | ✓ pass / ✓ minor | ✗1 fixable / ✗1 unusable |
| t4 bug fix | ✓ fixable / ✓ fixable | ✓ unusable / ✗4 fixable | ✓ fixable / ✓ fixable | ✓ pass / ✓ pass | ✗1 fixable / ✓ fixable |
| t5 Find* removal | ✓ pass / ✓ minor | ✓ pass / ✓ minor | ✓ pass / ✓ pass | ✓ pass / ✓ pass | ✗4 fixable / ✓ pass |
| w1 Apparel Editor | ✓ minor / ✗1 fixable | ✗3 unusable / ✗2 fixable | ✗1 fixable / ✗1 fixable | ✓ pass / ✓ pass | ✗8 unusable / ✗4 unusable |

### Notes

- **Q4 · 4090:** t1 fails the tests both times. ~2.5× qwen3.5's speed on the same 4090; w1 in ~1.6 min.
- **Q8 · 5090 · f16:** run at `num_ctx=50000` because f16 spills at 64k (94% on GPU already at 54k). ~2.3× slower than
  Q4 · 4090, but t1 right both times; w1 in ~3–3.7 min.
- **Q8 · 5090 · q8 KV:** the same model and rig with `kv_cache_type=q8_0`, which fits 64k fully on the GPU in less
  VRAM than f16 needed at 50k, at the same speed. No sign the quantized cache hurt: right after small repairs on all
  12 answers (f16 at 50k: 10), within the noise of two runs. w1 in ~3.6–4 min.
- **Haiku 5.5:** run as a Claude Code subagent with its default thinking, see **Haiku runs** below; 25–105 s per
  task. Its answer tokens are estimated from 75 KB of answers.

- **Classrooms-tuned:** the fine-tune built from the accepted-fix dataset (`train.jsonl`, kept in
  `TheClassrooms-training`). Fill its row in all three tables and its Closest Claude entry each time a new version is
  run (two runs per task, think on, rules v2). The six tasks here must stay out of its training data, or its row
  measures memory of the answers, not skill.
- **Classrooms-tuned v1** (2026-11-18): the first version, trained on a 4090 from 69 examples of at most 2,048 tokens,
  none with declarations attached. Worse here than the untuned Q4 · 4090 it was made from: half the first-try
  compiles, w1 unusable twice. The training examples are short excerpts of existing files; these tasks mostly ask for
  whole new files, which none of the 69 examples showed. On the game's own held-out fixes the same model did better
  than untuned (`TheClassrooms-training/results/HELDOUT-RESULTS.md`). The rig held 15.2 GB of the 21.0 GB model on
  the GPU, hence 22–34 tok/s; that affects speed, not answers. w1 run 1 had no `// FILE:` line and was compiled
  under the right name by hand.

Not yet run: **qwen3.5:27b · think · v2**, the fair qwen3.5 set (needs the owner to load qwen3.5:27b on the rig).

## History: not comparable (2026-11-03, mixed rules and think modes, one run each)

All three: qwen3.5:27b Q4_K_M on the RTX 4090 (400 W), f16 cache, 64k context, 20.7 GB VRAM, 47–49 tok/s.

| Set | Think | Rules | First-try compiles | Right after ≤2 one-line repairs | Answer tokens | Closest Claude (est.) |
|---|---|---|---|---|---|---|
| **3.5 · off · v1** | off | v1 | 2/5 (t1 compiles but is wrong) | 3/5 (t2, t4, t5) | 7,320 | Claude 3 Haiku |
| **3.5 · on · v1** | on | v1 | 1/2 | 2/2 | 9,467 | Claude 3.5 Haiku |
| **3.5 · on · v2** | on | v2 | 0/1 | 0/1 | 10,690 | Claude 3.5 Haiku |

| Task | 3.5 · off · v1 | 3.5 · on · v1 | 3.5 · on · v2 |
|---|---|---|---|
| t1 ring buffer | ✓ unusable (tests fail) | ✓ pass | — |
| t2 console command | ✓ minor | — | — |
| t3 editor window | ✗1+ unusable | ✗2 fixable | — |
| t4 bug fix | ✗3 fixable | — | — |
| t5 Find* removal | ✗1 fixable | — | — |
| w1 Apparel Editor | — | — | ✗6 unusable |

- **3.5 · off · v1:** t4 uses bare `activeSelf` (wrong check, 1 critical); t5 deleted `using Fusion` (rules v1
  wording) but found `LightService`; t3 invented 4 APIs.
- **3.5 · on · v1:** only t1 and t3 run; t1 ~2.5 min, all tests pass.
- **3.5 · on · v2:** rows not clickable, no status tags, project-change hook never subscribed, dead list method; 118
  of 234 lines kept (50%).

Folders: `results/qwen3.5-27b/t1..t5` (off · v1), `t1k`, `t3k` (on · v1), `w1` (on · v2). The trial's own notes:
`results/qwen3.5-27b/SCORECARD.md` (its "5 of 5 with think" is wrong: only t1 and t3 ran with think on).

## Grading notes, 2026-11-07 (grader: Claude Opus 5.5)

Folders: `results/qwen3.8-27b/<task>-think` (run 1) and `<task>-think-r2` (run 2); `results/claude-haiku-5-5/<task>`
and `<task>-r2`. Run 1 of t3–t5 on qwen3.8 was redone after the rig's status probe timed out while both runs were
generating (no answer was lost or picked).

### qwen3.8:27b

- **t1, both runs, critical:** the same bug twice. Min, Max and Percentile start the window at the write index, which
  is the oldest sample only once the buffer is full; before that it is the next empty slot, so they read a stale or
  zero slot (240 test failures, including "after clear"). Fixing it takes the same edit at 3 places: over the
  rubric's 2.
- **t2 run 1, critical:** copied `LootCommand`'s `JoinArgs(args, 1, ...)` and `argEnd < 2`, but loot's `args[0]` is
  a subcommand. Here it is the first search word, so `tilefind Big Tile` searches "Tile" and `tilefind Big` prints the
  help. Two one-line repairs. Major: 0 matches prints a warning, not the required total line. Minor: help claims
  "Big Tile" finds "Big_Tile_03".
- **t2 run 2:** the same JoinArgs bug, plus a ternary inside an interpolated string (4 compiler errors, one cause:
  needs parentheses). Two one-line repairs.
- **t3 run 1:** meets every requirement (bar every 200 files, cleared in `finally`, cancel, HelpBox, ping + select).
  Minor: `Repaint()` at the end of every `OnGUI` keeps the window repainting forever; paths keep backslashes.
- **t3 run 2, major:** shows the progress bar on every file (15,000 calls), not every 200, with an empty
  "every 200" branch left behind (dead code). One-line repair.
- **t4, both runs:** the right 3 call sites, but guarded with `isActiveAndEnabled`, not `activeInHierarchy`: a
  disabled handler on an active object would now skip coroutines it used to run (major). Run 2 put the guard in one
  helper (one-line repair); run 1 repeats it 3 times (a one-word swap at each).
- **t5, both runs:** passed the trap: `LightService.Instance`, no new registry, no deleted `using`. Run 2 also used
  `LightService.SetColorFilter` and dropped the per-light try/catch (minor behaviour change).
- **w1 run 1:** compiles first try and meets every requirement the qwen3.5 answer missed: clickable rows, status
  tags, the `OnProjectChange` reload, one shared `MarkDone`, every Begin* matched. Minor: rebuilds the shown list in
  the middle of the click event after "Mark all shown done" (can log one GUILayout mismatch), `Enum.GetNames` on every
  event, decorative separator comments. About all of it usable as written.
- **w1 run 2:** ✗1 (`Array.Contains` needs `using System.Linq`), otherwise complete; minor: an unused local.

### qwen3.8:27b-q8_0 on the 5090 (f16 cache, 50k context), 2026-11-08

Folders: `results/qwen3.8-27b-q8_0/<task>-think-r50k-1` and `-r50k-2`. Run 1 of t3 was redone after the rig's status
probe timed out twice. Graded from `check.sh` and the task checks on each answer; not every answer was read line by line.

- **t1, both runs:** pass every test (the Q4_K_M build failed both).
- **t2 run 1:** `JoinArgs(args, 0, end)` with the trailing `-count` peeled first: right. **Run 2, critical:**
  `JoinArgs(args, 1, ...)`, the same bug the Q4_K_M build made (drops the first search word). Two one-line repairs.
- **t3 run 1:** ✗1, `AssetDatabase.TryGetGUIDAndLocalFileIdentifier` called with a path (that overload takes an
  object; `AssetPathToGUID` is the one-line repair). **Run 2:** ✗4, one cause: a ternary inside an interpolated
  string. Both show the bar every 200 files and clear it in `finally`.
- **t4 run 1, critical:** guards the 3 calls with `enabled`, which stays true while the object is inactive: the bug
  is not fixed. **Run 2:** the right check (`gameObject.activeInHierarchy`) in one helper, but the helper takes a
  `Coroutine` instead of an `IEnumerator` (✗4, one cause, one-line repair).
- **t5, both runs:** passed the trap (`LightService.Instance`, no new registry, no deleted `using`). Run 2 used
  `LightService.SetColorFilter` and dropped the per-light try/catch (minor, as with Q4_K_M).
- **w1 run 1:** ✗3: `?.` on the `Apparel` struct at 2 places and `EditorGUILayout.Label` (3 repairs, over the
  rubric's 2). **Run 2:** ✗2, missing `using System` and `EditorGUI.Label`. Both have the status filter, clickable
  rows and the `OnProjectChange` reload. Run 2 put `#if UNITY_EDITOR` above the `// FILE:` line, so `extract.py`
  saved it as `code0.cs` (copied to `ApparelEditorWindow.cs` for `check.sh`).

### qwen3.8:27b-q8_0 on the 5090 (q8_0 cache, 64k context), 2026-11-08

Folders: `results/qwen3.8-27b-q8_0/<task>-think-r64kq8-1` and `-r64kq8-2`. Graded like the f16 set: `check.sh` and
the task checks on each answer, not every answer read line by line.

- **t1, both runs:** pass every test.
- **t2, both runs:** `JoinArgs(args, 0, nameCount)` with the trailing `-count` peeled first: right.
- **t3 run 1:** ✗1, invented `EditorGUI.IndentedScope` (the real one is `IndentLevelScope`). **Run 2:** ✗1, `MinSize`
  for `minSize`. Both show a cancelable bar every 200 files and clear it in `finally`.
- **t4, both runs, major:** the right 3 call sites guarded with `isActiveAndEnabled`, not `activeInHierarchy`, like
  the Q4_K_M build: a disabled handler on an active object would now skip coroutines it used to run. A one-word
  swap at each site.
- **t5, both runs:** passed the trap (`LightService.Instance`, no new registry, no deleted `using`), per-light
  try/catch kept.
- **w1, both runs:** ✗1, `!= null` on the `Apparel` struct (a one-line repair). Both have the status filter,
  clickable rows and the `OnProjectChange` reload; run 1 adds ping, select and arrow-key navigation.

### qwen3.8-unity:27b (Classrooms-tuned v1), 2026-11-18 (grader: a Claude Fable 5.2 reviewer)

Folders: `results/qwen3.8-unity-27b/<task>-think` (run 1) and `<task>-think-r2` (run 2).

- **t1 run 1:** ALL PASS; the window start is right before and after the buffer fills.
- **t1 run 2, critical:** `Add` overwrites the oldest slot without subtracting it from the sum, so Mean is wrong once
  the window fills. One added line passes every test.
- **t2 run 1:** `Find` is declared `static` but reads the instance `name` (3 errors, one edit). Logic right:
  `JoinArgs(args, 0, ...)`, `-count` peeled first, the 25-line cap.
- **t2 run 2, minor:** right; every output starts with a newline and two spaces, the `-count` total included.
- **t3 run 1, critical:** invented `EditorGUILayout.ObjectField<MonoScript>(...)`, and the cancel test is inverted
  (`!DisplayCancelableProgressBar` breaks at file 0 unless the user cancels), so it always reports 0 prefabs. Two
  one-line repairs.
- **t3 run 2, unusable:** the same inverted cancel test; `TryGetGUIDAndLocalFileIdentifier` called with a path
  string; pressing the button with no script picked throws on every repaint. Three repairs.
- **t4 run 1:** the right three call sites through one helper, written as a bare `activeInHierarchy` (needs
  `gameObject.`).
- **t4 run 2, major:** compiles but guards with `isActiveAndEnabled`, and justifies it with a false claim about
  disabled components.
- **t5 run 1:** reuses `LightService` and deletes no `using`, but adds `using System;` for an `Action<ILight>`
  helper, which makes the four `Random.Range` calls ambiguous. One line repairs it.
- **t5 run 2:** the minimal change, four `foreach (var l in LightService.Instance)`.
- **w1 run 1, unusable:** complete in structure (clickable rows, status tags, project-change reload, one shared
  `MarkDone`), but static methods read instance fields at 2 places and the `Apparel` struct is compared with null at
  3. Five line edits, and no `// FILE:` line.
- **w1 run 2, unusable:** `?.` on the `Apparel` struct twice, invented `EditorGUI.Label` twice, and GUIDs from
  `FindAssets` passed to `LoadAssetAtPath` without `GUIDToAssetPath`, so the list is always empty.
- **Against Q4 · 4090:** better where the untuned model was consistently wrong (`JoinArgs(args, 0, ...)` both times,
  t1 passing once, `activeInHierarchy` chosen once). Worse on C# slips it did not make before (static methods reading
  instance members, an added `using` that makes a name ambiguous) and on new logic bugs (the inverted cancel test
  twice, GUIDs used as paths, the missing subtraction).

### claude-haiku-5-5

- **t1:** both pass every test.
- **t2:** both right (`JoinArgs(args, 0, n)`, trailing `-count` peeled first). Minor: run 1's help claims "Big Tile"
  finds `Tile_PlayRooms_BigTile1` (it can't); run 2 treats a lone `tilefind -count` as an empty name.
- **t3:** both meet every requirement. Minor: run 2 leaves one unused line (`assetsRoot`), which its agent reported.
- **t4:** both equal the real fix (`gameObject.activeInHierarchy`), run 2 in one helper.
- **t5:** both use `LightService`, casting to `Light_Base`, and copy the registry into a list first in case a light's
  event changes it mid-loop (a one-shot allocation, explained in a comment).
- **w1:** both compile first try and meet every requirement; run 1 defers the reload to the Layout event, which
  avoids the GUILayout mismatch qwen3.8 can hit. Run 1 used `DebugX.Log` where the prompt asked for `Debug.Log`
  (rules.txt forbids `Debug.Log`; it said so in its notes).

### Haiku runs: how they differ from the rig runs

Haiku ran as a Claude Code subagent (`model: haiku`), told to read only `rules.txt`, the task's `prompt.txt` and its
`files.txt` inputs and to write `answer.md` once, without searching, compiling or revising. So its context also held
Claude Code's own system prompt, and it read the inputs through tool calls instead of receiving them inline. Its
token counts are not reported to the session; the sum above is estimated from the answer sizes. The answers were
not checked against its transcripts, so nothing proves it stayed inside the files it was given, but no answer shows
knowledge the inputs don't contain.

## Verdict

**qwen3.8:27b is a clear step up from qwen3.5:27b** at 2.5× the speed: on the one task both ran under the same
conditions (w1, think on, rules v2) it went from 6 compile errors, two critical defects and 50% usable to a
first-try compile with only minor defects. Across all six tasks it compiles first try 10 times in 12 and is right
after small repairs 10 times in 12.

**It is still below Claude Haiku 5.5**, which was correct as written on all 12 runs. qwen3.8's misses are the kind
that pass review only when someone reads closely: an off-by-start ring buffer, an idiom copied from an example
without its context (t2), a near-miss Unity API (t4). Only 4 of its 12 answers were usable as written. For code
that goes into the game, a qwen3.8 answer still needs a careful reviewer. The fair qwen3.5 set (think on, v2) is
still to run; it would settle how much of the gain is the model and how much is think mode plus rules v2.

**Q8_0 on the 5090 (2026-11-08)** got t1 right in all 4 runs where Q4_K_M failed both, and is right after small
repairs on 22 of 24 answers, but at under half the 4090's speed and with the same kinds of near-miss API mistakes.
A `q8_0` KV cache cost nothing measurable: it holds 64k on the GPU and its set scored as well as f16 at 50k. Use
`kv_cache_type=q8_0` on the 5090.


**The first Classrooms fine-tune (2026-11-18) is not better here than the model it came from**: 5 first-try compiles
in 12 against 10, and 3 answers usable as written against 4. It was trained on 69 short excerpt fixes with no
declarations, and it does better than the untuned model on fixes of that kind (the held-out set in
`TheClassrooms-training`), but these six tasks mostly ask for whole new files and it lost ground on them. The next
version (224 examples with declarations attached, up to 7,168 tokens) is the one to judge the approach by.
