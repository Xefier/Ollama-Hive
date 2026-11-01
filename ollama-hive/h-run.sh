#!/usr/bin/env bash

# Runs Ollama in the foreground of Hive's miner screen, so switching flight sheet starts and stops it.
# Nothing here installs a system service: with another flight sheet active, Ollama is not running and holds no GPU memory.

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
. ./h-common.sh

LOG_FILE="$CUSTOM_LOG_BASENAME.log"
mkdir -p "$CUSTOM_LOG_BASEDIR" "$OH_RUN_DIR"
touch "$LOG_FILE"

log() {
    echo "[ollama-hive] $(date '+%F %T') $*" | tee -a "$LOG_FILE"
}

# Shows on the Hive dashboard
notify() {
    log "$2"
    command -v message >/dev/null 2>&1 && message "$1" "ollama-hive: $2" >/dev/null 2>&1
}

on_stop() {
    trap '' INT TERM HUP
    log "Stopping"
    rm -f "$OH_RUN_DIR/run.pid"
    bash ./h-stop.sh 2>&1 | tee -a "$LOG_FILE"
    exit 0
}
trap on_stop INT TERM HUP

# Sleeps in a way a stop signal interrupts at once
pause() {
    sleep "$1" &
    wait $!
}

# A previous run that died without cleaning up
if [[ -f $OH_RUN_DIR/guard.pid ]]; then
    kill "$(< "$OH_RUN_DIR/guard.pid")" 2>/dev/null
    rm -f "$OH_RUN_DIR/guard.pid"
fi
bash ./h-stop.sh >> "$LOG_FILE" 2>&1

echo "$$" > "$OH_RUN_DIR/run.pid"
date +%s > "$OH_RUN_DIR/started"
oh_set_state starting
setsid bash ./h-guard.sh "$$" </dev/null >/dev/null 2>&1 &
echo "$!" > "$OH_RUN_DIR/guard.pid"

# Waits until the rig is safe to use instead of exiting: Hive would only start this again
wait_for_blocker() {
    local reported=""
    local blocker
    while true; do
        blocker=$("$@")
        [[ -z $blocker ]] && return 0
        if [[ $blocker != "$reported" ]]; then
            notify warn "$blocker"
            reported=$blocker
        fi
        oh_set_state waiting
        pause 30
    done
}

find_settings_problem() {
    [[ -n $OH_MODEL ]] || { echo "No model set: add model=<name> to the flight sheet's Extra config arguments"; return; }
    command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L 2>/dev/null | grep -q '^GPU' \
        || echo "No NVIDIA GPU found: this miner only supports NVIDIA"
}

# Never takes a GPU from a rental. A rented container can be idle, so running containers count as well as GPU processes.
find_gpu_user() {
    local apps containers
    apps=$(nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader 2>/dev/null)
    if [[ -n $apps ]]; then
        echo "Waiting: the GPU is in use by: ${apps//$'\n'/; }"
        return
    fi
    if [[ $OH_ALLOW_DOCKER != 1 ]] && command -v docker >/dev/null 2>&1; then
        containers=$(docker ps --format '{{.Names}}' 2>/dev/null)
        if [[ -n $containers ]]; then
            echo "Waiting: Docker containers are running (possibly a rental): ${containers//$'\n'/, }. If they are safe to share with, set allow_docker=1"
        fi
    fi
}

# Tries the rig's package lists as they are first: refreshing them is slow and usually not needed
install_package() {
    log "Installing $1"
    DEBIAN_FRONTEND=noninteractive apt-get install -y "$1" >> "$LOG_FILE" 2>&1 && return 0
    apt-get update >> "$LOG_FILE" 2>&1
    DEBIAN_FRONTEND=noninteractive apt-get install -y "$1" >> "$LOG_FILE" 2>&1 && return 0
    log "Could not install $1"
    return 1
}

