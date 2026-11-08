# Local model coding results

Can a local model on the LAN rig take over code writing? (owner, 2026-11-03). Six frozen tasks (`tasks/`), graded
by Claude reading every answer, compiling it offline (`compile.sh`) and, for t1, running `tasks/t1/test`. Tasks and
rubric: `README.md` in this folder.

Cell format: compile result, then verdict. `✓` compiles first try, `✗n` n compile errors (a floor when the compiler
stopped early). Verdicts: `pass` (correct), `minor` (correct, only minor defects), `fixable` (right after at most 2
one-line repairs), `unusable`. A cell with two results is two runs of the same task (the client sends no seed, so
runs differ). `—` not run.

**Closest Claude (est.)** is the Claude model and version whose code on tasks like these the row's results are
closest to: a judgement by the grader (Claude Opus 5.5, 2026-11-07) from the failure kinds (invented APIs, wrong
checks, missed requirements, first-try compile rate), not a measurement. Claude Haiku 5.5 has its own measured row,
which anchors the column; the other entries are still estimates.

## Comparable rows (think on, rules v2, two runs per task)

| Model | Quant | VRAM @64k | tok/s | Think | Rules | t1 | t2 | t3 | t4 | t5 | w1 | First-try compiles | Right after ≤2 one-line repairs | Answer tokens (sum) | Closest Claude (est.) | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.8:27b | Q4_K_M | 17.6 GB | 111–130 | on | v2 | ✓ unusable / ✓ unusable (tests fail, both) | ✓ fixable / ✗4 fixable | ✓ minor / ✓ fixable | ✓ fixable / ✓ fixable | ✓ pass / ✓ minor | ✓ minor / ✗1 fixable | 10/12 | 10/12 (correct as written: 4/12) | 60,261 | Claude 3.5 Sonnet; below Haiku 5.5 (measured) | details below; ~2.5× qwen3.5's speed on the same 4090, w1 in ~1.6 min |
| **claude-haiku-5-5** (baseline) | API | — | — | default | v2 | ✓ pass / ✓ pass | ✓ minor / ✓ minor | ✓ pass / ✓ minor | ✓ pass / ✓ pass | ✓ pass / ✓ pass | ✓ pass / ✓ pass | 12/12 | 12/12 (correct as written: 12/12) | ~22,000 (est. from 75 KB of answers) | Haiku 5.5 (itself) | run as a Claude Code subagent, see **Haiku runs** below; 25–105 s per task |

Not yet run: **qwen3.5:27b · think · v2**, the fair qwen3.5 row (needs the owner to load qwen3.5:27b on the rig).

## History: not comparable (2026-11-03, mixed rules and think modes, one run each)

| Model | Quant | VRAM @64k | tok/s | Think | Rules | t1 | t2 | t3 | t4 | t5 | w1 | First-try compiles | Right after ≤2 one-line repairs | Answer tokens (sum) | Closest Claude (est.) | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5:27b | Q4_K_M | 20.7 GB | 47–49 | off | v1 | ✓ unusable (tests fail) | ✓ minor | ✗1+ unusable | ✗3 fixable | ✗1 fixable | — | 2/5 (t1 compiles but is wrong) | 3/5 (t2, t4, t5) | 7,320 | Claude 3 Haiku | t4 uses bare `activeSelf` (wrong check, 1 critical); t5 deleted `using Fusion` (rules v1 wording) but found `LightService`; t3 invented 4 APIs |
| qwen3.5:27b | Q4_K_M | 20.7 GB | 47–49 | on | v1 | ✓ pass | — | ✗2 fixable | — | — | — | 1/2 | 2/2 | 9,467 | Claude 3.5 Haiku | only t1 and t3 run; t1 ~2.5 min, all tests pass |
| qwen3.5:27b | Q4_K_M | 20.7 GB | 47 | on | v2 | — | — | — | — | — | ✗6 unusable | 0/1 | 0/1 | 10,690 | Claude 3.5 Haiku | rows not clickable, no status tags, project-change hook never subscribed, dead list method; 118 of 234 lines kept (50%) |

Folders: row 1 `results/qwen3.5-27b/t1..t5`, row 2 `t1k`, `t3k`, row 3 `w1`. The trial's own notes:
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
that goes into the game, a qwen3.8 answer still needs a careful reviewer. The fair qwen3.5 row (think on, v2) is
still to run; it would settle how much of the gain is the model and how much is think mode plus rules v2.

