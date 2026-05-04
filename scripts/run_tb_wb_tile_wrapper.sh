#!/usr/bin/env bash
# run_tb_wb_tile_wrapper.sh — compile and run the Phase-3B wb_tile_wrapper TB.
#
# Generates the Python golden vectors, builds the TB with iverilog, runs vvp,
# and reports PASS/FAIL based on the final summary line.
#
# Usage (from project root or anywhere — script cd's to project root itself):
#     scripts/run_tb_wb_tile_wrapper.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# 1. Refresh golden hex files (idempotent).
"${ROOT}/.venv/bin/python" scripts/wb_tile_reference.py >/dev/null

# 2. Compile.
SIM=/tmp/tb_wb_tile_wrapper
LOG=/tmp/tb_wb_tile_wrapper.log
rm -f "$SIM" "$LOG"

iverilog -g2012 -Wall \
    -o "$SIM" \
    tb/tb_wb_tile_wrapper.sv \
    rtl/soc/wb_tile_wrapper.v \
    rtl/tile_tlg_ld/tile_tlg_ld.v

# 3. Run from tb/ so $readmemh resolves relative paths.
( cd tb && vvp -N "$SIM" ) | tee "$LOG"

# 4. Decide PASS/FAIL.
if grep -q "TILE WRAPPER FUNCTIONAL CHECK: PASS (10/10)" "$LOG"; then
    echo "wrapper TB: PASS — log at $LOG"
    exit 0
else
    echo "wrapper TB: FAIL — log at $LOG"
    exit 1
fi
