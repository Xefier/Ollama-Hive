#!/usr/bin/env python3
"""Folds a trained adapter into the base model's own weights, for h-export.sh.

Ollama no longer loads LoRA adapters, so the adapter from train.py can only be served as part of the model. Merged,
the model has the same weights count as before: quantized the same way it takes the same VRAM and runs at the same
speed as the stock model.

  export.py size --base REPO                     bytes of the base model's weights
  export.py merge --adapter DIR --base REPO --out DIR
  export.py modelfile STOCK_MODELFILE GGUF       the stock model's Modelfile, with its weights swapped for GGUF
  export.py convert SCRIPT ARGUMENTS...          llama.cpp's converter, writing the tensors the way Ollama reads them

The merge never holds more than one weights file in memory and never keeps a second copy of the base on disk: each
file is downloaded, merged, written and its download deleted. It can be stopped and started again.
"""

import argparse
import json
import math
import os
import re
import shutil
import sys

ADAPTER_KEY = re.compile(r"^(?:base_model\.model\.)?(.+)\.lora_([AB])(?:\.default)?\.weight$")


def log(text):
    print(f"[export] {text}", flush=True)


def read_adapter(folder):
    """{module path: (A, B, scale)} from a PEFT LoRA folder."""
    from safetensors.torch import load_file

    with open(os.path.join(folder, "adapter_config.json"), encoding="utf-8") as handle:
        config = json.load(handle)
    unsupported = [name for name in ("use_dora", "rank_pattern", "alpha_pattern", "modules_to_save") if config.get(name)]
    if config.get("peft_type") != "LORA" or unsupported:
        sys.exit(f"{folder} is not a plain LoRA adapter ({config.get('peft_type')} {' '.join(unsupported)})")
    rank = config["r"]
    scale = config["lora_alpha"] / (math.sqrt(rank) if config.get("use_rslora") else rank)

    halves = {}
    for key, tensor in load_file(os.path.join(folder, "adapter_model.safetensors")).items():
        match = ADAPTER_KEY.match(key)
        if not match:
            sys.exit(f"The adapter has a tensor the merge doesn't know: {key}")
        halves.setdefault(match.group(1), {})[match.group(2)] = tensor
    modules = {}
    for path, pair in halves.items():
        if set(pair) != {"A", "B"}:
            sys.exit(f"The adapter lacks half of {path}")
        modules[path] = (pair["A"], pair["B"], scale)
    return modules


def base_tensors(base):
    """{weights file: {tensor name: shape}} of the base model, read from the files' headers only."""
    if os.path.isdir(base):
        from safetensors import safe_open

        files = {}
        for name in sorted(os.listdir(base)):
            if name.endswith(".safetensors"):
                with safe_open(os.path.join(base, name), "pt") as handle:
                    files[name] = {key: list(handle.get_slice(key).get_shape()) for key in handle.keys()}
        return files
    from huggingface_hub import get_safetensors_metadata

    metadata = get_safetensors_metadata(base)
    return {name: {key: list(info.shape) for key, info in file.tensors.items()}
            for name, file in metadata.files_metadata.items()}


def match_modules(modules, files):
    """{weights file: {tensor name: module path}}. The adapter names modules as the loaded model does, the files as
    the checkpoint does, and the two can differ at the front (a text-only class drops a prefix), so each module is
    matched to the tensor sharing its longest tail of names, and the shapes must agree. Where several tensors share
    that tail, the one that also starts most like the module is it: Qwen3.8 has a small block beside the model
    (mtp.layers.0...) whose weights end like the first layer's and are as large."""
    by_tail = {}
    for name, tensors in files.items():
        for key, shape in tensors.items():
            if not key.endswith(".weight") or len(shape) != 2:
                continue
            parts = key[:-len(".weight")].split(".")
            for start in range(len(parts)):
                by_tail.setdefault(".".join(parts[start:]), []).append((name, key, shape))

    plan = {}
    taken = set()
    for path, (a, b, _) in modules.items():
        wanted = [b.shape[0], a.shape[1]]
        parts = path.split(".")
        found = []
        for start in range(len(parts)):
            found = [entry for entry in by_tail.get(".".join(parts[start:]), []) if entry[2] == wanted]
            if found:
                break
        if len(found) > 1:
            def same_start(entry):
                names = entry[1].split(".")
                return next((count for count, (ours, theirs) in enumerate(zip(parts, names)) if ours != theirs),
                            min(len(parts), len(names)))

            best = max(same_start(entry) for entry in found)
            found = [entry for entry in found if same_start(entry) == best]
        if len(found) != 1 or (found[0][0], found[0][1]) in taken:
            sys.exit(f"Can't place the adapter's {path} in the base model: {len(found)} tensors fit. "
                     "Is this the full-precision repo of the model the adapter was trained on?")
        name, key, _ = found[0]
        taken.add((name, key))
        plan.setdefault(name, {})[key] = path
    return plan


def fetch(base, name, folder):
    """A local path of one of the base's files, and whether it is a download to delete after use."""
    if os.path.isdir(base):
        return os.path.join(base, name), False
    from huggingface_hub import hf_hub_download

    return hf_hub_download(base, name, local_dir=folder), True


