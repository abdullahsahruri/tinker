"""Full MNIST test-set evaluation of the Phase-3D golden BNN.

Uses the Python golden's preprocessing (preprocess_image from bnn_reference.py)
and an algebraically equivalent vectorized forward pass for speed.

Equivalence proof (XNOR-popcount = dot arithmetic):
    For ±1 vectors x, w of length N:
        popcount(XNOR(x_bits, w_bits)) = (N + dot(x, w)) / 2
    Because XNOR bit is 1 iff x_i == w_i, i.e. x_i*w_i = +1; -1 when they
    differ. So dot(x,w) = agrees - disagrees = 2*popcount - N.
    Layer-1 threshold: popcount >= t  ↔  dot(x, w) >= 2t - 49
    Layer-2 logit:     2*popcount - 64 + bias = dot(h_pm1, w) + bias
    Both are exact integer arithmetic — byte-identical predictions to the golden.
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

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT       = Path(__file__).parent.parent
WEIGHTS    = ROOT / "data" / "bnn_weights.npz"
MNIST_DIR  = ROOT / "data" / "mnist"
OUT_DIR    = ROOT / "results" / "phase4_prep"
OUT_JSON   = OUT_DIR / "full_mnist_accuracy.json"
OUT_MD     = OUT_DIR / "full_mnist_accuracy.md"

# Add scripts/ to path so we can import from bnn_reference.
sys.path.insert(0, str(ROOT / "scripts"))
from bnn_reference import preprocess_image, load_bnn  # noqa: E402


# ---------------------------------------------------------------------------
# MNIST loader — reads gz files from MNIST_DIR without torchvision.
# ---------------------------------------------------------------------------
def _idx_parse(buf: bytes) -> np.ndarray:
    magic, n_items = struct.unpack(">II", buf[:8])
    if magic == 2049:                        # labels
        return np.frombuffer(buf, dtype=np.uint8, offset=8, count=n_items)
    if magic == 2051:                        # images
        rows, cols = struct.unpack(">II", buf[8:16])
        return np.frombuffer(buf, dtype=np.uint8, offset=16,
                             count=n_items * rows * cols).reshape(n_items, rows, cols)
    raise ValueError(f"unknown IDX magic 0x{magic:08x}")


def load_mnist_test(mnist_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (images (10000, 28, 28) uint8, labels (10000,) uint8)."""
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
# Vectorized BNN forward (equivalent to bnn_reference golden).
# ---------------------------------------------------------------------------
def bnn_forward_vectorized(img_28x28: np.ndarray, net: dict) -> int:
    """Single-image forward using vectorized numpy dot products."""
    x = preprocess_image(img_28x28)                       # (49,) ±1 int8

    # Layer 1: threshold comparison in dot-product space.
    # dot(x, l1_w[i]) = 2*popcount(XNOR) - 49
    # neuron fires if popcount >= l1_t[i]  ↔  dot >= 2*l1_t[i] - 49
    z1 = net["l1_w"].astype(np.int32) @ x.astype(np.int32)   # (64,)
    thresholds1 = 2 * net["l1_t"].astype(np.int32) - 49       # (64,)
    h_binary = (z1 >= thresholds1)                             # (64,) bool
    h_pm1 = (2 * h_binary.astype(np.int32) - 1)               # (64,) ±1

    # Layer 2: logit[c] = 2*popcount(h XNOR l2w[c]) - 64 + bias[c]
    #                    = dot(h_pm1, l2w[c]) + bias[c]
    logits = net["l2_w"].astype(np.int32) @ h_pm1 + net["l2_bias"].astype(np.int32)
    return int(np.argmax(logits))


