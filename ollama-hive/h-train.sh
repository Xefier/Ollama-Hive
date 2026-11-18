#!/usr/bin/env bash

# mode=train, sourced by h-run.sh: this rig is one worker of a QLoRA run shared between the rigs on the LAN that have
# the same flight sheet. train.py does the training; meet.py finds the other rigs and starts it, again whenever the
# group changes.
# Rigs come and go as rentals take them, so no rig is special: the run goes on with whichever are here, down to one.
# The run has no end: the dataset grows while it trains, and with nothing left to train the workers wait for more.
# Nothing is installed into the system: Python, PyTorch, the base model and the run are all under $OH_TRAIN_DIR.

find_train_settings_problem() {
    [[ -n $OH_BASE ]] || { echo "No base model set: add base=<Hugging Face repo> to the flight sheet"; return; }
    [[ -n $OH_DATASET ]] || { echo "No dataset set: add dataset=<URL or path of a .jsonl> to the flight sheet"; return; }
    local peer
    for peer in ${OH_PEERS//,/ }; do
        oh_is_private "$peer" || { echo "peers= has $peer, which is not a private LAN address"; return; }
    done
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

# speedups=1: the optional packages of requirements-speedups.txt. Training works without them, so a failed install
# is said and nothing more. train.py tries them out before it relies on them.
install_speedups() {
    [[ $OH_SPEEDUPS == 1 ]] || return 0
    local requirements="$OH_DIR/requirements-speedups.txt"
    local stamp="$OH_VENV/.speedups"
    local wanted
    wanted=$(sha256sum < "$requirements")
    [[ -f $stamp && $(< "$stamp") == "$wanted" ]] && return 0
    install_uv || return 0
    log "Installing the optional speed-ups (speedups=1)"
    "$OH_UV" pip install --python "$OH_VENV/bin/python" -r "$requirements" >> "$LOG_FILE" 2>&1 &
    if wait $!; then
        echo "$wanted" > "$stamp"
    else
        log "The speed-ups did not install (see above): training without them"
    fi
}

# Runs meet.py, which trains with whichever rigs are there, until something breaks
train_once() {
    local address interface broadcast gpus workers
    address=$(oh_lan_address)
    [[ -n $address ]] || { log "No private LAN address found"; return 1; }
    echo "$address" > "$OH_RUN_DIR/address"
    # Named for NCCL, which otherwise may pick a Docker bridge for the traffic between the GPUs
    # and the address that reaches every rig on this LAN, which is how they find each other (meet.py)
    read -r interface broadcast < <(ip -o -4 addr show 2>/dev/null | awk -v a="$address" '{
        split($4, p, "/")
        if (p[1] == a) { for (i = 5; i < NF; i++) if ($i == "brd") b = $(i + 1); print $2, b; exit }
    }')
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
        --step-size "$OH_STEP_SIZE" --save-steps "$OH_SAVE_STEPS"
        --state-file "$OH_RUN_DIR/state" --status-file "$OH_RUN_DIR/train-status" --problem-file "$OH_PROBLEM_FILE"
        --memory-file "$OH_MEMORY_FILE")
    [[ $OH_SPEEDUPS == 1 ]] && arguments+=(--speedups)

    oh_set_state preparing
    log "Fetching $OH_BASE if it isn't on disk, and the dataset if it is there. Free space: $(df -h --output=avail "$OH_DATA_DIR" 2>/dev/null | tail -n 1 | tr -d ' ')"
    setsid "$OH_VENV/bin/python" "$OH_DIR/train.py" "${arguments[@]}" --prepare >> "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$OH_RUN_DIR/server.pid"
    wait "$SERVER_PID" || return 1

    oh_set_state joining
    # Its own process group, so h-stop.sh also ends the workers it starts
    setsid "$OH_VENV/bin/python" "$OH_DIR/meet.py" \
        --me "$address" --port "$OH_TRAIN_PORT" --workers "$workers" --run "$OH_RUN_NAME" \
        --broadcast "${broadcast:-255.255.255.255}" --peers "$OH_PEERS" --rigs-file "$OH_RIGS_FILE" \
        --problem-file "$OH_PROBLEM_FILE" -- \
        "$OH_VENV/bin/python" "$OH_DIR/train.py" "${arguments[@]}" >> "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$OH_RUN_DIR/server.pid"

    while kill -0 "$SERVER_PID" 2>/dev/null; do
        pause 20
        # A rig that lost power mid-step can leave the others waiting on it for good. train.py writes its status
        # after every step, and every few seconds while it has nothing to train.
        if [[ $(cat "$OH_RUN_DIR/state" 2>/dev/null) =~ ^(training|idle)$ ]] \
            && [[ -n $(find "$OH_RUN_DIR/train-status" -mmin +20 2>/dev/null) ]]; then
            log "No sign of life from the training in 20 minutes: starting the attempt again"
            oh_stop_group "$SERVER_PID" 40
            return 1
        fi
    done
    wait "$SERVER_PID"
}

# The progress page and this rig's part of its data, for as long as the flight sheet runs. h-stop.sh ends it with
# everything else that runs from the training environment.
start_status_page() {
    local address
    address=$(oh_lan_address)
    [[ -n $address ]] || return
    mkdir -p "$OH_RUN_PATH"
    "$OH_VENV/bin/python" "$OH_DIR/status.py" --me "$address" --port "$OH_STATUS_PORT" --rigs-file "$OH_RIGS_FILE" \
        --run-dir "$OH_RUN_PATH" --run-name "$OH_RUN_NAME" --version "${CUSTOM_VERSION:-}" \
        --state-file "$OH_RUN_DIR/state" --status-file "$OH_RUN_DIR/train-status" --log-file "$LOG_FILE" \
        --problem-file "$OH_PROBLEM_FILE" --memory-file "$OH_MEMORY_FILE" \
        >> "$LOG_FILE" 2>&1 &
    log "Progress page: http://$address:$OH_STATUS_PORT/"
}

# meet.py handles rigs joining and leaving by itself and the run has no end, so it only ends on an error. Every start
# continues from the last checkpoint. Said once on the dashboard per stretch of failures, not on every retry.
train_loop() {
    local told=""
    install_speedups
    # Left by an earlier time on this flight sheet
    rm -f "$OH_PROBLEM_FILE" "$OH_MEMORY_FILE"-*
    start_status_page
    while true; do
        oh_set_state starting
        train_once
        oh_stop_group "$SERVER_PID" 5
        # It got as far as training, so this is a new stretch of failures
        [[ $(cat "$OH_RUN_DIR/state" 2>/dev/null) =~ ^(training|idle)$ ]] && told=""
        if [[ $told != stopped ]]; then
            notify warn "Training stopped on an error: trying again every 10 s. See the miner log."
            told=stopped
        else
            log "Training stopped, trying again in 10 s"
        fi
        oh_set_state waiting
        pause 10
    done
}
