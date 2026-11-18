#!/usr/bin/env python3
"""One worker of a QLoRA run shared between rigs. meet.py starts it on every rig, for h-train.sh.

Each worker holds its own 4-bit copy of the base model on its GPU. Only the adapter's gradients cross the network:
they are added up over the rigs on every optimizer step (sum_gradients), so every worker ends each step with the same
adapter.

The rigs need not be alike. A step's examples are dealt out by how fast each rig is, so that all finish their part
at about the same time (deal), and max_len can give a GPU with more memory a higher limit: the examples only it can
hold go to it, and wait while it is away. With max_len=auto every rig finds its own limit, by training made-up
examples of growing length on the loaded model until its GPU memory is nearly used (measure_limit).

The run has no end. The dataset grows while it trains: every example is trained --epochs times, the least trained
first, and when all have been the workers stay loaded and wait for more (next_batch). The dataset's source is looked
at every minute, and the rig that finds a newer one hands it to the others (sync_dataset), so only one rig has to
reach it. A source that isn't there yet is the same as an empty one: the workers wait.

Rigs come and go (a rental takes one, it comes back when idle), so nothing here depends on how many take part:
- A step is always step_size examples however many rigs share it, and which examples it takes follows from
  how often each has been trained, which the checkpoint records.
- Every rig saves the adapter to its own disk. On every start the workers compare checkpoints and all continue from
  the furthest one (sync_checkpoint).
- A rig told to stop drops the rest of its part of the step and says so when the rigs next meet, at the end of
  the step; all of them then save without that step. meet.py tells the other rigs at once, so they don't finish
  their parts first.

Every rig keeps a line per step in the run's history.jsonl, which status.py serves to the progress page.

Dataset: JSON lines, each {"messages": [{"role": ..., "content": ...}, ...]} or {"text": "..."}. An example is known
by its line: a changed line is a new example.
"""

import argparse
import email.utils
import hashlib
import io
import json
import math
import os
import re
import signal
import sys
import threading
import time
import traceback
import urllib.request

import problem

VISION_OR_HEAD = re.compile(r"(^|\.)(visual|vision\w*|merger|multi_modal_projector|lm_head|mtp\w*)(\.|$)")
CHUNK = 256 * 1024 * 1024
CHECK = 60          # seconds between looks at the dataset's source
IDLE = 5            # seconds between looks at the other rigs while there is nothing to train
WARMUP_STEPS = 10
# What a worker tells the others where they meet, before a step and after its examples; the highest wins
NEW_DATA, STOP = 1, 2
BUCKET = 32 * 1024 * 1024   # gradient values sent in one go
# Exit codes meet.py knows: stopped for the group to change, and stopped because another rig's worker went away.
# Neither is this rig failing.
REGROUP, PEER_LOST = 75, 76
# How the libraries under PyTorch say that the worker of another rig is gone
PEER_LOST_SIGNS = ("connection closed by peer", "connection reset", "broken pipe", "socket timeout", "nccl",
                   "distnetworkerror", "remote worker")
AUTO = "auto"       # max_len: every rig measures its own limit
AUTO_TOP = 16384    # the longest example a rig tries then, and the longest the run knows of
AUTO_STRIDE = 1024  # tokens between the lengths tried
AUTO_USE = 0.9      # the part of the free GPU memory an example may take: the rest is for what moves around
# Positions of an example scored against the vocabulary in one go. All at once is what the model's own loss does, and
# with a vocabulary of 250,000 that takes some 5 GB per 1000 tokens, more than the rest of the model's work together.
LOSS_CHUNK = 32


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--epochs", type=int, default=3, help="times each example is trained")
    parser.add_argument("--max-len", default="2048",
                        help="longest example in tokens, or by GPU memory in GB: 24:2048,32:6144, or auto")
    parser.add_argument("--gpu-gb", type=int, help="this rig's GPU memory, instead of asking the GPU")
    parser.add_argument("--limit", type=int, help="this rig's limit under max_len=auto, instead of measuring it")
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--step-size", type=int, default=8, help="examples per step, shared by the rigs present")
    parser.add_argument("--save-steps", type=int, default=25)
    parser.add_argument("--seed", type=int, default=3407)
    parser.add_argument("--state-file")
    parser.add_argument("--status-file")
    parser.add_argument("--problem-file", help="where to say what went wrong, for the progress page")
    parser.add_argument("--memory-file", help="where to say what the GPU memory goes to, for the progress page")
    parser.add_argument("--speedups", action="store_true",
                        help="use the optional faster code of requirements-speedups.txt where it is installed and works")
    parser.add_argument("--prepare", action="store_true",
                        help="download the base model and the dataset if it is there, report on it, then exit")
    return parser.parse_args()


def log(text):
    print(f"[train r{os.environ.get('RANK', '-')}] {text}", flush=True)


def write_line(path, text):
    if not path:
        return
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    os.replace(path + ".tmp", path)


def dataset_path(args):
    """The run's own copy of the dataset: what this rig trains on, whether it came from the source or another rig."""
    return os.path.join(args.run_dir, "dataset.jsonl")


def dataset_meta(args):
    """version: when the source was last changed, as the source says, so the same on every rig. -1 with no copy."""
    try:
        with open(dataset_path(args) + ".json", encoding="utf-8") as handle:
            meta = json.load(handle)
        if os.path.exists(dataset_path(args)):
            return meta
    except (OSError, ValueError):
        pass
    return {"version": -1, "sha": ""}


def write_dataset(args, data, version, modified=None):
    with open(dataset_path(args) + ".tmp", "wb") as handle:
        handle.write(data)
    os.replace(dataset_path(args) + ".tmp", dataset_path(args))
    write_line(dataset_path(args) + ".json", json.dumps(
        {"version": version, "sha": hashlib.sha256(data).hexdigest(), "modified": modified}))


