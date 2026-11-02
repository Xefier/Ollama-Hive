# Sync local-llm stats to "Local LLM Savings" (https://claude.ai/artifact/UzfFB2BhTVdyGLWagiWimc)

1. `local_llm_stats` with `{"json": true}` (default 14 days; pass `days` to cover a longer gap since the last sync).
   No tool in the session? Run `client\local-llm.cmd stats 14 --json` from the Ollama-Hive repo instead.
2. `ArtifactData` `list`, collection `daily`, `query: {limit: 1000}`: note each doc's `version` (existing docs need it as `if_version`).
   Also `get` `meta/info` for its `version`.
3. From the JSON's `rows`, keep the ones that are new or whose counts differ from the listed doc (usually today and yesterday).
4. One `ArtifactData` `batch` (max 50 writes; split if more):
   - per kept row: `{op: "set", collection: "daily", doc_id: row.id, data: row minus "id", if_version: <listed version, omit if new>}`
     (fields: pc, project, date, calls, prompt_tokens, answer_tokens, saved_tokens, file_bytes, refusals, errors, rigs;
     `rigs` is an object keyed `"<model> @ <host:port>"` with calls, prompt_tokens, answer_tokens, saved_tokens and
     seconds per rig; compare it too when deciding whether a row changed)
   - `{op: "update", collection: "meta", doc_id: "info", data: {last_sync: <now, ISO UTC>, note: <short note>}, if_version: <version>}`
     (`update`, not `set`: it keeps `price_per_m`, which people change on the page).
5. A batch refused for a changed version: re-list and redo only those entries. Rows of other PCs are never touched:
   each PC syncs its own rows (ids are `pc+project+date`, chars outside `A-Za-z0-9_.~:@-` become `_`).
6. The hand-entered seed row `DESKTOP-0Q0U62O+TheSneedRooms+2026-11-01` predates logging; the first sync from that PC that
   has a 2026-11-01 row overwrites it. Then drop "Hand-entered seed" from the note.

## Calibrating the weekly percent

The page shows "tokens the local model read instead of Claude" as a percent of the Claude plan's weekly limit. Nobody
publishes how many tokens 1% is, so it is estimated from this PC's own Claude Code usage, priced at API list rates (only
as a weighting across models):

1. Read the usage card: in Claude Code, `mcp__ccd_session_mgmt__get_usage` returns `plan.windows[0].percentUsed` and
   `resetsAt` (the NEXT reset, ISO).
2. From the Ollama-Hive repo: `client\local-llm.cmd calibrate <percentUsed> --reset <resetsAt> --json`. It sums the
   API-rate dollars of every Claude Code message in the week before that reset (transcripts under `~/.claude/projects`)
   and returns `usd_per_pct` (total dollars / percent used). Check `unknown_models` is empty (unknown ids are priced as
   Opus 5.5) and `messages` is not 0.
3. In the same `ArtifactData` `batch` as the sync (or alone): `{op: "update", collection: "meta", doc_id: "info",
   data: {usd_per_pct: <result.usd_per_pct>, week_reset: <resetsAt>, price_per_m: <result.usd_per_m_in_context>},
   if_version: <version>}`. The page uses all three. `usd_per_m_in_context` is what a million tokens entering Claude's
   context cost over the window (written to the cache once, then re-read on every later turn: cache-write plus
   cache-read dollars per million written), so it is the value of a million tokens the local model read instead.
   Skip `price_per_m` when it is null (no cache writes in the window).

It is an estimate: the plan's accounting is not published, and only this PC's Claude Code usage is counted (another PC
or claude.ai chats on the same plan make 1% look cheaper than it is; calibrate from the PC that does most of the work).
A calibration early in the week, at a low percent, is noisy: prefer one late in the week. Recalibrate when it drifts,
e.g. once a month or after a plan or price change.

### Reference calibration

Plan week of 2026-10-25 (reset Saturdays 11:59:59 UTC), measured 2026-10-30 22:30 UTC at **99%** of the Ultra
weekly limit: **$4,187** of API-rate use from this PC's Claude Code transcripts (48,869 calls; 98% of the tokens were
cache reads), so **1% = $42.29**. The following 7 days came to $4,341, which agrees. A reading taken early in a week
(17 h in: $323 at 32%, $10.09 per 1%) did not, so calibrate late in the week, never early.
