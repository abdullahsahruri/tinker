#!/usr/bin/env bash
# check_soc_elab.sh — elaborate the Phase 3A SoC skeleton with iverilog.
#
# Returns 0 if the skeleton elaborates cleanly. Used by Session 3A as the
# port-list-consistency gate; sessions 3B onward keep it green as bodies
# get filled in.
set -euo pipefail

cd "$(dirname "$0")/.."

OUT=/tmp/soc_elab_check
rm -f "$OUT"

# Session 3.5 (OpenRAM): wb_imem and wb_dmem now wrap sky130_sram_*
# macros. The Verilog behavioral models live in the PDK and must be
# on the command line for elaboration. Assumes scripts/env.sh has set
# PDK_ROOT.
SRAM_DIR="${PDK_ROOT}/ciel/sky130/versions/8afc8346a57fe1ab7934ba5a6056ea8b43078e71/sky130A/libs.ref/sky130_sram_macros/verilog"

iverilog -g2012 -Wall \
    -o "$OUT" \
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
    "${SRAM_DIR}/sky130_sram_1kbyte_1rw1r_32x256_8.v"

echo "OK: SoC skeleton elaborates cleanly. Output binary: $OUT"