def refresh_dataset(args):
    """Takes the dataset from its source if that is newer than the run's copy. False when it isn't, and when the
    source can't be read: it may not exist yet, or the PC serving it may be off."""
    have = dataset_meta(args)
    modified = None
    try:
        if re.match(r"https?://", args.dataset):
            request = urllib.request.Request(args.dataset)
            if have.get("modified"):
                # Unchanged is then answered without the file (an error 304, caught below)
                request.add_header("If-Modified-Since", have["modified"])
            with urllib.request.urlopen(request, timeout=20) as response:
                data = response.read()
                modified = response.headers.get("Last-Modified")
            version = int(email.utils.parsedate_to_datetime(modified).timestamp()) if modified else int(time.time())
        else:
            version = int(os.path.getmtime(args.dataset))
            if version < have["version"]:
                return False
            with open(args.dataset, "rb") as handle:
                data = handle.read()
    except (OSError, ValueError):
        return False
    if version < have["version"] or hashlib.sha256(data).hexdigest() == have["sha"]:
        return False
    # Changed twice within the second the source's clock counts in
    version = max(version, have["version"] + 1)
    write_dataset(args, data, version, modified)
    return True


def read_rows(data):
    """The examples by key. A line that is no example is left out instead of stopping the run: the file is written to
    while the run reads it, and its last line may be half there."""
    rows = {}
    bad = 0
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(row, dict) and ("messages" in row or "text" in row):
            rows[hashlib.sha1(line).hexdigest()[:16]] = row
        else:
            bad += 1
    return rows, bad


def parse_limits(spec):
    """max_len as {GPU memory in GB: tokens}; a plain number is the limit of every GPU."""
    if ":" not in spec:
        return {0: int(spec)}
    return {int(memory): int(tokens) for memory, tokens in (part.split(":") for part in spec.split(","))}


def limit_for(limits, memory):
    """The limit of the largest memory size this GPU reaches, or of the smallest one listed if it reaches none."""
    reached = [size for size in limits if size <= memory]
    return limits[max(reached) if reached else min(limits)]


def longest(spec):
    """The longest example any rig of the run could take: what every rig keeps of the dataset."""
    return AUTO_TOP if spec == AUTO else max(parse_limits(spec).values())


def find_limit(peak_at, budget, top=AUTO_TOP, stride=AUTO_STRIDE):
    """The longest example that fits in budget bytes, given peak_at(length): the memory an example of that length
    takes, or None when it ran out. Goes up a stride at a time until one doesn't fit, then tries once in between,
    where the growth so far says the budget is reached. A length that the growth so far says is over the budget is
    not tried: running a GPU out of memory is what this is for avoiding. 0 when not even the first length fits."""
    fits = []
    over = None
    for length in range(stride, top + 1, stride):
        if len(fits) > 1 and fits[-1][1] + (fits[-1][1] - fits[-2][1]) > budget:
            over = length
            break
        peak = peak_at(length)
        if peak is None or peak > budget:
            over = length
            break
        fits.append((length, peak))
    if not fits:
        # Shorter than a stride then, rather than nothing: the rig still trains the examples that short
        for length in (stride // 2, stride // 4, stride // 8):
            peak = peak_at(length)
            if peak is not None and peak <= budget:
                return length
        return 0
    length, peak = fits[-1]
    if over is None or len(fits) < 2:
        return length
    per_token = (peak - fits[-2][1]) / (length - fits[-2][0])
    if per_token <= 0:
        return length
    between = min(int(length + (budget - peak) / per_token), over - 1) // 64 * 64
    if between > length:
        peak = peak_at(between)
        if peak is not None and peak <= budget:
            return between
    return length


def deal(lengths, limits, speeds):
    """Which examples of a step each rig takes, as positions in lengths: the same answer on every rig. Longest
    first, each to the rig that would be done with it soonest among those whose limit it fits, so the rigs finish
    together as nearly as the examples allow. A rig can come away with none."""
    parts = [[] for _ in limits]
    busy = [0.0] * len(limits)
    for position in sorted(range(len(lengths)), key=lambda position: (-lengths[position], position)):
        length = lengths[position]
        rig = min((rig for rig, limit in enumerate(limits) if length <= limit),
                  key=lambda rig: (busy[rig] + length / speeds[rig], rig))
        parts[rig].append(position)
        busy[rig] += length / speeds[rig]
    return parts


def encode(tokenizer, row):
    """Token ids and labels. With messages ending in an assistant turn, only that turn is learned: everything before
    it is masked, so the model isn't trained to write the prompts."""
    if "text" in row:
        ids = tokenizer(row["text"], add_special_tokens=False)["input_ids"]
        return ids, list(ids)
    messages = row["messages"]
    full = tokenizer.apply_chat_template(messages, tokenize=False)
    ids = tokenizer(full, add_special_tokens=False)["input_ids"]
    labels = list(ids)
    if messages and messages[-1].get("role") == "assistant":
        prompt = tokenizer.apply_chat_template(messages[:-1], tokenize=False, add_generation_prompt=True)
        # The generation prompt may open a think block the full text continues differently, hence the common part
        shared = os.path.commonprefix([full, prompt])
        shared_ids = tokenizer(shared, add_special_tokens=False)["input_ids"]
        masked = 0
        while masked < min(len(shared_ids), len(ids)) and shared_ids[masked] == ids[masked]:
            masked += 1
        if masked < len(ids):
            labels[:masked] = [-100] * masked
    return ids, labels


def encode_all(tokenizer, data, max_len, encoded):
    """The dataset's examples as token ids by key, and a line on what was left out. Examples over max_len are left
    out, not cut: an answer cut off halfway teaches the model to stop halfway. encoded keeps what earlier calls
    worked out, so a dataset that grew costs only its new lines."""
    rows, bad = read_rows(data)
    examples = {}
    too_long = 0
    for key, row in rows.items():
        if key not in encoded:
            try:
                ids, labels = encode(tokenizer, row)
            except Exception:  # messages the chat template can't take
                ids = []
            encoded[key] = (ids, labels) if 1 < len(ids) <= max_len else len(ids)
        if isinstance(encoded[key], tuple):
            examples[key] = encoded[key]
        elif encoded[key] > max_len:
            too_long += 1
        else:
            bad += 1
    return examples, (f"{len(examples)} examples, {sum(len(ids) for ids, _ in examples.values())} tokens; "
                      f"{too_long} left out for being over max_len={max_len}, {bad} for not being an example")


def fingerprint(args, torch_version):
    """What every rig of a run must agree on. A checkpoint also carries it, so a run_name can't continue with other
    settings. Not the dataset: that changes during a run, and the rigs pass it on (sync_dataset)."""
    parts = [args.base, args.epochs, args.max_len, args.lora_r, args.lr, args.step_size,
             args.seed, torch_version]
    return int(hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:15], 16)


