#!/usr/bin/env bash
# Phase 3E — full SoC LibreLane P&R run.
#
# Pushes the Phase-3 SoC (PicoRV32 + WB interconnect + 8 KB IMEM +
# 4 KB DMEM + tile wrapper + GPIO) through Yosys synth + OpenROAD
# floorplan/place/route/sign-off, using Phase-2-equivalent knobs
# (CLOCK_PERIOD=10 ns, SYNTH_STRATEGY="AREA 0", FP_CORE_UTIL=35,
# PL_TARGET_DENSITY_PCT=55) so the SoC numbers are directly
# comparable to the Phase-2 tile numbers.
#
# Run-tag is `phase3_soc`, so artifacts land at
# flow/phase3_soc/runs/phase3_soc/. Log goes to
# results/phase3/logs/soc_pnr.log.
#
# Run from the project root with the venv-activated environment:
#     source scripts/env.sh
#     scripts/run_soc_pnr.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CFG="flow/phase3_soc/config.json"
RUN_TAG="phase3_soc"
LOG_DIR="results/phase3/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/soc_pnr.log"

start_ts=$(date +%s)
echo "=========================================================="
echo "[run] Phase 3E SoC P&R"
echo "       config:   ${CFG}"
echo "       run-tag:  ${RUN_TAG}"
echo "       log:      ${LOG_FILE}"
echo "       start:    $(date -u +%FT%TZ)"
echo "=========================================================="

if .venv/bin/librelane \
    --docker-no-tty --dockerized \
    --pdk-root "$ROOT/pdk" --pdk sky130A --scl sky130_fd_sc_hd \
    --run-tag "$RUN_TAG" \
    "$CFG" 2>&1 | tee "$LOG_FILE"
then
    end_ts=$(date +%s)
    echo "[ok] SoC P&R — wall-clock $((end_ts - start_ts)) s"
else
    end_ts=$(date +%s)
    echo "[FAIL] SoC P&R — see ${LOG_FILE} (wall-clock $((end_ts - start_ts)) s)" >&2
    exit 1
fi
