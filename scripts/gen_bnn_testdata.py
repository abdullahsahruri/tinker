"""Generate the 16-image Phase-3D test set + Python-vs-PyTorch agreement check.

Outputs (idempotent):
    data/bnn_test_set.npz       — full test set
        images:    uint8  (16, 28, 28)   — raw MNIST test images
        labels:    uint8  (16,)          — MNIST ground-truth labels
        x_pm1:     int8   (16, 49)       — preprocessed ±1 features
        x_lo:      uint32 (16,)          — bits [31:0] of the 49-b packed word
        x_hi:      uint32 (16,)          — bits [63:32] (bits [63:49] = 0)
        expected:  uint8  (16,)          — Python-golden classifications
                                           (this is what the SoC must match)
    tb/tb_bnn_xs.hex            — 32 lines × 8 hex digits = 16 (lo, hi) pairs
                                  for $readmemh into wb_dmem.mem at offsets
                                  0..31. lo at even offsets, hi at odd.
    tb/tb_bnn_expected.hex      — 16 lines × 2 hex digits = 16 expected
                                  classes.

Also performs the Phase-3D checkpoint #1 verification:
    PyTorch model (data/bnn_model.pt) prediction on the 16 raw images
        ==
    bnn_reference.bnn_forward on the same 16 raw images.

A mismatch indicates the binarization in train_bnn.py and bnn_reference.py
disagree — fix before proceeding to firmware.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bnn_reference as ref           # noqa: E402

N_IMAGES = 16


def _pack_input_words(x_pm1_row: np.ndarray) -> tuple[int, int]:
    """49 ±1 → (lo32, hi32). Bits [63:49] = 0 (PAD_INPUT_BITS)."""
    word = ref.pack_input_l1(x_pm1_row)        # 64-bit Python int
    lo = word & 0xFFFFFFFF
    hi = (word >> 32) & 0xFFFFFFFF
    return int(lo), int(hi)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--weights", default="data/bnn_weights.npz")
    p.add_argument("--mnist-dir", default="data/mnist")
    p.add_argument("--out-npz", default="data/bnn_test_set.npz")
    p.add_argument("--out-xs",  default="tb/tb_bnn_xs.hex")
    p.add_argument("--out-exp", default="tb/tb_bnn_expected.hex")
    p.add_argument("--n", type=int, default=N_IMAGES)
    p.add_argument("--no-pytorch-check", action="store_true",
                   help="skip the train_bnn PyTorch ↔ bnn_reference agreement check")
    args = p.parse_args()

    # Load MNIST test set (uses train_bnn's loader so we don't re-implement IDX).
    import train_bnn                      # type: ignore
    _, _, x_te_full, y_te_full = train_bnn.load_mnist(Path(args.mnist_dir))
    images = x_te_full[: args.n]
    labels = y_te_full[: args.n]

    network = ref.load_bnn(args.weights)

    # Compute golden predictions + packed-input words.
    x_pm1_rows = np.zeros((args.n, ref.N_INPUT), dtype=np.int8)
    x_lo = np.zeros(args.n, dtype=np.uint32)
    x_hi = np.zeros(args.n, dtype=np.uint32)
    expected = np.zeros(args.n, dtype=np.uint8)
    for i in range(args.n):
        x_pm1 = ref.preprocess_image(images[i])
        x_pm1_rows[i] = x_pm1
        lo, hi = _pack_input_words(x_pm1)
        x_lo[i] = lo
        x_hi[i] = hi
        expected[i] = ref.bnn_forward(images[i], network)

    # Pretty-print the per-image table.
    n_label_match = int((expected == labels).sum())
    print(f"Python-golden vs MNIST labels: {n_label_match}/{args.n} correct")
    for i in range(args.n):
        print(f"  img[{i:2d}] label={int(labels[i])}  golden_pred={int(expected[i])}  "
              f"x_lo=0x{int(x_lo[i]):08x}  x_hi=0x{int(x_hi[i]):08x}")

    # ---- PyTorch ↔ Python-golden agreement check ----------------------------
    if not args.no_pytorch_check:
        try:
            import torch
            import torch.nn.functional as F
            model_pt = Path(args.weights).with_suffix(".pt")
            if not model_pt.exists():
                print(f"!! {model_pt} missing; skipping PyTorch check (rerun train_bnn.py)")
            else:
                model = train_bnn.BNN_49_64_10()
                state = torch.load(model_pt, map_location="cpu")
                model.load_state_dict(state)
                model.eval()
                with torch.no_grad():
                    xb = torch.from_numpy(images).unsqueeze(1).to(torch.float32)
                    xb = train_bnn.preprocess_batch(xb)
                    pt_pred = model(xb).argmax(dim=1).cpu().numpy().astype(np.uint8)
                mismatch = np.where(pt_pred != expected)[0]
                if len(mismatch) == 0:
                    print(f"PyTorch ↔ Python-golden: 16/16 agree (CHECKPOINT #1 PASS)")
                else:
                    print(f"!! PyTorch ↔ Python-golden DISAGREE on {len(mismatch)}/{args.n}")
                    for j in mismatch:
                        print(f"  img[{j:2d}]: pytorch={int(pt_pred[j])}  golden={int(expected[j])}")
                    print("  → Fix the golden binarization, NEVER patch the SoC to match PyTorch.")
        except Exception as e:
            print(f"!! PyTorch check failed: {e!r}")

    # Write npz.
    out_npz = Path(args.out_npz)
    out_npz.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        out_npz,
        images=images.astype(np.uint8),
        labels=labels.astype(np.uint8),
        x_pm1=x_pm1_rows,
        x_lo=x_lo,
        x_hi=x_hi,
        expected=expected,
    )
    print(f"wrote {out_npz}")

    # Write tb_bnn_xs.hex — 16 (lo, hi) pairs in DMEM-word order.
    out_xs = Path(args.out_xs)
    out_xs.parent.mkdir(parents=True, exist_ok=True)
    with out_xs.open("w") as fh:
        for i in range(args.n):
            fh.write(f"{int(x_lo[i]):08x}\n")
            fh.write(f"{int(x_hi[i]):08x}\n")
    print(f"wrote {out_xs}  ({2*args.n} words)")

    # Write tb_bnn_expected.hex — 16 single-byte classes.
    out_exp = Path(args.out_exp)
    out_exp.parent.mkdir(parents=True, exist_ok=True)
    with out_exp.open("w") as fh:
        for i in range(args.n):
            fh.write(f"{int(expected[i]):02x}\n")
    print(f"wrote {out_exp}  ({args.n} bytes)")


if __name__ == "__main__":
    main()