def share(dist, torch, device, rank, world, value):
    """Every rig's value, by rank."""
    values = torch.zeros(world, dtype=torch.float64, device=device)
    values[rank] = value
    dist.all_reduce(values)
    return values.tolist()


def sum_gradients(dist, torch, parameters):
    """Each rig comes with the gradients of its own examples and leaves with the sum of every rig's. A rig that had
    no example in the step brings zeros."""
    bucket = []
    for number, parameter in enumerate(parameters):
        bucket.append(parameter)
        if sum(p.numel() for p in bucket) < BUCKET and number + 1 < len(parameters):
            continue
        flat = torch.cat([(torch.zeros_like(p) if p.grad is None else p.grad).reshape(-1).float() for p in bucket])
        dist.all_reduce(flat)
        start = 0
        for p in bucket:
            p.grad = flat[start:start + p.numel()].view_as(p).to(p.dtype)
            start += p.numel()
        bucket = []


def split_model(model):
    """The model in two: what turns tokens into hidden states (adapter included), and the layer that scores a hidden
    state against the vocabulary. None for a model that isn't built that way."""
    whole = model.get_base_model() if hasattr(model, "get_base_model") else model
    body = getattr(whole, getattr(whole, "base_model_prefix", ""), None)
    head = whole.get_output_embeddings()
    return (body, head) if body is not None and body is not whole and head is not None else None


def example_loss(torch, parts, ids, labels):
    """The model's loss on one example: how well each labelled token is predicted from those before it, averaged.
    The same number as model(input_ids=ids, labels=labels).loss, on far less memory: only the labelled positions are
    scored, LOSS_CHUNK at a time, and the scores of a chunk are worked out again for the gradient instead of all
    being kept until then."""
    from torch.utils.checkpoint import checkpoint

    body, head, table = parts
    kind = next(head.parameters()).dtype
    if table is None:
        hidden = body(input_ids=ids).last_hidden_state[0, :-1]
    else:
        # The input layer was taken off the GPU (lighten): looked up where it is, and the result brought over
        looked_up = table(ids.to(table.weight.device)).to(ids.device, kind)
        hidden = body(inputs_embeds=looked_up).last_hidden_state[0, :-1]
    targets = labels[0, 1:]
    labelled = (targets != -100).nonzero().squeeze(1)

    def chunk_loss(states, wanted):
        # In the vocabulary layer's own number format, and out of autocast's hands: autocast would first make a copy
        # of the whole layer in its format, 2.4 GB for a vocabulary of 250,000, however short the example
        with torch.autocast(states.device.type, enabled=False):
            return torch.nn.functional.cross_entropy(head(states.to(kind)).float(), wanted, reduction="sum")

    total = hidden.new_zeros((), dtype=torch.float32)
    for start in range(0, len(labelled), LOSS_CHUNK):
        positions = labelled[start:start + LOSS_CHUNK]
        total = total + checkpoint(chunk_loss, hidden[positions], targets[positions], use_reentrant=False)
    return total / max(1, len(labelled))


def share_vocabulary(torch, model):
    """Makes the vocabulary layer and the input layer one again where they hold the same numbers twice: they are
    one table by design, 2.4 GB for a vocabulary of 250,000, and loading can leave two copies. Neither is trained."""
    parts = split_model(model)
    if not parts or not hasattr(parts[1], "weight"):
        return
    head, table = parts[1], model.get_input_embeddings()
    if (head.weight.data_ptr() == table.weight.data_ptr() or head.weight.shape != table.weight.shape
            or head.weight.dtype != table.weight.dtype or head.weight.device != table.weight.device):
        return
    # Compared a piece at a time: all at once would take a third copy's worth of memory
    rows = 4096
    if all(torch.equal(head.weight[start:start + rows], table.weight[start:start + rows])
           for start in range(0, head.weight.shape[0], rows)):
        size = head.weight.numel() * head.weight.element_size()
        head.weight = table.weight
        torch.cuda.empty_cache()
        log(f"The vocabulary layer was a second copy of the input layer: made one of them, {size / 2 ** 30:.1f} GB freed")


def lighten(torch, model):
    """Makes room on the GPU without changing what the model computes. Returns the input layer if it was moved off.
    - The input layer is a table with a row per token of the vocabulary, 2.4 GB for 250,000, of which an example
      reads a few hundred rows: it goes to the computer's memory, and only the rows read come back.
    - Weights stored as float16 become bfloat16, the format the training computes in: left as they are, each is
      copied into that format every time it is used, the vocabulary layer's 2.4 GB included."""
    table, head = model.get_input_embeddings(), model.get_output_embeddings()
    moved = None
    if head is None or getattr(head, "weight", None) is None or head.weight.data_ptr() != table.weight.data_ptr():
        table.to("cpu")
        moved = table
        torch.cuda.empty_cache()
    for parameter in model.parameters():
        if parameter.dtype == torch.float16 and parameter.device.type == "cuda":
            parameter.data = parameter.data.to(torch.bfloat16)
    # The 4-bit layers unpack their weights into the format they were saved with, float16 here: the same copying
    for module in model.modules():
        if getattr(module, "compute_dtype", None) == torch.float16:
            module.compute_dtype = torch.bfloat16
    torch.cuda.empty_cache()
    return moved


def out_of_memory(torch, error):
    """Whether an error is the GPU running out of memory. Not always said as torch.OutOfMemoryError: the libraries
    under PyTorch that find no room for their own work say it their own way, as a cuBLAS or cuDNN failure."""
    text = str(error).lower()
    return isinstance(error, torch.OutOfMemoryError) or (
        isinstance(error, RuntimeError) and any(sign in text for sign in ("out of memory", "cublas", "cudnn", "alloc")))


