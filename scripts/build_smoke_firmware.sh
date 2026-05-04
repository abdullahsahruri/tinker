#!/usr/bin/env bash
# build_smoke_firmware.sh — build the Phase-3C SoC smoke firmware.
#
# Wraps `make` in firmware/smoke/ so callers don't have to remember the path.
# Emits firmware/smoke/firmware.hex which the testbench loads via $readmemh.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v riscv64-unknown-elf-gcc >/dev/null 2>&1; then
    echo "error: riscv64-unknown-elf-gcc not on PATH; run 'source scripts/env.sh'" >&2
    exit 1
fi

make -C firmware/smoke clean >/dev/null
make -C firmware/smoke all

echo
echo "OK: firmware/smoke/firmware.hex built ($(wc -l < firmware/smoke/firmware.hex) words)."
