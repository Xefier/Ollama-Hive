#!/usr/bin/env bash

# Puts the rig back as it was: no Ollama or training run on the GPU, no firewall rules, watchdog running if it was before.
# Safe to run any number of times. h-run.sh runs it when stopped, h-guard.sh if h-run.sh is killed outright. Hive itself
# won't: for a custom miner it looks for h-stop.sh in /hive/miners/custom, not in this folder.

. "$(dirname "${BASH_SOURCE[0]}")/h-common.sh"

if [[ -f $OH_RUN_DIR/tail.pid ]]; then
    kill "$(< "$OH_RUN_DIR/tail.pid")" 2>/dev/null
    rm -f "$OH_RUN_DIR/tail.pid"
fi

if [[ -f $OH_RUN_DIR/server.pid ]]; then
    # A training run saves its progress when asked to stop, which takes longer than Ollama letting go
    grace=10
    [[ $OH_MODE == train ]] && grace=40
    oh_stop_group "$(< "$OH_RUN_DIR/server.pid")" "$grace"
    rm -f "$OH_RUN_DIR/server.pid"
fi
# Runners and pulls that outlived the server, and only ours: the match is on this miner's own binary path
pkill -KILL -f "^$OH_BIN( |$)" 2>/dev/null
pkill -KILL -f "$OH_DATA_DIR/lib/ollama" 2>/dev/null
pkill -KILL -f "$OH_DATA_DIR/ollama-download" 2>/dev/null
# A training run or an export, or the install of their tools (uv, the venvs' python, the workers, llama.cpp)
if [[ -f $OH_RUN_DIR/status.pid ]]; then
    kill "$(< "$OH_RUN_DIR/status.pid")" 2>/dev/null
    rm -f "$OH_RUN_DIR/status.pid"
fi
rm -f "$OH_RUN_DIR/train-status"
if [[ -f $OH_RUN_DIR/export-run.pid ]]; then
    # export-run.sh, before the step it is on (below)
    kill -KILL -- "-$(< "$OH_RUN_DIR/export-run.pid")" 2>/dev/null
    rm -f "$OH_RUN_DIR/export-run.pid"
fi
if [[ -f $OH_RUN_DIR/export.pid ]]; then
    kill -KILL -- "-$(< "$OH_RUN_DIR/export.pid")" 2>/dev/null
    rm -f "$OH_RUN_DIR/export.pid"
fi
pkill -KILL -f "$OH_TRAIN_DIR/(bin|venv|convert)/" 2>/dev/null

oh_remove_firewall
rm -f "$OH_RUN_DIR/address"

if [[ -f $OH_RUN_DIR/watchdog-stopped ]]; then
    systemctl start "$OH_WATCHDOG" && echo "Hive watchdog started"
    rm -f "$OH_RUN_DIR/watchdog-stopped"
fi

oh_set_state stopped
