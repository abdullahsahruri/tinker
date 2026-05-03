#!/usr/bin/env python3
"""Generate the 200 random input vectors and corresponding 16-bit golden
outputs for the tile testbench.

  tb/tb_tile_xs.hex   — one 16-hex-digit input per line ($readmemh-compatible)
  tb/tb_tile_ys.hex   — one 4-hex-digit expected output per line (16 bits)
  tb/tb_tile_ws.hex   — 16 lines, the per-neuron 64-bit weights (programmed
                        into the loadable variants before vector replay)
  tb/tb_tile_ts.hex   — 16 lines, 7-bit thresholds (low bits of each line)

Same (W, t) used as gen_tile.py's hardcoded variants — ensures the testbench
checks all four DUTs (the two loadable ones are programmed with these values
before vector replay begins).
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tile_reference import tile_y, tile_weights, N_NEURONS  # noqa: E402

import numpy as np  # noqa: E402

N_VECTORS = 200
TB_SEED = 0xC0FFEE


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("tb"))
    p.add_argument("--n", type=int, default=N_VECTORS)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    rng = np.random.RandomState(TB_SEED)
    weights = tile_weights()
    thresholds = [32] * N_NEURONS

    xs_path = args.out / "tb_tile_xs.hex"
    ys_path = args.out / "tb_tile_ys.hex"
    with xs_path.open("w") as fx, ys_path.open("w") as fy:
        for _ in range(args.n):
            hi = int(rng.randint(0, 1 << 32))
            lo = int(rng.randint(0, 1 << 32))
            x = (hi << 32) | lo
            y = tile_y(x, weights, thresholds)
            fx.write(f"{x:016x}\n")
            fy.write(f"{y:04x}\n")
    ws_path = args.out / "tb_tile_ws.hex"
    ts_path = args.out / "tb_tile_ts.hex"
    with ws_path.open("w") as fw, ts_path.open("w") as ft:
        for w, t in zip(weights, thresholds):
            fw.write(f"{w:016x}\n")
            ft.write(f"{t:02x}\n")  # 7-bit value, comfortably in 2 hex chars

    print(f"wrote {args.n} (x, y) pairs to {xs_path}, {ys_path}")
    print(f"wrote {len(weights)} (w, t) pairs to {ws_path}, {ts_path}")
    print(f"  weights from numpy.random.RandomState(42), {N_NEURONS} neurons, "
          f"thresholds=32 each")


if __name__ == "__main__":
    main()
