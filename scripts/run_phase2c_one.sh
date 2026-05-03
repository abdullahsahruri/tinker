#!/usr/bin/env bash
# Phase 2C — full pipeline for one (variant_logic, variant_mode, seed_id):
#   1. Emit a per-DUT power testbench (scripts/emit_power_tb.py).
#   2. Compile + run with iverilog → VCD scoped to the DUT.
#   3. Re-run only the OpenSTA power stage against the existing post-route
#      netlist + parasitics, with the VCD as activity input.
#   4. Drop power.rpt and power.metrics.json under
#      results/phase2c/runs/<dut>/<corner>/.
#
# Usage:
#   scripts/run_phase2c_one.sh <variant_logic> <variant_mode> <seed_id> [corner]
#
# Default corner is max_ff_n40C_1v95 (the corner LibreLane reports as the
# headline `power__total` metric — first alphabetically in OpenROAD's corner
# dict, hence what 2B/2B.5 published).
#
# Environment: source scripts/env.sh first.

set -euo pipefail

usage() {
    echo "Usage: $0 <variant_logic:tlg|handopt> <variant_mode:hc|ld> <seed_id:0|1|2> [corner]"
    exit 2
}

[ "$#" -ge 3 ] || usage
VLOGIC="$1"
VMODE="$2"
SEED="$3"
CORNER="${4:-max_ff_n40C_1v95}"

case "$VLOGIC" in tlg|handopt) ;; *) usage;; esac
case "$VMODE"   in hc|ld)      ;; *) usage;; esac
case "$SEED"    in 0|1|2)      ;; *) usage;; esac

# Optional knob: EXCLUDE_CFG=1 — for ld variants only, defer $dumpvars until
# after the cfg-write phase, so OpenSTA's activity propagation only sees the
# steady-state inference window. Tags output paths with "_cfg_excl" to avoid
# clobbering the cfg-included baseline.
EXCLUDE_CFG="${EXCLUDE_CFG:-0}"
DUMP_TAG=""
EMIT_FLAG=""
if [ "$EXCLUDE_CFG" = "1" ] && [ "$VMODE" = "ld" ]; then
    DUMP_TAG="_cfg_excl"
    EMIT_FLAG="--exclude-cfg"
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ---------- 1. derive paths ----------
DUT_BASE="tile_${VLOGIC}_${VMODE}"
if [ "$VMODE" = "ld" ]; then
    # Loadable RTL is seed-invariant — all 3 seeds share the seed-0 RTL
    # and post-route artifacts; only the runtime weight program differs.
    DUT="${DUT_BASE}"
    RTL_FILE="rtl/${DUT_BASE}/${DUT_BASE}.v"
    FLOW_RUN="flow/phase2_${VLOGIC}_${VMODE}/runs/phase2_${VLOGIC}_${VMODE}"
    # Disambiguate output dirs so seeds 1+ don't clobber seed 0.
    if [ "$SEED" = "0" ]; then
        RUN_KEY="${DUT}"
    else
        RUN_KEY="${DUT}_s${SEED}"
    fi
elif [ "$SEED" = "0" ]; then
    DUT="${DUT_BASE}"
    RTL_FILE="rtl/${DUT_BASE}/${DUT_BASE}.v"
    FLOW_RUN="flow/phase2_${VLOGIC}_${VMODE}/runs/phase2_${VLOGIC}_${VMODE}"
    RUN_KEY="${DUT}"
else
    DUT="${DUT_BASE}_s${SEED}"
    RTL_FILE="rtl/${DUT_BASE}/${DUT_BASE}_s${SEED}.v"
    FLOW_RUN="flow/phase2_${VLOGIC}_${VMODE}/seed${SEED}/runs/phase2_${VLOGIC}_${VMODE}_s${SEED}"
    RUN_KEY="${DUT}"
fi

[ -f "$RTL_FILE" ] || { echo "missing RTL: $RTL_FILE" >&2; exit 3; }
[ -d "${FLOW_RUN}/final" ] || { echo "missing post-route artifacts: ${FLOW_RUN}/final" >&2; exit 3; }

NETLIST="${FLOW_RUN}/final/nl/${DUT}.nl.v"
SDC="flow/common/tile.sdc"

# Map LibreLane corner_name → (lib_subdir, spef_subdir, lib_file).
case "$CORNER" in
    max_ff_n40C_1v95)  LIB_FILE="sky130_fd_sc_hd__ff_n40C_1v95.lib"; SPEF_DIR="max" ;;
    max_ss_100C_1v60)  LIB_FILE="sky130_fd_sc_hd__ss_100C_1v60.lib"; SPEF_DIR="max" ;;
    max_tt_025C_1v80)  LIB_FILE="sky130_fd_sc_hd__tt_025C_1v80.lib"; SPEF_DIR="max" ;;
    nom_ff_n40C_1v95)  LIB_FILE="sky130_fd_sc_hd__ff_n40C_1v95.lib"; SPEF_DIR="nom" ;;
    nom_ss_100C_1v60)  LIB_FILE="sky130_fd_sc_hd__ss_100C_1v60.lib"; SPEF_DIR="nom" ;;
    nom_tt_025C_1v80)  LIB_FILE="sky130_fd_sc_hd__tt_025C_1v80.lib"; SPEF_DIR="nom" ;;
    min_ff_n40C_1v95)  LIB_FILE="sky130_fd_sc_hd__ff_n40C_1v95.lib"; SPEF_DIR="min" ;;
    min_ss_100C_1v60)  LIB_FILE="sky130_fd_sc_hd__ss_100C_1v60.lib"; SPEF_DIR="min" ;;
    min_tt_025C_1v80)  LIB_FILE="sky130_fd_sc_hd__tt_025C_1v80.lib"; SPEF_DIR="min" ;;
    *) echo "unknown corner: $CORNER" >&2; exit 4 ;;
