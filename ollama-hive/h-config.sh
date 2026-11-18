#!/usr/bin/env bash

# Sourced by Hive when the flight sheet is applied, so it must never call exit.
# Reads key=value settings from the flight sheet's "Extra config arguments" (CUSTOM_USER_CONFIG), one per line or
# separated by spaces. Each value is checked, because h-run.sh sources the file this writes.

ollama_hive_valid() {
    case "$1" in
        model)                          [[ $2 =~ ^[A-Za-z0-9._:/-]+$ ]] ;;
        num_ctx|num_parallel|port)      [[ $2 =~ ^[0-9]+$ ]] ;;
        mode)                           [[ $2 =~ ^(serve|train|export)$ ]] ;;
        base|full_base)                 [[ $2 =~ ^[A-Za-z0-9._/-]+$ ]] ;;
        export_name)                    [[ $2 =~ ^[A-Za-z0-9._:/-]+$ ]] ;;
        quant)                          [[ $2 =~ ^[A-Za-z0-9_]+$ ]] ;;
        llama_cpp)                      [[ $2 =~ ^b[0-9]+$ ]] ;;
        # No & ; or quotes: h-run.sh sources this value
        dataset)                        [[ $2 =~ ^(https?://[A-Za-z0-9._:/%=+?-]+|/[A-Za-z0-9._/-]+)$ ]] ;;
        peers)                          [[ $2 =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(,[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)*$ ]] ;;
        train_port|epochs|lora_r|step_size|save_steps) [[ $2 =~ ^[1-9][0-9]*$ ]] ;;
        # One limit, one per GPU memory size in GB (24:2048,32:6144), or auto: every rig measures its own
        max_len)                        [[ $2 =~ ^(auto|[1-9][0-9]*(:[1-9][0-9]*(,[1-9][0-9]*:[1-9][0-9]*)*)?)$ ]] ;;
        lr)                             [[ $2 =~ ^[0-9]+(\.[0-9]+)?(e-?[0-9]+)?$ ]] ;;
        run_name)                       [[ $2 =~ ^[A-Za-z0-9._-]+$ ]] ;;
        torch_index)                    [[ $2 =~ ^(cu[0-9]+|cpu)$ ]] ;;
        allow)                          [[ $2 =~ ^[0-9./,]+$ ]] ;;
        data_dir)                       [[ $2 =~ ^/[A-Za-z0-9._/-]+$ ]] ;;
        ollama_version)                 [[ $2 =~ ^[A-Za-z0-9.+-]+$ ]] ;;
        gpus)                           [[ $2 =~ ^[0-9,]+$ ]] ;;
        bind)                           [[ $2 =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ && $2 != 0.0.0.0 ]] ;;
        reset_oc|allow_docker|flash_attention) [[ $2 =~ ^[01]$ ]] ;;
        kv_cache_type)                  [[ $2 =~ ^(f16|q8_0|q4_0)$ ]] ;;
        *)                              return 2 ;;
    esac
}

ollama_hive_config() {
    local item key value result
    local conf=""

    for item in $CUSTOM_USER_CONFIG; do
        key=${item%%=*}
        value=${item#*=}
        if [[ $item != *=* ]]; then
            echo "ollama-hive: ignoring '$item': expected key=value"
            continue
        fi
        ollama_hive_valid "$key" "$value"
        result=$?
        if [[ $result -eq 2 ]]; then
            echo "ollama-hive: ignoring unknown setting '$key'"
        elif [[ $result -ne 0 ]]; then
            echo "ollama-hive: ignoring invalid value for '$key'"
        else
            conf+="OH_${key^^}=${value}"$'\n'
        fi
    done

    printf '%s' "$conf" > "$CUSTOM_CONFIG_FILENAME"
}

ollama_hive_config
unset -f ollama_hive_valid ollama_hive_config