def merge(args):
    import torch
    from safetensors.torch import load_file, save_file

    modules = read_adapter(args.adapter)
    files = base_tensors(args.base)
    plan = match_modules(modules, files)
    os.makedirs(args.out, exist_ok=True)
    downloads = os.path.join(args.out, ".download")

    # Everything that isn't weights: the config, the tokenizer, the index of the weights files
    if os.path.isdir(args.base):
        for name in os.listdir(args.base):
            source = os.path.join(args.base, name)
            if os.path.isfile(source) and not name.endswith(".safetensors"):
                shutil.copy(source, os.path.join(args.out, name))
    else:
        from huggingface_hub import snapshot_download

        snapshot_download(args.base, local_dir=args.out, ignore_patterns=["*.safetensors", "*.gguf", "*.bin", "*.onnx", "*.onnx_data"])

    for number, name in enumerate(sorted(files), 1):
        if args.status_file:
            # For the progress page: the download of a file is most of its time
            with open(args.status_file, "w", encoding="utf-8") as handle:
                handle.write(f"{args.status_until * (number - 1) // len(files)}% · step 1 of 4: adding the adapter to the "
                             f"base model's weights, file {number} of {len(files)}\n")
        target = os.path.join(args.out, name)
        # A finished file was moved into place whole, so one that exists is done
        if os.path.exists(target):
            continue
        source, downloaded = fetch(args.base, name, downloads)
        wanted = plan.get(name, {})
        if wanted:
            tensors = load_file(source)
            for key, path in wanted.items():
                a, b, scale = modules[path]
                weight = tensors[key]
                merged = weight.to(torch.float32) + scale * (b.to(torch.float32) @ a.to(torch.float32))
                tensors[key] = merged.to(weight.dtype)
            save_file(tensors, target + ".tmp", metadata={"format": "pt"})
            del tensors
        else:
            shutil.copy(source, target + ".tmp")
        os.replace(target + ".tmp", target)
        if downloaded:
            os.remove(source)
        log(f"{number}/{len(files)} {name}: {len(wanted)} layers merged")
    shutil.rmtree(downloads, ignore_errors=True)
    shutil.rmtree(os.path.join(args.out, ".cache"), ignore_errors=True)
    log(f"Merged {len(modules)} layers into {args.out}")


def convert(args):
    """Runs llama.cpp's convert_hf_to_gguf.py with one thing changed. For some architectures (Qwen3.5/3.8) it writes
    pairs of weights that share an input as one tensor each (attn_qkv_gate, ssm_beta_alpha), which llama.cpp itself
    reads either way. Ollama's own build of it only knows them apart, as in the models of its registry, and fails
    to load the other with "tensor 'blk.0.ssm_beta.weight' not found". The converter has no option for it: the
    pairs are a list on its model classes, emptied here before it runs."""
    import importlib
    import pkgutil
    import runpy

    sys.path.insert(0, os.path.dirname(os.path.abspath(args.script)))
    try:
        import conversion
    except ImportError:
        conversion = None  # a release from before the converter was split into modules, which had no such pairs
    apart = 0
    for found in pkgutil.iter_modules(conversion.__path__) if conversion else []:
        try:
            module = importlib.import_module(f"conversion.{found.name}")
        except Exception:  # an architecture whose own packages aren't installed: not the one being converted
            continue
        for value in vars(module).values():
            if isinstance(value, type) and getattr(value, "_SHARED_INPUT_MERGES", None):
                value._SHARED_INPUT_MERGES = ()
                apart += 1
    log(f"Converting with paired weights kept apart ({apart} model classes of the converter pair them)")
    sys.argv = [args.script, *args.arguments]
    runpy.run_path(args.script, run_name="__main__")


def size(args):
    if os.path.isdir(args.base):
        print(sum(os.path.getsize(os.path.join(args.base, name)) for name in os.listdir(args.base)
                  if name.endswith(".safetensors")))
        return
    from huggingface_hub import HfApi

    print(sum(entry.size or 0 for entry in HfApi().model_info(args.base, files_metadata=True).siblings
              if entry.rfilename.endswith(".safetensors")))


def modelfile(args):
    """The stock Modelfile keeps its renderer, parser, parameters and vision projector; only its weights change.
    `ollama show --modelfile` lists the weights and the projector as two FROM lines of blob paths: the weights are
    the larger file."""
    with open(args.stock, encoding="utf-8") as handle:
        lines = handle.read().split("\n")
    sources = [index for index, line in enumerate(lines) if line.startswith("FROM ")]
    if not sources:
        sys.exit(f"{args.stock} has no FROM line")

    def blob_size(index):
        path = lines[index][len("FROM "):].strip()
        return os.path.getsize(path) if os.path.isfile(path) else -1

    lines[max(sources, key=blob_size)] = f"FROM {args.gguf}"
    print("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("size")
    command.add_argument("--base", required=True)
    command.set_defaults(run=size)
    command = commands.add_parser("merge")
    command.add_argument("--adapter", required=True)
    command.add_argument("--base", required=True)
    command.add_argument("--out", required=True)
    command.add_argument("--status-file", help="where to say how far it is, for the progress page")
    command.add_argument("--status-until", type=int, default=100, help="the percent of the whole export this ends at")
    command.set_defaults(run=merge)
    command = commands.add_parser("convert")
    command.add_argument("script")
    command.add_argument("arguments", nargs=argparse.REMAINDER)
    command.set_defaults(run=convert)
    command = commands.add_parser("modelfile")
    command.add_argument("stock")
    command.add_argument("gguf")
    command.set_defaults(run=modelfile)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
