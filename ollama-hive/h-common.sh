#!/usr/bin/env bash

# Shared by h-run.sh, h-stop.sh, h-guard.sh and h-stats.sh.

# Hive's miner screen doesn't always have the admin folders on its PATH (iptables was "not found" there on a rig)
export PATH="$PATH:/usr/sbin:/sbin"

OH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$OH_DIR/h-manifest.conf"

OH_RUN_DIR="${OLLAMA_HIVE_TEST_ROOT:-}/run/ollama-hive"
OH_CHAIN="OLLAMA_HIVE"
OH_WATCHDOG="hive-watchdog"

OH_MODEL=""
OH_NUM_CTX=32768
OH_NUM_PARALLEL=2
OH_PORT=11434
OH_ALLOW=""
# Outside the miner folder: custom-get deletes that folder when a new version of this miner is installed.
# On the rigs' big data drive when it is mounted, since models are tens of GB and the OS drive is small.
OH_DATA_DIR="${OLLAMA_HIVE_TEST_ROOT:-}/var/lib/ollama-hive"
mountpoint -q "${OLLAMA_HIVE_TEST_ROOT:-}/var/lib/docker" 2>/dev/null \
    && OH_DATA_DIR="${OLLAMA_HIVE_TEST_ROOT:-}/var/lib/docker/ollama-hive"
OH_OLLAMA_VERSION=""
OH_GPUS=""
OH_RESET_OC=0
OH_ALLOW_DOCKER=0

[[ -f $CUSTOM_CONFIG_FILENAME ]] && . "$CUSTOM_CONFIG_FILENAME"

OH_BIN="$OH_DATA_DIR/bin/ollama"
OH_API="http://127.0.0.1:$OH_PORT"

oh_set_state() {
    mkdir -p "$OH_RUN_DIR"
    echo "$1" > "$OH_RUN_DIR/state"
}
