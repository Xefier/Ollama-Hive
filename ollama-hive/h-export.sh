#!/usr/bin/env bash

# mode=export, sourced by h-run.sh: makes the Ollama model <export_name> out of a training run as it stands, then
# h-run.sh serves it like any other. Ollama no longer loads LoRA adapters, so the adapter is merged into the full-precision
# base model (export.py), converted to GGUF and quantized with llama.cpp, and imported with the stock model's
# Modelfile. Once the model exists none of this runs again, so the flight sheet can stay on mode=export.

# model= is the stock Ollama model here: its Modelfile and vision projector are reused
OH_STOCK_MODEL=$OH_MODEL
OH_CONVERT_DIR="$OH_TRAIN_DIR/convert"
OH_EXPORT_WORK="$OH_RUN_PATH/export"
# Where the progress page reads how the export is going: the flight sheet's status line, unless export-run.sh,
# which runs beside a flight sheet that has its own, names another
OH_EXPORT_STATUS_FILE="$OH_RUN_DIR/train-status"

# A line that starts with "<number>% · " is drawn as a progress bar by the page. The export's four steps take their
# time in about these parts: 70% adding the adapter (which downloads the base model), 15% converting, 12% quantizing.
export_says() {
    echo "$1" > "$OH_EXPORT_STATUS_FILE"
}

# For the next export_step, which writes one big file: says every 10 s how far that file is.
# $1 the file, $2 its size when done (bytes, roughly), $3 and $4 the percents the step goes from and to, $5 the step
export_watching() {
    OH_WATCH_FILE=$1 OH_WATCH_WHOLE=$2 OH_WATCH_FROM=$3 OH_WATCH_TO=$4 OH_WATCH_TEXT=$5
}

# Ends with the step it watches, also when h-stop.sh kills that step
export_watch() {
    local step=$1 size
    while kill -0 "$step" 2>/dev/null; do
        size=$(stat -c %s "$OH_WATCH_FILE" 2>/dev/null || echo 0)
        (( size > OH_WATCH_WHOLE )) && size=$OH_WATCH_WHOLE
        export_says "$(( OH_WATCH_FROM + (OH_WATCH_TO - OH_WATCH_FROM) * size / (OH_WATCH_WHOLE > 0 ? OH_WATCH_WHOLE : 1) ))% · $OH_WATCH_TEXT"
        sleep 10
    done
}

find_export_settings_problem() {
    [[ -n $OH_STOCK_MODEL ]] || { echo "No model set: add model=<the stock Ollama model the run was trained from>"; return; }
    [[ -n $OH_FULL_BASE ]] || echo "No full_base set: add full_base=<Hugging Face repo of the full-precision base model>"
}

# Runs a long step so that a stop ends it at once, and h-stop.sh can find it
export_step() {
    setsid "$@" >> "$LOG_FILE" 2>&1 &
    local step=$!
    echo "$step" > "$OH_RUN_DIR/export.pid"
    [[ -n $OH_WATCH_FILE ]] && export_watch "$step" &
    wait "$step"
    local result=$?
    OH_WATCH_FILE=""
    rm -f "$OH_RUN_DIR/export.pid"
    return $result
}

