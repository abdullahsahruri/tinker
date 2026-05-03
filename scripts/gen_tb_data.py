#!/usr/bin/env python3
"""Generate testbench input vectors + golden outputs for a given seed.

Writes:
  <out>/tb_xs_s<seed>.hex   — one 64-bit hex input per line (LSB-first nibble order
                              compatible with $readmemh)
  <out>/tb_ys_s<seed>.hex   — one bit per line (0 or 1), matching xs line-by-line

The "expected y" follows the same Python golden model as the RTL generator.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

# Reuse the reference function from gen_neuron to keep one source of truth.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_neuron import gen_weights, w_to_int, reference_y, N_INPUTS  # noqa: E402

import numpy as np  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    w_int = w_to_int(gen_weights(args.seed))
    rng = np.random.RandomState(0xBEEF + args.seed)  # independent of weight RNG
    mask = (1 << N_INPUTS) - 1

    xs_path = args.out / f"tb_xs_s{args.seed}.hex"
    ys_path = args.out / f"tb_ys_s{args.seed}.hex"

    with xs_path.open("w") as fx, ys_path.open("w") as fy:
        for _ in range(args.n):
            # Build a uniformly-random 64-bit value out of two 32-bit draws.
            hi = int(rng.randint(0, 1 << 32))
            lo = int(rng.randint(0, 1 << 32))
            x = ((hi << 32) | lo) & mask
            y = reference_y(x, w_int)
            fx.write(f"{x:016x}\n")
            fy.write(f"{y}\n")
    print(f"wrote {args.n} vectors to {xs_path} and {ys_path} (seed={args.seed}, "
          f"W=0x{w_int:016x})")


if __name__ == "__main__":
    main()
