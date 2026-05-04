#!/usr/bin/env bash
# run_soc_smoke.sh — build the smoke firmware, compile soc_top + tb_soc_smoke,
# run iverilog, and report PASS/FAIL.
#
# Phase-3C functional gate. Pass criterion: gpio_o reaches 0x BE *and*
# u_gpio.sim_end_q reaches 0xCAFE_BABE within 100K simulation cycles.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] Building smoke firmware"
bash scripts/build_smoke_firmware.sh

OUT=/tmp/tb_soc_smoke
LOG=/tmp/tb_soc_smoke.log
rm -f "$OUT" "$LOG"

echo
echo "==> [2/3] Compiling RTL + testbench with iverilog"
iverilog -g2012 -Wall \
    -o "$OUT" \
    -s tb_soc_smoke \
    rtl/soc/soc_top.v \
    rtl/soc/picorv32_wrapper.v \
    rtl/soc/wb_interconnect.v \
    rtl/soc/wb_imem.v \
    rtl/soc/wb_dmem.v \
    rtl/soc/wb_tile_wrapper.v \
    rtl/soc/wb_gpio.v \
    rtl/tile_tlg_ld/tile_tlg_ld.v \
    vendor/picorv32/picorv32.v \
    tb/tb_soc_smoke.sv

echo
echo "==> [3/3] Running simulation"
set +e
vvp "$OUT" | tee "$LOG"
RC=${PIPESTATUS[0]}
set -e

echo
if grep -q "SOC SMOKE TEST: PASS" "$LOG"; then
    echo "RESULT: PASS"
    exit 0
fi

echo "RESULT: FAIL"
exit ${RC:-1}
