"""Full MNIST test-set evaluation of the Phase-4.5 grouped 14×14 BNN.

Uses the Python golden's preprocessing (preprocess_image_14x14 from
bnn_reference.py) and an algebraically equivalent vectorized forward pass.

XNOR-popcount ↔ dot-product equivalence (same as 7×7 eval):
    For ±1 vectors x, w of length N:
        popcount(XNOR(x_bits, w_bits)) = (N + dot(x, w)) / 2
    Layer-1 threshold: popcount(x XNOR w_i) >= t_i
                     ⟺ dot(x, w_i) >= 2*t_i - 49
    Layer-2 logit: 2*popcount(h XNOR L2W_c) - 64 + bias_c
                 = dot(h_pm1, L2W_c) + bias_c

Vectorized forward over (N, 4, 49) → predictions in one numpy pass.
"""
from __future__ import annotations
import gzip
import json
import math
import struct
import sys
import time
from pathlib import Path

import numpy as np

ROOT      = Path(__file__).parent.parent
WEIGHTS   = ROOT / "data" / "bnn_weights_14x14.npz"
MNIST_DIR = ROOT / "data" / "mnist"
OUT_DIR   = ROOT / "results" / "phase4_prep"
OUT_JSON  = OUT_DIR / "full_mnist_accuracy_14x14.json"
OUT_MD    = OUT_DIR / "full_mnist_accuracy_14x14.md"

sys.path.insert(0, str(ROOT / "scripts"))
import bnn_reference as ref   # noqa: E402

EXPECTED_LO = 0.78
EXPECTED_HI = 0.92   # wide band; exact result depends on training run


# ---------------------------------------------------------------------------
# MNIST test-set loader (no torchvision dep).
# ---------------------------------------------------------------------------
def _idx_parse(buf: bytes) -> np.ndarray:
    magic, n = struct.unpack(">II", buf[:8])
    if magic == 2049:
        return np.frombuffer(buf, dtype=np.uint8, offset=8, count=n)
    if magic == 2051:
        r, c = struct.unpack(">II", buf[8:16])
        return np.frombuffer(buf, dtype=np.uint8, offset=16,
                             count=n * r * c).reshape(n, r, c)
    raise ValueError(f"unknown IDX magic 0x{magic:08x}")


