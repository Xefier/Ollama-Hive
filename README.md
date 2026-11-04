# Ollama-Hive

A Hive OS custom miner that runs Ollama instead of mining, so a rig switches between Octa and serving a local model by
changing flight sheet. `client/local_llm_mcp.py` lets Claude sessions on other PCs delegate to it.

NVIDIA only. Ollama runs in the foreground of Hive's miner screen and no system service is installed, so with another
flight sheet active it isn't running and holds no GPU memory.

## Flight sheet

Host `ollama-hive-v0.3.tar.gz` somewhere the rigs can download it (a GitHub release, like the other miners), then make a
flight sheet with miner **Custom**:

- **Miner name:** `ollama-hive`
- **Installation URL:** the link to the archive
- **Wallet, worker template, pool:** anything Hive accepts; they are ignored
- **Extra config arguments:**

```
model=qwen3.5:27b
num_ctx=32768
num_parallel=2
```

| Setting | Default | Meaning |
|---|---|---|
| `model` | none, required | Ollama model to pull and keep loaded |
| `num_ctx` | `32768` | Context size per request |
| `num_parallel` | `2` | Requests served at once. VRAM use grows with `num_ctx` x `num_parallel` |
| `port` | `11434` | API port |
| `bind` | the rig's private LAN address | Address to listen on. Anything else on that network can reach it unless the firewall limits it |
| `allow` | the rig's own LAN | Comma-separated CIDRs allowed to connect, e.g. `192.168.1.0/24` |
| `data_dir` | see below | Where Ollama and the models are kept |
| `ollama_version` | latest at first install | Pins a version, e.g. `0.14.0` |
| `gpus` | all | Value for `CUDA_VISIBLE_DEVICES`, e.g. `0` |
| `reset_oc` | `0` | `1` resets clock locks and power limits to default at start |
| `allow_docker` | `0` | `1` starts even with Docker containers running |

Ollama and the models go on the DOCKER drive (`/var/lib/docker/ollama-hive`) when `/var/lib/docker` is a mounted drive,
otherwise in `/var/lib/ollama-hive`. They outlive flight sheet switches and new versions of this miner. Wiping the
DOCKER drive only means downloading them again.

## What happens on a switch

**Switching to this flight sheet:**

1. It waits, without touching anything, while any GPU process or Docker container is running, so it can't take a GPU
   from a rental. It says why on the dashboard. **This is only a backstop, since a rental with no container running
   yet can't be detected: check for rentals and take the node off the market first.** If Octa keeps its own containers
   running with no rental, it waits for those too: stop them, or set `allow_docker=1` once you have checked them.
2. It downloads Ollama if needed and warns about power limits left by a mining OC profile.
3. It adds firewall rules so only `allow` can reach the port, trying `iptables` and then `iptables-legacy`, and reads
   them back to confirm they work. Some Hive kernels can't do this. Then it warns on the dashboard and carries on, since
   the server only listens on the private address anyway. If you set `allow` yourself, it won't start without rules
   to enforce it. It never installs `iptables`, because Octa's Docker shares that system.
4. It stops `hive-watchdog`, then starts Ollama on the rig's private LAN address (never `0.0.0.0`), pulls the model and
   loads it. The log says how much is on the GPU. If the rig has no private address, it waits and says so.

**Switching away (or a stop or reboot):** Ollama and its model runner end, the firewall rules go, and the watchdog
starts again if it was running. `h-guard.sh` does the same if `h-run.sh` is killed outright.

**While it runs**, the dashboard shows 1 H/s per GPU when the model is loaded and answering, and 0 otherwise, with the
state in the algo field (`ollama ready`, `ollama pulling`, `ollama waiting`). If the server crashes it restarts.

### Why the watchdog is stopped

Beyond low hashrate, `hive-watchdog` reboots on minimum GPU power and high load, and an idle model can trip the power
check. With it stopped, nothing reboots this rig if a GPU drops out, so keep an eye on the dashboard state.