def describe_memory(torch, model, parts):
    """A line on what the loaded model's GPU memory is made of, for whoever has to find room."""
    sizes = {}
    seen = set()
    for tensor in [*model.parameters(), *model.buffers()]:
        if tensor.device.type == "cuda" and tensor.data_ptr() not in seen:
            seen.add(tensor.data_ptr())
            name = "4-bit weights" if tensor.dtype == torch.uint8 else f"{str(tensor.dtype).replace('torch.', '')} weights"
            sizes[name] = sizes.get(name, 0) + tensor.numel() * tensor.element_size()
    text = ", ".join(f"{size / 2 ** 30:.1f} GB of {name}" for name, size in sorted(sizes.items(), key=lambda item: -item[1]))
    if parts:
        weight = next(parts[1].parameters())
        table = model.get_input_embeddings().weight
        where = ("shared with the input layer" if weight.data_ptr() == table.data_ptr() else
                 "the input layer is as much again and in the computer's memory" if table.device.type == "cpu" else
                 "the input layer is as much again")
        text += (f"; the vocabulary layer is {weight.numel() * weight.element_size() / 2 ** 30:.1f} GB of that in "
                 f"{str(weight.dtype).replace('torch.', '')}, {where}")
    return text


def measure_limit(torch, tokenizer, parameters, device, loss_of, reserve, say, tried):
    """The longest example this GPU can train with the model as loaded: see find_limit. Nothing is learned from the
    made-up examples. loss_of: the loss of an example, as the training works it out. reserve: bytes the training
    will take that aren't taken yet. say: where to tell how it is going. tried: called after every length."""
    import gc

    torch.cuda.empty_cache()
    in_use, free = torch.cuda.memory_allocated(device), torch.cuda.mem_get_info(device)[0]
    budget = in_use + AUTO_USE * (free - reserve)
    # An ordinary word over and over: memory goes by length, and a made-up token could be one the model reads as
    # the place of an image
    word = tokenizer(" the", add_special_tokens=False)["input_ids"][-1]

    def peak_at(length):
        torch.cuda.reset_peak_memory_stats(device)
        ids = loss = None
        try:
            ids = torch.full((1, length), word, device=device)
            loss = loss_of(ids, ids)
            loss.backward()
            peak = torch.cuda.max_memory_allocated(device)
        except RuntimeError as error:
            if not out_of_memory(torch, error):
                raise
            log(f"  {str(error).splitlines()[0][:300]}")
            # Where it asked for the memory: the innermost places in the code
            log("  at " + " < ".join(f"{os.path.basename(frame.filename)}:{frame.lineno} {frame.name}"
                                    for frame in reversed(traceback.extract_tb(error.__traceback__)[-4:])))
            peak = None
        ids = loss = None
        for parameter in parameters:
            parameter.grad = None
        # What the failed attempt held is only let go once its error is gone, hence after the except block
        gc.collect()
        torch.cuda.empty_cache()
        say(f"measuring: {length} tokens " + ("ran out of memory" if peak is None else f"take {peak / 2 ** 30:.1f} GB"))
        tried(length)
        return peak

    log(f"The model takes {in_use / 2 ** 30:.1f} GB and {free / 2 ** 30:.1f} GB is free, of which "
        f"{reserve / 2 ** 30:.1f} GB is kept for the optimizer and the exchange of gradients")
    say(f"measuring the longest example this GPU can train: up to {budget / 2 ** 30:.1f} GB may be used")
    return find_limit(peak_at, budget)


speedups_in_use = []  # the names of the optional packages this worker uses


def gpu_name(torch, device):
    """What a measured limit holds for: this GPU, with or without the speed-ups, which use memory differently."""
    properties = torch.cuda.get_device_properties(device)
    return ", ".join([properties.name, str(properties.total_memory), *speedups_in_use])


def set_up_speedups(torch, wanted, device, cuda):
    """flash-linear-attention is used by the model's library whenever it can be imported, so this decides it before
    the model is: tried out on the GPU when wanted, and put out of reach when not wanted or not working. Its fast
    code is compiled on the rig the first time it runs, which is where it would fail."""
    def put_out_of_reach():
        for name in [name for name in sys.modules if name == "fla" or name.startswith("fla.")]:
            del sys.modules[name]
        sys.modules["fla"] = None

    if not (wanted and cuda):
        put_out_of_reach()
        return
    try:
        import importlib.metadata

        from fla.ops.gated_delta_rule import chunk_gated_delta_rule

        query, key, value = (torch.randn(1, 128, 2, 16, device=device, requires_grad=True) for _ in range(3))
        decay = -torch.rand(1, 128, 2, device=device)
        beta = torch.rand(1, 128, 2, device=device)
        result = chunk_gated_delta_rule(query, key, value, decay, beta)[0]
        result.sum().backward()
        if not (torch.isfinite(result).all() and torch.isfinite(query.grad).all()):
            raise ValueError("its result is not a number")
        speedups_in_use.append(f"flash-linear-attention {importlib.metadata.version('flash-linear-attention')}")
        log(f"Speed-ups: {speedups_in_use[-1]} works here and is used")
    except ImportError:
        log("Speed-ups: flash-linear-attention is not installed (see the install further up): training without it")
        put_out_of_reach()
    except Exception as error:
        traceback.print_exc()
        log(f"Speed-ups: flash-linear-attention failed its try-out ({type(error).__name__}: {str(error)[:200]}): "
            "training without it")
        put_out_of_reach()


def limit_path(args, local_rank):
    return os.path.join(args.run_dir, f"limit-{local_rank}.json")


