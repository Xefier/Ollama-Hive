#!/usr/bin/env python3
"""One worker of a QLoRA run shared between rigs. h-train.sh starts it on every rig through torchrun.

Each worker holds its own 4-bit copy of the base model on its GPU. Only the adapter's gradients cross the network:
DistributedDataParallel averages them on every optimizer step, so every worker ends each step with the same adapter.
Every rig saves that adapter to its own disk, which is how a run survives any rig leaving: on the next start the
workers compare checkpoints and all continue from the furthest one (sync_checkpoint).

Dataset: JSON lines, each {"messages": [{"role": ..., "content": ...}, ...]} or {"text": "..."}.
"""

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import re
import sys
import time
import urllib.request

VISION_OR_HEAD = re.compile(r"(^|\.)(visual|vision\w*|merger|multi_modal_projector|lm_head|mtp\w*)(\.|$)")
CHUNK = 256 * 1024 * 1024


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--max-len", type=int, default=2048)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--save-steps", type=int, default=25)
    parser.add_argument("--seed", type=int, default=3407)
    parser.add_argument("--state-file")
    parser.add_argument("--status-file")
    parser.add_argument("--prepare", action="store_true",
                        help="download the dataset and the base model, check the dataset, then exit")
    return parser.parse_args()


def log(text):
    print(f"[train r{os.environ.get('RANK', '-')}] {text}", flush=True)


def write_line(path, text):
    if not path:
        return
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    os.replace(path + ".tmp", path)


def dataset_file(args):
    """A URL is downloaded once per run folder, so a run never changes data halfway: new data means a new run_name."""
    if not re.match(r"https?://", args.dataset):
        return args.dataset
    path = os.path.join(args.run_dir, "dataset.jsonl")
    if not os.path.exists(path):
        log(f"Downloading {args.dataset}")
        with urllib.request.urlopen(args.dataset, timeout=60) as response, open(path + ".tmp", "wb") as out:
            while True:
                block = response.read(1 << 20)
                if not block:
                    break
                out.write(block)
        os.replace(path + ".tmp", path)
    return path


def read_rows(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as error:
                sys.exit(f"{path} line {number} is not JSON: {error}")
            if not isinstance(row, dict) or not ("messages" in row or "text" in row):
                sys.exit(f'{path} line {number} needs "messages" or "text"')
            rows.append(row)
    if not rows:
        sys.exit(f"{path} has no examples")
    return rows


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


def encode_all(tokenizer, rows, max_len):
    """Examples over max_len are left out, not cut: an answer cut off halfway teaches the model to stop halfway."""
    examples = []
    too_long = 0
    for row in rows:
        ids, labels = encode(tokenizer, row)
        if len(ids) > max_len:
            too_long += 1
        elif len(ids) > 1:
            examples.append((ids, labels))
    return examples, too_long


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(args, dataset_sha, torch_version):
    """What every rig of a run must agree on. A checkpoint also carries it, so a run_name can't continue with other
    settings."""
    parts = [args.base, dataset_sha, args.epochs, args.max_len, args.lora_r, args.lr, args.grad_accum, args.seed,
             torch_version]
    return int(hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:15], 16)


def all_equal(dist, torch, value, device):
    high = torch.tensor([value], dtype=torch.int64, device=device)
    low = high.clone()
    dist.all_reduce(high, op=dist.ReduceOp.MAX)
    dist.all_reduce(low, op=dist.ReduceOp.MIN)
    return high.item() == low.item(), high.item()


def local_checkpoint_step(args, print_of_settings):
    meta_path = os.path.join(args.run_dir, "checkpoint.json")
    if not (os.path.exists(meta_path) and os.path.exists(os.path.join(args.run_dir, "checkpoint.pt"))):
        return -1
    with open(meta_path, encoding="utf-8") as handle:
        meta = json.load(handle)
    if meta.get("fingerprint") != print_of_settings:
        sys.exit(f"{args.run_dir} holds a checkpoint made with another base model, dataset or settings: "
                 "set a new run_name, or delete that folder to start this one again")
    return int(meta["step"])


def write_checkpoint(args, blob, step, print_of_settings):
    path = os.path.join(args.run_dir, "checkpoint.pt")
    with open(path + ".tmp", "wb") as handle:
        handle.write(blob)
    os.replace(path + ".tmp", path)
    write_line(os.path.join(args.run_dir, "checkpoint.json"),
               json.dumps({"step": step, "fingerprint": print_of_settings}))


