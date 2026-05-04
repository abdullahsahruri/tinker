"""Grouped-BNN float-ceiling diagnostic.

Tests whether the tile-compatible grouped architecture
  4 branches × Linear(49→16, ReLU) → concat(64) → Linear(64→10)
has a float ceiling that justifies implementing the 14×14 grouped BNN.

Preprocessing: 28×28 → adaptive_avg_pool 14×14 → four 7×7 quadrants,
each independently binarized with v4 strict > per-quadrant median.
This matches the deployment contract: the tile sees one 49-bit quadrant
per evaluation, exactly as in the current 7×7 firmware.

The fully-connected 196→64→10 control uses the same per-quadrant
binarized input (concatenated flat) to show what full connectivity
would add over the grouped structure.
"""
from __future__ import annotations
import gzip
import json
import struct
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset

ROOT      = Path(__file__).parent.parent
MNIST_DIR = ROOT / "data" / "mnist"
OUT_DIR   = ROOT / "results" / "phase4_prep"
OUT_JSON  = OUT_DIR / "grouped_diagnostic.json"

EPOCHS = 5
BATCH  = 128
LR     = 1e-3
REPORT = (1, 3, 5)


# ---------------------------------------------------------------------------
# MNIST loader
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


def _load_gz(path: Path) -> np.ndarray:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as fh:
        return _idx_parse(fh.read())


def load_mnist(mnist_dir: Path):
    def find(prefix: str) -> np.ndarray:
        for suf in (".gz", ""):
            p = mnist_dir / (prefix + suf)
            if p.exists():
                return _load_gz(p)
        raise FileNotFoundError(prefix)
    return (find("train-images-idx3-ubyte"), find("train-labels-idx1-ubyte"),
            find("t10k-images-idx3-ubyte"),  find("t10k-labels-idx1-ubyte"))


# ---------------------------------------------------------------------------
# Preprocessing — grouped quadrant binarization
# ---------------------------------------------------------------------------
def preprocess_grouped(images: np.ndarray) -> np.ndarray:
    """(N,28,28) uint8 → (N, 196) float32 ±1.

    14×14 adaptive avg-pool → four 7×7 quadrants → per-quadrant strict>median.
    Output layout: [q0_flat(49) | q1_flat(49) | q2_flat(49) | q3_flat(49)].

    Per-quadrant independent medians ensure each branch self-normalises over
    its own 49-cell local context — same logic as Phase-3D's per-image median
    but scoped to the quadrant. Enables fair comparison with the grouped model
    that sees exactly one quadrant per tile evaluation.
    """
    f = torch.from_numpy(images.astype(np.float32) / 255.0).unsqueeze(1)
    p14 = F.adaptive_avg_pool2d(f, (14, 14)).squeeze(1).numpy()   # (N,14,14)

    # Extract 4 non-overlapping 7×7 quadrants.
    quads = [
        p14[:, 0:7,  0:7 ].reshape(-1, 49),   # q0: top-left
        p14[:, 0:7,  7:14].reshape(-1, 49),   # q1: top-right
        p14[:, 7:14, 0:7 ].reshape(-1, 49),   # q2: bottom-left
        p14[:, 7:14, 7:14].reshape(-1, 49),   # q3: bottom-right
    ]

    # Per-quadrant strict > median binarization (v4, scoped to 49 cells).
    bits = []
    for q in quads:
        thr = np.median(q, axis=1, keepdims=True)   # (N,1) — 24th sorted of 49
        bits.append(np.where(q > thr, 1.0, -1.0).astype(np.float32))

    # Sanity: each quadrant should have ~49% +1 bits (24/49 above-median cells).
    return np.concatenate(bits, axis=1)              # (N, 196)


def quad_stats(x196: np.ndarray) -> list[float]:
    """Return per-quadrant +1 fraction for a batch of preprocessed features."""
    return [(x196[:, k*49:(k+1)*49] > 0).mean() for k in range(4)]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class GroupedMLP(nn.Module):
    """Tile-compatible grouped architecture.

    4 branches: each branch sees one 7×7 quadrant (49 ±1 inputs → 16 hidden).
    Hidden vectors concatenated → 64-dim → 10 classes.

    At BNN deployment: each branch maps to one tile evaluation
    (same format as Phase-3D's HIDDEN_BATCHES loop, one batch per quadrant).
    """
    def __init__(self):
        super().__init__()
        self.branches = nn.ModuleList([
            nn.Sequential(nn.Linear(49, 16), nn.BatchNorm1d(16), nn.ReLU())
            for _ in range(4)
        ])
        self.out = nn.Linear(64, 10)

    def forward(self, x: torch.Tensor) -> torch.Tensor:   # x: (B, 196)
        parts   = [x[:, k*49:(k+1)*49] for k in range(4)]
        hiddens = [branch(p) for branch, p in zip(self.branches, parts)]
        return self.out(torch.cat(hiddens, dim=1))


class FullyConnectedMLP(nn.Module):
    """Fully-connected 196→64→10 control (tile-incompatible, accuracy ceiling)."""
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(196, 64), nn.BatchNorm1d(64), nn.ReLU(),
            nn.Linear(64, 10),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
