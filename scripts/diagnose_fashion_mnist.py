"""Fashion-MNIST diagnostic for the grouped 4×(49→16) architecture.

Tests whether the tile-compatible grouped architecture works on Fashion-MNIST,
where clothing features may require cross-quadrant connectivity unavailable
to the block-diagonal hidden layer.

Same preprocessing as Phase 4.5 grouped MNIST:
  28×28 → adaptive_avg_pool2d(14,14) → four 7×7 quadrants →
  strict > per-quadrant median binarization → ±1

Two float MLPs trained for 5 epochs each:
  Config 1 (tile-compatible): 4×(49→16,BN,ReLU) → concat(64) → 10
  Config 2 (upper bound):     196→64→10 (fully-connected, tile-incompatible)

MNIST reference values loaded from results/phase4_prep/grouped_diagnostic.json.
"""
from __future__ import annotations
import gzip
import json
import struct
import time
import urllib.request
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

ROOT       = Path(__file__).parent.parent
DATA_DIR   = ROOT / "data" / "fashion_mnist"
OUT_DIR    = ROOT / "results" / "phase4_prep"
OUT_JSON   = OUT_DIR / "fashion_mnist_diagnostic.json"

EPOCHS = 5
BATCH  = 128
LR     = 1e-3
REPORT = (1, 3, 5)

# Fashion-MNIST class names (for context in output).
CLASS_NAMES = [
    "T-shirt/top", "Trouser", "Pullover", "Dress", "Coat",
    "Sandal", "Shirt", "Sneaker", "Bag", "Ankle boot",
]


# ---------------------------------------------------------------------------
# Fashion-MNIST loader — tries torchvision first, falls back to direct download.
# ---------------------------------------------------------------------------
_FMNIST_BASE = "http://fashion-mnist.s3-website.eu-west-1.amazonaws.com/"
_FMNIST_FILES = {
    "train_images": "train-images-idx3-ubyte.gz",
    "train_labels": "train-labels-idx1-ubyte.gz",
    "test_images":  "t10k-images-idx3-ubyte.gz",
    "test_labels":  "t10k-labels-idx1-ubyte.gz",
}


def _idx_parse(buf: bytes) -> np.ndarray:
    magic, n = struct.unpack(">II", buf[:8])
    if magic == 2049:
        return np.frombuffer(buf, dtype=np.uint8, offset=8, count=n)
    if magic == 2051:
        r, c = struct.unpack(">II", buf[8:16])
        return np.frombuffer(buf, dtype=np.uint8, offset=16,
                             count=n * r * c).reshape(n, r, c)
    raise ValueError(f"unknown IDX magic 0x{magic:08x}")


def _load_gz(path: Path) -> np.ndarray:
    with gzip.open(path, "rb") as fh:
        return _idx_parse(fh.read())


def _download_fallback(data_dir: Path) -> dict[str, np.ndarray]:
    data_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, np.ndarray] = {}
    for key, name in _FMNIST_FILES.items():
        local = data_dir / name
        if not local.exists():
            url = _FMNIST_BASE + name
            print(f"  downloading {name} from Fashion-MNIST S3 …")
            urllib.request.urlretrieve(url, str(local))
        out[key] = _load_gz(local)
    return out


def load_fashion_mnist(data_dir: Path):
    """Return (train_images, train_labels, test_images, test_labels) uint8 arrays."""
    try:
        from torchvision import datasets  # type: ignore
        train = datasets.FashionMNIST(str(data_dir), train=True,  download=True)
        test  = datasets.FashionMNIST(str(data_dir), train=False, download=True)

        def to_arr(ds):
            xs = np.stack([np.asarray(ds[i][0]) for i in range(len(ds))])
            ys = np.asarray([ds[i][1] for i in range(len(ds))], dtype=np.uint8)
            return xs.astype(np.uint8), ys

        return (*to_arr(train), *to_arr(test))
    except Exception as e:
        print(f"  torchvision unavailable ({e!r}); falling back to direct download")
        d = _download_fallback(data_dir)
        return (d["train_images"], d["train_labels"],
                d["test_images"],  d["test_labels"])


