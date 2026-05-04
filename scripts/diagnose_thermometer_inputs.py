"""Float-MLP ceiling diagnostic: 6-configuration design-space sweep.

Configs
-------
A  49-bit  v4-binary   7×7   49→64→10          prior run (cached from JSON)
B  147-bit thermometer 7×7   147→64→10         prior run (cached, degenerate encoding)
C  64-bit  binary      8×8   64→64→10          spatial resolution +1 step
D  196-bit binary     14×14  196→64→10         spatial resolution +2 steps
E  49-bit  v4-binary   7×7   49→64→64→10       depth: does a second hidden layer help?
F  49-bit  v4-binary   7×7   conv(1→16,3×3)    spatial structure: conv preamble on 7×7

Configs A-B are loaded from the output JSON if it exists (skips re-training).
Configs C-F are always trained fresh.
"""
from __future__ import annotations
import gzip
import json
import struct
import sys
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
OUT_JSON  = OUT_DIR / "thermometer_diagnostic.json"

EPOCHS = 5
BATCH  = 128
LR     = 1e-3
REPORT = (1, 3, 5)

CONTROL_EXPECTED_LO = 0.77
CONTROL_EXPECTED_HI = 0.84


# ---------------------------------------------------------------------------
# MNIST loader
# ---------------------------------------------------------------------------
def _idx_parse(buf: bytes) -> np.ndarray:
    magic, n_items = struct.unpack(">II", buf[:8])
    if magic == 2049:
        return np.frombuffer(buf, dtype=np.uint8, offset=8, count=n_items)
    if magic == 2051:
        rows, cols = struct.unpack(">II", buf[8:16])
        return np.frombuffer(buf, dtype=np.uint8, offset=16,
                             count=n_items * rows * cols).reshape(n_items, rows, cols)
    raise ValueError(f"unknown IDX magic 0x{magic:08x}")


def _load_gz(path: Path) -> np.ndarray:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as fh:
        return _idx_parse(fh.read())


def load_mnist(mnist_dir: Path):
    def find(prefix: str) -> np.ndarray:
        for suffix in (".gz", ""):
            p = mnist_dir / (prefix + suffix)
            if p.exists():
                return _load_gz(p)
        raise FileNotFoundError(f"{prefix}[.gz] not found in {mnist_dir}")
    return (find("train-images-idx3-ubyte"), find("train-labels-idx1-ubyte"),
            find("t10k-images-idx3-ubyte"),  find("t10k-labels-idx1-ubyte"))


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------
def pool_adaptive(images: np.ndarray, grid: int) -> np.ndarray:
    """(N,28,28) uint8 → (N, grid²) float32 in [0,1] via adaptive_avg_pool2d."""
    f = torch.from_numpy(images.astype(np.float32) / 255.0).unsqueeze(1)
    p = F.adaptive_avg_pool2d(f, (grid, grid))
    return p.squeeze(1).reshape(len(images), -1).numpy()