install_ollama() {
    local wanted=$OH_OLLAMA_VERSION
    if [[ -x $OH_BIN ]]; then
        [[ -z $wanted || $("$OH_BIN" --version 2>/dev/null) == *"$wanted"* ]] && return 0
    fi

    local base="https://ollama.com/download/ollama-linux-amd64"
    local query=${wanted:+?version=$wanted}
    local archive="$OH_DATA_DIR/ollama-download"
    log "Downloading Ollama ${wanted:-latest}"
    mkdir -p "$OH_DATA_DIR"

    if curl -fsSIL "$base.tar.zst$query" >/dev/null 2>&1; then
        command -v zstd >/dev/null 2>&1 || install_package zstd || return 1
        curl -fL --retry 3 -C - -o "$archive" "$base.tar.zst$query" &
        wait $! || return 1
        zstd -dc "$archive" | tar -xf - -C "$OH_DATA_DIR" || return 1
    else
        curl -fL --retry 3 -C - -o "$archive" "$base.tgz$query" &
        wait $! || return 1
        tar -xzf "$archive" -C "$OH_DATA_DIR" || return 1
    fi
    rm -f "$archive"

    "$OH_BIN" --version >> "$LOG_FILE" 2>&1 || { log "The Ollama binary does not run on this system"; return 1; }
}

# Mining limits slow the model and can make it unstable. Hive applies these from the OC profile, not the flight sheet.
check_gpu_tuning() {
    if [[ $OH_RESET_OC == 1 ]]; then
        log "Resetting GPU clock locks and power limits (reset_oc=1)"
        nvidia-smi -rgc >> "$LOG_FILE" 2>&1
        nvidia-smi -rmc >> "$LOG_FILE" 2>&1
        nvidia-smi --query-gpu=index,power.default_limit --format=csv,noheader,nounits 2>/dev/null |
            while IFS=', ' read -r index limit; do
                nvidia-smi -i "$index" -pl "$limit" >> "$LOG_FILE" 2>&1
            done
        return
    fi
    nvidia-smi --query-gpu=index,power.limit,power.default_limit --format=csv,noheader,nounits 2>/dev/null |
        while IFS=', ' read -r index limit default; do
            if [[ ${limit%.*} -lt ${default%.*} ]]; then
                log "GPU $index power is limited to ${limit} W of ${default} W: remove the OC profile or set reset_oc=1"
            fi
        done
}

