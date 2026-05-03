#!/usr/bin/env bash
# Phase 2C — drive activity-aware power for all 12 (variant, seed) pairs.
#
# Sequential, no parallelism. Same methodology across every run:
#   - corner: max_ff_n40C_1v95 (the corner LibreLane reports as the headline
#     `power__total` metric — first alphabetically in OpenROAD's corner dict)
#   - VCD dump window: full simulation, cfg-write phase included
#     (locked-in methodology — diagnostic confirmed cfg phase contributes
#     <0.5% to the activity power for handopt_ld s0)
#   - input cadence: 1 cycle x_valid + 2 cycles idle (3 cycles/vector × 1024
#     vectors = 3072 active cycles per run)
#   - VCD scope: tb_power/dut
#   - input vectors: shared per seed_id across all variants
#     (results/phase2c/inputs/seed<N>/xs.hex)
#
# Skips combinations that already have a power.metrics.json (idempotent —
# safe to re-run after a partial failure).
#
# Usage: scripts/run_phase2c_all.sh [corner]

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Be permissive with PDK_ROOT etc. when sourced.
set +u
source scripts/env.sh
set -u

CORNER="${1:-max_ff_n40C_1v95}"

JOBS=(
    "tlg     hc 0"
    "tlg     hc 1"
    "tlg     hc 2"
    "handopt hc 0"
    "handopt hc 1"
    "handopt hc 2"
    "tlg     ld 0"
    "tlg     ld 1"
    "tlg     ld 2"
    "handopt ld 0"
    "handopt ld 1"
    "handopt ld 2"
)

LOG_DIR="results/phase2c/logs"
mkdir -p "$LOG_DIR"
ALL_LOG="${LOG_DIR}/run_all_$(date +%Y%m%d_%H%M%S).log"
SUMMARY_TSV="${LOG_DIR}/run_all_progress.tsv"
: > "$SUMMARY_TSV"

# Match the per-run output convention from run_phase2c_one.sh.
result_path() {
    local vlogic="$1" vmode="$2" seed="$3"
    local key="tile_${vlogic}_${vmode}"
    if [ "$seed" != "0" ]; then
        if [ "$vmode" = "ld" ]; then
            key="${key}_s${seed}"
        else
            key="${key}_s${seed}"
        fi
    fi
    echo "results/phase2c/runs/${key}/${CORNER}/power.metrics.json"
}

start_ts=$(date +%s)
total=${#JOBS[@]}
done_n=0
echo "[$(date +%T)] Phase 2C all-runs sweep start (${total} jobs, corner=${CORNER})" | tee -a "$ALL_LOG"

for j in "${JOBS[@]}"; do
    read -r VL VM SD <<<"$j"
    rp="$(result_path "$VL" "$VM" "$SD")"
    label=$(printf "%-7s %s s%s" "$VL" "$VM" "$SD")

    if [ -s "$rp" ]; then
        # Already done — read the number, log, continue.
        total_uw=$(.venv/bin/python -c "import json,sys; m=json.load(open('$rp')); print(f'{float(m[\"power__total\"])*1e6:.1f}')")
        echo "[$(date +%T)] SKIP  ${label}  cached: ${total_uw} uW  ($rp)" | tee -a "$ALL_LOG"
        printf "%s\t%s\t%s\t%s\tCACHED\n" "$VL" "$VM" "$SD" "$total_uw" >>"$SUMMARY_TSV"
        done_n=$((done_n+1))
        continue
    fi

    echo "[$(date +%T)] RUN   ${label}  (${done_n}/${total} done)" | tee -a "$ALL_LOG"
    run_start=$(date +%s)
    if bash scripts/run_phase2c_one.sh "$VL" "$VM" "$SD" "$CORNER" >>"$ALL_LOG" 2>&1; then
        run_dur=$(( $(date +%s) - run_start ))
        if [ -s "$rp" ]; then
            total_uw=$(.venv/bin/python -c "import json,sys; m=json.load(open('$rp')); print(f'{float(m[\"power__total\"])*1e6:.1f}')")
            echo "[$(date +%T)] OK    ${label}  ${total_uw} uW  (${run_dur}s)" | tee -a "$ALL_LOG"
            printf "%s\t%s\t%s\t%s\tOK_%ss\n" "$VL" "$VM" "$SD" "$total_uw" "$run_dur" >>"$SUMMARY_TSV"
            done_n=$((done_n+1))
        else
            echo "[$(date +%T)] ERR   ${label}  no metrics produced" | tee -a "$ALL_LOG"
            printf "%s\t%s\t%s\tNA\tNO_METRICS\n" "$VL" "$VM" "$SD" >>"$SUMMARY_TSV"
            exit 11
        fi
    else
        echo "[$(date +%T)] FAIL  ${label}  exit code $?" | tee -a "$ALL_LOG"
        printf "%s\t%s\t%s\tNA\tFAIL\n" "$VL" "$VM" "$SD" >>"$SUMMARY_TSV"
        exit 12
    fi
done

total_dur=$(( $(date +%s) - start_ts ))
echo "[$(date +%T)] ALL_DONE  ${done_n}/${total}  total=${total_dur}s" | tee -a "$ALL_LOG"
echo "log: $ALL_LOG"
echo "progress: $SUMMARY_TSV"
