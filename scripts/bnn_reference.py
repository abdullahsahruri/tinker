"""Python golden for the Phase-3D MNIST BNN — source of truth for the SoC.

Network shape (locked): 49 → 64 → 10, weights ±1, integer hidden thresholds,
integer signed output biases. The hardware semantics of one tile evaluation
(see PHASE3_ARCHITECTURE.md §4 and rtl/tile_tlg_ld) are:

    y[i] = (popcount(x XNOR W[i]) >= t[i])     for i in 0..15
where x, W[i] are 64-bit values; bit j is input/weight position j (LSB-first).

Layer 1 (49 → 64) maps onto FOUR sequential 16-neuron tile evaluations. The
49-bit binarized input occupies bits [48:0] of the 64-bit tile-input word.
The 15 padding bits [63:49] are encoded as:

    tile_input  bits [63:49] = 0       (PAD_INPUT_BITS)
    tile_weight bits [63:49] = all-1   (PAD_WEIGHT_BITS)

so that x XNOR w in those positions = 0 — they contribute zero to the popcount,
and the trained per-neuron threshold (in 0..49) maps directly onto the tile's
integer threshold register without offset. (Note: the brief loosely says "both
unused input and weight are 0, contributing nothing"; mathematically that
contributes a constant 15 per neuron because XNOR(0,0)=1, so the cleaner
convention used here puts a 1 on the weight side and folds nothing extra into
the threshold. Documented in docs/PHASE3D_NOTES.md.)

Layer 2 (64 → 10) does NOT use the tile. The tile only emits the binary
"above/below threshold" output, but argmax over 10 classes needs the
pre-threshold sums. Firmware therefore computes the layer-2 popcount in
software and applies an integer signed bias:

    logit[c] = 2 * popcount(h XNOR L2W[c]) - 64 + L2_bias[c]
    prediction = argmax(logit)

This file is the Python golden the testbench compares the SoC's classifications
against. If the SoC disagrees, the SoC is wrong; if PyTorch disagrees with
this golden, this golden is wrong.
"""
from __future__ import annotations
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Network shape — locked.
# ---------------------------------------------------------------------------
N_INPUT      = 49
N_HIDDEN     = 64
N_OUTPUT     = 10
TILE_INPUTS  = 64
N_PAD        = TILE_INPUTS - N_INPUT          # 15

# Layer-1 padding convention (see header).
PAD_INPUT_BITS  = 0
PAD_WEIGHT_BITS = ((1 << TILE_INPUTS) - 1) ^ ((1 << N_INPUT) - 1)   # bits [63:49]


# ---------------------------------------------------------------------------
# Loaders.
# ---------------------------------------------------------------------------
def load_bnn(path: str | Path) -> dict:
    """Return a dict with the five trained network arrays.

    Keys (matching scripts/train_bnn.py output):
        l1_w     int8  (64, 49)  in {-1, +1}
        l1_t     int32 (64,)     in [0, 49]
        l2_w     int8  (10, 64)  in {-1, +1}
        l2_t     int32 (10,)     in [0, 64]    (kept for spec compliance)
        l2_bias  int32 (10,)     signed integer (used for argmax)
    """
    d = np.load(path)
    return {
        "l1_w":    d["layer1_weights"].astype(np.int8),
        "l1_t":    d["layer1_thresholds"].astype(np.int32),
        "l2_w":    d["layer2_weights"].astype(np.int8),
        "l2_t":    d["layer2_thresholds"].astype(np.int32),
        "l2_bias": d["layer2_bias"].astype(np.int32),
    }


# ---------------------------------------------------------------------------
# Preprocessing (28x28 → 49 ±1 ints).
# ---------------------------------------------------------------------------
def preprocess_image(img_28x28: np.ndarray) -> np.ndarray:
    """28x28 grayscale (uint8 0..255 *or* float in [0,1]) → 49 ±1 int8 vector.

    Steps: normalize to [0,1] → average-pool 4x4 stride 4 → 7x7 floats →
    strict-`>` per-image median binarization → flatten row-major.

    See scripts/train_bnn.py for the full Path-B v1→v4 evolution. Strict
    `>` (rather than `>=`) handles the 94 % of MNIST images whose
    49-element median is exactly 0: only the strictly-positive pooled
    positions (the actual digit pixels) get +1 in those cases, while a
    `>= 0` would mark essentially every position +1 and starve the
    classifier. For 49 odd elements numpy.median returns the unique
    middle value (24th sorted, 0-indexed), which matches torch.median's
    lower-median convention — keeping numpy and PyTorch byte-identical.
    """
    if img_28x28.shape != (28, 28):
        raise ValueError(f"expected (28,28) image, got {img_28x28.shape}")
    f = img_28x28.astype(np.float32)
    if f.max() > 1.5:
        f = f / 255.0
    pooled = f.reshape(7, 4, 7, 4).mean(axis=(1, 3)).flatten()    # (49,)
    threshold = float(np.median(pooled))                            # scalar
    binarized = np.where(pooled > threshold, 1, -1).astype(np.int8)
    return binarized                                                # (49,)