def make_loaders(x: np.ndarray, y: np.ndarray,
                 x_te: np.ndarray, y_te: np.ndarray):
    tx    = torch.from_numpy(x).float()
    ty    = torch.from_numpy(y.astype(np.int64))
    tx_te = torch.from_numpy(x_te).float()
    ty_te = torch.from_numpy(y_te.astype(np.int64))
    return (DataLoader(TensorDataset(tx, ty),       batch_size=BATCH, shuffle=True),
            DataLoader(TensorDataset(tx_te, ty_te), batch_size=512,   shuffle=False))


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
        elif isinstance(m, (nn.BatchNorm1d,)):
            nn.init.ones_(m.weight); nn.init.zeros_(m.bias)

    opt = torch.optim.Adam(model.parameters(), lr=LR)
    train_dl, test_dl = make_loaders(x_tr, y_tr, x_te, y_te)
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
# Decision
# ---------------------------------------------------------------------------
def decide(grouped_e5: float) -> tuple[str, str]:
    if grouped_e5 >= 0.90:
        return ">=90%", (
            "PROCEED — grouped BNN expected at 82-86%. "
            "Comfortable headline; implementation justified."
        )
    if grouped_e5 >= 0.86:
        return "86-89%", (
            "MARGINAL — grouped BNN at 78-82%. "
            "Modest gain over current 71%; discuss before committing."
        )
    if grouped_e5 >= 0.82:
        return "82-85%", (
            "LIKELY NOT WORTH IT — grouped BNN at 73-77%. "
            "Small delta over current 71%; implementation cost high."
        )
    return "<=81%", (
        "DECLINE — grouped architecture gains nothing over current 7×7. "
        "Accept 71% and reframe paper around SoC/energy contribution."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("Grouped BNN ceiling diagnostic")
    print(f"MNIST : {MNIST_DIR}")
    print(f"Out   : {OUT_JSON}")

    print("\nLoading MNIST …", end=" ", flush=True)
    t0 = time.time()
    x_tr_raw, y_tr, x_te_raw, y_te = load_mnist(MNIST_DIR)
    print(f"{time.time()-t0:.1f}s")

    print("Preprocessing grouped (per-quadrant median) …", end=" ", flush=True)
    t0 = time.time()
    x_tr = preprocess_grouped(x_tr_raw)
    x_te = preprocess_grouped(x_te_raw)
    print(f"{time.time()-t0:.1f}s")

    # Sanity: each quadrant should have ~49% +1 fraction.
    fracs = quad_stats(x_tr)
    print(f"  per-quadrant +1 fractions: " +
          "  ".join(f"q{k}={f:.3f}" for k, f in enumerate(fracs)))
    if any(abs(f - 0.49) > 0.05 for f in fracs):
        print("  WARNING: quadrant +1 fraction deviates from expected ~49% — "
              "check preprocessing")
    else:
        print("  ✓ all four quadrants near 49% as expected for strict>median on 49 cells")

    # --- Grouped model ---
    r_grouped = train_run(
        "GROUPED  4×(49→16, BN, ReLU) → concat(64) → 10",
        GroupedMLP(), x_tr, y_tr, x_te, y_te)

    # --- Fully-connected control (same per-quadrant-binarized input, full connectivity) ---
    r_fc = train_run(
        "FULLY-CONNECTED  196→64→10  [tile-incompatible, upper bound]",
        FullyConnectedMLP(), x_tr, y_tr, x_te, y_te)

    # --- Summary table ---
    W = 50
    print(f"\n{'='*65}")
    print("COMPARISON TABLE — float MLP ceiling (epoch 5)")
    print(f"{'='*65}")
    print(f"  {'Architecture':<{W}} | ep1     ep3     ep5")
    print(f"  {'-'*W}-+----------------------")
    known = [
        ("49→64→10      (7×7 binary, current)         [known]",
         [0.7897, 0.8095, 0.8188]),
        ("196→64→10     (14×14 full-connect, blocked) [known]",
         [0.9090, 0.9371, 0.9450]),
    ]
    for name, accs in known:
        print(f"  {name:<{W}} | {accs[0]:.4f}  {accs[1]:.4f}  {accs[2]:.4f}")
    new = [
        ("4×(49→16)→64→10  (grouped, tile-compatible)",   r_grouped),
        ("196→64→10     (full-connect, per-quad preproc)", r_fc),
    ]
    for name, r in new:
        print(f"  {name:<{W}} | {r[1]:.4f}  {r[3]:.4f}  {r[5]:.4f}")
    print(f"  {'-'*W}-+----------------------")
    print(f"  {'Current BNN (Phase-3D, integer weights)':<{W}} | "
          f"                71.12%")

    grouped_e5 = r_grouped[5]
    band, recommendation = decide(grouped_e5)

    print(f"\n{'='*65}")
    print("DECISION")
    print(f"{'='*65}")
    print(f"  Grouped float ceiling (epoch 5): {grouped_e5*100:.2f}%")
    print(f"  Fully-connected ceiling (same preproc): {r_fc[5]*100:.2f}%")
    connectivity_gap = r_fc[5] - grouped_e5
    print(f"  Connectivity gap (FC minus grouped): {connectivity_gap*100:+.2f} pp")
    print(f"  Band: {band}")
    print(f"  >> {recommendation}")
    print(f"{'='*65}")

    # --- Save JSON ---
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "phase": "4_diagnostic_grouped",
        "description": "Grouped 4×(49→16) float-MLP ceiling vs fully-connected control",
        "preprocessing": {
            "pool": "F.adaptive_avg_pool2d(28x28, (14,14))",
            "quadrants": ["rows[0:7,cols[0:7]", "rows[0:7],cols[7:14]",
                          "rows[7:14],cols[0:7]", "rows[7:14],cols[7:14]"],
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
            "note": "uses same per-quadrant binarization as grouped; "
                    "connectivity gap shows cost of tile constraint",
        },
        "known_baselines": {
            "current_7x7_bnn_float_ceiling": 0.8188,
            "current_7x7_bnn_integer": 0.7112,
            "full_14x14_fc_float_ceiling_global_median": 0.9450,
        },
        "decision": {
            "grouped_epoch5_acc": grouped_e5,
            "connectivity_gap_pp": round(connectivity_gap * 100, 2),
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
