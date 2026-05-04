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

iverilog -g2012 -Wall \
    -o "$OUT" \
    rtl/soc/soc_top.v \
    rtl/soc/picorv32_wrapper.v \
    rtl/soc/wb_interconnect.v \
    rtl/soc/wb_imem.v \
    rtl/soc/wb_dmem.v \
    rtl/soc/wb_tile_wrapper.v \
    rtl/soc/wb_gpio.v \
    rtl/tile_tlg_ld/tile_tlg_ld.v

echo "OK: SoC skeleton elaborates cleanly. Output binary: $OUT"
