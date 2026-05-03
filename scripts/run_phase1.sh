#!/usr/bin/env bash
# Run all 15 LibreLane flows for Phase 1 (3 variants × 5 seeds).
#
# Each per-seed config is derived on the fly from the variant's template
# config.json by sed-substituting the seed in DESIGN_NAME and VERILOG_FILES.
# Logs go to results/phase1/logs/<variant>_s<seed>/.
#
# Run from the project root with the venv-activated environment:
#     source scripts/env.sh
#     scripts/run_phase1.sh [variant] [seed]   # both optional, default = all
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VARIANTS=(naive handopt tlg)
SEEDS=(0 1 2 3 4)

# Allow targeted runs.
if [[ $# -ge 1 ]]; then VARIANTS=("$1"); fi
if [[ $# -ge 2 ]]; then SEEDS=("$2"); fi

mkdir -p results/phase1/logs

for variant in "${VARIANTS[@]}"; do
    for seed in "${SEEDS[@]}"; do
        rtl_file="rtl/${variant}/neuron_${variant}_s${seed}.v"
        if [[ ! -f "$rtl_file" ]]; then
            echo "[gen] $rtl_file missing — generating"
            .venv/bin/python scripts/gen_neuron.py "$variant" --seed "$seed" \
                --out "rtl/${variant}/"
        fi

        cfg_dir="flow/phase1_${variant}/seed${seed}"
        cfg="${cfg_dir}/config.json"
        mkdir -p "$cfg_dir"

        # Materialize the per-seed config from the variant template.
        # The template carries seed=0 hardcoded; we sed it for the actual seed.
        sed -e "s|neuron_${variant}_s0|neuron_${variant}_s${seed}|g" \
            -e "s|rtl/${variant}/neuron_${variant}_s0\\.v|rtl/${variant}/neuron_${variant}_s${seed}.v|g" \
            -e "s|dir::\\.\\./\\.\\./rtl|dir::../../../rtl|g" \
            -e "s|dir::\\.\\./common|dir::../../common|g" \
            "flow/phase1_${variant}/config.json" > "$cfg"

        log_dir="results/phase1/logs/${variant}_s${seed}"
        mkdir -p "$log_dir"
        log_file="${log_dir}/librelane.log"
        echo "=========================================================="
        echo "[run] variant=${variant} seed=${seed}"
        echo "       config: ${cfg}"
        echo "       log:    ${log_file}"
        echo "=========================================================="
        if .venv/bin/librelane \
            --docker-no-tty --dockerized \
            --pdk-root "$ROOT/pdk" --pdk sky130A --scl sky130_fd_sc_hd \
            --run-tag "phase1_${variant}_s${seed}" \
            "$cfg" 2>&1 | tee "$log_file"
        then
            echo "[ok] ${variant}/s${seed}"
        else
            echo "[FAIL] ${variant}/s${seed} — see ${log_file}"
            # Continue with remaining runs; collection script handles missing data.
        fi
    done
done
echo "All requested runs complete."