def sync_checkpoint(dist, torch, args, device, rank, world, writer, print_of_settings):
    """Every worker continues from the furthest checkpoint any rig has. Rigs save at the same steps, so normally all
    have it; one that was away, or is new to the run, gets it over the network from the lowest rank that has it."""
    local = local_checkpoint_step(args, print_of_settings)
    same, best = all_equal(dist, torch, local, device)
    if best < 0:
        return None
    path = os.path.join(args.run_dir, "checkpoint.pt")
    if same:
        return torch.load(path, map_location="cpu", weights_only=True)

    source = torch.tensor([rank if local == best else world], dtype=torch.int64, device=device)
    dist.all_reduce(source, op=dist.ReduceOp.MIN)
    source = int(source.item())
    blob = b""
    if rank == source:
        with open(path, "rb") as handle:
            blob = handle.read()
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
    if rank != source:
        blob = bytes(received)
        log(f"Took the step {best} checkpoint from rank {source} (this rig had step {local})")
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
    data_path = dataset_file(args)
    rows = read_rows(data_path)

    from transformers import AutoTokenizer

    if args.prepare:
        from huggingface_hub import snapshot_download

        snapshot_download(args.base)
        tokenizer = AutoTokenizer.from_pretrained(args.base)
        examples, too_long = encode_all(tokenizer, rows, args.max_len)
        log(f"Dataset: {len(examples)} examples, {sum(len(ids) for ids, _ in examples)} tokens; "
            f"{too_long} left out for being over max_len={args.max_len}")
        if not examples:
            sys.exit("No example fits max_len")
        return

    import torch
    import torch.distributed as dist
    from torch.nn.parallel import DistributedDataParallel
    from torch.utils.data.distributed import DistributedSampler

    cuda = torch.cuda.is_available()
    rank = int(os.environ.get("RANK", 0))
    local_rank = int(os.environ.get("LOCAL_RANK", 0))
    world = int(os.environ.get("WORLD_SIZE", 1))
    writer = local_rank == 0  # one worker per rig writes that rig's files
    device = torch.device(f"cuda:{local_rank}" if cuda else "cpu")
    dist.init_process_group("nccl" if cuda else "gloo")
    if writer:
        write_line(args.state_file, "syncing")

    print_of_settings = fingerprint(args, sha256_file(data_path), torch.__version__)
    same, _ = all_equal(dist, torch, print_of_settings, device)
    if not same:
        sys.exit("The rigs disagree on the base model, the dataset's content, a training setting or the PyTorch "
                 "version: give every rig the same flight sheet settings and the same dataset")
    state = sync_checkpoint(dist, torch, args, device, rank, world, writer, print_of_settings)

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    examples, _ = encode_all(tokenizer, rows, args.max_len)
    if writer:
        write_line(args.state_file, "loading")
    model = add_adapter(torch, load_model(torch, args, device, cuda), args)
    named = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
    parameters = [p for _, p in named]
    optimizer = torch.optim.AdamW(parameters, lr=args.lr, weight_decay=0.0)
    step = 0
    if state:
        with torch.no_grad():
            for name, parameter in named:
                parameter.copy_(state["adapter"][name])
        optimizer.load_state_dict(state["optimizer"])
        step = int(state["step"])
        del state
    ddp = DistributedDataParallel(model, device_ids=[local_rank] if cuda else None)

    sampler = DistributedSampler(examples, shuffle=True, seed=args.seed)
    per_epoch = math.ceil(len(sampler) / args.grad_accum)
    total = per_epoch * args.epochs
    warmup = min(10, max(1, total // 10))

    def rate(at):
        if at < warmup:
            return args.lr * (at + 1) / warmup
        return args.lr * max(0.0, (total - at) / max(1, total - warmup))

    def save():
        buffer = io.BytesIO()
        torch.save({"step": step, "adapter": {name: p.detach().cpu() for name, p in named},
                    "optimizer": optimizer.state_dict()}, buffer)
        write_checkpoint(args, buffer.getvalue(), step, print_of_settings)

    log(f"{world} workers, {len(examples)} examples, {total} steps of {args.grad_accum} x {world} examples; "
        f"starting at step {step}")
    if writer:
        write_line(args.state_file, "training")
    model.train()
    started = time.time()
    first_step = step
    try:
        while step < total:
            sampler.set_epoch(step // per_epoch)
            order = list(sampler)
            for begin in range((step % per_epoch) * args.grad_accum, len(order), args.grad_accum):
                group = order[begin:begin + args.grad_accum]
                for entry in optimizer.param_groups:
                    entry["lr"] = rate(step)
                optimizer.zero_grad(set_to_none=True)
                loss_sum = 0.0
                for position, index in enumerate(group):
                    ids, labels = examples[index]
                    ids = torch.tensor([ids], device=device)
                    labels = torch.tensor([labels], device=device)
                    # Gradients cross the network once per step, with the last example, not once per example
                    last = position == len(group) - 1
                    with contextlib.ExitStack() as stack:
                        if not last:
                            stack.enter_context(ddp.no_sync())
                        if cuda:
                            stack.enter_context(torch.autocast("cuda", dtype=torch.bfloat16))
                        loss = ddp(input_ids=ids, labels=labels).loss / len(group)
                        if not last:
                            loss.backward()
                    if last:
                        loss.backward()
                    loss_sum += loss.item()
                torch.nn.utils.clip_grad_norm_(parameters, 1.0)
                optimizer.step()
                step += 1
                pace = (time.time() - started) / (step - first_step)
                # The loss is over this rig's examples of the step; the other rigs log theirs
                status = f"step {step}/{total} loss {loss_sum:.3f}"
                log(f"{status} lr {rate(step - 1):.2e} {pace:.1f} s/step, "
                    f"{(total - step) * pace / 3600:.1f} h left")
                if writer:
                    write_line(args.status_file, status)
                    if step % args.save_steps == 0 or step == total:
                        save()
    except torch.OutOfMemoryError:
        if writer:
            write_line(args.status_file, "out of GPU memory: lower max_len")
        log(f"Out of GPU memory at max_len={args.max_len}: lower max_len (or lora_r) on every rig")
        sys.exit(3)

    if writer:
        final = os.path.join(args.run_dir, "final")
        model.save_pretrained(final)
        tokenizer.save_pretrained(final)
        write_line(os.path.join(args.run_dir, "done"), f"step {step}")
        log(f"Finished. The adapter is in {final}")
    dist.destroy_process_group()


if __name__ == "__main__":
    main()
