#!/usr/bin/env bash

# Sourced by Hive's agent, which reads $khs and $stats. Must stay quick and must not exit.
# There is no hashrate, so each GPU reports 1 H/s while the model is loaded and answering, and 0 otherwise: a glance at
# the dashboard shows whether the service is up.

. "$(dirname "${BASH_SOURCE[0]}")/h-common.sh"

oh_gpu_stats="${GPU_STATS_JSON:-/run/hive/gpu-stats.json}"
oh_state=$(cat "$OH_RUN_DIR/state" 2>/dev/null)
oh_started=$(cat "$OH_RUN_DIR/started" 2>/dev/null)
oh_loaded=$(curl -fs --max-time 2 "$OH_API/api/ps" 2>/dev/null | jq -r '.models | length' 2>/dev/null)

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

oh_count=$(jq -r 'length' <<< "$oh_temp" 2>/dev/null)
[[ ${oh_count:-0} -gt 0 ]] || oh_count=1
khs=$(awk -v v="$oh_value" -v c="$oh_count" 'BEGIN { printf "%.3f", v * c / 1000 }')

oh_uptime=0
[[ $oh_started =~ ^[0-9]+$ ]] && oh_uptime=$(( $(date +%s) - oh_started ))

stats=$(jq -nc \
    --argjson value "$oh_value" --argjson count "$oh_count" \
    --argjson temp "$oh_temp" --argjson fan "$oh_fan" --argjson bus "$oh_bus" \
    --argjson uptime "$oh_uptime" \
    --arg ver "${CUSTOM_VERSION:-}" --arg algo "ollama ${oh_state:-stopped}" \
    '{hs: [range(0; $count) | $value], hs_units: "hs", temp: $temp, fan: $fan, bus_numbers: $bus,
      uptime: $uptime, ver: $ver, ar: [0, 0], algo: $algo}')
