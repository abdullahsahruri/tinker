#!/usr/bin/env bash
# Session 2B.5 — multi-seed PPA sweep for the two hardcoded tile variants.
#
# Loadable variants are seed-invariant by construction (the .v file does
# not reference any specific weight value — see the docstrings in
# scripts/gen_tile.py:emit_tile_*_ld), so we only re-synthesize the
# hardcoded variants for new seeds. The seed-0 (= numpy seed 42) hardcoded
# runs from Session 2B are reused as the seed-0 row of the multi-seed
# table; this script generates only the seed-1 and seed-2 hardcoded runs.
#
# Sequential, not parallel — same memory-pressure rationale as 2B.
#
# Logs: results/phase2/logs/<variant>_hc/seed<N>/librelane.log
# Run-tag: phase2_<variant>_hc_s<N>
# Run dir: flow/phase2_<variant>_hc/seed<N>/runs/phase2_<variant>_hc_s<N>/
#
# Run from the project root with the venv-activated environment:
#     source scripts/env.sh
#     scripts/run_phase2b5.sh                       # all 4 new runs
#     scripts/run_phase2b5.sh tlg_hc                # both seeds, one variant
#     scripts/run_phase2b5.sh tlg_hc 1              # one variant, one seed
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VARIANTS=(tlg_hc handopt_hc)
SEEDS=(1 2)

if [[ $# -ge 1 ]]; then VARIANTS=("$1"); fi
if [[ $# -ge 2 ]]; then SEEDS=("$2"); fi

mkdir -p results/phase2/logs

for variant in "${VARIANTS[@]}"; do
    for seed in "${SEEDS[@]}"; do
        cfg="flow/phase2_${variant}/seed${seed}/config.json"
        rtl="rtl/tile_${variant}/tile_${variant}_s${seed}.v"
        if [[ ! -f "$rtl" ]]; then
            echo "[gen] $rtl missing — generating"
            logic_part="${variant%_*}"   # tlg_hc → tlg, handopt_hc → handopt
            .venv/bin/python scripts/gen_tile.py "$logic_part" --hardcoded \
                --seed "$seed" --out "rtl/tile_${variant}/"
        fi
        if [[ ! -f "$cfg" ]]; then
            echo "[skip] $cfg not found"
            continue
        fi

        log_dir="results/phase2/logs/${variant}/seed${seed}"
        mkdir -p "$log_dir"
        log_file="${log_dir}/librelane.log"
        start_ts=$(date +%s)
        echo "=========================================================="
        echo "[run] variant=${variant} seed=${seed}"
        echo "       config: ${cfg}"
        echo "       log:    ${log_file}"
        echo "       start:  $(date -u +%FT%TZ)"
        echo "=========================================================="
        if .venv/bin/librelane \
            --docker-no-tty --dockerized \
            --pdk-root "$ROOT/pdk" --pdk sky130A --scl sky130_fd_sc_hd \
            --run-tag "phase2_${variant}_s${seed}" \
            "$cfg" 2>&1 | tee "$log_file"
        then
            end_ts=$(date +%s)
            echo "[ok] ${variant}/s${seed} — wall-clock $((end_ts - start_ts)) s"
        else
            end_ts=$(date +%s)
            echo "[FAIL] ${variant}/s${seed} — see ${log_file} (wall-clock $((end_ts - start_ts)) s)"
        fi
    done
done
echo "All requested phase2b5 runs complete."
