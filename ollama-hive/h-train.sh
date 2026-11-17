#!/usr/bin/env bash

# mode=train, sourced by h-run.sh: this rig is one worker of a QLoRA run shared between rigs. Every rig runs torchrun
# with the same settings and meets the others at coordinator=<one rig's LAN address>; train.py does the training.
# Nothing is installed into the system: Python, PyTorch, the base model and the run are all under $OH_TRAIN_DIR.

find_train_settings_problem() {
    [[ -n $OH_BASE ]] || { echo "No base model set: add base=<Hugging Face repo> to the flight sheet"; return; }
    [[ -n $OH_DATASET ]] || { echo "No dataset set: add dataset=<URL or path of a .jsonl> to the flight sheet"; return; }
    [[ -n $OH_COORDINATOR ]] || { echo "No coordinator set: add coordinator=<LAN address of one of the rigs>"; return; }
    oh_is_private "$OH_COORDINATOR" || echo "coordinator=$OH_COORDINATOR is not a private LAN address"
}

# One worker per GPU listed in gpus=, and by default one GPU per rig
train_gpus() {
    echo "${OH_GPUS:-0}"
}

# uv installs Python and the packages, here and for h-export.sh
install_uv() {
    OH_UV="$OH_TRAIN_DIR/bin/uv"
    mkdir -p "$OH_TRAIN_DIR/bin"
    export UV_CACHE_DIR="$OH_TRAIN_DIR/uv-cache"
    export UV_PYTHON_INSTALL_DIR="$OH_TRAIN_DIR/python"
    [[ -x $OH_UV ]] && return 0
    log "Downloading uv, which installs Python and the packages"
    ( curl -fsSL --retry 3 https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz |
        tar -xz --strip-components=1 -C "$OH_TRAIN_DIR/bin" ) &
    wait $!
}

install_train_env() {
    local requirements="$OH_DIR/requirements-train.txt"
    local stamp="$OH_VENV/.installed"
    local wanted
    wanted="$(sha256sum < "$requirements") $OH_TORCH_INDEX"
    [[ -f $stamp && $(< "$stamp") == "$wanted" ]] && return 0

    oh_set_state installing
    install_uv || return 1
    local uv=$OH_UV
    log "Installing Python, PyTorch ($OH_TORCH_INDEX) and the training packages. Free space: $(df -h --output=avail "$OH_DATA_DIR" 2>/dev/null | tail -n 1 | tr -d ' ')"
    "$uv" venv --clear --python 3.12 "$OH_VENV" >> "$LOG_FILE" 2>&1 &
    wait $! || return 1
    "$uv" pip install --python "$OH_VENV/bin/python" \
        --index-url "https://download.pytorch.org/whl/$OH_TORCH_INDEX" torch >> "$LOG_FILE" 2>&1 &
    wait $! || return 1
    "$uv" pip install --python "$OH_VENV/bin/python" -r "$requirements" >> "$LOG_FILE" 2>&1 &
    wait $! || return 1
    "$OH_VENV/bin/python" -c 'import torch; print("PyTorch", torch.__version__, "CUDA", torch.cuda.is_available())' \
        >> "$LOG_FILE" 2>&1 || { log "PyTorch does not run on this system"; return 1; }
    echo "$wanted" > "$stamp"
}

# Runs one attempt: joins the other rigs, trains until the run is finished or any rig drops out
train_once() {
    local address interface gpus workers
    address=$(oh_lan_address)
    [[ -n $address ]] || { log "No private LAN address found"; return 1; }
    echo "$address" > "$OH_RUN_DIR/address"
    # Named for NCCL, which otherwise may pick a Docker bridge for the traffic between the GPUs
    interface=$(ip -o -4 addr show 2>/dev/null | awk -v a="$address" '{ split($4, p, "/"); if (p[1] == a) { print $2; exit } }')
    gpus=$(train_gpus)
    workers=$(awk -F, '{ print NF }' <<< "$gpus")

    export HOME="$OH_DATA_DIR/home"
    export HF_HOME="$OH_TRAIN_DIR/hf"
    export HF_HUB_DISABLE_TELEMETRY=1
    # Progress bars fill the miner log
    export HF_HUB_DISABLE_PROGRESS_BARS=1
    export TOKENIZERS_PARALLELISM=false
    export PYTHONUNBUFFERED=1
    export CUDA_VISIBLE_DEVICES="$gpus"
    [[ -n $interface ]] && export NCCL_SOCKET_IFNAME="$interface"
    mkdir -p "$HOME" "$HF_HOME" "$OH_RUN_PATH"
    rm -f "$OH_RUN_DIR/train-status"

    local arguments=(--base "$OH_BASE" --dataset "$OH_DATASET" --run-dir "$OH_RUN_PATH"
        --epochs "$OH_EPOCHS" --max-len "$OH_MAX_LEN" --lora-r "$OH_LORA_R" --lr "$OH_LR"
        --grad-accum "$OH_GRAD_ACCUM" --save-steps "$OH_SAVE_STEPS"
        --state-file "$OH_RUN_DIR/state" --status-file "$OH_RUN_DIR/train-status")

    oh_set_state preparing
    log "Fetching the dataset and $OH_BASE if they aren't on disk. Free space: $(df -h --output=avail "$OH_DATA_DIR" 2>/dev/null | tail -n 1 | tr -d ' ')"
    setsid "$OH_VENV/bin/python" "$OH_DIR/train.py" "${arguments[@]}" --prepare >> "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$OH_RUN_DIR/server.pid"
    wait "$SERVER_PID" || return 1

    oh_set_state joining
    log "Joining the run at $OH_COORDINATOR:$OH_TRAIN_PORT as $address ($OH_NODES rigs, $workers GPU here)"
    # Its own process group, so h-stop.sh also ends the workers it starts. --local_addr because rigs can't resolve
    # each other's host names.
    setsid "$OH_VENV/bin/python" -m torch.distributed.run \
        --nnodes "$OH_NODES" --nproc_per_node "$workers" --max_restarts 0 \
        --rdzv_backend c10d --rdzv_endpoint "$OH_COORDINATOR:$OH_TRAIN_PORT" --rdzv_id "$OH_RUN_NAME" \
        --rdzv_conf join_timeout=3600 --local_addr "$address" \
        "$OH_DIR/train.py" "${arguments[@]}" >> "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$OH_RUN_DIR/server.pid"
    wait "$SERVER_PID"
}

# A rig leaving stops the step for all of them, so every rig restarts its attempt and they meet again. Each attempt
# continues from the last checkpoint. Said once on the dashboard per stretch of failures, not on every retry.
train_loop() {
    local told=""
    while true; do
        if [[ -f $OH_RUN_PATH/done ]]; then
            oh_set_state done
            if [[ $told != done ]]; then
                notify info "Run $OH_RUN_NAME is finished: the adapter is in $OH_RUN_PATH/final. Set a new run_name to train again"
                told=done
            fi
            pause 60
            continue
        fi
        oh_set_state starting
        train_once
        kill -TERM -- "-$SERVER_PID" 2>/dev/null
        [[ -f $OH_RUN_PATH/done ]] && continue
        # It got as far as training, so this is a new stretch of failures
        [[ $(cat "$OH_RUN_DIR/state" 2>/dev/null) == training ]] && told=""
        if [[ $told != stopped ]]; then
            notify warn "Training stopped (a rig left, the coordinator isn't up yet, or an error): retrying every 30 s. See the miner log."
            told=stopped
        else
            log "Training stopped, retrying in 30 s"
        fi
        oh_set_state waiting
        pause 30
    done
}