def own_auto_limit(torch, args, tokenizer, parameters, device, cuda, local_rank, writer, loss_of, reserve, tried):
    """This GPU's limit under max_len=auto: measured once per run and GPU, and kept in the run's folder."""
    if args.limit is not None:
        return args.limit
    if not cuda:
        log("max_len=auto measures GPU memory and there is no GPU here: taking 2048")
        return 2048
    try:
        with open(limit_path(args, local_rank), encoding="utf-8") as handle:
            kept = json.load(handle)
        if kept["gpu"] == gpu_name(torch, device):
            return int(kept["limit"])
    except (OSError, ValueError, KeyError, TypeError):
        pass

    def say(text):
        log(text[0].upper() + text[1:])
        if writer:
            write_line(args.status_file, text)

    if writer:
        write_line(args.state_file, "measuring")
    try:
        limit = measure_limit(torch, tokenizer, parameters, device, loss_of, reserve, say, tried)
    except Exception as error:
        # Training goes on at the usual limit rather than not at all, and the next start measures again
        traceback.print_exc()
        say(f"measuring failed ({type(error).__name__}: {str(error)[:200]}): taking 2048 tokens for now")
        return 2048
    if not limit:
        sys.exit(f"Not even an example of {AUTO_STRIDE // 8} tokens fits on this GPU beside the model: "
                 "free its memory, or use a smaller base model or lora_r")
    say(f"this GPU takes examples up to {limit} tokens")
    write_line(limit_path(args, local_rank), json.dumps({"gpu": gpu_name(torch, device), "limit": limit}))
    return limit


def lower_auto_limit(torch, args, device, local_rank, limit):
    """After running out of memory at this GPU's limit under max_len=auto: the next start takes a quarter less."""
    lowered = int(limit * 0.75)
    write_line(limit_path(args, local_rank), json.dumps({"gpu": gpu_name(torch, device), "limit": lowered}))
    return lowered


def all_equal(dist, torch, value, device):
    high = torch.tensor([value], dtype=torch.int64, device=device)
    low = high.clone()
    dist.all_reduce(high, op=dist.ReduceOp.MAX)
    dist.all_reduce(low, op=dist.ReduceOp.MIN)
    return high.item() == low.item(), high.item()


def furthest(dist, torch, device, rank, world, score):
    """Whether every worker has the same score, the highest score, and the lowest rank that has it."""
    same, best = all_equal(dist, torch, score, device)
    source = torch.tensor([rank if score == best else world], dtype=torch.int64, device=device)
    dist.all_reduce(source, op=dist.ReduceOp.MIN)
    return same, best, int(source.item())


def broadcast_bytes(dist, torch, device, rank, source, blob):
    """Sends the source rank's blob to every worker, and returns it on each."""
    size = torch.tensor([len(blob)], dtype=torch.int64, device=device)
    dist.broadcast(size, source)
    received = bytearray()
    for start in range(0, int(size.item()), CHUNK):
        length = min(CHUNK, int(size.item()) - start)
        part = torch.empty(length, dtype=torch.uint8, device=device)
        if rank == source:
            part.copy_(torch.frombuffer(bytearray(blob[start:start + length]), dtype=torch.uint8))
        dist.broadcast(part, source)
        if rank != source:
            received += part.cpu().numpy().tobytes()
        del part
    return blob if rank == source else bytes(received)


def read_file(path):
    with open(path, "rb") as handle:
        return handle.read()


def sync_dataset(dist, torch, args, device, rank, world, writer):
    """Every worker gets the newest dataset any rig here has, as bytes: empty when none has one yet."""
    have = dataset_meta(args)
    score = -1 if have["version"] < 0 else have["version"] << 28 | int(have["sha"][:7], 16)
    same, best, source = furthest(dist, torch, device, rank, world, score)
    if best < 0:
        return b""
    if same:
        return read_file(dataset_path(args))
    data = broadcast_bytes(dist, torch, device, rank, source, read_file(dataset_path(args)) if rank == source else b"")
    if score != best:
        log(f"Took the dataset from rank {source}")
        if writer:
            write_dataset(args, data, best >> 28)
    return data


def local_checkpoint_seen(args, print_of_settings):
    meta_path = os.path.join(args.run_dir, "checkpoint.json")
    if not (os.path.exists(meta_path) and os.path.exists(os.path.join(args.run_dir, "checkpoint.pt"))):
        return -1
    with open(meta_path, encoding="utf-8") as handle:
        meta = json.load(handle)
    if meta.get("fingerprint") != print_of_settings:
        sys.exit(f"{args.run_dir} holds a checkpoint made with another base model or other settings: "
                 "set a new run_name, or delete that folder to start this one again")
    return int(meta["seen"])


def write_checkpoint(args, blob, seen, print_of_settings):
    path = os.path.join(args.run_dir, "checkpoint.pt")
    with open(path + ".tmp", "wb") as handle:
        handle.write(blob)
    os.replace(path + ".tmp", path)
    write_line(os.path.join(args.run_dir, "checkpoint.json"),
               json.dumps({"seen": seen, "fingerprint": print_of_settings}))


def sync_checkpoint(dist, torch, args, device, rank, world, writer, print_of_settings):
    """Every worker continues from the furthest checkpoint any rig here has. Rigs that train together save together,
    so they normally all have it; one that was away, or is new to the run, gets it over the network from the lowest
    rank that has it. A rig that trained alone meanwhile and got less far loses that stretch."""
    local = local_checkpoint_seen(args, print_of_settings)
    same, best, source = furthest(dist, torch, device, rank, world, local)
    if best < 0:
        return None
    path = os.path.join(args.run_dir, "checkpoint.pt")
    if same:
        return torch.load(path, map_location="cpu", weights_only=True)
    blob = broadcast_bytes(dist, torch, device, rank, source, read_file(path) if rank == source else b"")
    if rank != source:
        log(f"Took the checkpoint at {best} examples from rank {source} (this rig was at {local})")
        if writer:
            write_checkpoint(args, blob, best, print_of_settings)
    return torch.load(io.BytesIO(blob), map_location="cpu", weights_only=True)


def load_model(torch, args, device, cuda):
    import transformers

    kwargs = {"device_map": {"": device}}
    if cuda:
        kwargs["dtype"] = torch.bfloat16
        kwargs["quantization_config"] = transformers.BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16)
    # The text-only class first: it leaves the vision tower off the GPU where the architecture has one
    problem = None
    for name in ("AutoModelForCausalLM", "AutoModelForMultimodalLM", "AutoModelForImageTextToText"):
        loader = getattr(transformers, name, None)
        if loader is None:
            continue
        try:
            model, info = loader.from_pretrained(args.base, output_loading_info=True, **kwargs)
        except ValueError as error:
            problem = error
            continue
        # A class that doesn't match the checkpoint loads with fresh random weights and only warns
        missing = [key for key in info.get("missing_keys", []) if not VISION_OR_HEAD.search(key)]
        if missing:
            problem = ValueError(f"{name} left {len(missing)} weights unset, e.g. {missing[0]}")
            del model
            continue
        log(f"Loaded {args.base} with {name}")
        return model
    sys.exit(f"Could not load {args.base}: {problem}")


