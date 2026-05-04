#!/usr/bin/env python3
"""Golden BNN model for tb_wb_tile_wrapper.sv.

Emits four hex files into ``tb/`` (or ``--out``):

  tb_wb_ws.hex   — 16 lines × 16 hex digits, seed-0 weights (= numpy seed 42)
  tb_wb_ts.hex   — 16 lines × 2 hex digits,  thresholds (all 32 in seed 0)
  tb_wb_xs.hex   — N=100 lines × 16 hex digits, random 64-b input vectors
  tb_wb_ys.hex   — N=100 lines × 4 hex digits,  expected y_out per vector

The math is identical to scripts/tile_reference.py — y[i] = (popcount(x XNOR
W[i]) >= t[i]) — and reuses the same tlg_lib helpers used by Phase 1/2 TBs.
The TB seed is held in a separate namespace (``TB_SEED``) so adding more
input vectors here does not perturb the Phase-2 weight or input seeds.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tile_reference import N_NEURONS, tile_weights, tile_y  # noqa: E402

import numpy as np  # noqa: E402

N_VECTORS = 100
TB_SEED = 0xC0FFEE


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("tb"))
    p.add_argument("--n", type=int, default=N_VECTORS)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    weights = tile_weights()
    thresholds = [32] * N_NEURONS
    rng = np.random.RandomState(TB_SEED)

    ws = args.out / "tb_wb_ws.hex"
    ts = args.out / "tb_wb_ts.hex"
    xs = args.out / "tb_wb_xs.hex"
    ys = args.out / "tb_wb_ys.hex"

    with ws.open("w") as f:
        for w in weights:
            f.write(f"{w:016x}\n")
    with ts.open("w") as f:
        for t in thresholds:
            f.write(f"{t:02x}\n")
    with xs.open("w") as fx, ys.open("w") as fy:
        for _ in range(args.n):
            hi = int(rng.randint(0, 1 << 32))
            lo = int(rng.randint(0, 1 << 32))
            x = (hi << 32) | lo
            y = tile_y(x, weights, thresholds)
            fx.write(f"{x:016x}\n")
            fy.write(f"{y:04x}\n")

    print(
        f"wrote {len(weights)} weights, {len(thresholds)} thresholds, "
        f"{args.n} (x,y) pairs to {args.out}/tb_wb_*.hex"
    )


if __name__ == "__main__":
    main()