# ---------------------------------------------------------------------------
# Preprocessing — identical to Phase 4.5 grouped MNIST.
# ---------------------------------------------------------------------------
def preprocess_grouped(images: np.ndarray) -> np.ndarray:
    """(N,28,28) uint8 → (N,196) float32 ±1, per-quadrant strict>median."""
    f   = torch.from_numpy(images.astype(np.float32) / 255.0).unsqueeze(1)
    p14 = F.adaptive_avg_pool2d(f, (14, 14)).squeeze(1).numpy()   # (N,14,14)
    quads = [
        p14[:, 0:7,  0:7 ].reshape(-1, 49),
        p14[:, 0:7,  7:14].reshape(-1, 49),
        p14[:, 7:14, 0:7 ].reshape(-1, 49),
        p14[:, 7:14, 7:14].reshape(-1, 49),
    ]
    bits = []
    for q in quads:
        thr = np.median(q, axis=1, keepdims=True)
        bits.append(np.where(q > thr, 1.0, -1.0).astype(np.float32))
    return np.concatenate(bits, axis=1)   # (N,196)


def quad_stats(x196: np.ndarray) -> list[float]:
    return [(x196[:, k * 49:(k + 1) * 49] > 0).mean() for k in range(4)]


# ---------------------------------------------------------------------------
# Models.
# ---------------------------------------------------------------------------
class GroupedMLP(nn.Module):
    """Tile-compatible: 4 branches × (49→16, BN, ReLU) → concat(64) → 10."""
    def __init__(self):
        super().__init__()
        self.branches = nn.ModuleList([
            nn.Sequential(nn.Linear(49, 16), nn.BatchNorm1d(16), nn.ReLU())
            for _ in range(4)
        ])
        self.out = nn.Linear(64, 10)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        parts   = [x[:, k * 49:(k + 1) * 49] for k in range(4)]
        hiddens = [branch(p) for branch, p in zip(self.branches, parts)]
        return self.out(torch.cat(hiddens, dim=1))


class FullyConnectedMLP(nn.Module):
    """Upper bound: 196→64→10 (tile-incompatible)."""
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(196, 64), nn.BatchNorm1d(64), nn.ReLU(),
            nn.Linear(64, 10),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


# ---------------------------------------------------------------------------
# Training.
# ---------------------------------------------------------------------------
def evaluate(model: nn.Module, loader: DataLoader) -> float:
    model.eval()
    ok = tot = 0
    with torch.no_grad():
        for xb, yb in loader:
            ok  += (model(xb).argmax(1) == yb).sum().item()
            tot += yb.size(0)
    return ok / tot


def train_run(label: str, model: nn.Module,
              x_tr: np.ndarray, y_tr: np.ndarray,
              x_te: np.ndarray, y_te: np.ndarray) -> dict[int, float]:
    n_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"\n{'='*60}")
    print(f"{label}  (params={n_params:,})")
    print(f"{'='*60}")

    torch.manual_seed(2026)
    for m in model.modules():
        if isinstance(m, nn.Linear):
            nn.init.kaiming_uniform_(m.weight, nonlinearity="relu")
            if m.bias is not None:
                nn.init.zeros_(m.bias)
        elif isinstance(m, nn.BatchNorm1d):
            nn.init.ones_(m.weight)
            nn.init.zeros_(m.bias)

    opt = torch.optim.Adam(model.parameters(), lr=LR)
    tx    = torch.from_numpy(x_tr).float()
    ty    = torch.from_numpy(y_tr.astype(np.int64))
    tx_te = torch.from_numpy(x_te).float()
    ty_te = torch.from_numpy(y_te.astype(np.int64))
    train_dl = DataLoader(TensorDataset(tx, ty),       batch_size=BATCH, shuffle=True)
    test_dl  = DataLoader(TensorDataset(tx_te, ty_te), batch_size=512,   shuffle=False)

    results: dict[int, float] = {}
    t0 = time.time()
    for epoch in range(1, EPOCHS + 1):
        model.train()
        run_loss = ok = n = 0
        for xb, yb in train_dl:
            logits = model(xb)
            loss   = F.cross_entropy(logits, yb)
            opt.zero_grad(); loss.backward(); opt.step()
            run_loss += loss.item() * yb.size(0)
            ok += (logits.argmax(1) == yb).sum().item()
            n  += yb.size(0)
        test_acc = evaluate(model, test_dl)
        print(f"  ep {epoch}/{EPOCHS}  loss={run_loss/n:.4f}  "
              f"train={ok/n:.4f}  test={test_acc:.4f}  ({time.time()-t0:.0f}s)")
        if epoch in REPORT:
            results[epoch] = test_acc
    return results


