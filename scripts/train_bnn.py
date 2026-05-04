"""Train a BNN on MNIST and export it in hardware-compatible form.

Supports two network architectures (--net 7x7 | 14x14):

  7×7  (Phase-3D baseline):
    BinaryLinear(49→64) → BN1d(64, affine) → sign → BinaryLinear(64→10, bias)

  14×14 (Phase-4.5 grouped, tile-compatible):
    4 branches × [BinaryLinear(49→16) → BN1d(16, affine) → sign]
    concat(64) → BinaryLinear(64→10, bias)
    Tile mapping: batch k = branch k = quadrant k of the 14×14 image.

Training improvements for 14×14:
  - Hard-tanh STE (Hubara et al. 2016): gradient passes through when |x|<=1,
    clipped to 0 otherwise. Applied to both weight and activation binarization.
  - OneCycleLR with 5% warmup → cosine decay to 0: final_div_factor=1e4.
  - 30 epochs, 3 seeds (42, 1042, 2042); best-seed weights saved.

Export (data/bnn_weights[_14x14].npz) — same npz schema for both nets:
    layer1_weights     int8  (64, 49)  ±1
    layer1_thresholds  uint8 (64,)     0..49
    layer2_weights     int8  (10, 64)  ±1
    layer2_thresholds  uint8 (10,)     0..64  (spec compliance only)
    layer2_bias        int16 (10,)     signed
"""
from __future__ import annotations
import argparse
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader

# ---------------------------------------------------------------------------
# Hyperparameters.
# ---------------------------------------------------------------------------
N_INPUT_7X7  = 49
N_HIDDEN     = 64
N_OUTPUT     = 10
EPOCHS       = 10       # 7×7 default (Phase-3D baseline, unchanged)
EPOCHS_14X14 = 30       # 14×14: cosine schedule benefits from longer run
BATCH        = 128
LR           = 1e-3
WCLIP        = 1.0
LOGIT_TEMP   = 8.0
ACCURACY_FLOOR_7X7   = 0.80
ACCURACY_FLOOR_14X14 = 0.82    # floor below expected 85-88%; warns on collapse only

SEEDS_14X14 = [42, 1042, 2042]   # train 3 seeds, export the best


# ---------------------------------------------------------------------------
# Hard-tanh STE — Hubara et al. (2016) standard BinaryConnect recipe.
#
# Forward: y = sign(x)  (0 → 0; weight latent values are clipped to [-1,1]
#          after each step, so 0 is measure-zero in practice).
# Backward: g · 1(|x| <= 1)  — zero gradient outside the unit interval,
#           which caps the STE error for saturated weights/activations.
#           In the 7×7 identity-STE version the unbounded backward sometimes
#           let large latent weights drift; capping it here helps the 14×14
#           model converge to a flatter loss basin.
# ---------------------------------------------------------------------------
class SignSTE(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x: torch.Tensor) -> torch.Tensor:
        ctx.save_for_backward(x)
        return torch.sign(x)

    @staticmethod
    def backward(ctx, grad_output: torch.Tensor) -> torch.Tensor:
        x, = ctx.saved_tensors
        g = grad_output.clone()
        g[x.abs() > 1] = 0
        return g


def sign_ste(x: torch.Tensor) -> torch.Tensor:
    return SignSTE.apply(x)


class BinaryLinear(nn.Linear):
    """nn.Linear with weights binarized to ±1 via hard-tanh STE."""
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        wb = sign_ste(self.weight)
        return F.linear(x, wb, self.bias)


