#!/usr/bin/env bash

# Makes an Ollama model out of a training run, on a rig that is serving, without touching its flight sheet:
#
#   /hive/miners/custom/ollama-hive/export-run.sh from=192.168.1.232 export_name=qwen3.8-unity:27b
#
# Run it from Hive's "Run command" or a shell on the rig. It returns at once and works on in the background, saying
# how it goes in the miner log. The model it makes is then one more model of this rig's Ollama: ask for it by name.
#
#   from=         a rig that is training the run: its adapter is fetched from there, as it stands now. Without it,
#                 the adapter already on this rig is used (<data_dir>/train/runs/<run_name>/adapter)
#   export_name=  the Ollama model to make. Default: the run's name
#   full_base=    Hugging Face repo of the base model at full precision. Default: the flight sheet's, of this rig or
#                 of the rig in from=
#   run_name=, model=, quant=, llama_cpp=   as on a mode=export flight sheet. model= is the stock model whose
#                 Modelfile is reused: by default the one this rig serves
#
# It is the same work as mode=export (h-export.sh), which a flight sheet does before it serves. Everything but the
# last step runs on the CPU, so the model this rig serves stays loaded; the rig is slower meanwhile. Stopping the
# miner stops it, as for a rental: run the command again and it goes on where it was.

cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
. ./h-common.sh
. ./h-log.sh
. ./h-train.sh
. ./h-export.sh

mkdir -p "$CUSTOM_LOG_BASEDIR" "$OH_RUN_DIR"
OH_EXPORT_PID_FILE="$OH_RUN_DIR/export-run.pid"

# The miner's state and status line are the flight sheet's, not this command's: its own are in files beside them,
# which the progress page shows as well (status.py --export-files)
OH_EXPORT_STATUS_FILE="$OH_RUN_DIR/export-status"
oh_set_state() {
    echo "$1" > "$OH_RUN_DIR/export-state"
}

fail() {
    log "export-run: $*"
    exit 1
}

background=0
[[ $1 == --in-background ]] && { background=1; shift; }

from=""
OH_EXPORT_NAME=""
for item in "$@"; do
    value=${item#*=}
    case $item in
        from=*)         from=$value ;;
        export_name=*)  OH_EXPORT_NAME=$value ;;
        full_base=*)    OH_FULL_BASE=$value ;;
        run_name=*)     OH_RUN_NAME=$value ;;
        model=*)        OH_MODEL=$value ;;
        quant=*)        OH_QUANT=$value ;;
        llama_cpp=*)    OH_LLAMA_CPP=$value ;;
        *)              echo "Not a setting of this command: $item"; sed -n '3,19p' "${BASH_SOURCE[0]}" | cut -c3-; exit 2 ;;
    esac
done
[[ "$from$OH_EXPORT_NAME$OH_FULL_BASE$OH_RUN_NAME$OH_MODEL$OH_QUANT$OH_LLAMA_CPP" =~ ^[A-Za-z0-9._:/-]*$ ]] \
    || { echo "A setting has a character that isn't a letter, a digit or one of . _ : / -"; exit 2; }

if [[ $background == 0 ]]; then
    if [[ -f $OH_EXPORT_PID_FILE ]] && kill -0 "$(< "$OH_EXPORT_PID_FILE")" 2>/dev/null; then
        echo "An export is already running on this rig: see the miner log ($LOG_FILE)"
        exit 1
    fi
    # What it says goes to the miner log by itself (log), so only what goes wrong unsaid is sent there
    setsid bash "${BASH_SOURCE[0]}" --in-background "$@" < /dev/null > /dev/null 2>> "$LOG_FILE" &
    echo "Started. It says how it goes in the miner log: $LOG_FILE"
    exit 0
fi

echo "$$" > "$OH_EXPORT_PID_FILE"
trap 'rm -f "$OH_EXPORT_PID_FILE" "$OH_RUN_DIR/export-state" "$OH_EXPORT_STATUS_FILE"' EXIT
log "export-run: $*"

address=$(cat "$OH_RUN_DIR/address" 2>/dev/null)
OH_API="http://$address:$OH_PORT"
[[ -n $address ]] && curl -fs --max-time 5 "$OH_API/api/version" >/dev/null 2>&1 \
    || fail "No Ollama is running on this rig for the model to go to. Run this on a rig that is serving; a rig that trains makes its model with a mode=export flight sheet"