# ---------------------------------------------------------------------------
# Bit-packing helpers.
# ---------------------------------------------------------------------------
def _pm1_to_bit(v: np.ndarray) -> np.ndarray:
    """Map ±1 → 0/1 (with +1 → 1, -1 → 0)."""
    return ((v.astype(np.int32) + 1) // 2).astype(np.uint64)


def pack_bits_lsb(bits: np.ndarray) -> int:
    """Pack a 1D bit array (LSB at index 0) into a Python int."""
    word = 0
    for j, b in enumerate(bits):
        word |= int(b) << j
    return word


def pack_input_l1(x_pm1: np.ndarray) -> int:
    """49-element ±1 input → 64-bit tile-input word (PAD_INPUT_BITS in [63:49])."""
    if x_pm1.shape != (N_INPUT,):
        raise ValueError(f"expected ({N_INPUT},) ±1, got {x_pm1.shape}")
    return pack_bits_lsb(_pm1_to_bit(x_pm1)) | PAD_INPUT_BITS


def pack_weight_l1(w_pm1: np.ndarray) -> int:
    """One layer-1 neuron's 49 ±1 weights → 64-bit tile-weight word
    (PAD_WEIGHT_BITS in [63:49])."""
    if w_pm1.shape != (N_INPUT,):
        raise ValueError(f"expected ({N_INPUT},) weight, got {w_pm1.shape}")
    return pack_bits_lsb(_pm1_to_bit(w_pm1)) | PAD_WEIGHT_BITS


def pack_weight_l2(w_pm1: np.ndarray) -> int:
    """One layer-2 class's 64 ±1 weights → 64-bit weight word (no padding)."""
    if w_pm1.shape != (N_HIDDEN,):
        raise ValueError(f"expected ({N_HIDDEN},) weight, got {w_pm1.shape}")
    return pack_bits_lsb(_pm1_to_bit(w_pm1))


# ---------------------------------------------------------------------------
# Forward pass.
# ---------------------------------------------------------------------------
def _popcount(x: int, nbits: int) -> int:
    mask = (1 << nbits) - 1
    return bin(x & mask).count("1")


def hidden_layer(x_pm1: np.ndarray, l1_w: np.ndarray,
                 l1_t: np.ndarray) -> int:
    """Layer 1 forward over the hardware contract; returns 64-bit hidden output.

    Bit i of the result is the binary output of hidden neuron i (1 iff the
    popcount over 49 active bits is >= l1_t[i]; padding contributes 0 by
    construction).
    """
    x_word = pack_input_l1(x_pm1)
    out = 0
    for i in range(N_HIDDEN):
        w_word = pack_weight_l1(l1_w[i])
        xnor = (~(x_word ^ w_word)) & ((1 << TILE_INPUTS) - 1)
        if bin(xnor).count("1") >= int(l1_t[i]):
            out |= 1 << i
    return out


def output_layer(hidden_word: int, l2_w: np.ndarray,
                 l2_bias: np.ndarray) -> tuple[int, np.ndarray]:
    """Layer 2 forward in software; returns (predicted_class, logits[10] int32).

    logit[c] = 2 * popcount(hidden XNOR L2W[c]) - 64 + bias[c]
    """
    logits = np.zeros(N_OUTPUT, dtype=np.int32)
    for c in range(N_OUTPUT):
        w_word = pack_weight_l2(l2_w[c])
        p = _popcount((~(hidden_word ^ w_word)) & ((1 << N_HIDDEN) - 1),
                      N_HIDDEN)
        logits[c] = 2 * p - N_HIDDEN + int(l2_bias[c])
    return int(np.argmax(logits)), logits


def bnn_forward(img_28x28: np.ndarray, network: dict) -> int:
    x = preprocess_image(img_28x28)
    h = hidden_layer(x, network["l1_w"], network["l1_t"])
    cls, _ = output_layer(h, network["l2_w"], network["l2_bias"])
    return cls


# ---------------------------------------------------------------------------
# CLI: predict on a small test set and print classifications.
# ---------------------------------------------------------------------------
def _cli() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--weights", default="data/bnn_weights.npz")
    p.add_argument("--testset", default="data/bnn_test_set.npz")
    args = p.parse_args()

    net = load_bnn(args.weights)
    ts = np.load(args.testset)
    images = ts["images"]               # (N, 28, 28) uint8
    expected = ts["labels"]             # (N,) int

    correct = 0
    for i in range(len(images)):
        pred = bnn_forward(images[i], net)
        ok = "OK" if pred == int(expected[i]) else "MISMATCH"
        print(f"  img[{i:2d}]: golden_pred={pred}  expected={int(expected[i])}  {ok}")
        if pred == int(expected[i]):
            correct += 1
    print(f"golden vs expected: {correct}/{len(images)}")


if __name__ == "__main__":
    _cli()