# llama.cpp's converter with the Python packages it pins, and its quantize tool. Fixed to one release (llama_cpp=).
install_export_tools() {
    local source="$OH_CONVERT_DIR/llama.cpp-$OH_LLAMA_CPP"
    local stamp="$OH_CONVERT_DIR/.installed-$OH_LLAMA_CPP"
    OH_CONVERT_SCRIPT="$source/convert_hf_to_gguf.py"
    OH_CONVERT_PYTHON="$OH_CONVERT_DIR/venv/bin/python"
    OH_QUANTIZE=$(find "$OH_CONVERT_DIR/bin-$OH_LLAMA_CPP" -name llama-quantize -type f 2>/dev/null | head -n 1)
    [[ -f $stamp && -x $OH_QUANTIZE ]] && return 0

    oh_set_state installing
    export_says "0% · installing llama.cpp, which converts the model"
    install_uv || return 1
    log "Installing llama.cpp $OH_LLAMA_CPP: the GGUF converter and llama-quantize"
    local release="https://github.com/ggml-org/llama.cpp"
    mkdir -p "$source" "$OH_CONVERT_DIR/bin-$OH_LLAMA_CPP"
    ( curl -fsSL --retry 3 "$release/archive/refs/tags/$OH_LLAMA_CPP.tar.gz" |
        tar -xz --strip-components=1 -C "$source" ) &
    wait $! || return 1
    ( curl -fsSL --retry 3 "$release/releases/download/$OH_LLAMA_CPP/llama-$OH_LLAMA_CPP-bin-ubuntu-x64.tar.gz" |
        tar -xz -C "$OH_CONVERT_DIR/bin-$OH_LLAMA_CPP" ) &
    wait $! || return 1
    OH_QUANTIZE=$(find "$OH_CONVERT_DIR/bin-$OH_LLAMA_CPP" -name llama-quantize -type f | head -n 1)
    # It prints its usage and exits non-zero; a binary this system can't run prints a loader error instead
    if ! LD_LIBRARY_PATH="$(dirname "$OH_QUANTIZE")" "$OH_QUANTIZE" --help 2>&1 | grep -qi usage; then
        log "llama-quantize of llama.cpp $OH_LLAMA_CPP does not run on this system (see below). quant=q8_0 needs no llama-quantize."
        LD_LIBRARY_PATH="$(dirname "$OH_QUANTIZE")" "$OH_QUANTIZE" --help 2>&1 | head -n 3 >> "$LOG_FILE"
        [[ ${OH_QUANT,,} == q8_0 ]] || return 1
    fi
    "$OH_UV" venv --clear --python 3.12 "$OH_CONVERT_DIR/venv" >> "$LOG_FILE" 2>&1 &
    wait $! || return 1
    # From inside its folder: the file includes another by a relative path
    ( cd "$source/requirements" && "$OH_UV" pip install --python "$OH_CONVERT_PYTHON" \
        -r requirements-convert_hf_to_gguf.txt safetensors huggingface_hub ) >> "$LOG_FILE" 2>&1 &
    wait $! || return 1
    touch "$stamp"
}

# Merged copy + its GGUF at full precision, then the quantized file and Ollama's copy of it: about 2.4 x the base
export_has_space() {
    local bytes needed free
    bytes=$("$OH_CONVERT_PYTHON" "$OH_DIR/export.py" size --base "$OH_FULL_BASE" 2>> "$LOG_FILE")
    [[ $bytes =~ ^[0-9]+$ ]] || { log "Could not read the size of $OH_FULL_BASE"; return 1; }
    needed=$(( bytes * 24 / 10 / 1024 / 1024 / 1024 + 2 ))
    free=$(( $(df --output=avail -k "$OH_DATA_DIR" | tail -n 1) / 1024 / 1024 ))
    [[ $free -ge $needed ]] && return 0
    log "The export needs about $needed GB free on $OH_DATA_DIR and there are $free GB"
    return 1
}

# The run is the flight sheet's; export-run.sh without run_name= takes the one the rig in from= trains
OH_RUN_GIVEN=1

