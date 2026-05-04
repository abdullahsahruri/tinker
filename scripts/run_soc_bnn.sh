#!/usr/bin/env bash
# =============================================================================
# run_soc_bnn.sh — end-to-end Phase-4.5 BNN inference orchestrator.
#
# Network: 14×14 grouped BNN — 4 branches × (49→16) → concat(64) → 10.
#
# Steps:
#   1. (Re)train the BNN if data/bnn_weights_14x14.npz is missing/stale.
#   2. Generate firmware/inference/weights_14x14.h.
#   3. Generate test set + PyTorch ↔ Python-golden agreement check.
#   4. Build firmware/inference/firmware.hex.
#   5. Compile RTL + tb_soc_bnn with iverilog and run vvp.
#   6. Report PASS/FAIL.
#
# Usage:
#   scripts/run_soc_bnn.sh                  # full pipeline
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
   { [ ! -f data/bnn_weights_14x14.npz ] || \
     [ scripts/train_bnn.py -nt data/bnn_weights_14x14.npz ]; }; then
    echo "==> [1/5] Training 14x14 grouped BNN"
    python3 scripts/train_bnn.py --net 14x14
else
    echo "==> [1/5] Reusing data/bnn_weights_14x14.npz"
fi

# ---- 2. Generate weights_14x14.h ---------------------------------------------
echo
echo "==> [2/5] Generating firmware/inference/weights_14x14.h"
python3 scripts/weights_to_c.py --net 14x14

# ---- 3. Generate test set + golden ↔ PyTorch check --------------------------
echo
echo "==> [3/5] Generating test set + checking golden ↔ PyTorch agreement"
python3 scripts/gen_bnn_testdata.py --net 14x14 --n "$N_IMAGES"

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