def preprocess_binary(images: np.ndarray, grid: int) -> np.ndarray:
    """v4 strict->median binarization at any grid size → ±1 float32."""
    pooled = pool_adaptive(images, grid)
    thr = np.median(pooled, axis=1, keepdims=True)
    return np.where(pooled > thr, 1.0, -1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class FloatMLP(nn.Module):
    """Single hidden layer: in → 64 → BN → ReLU → 10."""
    def __init__(self, in_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, 64), nn.BatchNorm1d(64), nn.ReLU(),
            nn.Linear(64, 10),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class FloatMLP2H(nn.Module):
    """Two hidden layers: in → 64 → BN → ReLU → 64 → BN → ReLU → 10."""
    def __init__(self, in_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, 64), nn.BatchNorm1d(64), nn.ReLU(),
            nn.Linear(64, 64),     nn.BatchNorm1d(64), nn.ReLU(),
            nn.Linear(64, 10),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class FloatConvMLP(nn.Module):
    """Conv preamble: reshape (B,g²) → (B,1,g,g) → Conv(16,3×3) → BN → ReLU → Linear(16g²,10)."""
    def __init__(self, grid: int = 7, channels: int = 16):
        super().__init__()
        self.grid = grid
        self.conv = nn.Conv2d(1, channels, kernel_size=3, padding=1)
        self.bn   = nn.BatchNorm2d(channels)
        self.fc   = nn.Linear(channels * grid * grid, 10)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b = x.size(0)
        h = x.view(b, 1, self.grid, self.grid)
        h = F.relu(self.bn(self.conv(h)))
        return self.fc(h.view(b, -1))


# ---------------------------------------------------------------------------
# Training + evaluation
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
    correct = total = 0
    with torch.no_grad():
        for xb, yb in loader:
            pred = model(xb).argmax(dim=1)
            correct += (pred == yb).sum().item()
            total   += yb.size(0)
    return correct / total


def train_and_eval(label: str, model: nn.Module,
                   x_tr: np.ndarray, y_tr: np.ndarray,
                   x_te: np.ndarray, y_te: np.ndarray) -> dict[int, float]:
    in_dim    = x_tr.shape[1]
    n_params  = sum(p.numel() for p in model.parameters() if p.requires_grad)
    print(f"\n{'='*65}")
    print(f"Training: {label}")
    print(f"  input_dim={in_dim}  params={n_params:,}")
    print(f"{'='*65}")

    torch.manual_seed(2026)
    # Re-init weights with the fixed seed so every run is comparable.
    for m in model.modules():
        if isinstance(m, nn.Linear):
            nn.init.kaiming_uniform_(m.weight, nonlinearity="relu")
            if m.bias is not None:
                nn.init.zeros_(m.bias)
        elif isinstance(m, (nn.BatchNorm1d, nn.BatchNorm2d)):
            nn.init.ones_(m.weight)
            nn.init.zeros_(m.bias)
        elif isinstance(m, nn.Conv2d):
            nn.init.kaiming_uniform_(m.weight, nonlinearity="relu")
            if m.bias is not None:
                nn.init.zeros_(m.bias)

    opt = torch.optim.Adam(model.parameters(), lr=LR)
    train_dl, test_dl = make_loaders(x_tr, y_tr, x_te, y_te)
    results: dict[int, float] = {}
    t0 = time.time()

    for epoch in range(1, EPOCHS + 1):
        model.train()
        run_loss = tr_ok = tr_n = 0
        for xb, yb in train_dl:
            logits = model(xb)
            loss   = F.cross_entropy(logits, yb)
            opt.zero_grad(); loss.backward(); opt.step()
            run_loss += loss.item() * yb.size(0)
            tr_ok    += (logits.argmax(1) == yb).sum().item()
            tr_n     += yb.size(0)

        test_acc  = evaluate(model, test_dl)
        print(f"  ep {epoch}/{EPOCHS}  loss={run_loss/tr_n:.4f}  "
              f"train={tr_ok/tr_n:.4f}  test={test_acc:.4f}  "
              f"({time.time()-t0:.0f}s)")
        if epoch in REPORT:
            results[epoch] = test_acc

    return results


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------
def _fmt(r: dict[int, float] | None) -> str:
    if r is None:
        return "  n/a    n/a    n/a "
    return f"{r[1]:.4f}  {r[3]:.4f}  {r[5]:.4f}"


def print_decision(r8: dict, r14: dict, r_deep: dict, r_conv: dict) -> dict:
    e8   = r8[5];   e14  = r14[5]
    edp  = r_deep[5]; ecv = r_conv[5]

    findings = []
    if e8 >= 0.87:
        findings.append(
            "SPATIAL RESOLUTION is the binding constraint.\n"
            "  8×8 float ceiling ≥87% → expected BNN at ~80-84%.\n"
            "  Recommend: upgrade to 8×8 inputs (tile fits exactly, modest firmware change)."
        )
    elif e14 >= 0.90 and e8 < 0.84:
        findings.append(
            "Spatial helps but needs resolution BEYOND 8×8.\n"
            "  14×14 ≥90% but 8×8 <84% → 8-step grid doesn't unlock the gain.\n"
            "  Recommend: discuss whether 14×14 is feasible for the SoC."
        )
    else:
        findings.append(
            f"Spatial resolution alone does NOT break the ceiling "
            f"(8×8={e8*100:.1f}%, 14×14={e14*100:.1f}%)."
        )

    if edp >= 0.85:
        findings.append(
            f"NETWORK DEPTH is a binding constraint (49→64→64→10 = {edp*100:.1f}%).\n"
            "  Recommend: keep 49-bit inputs but add a second hidden layer."
        )
    else:
        findings.append(
            f"Adding depth (49→64→64→10 = {edp*100:.1f}%) does not break the ceiling."
        )

    if ecv >= 0.90:
        findings.append(
            f"SPATIAL-AWARE PROCESSING (conv preamble) = {ecv*100:.1f}% breaks the ceiling.\n"
            "  Note: a conv BNN is unlikely to fit cleanly in the current tile geometry;\n"
            "  discuss whether this changes the paper's story."
        )
    else:
        findings.append(
            f"Conv preamble ({ecv*100:.1f}%) does not break the ceiling."
        )

    all_e5 = [e8, e14, edp, ecv]
    if all(v < 0.85 for v in all_e5):
        findings.append(
            "OVERALL: NONE of the four new configs reaches 85%.\n"
            "  This is a fundamental ceiling of single-hidden-layer BNN-scale networks\n"
            "  on binarized MNIST at small spatial scale.\n"
            "  >> ACCEPT 71% and reframe the paper around the SoC/energy contribution."
        )
    else:
        best_v = max(all_e5)
        best_n = ["8×8 spatial", "14×14 spatial", "deeper arch", "conv preamble"][all_e5.index(best_v)]
        findings.append(
            f"Best new config: {best_n} at {best_v*100:.1f}% float ceiling."
        )

    print(f"\n{'='*65}")
    print("DECISION")
    print(f"{'='*65}")
    for i, f in enumerate(findings, 1):
        print(f"\n[{i}] {f}")
    print(f"\n{'='*65}")

    return {
        "e5_8x8":    e8,
        "e5_14x14":  e14,
        "e5_deeper": edp,
        "e5_conv":   ecv,
        "findings":  findings,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("Phase 4 diagnostic — spatial resolution + architecture sweep")
    print(f"MNIST dir : {MNIST_DIR}")
    print(f"Output    : {OUT_JSON}")

    # Load MNIST.
    print("\nLoading MNIST …", end=" ", flush=True)
    t0 = time.time()
    x_tr_raw, y_tr, x_te_raw, y_te = load_mnist(MNIST_DIR)
    print(f"{time.time()-t0:.1f}s  "
          f"(train {x_tr_raw.shape}, test {x_te_raw.shape})")

    # Load prior JSON results for configs A and B.
    prior: dict = {}
    if OUT_JSON.exists():
        with open(OUT_JSON) as fh:
            prior = json.load(fh)
        print("Prior results found — configs A (v4-binary) and B (thermometer) will be loaded from JSON.")

    def load_prior(key: str) -> dict[int, float] | None:
        if key in prior and "epoch_accuracies" in prior[key]:
            accs = {int(k): float(v) for k, v in prior[key]["epoch_accuracies"].items()}
            if set(accs.keys()) >= set(REPORT):
                print(f"  [cached] {key}: "
                      f"ep1={accs[1]:.4f}  ep3={accs[3]:.4f}  ep5={accs[5]:.4f}")
                return accs
        return None

    print("\n--- Configs A+B (prior results) ---")
    v4_res = load_prior("control_v4_binary")
    th_res = load_prior("thermometer")

    # If either is missing we need to train from scratch.
    need_v4_features = (v4_res is None) or True   # always need for configs E+F
    x_tr_v4 = x_te_v4 = None

    def ensure_v4():
        nonlocal x_tr_v4, x_te_v4
        if x_tr_v4 is None:
            print("Preprocessing 7×7 v4-binary …", end=" ", flush=True)
            t = time.time()
            x_tr_v4 = preprocess_binary(x_tr_raw, 7)
            x_te_v4 = preprocess_binary(x_te_raw, 7)
            frac = (x_tr_v4 > 0).mean()
            print(f"{time.time()-t:.1f}s  +1 fraction={frac:.3f}")

    if v4_res is None:
        ensure_v4()
        v4_res = train_and_eval(
            "A: 49-bit v4-binary  7×7  49→64→10  [control]",
            FloatMLP(49), x_tr_v4, y_tr, x_te_v4, y_te)
        ctrl_e5 = v4_res[5]
        if not (CONTROL_EXPECTED_LO <= ctrl_e5 <= CONTROL_EXPECTED_HI):
            print(f"\n!! CONTROL SANITY FAIL: {ctrl_e5:.4f} outside "
                  f"[{CONTROL_EXPECTED_LO:.0%},{CONTROL_EXPECTED_HI:.0%}] — halting.")
            sys.exit(1)

    if th_res is None:
        print("Preprocessing 7×7 thermometer …", end=" ", flush=True)
        t = time.time()
        pooled_tr = pool_adaptive(x_tr_raw, 7)
        pooled_te = pool_adaptive(x_te_raw, 7)
        # Thermometer: >=q25, >=q50, >=q75 (note: degenerate on MNIST, see notes)
        def therm(p):
            q25 = np.percentile(p, 25, axis=1, keepdims=True)
            q50 = np.percentile(p, 50, axis=1, keepdims=True)
            q75 = np.percentile(p, 75, axis=1, keepdims=True)
            return np.concatenate([(p >= q25), (p >= q50), (p >= q75)],
                                  axis=1).astype(np.float32)
        x_tr_th = therm(pooled_tr)
        x_te_th = therm(pooled_te)
        print(f"{time.time()-t:.1f}s")
        th_res = train_and_eval(
            "B: 147-bit thermometer  7×7  147→64→10  [degenerate]",
            FloatMLP(147), x_tr_th, y_tr, x_te_th, y_te)

    # --- Config C: 8×8 binary ---
    print("\n--- Config C: 8×8 binary ---")
    print("Preprocessing 8×8 binary …", end=" ", flush=True)
    t = time.time()
    x_tr_8 = preprocess_binary(x_tr_raw, 8)
    x_te_8 = preprocess_binary(x_te_raw, 8)
    frac_8 = (x_tr_8 > 0).mean()
    print(f"{time.time()-t:.1f}s  +1 fraction={frac_8:.3f}")
    r8 = train_and_eval(
        "C: 64-bit binary  8×8  64→64→10",
        FloatMLP(64), x_tr_8, y_tr, x_te_8, y_te)

    # --- Config D: 14×14 binary ---
    print("\n--- Config D: 14×14 binary ---")
    print("Preprocessing 14×14 binary …", end=" ", flush=True)
    t = time.time()
    x_tr_14 = preprocess_binary(x_tr_raw, 14)
    x_te_14 = preprocess_binary(x_te_raw, 14)
    frac_14 = (x_tr_14 > 0).mean()
    print(f"{time.time()-t:.1f}s  +1 fraction={frac_14:.3f}")
    r14 = train_and_eval(
        "D: 196-bit binary  14×14  196→64→10",
        FloatMLP(196), x_tr_14, y_tr, x_te_14, y_te)

    # --- Config E: 49-bit v4, deeper (49→64→64→10) ---
    print("\n--- Config E: 49-bit v4, deeper network ---")
    ensure_v4()
    r_deep = train_and_eval(
        "E: 49-bit v4-binary  7×7  49→64→64→10  [deeper]",
        FloatMLP2H(49), x_tr_v4, y_tr, x_te_v4, y_te)

    # --- Config F: 49-bit v4, conv preamble ---
    print("\n--- Config F: 49-bit v4, conv preamble ---")
    r_conv = train_and_eval(
        "F: 49-bit v4-binary  7×7  conv(1→16,3×3)→flatten→10",
        FloatConvMLP(grid=7, channels=16), x_tr_v4, y_tr, x_te_v4, y_te)

    # --- Summary table ---
    print(f"\n{'='*65}")
    print("FULL COMPARISON TABLE — float MLP ceiling (epochs 1, 3, 5)")
    print(f"{'='*65}")
    W = 46
    print(f"  {'Config':<{W}} | ep1     ep3     ep5")
    print(f"  {'-'*W}-+------------------------")
    rows = [
        ("A  49-bit v4-binary   7×7   49→64→10   [control]",   v4_res),
        ("B  147-bit thermometer 7×7  147→64→10  [degenerate]", th_res),
        ("C  64-bit binary       8×8   64→64→10",               r8),
        ("D  196-bit binary     14×14 196→64→10",               r14),
        ("E  49-bit v4-binary   7×7   49→64→64→10 [deeper]",    r_deep),
        ("F  49-bit v4-binary   7×7   conv preamble",           r_conv),
    ]
    for name, res in rows:
        print(f"  {name:<{W}} | {_fmt(res)}")
    print(f"  {'-'*W}-+------------------------")
    print(f"  {'Current BNN (v4-binary, integer weights)':<{W}} | "
          f"                71.12% (phase 3D)")

    # --- Decision ---
    decision = print_decision(r8, r14, r_deep, r_conv)

    # --- Save / append JSON ---
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    def res_entry(res, **extra):
        return {
            "epoch_accuracies": {str(e): res[e] for e in REPORT},
            "epoch5_acc": res[5],
            **extra,
        }

    out = dict(prior)   # carry forward prior fields unchanged
    out.update({
        "phase": "4_diagnostic",
        "description": "Float-MLP ceiling: 6-config spatial+architecture sweep",
        "control_v4_binary": res_entry(
            v4_res, input_dim=49, grid="7x7",
            expected_range=[CONTROL_EXPECTED_LO, CONTROL_EXPECTED_HI]),
        "thermometer": {
            **prior.get("thermometer", {}),
            "epoch_accuracies": {str(e): th_res[e] for e in REPORT},
            "epoch5_acc": th_res[5],
            "note": "degenerate — b0/b1 ≈1.0 due to MNIST zero-heavy background",
        },
        "binary_8x8": res_entry(
            r8, input_dim=64, grid="8x8", plus1_fraction=float(frac_8)),
        "binary_14x14": res_entry(
            r14, input_dim=196, grid="14x14", plus1_fraction=float(frac_14)),
        "deeper_49_64_64_10": res_entry(r_deep, input_dim=49, hidden_layers=2),
        "conv_preamble": res_entry(r_conv, input_dim=49, arch="conv(1→16,3×3)+flatten"),
        "decision": decision,
    })

    with open(OUT_JSON, "w") as fh:
        json.dump(out, fh, indent=2)
    print(f"\nSaved → {OUT_JSON}")
    print("Done. Do NOT commit — review first.")


if __name__ == "__main__":
    main()
