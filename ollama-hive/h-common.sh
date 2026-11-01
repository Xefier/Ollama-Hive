#!/usr/bin/env bash

# Shared by h-run.sh, h-stop.sh, h-guard.sh and h-stats.sh.

# Hive's miner screen doesn't always have the admin folders on its PATH
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
OH_BIND=""

[[ -f $CUSTOM_CONFIG_FILENAME ]] && . "$CUSTOM_CONFIG_FILENAME"

OH_BIN="$OH_DATA_DIR/bin/ollama"
# The address h-run.sh is serving on. Ollama doesn't listen on 127.0.0.1 here, so this is how to reach it on the rig too.
OH_API="http://$(cat "$OH_RUN_DIR/address" 2>/dev/null || echo 127.0.0.1):$OH_PORT"

oh_is_private() {
    [[ $1 =~ ^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.) ]]
}

# Where to listen: bind= from the flight sheet, or else this rig's private LAN address. Empty if it has none, because
# Ollama has no authentication and must never listen on a public address or on 0.0.0.0 by default.
oh_lan_address() {
    if [[ -n $OH_BIND ]]; then
        echo "$OH_BIND"
        return
    fi
    local address
    address=$(ip -4 route get 1.1.1.1 2>/dev/null | grep -oP 'src \K[0-9.]+' | head -n 1)
    if oh_is_private "$address"; then
        echo "$address"
        return
    fi
    ip -o -4 addr show scope global 2>/dev/null |
        awk '$2 !~ /^(docker|br-|veth|virbr)/ { split($4, a, "/"); print a[1] }' |
        while read -r address; do
            if oh_is_private "$address"; then
                echo "$address"
                break
            fi
        done
}

oh_remove_firewall() {
    local command i
    for command in iptables iptables-legacy; do
        command -v "$command" >/dev/null 2>&1 || continue
        for (( i = 0; i < 20; i++ )); do
            "$command" -D INPUT -p tcp --dport "$OH_PORT" -j "$OH_CHAIN" 2>/dev/null || break
        done
        "$command" -F "$OH_CHAIN" 2>/dev/null
        "$command" -X "$OH_CHAIN" 2>/dev/null
    done
    # iptables can create a chain on a kernel where it then can't read or delete it
    command -v nft >/dev/null 2>&1 && nft delete chain ip filter "$OH_CHAIN" 2>/dev/null
}

oh_set_state() {
    mkdir -p "$OH_RUN_DIR"
    echo "$1" > "$OH_RUN_DIR/state"
}
