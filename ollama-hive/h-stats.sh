#!/usr/bin/env bash

# Sourced by Hive's agent, which reads $khs and $stats. Must stay quick and must not exit.
# There is no hashrate, so each GPU reports 1 H/s while the model is loaded and answering (or, with mode=train, while
# the run is training, not while it waits for new examples), and 0 otherwise: a glance at the dashboard shows whether
# the service is up.

. "$(dirname "${BASH_SOURCE[0]}")/h-common.sh"

oh_gpu_stats="${GPU_STATS_JSON:-/run/hive/gpu-stats.json}"
oh_state=$(cat "$OH_RUN_DIR/state" 2>/dev/null)
oh_started=$(cat "$OH_RUN_DIR/started" 2>/dev/null)
oh_algo="ollama ${oh_state:-stopped}"
if [[ $OH_MODE == train ]]; then
    oh_loaded=0
    # train.py's last "step 120, 780 to go loss 1.234"
    oh_algo="qlora ${oh_state:-stopped} $(cat "$OH_RUN_DIR/train-status" 2>/dev/null)"
    oh_algo=${oh_algo% }
else
    oh_ps=$(curl -fs --max-time 2 "$OH_API/api/ps" 2>/dev/null)
    oh_loaded=$(jq -r '.models | length' 2>/dev/null <<< "$oh_ps")
    # A model that isn't all on the GPU runs partly on the CPU, far slower: said where the dashboard shows it, for as
    # long as it is so. The miner log and the progress page say what to change.
    oh_on_gpu=$(jq -r '.models[0] | if (.size // 0) > 0 then (.size_vram * 100 / .size | floor) else 100 end' 2>/dev/null <<< "$oh_ps")
    [[ $oh_on_gpu =~ ^[0-9]+$ && $oh_on_gpu -lt 100 ]] && oh_algo="$oh_algo, only $oh_on_gpu% on GPU"
fi

oh_temp='[]'
oh_fan='[]'
oh_bus='[]'
if [[ -f $oh_gpu_stats ]]; then
    # Hive lists onboard graphics too; only cards count
    oh_cards='[.brand | to_entries[] | select(.value != "cpu") | .key] as $i'
    oh_temp=$(jq -c "$oh_cards | [\$i[] as \$k | .temp[\$k] | tonumber]" "$oh_gpu_stats" 2>/dev/null)
    oh_fan=$(jq -c "$oh_cards | [\$i[] as \$k | .fan[\$k] | tonumber]" "$oh_gpu_stats" 2>/dev/null)
    oh_bus=$(jq -c "$oh_cards | [\$i[] as \$k | .busids[\$k] | split(\":\")[0] | tonumber? // 0]" "$oh_gpu_stats" 2>/dev/null)
fi
[[ -n $oh_temp ]] || oh_temp='[]'
[[ -n $oh_fan ]] || oh_fan='[]'
[[ -n $oh_bus ]] || oh_bus='[]'

oh_value=0
[[ $oh_state == ready && ${oh_loaded:-0} -gt 0 ]] && oh_value=1
[[ $OH_MODE == train && $oh_state == training ]] && oh_value=1

oh_count=$(jq -r 'length' <<< "$oh_temp" 2>/dev/null)
[[ ${oh_count:-0} -gt 0 ]] || oh_count=1
khs=$(awk -v v="$oh_value" -v c="$oh_count" 'BEGIN { printf "%.3f", v * c / 1000 }')

oh_uptime=0
[[ $oh_started =~ ^[0-9]+$ ]] && oh_uptime=$(( $(date +%s) - oh_started ))

stats=$(jq -nc \
    --argjson value "$oh_value" --argjson count "$oh_count" \
    --argjson temp "$oh_temp" --argjson fan "$oh_fan" --argjson bus "$oh_bus" \
    --argjson uptime "$oh_uptime" \
    --arg ver "${CUSTOM_VERSION:-}" --arg algo "$oh_algo" \
    '{hs: [range(0; $count) | $value], hs_units: "hs", temp: $temp, fan: $fan, bus_numbers: $bus,
      uptime: $uptime, ver: $ver, ar: [0, 0], algo: $algo}')