def load_mnist_test(mnist_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    for name in ("t10k-images-idx3-ubyte.gz", "t10k-images-idx3-ubyte"):
        p = mnist_dir / name
        if p.exists():
            opener = gzip.open if name.endswith(".gz") else open
            with opener(p, "rb") as fh:
                images = _idx_parse(fh.read())
            break
    else:
        raise FileNotFoundError(f"MNIST test images not found in {mnist_dir}")
    for name in ("t10k-labels-idx1-ubyte.gz", "t10k-labels-idx1-ubyte"):
        p = mnist_dir / name
        if p.exists():
            opener = gzip.open if name.endswith(".gz") else open
            with opener(p, "rb") as fh:
                labels = _idx_parse(fh.read())
            break
    else:
        raise FileNotFoundError(f"MNIST test labels not found in {mnist_dir}")
    return images, labels


# ---------------------------------------------------------------------------
# Vectorized 14×14 grouped forward pass.
# ---------------------------------------------------------------------------
def preprocess_all(images: np.ndarray) -> np.ndarray:
    """(N,28,28) uint8 → (N,4,49) int8 ±1.

    Each row k of the (4,49) slice is quadrant k after per-quadrant
    strict>median binarization — identical logic to bnn_reference.preprocess_image_14x14
    but vectorized over the full test set.
    """
    N   = len(images)
    f   = images.astype(np.float32) / 255.0          # (N,28,28)
    # 2×2 non-overlapping average pool → (N,14,14)
    p14 = f.reshape(N, 14, 2, 14, 2).mean(axis=(2, 4))
    quad_slices = [
        p14[:, 0:7,  0:7 ].reshape(N, 49),
        p14[:, 0:7,  7:14].reshape(N, 49),
        p14[:, 7:14, 0:7 ].reshape(N, 49),
        p14[:, 7:14, 7:14].reshape(N, 49),
    ]
    result = np.zeros((N, 4, 49), dtype=np.int8)
    for k, q in enumerate(quad_slices):
        thr = np.median(q, axis=1, keepdims=True)
        result[:, k, :] = np.where(q > thr, 1, -1).astype(np.int8)
    return result   # (N, 4, 49)


def forward_all(x_quads: np.ndarray, net: dict) -> np.ndarray:
    """Vectorized grouped forward; returns (N,) int predictions.

    x_quads: (N,4,49) int8 ±1
    Uses dot-product equivalence of XNOR-popcount.
    """
    N   = x_quads.shape[0]
    l1w = net["l1_w"].astype(np.int32)   # (64, 49)
    l1t = net["l1_t"].astype(np.int32)   # (64,)
    l2w = net["l2_w"].astype(np.int32)   # (10, 64)
    l2b = net["l2_bias"].astype(np.int32) # (10,)

    # Layer 1: 4 branches, each branch k handles quadrant k and neurons k*16..k*16+15.
    hidden_bits = np.zeros((N, 64), dtype=np.int8)
    for k in range(4):
        xk   = x_quads[:, k, :].astype(np.int32)   # (N, 49)
        wk   = l1w[k*16:(k+1)*16, :]                # (16, 49)
        tk   = l1t[k*16:(k+1)*16]                   # (16,)
        # dots_ik ∈ [-49, 49] integer; pop = (49 + dot) / 2
        dots = xk @ wk.T                             # (N, 16)
        pops = (49 + dots) // 2                      # integer (N, 16)
        hidden_bits[:, k*16:(k+1)*16] = (pops >= tk).astype(np.int8)

    # Layer 2: hidden_bits ∈ {0,1} → ±1, then dot+bias = logit.
    h_pm1   = (hidden_bits.astype(np.int32) * 2 - 1)   # (N, 64) ±1
    logits  = h_pm1 @ l2w.T + l2b                        # (N, 10)
    return np.argmax(logits, axis=1).astype(np.int32)


# ---------------------------------------------------------------------------
# Wilson confidence interval.
# ---------------------------------------------------------------------------
def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    p    = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half   = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------
def main() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--weights",   default=str(WEIGHTS))
    p.add_argument("--mnist-dir", default=str(MNIST_DIR))
    args = p.parse_args()

    weights_path = Path(args.weights)
    mnist_dir    = Path(args.mnist_dir)

    print(f"weights : {weights_path}")
    print(f"mnist   : {mnist_dir}")

    print("loading weights …", end=" ", flush=True)
    net = ref.load_bnn_14x14(weights_path)
    print("ok")
    print(f"  l1_w {net['l1_w'].shape}  l1_t [{net['l1_t'].min()}..{net['l1_t'].max()}]")
    print(f"  l2_w {net['l2_w'].shape}  "
          f"l2_bias [{net['l2_bias'].min()}..{net['l2_bias'].max()}]")

    print("loading MNIST test set …", end=" ", flush=True)
    images, labels = load_mnist_test(mnist_dir)
    print(f"{len(images):,} images")

    print("preprocessing (per-quadrant median) …", end=" ", flush=True)
    t0 = time.time()
    x_quads = preprocess_all(images)    # (10000, 4, 49) int8
    print(f"{time.time()-t0:.1f}s")

    print("running vectorized forward pass …", end=" ", flush=True)
    t0 = time.time()
    preds = forward_all(x_quads, net)
    elapsed = time.time() - t0
    print(f"{elapsed:.1f}s  ({len(images)/elapsed:,.0f} img/s)")

    n_total   = len(labels)
    n_correct = int((preds == labels.astype(np.int32)).sum())
    accuracy  = n_correct / n_total
    ci_lo, ci_hi = wilson_ci(n_correct, n_total)

    print(f"\n{'='*55}")
    print(f"  Test images : {n_total:,}")
    print(f"  Correct     : {n_correct:,}")
    print(f"  Accuracy    : {accuracy*100:.2f}%")
    print(f"  95% Wilson CI: [{ci_lo*100:.2f}%, {ci_hi*100:.2f}%]")
    print(f"{'='*55}")

    # Per-class accuracy and confusion matrix.
    conf = np.zeros((10, 10), dtype=np.int32)
    for true, pred in zip(labels.astype(int), preds):
        conf[true, pred] += 1

    per_class_acc: dict[int, dict] = {}
    print("\nPer-digit accuracy:")
    for c in range(10):
        ok  = int(conf[c, c])
        tot = int(conf[c].sum())
        per_class_acc[c] = {"correct": ok, "total": tot,
                             "accuracy": ok / tot if tot else 0.0}
        print(f"  {c}: {ok:4d}/{tot}  {ok/tot*100:.1f}%")

    print("\nConfusion matrix (rows=true, cols=pred):")
    header = "     " + "".join(f"{c:5d}" for c in range(10))
    print(header)
    for r in range(10):
        row = f"  {r}: " + "".join(f"{conf[r,c]:5d}" for c in range(10))
        print(row)

    # Phase-3D and Phase-4.5 initial comparison.
    print(f"\nPhase-3D (7×7 BNN):          71.12%")
    print(f"Phase-4.5 initial (14×14):   80.73%")
    print(f"This eval (14×14 stage 1):   {accuracy*100:.2f}%")
    delta_vs_initial = (accuracy - 0.8073) * 100
    print(f"Delta vs initial 14×14:      {delta_vs_initial:+.2f} pp")

    # Save JSON.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = {
        "phase": "4_5_stage1",
        "description": "Full MNIST 10K eval — Phase-4.5 grouped 14×14 BNN (hard-tanh STE, OneCycleLR, 30 ep)",
        "network": "4×(49→16,BN,sign)→64→10, v4 quadrant preprocessing",
        "weights": str(weights_path),
        "n_total": n_total,
        "n_correct": n_correct,
        "accuracy": accuracy,
        "ci_95_lo": ci_lo,
        "ci_95_hi": ci_hi,
        "phase3d_7x7_bnn": 0.7112,
        "phase45_initial_80_73": 0.8073,
        "per_class": {str(c): per_class_acc[c] for c in range(10)},
        "confusion_matrix": conf.tolist(),
        "eval_time_seconds": round(elapsed, 1),
    }
    with open(OUT_JSON, "w") as fh:
        json.dump(results, fh, indent=2)
    print(f"\nSaved JSON → {OUT_JSON}")

    # Markdown.
    md = [
        "# Phase 4.5 Stage 1 — Full MNIST Test-Set Accuracy",
        "",
        "**Network**: 4×(49→16,BN,sign)→64→10 grouped BNN (14×14 grouped "
        "preprocessing, hard-tanh STE, OneCycleLR 30 ep, 3-seed best).",
        "",
        "## Headline Result",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Test images | {n_total:,} |",
        f"| Correct | {n_correct:,} |",
        f"| **Accuracy** | **{accuracy*100:.2f}%** |",
        f"| 95% Wilson CI | [{ci_lo*100:.2f}%, {ci_hi*100:.2f}%] |",
        f"| Phase-3D 7×7 BNN | 71.12% |",
        f"| Phase-4.5 initial 14×14 | 80.73% |",
        f"| Delta vs initial | {delta_vs_initial:+.2f} pp |",
        "",
        "## Per-Class Accuracy",
        "",
        "| Digit | Correct | Total | Accuracy |",
        "|-------|---------|-------|----------|",
    ]
    for c in range(10):
        d = per_class_acc[c]
        md.append(f"| {c} | {d['correct']} | {d['total']} | {d['accuracy']*100:.1f}% |")
    md += [
        "",
        "## Confusion Matrix",
        "",
        "Rows = true class, columns = predicted class.",
        "",
        "| True \\ Pred | " + " | ".join(str(c) for c in range(10)) + " |",
        "|" + "---|" * 11,
    ]
    for r in range(10):
        md.append("| **" + str(r) + "** | " +
                  " | ".join(str(conf[r, c]) for c in range(10)) + " |")
    md += [
        "",
        f"*Eval time: {elapsed:.1f}s on CPU.*",
    ]
    with open(OUT_MD, "w") as fh:
        fh.write("\n".join(md) + "\n")
    print(f"Saved MD  → {OUT_MD}")
    print("\nDone. Do NOT commit — review first.")


if __name__ == "__main__":
    main()