# As h-run.sh sets them for the server: the ollama commands here talk to that server
export HOME="$OH_DATA_DIR/home"
export OLLAMA_HOST="$address:$OH_PORT"
export OLLAMA_MODELS="$OH_DATA_DIR/models"

# Takes the run's adapter from a rig that is training it (status.py there hands it out). That rig writes it anew at
# every checkpoint, so what it says it has is compared before and after.
fetch_adapter() {
    local source=$1
    [[ $source == *:* ]] || source="$source:$OH_STATUS_PORT"
    oh_is_private "$source" || { log "from=$from is not a private LAN address"; return 1; }
    local listing again kind name size try
    for try in 1 2 3; do
        listing=$(curl -fs --max-time 20 "http://$source/adapter") \
            || { log "http://$source/adapter gave nothing: is that rig on the training flight sheet, with v0.15 or newer, and has it trained a step?"; return 1; }
        name=$(awk '$1 == "run" { print $2 }' <<< "$listing")
        [[ -z $run_given && -n $name ]] && OH_RUN_NAME=$name
        [[ -n $OH_FULL_BASE ]] || OH_FULL_BASE=$(awk '$1 == "full_base" { print $2 }' <<< "$listing")
        OH_RUN_PATH="$OH_TRAIN_DIR/runs/$OH_RUN_NAME"
        local seen target="$OH_RUN_PATH/adapter" incoming="$OH_RUN_PATH/adapter.incoming"
        seen=$(awk '$1 == "seen" { print $2 }' <<< "$listing")
        if [[ -n $seen && $(cat "$target/examples-seen" 2>/dev/null) == "$seen" ]]; then
            log "The adapter of run $OH_RUN_NAME on this rig is already the one $source has (trained on $seen examples)"
            return 0
        fi
        log "Fetching the adapter of run $OH_RUN_NAME from $source (trained on $seen examples)"
        rm -rf "$incoming"
        mkdir -p "$incoming"
        local complete=1
        while read -r kind name size; do
            [[ $kind == file ]] || continue
            curl -fs --max-time 1800 -o "$incoming/$name" "http://$source/adapter/$name" &
            wait $! && [[ $(stat -c %s "$incoming/$name" 2>/dev/null) == "$size" ]] || { complete=0; break; }
        done <<< "$listing"
        again=$(curl -fs --max-time 20 "http://$source/adapter")
        if [[ $complete == 1 && $again == "$listing" ]]; then
            rm -rf "$target"
            mv "$incoming" "$target"
            return 0
        fi
        log "The adapter changed while it was fetched (that rig saved a checkpoint): once more"
        sleep 5
    done
    rm -rf "$incoming"
    log "Could not fetch a whole adapter from $source"
    return 1
}

run_given=""
for item in "$@"; do
    [[ $item == run_name=* ]] && run_given=1
done
if [[ -n $from ]]; then
    fetch_adapter "$from" || exit 1
fi
OH_RUN_PATH="$OH_TRAIN_DIR/runs/$OH_RUN_NAME"
OH_EXPORT_WORK="$OH_RUN_PATH/export"
OH_STOCK_MODEL=$OH_MODEL
[[ -n $OH_EXPORT_NAME ]] || OH_EXPORT_NAME=$OH_RUN_NAME

problem=$(find_export_settings_problem)
[[ -z $problem ]] || fail "${problem/to the flight sheet/to the command}"
"$OH_BIN" show "$OH_EXPORT_NAME" >/dev/null 2>&1 \
    && fail "This rig already has a model called $OH_EXPORT_NAME: give another export_name=, or remove it first (ollama rm)"

# The downloads are where it most often stops, and they are back by themselves: every stage that is done stays done
for attempt in 1 2 3 4 5; do
    if export_model; then
        log "export-run: $OH_EXPORT_NAME is ready on this rig"
        exit 0
    fi
    [[ $attempt == 5 ]] || { log "export-run: that did not work (see above): trying again in 2 minutes, from where it stopped"; pause 120; }
done
notify warn "Could not make $OH_EXPORT_NAME from run $OH_RUN_NAME. See the miner log; the same command goes on where this stopped."
exit 1