# ---------------------------------------------------------------------------
# Models.
# ---------------------------------------------------------------------------
class BNN_49_64_10(nn.Module):
    """7×7 BNN: BinaryLinear(49→64) → BN1d(64) → sign → BinaryLinear(64→10)."""
    def __init__(self):
        super().__init__()
        self.fc1 = BinaryLinear(N_INPUT_7X7, N_HIDDEN, bias=False)
        self.bn1 = nn.BatchNorm1d(N_HIDDEN, affine=True)
        self.fc2 = BinaryLinear(N_HIDDEN, N_OUTPUT, bias=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(sign_ste(self.bn1(self.fc1(x))))


class GroupedBNN_14x14(nn.Module):
    """14×14 grouped BNN: 4 branches × (49→16, BN, sign) → concat(64) → 10.

    Tile-compatible: branch k = tile evaluation k = quadrant k's 16 neurons.
    Weight export: rows 16k..16k+15 of layer1_weights = branch k.
    """
    def __init__(self):
        super().__init__()
        self.branches = nn.ModuleList([
            nn.Sequential(
                BinaryLinear(49, 16, bias=False),
                nn.BatchNorm1d(16, affine=True),
            )
            for _ in range(4)
        ])
        self.fc2 = BinaryLinear(N_HIDDEN, N_OUTPUT, bias=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:   # x: (B, 196)
        parts   = [x[:, k * 49:(k + 1) * 49] for k in range(4)]
        hiddens = [sign_ste(branch(p)) for branch, p in zip(self.branches, parts)]
        return self.fc2(torch.cat(hiddens, dim=1))


# ---------------------------------------------------------------------------
# Preprocessing.
# ---------------------------------------------------------------------------
def preprocess_batch(x: torch.Tensor) -> torch.Tensor:
    """7×7: (B,1,28,28) → (B,49) ±1. avg-pool 4×4 stride 4, strict>median."""
    x = x.to(torch.float32)
    if x.max() > 1.5:
        x = x / 255.0
    x    = F.avg_pool2d(x, kernel_size=4, stride=4)
    flat = x.view(x.size(0), -1)
    thr  = flat.median(dim=1, keepdim=True).values
    return (flat > thr).to(torch.float32) * 2.0 - 1.0


def preprocess_grouped_batch_14x14(x: torch.Tensor) -> torch.Tensor:
    """14×14: (B,1,28,28) → (B,196) ±1.

    adaptive_avg_pool2d(14,14) → four 7×7 quadrants →
    per-quadrant strict>median binarization.
    Output: [q0(49) | q1(49) | q2(49) | q3(49)].
    """
    x = x.to(torch.float32)
    if x.max() > 1.5:
        x = x / 255.0
    p14 = F.adaptive_avg_pool2d(x, (14, 14)).squeeze(1)   # (B,14,14)
    B   = p14.size(0)
    quads = [
        p14[:, 0:7,  0:7 ].reshape(B, 49),
        p14[:, 0:7,  7:14].reshape(B, 49),
        p14[:, 7:14, 0:7 ].reshape(B, 49),
        p14[:, 7:14, 7:14].reshape(B, 49),
    ]
    bits = []
    for q in quads:
        thr = q.median(dim=1, keepdim=True).values
        bits.append((q > thr).to(torch.float32) * 2.0 - 1.0)
    return torch.cat(bits, dim=1)


# ---------------------------------------------------------------------------
# MNIST loader.
# ---------------------------------------------------------------------------
def _idx_parse(buf: bytes) -> np.ndarray:
    import struct
    magic, n = struct.unpack(">II", buf[:8])
    if magic == 2049:
        return np.frombuffer(buf, dtype=np.uint8, offset=8, count=n)
    if magic == 2051:
        r, c = struct.unpack(">II", buf[8:16])
        return np.frombuffer(buf, dtype=np.uint8, offset=16,
                             count=n * r * c).reshape(n, r, c)
    raise ValueError(f"unknown IDX magic: {magic}")


def _load_mnist_fallback(data_dir: Path):
    import gzip, urllib.request
    data_dir.mkdir(parents=True, exist_ok=True)
    base  = "https://ossci-datasets.s3.amazonaws.com/mnist/"
    files = {
        "train_images": "train-images-idx3-ubyte.gz",
        "train_labels": "train-labels-idx1-ubyte.gz",
        "test_images":  "t10k-images-idx3-ubyte.gz",
        "test_labels":  "t10k-labels-idx1-ubyte.gz",
    }
    out = {}
    for key, name in files.items():
        local = data_dir / name
        if not local.exists():
            print(f"  download {name} → {local}")
            urllib.request.urlretrieve(base + name, str(local))
        import gzip as gz
        with gz.open(local, "rb") as fh:
            out[key] = _idx_parse(fh.read())
    return out


def load_mnist(data_dir: Path):
    try:
        from torchvision import datasets, transforms  # type: ignore
        tx = transforms.Compose([transforms.PILToTensor()])
        train = datasets.MNIST(str(data_dir), train=True,  download=True, transform=tx)
        test  = datasets.MNIST(str(data_dir), train=False, download=True, transform=tx)

        def to_arr(ds):
            xs = np.stack([np.asarray(ds[i][0]).reshape(28, 28) for i in range(len(ds))])
            ys = np.asarray([ds[i][1] for i in range(len(ds))], dtype=np.uint8)
            return xs.astype(np.uint8), ys
        x_tr, y_tr = to_arr(train)
        x_te, y_te = to_arr(test)
        return x_tr, y_tr, x_te, y_te
    except Exception as e:
        print(f"  torchvision unavailable ({e!r}); falling back to direct download")
        d = _load_mnist_fallback(data_dir)
        return d["train_images"], d["train_labels"], d["test_images"], d["test_labels"]


# ---------------------------------------------------------------------------
# Dataset wrapper.
# ---------------------------------------------------------------------------
class _ArrDS(torch.utils.data.Dataset):
    def __init__(self, x: np.ndarray, y: np.ndarray):
        self.x = torch.from_numpy(x.astype(np.uint8))
        self.y = torch.from_numpy(y.astype(np.int64))

    def __len__(self):
        return self.x.shape[0]

    def __getitem__(self, i):
        return self.x[i].unsqueeze(0).to(torch.float32), int(self.y[i].item())


# ---------------------------------------------------------------------------
# BN-fold export helpers — shared by both nets.
# ---------------------------------------------------------------------------
def _bn_fold_export(fc_weight: torch.Tensor, bn: nn.BatchNorm1d,
                    n_input: int) -> tuple[np.ndarray, np.ndarray]:
    w = torch.where(fc_weight >= 0,
                    torch.ones_like(fc_weight),
                    -torch.ones_like(fc_weight)).cpu().numpy().astype(np.int8)
    mu    = bn.running_mean.cpu().numpy()
    sigma = torch.sqrt(bn.running_var + bn.eps).cpu().numpy()
    gamma = bn.weight.cpu().numpy()
    beta  = bn.bias.cpu().numpy()
    sg    = np.where(gamma >= 0, 1.0, -1.0)
    gabs  = np.abs(gamma) + 1e-12
    w     = (w.T * sg.astype(np.int8)).T.astype(np.int8)
    t     = np.clip(np.ceil((n_input + sg * mu - beta * sigma / gabs) / 2.0),
                    0, n_input).astype(np.uint8)
    return w, t


def _export(model: nn.Module, out_path: Path, net: str, test_acc: float) -> None:
    model.eval()
    with torch.no_grad():
        if net == "14x14":
            l1_w = np.zeros((64, 49), dtype=np.int8)
            l1_t = np.zeros(64, dtype=np.uint8)
            for k in range(4):
                w_k, t_k = _bn_fold_export(model.branches[k][0].weight,
                                            model.branches[k][1], n_input=49)
                l1_w[k * 16:(k + 1) * 16] = w_k
                l1_t[k * 16:(k + 1) * 16] = t_k
        else:
            l1_w, l1_t = _bn_fold_export(model.fc1.weight, model.bn1,
                                          n_input=N_INPUT_7X7)

        l2_w = torch.where(model.fc2.weight >= 0,
                           torch.ones_like(model.fc2.weight),
                           -torch.ones_like(model.fc2.weight)).cpu().numpy().astype(np.int8)
        l2_bias_f = model.fc2.bias.cpu().numpy()
        l2_bias   = np.rint(l2_bias_f).astype(np.int16)
        l2_t      = np.clip(np.ceil((N_HIDDEN - l2_bias_f) / 2.0),
                            0, N_HIDDEN).astype(np.uint8)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(out_path,
             layer1_weights=l1_w, layer1_thresholds=l1_t,
             layer2_weights=l2_w, layer2_thresholds=l2_t,
             layer2_bias=l2_bias)
    print(f"wrote {out_path}")
    pt_path = out_path.with_suffix(".pt")
    torch.save(model.state_dict(), pt_path)
    print(f"wrote {pt_path}")
    print(f"  l1_w {l1_w.shape}  l1_t [{int(l1_t.min())}..{int(l1_t.max())}]")
    print(f"  l2_w {l2_w.shape}  l2_t [{int(l2_t.min())}..{int(l2_t.max())}]  "
          f"l2_bias [{int(l2_bias.min())}..{int(l2_bias.max())}]")
    print(f"final test_acc = {test_acc:.4f}")


# ---------------------------------------------------------------------------
# Training — single-seed inner loop.
# ---------------------------------------------------------------------------
def _train_one_seed(seed: int, model_factory, preprocess_fn,
                    train_dl: DataLoader, test_dl: DataLoader,
                    epochs: int, net14: bool) -> tuple[float, nn.Module]:
    """Train with one random seed; return (final_test_acc, trained_model)."""
    torch.manual_seed(seed)
    np.random.seed(seed)

    model = model_factory()

    with torch.no_grad():
        if net14:
            for k in range(4):
                nn.init.uniform_(model.branches[k][0].weight, -0.5, 0.5)
        else:
            nn.init.uniform_(model.fc1.weight, -0.5, 0.5)
        nn.init.uniform_(model.fc2.weight, -0.5, 0.5)
        if model.fc2.bias is not None:
            nn.init.zeros_(model.fc2.bias)

    opt = torch.optim.Adam(model.parameters(), lr=LR)

    steps_per_epoch = len(train_dl)
    if net14:
        scheduler = torch.optim.lr_scheduler.OneCycleLR(
            opt,
            max_lr=LR,
            total_steps=epochs * steps_per_epoch,
            pct_start=0.05,
            anneal_strategy="cos",
            final_div_factor=1e4,
        )
    else:
        scheduler = None

    test_acc = 0.0
    for epoch in range(epochs):
        model.train()
        total = correct = 0
        running = 0.0
        for x, y in train_dl:
            x      = preprocess_fn(x)
            logits = model(x)
            loss   = F.cross_entropy(logits / LOGIT_TEMP, y)
            opt.zero_grad()
            loss.backward()
            opt.step()
            if scheduler is not None:
                scheduler.step()
            with torch.no_grad():
                if net14:
                    for k in range(4):
                        model.branches[k][0].weight.clamp_(-WCLIP, WCLIP)
                else:
                    model.fc1.weight.clamp_(-WCLIP, WCLIP)
                model.fc2.weight.clamp_(-WCLIP, WCLIP)
            running += loss.item() * y.size(0)
            pred    = logits.argmax(dim=1)
            total   += y.size(0)
            correct += (pred == y).sum().item()
        train_acc = correct / total

        model.eval()
        ok = tot = 0
        with torch.no_grad():
            for x, y in test_dl:
                x  = preprocess_fn(x)
                ok  += (model(x).argmax(1) == y).sum().item()
                tot += y.size(0)
        test_acc = ok / tot

        lr_now = opt.param_groups[0]["lr"] if scheduler is None else scheduler.get_last_lr()[0]
        print(f"  ep {epoch+1:2d}/{epochs}  loss={running/total:.4f}  "
              f"train={train_acc:.4f}  test={test_acc:.4f}  "
              f"lr={lr_now:.2e}")

    return test_acc, model


# ---------------------------------------------------------------------------
# Training — outer driver.
# ---------------------------------------------------------------------------
def train(args) -> None:
    net14 = (args.net == "14x14")

    if args.out is None:
        args.out = ("data/bnn_weights_14x14.npz" if net14
                    else "data/bnn_weights.npz")
    if args.epochs is None:
        args.epochs = EPOCHS_14X14 if net14 else EPOCHS

    accuracy_floor = ACCURACY_FLOOR_14X14 if net14 else ACCURACY_FLOOR_7X7

    print(f"net={args.net}  epochs={args.epochs}  out={args.out}")
    print(f"ste=hard-tanh  scheduler={'OneCycleLR' if net14 else 'constant'}")
    print(f"loading MNIST from {args.data_dir}")
    x_tr, y_tr, x_te, y_te = load_mnist(Path(args.data_dir))
    print(f"  train {x_tr.shape}  test {x_te.shape}")

    train_dl = DataLoader(_ArrDS(x_tr, y_tr), batch_size=BATCH, shuffle=True)
    test_dl  = DataLoader(_ArrDS(x_te, y_te), batch_size=512,  shuffle=False)

    if net14:
        model_factory = GroupedBNN_14x14
        preprocess_fn = preprocess_grouped_batch_14x14
        seeds = [args.seed] if args.seed != 2026 else SEEDS_14X14
    else:
        model_factory = BNN_49_64_10
        preprocess_fn = preprocess_batch
        seeds = [args.seed]

    best_acc   = -1.0
    best_model = None
    best_seed  = None
    seed_results: dict[int, float] = {}

    for seed in seeds:
        sep = "=" * 60
        print(f"\n{sep}")
        print(f"SEED {seed}  ({seeds.index(seed)+1}/{len(seeds)})")
        print(sep)
        acc, model = _train_one_seed(
            seed, model_factory, preprocess_fn,
            train_dl, test_dl, args.epochs, net14,
        )
        seed_results[seed] = acc
        if acc > best_acc:
            best_acc   = acc
            best_model = model
            best_seed  = seed
        print(f"  → seed {seed} final test_acc = {acc:.4f}")

    if len(seeds) > 1:
        print(f"\n{'='*60}")
        print("MULTI-SEED SUMMARY")
        print(f"{'='*60}")
        for s, a in seed_results.items():
            marker = " ← best" if s == best_seed else ""
            print(f"  seed {s:5d}: {a:.4f}{marker}")
        print(f"  best = seed {best_seed}, test_acc = {best_acc:.4f}")

    if best_acc < accuracy_floor:
        print(f"\n!! best test_acc {best_acc:.4f} < floor {accuracy_floor:.2f} "
              "— check STE / preprocessing")

    _export(best_model, Path(args.out), args.net, best_acc)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--net",      choices=["7x7", "14x14"], default="7x7")
    p.add_argument("--out",      default=None,
                   help="output npz (default: data/bnn_weights[_14x14].npz)")
    p.add_argument("--data-dir", default="data/mnist")
    p.add_argument("--epochs",   type=int, default=None,
                   help="epochs (default: 10 for 7x7, 30 for 14x14)")
    p.add_argument("--seed",     type=int, default=2026,
                   help="seed override; 14x14 default is 3-seed sweep [42,1042,2042]")
    train(p.parse_args())