# Takes the run's adapter from a rig that is training it (status.py there hands it out). That rig writes it anew at
# every checkpoint, so what it says it has is compared before and after.
fetch_adapter() {
    local source=$1
    [[ $source == *:* ]] || source="$source:$OH_STATUS_PORT"
    oh_is_private "$source" || { log "$source is not a private LAN address"; return 1; }
    local listing again kind name size try
    for try in 1 2 3; do
        listing=$(curl -fs --max-time 20 "http://$source/adapter") \
            || { log "http://$source/adapter gave nothing: is that rig on the training flight sheet, with v0.15 or newer, and has it trained a step?"; return 1; }
        name=$(awk '$1 == "run" { print $2 }' <<< "$listing")
        if [[ -z $OH_RUN_GIVEN && -n $name ]]; then
            OH_RUN_NAME=$name
        elif [[ -n $name && $name != "$OH_RUN_NAME" ]]; then
            log "$source trains run $name, not $OH_RUN_NAME"
            return 1
        fi
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

# For a rig that what the others say on the LAN doesn't reach (a firewall of its own, a network that carries no
# broadcasts): asks the progress page of every address that shares this rig's first three numbers for the run's
# adapter, all at once, and prints the ones that have it. Asking goes out, which such a rig can do.
ask_for_training_rigs() {
    local address
    address=$(cat "$OH_RUN_DIR/address" 2>/dev/null)
    [[ -n $address ]] || address=$(oh_lan_address)
    [[ -n $address ]] || return 1
    seq 1 254 | grep -vx "${address##*.}" |
        xargs -P 64 -I{} sh -c 'curl -fs --connect-timeout 2 --max-time 5 "http://$0.{}:$1/adapter" 2>/dev/null | grep -qx "run $2" && echo "$0.{}"' \
            "${address%.*}" "$OH_STATUS_PORT" "$OH_RUN_NAME" | sort -t . -k 4 -n
}

# The rigs training the run say so on the LAN every few seconds (meet.py): the adapter is taken from one of them, as
# it stands now, so the rig that makes the model needs no copy of its own and no address in its flight sheet.
# Without one to hear, the adapter already on this rig is the one.
fetch_adapter_from_training_rig() {
    local python rig rigs
    python=$(plain_python) || return 1
    export_says "0% · listening for a rig that is training run $OH_RUN_NAME, for its adapter"
    rigs=$("$python" "$OH_DIR/meet.py" hear --run "$OH_RUN_NAME" --port "$OH_TRAIN_PORT" 2>> "$LOG_FILE")
    if [[ -z $rigs ]]; then
        log "No rig heard training run $OH_RUN_NAME: asking every address of this rig's network instead"
        rigs=$(ask_for_training_rigs)
        [[ -n $rigs ]] || { log "No rig of this network has an adapter of run $OH_RUN_NAME"; return 1; }
    fi
    for rig in $rigs; do
        fetch_adapter "$rig" && return 0
    done
    return 1
}

# Needs the Ollama server running (start_server). Every stage leaves its result in $OH_EXPORT_WORK and is skipped when
# that result is there, so a stopped export continues where it was.
export_model() {
    if "$OH_BIN" show "$OH_EXPORT_NAME" >/dev/null 2>&1; then
        # v0.16 and earlier wrote two pairs of weights as one tensor each, which Ollama can't load (export.py
        # convert). Such a model is no use to anyone: it is made again.
        if curl -fs --max-time 300 "$OH_API/api/show" -d "{\"model\":\"$OH_EXPORT_NAME\",\"verbose\":true}" 2>/dev/null |
            grep -q 'ssm_beta_alpha\|attn_qkv_gate'; then
            log "$OH_EXPORT_NAME was made in a layout this Ollama can't load (by v0.16 or earlier): removing it and making it again"
            "$OH_BIN" rm "$OH_EXPORT_NAME" >> "$LOG_FILE" 2>&1
        else
            return 0
        fi
    fi

    local adapter="$OH_RUN_PATH/adapter"
    # Before the first stage only: a model is made of one adapter from start to end
    [[ -n $OH_ADAPTER_FETCHED || -d $OH_EXPORT_WORK ]] || fetch_adapter_from_training_rig
    if [[ ! -f $adapter/adapter_model.safetensors ]]; then
        log "No adapter of run $OH_RUN_NAME: no rig is training it just now (with v0.15 or newer, past its first step), and $adapter on this rig has none. Check run_name, or copy the folder from a rig that trained"
        return 1
    fi
    export HF_HOME="$OH_TRAIN_DIR/hf"
    export HF_HUB_DISABLE_TELEMETRY=1
    export HF_HUB_DISABLE_PROGRESS_BARS=1
    install_export_tools || return 1

    local merged="$OH_EXPORT_WORK/merged"
    local full="$OH_EXPORT_WORK/full.gguf"
    local final="$OH_EXPORT_WORK/$OH_QUANT.gguf"
    local direct=0
    # The converter writes q8_0 itself; every other level goes through llama-quantize
    [[ ${OH_QUANT,,} == q8_0 ]] && direct=1
    mkdir -p "$OH_EXPORT_WORK"

    if [[ ! -f $final ]]; then
        if [[ ! -f $full ]]; then
            [[ -d $merged ]] || export_has_space || return 1
            oh_set_state merging
            export_says "0% · step 1 of 4: adding the adapter to the base model's weights"
            log "Merging the adapter of run $OH_RUN_NAME into $OH_FULL_BASE"
            export_step "$OH_CONVERT_PYTHON" "$OH_DIR/export.py" merge \
                --adapter "$adapter" --base "$OH_FULL_BASE" --out "$merged" --status-file "$OH_EXPORT_STATUS_FILE" --status-until 70 || return 1
            oh_set_state converting
            export_says "70% · step 2 of 4: converting to the format Ollama reads"
            log "Converting to GGUF"
            local whole
            whole=$(du -sb "$merged" 2>/dev/null | cut -f 1)
            if [[ $direct == 1 ]]; then
                # No quantizing step after it then, and 8 bits of every 16
                export_watching "$final.tmp" "$(( ${whole:-0} / 2 ))" 70 97 "step 2 of 4: converting to the format Ollama reads"
                export_step "$OH_CONVERT_PYTHON" "$OH_DIR/export.py" convert "$OH_CONVERT_SCRIPT" "$merged" --outfile "$final.tmp" --outtype q8_0 || return 1
                mv "$final.tmp" "$final"
            else
                export_watching "$full.tmp" "${whole:-0}" 70 85 "step 2 of 4: converting to the format Ollama reads"
                export_step "$OH_CONVERT_PYTHON" "$OH_DIR/export.py" convert "$OH_CONVERT_SCRIPT" "$merged" --outfile "$full.tmp" --outtype bf16 || return 1
                mv "$full.tmp" "$full"
            fi
        fi
        rm -rf "$merged"
        if [[ $direct != 1 ]]; then
            oh_set_state quantizing
            export_says "85% · step 3 of 4: quantizing to $OH_QUANT"
            log "Quantizing to $OH_QUANT"
            # About what the levels leave of 16 bits a weight, in percent: near enough for a progress bar
            local kept=30
            case ${OH_QUANT^^} in
                Q8*) kept=53 ;; Q6*) kept=41 ;; Q5*) kept=36 ;; Q4*) kept=30 ;; Q3*) kept=25 ;; Q2*) kept=20 ;;
            esac
            export_watching "$final.tmp" "$(( $(stat -c %s "$full" 2>/dev/null || echo 0) / 100 * kept ))" 85 97 "step 3 of 4: quantizing to $OH_QUANT"
            LD_LIBRARY_PATH="$(dirname "$OH_QUANTIZE")" export_step "$OH_QUANTIZE" "$full" "$final.tmp" "$OH_QUANT" || return 1
            mv "$final.tmp" "$final"
            rm -f "$full"
        fi
    fi

    oh_set_state importing
    export_says "97% · step 4 of 4: handing $OH_EXPORT_NAME to Ollama"
    if ! "$OH_BIN" show "$OH_STOCK_MODEL" >/dev/null 2>&1; then
        log "Pulling $OH_STOCK_MODEL for its Modelfile and vision projector"
        export_step "$OH_BIN" pull "$OH_STOCK_MODEL" || return 1
    fi
    "$OH_BIN" show --modelfile "$OH_STOCK_MODEL" > "$OH_EXPORT_WORK/stock.Modelfile" 2>> "$LOG_FILE" || return 1
    "$OH_CONVERT_PYTHON" "$OH_DIR/export.py" modelfile "$OH_EXPORT_WORK/stock.Modelfile" "$final" \
        > "$OH_EXPORT_WORK/Modelfile" 2>> "$LOG_FILE" || return 1
    log "Creating the Ollama model $OH_EXPORT_NAME"
    export_step "$OH_BIN" create "$OH_EXPORT_NAME" -f "$OH_EXPORT_WORK/Modelfile" || return 1
    # Ollama has its own copy now
    rm -rf "$OH_EXPORT_WORK"
    rm -f "$OH_EXPORT_STATUS_FILE"
    notify info "$OH_EXPORT_NAME is made from run $OH_RUN_NAME. model=$OH_EXPORT_NAME serves it without mode=export too"
    return 0
}