### OC profile

Hive applies overclocks from the OC profile, not the flight sheet. Mining limits slow a model and can make it unstable.
Either use a stock profile while on this flight sheet or set `reset_oc=1`, and check your Octa settings are back when
you switch away. Fan control stays with Hive.

## Connecting Claude

On each worker PC, clone or pull this repo (needs Claude Code and Python 3.8 or newer; nothing to install). Then either:

- **Ask Claude:** open Claude Code in this repo's folder and say `/local-llm add 192.168.1.189`, or just "add the rig
  at 192.168.1.189". The repo's `local-llm` skill runs the command.
- **Or run it yourself** in PowerShell. It has to run from this repo's folder: from anywhere else PowerShell reports
  that "the module 'client' could not be loaded". Change to the folder first, wherever your clone is:

```powershell
cd "I:\Development\Mining\Hive Custom Miners\Ollama-Hive"
```

```powershell
.\client\local-llm.cmd add 192.168.1.189
```

| Command | Does |
|---|---|
| `local-llm add <address>[:port] ...` | Adds rigs; port 11434 unless given. Registers the MCP server on first use |
| `local-llm remove <address>[:port] ...` | Removes rigs; removing the last one unregisters the server |
| `local-llm list` | Lists the rigs and whether each answers now (also what a double-click does) |
| `local-llm unregister` | Removes every rig and the server |
| `local-llm stats [days] [--json]` | This PC's usage of the local model (see below); `days` defaults to 14 |
| `local-llm calibrate <percent> [--reset <ISO>] [--json]` | API dollars of this PC's Claude Code usage per 1% of the weekly plan limit (see below) |

It registers for the current Windows user, in every project, and keeps the rig list in that registration only. List
every rig that might be on this flight sheet: a rig switched to another flight sheet simply stops answering and is
skipped.

### Which rig answers

Each `local_llm_ask` asks every registered rig at once what it has loaded (2 s timeout each, so any number of rigs costs
one round trip). Rigs that don't answer or have no model loaded are dropped, and so are those whose context can't hold
the request (the same estimate as the refusal: about 3 characters per token, plus 2048 tokens kept for the answer). If
rigs have a model but none fits, the call is refused and the message names the largest context available. Of the rest,
the one with the fewest requests in flight from this PC is chosen, ties broken at random.

