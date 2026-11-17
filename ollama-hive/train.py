#!/usr/bin/env python3
"""One worker of a QLoRA run shared between rigs. meet.py starts it on every rig, for h-train.sh.

Each worker holds its own 4-bit copy of the base model on its GPU. Only the adapter's gradients cross the network:
DistributedDataParallel averages them on every optimizer step, so every worker ends each step with the same adapter.

The run has no end. The dataset grows while it trains: every example is trained --epochs times, the least trained
first, and when all have been the workers stay loaded and wait for more (next_batch). The dataset's source is looked
at every minute, and the rig that finds a newer one hands it to the others (sync_dataset), so only one rig has to
reach it. A source that isn't there yet is the same as an empty one: the workers wait.

Rigs come and go (a rental takes one, it comes back when idle), so nothing here depends on how many take part:
- A step is always grad_accum x nodes examples however many rigs share it, and which examples it takes follows from
  how often each has been trained, which the checkpoint records.
- Every rig saves the adapter to its own disk. On every start the workers compare checkpoints and all continue from
  the furthest one (sync_checkpoint).
- A rig told to stop says so to the others before the next example, and all of them save first (the stop flag).

Dataset: JSON lines, each {"messages": [{"role": ..., "content": ...}, ...]} or {"text": "..."}. An example is known
by its line: a changed line is a new example.
"""

import argparse
import contextlib
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
import urllib.request

VISION_OR_HEAD = re.compile(r"(^|\.)(visual|vision\w*|merger|multi_modal_projector|lm_head|mtp\w*)(\.|$)")
CHUNK = 256 * 1024 * 1024
CHECK = 60          # seconds between looks at the dataset's source
IDLE = 5            # seconds between looks at the other rigs while there is nothing to train
WARMUP_STEPS = 10
# What a worker tells the others before an example; the highest wins
NEW_DATA, STOP = 1, 2


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--epochs", type=int, default=3, help="times each example is trained")
    parser.add_argument("--max-len", type=int, default=2048)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--nodes", type=int, default=1, help="rigs of the run when all take part")
    parser.add_argument("--save-steps", type=int, default=25)
    parser.add_argument("--seed", type=int, default=3407)
    parser.add_argument("--state-file")
    parser.add_argument("--status-file")
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
    parts = [args.base, args.epochs, args.max_len, args.lora_r, args.lr, args.grad_accum, args.nodes,
             args.seed, torch_version]
    return int(hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:15], 16)


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


