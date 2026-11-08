# Local model coding eval: harness moved here, qwen3.8:27b and Haiku 5.5 graded; next rows not run

## Status

**What exists** (2026-11-08): the coding eval in [`eval/`](eval/README.md), moved here from
`TheSneedRooms/Tools/LocalModelEval` (removed there in the same change). [`eval/RESULTS.md`](eval/RESULTS.md) has three
history rows for qwen3.5:27b (not comparable), a graded **qwen3.8:27b Q4_K_M · think · rules v2** row and a measured
**claude-haiku-5-5** baseline, both with two runs per task, plus a verdict: qwen3.8 is far better than qwen3.5 and
2.5× faster, but still below Haiku 5.5 (Haiku right as written 12/12, qwen3.8 4/12). `eval/check.sh` was rechecked on
all 24 stored answers from the new location and a live `run.py` call worked from this repo (2026-11-08).

**What doesn't exist, in the order to do it:**

1. **qwen3.8:27b at Q8** (or Q6): does a better quant fix qwen3.8's misses? Same model, so it isolates the quant.
   Ollama's library has `qwen3.8:27b-q8_0` (30 GB) but no Q6 tag; a Q6_K GGUF from Hugging Face can be pulled as
   `hf.co/<user>/<repo>:Q6_K` (check the repo exists first; the flight sheet's `model=` accepts that form,
   `ollama-hive/h-config.sh`: `model) [[ $2 =~ ^[A-Za-z0-9._:/-]+$ ]]`). Q8 does not fit the 4090 rig (24 GB); on
   a 32 GB 5090 it is borderline at 64k context and may need `num_parallel=1`. `h-run.sh` warns ("only N% on GPU")
   when a model spills out of VRAM.
2. **The fair qwen3.5:27b row** (think on, rules v2, two runs): settles how much of qwen3.8's gain is the model and
   how much is think mode and rules v2. Needs the owner to load qwen3.5:27b.
3. **Other 32 GB candidates**, from web guides (unverified tags): Qwen3-Coder 30B (MoE, ~3B active) and Qwen 3.6
   35B-A3B at Q6_K (~25 GB). MoE models with ~3B active parameters are fast but tend to be weaker at exact API use.

**First thing to do:** ask the owner which model the rig has loaded (`local_llm_status`), then run whichever of the
above that is, as `eval/README.md` "Testing a rig model" says. A new quant of the same tag gets its own results
folder only if its footer name differs; if it doesn't (an `hf.co/...` name does differ, `qwen3.8:27b-q8_0` does
too), rename the folder after the run so it doesn't mix with the Q4 answers.

**Who switches models:** the owner, in the rig's flight sheet. Never change the rig yourself.

**Context:** the owner's question is whether a local model can take over code writing for TheSneedRooms. That
repo's CLAUDE.md still forbids delegating code writing to the local model for normal work; running this eval is not
normal work, and nothing a model writes here goes into the game.

## Running it from a session in this folder

Everything is in `eval/README.md`: what you need, how to run a rig model (`python eval/run.py <task> --think --run
<n>`), how to run a Claude baseline (one Agent per task and run, with the prompt given there), `eval/check.sh` for
the mechanical checks, the rubric, and how to add a row. The one thing outside this repo is the compile step: it needs
a TheSneedRooms checkout whose editor has compiled once (`UNITY_PROJECT`, default
`D:/Dev/TheSneedRooms/master/TheSneedRooms`). Don't open or drive that editor from here; the compile is offline.

## What changed in the move

- `run.py` finds the client as `../client` and runs from `eval/`, so it works from any working directory; it was
  hard-coded to this repo's path and had to run from TheSneedRooms' root.
- `files.txt` paths are relative to `eval/`. The models now see input labels like `tasks/t2/inputs/LootCommand.cs`
  instead of `Tools/LocalModelEval/tasks/...`: 15 fewer prompt tokens on t5, no other difference.
- `compile.sh` takes `UNITY_PROJECT` and absolute (Windows-form, `pwd -W`) paths; MSYS paths (`/i/...`) made csc fail
  with CS2001.
- New `check.sh` runs every mechanical check per answer folder, so grading no longer means retyping the renames
  and diffs.
- `run.py --run <n>` (added 2026-11-07) gives a second run its own folder (`-r<n>`); before, it overwrote the first.

## Where the earlier record was wrong (read before comparing)

- **The first trial's SCORECARD "5 of 5 with think" is wrong:** only t1 and t3 ran with think on for qwen3.5.
- **The qwen3.5 rows don't share conditions** (t1–t5 under rules v1, w1 under v2, think mixed), so only w1 compares
  with qwen3.8 directly. That is why the fair qwen3.5 row is still on the list.
- **The rig "unreachable" errors on 2026-11-07 were not an outage:** with both runs generating, the client's status
  probe timed out for 3 calls; rerunning them worked.
- **The Haiku baseline is not under identical conditions:** it ran as a Claude Code subagent (its system prompt in
  context, inputs read by tool calls, token counts estimated). RESULTS.md says so.

## Verification (for someone who didn't do this)

1. `eval/check.sh eval/results/claude-haiku-5-5`: t1 and t1-r2 print `ALL PASS`, every compile `exit=0`.
2. `eval/check.sh eval/results/qwen3.8-27b`: t1 runs print `240 failures`, `t2-think-r2` and `w1-think-r2` fail to
   compile (4 errors and 1 error), the rest `exit=0`. That matches RESULTS.md.
3. In TheSneedRooms, `Tools/LocalModelEval` and `HANDOFF-local-model-results-master.md` are gone (`git log --stat -1
   -- Tools/LocalModelEval` shows the removal and names this repo).
4. `python eval/run.py t1 --think --run 9` from this repo's root, with a rig up, writes
   `eval/results/<model>/t1-think-r9/`; delete it afterwards.
