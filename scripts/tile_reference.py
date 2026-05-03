"""Python golden model for the BNN tile.

The tile computes 16 binary outputs from one 64-bit input vector x against
a fixed (per-neuron) weight matrix W and threshold vector t:

    y[i] = (popcount(x XNOR W[i]) >= t[i])     for i in 0..15

Source of truth — every Verilog variant is checked against this function in
the testbench. If a Verilog variant disagrees, the Verilog is wrong.
"""
from __future__ import annotations
from typing import Sequence
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tlg_lib import reference_y, gen_weight_set, w_to_int, N_INPUTS  # noqa: E402

N_NEURONS = 16
WEIGHT_SEED = 42  # must match gen_tile.py


def tile_weights() -> list[int]:
    """The 16 64-bit weight integers used by both the hardcoded variants
    (baked in) and the loadable variants (programmed at runtime via cfg)."""
    return [w_to_int(w) for w in gen_weight_set(WEIGHT_SEED, N_NEURONS)]


def tile_y(x_int: int, w_ints: Sequence[int],
           thresholds: Sequence[int]) -> int:
    """Pack 16 neuron outputs into a 16-bit int. y[i] is bit i."""
    y = 0
    for i, (w, t) in enumerate(zip(w_ints, thresholds)):
        y |= reference_y(x_int, w, t) << i
    return y
