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

On each worker PC, clone or pull this repo, then add the rigs from its `client` folder (needs Claude Code and Python 3.8
or newer; nothing to install):

```bash
client\local-llm add 192.168.1.189
```

| Command | Does |
|---|---|
| `local-llm add <address>[:port] ...` | Adds rigs; port 11434 unless given. Registers the MCP server on first use |
| `local-llm remove <address>[:port] ...` | Removes rigs; removing the last one unregisters the server |
| `local-llm list` | Lists the rigs and whether each answers now (also what a double-click does) |
| `local-llm unregister` | Removes every rig and the server |

It registers for the current Windows user, in every project, and keeps the rig list in that registration only. Rigs are
tried in the order added: the first with a model loaded is used, so list every rig that might be on this flight sheet.
New sessions get `local_llm_status` and `local_llm_ask`. The registration points at this clone's
`client\local_llm_mcp.py`, so a pull updates the client too; after moving the clone, run `add` again. Files are read on the worker PC, only from the session's working directory unless `LOCAL_LLM_ROOTS`
says otherwise, and go to the rig over plain HTTP on your LAN.

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