# ---------------------------------------------------------------------------
# Decision.
# ---------------------------------------------------------------------------
def decide(grouped_e5: float, connectivity_gap_pp: float,
           mnist_gap_pp: float) -> tuple[str, str]:
    gap_delta = connectivity_gap_pp - mnist_gap_pp
    gap_note  = (f"Fashion-MNIST connectivity gap {connectivity_gap_pp:+.2f} pp "
                 f"vs MNIST {mnist_gap_pp:.2f} pp "
                 f"(delta {gap_delta:+.2f} pp — "
                 f"{'larger gap suggests clothing needs cross-quadrant features' if gap_delta > 2 else 'similar gap; quadrant locality holds'}).")
    if grouped_e5 >= 0.88:
        return ">=88%", (
            f"PROCEED — grouped BNN expected 78-84%, publishable for tiny BNNs. {gap_note}"
        )
    if grouped_e5 >= 0.84:
        return "84-87%", (
            f"MARGINAL — connectivity limitation costs more on Fashion-MNIST than MNIST. "
            f"Discuss before committing. {gap_note}"
        )
    if grouped_e5 >= 0.80:
        return "80-83%", (
            f"DECLINE — grouped architecture doesn't suit clothing classification. "
            f"Stay on MNIST and pursue accuracy via training improvements. {gap_note}"
        )
    return "<80%", (
        f"STRONGLY DECLINE — architecture mismatch. Stay on MNIST. {gap_note}"
    )