# ---------------------------------------------------------------------------
# Wilson 95% confidence interval.
# ---------------------------------------------------------------------------
def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Return (lo, hi) of Wilson score interval for k successes in n trials."""
    p_hat = k / n
    denom = 1 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denom
    half   = (z / denom) * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n))
    return max(0.0, center - half), min(1.0, center + half)


# ---------------------------------------------------------------------------
# Main evaluation.
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("Phase 4 prep — full MNIST test-set evaluation")
    print("=" * 60)

    print(f"\nLoading weights from {WEIGHTS}")
    net = load_bnn(WEIGHTS)
    print(f"  l1_w {net['l1_w'].shape}  l1_t [{net['l1_t'].min()}..{net['l1_t'].max()}]")
    print(f"  l2_w {net['l2_w'].shape}  l2_bias [{net['l2_bias'].min()}..{net['l2_bias'].max()}]")

    print(f"\nLoading MNIST test set from {MNIST_DIR}")
    images, labels = load_mnist_test(MNIST_DIR)
    n_total = len(images)
    print(f"  {n_total} images, shape {images.shape}, dtype {images.dtype}")

    print(f"\nRunning forward pass on {n_total} images …")
    t0 = time.time()

    predictions = np.empty(n_total, dtype=np.int32)
    for i in range(n_total):
        predictions[i] = bnn_forward_vectorized(images[i], net)
        if (i + 1) % 1000 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta  = (n_total - i - 1) / rate
            print(f"  {i+1:5d}/{n_total}  {rate:.0f} img/s  ETA {eta:.0f}s")

    elapsed = time.time() - t0
    print(f"  done in {elapsed:.1f}s  ({n_total/elapsed:.0f} img/s)")

    # Overall accuracy.
    labels_i = labels.astype(np.int32)
    correct_mask = (predictions == labels_i)
    n_correct = int(correct_mask.sum())
    accuracy = n_correct / n_total
    ci_lo, ci_hi = wilson_ci(n_correct, n_total)

    print(f"\nOverall accuracy: {n_correct}/{n_total} = {accuracy:.4f} "
          f"({accuracy*100:.2f}%)  95% CI [{ci_lo*100:.2f}%, {ci_hi*100:.2f}%]")

    # Sanity check.
    EXPECTED_LO, EXPECTED_HI = 0.60, 0.80
    if accuracy < EXPECTED_LO:
        print(f"  !! SUSPICIOUS: {accuracy:.4f} < {EXPECTED_LO} — possible preprocessing mismatch")
    elif accuracy > EXPECTED_HI:
        print(f"  !! SUSPICIOUS: {accuracy:.4f} > {EXPECTED_HI} — unexpectedly high, check for data leakage")
    else:
        print(f"  ✓ Within expected range [{EXPECTED_LO:.0%}, {EXPECTED_HI:.0%}]")

    # Per-class accuracy.
    per_class_acc = {}
    for c in range(10):
        mask = (labels_i == c)
        n_c = int(mask.sum())
        n_c_correct = int(correct_mask[mask].sum())
        per_class_acc[c] = {"correct": n_c_correct, "total": n_c,
                             "accuracy": n_c_correct / n_c if n_c > 0 else 0.0}

    print("\nPer-class accuracy:")
    for c in range(10):
        d = per_class_acc[c]
        print(f"  class {c}: {d['correct']:4d}/{d['total']:4d} = {d['accuracy']:.4f}")

    # Confusion matrix.
    conf = np.zeros((10, 10), dtype=np.int32)
    for pred, true in zip(predictions, labels_i):
        conf[true, pred] += 1

    print("\nConfusion matrix (rows=true, cols=pred):")
    header = "     " + "".join(f"{c:5d}" for c in range(10))
    print(header)
    for r in range(10):
        row = f"  {r}: " + "".join(f"{conf[r,c]:5d}" for c in range(10))
        print(row)

    # Cross-check against Phase-3D 16-image batch.
    # (Can't reproduce exact images without bnn_test_set.npz alignment check,
    #  but we know the expected accuracy is ~0.7127 from training logs.)
    print(f"\nPhase-3D reference: training reported test_acc=0.7127")
    print(f"This eval:          test_acc={accuracy:.4f}")
    delta_pp = (accuracy - 0.7127) * 100
    print(f"Delta: {delta_pp:+.2f} pp (expected ~0 ± a few pp due to different random seeds)")

    # Save results.
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    results = {
        "phase": "4_prep",
        "description": "Full MNIST test-set accuracy of Phase-3D golden BNN",
        "network": "49→64→10 BinaryConnect v4-preprocessing",
        "n_total": n_total,
        "n_correct": n_correct,
        "accuracy": accuracy,
        "ci_95_lo": ci_lo,
        "ci_95_hi": ci_hi,
        "phase3d_train_reported_test_acc": 0.7127,
        "phase3d_16img_accuracy": 13 / 16,
        "per_class": {
            str(c): per_class_acc[c] for c in range(10)
        },
        "confusion_matrix": conf.tolist(),
        "eval_time_seconds": round(elapsed, 1),
    }

    with open(OUT_JSON, "w") as fh:
        json.dump(results, fh, indent=2)
    print(f"\nSaved JSON → {OUT_JSON}")

    # Markdown summary.
    md = [
        "# Phase 4 Prep — Full MNIST Test-Set Accuracy",
        "",
        f"**Network**: 49→64→10 BinaryConnect, v4 preprocessing (strict `>` per-image median), "
        f"trained weights from `data/bnn_weights.npz`.",
        "",
        "## Headline Result",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Test images | {n_total:,} |",
        f"| Correct | {n_correct:,} |",
        f"| **Accuracy** | **{accuracy*100:.2f}%** |",
        f"| 95% Wilson CI | [{ci_lo*100:.2f}%, {ci_hi*100:.2f}%] |",
        f"| Phase-3D training log | 71.27% |",
        f"| Phase-3D 16-image batch | 81.25% (13/16) |",
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
        row = f"| **{r}** | " + " | ".join(str(conf[r, c]) for c in range(10)) + " |"
        md.append(row)

    md += [
        "",
        "## Sanity Check",
        "",
        f"Expected range: 60%–80% (based on training-time test_acc 71.27% "
        f"and typical BinaryConnect ±5 pp variance).",
        "",
        f"Result {accuracy*100:.2f}% is **{'within' if EXPECTED_LO <= accuracy <= EXPECTED_HI else 'OUTSIDE'}** "
        f"the expected range.",
        "",
        f"*Eval time: {elapsed:.1f}s on CPU.*",
    ]

    with open(OUT_MD, "w") as fh:
        fh.write("\n".join(md) + "\n")
    print(f"Saved MD  → {OUT_MD}")
    print("\nDone. Do NOT commit — review first.")


if __name__ == "__main__":
    main()
