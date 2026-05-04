#!/usr/bin/env bash
# Phase 3E — activity-aware power on the post-P&R SoC for one corner.
#
# Adapted from scripts/run_phase2c_one.sh. Differences:
#   - Top-level instance is `soc_top` (not a tile variant).
#   - VCD comes from the Phase-3D inference TB (`tb_soc_bnn`) with the
#     +vcd plus-arg enabled — caller is responsible for having generated
#     /tmp/tb_soc_bnn.vcd.
#   - SDC is `flow/common/soc.sdc`.
#   - Hierarchical decomposition: scripts/bucket_soc_cells.py is run
#     first to build per-bucket cell lists, then sta_soc_power_one_corner.tcl
#     iterates them inside OpenSTA via sta::instance_power.
#
# Usage:
#   scripts/run_soc_power.sh [corner]
#
# Default corner is max_ff_n40C_1v95 (matching Phase 2C's headline corner).
#
# Environment: source scripts/env.sh first.

set -euo pipefail

CORNER="${1:-max_ff_n40C_1v95}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DUT="soc_top"
RUN_DIR="flow/phase3_soc/runs/phase3_soc"
NETLIST="${RUN_DIR}/final/nl/${DUT}.nl.v"
SDC="flow/common/soc.sdc"
VCD_RAW="/tmp/tb_soc_bnn.vcd"
VCD="/tmp/tb_soc_bnn.flat.vcd"
VCD_SCOPE="tb_soc_bnn/dut"

[ -f "$NETLIST" ] || { echo "missing post-P&R netlist: $NETLIST" >&2; exit 3; }
[ -f "$SDC"     ] || { echo "missing SDC: $SDC" >&2; exit 3; }
[ -f "$VCD_RAW" ] || { echo "missing VCD: $VCD_RAW — re-run vvp /tmp/tb_soc_bnn +vcd first" >&2; exit 3; }

# Flatten the VCD hierarchy so OpenSTA can match interior signals against
# the post-flatten netlist's escaped-identifier wires (e.g., \u_cpu.clk).
# Without this step, only the 18 chip-pin boundary signals get annotated
# and combinational power collapses to ~0. See
# scripts/flatten_vcd_hierarchy.py for rationale.
if [ "$VCD_RAW" -nt "$VCD" ] || [ ! -f "$VCD" ]; then
    echo "    [vcd]     flattening hierarchy → $VCD"
    python3 scripts/flatten_vcd_hierarchy.py "$VCD_RAW" "$VCD" --src-scope tb_soc_bnn.dut
fi

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
SPEF="${RUN_DIR}/final/spef/${SPEF_DIR}/${DUT}.${SPEF_DIR}.spef"

# Session 3.5 (OpenRAM) — point STA at the macro Liberties too so
# sta::instance_power on u_*mem.u_macro returns the macro's
# Liberty-characterized power instead of 0.
SRAM_LIB_DIR="${PDK_ROOT}/ciel/sky130/versions/8afc8346a57fe1ab7934ba5a6056ea8b43078e71/sky130A/libs.ref/sky130_sram_macros/lib"
SRAM_LIB_IMEM="${SRAM_LIB_DIR}/sky130_sram_2kbyte_1rw1r_32x512_8_TT_1p8V_25C.lib"
SRAM_LIB_DMEM="${SRAM_LIB_DIR}/sky130_sram_1kbyte_1rw1r_32x256_8_TT_1p8V_25C.lib"

[ -f "$LIB_PATH" ] || { echo "missing liberty: $LIB_PATH" >&2; exit 5; }
[ -f "$SPEF"     ] || { echo "missing SPEF: $SPEF" >&2; exit 5; }

OUT_DIR="results/phase3/power/${CORNER}"
BUCKET_DIR="results/phase3/power/buckets"
mkdir -p "$OUT_DIR" "$BUCKET_DIR"

echo ">>> Phase 3E SoC activity-aware power — corner=$CORNER"

# ---- (re)build per-bucket cell lists ----------------------------------
echo "    [bucket]  python3 scripts/bucket_soc_cells.py"
python3 scripts/bucket_soc_cells.py >/dev/null

# ---- container path translation ---------------------------------------
# /work mount inside the librelane container points at the project root.
to_ctr() {
    local p="$1"
    case "$p" in
        "${ROOT}"/*) echo "/work/${p#${ROOT}/}" ;;
        /tmp/*)      echo "$p" ;;
        /*)          echo "$p" ;;
        *)           echo "/work/${p}" ;;
    esac
}

CTR_LIB="$(to_ctr "$LIB_PATH")"
CTR_SRAM_IMEM="$(to_ctr "$SRAM_LIB_IMEM")"
CTR_SRAM_DMEM="$(to_ctr "$SRAM_LIB_DMEM")"
CTR_EXTRA_LIBS="${CTR_SRAM_IMEM}:${CTR_SRAM_DMEM}"
CTR_NETLIST="$(to_ctr "$NETLIST")"
CTR_SDC="$(to_ctr "$SDC")"
CTR_SPEF="$(to_ctr "$SPEF")"
CTR_VCD="$(to_ctr "$VCD")"
CTR_TCL="$(to_ctr "scripts/sta_soc_power_one_corner.tcl")"
CTR_REPORT="$(to_ctr "$OUT_DIR")"
CTR_BUCKETS="$(to_ctr "$BUCKET_DIR")"

echo "    [opensta] running inside ${LIBRELANE_IMAGE_OVERRIDE}"

# Mount /tmp too so the VCD is visible in the container.
docker run --rm \
    -v "${ROOT}:/work" \
    -v "/tmp:/tmp" \
    -e STA_LIB="$CTR_LIB" \
    -e STA_EXTRA_LIBS="$CTR_EXTRA_LIBS" \
    -e STA_NETLIST="$CTR_NETLIST" \
    -e STA_TOP="$DUT" \
    -e STA_SDC="$CTR_SDC" \
    -e STA_SPEF="$CTR_SPEF" \
    -e STA_VCD="$CTR_VCD" \
    -e STA_VCD_SCOPE="$VCD_SCOPE" \
    -e STA_CORNER_NAME="$CORNER" \
    -e STA_REPORT_DIR="$CTR_REPORT" \
    -e STA_BUCKET_DIR="$CTR_BUCKETS" \
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

.venv/bin/python - <<EOF
import json
with open("${OUT_DIR}/power.metrics.json") as f:
    m = json.load(f)
total_mw = float(m["power__total"]) * 1e3
print(f"    [result]  power__total = {total_mw:.2f} mW (corner={m['corner']})")
print(f"    [result]  per-bucket (mW):")
for b, p in m["buckets"].items():
    print(f"                {b:11s} {float(p['total'])*1e3:7.2f}  ({p['cells_found']} cells)")
EOF

echo ">>> Phase 3E SoC power ($CORNER) DONE → ${OUT_DIR}/"
