#!/usr/bin/env bash
# Run all four LibreLane flows for Phase 2 Session B (tile-level PPA).
#
# Variants are sequenced rather than run in parallel — with 13 GiB of
# WSL RAM, OpenROAD's detailed routing on the heavier variants needs
# the whole machine's headroom.
#
# Logs go to results/phase2/logs/<variant>/librelane.log. Each run
# uses run-tag phase2_<variant> so the run dir is deterministic at
# flow/phase2_<variant>/runs/phase2_<variant>/.
#
# Run from the project root with the venv-activated environment:
#     source scripts/env.sh
#     scripts/run_phase2.sh [variant]   # variant optional, default = all
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Order: pilot first (tlg_hc, the heaviest), then the rest in increasing
# expected complexity-per-design.
VARIANTS=(tlg_hc tlg_ld handopt_hc handopt_ld)

if [[ $# -ge 1 ]]; then VARIANTS=("$1"); fi

mkdir -p results/phase2/logs

for variant in "${VARIANTS[@]}"; do
    cfg="flow/phase2_${variant}/config.json"
    if [[ ! -f "$cfg" ]]; then
        echo "[skip] $cfg not found"
        continue
    fi

    log_dir="results/phase2/logs/${variant}"
    mkdir -p "$log_dir"
    log_file="${log_dir}/librelane.log"
    start_ts=$(date +%s)
    echo "=========================================================="
    echo "[run] variant=${variant}"
    echo "       config: ${cfg}"
    echo "       log:    ${log_file}"
    echo "       start:  $(date -u +%FT%TZ)"
    echo "=========================================================="
    if .venv/bin/librelane \
        --docker-no-tty --dockerized \
        --pdk-root "$ROOT/pdk" --pdk sky130A --scl sky130_fd_sc_hd \
        --run-tag "phase2_${variant}" \
        "$cfg" 2>&1 | tee "$log_file"
    then
        end_ts=$(date +%s)
        echo "[ok] ${variant} — wall-clock $((end_ts - start_ts)) s"
    else
        end_ts=$(date +%s)
        echo "[FAIL] ${variant} — see ${log_file} (wall-clock $((end_ts - start_ts)) s)"
        # Continue with remaining runs; collection script handles missing data.
    fi
done
echo "All requested phase2 runs complete."