# LAN only: Ollama has no authentication of its own
open_firewall() {
    command -v iptables >/dev/null 2>&1 || install_package iptables || return 1

    local allow=${OH_ALLOW//,/ }
    if [[ -z $allow ]]; then
        allow=$(ip -o -4 route show scope link 2>/dev/null |
            awk '$3 !~ /^(docker|br-|veth|virbr)/ && $1 ~ /\// {print $1}' | tr '\n' ' ')
    fi
    [[ -n ${allow// /} ]] || { log "Could not work out the LAN: set allow=<cidr> in the flight sheet"; return 1; }

    iptables -N "$OH_CHAIN" 2>/dev/null
    iptables -F "$OH_CHAIN" || return 1
    iptables -A "$OH_CHAIN" -i lo -j ACCEPT || return 1
    local cidr
    for cidr in $allow; do
        iptables -A "$OH_CHAIN" -s "$cidr" -j ACCEPT || return 1
    done
    iptables -A "$OH_CHAIN" -j DROP || return 1
    iptables -I INPUT -p tcp --dport "$OH_PORT" -j "$OH_CHAIN" || return 1
    log "Port $OH_PORT is open to: $allow"
}

# The watchdog's low hashrate, minimum power and load checks all mean something else here: an idle model is not a
# failed miner. h-stop.sh starts it again, and only if it was running.
stop_watchdog() {
    if systemctl is-active --quiet "$OH_WATCHDOG"; then
        touch "$OH_RUN_DIR/watchdog-stopped"
        systemctl stop "$OH_WATCHDOG"
        log "Hive watchdog stopped"
    fi
}

start_server() {
    export HOME="$OH_DATA_DIR/home"
    export OLLAMA_HOST="0.0.0.0:$OH_PORT"
    export OLLAMA_MODELS="$OH_DATA_DIR/models"
    export OLLAMA_CONTEXT_LENGTH="$OH_NUM_CTX"
    export OLLAMA_NUM_PARALLEL="$OH_NUM_PARALLEL"
    export OLLAMA_MAX_LOADED_MODELS=1
    export OLLAMA_KEEP_ALIVE=-1
    [[ -n $OH_GPUS ]] && export CUDA_VISIBLE_DEVICES="$OH_GPUS"
    mkdir -p "$HOME" "$OLLAMA_MODELS"

    # Its own process group, so h-stop.sh also ends the model runner it starts
    setsid "$OH_BIN" serve >> "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    echo "$SERVER_PID" > "$OH_RUN_DIR/server.pid"

    local i
    for (( i = 0; i < 60; i++ )); do
        curl -fs --max-time 2 "$OH_API/api/version" >/dev/null 2>&1 && return 0
        kill -0 "$SERVER_PID" 2>/dev/null || return 1
        pause 1
    done
    return 1
}

# Retries, so an unreachable registry doesn't stop a model that is already on disk from being used later
prepare_model() {
    while kill -0 "$SERVER_PID" 2>/dev/null; do
        if ! OLLAMA_HOST="127.0.0.1:$OH_PORT" "$OH_BIN" show "$OH_MODEL" >/dev/null 2>&1; then
            oh_set_state pulling
            log "Pulling $OH_MODEL. Free space: $(df -h --output=avail "$OH_DATA_DIR" 2>/dev/null | tail -n 1 | tr -d ' ')"
            OLLAMA_HOST="127.0.0.1:$OH_PORT" "$OH_BIN" pull "$OH_MODEL" >> "$LOG_FILE" 2>&1 &
            if ! wait $!; then
                notify warn "Could not pull $OH_MODEL, retrying in 60 s. See the miner log."
                pause 60
                continue
            fi
        fi

        oh_set_state loading
        log "Loading $OH_MODEL"
        curl -fs --max-time 900 "$OH_API/api/generate" \
            -d "{\"model\":\"$OH_MODEL\",\"keep_alive\":-1}" >/dev/null 2>&1 &
        if wait $!; then
            return 0
        fi
        notify warn "Could not load $OH_MODEL, retrying in 60 s. See the miner log."
        pause 60
    done
    return 1
}

# A model that spills out of VRAM is far slower and also loads the CPU and RAM
report_placement() {
    local line size vram
    line=$(curl -fs --max-time 5 "$OH_API/api/ps" | jq -r '.models[0] | "\(.size) \(.size_vram)"' 2>/dev/null)
    read -r size vram <<< "$line"
    if [[ $size =~ ^[0-9]+$ && $vram =~ ^[0-9]+$ && $size -gt 0 ]]; then
        local percent=$(( vram * 100 / size ))
        if [[ $percent -lt 100 ]]; then
            notify warn "$OH_MODEL is only $percent% on GPU: lower num_ctx or num_parallel, or use a smaller model"
        else
            log "$OH_MODEL is 100% on GPU ($(( size / 1024 / 1024 )) MiB, num_ctx=$OH_NUM_CTX x $OH_NUM_PARALLEL)"
        fi
    fi
}

wait_for_blocker find_settings_problem
wait_for_blocker find_gpu_user

until install_ollama; do
    notify warn "Could not install Ollama, retrying in 60 s. See the miner log."
    oh_set_state waiting
    pause 60
done

check_gpu_tuning

# Fails closed: without the firewall rules the server is never started on 0.0.0.0
until open_firewall; do
    notify warn "Could not set the firewall rules, retrying in 60 s."
    oh_set_state waiting
    pause 60
done

stop_watchdog

tail -n 0 -F "$LOG_FILE" 2>/dev/null &
echo "$!" > "$OH_RUN_DIR/tail.pid"

while true; do
    oh_set_state starting
    if start_server && prepare_model; then
        report_placement
        oh_set_state ready
        notify info "$OH_MODEL is ready on port $OH_PORT"
        wait "$SERVER_PID"
    fi
    kill -TERM -- "-$SERVER_PID" 2>/dev/null
    notify warn "The Ollama server stopped, restarting in 10 s. See the miner log."
    oh_set_state restarting
    pause 10
done