def add_adapter(torch, model, args):
    """LoRA on every linear layer of the language model. The names are read off the model instead of listed, because
    they differ between architectures (Qwen3.5/3.8 mix attention with Gated DeltaNet layers)."""
    import peft

    for parameter in model.parameters():
        parameter.requires_grad = False
    model.config.use_cache = False
    try:
        # Renamed in transformers 5
        (getattr(model, "activation_checkpointing_enable", None) or model.gradient_checkpointing_enable)()
        # Checkpointed blocks need an input that requires grad, or no gradient reaches the adapter
        model.enable_input_require_grads()
    except Exception as error:  # training still works without it, on far more GPU memory
        log(f"Could not turn on activation checkpointing ({error}): expect to need a lower max_len")
    targets = [name for name, module in model.named_modules()
               if isinstance(module, torch.nn.Linear) and not VISION_OR_HEAD.search(name)]
    if not targets:
        sys.exit("Found no linear layers to adapt in the model")
    config = peft.LoraConfig(r=args.lora_r, lora_alpha=args.lora_r, lora_dropout=0.0, bias="none",
                             target_modules=targets, task_type="CAUSAL_LM")
    model = peft.get_peft_model(model, config)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    log(f"Adapter: rank {args.lora_r} on {len(targets)} layers, {trainable / 1e6:.1f} M weights "
        f"({trainable * 4 / 1e6:.0f} MB sent per rig on every step)")
    return model


def versions():
    import importlib.metadata

    found = []
    for package in ("torch", "transformers", "peft", "bitsandbytes", "accelerate"):
        try:
            found.append(f"{package} {importlib.metadata.version(package)}")
        except importlib.metadata.PackageNotFoundError:
            found.append(f"{package} missing")
    return ", ".join(found)


