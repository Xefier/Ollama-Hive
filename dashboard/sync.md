# Sync local-llm stats to "Local LLM Savings" (https://claude.ai/artifact/UzfFB2BhTVdyGLWagiWimc)

1. `local_llm_stats` with `{"json": true}` (default 14 days; pass `days` to cover a longer gap since the last sync).
   No tool in the session? Run `client\local-llm.cmd stats 14 --json` from the Ollama-Hive repo instead.
2. `ArtifactData` `list`, collection `daily`, `query: {limit: 1000}`: note each doc's `version` (existing docs need it as `if_version`).
   Also `get` `meta/info` for its `version`.
3. From the JSON's `rows`, keep the ones that are new or whose counts differ from the listed doc (usually today and yesterday).
4. One `ArtifactData` `batch` (max 50 writes; split if more):
   - per kept row: `{op: "set", collection: "daily", doc_id: row.id, data: row minus "id", if_version: <listed version, omit if new>}`
     (fields: pc, project, date, calls, prompt_tokens, answer_tokens, saved_tokens, file_bytes, refusals, errors)
   - `{op: "update", collection: "meta", doc_id: "info", data: {last_sync: <now, ISO UTC>, note: <short note>}, if_version: <version>}`
     (`update`, not `set`: it keeps `price_per_m`, which people change on the page).
5. A batch refused for a changed version: re-list and redo only those entries. Rows of other PCs are never touched:
   each PC syncs its own rows (ids are `pc+project+date`, chars outside `A-Za-z0-9_.~:@-` become `_`).
6. The hand-entered seed row `DESKTOP-0Q0U62O+TheSneedRooms+2026-11-01` predates logging; the first sync from that PC that
   has a 2026-11-01 row overwrites it. Then drop "Hand-entered seed" from the note.
