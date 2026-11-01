#!/usr/bin/env bash

# Runs beside h-run.sh in its own session, so it survives h-run.sh being killed outright. Without it, a hard kill would
# leave Ollama holding the GPU under the next flight sheet (a rental, say) and the watchdog off until the next reboot.

. "$(dirname "${BASH_SOURCE[0]}")/h-common.sh"

run_pid=$1
oh_dir="$(dirname "${BASH_SOURCE[0]}")"

while kill -0 "$run_pid" 2>/dev/null; do
    # Something in Hive may start it again while this flight sheet is active
    if [[ -f $OH_RUN_DIR/watchdog-stopped ]] && systemctl is-active --quiet "$OH_WATCHDOG"; then
        systemctl stop "$OH_WATCHDOG"
    fi
    sleep 15
done

# h-run.sh removes run.pid when it stops properly, and a new run replaces it: both have cleaned up already
[[ -f $OH_RUN_DIR/run.pid && $(< "$OH_RUN_DIR/run.pid") == "$run_pid" ]] || exit 0
rm -f "$OH_RUN_DIR/run.pid" "$OH_RUN_DIR/guard.pid"
bash "$oh_dir/h-stop.sh"