esac

PDK_LIB_DIR="${PDK_ROOT}/volare/sky130/versions/8afc8346a57fe1ab7934ba5a6056ea8b43078e71/sky130A/libs.ref/sky130_fd_sc_hd/lib"
LIB_PATH="${PDK_LIB_DIR}/${LIB_FILE}"
SPEF="${FLOW_RUN}/final/spef/${SPEF_DIR}/${DUT}.${SPEF_DIR}.spef"

[ -f "$LIB_PATH" ] || { echo "missing liberty: $LIB_PATH" >&2; exit 5; }
[ -f "$NETLIST"  ] || { echo "missing netlist: $NETLIST" >&2; exit 5; }
[ -f "$SPEF"     ] || { echo "missing SPEF: $SPEF" >&2; exit 5; }

OUT_DIR="results/phase2c/runs/${RUN_KEY}${DUMP_TAG}/${CORNER}"
SAIF_DIR="results/phase2c/saif/${RUN_KEY}${DUMP_TAG}"
mkdir -p "$OUT_DIR" "$SAIF_DIR"

VCD="${SAIF_DIR}/${DUT}.vcd"
SIM_BIN="${ROOT}/${SAIF_DIR}/sim_bin"

echo ">>> Phase 2C ($VLOGIC, $VMODE, seed_id=$SEED) — DUT=$DUT, corner=$CORNER"

# ---------- 2. emit + compile testbench, run sim, dump VCD ----------
TB_DIR="tb/phase2c/${RUN_KEY}${DUMP_TAG}"
.venv/bin/python scripts/emit_power_tb.py \
    "$VLOGIC" "$VMODE" "$SEED" \
    --inputs "$(pwd)/results/phase2c/inputs" \
    --out    "$(pwd)/${TB_DIR}" \
    $EMIT_FLAG >/dev/null

TB_FILE="${TB_DIR}/tb_power.sv"

echo "    [iverilog] compile $TB_FILE + $RTL_FILE → $SIM_BIN"
iverilog -g2012 -o "$SIM_BIN" "$TB_FILE" "$RTL_FILE"

echo "    [vvp]     run sim, dump $VCD"
( cd "$SAIF_DIR" && vvp -N "$SIM_BIN" >/dev/null )

[ -f "$VCD" ] || { echo "VCD not produced at $VCD" >&2; exit 6; }
VCD_SIZE=$(du -h "$VCD" | awk '{print $1}')
echo "    [vcd]     ${VCD_SIZE}"

# ---------- 3. run OpenSTA in librelane docker container ----------
TCL_SCRIPT="scripts/sta_power_one_corner.tcl"

# Container paths (project root mounted at /work). Host paths under $ROOT
# get the prefix stripped; relative paths simply get /work/ prepended.
to_ctr() {
    local p="$1"
    case "$p" in
        "${ROOT}"/*) echo "/work/${p#${ROOT}/}" ;;
        /*)          echo "$p" ;;   # absolute outside $ROOT — pass through (won't exist in container, will error)
        *)           echo "/work/${p}" ;;
    esac
}
CTR_LIB="$(to_ctr "$LIB_PATH")"
CTR_NETLIST="$(to_ctr "$NETLIST")"
CTR_SDC="$(to_ctr "$SDC")"
CTR_SPEF="$(to_ctr "$SPEF")"
CTR_VCD="$(to_ctr "$VCD")"
CTR_TCL="$(to_ctr "$TCL_SCRIPT")"
CTR_REPORT="$(to_ctr "$OUT_DIR")"

echo "    [opensta]  run $TCL_SCRIPT inside ${LIBRELANE_IMAGE_OVERRIDE}"
# SDC env knobs match the values resolved at synthesis (sky130_fd_sc_hd
# defaults pinned in the existing STAPostPNR step's config.json).
docker run --rm \
    -v "${ROOT}:/work" \
    -e STA_LIB="$CTR_LIB" \
    -e STA_NETLIST="$CTR_NETLIST" \
    -e STA_TOP="$DUT" \
    -e STA_SDC="$CTR_SDC" \
    -e STA_SPEF="$CTR_SPEF" \
    -e STA_VCD="$CTR_VCD" \
    -e STA_VCD_SCOPE="tb_power/dut" \
    -e STA_CORNER_NAME="$CORNER" \
    -e STA_REPORT_DIR="$CTR_REPORT" \
    -e CLOCK_PERIOD=10 \
    -e MAX_FANOUT_CONSTRAINT=10 \
    -e MAX_TRANSITION_CONSTRAINT=0.75 \
    -e SYNTH_DRIVING_CELL="sky130_fd_sc_hd__inv_2/Y" \
    -e OUTPUT_CAP_LOAD=33.442 \
    "${LIBRELANE_IMAGE_OVERRIDE}" \
    sta -no_splash -exit "$CTR_TCL"

if [ ! -f "${OUT_DIR}/power.metrics.json" ]; then
    echo "ERROR: OpenSTA did not produce ${OUT_DIR}/power.metrics.json" >&2
    exit 7
fi

# ---------- 4. summarize ----------
.venv/bin/python - <<EOF
import json
with open("${OUT_DIR}/power.metrics.json") as f:
    m = json.load(f)
total_uw = float(m["power__total"]) * 1e6
print(f"    [result]  power__total = {total_uw:.1f} uW (corner={m['corner']})")
EOF

echo ">>> Phase 2C ($DUT, $CORNER) DONE → $OUT_DIR/"
