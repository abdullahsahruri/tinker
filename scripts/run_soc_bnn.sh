#!/usr/bin/env bash
# =============================================================================
# run_soc_bnn.sh — end-to-end Phase-3D BNN inference orchestrator.
#
# Steps:
#   1. (Re)train the BNN if data/bnn_weights.npz is missing or older than
#      scripts/train_bnn.py. (~20 min on CPU.)
#   2. Generate firmware/inference/weights.h from data/bnn_weights.npz.
#   3. Generate the 16-image preprocessed test set (data/bnn_test_set.npz)
#      and the testbench inputs (tb/tb_bnn_xs.hex, tb/tb_bnn_expected.hex),
#      and run the PyTorch ↔ Python-golden agreement check.
#   4. Build firmware/inference/firmware.hex.
#   5. Compile soc_top + tb_soc_bnn with iverilog and run vvp.
#   6. Report PASS/FAIL with the (matches/16) count.
#
# Usage:
#   scripts/run_soc_bnn.sh                  # full pipeline (default 16 images)
#   scripts/run_soc_bnn.sh --skip-train     # reuse existing weights
#   scripts/run_soc_bnn.sh --n 1            # 1-image checkpoint mode
# =============================================================================
set -euo pipefail

cd "$(dirname "$0")/.."

SKIP_TRAIN=0
N_IMAGES=16
for arg in "$@"; do
    case "$arg" in
        --skip-train) SKIP_TRAIN=1 ;;
        --n=*)        N_IMAGES="${arg#--n=}" ;;
        --n)          shift; N_IMAGES="$1" ;;
        *) echo "unknown arg: $arg" >&2; exit 2 ;;
    esac
done

OUT=/tmp/tb_soc_bnn
LOG=/tmp/tb_soc_bnn.log
rm -f "$OUT" "$LOG"

# ---- 1. Train (or reuse) -----------------------------------------------------
if [ "$SKIP_TRAIN" = "0" ] && \
   { [ ! -f data/bnn_weights.npz ] || \
     [ scripts/train_bnn.py -nt data/bnn_weights.npz ]; }; then
    echo "==> [1/5] Training BNN (data/bnn_weights.npz missing or stale)"
    python3 scripts/train_bnn.py
else
    echo "==> [1/5] Reusing data/bnn_weights.npz"
fi

# ---- 2. Generate weights.h ---------------------------------------------------
echo
echo "==> [2/5] Generating firmware/inference/weights.h"
python3 scripts/weights_to_c.py

# ---- 3. Generate test set + golden ↔ PyTorch check --------------------------
echo
echo "==> [3/5] Generating test set + checking golden ↔ PyTorch agreement"
python3 scripts/gen_bnn_testdata.py --n "$N_IMAGES"

# ---- 4. Build firmware ------------------------------------------------------
echo
echo "==> [4/5] Building firmware/inference/firmware.hex"
make -C firmware/inference clean >/dev/null
make -C firmware/inference all

# ---- 5. Compile + run iverilog ----------------------------------------------
echo
echo "==> [5/5] Compiling RTL + tb_soc_bnn with iverilog"
# Session 3.5 (OpenRAM): macro Verilog models from the PDK.
SRAM_DIR="${PDK_ROOT}/ciel/sky130/versions/8afc8346a57fe1ab7934ba5a6056ea8b43078e71/sky130A/libs.ref/sky130_sram_macros/verilog"

iverilog -g2012 -Wall \
    -o "$OUT" \
    -s tb_soc_bnn \
    -DIMEM_INIT_HEX=\"firmware/inference/firmware.hex\" \
    rtl/soc/soc_top.v \
    rtl/soc/picorv32_wrapper.v \
    rtl/soc/wb_interconnect.v \
    rtl/soc/wb_imem.v \
    rtl/soc/wb_dmem.v \
    rtl/soc/wb_tile_wrapper.v \
    rtl/soc/wb_gpio.v \
    rtl/tile_tlg_ld/tile_tlg_ld.v \
    vendor/picorv32/picorv32.v \
    "${SRAM_DIR}/sky130_sram_2kbyte_1rw1r_32x512_8.v" \
    "${SRAM_DIR}/sky130_sram_1kbyte_1rw1r_32x256_8.v" \
    tb/tb_soc_bnn.sv

echo
echo "==> Running simulation"
set +e
vvp "$OUT" | tee "$LOG"
RC=${PIPESTATUS[0]}
set -e

echo
if grep -q "BNN INFERENCE TEST: PASS" "$LOG"; then
    echo "RESULT: PASS"
    exit 0
fi

echo "RESULT: FAIL"
exit "${RC:-1}"
