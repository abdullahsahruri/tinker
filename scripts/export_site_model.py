#!/usr/bin/env python3
"""Export the deployed 14x14 grouped BNN + sample MNIST digits for the website.

Writes site/model.json, which site/bnn.js loads to run the exact integer
network that the SoC firmware runs (same preprocessing, thresholds, and
layer-2 logit formula as scripts/bnn_reference.py).

Usage:
    python scripts/export_site_model.py [--n-samples 120]
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def bits(row: np.ndarray) -> str:
    """±1 vector → '0'/'1' string (+1 → '1'), index 0 first."""
    return "".join("1" if v > 0 else "0" for v in row)


def load_idx_images(path: Path) -> np.ndarray:
    with gzip.open(path, "rb") as fh:
        buf = fh.read()
    n = int.from_bytes(buf[4:8], "big")
    return np.frombuffer(buf, dtype=np.uint8, offset=16).reshape(n, 28, 28)


def load_idx_labels(path: Path) -> np.ndarray:
    with gzip.open(path, "rb") as fh:
        buf = fh.read()
    return np.frombuffer(buf, dtype=np.uint8, offset=8)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--weights", default=str(ROOT / "data/bnn_weights_14x14.npz"))
    p.add_argument("--mnist-dir", default=str(ROOT / "data/mnist"))
    p.add_argument("--n-samples", type=int, default=120)
    p.add_argument("--out", default=str(ROOT / "site/model.json"))
    args = p.parse_args()

    d = np.load(args.weights)
    images = load_idx_images(Path(args.mnist_dir) / "t10k-images-idx3-ubyte.gz")
    labels = load_idx_labels(Path(args.mnist_dir) / "t10k-labels-idx1-ubyte.gz")
    n = args.n_samples

    model = {
        "source": "data/bnn_weights_14x14.npz (deployed TINKER network)",
        "l1_w": [bits(r) for r in d["layer1_weights"]],          # 64 × 49
        "l1_t": [int(t) for t in d["layer1_thresholds"]],         # 64
        "l2_w": [bits(r) for r in d["layer2_weights"]],          # 10 × 64
        "l2_bias": [int(b) for b in d["layer2_bias"]],            # 10
        "samples": {
            "note": f"first {n} images of the MNIST test split",
            "images_b64": base64.b64encode(images[:n].tobytes()).decode(),
            "labels": [int(v) for v in labels[:n]],
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(model, separators=(",", ":")))
    print(f"wrote {out} ({out.stat().st_size / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