def main():
    args = parse_args()
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
                                args.max_len, {})[1]
            log(f"Dataset: {report}")
        return

    import torch
    import torch.distributed as dist
    from torch.nn.parallel import DistributedDataParallel

    cuda = torch.cuda.is_available()
    rank = int(os.environ.get("RANK", 0))
    local_rank = int(os.environ.get("LOCAL_RANK", 0))
    world = int(os.environ.get("WORLD_SIZE", 1))
    writer = local_rank == 0  # one worker per rig writes that rig's files
    device = torch.device(f"cuda:{local_rank}" if cuda else "cpu")

    # A stop (the flight sheet ending, or meet.py regrouping because a rig joined) is only noted here. The loop
    # passes it on to the other rigs and saves, between two examples.
    stopping = []
    in_loop = []

    def on_stop(*_):
        # Before the loop there is nothing new to save, and loading the model can't be interrupted politely
        if not in_loop:
            raise SystemExit(75)
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

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    encoded = {}
    examples = {}

    def load_examples():
        nonlocal examples
        examples, report = encode_all(tokenizer, sync_dataset(dist, torch, args, device, rank, world, writer),
                                      args.max_len, encoded)
        log(f"Dataset: {report}")

    load_examples()
    if writer:
        write_line(args.state_file, "loading")
    model = add_adapter(torch, load_model(torch, args, device, cuda), args)
    named = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
    parameters = [p for _, p in named]
    optimizer = torch.optim.AdamW(parameters, lr=args.lr, weight_decay=0.0)
    seen = 0
    counts = {}  # times each example has been trained, by key
    if state:
        with torch.no_grad():
            for name, parameter in named:
                parameter.copy_(state["adapter"][name])
        optimizer.load_state_dict(state["optimizer"])
        seen = int(state["seen"])
        counts = dict(state["counts"])
        del state
    saved = seen
    ddp = DistributedDataParallel(model, device_ids=[local_rank] if cuda else None)

    # A step is the same number of examples whoever is here, so the rigs present split it: alone, a rig does it all
    step_examples = args.grad_accum * args.nodes
    per_rig = math.ceil(step_examples / world)

    def rate(at):
        # No way down: the run has no end to come down to
        return args.lr * min(1.0, (at // step_examples + 1) / (WARMUP_STEPS + 1))

    def left():
        return sum(max(0, args.epochs - counts.get(key, 0)) for key in examples)

    def place(key):
        # Shuffled among the examples trained as often, differently on every pass
        times = counts.get(key, 0)
        return times, hashlib.sha1(f"{args.seed}:{times}:{key}".encode()).digest()

    def next_batch(size):
        """The least trained examples, the same on every rig and at every rig count since it follows from counts
        alone. Empty when every example has had its --epochs. The last step before that is filled up with examples
        that are already there, rather than leaving a rig without one."""
        if not left():
            return []
        order = sorted(examples, key=place)
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
            torch.save({"seen": seen, "counts": counts, "adapter": {name: p.detach().cpu() for name, p in named},
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

    def waiting_for():
        return "new examples" if examples else "the dataset"

    # The source is watched beside the training, which a PC that is off would otherwise hold up
    new_data = threading.Event()

    def watch_source():
        while True:
            time.sleep(CHECK)
            if refresh_dataset(args):
                new_data.set()

    if writer:
        threading.Thread(target=watch_source, daemon=True).start()

    log(f"{world} of {args.nodes} rigs, steps of {step_examples} examples ({per_rig} per rig now); "
        f"starting at {progress()}")
    save()
    model.train()
    in_loop.append(1)
    idle = None
    stopped = False
    try:
        while not stopped:
            word = tell_all(STOP if stopping else NEW_DATA if new_data.is_set() else 0)
            if word == STOP:
                break
            if word == NEW_DATA:
                new_data.clear()
                load_examples()
                continue
            batch = next_batch(per_rig * world)
            if not batch:
                if idle is not True:
                    idle = True
                    save()
                    log(f"Nothing to train at {progress()}: waiting for {waiting_for()}")
                    if writer:
                        write_line(args.state_file, "idle")
                if writer:
                    # Written every time: h-train.sh takes a status that stops changing for a worker that hangs
                    write_line(args.status_file,
                               f"step {seen // step_examples}, waiting for {waiting_for()}, {world}/{args.nodes} rigs")
                time.sleep(IDLE)
                continue
            if idle is not False:
                idle = False
                started = time.time()
                first_seen = seen
                steps_done = 0
                if writer:
                    write_line(args.status_file, f"{progress()}, {world}/{args.nodes} rigs")
                    write_line(args.state_file, "training")

            for entry in optimizer.param_groups:
                entry["lr"] = rate(seen)
            optimizer.zero_grad(set_to_none=True)
            loss_sum = 0.0
            for position, key in enumerate(batch[rank::world]):
                # Asked before every example, so a rig leaving costs the others at most the step in progress
                if position and tell_all(STOP if stopping else 0) == STOP:
                    stopped = True
                    break
                ids, labels = examples[key]
                ids = torch.tensor([ids], device=device)
                labels = torch.tensor([labels], device=device)
                # Gradients cross the network once per step, with the last example, not once per example
                last = position == per_rig - 1
                with contextlib.ExitStack() as stack:
                    if not last:
                        stack.enter_context(ddp.no_sync())
                    if cuda:
                        stack.enter_context(torch.autocast("cuda", dtype=torch.bfloat16))
                    loss = ddp(input_ids=ids, labels=labels).loss / per_rig
                    if not last:
                        loss.backward()
                if last:
                    loss.backward()
                loss_sum += loss.item()
            if stopped:
                break
            torch.nn.utils.clip_grad_norm_(parameters, 1.0)
            optimizer.step()
            for key in batch:
                counts[key] = counts.get(key, 0) + 1
            seen += len(batch)
            steps_done += 1
            pace = (time.time() - started) / (seen - first_seen) * step_examples
            # The loss is over this rig's examples of the step; the other rigs log theirs
            status = f"{progress()} loss {loss_sum:.3f}"
            log(f"{status} lr {rate(seen - 1):.2e} {pace:.1f} s/step, {left() / step_examples * pace / 3600:.1f} h left")
            if writer:
                write_line(args.status_file, f"{status}, {world}/{args.nodes} rigs")
            if steps_done % args.save_steps == 0:
                save()
    except torch.OutOfMemoryError:
        if writer:
            write_line(args.status_file, "out of GPU memory: lower max_len")
        log(f"Out of GPU memory at max_len={args.max_len}: lower max_len (or lora_r) on every rig")
        sys.exit(3)
    except Exception:
        # Usually a rig that vanished mid-step. The adapter is still as the last whole step left it.
        save()
        raise

    save()
    log(f"Stopped at {progress()} because a rig is leaving or joining; saved")
    # Not 0: to meet.py that would mean the run is finished, and this one never is
    sys.exit(75)


if __name__ == "__main__":
    main()
