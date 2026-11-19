# Classrooms code results (dashboard)

A one-page, phone-friendly dashboard of every measured result of local models writing code for The Classrooms.
It is published as a private claude.ai Artifact:

**https://claude.ai/artifact/SPpkS6eagr9fVJsrjco4Zh**

`index.html` is the whole page. The `DATA` object in its first `<script id="dashboard-data">` block holds every
number; the second script only draws what is in `DATA`. Percentages and differences are worked out on the page from
the counts.

Each section opens with its charts; the explanation, tables, per-task verdicts, caveats and sources follow. Where a
set has a baseline on the same tasks, it is drawn as a difference bar: the baseline is a plain blue bar; the other
set's bar is blue up to the smaller value, then a green segment (better) or a red hatched segment (worse) covering the
difference, labelled with the signed difference in percentage points (or tokens) and both counts. Green always means
better, including where lower is better (wrong answers, could not be spliced, answer tokens).

## Where the numbers come from

Only these files. Never estimate a number that is not in them.

| Page section | `DATA.sections` id | Source |
|---|---|---|
| Code pipeline (local_llm_code) | `pipeline` | `TheClassrooms-training/results/HELDOUT-RESULTS.md`, "The code pipeline: Ollama-Hive's local_llm_code (2026-11-18)" (per-stage tables); per-task cells from `results/qwen3.8-27b-set2-code/VERDICTS.md` and `results/qwen3.8-unity-v2-code/VERDICTS.md`; summary also in `eval/RESULTS.md`, "The code pipeline" |
| Tuned v2 against untuned, 34 tasks | `heldout34` | `HELDOUT-RESULTS.md`, "Tuned model v2 on the 34-task set (2026-11-18)" |
| 14 held-out tasks: arms and tuned v1 | `heldout14` | `HELDOUT-RESULTS.md`, "Scores", "Per task", "Stopping invented names: three arms", "Tuned model v1" |
| Six-task coding test | `six` | `eval/RESULTS.md`, "Comparable sets" (setup, scores, per task) |
| History: qwen3.5:27b | `history` | `eval/RESULTS.md`, "History: not comparable" |

Each entry in `DATA.sets` names its own `source.file` and `source.section`. The one known mismatch between sources:
the tuned v2 VERDICTS.md counts the baseline's unrun practice task as 2 "no answer" (28 of 70); the page uses
HELDOUT-RESULTS.md (28 of 68) and footnotes the per-task cell.

## Adding a result set

1. Add one object to `DATA.sets` with `section` set to an existing section id, plus `id`, `date`, `label`,
   `model`, `conditions` and `source`. Copy the shape of a set already in that section:
   - `pipeline`: `stages.{baseline,context,retry,tool}` with `answers`, `verdicts {same, close, partial, wrong,
     noAnswer}`, `usable`, `compiles`, `unspliced` as `[numerator, denominator]`, `calls`, `promptTokens`,
     `answerTokens`; `extra` (sentences); `perTask` (task id to four cells such as `"close / partial"`).
   - `heldout34` / `heldout14`: `answers`, `verdicts`, the fields named in that section's `table` list, optional
     `group` and `perTask` (task id to `"run 1 / run 2"`).
   - `six`: `scores {firstTry, rightAfterRepairs, correctAsWritten}` as `[n, 12]`, `answerTokens`, `closestClaude`,
     `grader`, setup fields (`quant`, `gpu`, `kv`, `context`, `vram`, `toks`), `perTask` (t1..w1 cells).
   - To draw it as a difference bar, add `compareTo: "<baseline set id>"` and `compareAs: "tuned"` (a fine-tune
     against the untuned set of the same section and conditions) or `"optimisation"` (an arm against its own base on
     the same model and tasks). Compare each tuned version with its own untuned set, never with another version's
     baseline. Which measures are compared is the section's `compare` list (keys: `usable`, `wrong`, `compiles`,
     `unspliced`, `answerTokens`, `firstTry`, `rightAfterRepairs`, `correctAsWritten`). Pipeline stages are always
     drawn against the `baseline` stage of the same model, and a pipeline set with `compareTo` is drawn stage by stage
     against that set.
2. Use `null` for anything the source says was not recorded. Verdict words must be `same`, `close`, `partial`,
   `wrong` or `no answer` for the coloured chips.
3. For a new kind of measurement, add a section to `DATA.sections` (newest first). The `about`, `findings` and
   `caveats` text should come from the source file's own conclusions. A new `kind` needs a renderer in the script.
   Sets from different sections are not comparable; keep them in separate sections.
4. Update `DATA.lastUpdated`.

## Republishing to the same URL

Publish with the Artifact tool, `action: "publish"`, `url: "https://claude.ai/artifact/SPpkS6eagr9fVJsrjco4Zh"`,
`file_path: "D:/Xefier/Ollama-Hive/eval/dashboard/index.html"`. In a new session, read the artifact first
(`action: "read"` with that url); a publish to an artifact the session has not read is refused. If the read shows a
newer version than this file, merge it into `index.html` before publishing. Leave out `icon` so it keeps its icon.