In-flight requests are counted from marker files, one per request, in `%LOCALAPPDATA%\local-llm\inflight\<host_port>\`
(`LOCAL_LLM_INFLIGHT` overrides the folder), created before the request and deleted after it, also when it fails. A
marker older than the answer timeout plus a minute is left over from a crash and is deleted rather than counted.
Choosing a rig and creating its marker happen under one lock file, so the sessions of one PC (each runs its own copy of
the client) balance exactly; PCs don't see each other's markers, so across PCs the balance is only statistical, from the
random tie-break.

If the chosen rig fails (no connection, an HTTP error, a broken reply or an empty answer), the next one in the same
order is tried before giving up; the answer's footer names the rig that answered and the ones that failed. A refusal for
size is never retried. `local_llm_status` shows each rig's in-flight count from this PC.

New sessions get `local_llm_status`, `local_llm_ask` and `local_llm_stats`. The client reads files from the session's folder, the Unity
editor logs (`%LOCALAPPDATA%\Unity\Editor`) and Claude's scratch folders (`%LOCALAPPDATA%\Temp\claude`), and nowhere
else; after pulling a client change, run `add` again so the registration picks it up. The registration points at this clone's
`client\local_llm_mcp.py`, so a pull updates the client too; after moving the clone, run `add` again. Files are read on the worker PC, only from the session's working directory unless `LOCAL_LLM_ROOTS`
says otherwise, and go to the rig over plain HTTP on your LAN.

### Usage stats

Every token the model reads is one Claude did not, so the client logs each `local_llm_ask` itself, at no cost to Claude:
one JSON line per call in `%LOCALAPPDATA%\local-llm\stats.jsonl` (`~/.local-llm/stats.jsonl` elsewhere; the
`LOCAL_LLM_STATS` environment variable overrides it). A line holds the time (`ts`, UTC, and `day`, the PC's own date),
`pc`, `project` (the folder of `CLAUDE_PROJECT_DIR`, else of the working directory), `rig`, `model`, `prompt_tokens`,
`answer_tokens`, `saved_tokens` (prompt minus answer, never below 0: the answer still enters Claude's context),
`file_bytes`, `files`, `seconds`, `eval_seconds` (the rig's generation time), `think` and `cut_off`. Each attempt
on a rig is its own line: a request that failed has `error: true` (after a failover, the rig that failed has that line and
the rig that answered the next), and one refused for not fitting any context has `refused: true` with its `estimate` and
the largest `context` available, and names that rig. If the log can't be written the
answer comes back anyway.

Sessions read it with the `local_llm_stats` tool: totals, then one line per project and per day for the last `days`
(default 14), then one per model and rig (calls, tokens read and saved, generation speed in tokens/s); `json: true`
returns the aggregate as JSON, with one row per PC, project and day, for a dashboard. Each row has `rigs`, an object keyed
`"<model> @ <host:port>"` with `calls`, `prompt_tokens`, `answer_tokens`, `saved_tokens` and `seconds` for that rig (calls
refused for size, and calls with no rig available, are in the row's counts but no rig's). From
the shell, `local-llm stats` prints the same summary (it needs only Python, not a registration).

#### Calibrating the weekly percent

To show the saving as a share of the Claude plan's weekly limit, `local-llm calibrate <percent used> --reset <next reset>`
(both from the plan's usage card) sums what this PC's Claude Code messages in that week would cost at API list prices,
read from the transcripts under `~/.claude/projects`, and divides by the percent: `usd_per_pct`, the dollars one percent
is worth. `--since <ISO>` sets the window start directly; with neither, it uses the last 7 days and says so. `--json`
gives `since`, `until`, `percent_used`, `usd_total`, `usd_by_model`, `usd_by_term` (input, output, cache reads, 5-minute
and 1-hour cache writes), `cache_write_tokens`, `cache_read_tokens`, `reads_per_written_token`,
`usd_per_m_in_context`, `messages`, `usd_per_pct`, `unknown_models` and `skipped`. Cache writes are priced by duration,
as the transcripts record them: 5-minute at 1.25 x input, 1-hour at 2 x input (1.25 x when a line doesn't say). The
prices (`CLAUDE_PRICES` in `client/local_llm_mcp.py`) are only a weighting between models; the result is an estimate,
since the plan's accounting is not published. `usd_per_m_in_context` is what a million tokens entering Claude's
context really cost over the window: cache-write plus cache-read dollars per million tokens written, since each token is
written to the cache once and re-read on every later turn (`reads_per_written_token` says how often). It is the value of
a million tokens the local model read instead, so it sets the dashboard's price per million. The dashboard's sync recipe
and page source moved to the `local-llm-dashboard` skill in `Xefier/claude-dashboards`, which says how both numbers
reach the dashboard.

## Checks on a rig

```bash
miner log
```

```bash
curl -s http://$(cat /run/ollama-hive/address):11434/api/ps | jq
```

`size_vram` should equal `size`. If not, the model has spilled out of VRAM: lower `num_ctx` or `num_parallel`.

## Files

- `h-run.sh`: start-up checks, then runs Ollama
- `h-stop.sh`: puts the rig back; safe to run repeatedly
- `h-guard.sh`: runs `h-stop.sh` if `h-run.sh` is killed, and keeps the watchdog off meanwhile
- `h-stats.sh`: dashboard stats
- `h-config.sh`: checks the flight sheet settings and writes `ollama-hive.conf`
- `h-common.sh`: settings and paths they share

Build the archive with `Archive.bat`, then rename it to `ollama-hive-v<version>.tar.gz`: Hive reads the miner's name and
version from the file name.