# ---------------------------------------------------------------------------
# Main.
# ---------------------------------------------------------------------------
def main() -> None:
    print("Fashion-MNIST grouped-BNN ceiling diagnostic")
    print(f"Data  : {DATA_DIR}")
    print(f"Out   : {OUT_JSON}")

    # Load MNIST reference values.
    mnist_ref: dict = {}
    if (p := ROOT / "results" / "phase4_prep" / "grouped_diagnostic.json").exists():
        with open(p) as fh:
            d = json.load(fh)
        mnist_ref = {
            "grouped_e5":         d["grouped_4x49_16"]["epoch5_acc"],
            "grouped_epochs":     d["grouped_4x49_16"]["epoch_accuracies"],
            "fc_e5":              d["fully_connected_196_64_10"]["epoch5_acc"],
            "fc_epochs":          d["fully_connected_196_64_10"]["epoch_accuracies"],
            "connectivity_gap_pp": d["decision"]["connectivity_gap_pp"],
        }
        print(f"\nMNIST reference loaded: grouped={mnist_ref['grouped_e5']:.4f}  "
              f"FC={mnist_ref['fc_e5']:.4f}  gap={mnist_ref['connectivity_gap_pp']:.2f} pp")
    else:
        print("  (grouped_diagnostic.json not found; MNIST reference unavailable)")
        mnist_ref = {"grouped_e5": None, "fc_e5": None, "connectivity_gap_pp": None,
                     "grouped_epochs": {}, "fc_epochs": {}}

    print("\nLoading Fashion-MNIST …", end=" ", flush=True)
    t0 = time.time()
    x_tr_raw, y_tr, x_te_raw, y_te = load_fashion_mnist(DATA_DIR)
    print(f"{time.time()-t0:.1f}s  "
          f"train={x_tr_raw.shape}  test={x_te_raw.shape}")

    print("Preprocessing (per-quadrant median) …", end=" ", flush=True)
    t0 = time.time()
    x_tr = preprocess_grouped(x_tr_raw)
    x_te = preprocess_grouped(x_te_raw)
    print(f"{time.time()-t0:.1f}s")

    fracs = quad_stats(x_tr)
    print(f"  per-quadrant +1 fractions: " +
          "  ".join(f"q{k}={f:.3f}" for k, f in enumerate(fracs)))

    # --- Grouped model ---
    r_grouped = train_run(
        "GROUPED  4×(49→16, BN, ReLU) → concat(64) → 10  [tile-compatible]",
        GroupedMLP(), x_tr, y_tr, x_te, y_te)

    # --- Fully-connected control ---
    r_fc = train_run(
        "FULLY-CONNECTED  196→64→10  [tile-incompatible, upper bound]",
        FullyConnectedMLP(), x_tr, y_tr, x_te, y_te)

    # --- Comparison table ---
    W = 52
    print(f"\n{'='*70}")
    print("COMPARISON TABLE — float MLP ceiling (epoch 5)")
    print(f"{'='*70}")
    print(f"  {'Architecture':<{W}} | MNIST   Fashion")
    print(f"  {'-'*W}-+-----------------")

    def acc_str(d: dict | None, key: str) -> str:
        if d is None or d.get(key) is None:
            return " n/a  "
        return f"{d[key]:.4f}"

    rows = [
        ("4×(49→16)→64→10  [tile-compatible]",
         acc_str(mnist_ref, "grouped_e5"), f"{r_grouped[5]:.4f}"),
        ("196→64→10  [fully-connected, upper bound]",
         acc_str(mnist_ref, "fc_e5"),      f"{r_fc[5]:.4f}"),
    ]
    for name, m_acc, f_acc in rows:
        print(f"  {name:<{W}} | {m_acc}  {f_acc}")
    print(f"  {'-'*W}-+-----------------")
    print(f"  {'Connectivity gap (FC minus grouped)':<{W}} | "
          f"{mnist_ref.get('connectivity_gap_pp', float('nan')):+5.2f} pp  "
          f"{(r_fc[5] - r_grouped[5])*100:+5.2f} pp")

    grouped_e5          = r_grouped[5]
    connectivity_gap_pp = (r_fc[5] - r_grouped[5]) * 100.0
    mnist_gap_pp        = float(mnist_ref.get("connectivity_gap_pp") or 0.87)
    band, recommendation = decide(grouped_e5, connectivity_gap_pp, mnist_gap_pp)

    print(f"\n{'='*70}")
    print("DECISION")
    print(f"{'='*70}")
    print(f"  Grouped float ceiling (epoch 5): {grouped_e5*100:.2f}%")
    print(f"  FC upper bound (epoch 5):         {r_fc[5]*100:.2f}%")
    print(f"  Connectivity gap:                 {connectivity_gap_pp:+.2f} pp "
          f"(MNIST was {mnist_gap_pp:.2f} pp)")
    print(f"  Band: {band}")
    print(f"  >> {recommendation}")
    print(f"{'='*70}")

    # --- Save JSON ---
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "phase": "4_diagnostic_fashion_mnist",
        "description": "Grouped 4×(49→16) float ceiling on Fashion-MNIST vs FC upper bound",
        "preprocessing": {
            "pool": "F.adaptive_avg_pool2d(28x28, (14,14))",
            "binarization": "strict > per-quadrant-median (49 cells each)",
            "train_plus1_fractions_per_quadrant": fracs,
        },
        "grouped_4x49_16": {
            "arch": "4×Linear(49→16,BN,ReLU) → concat(64) → Linear(64,10)",
            "tile_compatible": True,
            "tile_evaluations_per_image": 4,
            "epoch_accuracies": {str(e): r_grouped[e] for e in REPORT},
            "epoch5_acc": r_grouped[5],
        },
        "fully_connected_196_64_10": {
            "arch": "Linear(196,64,BN,ReLU) → Linear(64,10)",
            "tile_compatible": False,
            "epoch_accuracies": {str(e): r_fc[e] for e in REPORT},
            "epoch5_acc": r_fc[5],
        },
        "mnist_reference": {
            "grouped_epoch5_acc": mnist_ref.get("grouped_e5"),
            "fc_epoch5_acc":      mnist_ref.get("fc_e5"),
            "connectivity_gap_pp": mnist_ref.get("connectivity_gap_pp"),
        },
        "decision": {
            "grouped_epoch5_acc":       grouped_e5,
            "fc_epoch5_acc":            r_fc[5],
            "connectivity_gap_pp":      round(connectivity_gap_pp, 2),
            "mnist_connectivity_gap_pp": mnist_gap_pp,
            "gap_delta_pp":             round(connectivity_gap_pp - mnist_gap_pp, 2),
            "band": band,
            "recommendation": recommendation,
        },
    }
    with open(OUT_JSON, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nSaved → {OUT_JSON}")
    print("Done. Do NOT commit.")


if __name__ == "__main__":
    main()
