"""Generate the BNN test set + Python-vs-PyTorch agreement check.

Supports --net 7x7 (Phase-3D, default) and --net 14x14 (Phase-4.5 grouped).

7×7 outputs:
    data/bnn_test_set.npz       — images, labels, x_pm1(16,49), expected
    tb/tb_bnn_xs.hex            — 32 lines (2 words/image: lo, hi)
    tb/tb_bnn_expected.hex      — 16 lines (expected classes)

14×14 outputs:
    data/bnn_test_set_14x14.npz — images, labels, x_pm1(16,4,49), expected
    tb/tb_bnn_xs_14x14.hex      — 128 lines (8 words/image: q0lo,q0hi,…,q3lo,q3hi)
    tb/tb_bnn_expected_14x14.hex — 16 lines (expected classes)

Also performs PyTorch ↔ Python-golden agreement check (PAUSE-POINT 1 gate).
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
    word = ref.pack_input_l1(x_pm1_row)
    return int(word & 0xFFFFFFFF), int((word >> 32) & 0xFFFFFFFF)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--net", choices=["7x7", "14x14"], default="7x7")
    p.add_argument("--weights", default=None,
                   help="npz path (default: data/bnn_weights[_14x14].npz)")
    p.add_argument("--mnist-dir", default="data/mnist")
    p.add_argument("--out-npz", default=None)
    p.add_argument("--out-xs",  default=None)
    p.add_argument("--out-exp", default=None)
    p.add_argument("--n", type=int, default=N_IMAGES)
    p.add_argument("--no-pytorch-check", action="store_true",
                   help="skip the train_bnn PyTorch ↔ bnn_reference agreement check")
    args = p.parse_args()

    net14 = (args.net == "14x14")
    if args.weights is None:
        args.weights = ("data/bnn_weights_14x14.npz" if net14
                        else "data/bnn_weights.npz")
    if args.out_npz is None:
        args.out_npz = ("data/bnn_test_set_14x14.npz" if net14
                        else "data/bnn_test_set.npz")
    if args.out_xs is None:
        args.out_xs  = ("tb/tb_bnn_xs_14x14.hex" if net14
                        else "tb/tb_bnn_xs.hex")
    if args.out_exp is None:
        args.out_exp = ("tb/tb_bnn_expected_14x14.hex" if net14
                        else "tb/tb_bnn_expected.hex")

    import train_bnn                      # type: ignore
    _, _, x_te_full, y_te_full = train_bnn.load_mnist(Path(args.mnist_dir))
    images = x_te_full[: args.n]
    labels = y_te_full[: args.n]

    network = ref.load_bnn(args.weights)

    if net14:
        # 14×14: 4 quadrant inputs per image (8 DMEM words per image)
        x_pm1_quads = np.zeros((args.n, 4, 49), dtype=np.int8)
        # x_words[i, k, 0/1] = lo/hi for quadrant k of image i
        x_words = np.zeros((args.n, 4, 2), dtype=np.uint32)
        expected = np.zeros(args.n, dtype=np.uint8)
        for i in range(args.n):
            quads = ref.preprocess_image_14x14(images[i])   # (4, 49)
            x_pm1_quads[i] = quads
            for k in range(4):
                lo, hi = _pack_input_words(quads[k])
                x_words[i, k, 0] = lo
                x_words[i, k, 1] = hi
            expected[i] = ref.bnn_forward_14x14(images[i], network)

        n_label_match = int((expected == labels).sum())
        print(f"Python-golden vs MNIST labels: {n_label_match}/{args.n} correct")
        for i in range(args.n):
            q_strs = "  ".join(
                f"q{k}=(0x{int(x_words[i,k,0]):08x}, 0x{int(x_words[i,k,1]):08x})"
                for k in range(4))
            print(f"  img[{i:2d}] label={int(labels[i])}  "
                  f"golden_pred={int(expected[i])}  {q_strs}")

        if not args.no_pytorch_check:
            _pytorch_check_14x14(images, expected, network, args.weights, args.n)

        out_npz = Path(args.out_npz)
        out_npz.parent.mkdir(parents=True, exist_ok=True)
        np.savez(out_npz,
                 images=images.astype(np.uint8),
                 labels=labels.astype(np.uint8),
                 x_pm1=x_pm1_quads,
                 expected=expected)
        print(f"wrote {out_npz}")

        # tb_bnn_xs_14x14.hex — 8 words per image: q0lo, q0hi, q1lo, q1hi, …
        out_xs = Path(args.out_xs)
        out_xs.parent.mkdir(parents=True, exist_ok=True)
        with out_xs.open("w") as fh:
            for i in range(args.n):
                for k in range(4):
                    fh.write(f"{int(x_words[i, k, 0]):08x}\n")
                    fh.write(f"{int(x_words[i, k, 1]):08x}\n")
        print(f"wrote {out_xs}  ({8*args.n} words)")

    else:
        # 7×7: 1 input per image (2 DMEM words per image)
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

        n_label_match = int((expected == labels).sum())
        print(f"Python-golden vs MNIST labels: {n_label_match}/{args.n} correct")
        for i in range(args.n):
            print(f"  img[{i:2d}] label={int(labels[i])}  "
                  f"golden_pred={int(expected[i])}  "
                  f"x_lo=0x{int(x_lo[i]):08x}  x_hi=0x{int(x_hi[i]):08x}")

        if not args.no_pytorch_check:
            _pytorch_check_7x7(images, expected, args.weights, args.n)

        out_npz = Path(args.out_npz)
        out_npz.parent.mkdir(parents=True, exist_ok=True)
        np.savez(out_npz,
                 images=images.astype(np.uint8),
                 labels=labels.astype(np.uint8),
                 x_pm1=x_pm1_rows,
                 x_lo=x_lo, x_hi=x_hi,
                 expected=expected)
        print(f"wrote {out_npz}")

        out_xs = Path(args.out_xs)
        out_xs.parent.mkdir(parents=True, exist_ok=True)
        with out_xs.open("w") as fh:
            for i in range(args.n):
                fh.write(f"{int(x_lo[i]):08x}\n")
                fh.write(f"{int(x_hi[i]):08x}\n")
        print(f"wrote {out_xs}  ({2*args.n} words)")

    # Expected hex is the same for both nets.
    out_exp = Path(args.out_exp)
    out_exp.parent.mkdir(parents=True, exist_ok=True)
    with out_exp.open("w") as fh:
        for i in range(args.n):
            fh.write(f"{int(expected[i]):02x}\n")
    print(f"wrote {out_exp}  ({args.n} bytes)")


# ---------------------------------------------------------------------------
# PyTorch ↔ Python-golden agreement checks (PAUSE-POINT 1 gate).
# ---------------------------------------------------------------------------
def _pytorch_check_7x7(images, expected, weights_path, n):
    try:
        import torch
        import train_bnn                  # type: ignore
        model_pt = Path(weights_path).with_suffix(".pt")
        if not model_pt.exists():
            print(f"!! {model_pt} missing; skipping PyTorch check")
            return
        model = train_bnn.BNN_49_64_10()
        model.load_state_dict(torch.load(model_pt, map_location="cpu"))
        model.eval()
        with torch.no_grad():
            xb = torch.from_numpy(images).unsqueeze(1).to(torch.float32)
            xb = train_bnn.preprocess_batch(xb)
            pt_pred = model(xb).argmax(dim=1).cpu().numpy().astype(np.uint8)
        _report_agreement(pt_pred, expected, n)
    except Exception as e:
        print(f"!! PyTorch check failed: {e!r}")


def _pytorch_check_14x14(images, expected, network, weights_path, n):
    try:
        import torch
        import train_bnn                  # type: ignore
        model_pt = Path(weights_path).with_suffix(".pt")
        if not model_pt.exists():
            print(f"!! {model_pt} missing; skipping PyTorch check")
            return
        model = train_bnn.GroupedBNN_14x14()
        model.load_state_dict(torch.load(model_pt, map_location="cpu"))
        model.eval()
        with torch.no_grad():
            xb = torch.from_numpy(images).unsqueeze(1).to(torch.float32)
            xb = train_bnn.preprocess_grouped_batch_14x14(xb)
            pt_pred = model(xb).argmax(dim=1).cpu().numpy().astype(np.uint8)
        _report_agreement(pt_pred, expected, n)
    except Exception as e:
        print(f"!! PyTorch check failed: {e!r}")


def _report_agreement(pt_pred, golden, n):
    mismatch = np.where(pt_pred != golden)[0]
    if len(mismatch) == 0:
        print(f"PyTorch ↔ Python-golden: {n}/{n} agree (CHECKPOINT #1 PASS)")
    else:
        print(f"!! PyTorch ↔ Python-golden DISAGREE on {len(mismatch)}/{n}")
        for j in mismatch:
            print(f"  img[{j:2d}]: pytorch={int(pt_pred[j])}  golden={int(golden[j])}")
        print("  → Fix the golden binarization, NEVER patch the SoC to match PyTorch.")


if __name__ == "__main__":
    main()