def main(args):
    os.makedirs(args.run_dir, exist_ok=True)

    from transformers import AutoTokenizer

    if args.prepare:
        from huggingface_hub import snapshot_download

        snapshot_download(args.base)
        refresh_dataset(args)
        if dataset_meta(args)["version"] < 0:
            log(f"No dataset at {args.dataset} yet: the run waits for it, or gets it from another rig")
        else:
            report = encode_all(AutoTokenizer.from_pretrained(args.base), read_file(dataset_path(args)),
                                longest(args.max_len), {})[1]
            log(f"Dataset: {report}")
        return

    import torch
    import torch.distributed as dist

    cuda = torch.cuda.is_available()
    rank = int(os.environ.get("RANK", 0))
    local_rank = int(os.environ.get("LOCAL_RANK", 0))
    world = int(os.environ.get("WORLD_SIZE", 1))
    writer = local_rank == 0  # one worker per rig writes that rig's files
    device = torch.device(f"cuda:{local_rank}" if cuda else "cpu")
    # For whoever reads the log after something went wrong
    log(versions())
    if cuda:
        free, total = torch.cuda.mem_get_info(device)
        log(f"GPU {local_rank}: {torch.cuda.get_device_name(device)}, {free / 2 ** 30:.1f} of {total / 2 ** 30:.1f} GB free")
    else:
        log("No GPU that PyTorch can use: training on the CPU")
    set_up_speedups(torch, args.speedups, device, cuda)

    # A stop (the flight sheet ending, or meet.py regrouping because a rig joined) is only noted here. The loop
    # passes it on to the other rigs and saves, between two examples.
    stopping = []
    in_loop = []

    def on_stop(*_):
        # Before the loop there is nothing new to save, and loading the model can't be interrupted politely
        if not in_loop:
            raise SystemExit(REGROUP)
        stopping.append(1)

    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, on_stop)

    if writer:
        refresh_dataset(args)
    dist.init_process_group("nccl" if cuda else "gloo")
    if writer:
        write_line(args.state_file, "syncing")

    print_of_settings = fingerprint(args, torch.__version__)
    same, _ = all_equal(dist, torch, print_of_settings, device)
    if not same:
        sys.exit("The rigs disagree on the base model, a training setting or the PyTorch version: give every rig "
                 "the same flight sheet settings")
    state = sync_checkpoint(dist, torch, args, device, rank, world, writer, print_of_settings)

    # Every example any GPU of max_len could hold is known to every rig, so they agree on what a step holds
    top_limit = longest(args.max_len)

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    encoded = {}
    examples = {}

    def load_examples():
        nonlocal examples
        examples, report = encode_all(tokenizer, sync_dataset(dist, torch, args, device, rank, world, writer),
                                      top_limit, encoded)
        log(f"Dataset: {report}")

    load_examples()
    if writer:
        write_line(args.state_file, "loading")
    # What the GPU memory goes to, for the progress page: read off as each part arrives
    memory = {"pid": os.getpid()}

    def in_use():
        return torch.cuda.memory_allocated(device) if cuda else 0

    def tell_memory(tokens=None):
        """model: the base model. adapter: the weights being trained. optimizer: what Adam keeps per weight.
        example: the most that training an example took on top of those, since the last call. kept: what PyTorch
        holds on to for the next example without using it now."""
        if not (cuda and args.memory_file):
            return
        memory["optimizer"] = sum(value.numel() * value.element_size() for state in optimizer.state.values()
                                  for value in state.values() if torch.is_tensor(value))
        steady = memory["model"] + memory["adapter"] + memory["optimizer"]
        memory["example"] = max(0, torch.cuda.max_memory_allocated(device) - steady)
        memory["kept"] = max(0, torch.cuda.memory_reserved(device) - max(in_use(), steady + memory["example"]))
        memory["tokens"] = tokens
        memory["at"] = round(time.time())
        write_line(f"{args.memory_file}-{local_rank}", json.dumps(memory))
        torch.cuda.reset_peak_memory_stats(device)

    model = load_model(torch, args, device, cuda)
    if cuda:
        share_vocabulary(torch, model)
    table = lighten(torch, model) if cuda else None
    memory["model"] = in_use()
    model = add_adapter(torch, model, args)
    memory["adapter"] = in_use() - memory["model"]
    named = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
    parameters = [p for _, p in named]
    optimizer = torch.optim.AdamW(parameters, lr=args.lr, weight_decay=0.0)
    tell_memory()
    seen = 0
    counts = {}  # times each example has been trained, by key
    reached = 0  # the longest example any rig of the run could take so far
    if state:
        with torch.no_grad():
            for name, parameter in named:
                parameter.copy_(state["adapter"][name])
        optimizer.load_state_dict(state["optimizer"])
        seen = int(state["seen"])
        counts = dict(state["counts"])
        reached = int(state.get("reached", 0))
        del state
    elif world > 1:
        # A new run: every rig made its own random adapter, and they have to start from the same one
        for parameter in parameters:
            dist.broadcast(parameter.data, 0)
    saved = seen

    # What this rig can hold itself is its own limit, and limits has every rig's. Under auto no setting says how
    # long an example can be at all, so the run remembers the highest limit it has met: the examples over that are
    # no rig's to train, and don't count as left.
    gpu_gb = args.gpu_gb if args.gpu_gb is not None else (
        round(torch.cuda.get_device_properties(device).total_memory / 2 ** 30) if cuda else 0)
    # Before any measuring: only a model that is training saves memory by recomputing its activations
    model.train()
    parts = split_model(model)
    if parts:
        parts = (*parts, table)
    elif table is not None:
        # The model's own forward looks the tokens up on the GPU
        table.to(device)
    if cuda:
        log(f"On the GPU: {describe_memory(torch, model, parts)}")
    if not parts:
        log("This model doesn't come apart into a body and a vocabulary layer: its own loss is used, on more memory")

    def loss_of(ids, labels):
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=cuda):
            return example_loss(torch, parts, ids, labels) if parts else model(input_ids=ids, labels=labels).loss

    if args.max_len == AUTO:
        # Adam keeps two numbers per weight from its first step on, and a step's gradients pass through one more
        # copy of a bucket of them: not there yet in a new run, when the measuring is done
        weights = sum(parameter.numel() for parameter in parameters) * 4
        reserve = (0 if optimizer.state else 2 * weights) + min(weights, BUCKET * 4)
        own_limit = own_auto_limit(torch, args, tokenizer, parameters, device, cuda, local_rank, writer,
                                   loss_of, reserve, tell_memory)
    else:
        own_limit = limit_for(parse_limits(args.max_len), gpu_gb)
    limits = [int(limit) for limit in share(dist, torch, device, rank, world, own_limit)]
    reach = max(limits)
    reached = max(reached, reach) if args.max_len == AUTO else top_limit
    tell_memory()
    # A step is the same number of examples whoever is here, so the rigs present split it: alone, a rig does it all
    step_examples = args.step_size
    rigs = f"{world} rig{'s' * (world > 1)}"

    def rate(at):
        # No way down: the run has no end to come down to
        return args.lr * min(1.0, (at // step_examples + 1) / (WARMUP_STEPS + 1))

    def left():
        return sum(max(0, args.epochs - counts.get(key, 0)) for key in examples if len(examples[key][0]) <= reached)

    def place(key):
        # Shuffled among the examples trained as often, differently on every pass
        times = counts.get(key, 0)
        return times, hashlib.sha1(f"{args.seed}:{times}:{key}".encode()).digest()

    def next_batch(size):
        """The least trained examples that a rig here can hold, the same on every rig since it follows from counts
        and limits alone. Empty when every one of them has had its --epochs. The last step before that is filled up
        with examples that are already there, so a step is always the same size."""
        order = sorted((key for key in examples if len(examples[key][0]) <= reach), key=place)
        if not any(counts.get(key, 0) < args.epochs for key in order):
            return []
        return [order[number % len(order)] for number in range(size)]

    def tell_all(word):
        flag = torch.tensor([word], dtype=torch.int64, device=device)
        dist.all_reduce(flag, op=dist.ReduceOp.MAX)
        return int(flag.item())

    adapter_dir = os.path.join(args.run_dir, "adapter")

    def save():
        """The checkpoint to continue from, and the adapter as mode=export and PEFT read it. The adapter folder
        says what it holds, since a checkpoint taken from another rig comes without one."""
        nonlocal saved
        if not writer:
            return
        if saved != seen:
            buffer = io.BytesIO()
            torch.save({"seen": seen, "counts": counts, "reached": reached, "adapter": {name: p.detach().cpu() for name, p in named},
                        "optimizer": optimizer.state_dict()}, buffer)
            write_checkpoint(args, buffer.getvalue(), seen, print_of_settings)
            saved = seen
        mark = os.path.join(adapter_dir, "examples-seen")
        if seen and not (os.path.exists(mark) and open(mark).read().strip() == str(seen)):
            model.save_pretrained(adapter_dir)
            tokenizer.save_pretrained(adapter_dir)
            write_line(mark, str(seen))

    def progress():
        return f"step {seen // step_examples}, {math.ceil(left() / step_examples)} to go"

    def note(event, **more):
        """A line of this rig's history: what it did when, for the progress page."""
        if not writer:
            return
        line = {"t": round(time.time()), "e": event, "step": seen // step_examples, "left": left(),
                "n": len(examples), "rigs": world, "size": step_examples, "lim": own_limit}
        line.update({key: round(value, 4) for key, value in more.items() if value is not None})
        with open(os.path.join(args.run_dir, "history.jsonl"), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")

    def waiting_for():
        # Examples are left, but only for a GPU with a higher limit than any here
        return "a rig with more GPU memory" if left() else "new examples" if examples else "the dataset"

    # The source is watched beside the training, which a PC that is off would otherwise hold up
    new_data = threading.Event()

    def watch_source():
        while True:
            time.sleep(CHECK)
            if refresh_dataset(args):
                new_data.set()

    if writer:
        threading.Thread(target=watch_source, daemon=True).start()

    log(f"{rigs}, steps of {step_examples} examples, this rig takes examples up to {own_limit} tokens; "
        f"starting at {progress()}")
    beyond = sum(len(ids) > reached for ids, _ in examples.values())
    if beyond:
        log(f"{beyond} examples are longer than any rig of this run has been able to take ({reached} tokens): "
            "they wait for one that can")
    save()
    note("start")
    in_loop.append(1)
    idle = None
    stopped = False
    speed = 0.0  # tokens a second this rig trains, as measured so far
    try:
        while not stopped:
            word = tell_all(STOP if stopping else NEW_DATA if new_data.is_set() else 0)
            if word == STOP:
                break
            if word == NEW_DATA:
                new_data.clear()
                load_examples()
                continue
            batch = next_batch(step_examples)
            if not batch:
                if idle is not True:
                    idle = True
                    save()
                    log(f"Nothing to train at {progress()}: waiting for {waiting_for()}")
                    note("idle")
                    problem.clear(args.problem_file)
                    if writer:
                        write_line(args.state_file, "idle")
                if writer:
                    # Written every time: h-train.sh takes a status that stops changing for a worker that hangs
                    write_line(args.status_file,
                               f"step {seen // step_examples}, waiting for {waiting_for()}, {rigs}")
                time.sleep(IDLE)
                continue
            if idle is not False:
                idle = False
                started = time.time()
                first_seen = seen
                steps_done = 0
                if writer:
                    write_line(args.status_file, f"{progress()}, {rigs}")
                    write_line(args.state_file, "training")

            # The rigs that haven't measured their speed yet count as average
            speeds = share(dist, torch, device, rank, world, speed)
            known = [value for value in speeds if value > 0]
            speeds = [value if value > 0 else sum(known) / len(known) if known else 1.0 for value in speeds]
            lengths = [len(examples[key][0]) for key in batch]
            mine = [batch[position] for position in deal(lengths, limits, speeds)[rank]]

            for entry in optimizer.param_groups:
                entry["lr"] = rate(seen)
            optimizer.zero_grad(set_to_none=True)
            loss_sum = 0.0
            tokens = 0
            step_began = time.time()
            for key in mine:
                # A rig that is leaving drops the rest of its part: the step is then left out by all (below)
                if stopping:
                    break
                ids, labels = examples[key]
                ids = torch.tensor([ids], device=device)
                labels = torch.tensor([labels], device=device)
                loss = loss_of(ids, labels)
                # Every example of the step weighs the same, whichever rig has it
                (loss / len(batch)).backward()
                # Reading the loss waits for the GPU, so the time is this example's
                loss_sum += loss.item()
                tokens += ids.shape[1]
            # Where the step's time goes, for the progress page. waited: here, where the rigs meet and every rig
            # stands still until the slowest has done its part. network: adding up the gradients.
            computed = time.time() - step_began
            if tell_all(STOP if stopping else 0) == STOP:
                break
            waited = time.time() - step_began - computed
            network = None
            if world > 1:
                sum_gradients(dist, torch, parameters)
                network = time.time() - step_began - computed - waited
            torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            optimizer.step()
            if tokens and computed > 0:
                speed = tokens / computed if not speed else 0.7 * speed + 0.3 * tokens / computed
            for key in batch:
                counts[key] = counts.get(key, 0) + 1
            seen += len(batch)
            steps_done += 1
            tell_memory(max(len(examples[key][0]) for key in mine) if mine else None)
            if steps_done == 1:
                # It trains: whatever stopped earlier attempts is over
                problem.clear(args.problem_file)
            pace = (time.time() - started) / (seen - first_seen) * step_examples
            # The loss is over this rig's examples of the step; the other rigs log theirs
            own_loss = loss_sum / len(mine) if mine else None
            status = progress() + (f" loss {own_loss:.3f}" if mine else "")
            note("step", loss=own_loss, dur=time.time() - step_began, wait=waited, net=network, ex=len(mine))
            log(f"{status} lr {rate(seen - 1):.2e} {pace:.1f} s/step, {left() / step_examples * pace / 3600:.1f} h left")
            if writer:
                write_line(args.status_file, f"{status}, {rigs}")
            if steps_done % args.save_steps == 0:
                save()
    except Exception as error:
        if not out_of_memory(torch, error):
            # Usually a rig that vanished mid-step. The adapter is still as the last whole step left it.
            save()
            raise
        traceback.print_exc()
        tell_memory()
        if writer:
            write_line(args.status_file, "out of GPU memory: lower max_len")
        lowered = lower_auto_limit(torch, args, device, local_rank, own_limit) if args.max_len == AUTO else None
        sys.exit(f"Out of GPU memory with examples up to {own_limit} tokens on {gpu_gb} GB (max_len={args.max_len}): "
                 + (f"taking {lowered} from the next start" if lowered else "lower the limit for this GPU, or lora_r")
                 + f" ({str(error).splitlines()[0][:160]})")

    save()
    note("stop")
    log(f"Stopped at {progress()} because a rig is leaving or joining; saved")
    # Not 0: to meet.py that would mean the run is finished, and this one never is
    sys.exit(REGROUP)


def run():
    """main, and what went wrong said where the progress page finds it: the log is on the rig."""
    args = parse_args()
    try:
        main(args)
    except SystemExit as stop:
        # 75: stopped for the group to change, which is no failure. A text: the reason, already worded.
        if stop.code not in (None, 0, REGROUP):
            problem.report(args.problem_file, stop.code if isinstance(stop.code, str) else f"Stopped with code {stop.code}")
        raise
    except Exception as error:
        if isinstance(error, RuntimeError) and any(sign in str(error).lower() for sign in PEER_LOST_SIGNS):
            traceback.print_exc()
            log("The worker of another rig went away")
            sys.exit(PEER_LOST)
        frames = traceback.extract_tb(error.__traceback__)
        ours = [frame for frame in frames if os.path.basename(frame.filename) == "train.py"]
        where = [f"{os.path.basename(frame.filename)} line {frame.lineno}, in {frame.name}"
                 for frame in [*ours[-1:], frames[-1]]]
        problem.report(args.problem_file, f"{type(error).__name__}: {error} ({'; '.join(dict.fromkeys(where))})")
        raise


if __name__ == "__main__":
    run()
