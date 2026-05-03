#!/usr/bin/env bash
# Compile and run the unified Phase-2A tile testbench (all 4 DUTs).
#
# Run from project root:
#     scripts/run_tile_tb.sh
#
# Regenerates the TB data deterministically; assumes RTL has already been
# generated (rtl/tile_*/*.v exist).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Refresh test vectors and cfg-programming data.
.venv/bin/python scripts/gen_tile_tb_data.py >/dev/null

# Compile.
SIM=/tmp/tb_tile
iverilog -g2012 -o "$SIM" \
    tb/tb_tile.sv \
    rtl/tile_tlg_hc/tile_tlg_hc.v \
    rtl/tile_tlg_ld/tile_tlg_ld.v \
    rtl/tile_handopt_hc/tile_handopt_hc.v \
    rtl/tile_handopt_ld/tile_handopt_ld.v

# vvp prints PASS/FAIL lines via $display.
cd tb
vvp -N "$SIM"
