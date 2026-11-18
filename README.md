# Ollama-Hive

A Hive OS custom miner that runs Ollama instead of mining, so a rig switches between Octa and serving a local model by
changing flight sheet. `client/local_llm_mcp.py` lets Claude sessions on other PCs delegate to it. With `mode=train` the
same miner fine-tunes a model instead, as one QLoRA run shared between rigs (see [Training](#training)), and
`mode=export` turns the result into an Ollama model (see [Serving a trained model](#serving-a-trained-model)).

NVIDIA only. Ollama runs in the foreground of Hive's miner screen and no system service is installed, so with another
flight sheet active it isn't running and holds no GPU memory.

## Flight sheet

Host `ollama-hive-v0.21.tar.gz` somewhere the rigs can download it (a GitHub release, like the other miners), then make a
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
| `kv_cache_type` | `f16` | `q8_0` or `q4_0` quantizes the context's KV cache: `q8_0` about halves its VRAM with little quality loss, so a larger `num_ctx` fits. Turns on flash attention, which it needs |
| `flash_attention` | Ollama's default | `1` or `0`. Only needed to force it; `0` can't be combined with a quantized `kv_cache_type` |
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

## Training

`mode=train` turns the flight sheet into one worker of a QLoRA fine-tune. Put the same settings on every rig that takes
part; the rigs find each other on the LAN, so no rig is listed anywhere. For example:

```
mode=train
base=unsloth/Qwen3.8-27B-unsloth-bnb-4bit
dataset=http://192.168.1.50:8000/train.jsonl
run_name=unity-1
max_len=auto
```

Each rig loads its own 4-bit copy of the base model on one GPU and joins PyTorch's distributed training with the other
rigs that are training right now. On every step each rig works through its own examples, the adapter's gradients are
averaged over the network, and every rig applies the same update, so all of them hold the same adapter throughout.
The rigs don't have to be alike: a step's examples are shared out by how fast each rig is, so a faster GPU takes more
of them and the rigs finish their parts at about the same time, and a GPU with more memory can take longer examples
(`max_len`).
It is in `<data_dir>/train/runs/<run_name>/adapter` on every rig, written again at every checkpoint.

**The run has no end.** It is made to train for weeks on a dataset that something else keeps adding to (see
[A dataset that grows](#a-dataset-that-grows)): it waits for the dataset to appear, trains every example `epochs`
times, waits for more, and goes on when they arrive. It is also made for the idle time between rentals: the run goes
on with whichever rigs are on this flight sheet, down to one, and pauses only while none is (see
[Rigs leaving and joining](#rigs-leaving-and-joining)).

| Setting | Default | Meaning |
|---|---|---|
| `mode` | `serve` | `train` for a training run; the Ollama settings above are then unused. `export`: see [Serving a trained model](#serving-a-trained-model) |
| `base` | none, required | Hugging Face repo of the base model. A `-bnb-4bit` repo is a ~18 GB download instead of ~56 GB |
| `dataset` | none, required | `http(s)://` URL of a `.jsonl`, or a path on the rig. It doesn't have to be there yet, and one rig reaching it is enough |
| `peers` | none | Only for a network that doesn't carry broadcasts between the rigs: LAN addresses of rigs to tell one by one as well, comma-separated |
| `run_name` | `run1` | Folder of the run, and what rigs on one LAN train together by. A new name starts again from the base model |
| `epochs` | `3` | Times each example is trained |
| `max_len` | `2048` | Longest example in tokens; longer ones are left out, not cut. Lower it if a GPU runs out of memory. One number for every rig, or a limit per GPU memory size in GB: `24:2048,32:6144` gives a 24 GB card 2048 and a 32 GB card 6144. The examples only the larger card can hold go to it, and wait while it is rented. `auto`: every rig measures its own limit, see below |
| `lora_r` | `16` | Adapter rank |
| `bits` | `4` | `4`: the base model in 4 bits per weight, which is what lets a 27B fit a 24 or 32 GB card. `16`: the model as it is stored, for a GPU that holds it whole (about 56 GB for a 27B); `base` is then the full repo, without `-bnb-4bit`. Rigs of one run all use the same |
| `lr` | `2e-4` | Learning rate, reached over 10 warm-up steps and then held: there is no end to come down to |
| `step_size` | `8` | Examples per step, shared between the rigs training at that moment by their speed: one alone does all 8. A higher value gives more to balance with, and less network traffic per example. It replaces `grad_accum`, and a run started with that needs a new `run_name` |
| `save_steps` | `25` | Steps between checkpoints. A stop saves too, so this only matters for a crash or a power cut |
| `train_port` | `29400` | Port the rigs meet on. The firewall rules guard this port in train mode |
| `speedups` | `0` | `1`: install and use optional faster code for parts of some models, see below |
| `torch_index` | `cu128` | PyTorch wheel index. `cu128` needs NVIDIA driver 570 or newer (an RTX 5090 needs it anyway) |

`gpus`, `allow`, `bind`, `data_dir`, `reset_oc` and `allow_docker` work as when serving. `gpus` defaults to `0` here:
one GPU per rig; list more (`gpus=0,1`) for one worker per GPU.

**Dataset.** One JSON object per line: `{"messages": [{"role": "user", "content": "..."}, {"role": "assistant",
"content": "..."}]}` (a system message and earlier turns are fine), or `{"text": "..."}` for raw text. With messages,
the model learns only the last assistant message; what comes before is context. From a worker PC, `python -m
http.server 8000` in the dataset's folder is enough to serve it.

### A dataset that grows

Whatever produces the examples only has to keep one `.jsonl` up to date at `dataset`; the rigs know nothing else
about it.

- **Not there yet:** the rigs load the model and wait (`qlora idle step 0, waiting for the dataset`).
- **New examples:** every rig that can reach `dataset` looks at it once a minute. The one that finds a newer file
  hands it to the others, and all go on with it between two steps, without reloading the model. A rig coming back
  from a rental gets the newest copy from the rigs that are there, so the PC that serves the file can be off for a
  while.
- **What is trained next:** always the examples trained the fewest times, so new ones go first and each ends up
  trained `epochs` times. A step that the new examples don't fill is filled up with older ones, the least trained
  first. Those get an extra pass that way, which also keeps the model from drifting towards the latest examples.
- **Nothing left:** the rigs keep the model loaded and wait (`waiting for new examples`), at idle power.
- **An example is its line.** Appending lines is the normal case. A changed line counts as a new example, and a
  removed one is simply no longer trained; what the model learned from it stays. Lines that are not an example are
  skipped and counted in the log, so a file read while its last line is half written does no harm.
- **Newer** means the file's modification time, as the web server or the rig's disk reports it.

**Having a Claude session keep it.** Serve a folder that holds nothing but the dataset, since the server shows the
whole folder to the LAN, from the PC the session works on: `python -m http.server 8000 --bind <this PC's LAN address>`.
Run that outside the session (its own terminal, or a scheduled task at logon): a server the session starts ends with
the session. Then give the session a standing instruction like this one:

```
Keep a training dataset at D:\train-data\train.jsonl and serve that folder with
"python -m http.server 8000 --bind <LAN address>" if nothing is serving it yet.

After each task you finish, append one line to the file: a JSON object
{"messages": [{"role": "system", "content": ...}, {"role": "user", "content": ...},
{"role": "assistant", "content": ...}]} where the user message is the task with the
code it needed, and the assistant message is the fix as it was finally accepted.
One example per line, UTF-8, no line breaks inside a line. Only append; never
rewrite earlier lines. Keep each example under about 2000 tokens (or the longest
the rigs take, which their progress page shows), and leave out tasks that failed
or were reverted.
```

Three things in it matter to the training: the model learns only the last assistant message, so the fix has to be
there; examples over `max_len` are left out, hence the size limit; and a rewritten line is a new example that gets
trained again, hence append only. Make the user message look like the prompts the local model will get later: that
is what it learns to answer.

What can be used at any time is the `adapter` folder: `mode=export` makes an Ollama model of the run as it stands
(see [Serving a trained model](#serving-a-trained-model)).

**What it installs,** all under `<data_dir>/train` and nothing into the system: `uv`, a Python 3.12 it manages,
PyTorch and the packages in `requirements-train.txt` (about 8 GB), and the base model. A rig switched to another
flight sheet keeps them for the next run.

**`max_len=auto`.** Each rig finds out by itself how long an example its GPU can train. The first time it has the
model loaded for a run, it trains made-up examples of growing length (1024 tokens, 2048, 3072, ...) and reads how much
GPU memory each took, until one would take more than 90% of what was free; nothing is learned from them. That takes a
few minutes, the miner log has every length with its memory, and the result is kept in the run's folder
(`limit-0.json`), so later starts skip it. A rig that still runs out of memory in training lowers its own limit by a
quarter and starts again. The progress page shows every rig's limit. Examples longer than any rig of the run has been
able to take stay in the dataset untrained, and are trained once a rig that can take them joins; over 16384 tokens
they are left out. A length that the growth so far says would not fit is not tried, so the GPU should not actually run out; if the measuring fails for another reason, the rig says why on the progress page and trains with 2048 until its next start. The measurement counts on the GPU being free of anything else, and has not run on a real GPU yet.

**GPU memory.** Beside the model itself (about 16 GB for a 4-bit 27B), the largest cost of an example used to be scoring every position against the vocabulary at once: with Qwen3.8's 248,000 tokens that is some 5 GB per 1000 tokens, and a 24 GB card ran out at 1024. The trainer now scores only the positions that are learned (the answer, not the prompt), 32 at a time, and in the vocabulary layer's own number format: left to PyTorch's automatic mixed precision, every example first made a 2.4 GB copy of that whole layer. The loss and its gradients are the same. Two more things make room without changing what the model computes. The input layer, a second table of the same size that an example reads a few hundred rows of, is kept in the computer's memory instead of the GPU's (2.4 GB of RAM for Qwen3.8, so a rig needs that much to spare). And the weights that are stored as float16 are turned into bfloat16, the format the training computes in, once at the start instead of at every use. A 4-bit 27B with a rank 16 adapter then takes about 18 GB, so a 24 GB card has some 4 GB left for the examples: `lora_r=8` gives it about 1 GB more. PyTorch is also told to keep its GPU memory in a way that lets it give back what it frees (`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`, set by the trainer unless the rig sets its own): with its usual way, loading left 4 GB of a 24 GB card held but unusable. A GPU that runs out of memory doesn't always say so: it also shows as a cuBLAS error, which the trainer takes for the same thing. If an example of 128 tokens still doesn't fit, the rig says so on the progress page.

**`speedups=1`.** Three of every four layers of Qwen3.5/3.8 are of a kind (Gated DeltaNet) that the model's library
runs on plain PyTorch code it calls "correct but much slower" unless the `flash-linear-attention` package is there.
With `speedups=1` the miner installs it (`requirements-speedups.txt`), and every start tries it out on the GPU
before the model is loaded: its fast code is compiled on the rig the first time, which needs a C compiler there (`cc`, `gcc` or `clang`), and if that fails, or the package
didn't install, the rig trains without it and the miner log says why. The rigs of a run don't all have to have it.
With `max_len=auto` a rig measures its limit again when this changes. It has run on an RTX 5090 with a small model of this architecture, not yet with a 27B: turn it on once a rig
trains, and compare the seconds per step on the progress page. The other package
the library asks for, `causal-conv1d`, is not installed: it needs a CUDA compiler on the rig.

**`bits=16`.** With 4 bits the adapter learns beside a rounded copy of the model, and the export then adds it to
the real weights and rounds those again, another way. At full precision it learns beside the weights it is added
to, and only the rounding for serving is left, which the stock model has as well. It takes a GPU with room for the
whole model: `base=Qwen/Qwen3.8-27B bits=16` needs about 56 GB before the first example, so a 96 GB card, which then
has about half the room for examples that it has with 4 bits. The export is the same, and the model it makes serves
on the same cards as before. Run so far on an RTX 5090 with a small model of this architecture only.

**Dashboard:** 1 H/s per GPU while training and 0 while waiting, with the progress in the algo field (`qlora training
step 120, 780 to go loss 1.234`). The loss in each rig's log is over that rig's examples only.

**Progress page.** Every rig on this miner's flight sheet serves one, whatever its mode, at `http://<rig>:29410/` (`train_port` + 10;
the miner log has the link). Open it from any rig, on any device on the LAN: it asks every rig that rig has heard in the last week and draws
them together, so it shows the whole run whichever rigs are training. It has the loss per step, the steps left to train,
the size of the dataset, how long the latest stretch of training took (or has been going), and when each rig was
training, waiting or away. A rig that serves says which model its Ollama has loaded and with how much context, and warns when not all of it is on the GPU: the rest then runs on the CPU, far slower, because the model and its context don't fit the card together. The Hive dashboard says the same beside the miner (`ollama ready, only 72% on GPU`), and the miner log when the model loads. A rig that serves or makes a model says so, with the step of the export it is on and a progress bar for the whole of it, and
shows its GPU memory and miner log like the others; with no training anywhere the page is only that. **Do the rigs hold each other up?** A step
ends when every rig has done its part, so a rig that is done early stands still until the slowest is. The page shows,
per rig, how its step time divides between computing, waiting for the other rigs, and exchanging the gradients over
the network, with the waiting and the network share each marked fine (under 15%), worth a look, or holding the run up
(over 35%), and at the top which rig loses most and what would help. Much waiting means the work isn't shared out
evenly: a higher `step_size` gives more examples to balance with, and a step with one very long example makes the
others wait however it is shared. A large network share is where to see that the link between the rigs is worth
upgrading. Both are measured: the rigs meet once at the end of every step. A rented rig doesn't answer and its part
of the history is missing until it is back; with every rig rented there is no page. Each rig keeps its history in
`<data_dir>/train/runs/<run_name>/history.jsonl`, one line per step.

**When a rig isn't training,** the page says so on that rig, in red, with what went wrong on its last attempt and
how many attempts have failed in a row; it goes away once the rig trains again. Every rig also shows what its GPUs
are doing (load, temperature, power) with a bar of their memory: what this miner holds, what every other process
holds, by name and process number, what is in use without a process being listed for it (the display, or programs
in a container), and what is free. The miner's own part is split by what it goes to: the model itself, the adapter being trained with
its optimizer, the most that training an example took in the last step (with that example's length), and the rest
(PyTorch, the driver, memory kept ready). That is where to see whether something else is taking memory the training
could have. A rig that fails is off its GPU again within seconds, so under a failing rig the page also shows the bar as it was when the miner last held the most memory, with the time. It has a **Miner log** button that shows the end of that rig's
miner log on the page (`http://<rig>:29410/log` gives the same as text), so the reason can be read without logging
in to the rig. The log starts every attempt with the versions of PyTorch and the training packages and the GPU's
free memory. The page is read-only, and like the training
ports it is as open as the rig leaves it: anything on the LAN can read the run's progress.

The loss only says how well the model predicts the examples it is being trained on. It can't tell whether an answer
would compile or fix the task: for that the exported model has to write the answer and something has to check it
(see `eval/`).

**Network.** A rank 16 adapter on a 27B model is about 110 M weights, and each rig sends them once per step (~450 MB).
On 1 Gbit/s that is several seconds a step, so a higher `step_size` means less time on the wire per example; 2.5 or
10 Gbit/s between the rigs helps directly. The firewall rules cover `train_port` only: the GPU-to-GPU traffic uses
ports chosen at run time (the first is one of the 8 after `train_port`), which are as open as the rig leaves them,
and anything `allow` admits can join a run. Rigs take the dataset from each other as well as from `dataset`, so
whatever can join a run can also feed it examples.

### Rigs leaving and joining

A rental, a reboot or a flight sheet switch can take any rig at any time, and it comes back when it is idle again.
No rig has to stay: the run pauses only while every rig is away.

- **A rig is stopped** (Octa stops the miner for a rental): it says so on the LAN at once, every rig finishes the
  example it is on, drops the step in progress and saves, and the rest carry on without it about half a minute
  later, plus the time to load the model again. Only that one step is lost. The stopped rig frees its GPU as soon as
  it has saved, normally within seconds; after 40 s it is killed regardless.
- **A rig comes back:** the others save, and all start again together. It takes the newest checkpoint and the newest
  dataset over the network if its own are older.
- **A rig dies without warning** (power, a crash): the others lose the steps since the last checkpoint
  (`save_steps`), and notice within seconds, or after 20 minutes without a finished step in the worst case.
- **Finding each other:** every rig on the flight sheet says so on the LAN every 2 seconds (a UDP broadcast on
  `train_port`, with the `run_name`), and joins the rigs it hears. Putting the flight sheet on another rig adds it to
  the run and taking it off removes it; nothing else has to change, and a rented rig is simply not heard. The rigs
  must be on one subnet, or reach each other through `peers`.
- **A rig whose training keeps failing** (its GPU out of memory, a broken install) would take the others' workers
  down at every attempt, since they all start again when one joins. After 3 failures in a row it sits out between
  attempts, 30 s longer each time and 10 minutes at most, and the others train meanwhile. A rig that only stopped
  because another one's worker went away is not counted as failing.
- **Who is in charge:** nobody in particular. One rig hosts the meeting on `train_port` (the lowest address, when
  several start together); when it leaves, another takes over within about 10 seconds.
- **Rigs that are never idle together** each continue from their own checkpoint. When two such rigs meet again, the
  one that got further wins and the other's steps since they last trained together are dropped. If that would cost
  you much, keep one rig on this flight sheet.
- Every change of the group costs each rig a reload of the model, a minute or more for a 27B. Rentals that start and
  stop every few minutes would leave little time for training.

**Tested** so far only on CPU, with a small model and two or three rigs on one machine: finding each other by
broadcast, training together, one joining a run in progress, one stopped mid-run (the other went on at the same step), the hosting rig stopped (the other took over),
waiting for a dataset that isn't there yet, taking up examples added during the run (on a rig that can't reach the
source too), a rig with a lower `max_len` limit leaving the long examples to the other and waiting for it when alone,
sharing a step by speed, a rig whose worker can't start being shown with its error and sitting out while the other
trains, and both ending up with identical adapters. On one GPU (an RTX 5090), with a small model and with a small
random model of the Qwen3.5/3.8 architecture: the 4-bit load, the input layer off the GPU, measuring the limit for
`max_len=auto`, training, and `speedups=1`. A 4090 has loaded the 27B itself and reported its memory, and not yet
trained a step. Not yet run at all: how evenly the work is shared between two real GPUs, the broadcast between real
machines, and the traffic between two real GPUs.

## Serving a trained model

Ollama 0.34.1 and newer refuse LoRA adapters, so a run's adapter can't be loaded next to the stock model. `mode=export`
builds it into the model instead, then serves the result like `mode=serve` does:

```
mode=export
model=qwen3.8:27b
full_base=Qwen/Qwen3.8-27B
run_name=unity-1
export_name=qwen3.8-unity:27b
num_ctx=65536
```

The adapter is folded into the base model's own weights, so the new model has exactly as many weights as the stock one:
at the same quantization it takes the same VRAM and runs at the same speed. Only the values differ.

| Setting | Default | Meaning |
|---|---|---|
| `model` | none, required | The stock Ollama model the run was trained from. Its Modelfile (renderer, parser, parameters) and vision projector are reused |
| `full_base` | none, required | Hugging Face repo of the base model at full precision, not the `-bnb-4bit` one used for training |
| `run_name` | `run1` | The run to export: its adapter is fetched from a rig that is training it just now, or else the one on this rig is used |
| `export_name` | the `run_name` | Name of the Ollama model to make |
| `quant` | `Q4_K_M` | Quantization, as `llama-quantize` names them. Use the stock model's to match its VRAM |
| `llama_cpp` | `b12477` | llama.cpp release used to convert and quantize |

The serving settings (`num_ctx`, `kv_cache_type`, ...) apply as usual. On the first start the rig first listens a few seconds
for the rigs that are training `run_name` (they say so on the LAN, which is also how they find each other) and fetches
the adapter from one of them, as it stands at that moment. No address is needed and the training goes on. If none is
heard (a rig whose firewall lets nothing of that in, a network without broadcasts), it asks the progress page of every
address that shares its own first three numbers instead, which takes about ten seconds. If that finds none either, the adapter already in `<data_dir>/train/runs/<run_name>/adapter` on this rig is used: the rig's own if it
trained, or a copy of that folder from a rig that did. Then it:

1. downloads `full_base` one weights file at a time and adds the adapter to each (never more than one file in memory,
   no second copy of the base on disk);
2. converts the merged model to GGUF and quantizes it with llama.cpp, installed under `<data_dir>/train/convert`.
   The converter runs with one thing changed (`export.py convert`): for Qwen3.5/3.8 it would write two pairs of
   weights as one tensor each, which llama.cpp reads and Ollama's own build of it does not;
3. imports it with `ollama create`, using the stock model's Modelfile with only the weights swapped.

Then, and on every later start, it finds `export_name` already there and just serves it, so the flight sheet can stay
on `mode=export`. Plain `mode=serve` with `model=<export_name>` works too once it exists. For a run that has trained
further since, give a new `export_name` (and `ollama rm` the old model when it is no longer wanted).

It needs about 2.4 x the base model's size free on the data drive while it runs (about 135 GB for a 27B model) and
checks before starting; all of it but the final model (17 GB at Q4_K_M) is deleted afterwards. A stopped export
continues where it was, with the adapter it started with. The export runs on each rig that should serve the model.

The merge is done at the base model's own 16-bit precision, like PEFT's and Unsloth's exports.

### As a command, on a rig that serves

To try what a run has learned so far without taking a rig off its flight sheet, run this on a rig that is serving,
from Hive's "Run command" or a shell:

```
/hive/miners/custom/ollama-hive/export-run.sh from=192.168.1.232 export_name=qwen3.8-unity:27b full_base=Qwen/Qwen3.8-27B
```

It fetches the run's adapter from the training rig in `from=` as it stands at that moment (every training rig hands
it out on its progress page's port), does the same work as `mode=export`, and adds the result to that rig's Ollama
as one more model, to be asked for by name. It returns at once and works on in the background; the miner log and the
progress page of that rig say how far it is. The training goes on, and the model the rig serves stays loaded:
everything but the last step runs on the CPU, so the rig is slower meanwhile.

| Setting | Default | Meaning |
|---|---|---|
| `from` | none | A rig that is training the run, `address` or `address:port`. Without it, as for `mode=export`: a rig heard training the `run_name` of this rig's flight sheet, or else the adapter already on this rig |
| `export_name` | the run's name | Name of the Ollama model to make. One that exists is not overwritten: give a new name for a run that has trained further |
| `full_base` | the flight sheet's, of this rig or the training rig | As for `mode=export`. Put `full_base=` on the training flight sheet and the command needs no more than `from=` |
| `run_name`, `model`, `quant`, `llama_cpp` | this rig's flight sheet | As for `mode=export`. `model` is the stock model whose Modelfile is reused: by default the one this rig serves |

Stopping the miner stops it too, as for a rental; the same command then goes on where it was. A download that fails
is tried again by itself, five times two minutes apart. It needs the same free disk space as `mode=export`.

**Tested** in WSL (Ubuntu 20.04) with a small model: the whole flow with llama.cpp's real converter and
`llama-quantize`, against a stand-in for the `ollama` binary, and the merged weights are bit-identical to PEFT's own
merge. A small model of the Qwen3.5/3.8 architecture comes out with the same kinds of tensors, quantized the same
way, as the `qwen3.8:27b` of Ollama's registry. On a rig, a 27B has been merged, converted, quantized and taken in
by Ollama 0.40.16, which then could not load it for the paired tensors above; with that changed, loading it is not
yet seen. A model made before the change is found by its tensors and made again.

## Checks on a rig

```bash
miner log
```

```bash
curl -s http://$(cat /run/ollama-hive/address):11434/api/ps | jq
```

`size_vram` should equal `size`. If not, the model has spilled out of VRAM: lower `num_ctx` or `num_parallel`, or set `kv_cache_type=q8_0`.

## Files

- `h-run.sh`: start-up checks, then runs Ollama, or the training run
- `h-train.sh`: `mode=train`: installs the training environment and runs `meet.py`
- `meet.py`: agrees with the other rigs on who is training now, and starts `train.py` for that group; `meet.py hear` lists the rigs training a run, for the export
- `train.py`: one worker of the QLoRA run
- `status.py`, `status.html`: the progress page of a run, and the rig's part of its data
- `requirements-speedups.txt`: the optional packages of `speedups=1`
- `export-run.sh`: the export as a command, for a rig that serves
- `h-log.sh`: the miner log and the waiting, for `h-run.sh` and `export-run.sh`
- `problem.py`: what stopped a rig's last attempts at training, kept between attempts for the progress page
- `requirements-train.txt`: the Python packages of the training environment
- `h-export.sh`: `mode=export`: makes an Ollama model of a run
- `export.py`: merges the adapter into the base model's weights
- `h-stop.sh`: puts the rig back; safe to run repeatedly
- `h-guard.sh`: runs `h-stop.sh` if `h-run.sh` is killed, and keeps the watchdog off meanwhile
- `h-stats.sh`: dashboard stats
- `h-config.sh`: checks the flight sheet settings and writes `ollama-hive.conf`
- `h-common.sh`: settings and paths they share

Build the archive with `Archive.bat`, then rename it to `ollama-hive-v<version>.tar.gz`: Hive reads the miner's name and
version from the file name.
