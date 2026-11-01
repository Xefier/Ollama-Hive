#!/usr/bin/env bash

# Puts the rig back as it was: no Ollama on the GPU, no firewall rules, watchdog running if it was before.
# Safe to run any number of times. h-run.sh runs it when stopped, h-guard.sh if h-run.sh is killed outright. Hive itself
# won't: for a custom miner it looks for h-stop.sh in /hive/miners/custom, not in this folder.

. "$(dirname "${BASH_SOURCE[0]}")/h-common.sh"

if [[ -f $OH_RUN_DIR/tail.pid ]]; then
    kill "$(< "$OH_RUN_DIR/tail.pid")" 2>/dev/null
    rm -f "$OH_RUN_DIR/tail.pid"
fi

if [[ -f $OH_RUN_DIR/server.pid ]]; then
    server_pid=$(< "$OH_RUN_DIR/server.pid")
    kill -TERM -- "-$server_pid" 2>/dev/null
    for (( i = 0; i < 10; i++ )); do
        kill -0 "$server_pid" 2>/dev/null || break
        sleep 1
    done
    kill -KILL -- "-$server_pid" 2>/dev/null
    rm -f "$OH_RUN_DIR/server.pid"
fi
# Runners and pulls that outlived the server, and only ours: the match is on this miner's own binary path
pkill -KILL -f "^$OH_BIN( |$)" 2>/dev/null
pkill -KILL -f "$OH_DATA_DIR/lib/ollama" 2>/dev/null
pkill -KILL -f "$OH_DATA_DIR/ollama-download" 2>/dev/null

oh_remove_firewall
rm -f "$OH_RUN_DIR/address"

if [[ -f $OH_RUN_DIR/watchdog-stopped ]]; then
    systemctl start "$OH_WATCHDOG" && echo "Hive watchdog started"
    rm -f "$OH_RUN_DIR/watchdog-stopped"
fi

oh_set_state stopped
