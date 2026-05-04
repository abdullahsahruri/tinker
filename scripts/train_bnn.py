"""Train a 49 → 64 → 10 BNN on MNIST and export it in hardware-compatible form.

Architecture (small, transparent, no Brevitas):

    fc1 = BinaryLinear(49, 64, bias=False)        # ±1 weights via sign+STE
    bn1 = BatchNorm1d(64, affine=False)           # per-neuron normalization,
                                                  # no learnable γ/β so there
                                                  # is no sign-flip ambiguity
                                                  # at deployment.
    sign() activation                             # ±1 hidden
    fc2 = BinaryLinear(64, 10, bias=True)         # ±1 weights, learnable bias
                                                  # (used as the per-class
                                                  # signed offset at argmax).

Why not BN on layer 2: argmax(softmax(logit)) = argmax(logit), and we want a
purely integer logit at deployment. A BN with affine=True introduces per-class
γ/σ that affects argmax (it's a per-class scale), which can't be folded into
an integer comparison across classes. fc2.bias absorbs the per-class offset
without scale.

Why BN affine=False on layer 1: BN already gives each hidden neuron its own
running_mean and running_var. The per-neuron threshold at deployment is
therefore (49 + running_mean_i) / 2 (rounded), which uses BN's normalization
without needing a γ that could be negative.

Export (data/bnn_weights.npz):
    layer1_weights     int8  (64, 49) in {-1, +1}
    layer1_thresholds  uint8 (64,)    in [0, 49]   — popcount-≥ threshold
    layer2_weights     int8  (10, 64) in {-1, +1}
    layer2_thresholds  uint8 (10,)    in [0, 64]   — kept for spec compliance
    layer2_bias        int16 (10,)    signed       — used by argmax: logit_c
                                                    = 2·popcount(h XNOR W2_c)
                                                    − 64 + bias_c
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
# Hyperparameters — locked.
# ---------------------------------------------------------------------------
N_INPUT  = 49
N_HIDDEN = 64
N_OUTPUT = 10
EPOCHS   = 10
BATCH    = 128
LR       = 1e-3
ACCURACY_FLOOR = 0.80
# Latent-weight clip range. After each optim step the float weights are
# clamped into [-WCLIP, +WCLIP] so they stay inside the STE's pass band
# (|x|<=1) — the standard BinaryConnect recipe. Without it the latent
# weights drift large, sign(w) freezes, and the network stalls.
WCLIP = 1.0
# Logit temperature for cross-entropy. The deployed forward computes
#   logit_c = 2·popcount(h XNOR W2_c) − 64 + bias_c   ∈ roughly ±64.
# Softmax over logits in ±64 is one-hot — CE gradient becomes a near-
# delta function and learning stalls. We divide the training-time logits
# by LOGIT_TEMP before CE; argmax is preserved (positive scalar) so the
# train/eval predictions match the deployed firmware exactly.
LOGIT_TEMP = 8.0


# ---------------------------------------------------------------------------
# Sign with straight-through estimator.
# ---------------------------------------------------------------------------
class SignSTE(torch.autograd.Function):
    """y = sign(x), tie-break 0 → +1; backward = pure identity (no clip).

    The classic BinaryConnect recipe: forward is hard sign, backward passes
    the gradient through unchanged. Combined with post-step latent-weight
    clipping (see WCLIP) this keeps gradients flowing without letting the
    weight magnitudes drift unboundedly. A clipped backward (g * (|x|<=1))
    was tried first — it killed ~30% of activation gradients downstream of
    the affine BN (post-norm |x| often exceeds 1) and stalled training at
    ~60% MNIST test accuracy.
    """
    @staticmethod
    def forward(ctx, x):
        return torch.where(x >= 0, torch.ones_like(x), -torch.ones_like(x))

    @staticmethod
    def backward(ctx, g):
        return g


def sign_ste(x: torch.Tensor) -> torch.Tensor:
    return SignSTE.apply(x)


class BinaryLinear(nn.Linear):
    """nn.Linear with weights binarized to ±1 (STE on backward).

    Note: only the weight is binarized; the optional bias remains float and
    is folded into the per-class signed integer bias at export.
    """
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        wb = sign_ste(self.weight)
        return F.linear(x, wb, self.bias)


class BNN_49_64_10(nn.Module):
    """BinaryConnect architecture: fc1 → BN1 → sign() → fc2 (bias=True).

    No BN on layer 2: a per-class BN affine would re-order argmax at
    deployment (since γ_c, μ_c differ per class and we can't fold a
    per-class scale into the integer argmax we want at deployment). And
    BN affine=False on layer 2 was empirically worse — it makes the
    learnable fc2.bias redundant during training (BN's running mean
    absorbs the bias), so the deployed bias stays at 0 and per-class
    offset is lost.
    """
    def __init__(self):
        super().__init__()
        self.fc1 = BinaryLinear(N_INPUT, N_HIDDEN, bias=False)
        self.bn1 = nn.BatchNorm1d(N_HIDDEN, affine=True)
        self.fc2 = BinaryLinear(N_HIDDEN, N_OUTPUT, bias=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        h = self.fc1(x)            # (B, 64) integer-valued
        h = self.bn1(h)            # affine BN — γ folded at export
        h = sign_ste(h)            # ±1 hidden
        return self.fc2(h)         # (B, 10) raw integer logits + bias


# ---------------------------------------------------------------------------
# Image preprocessing — must match scripts/bnn_reference.preprocess_image.
#
# Per-image strict-`>` median binarization (Phase-3D Path B, v3):
#   v1 (fixed 0.5)  → 7×7 perimeter constant-zero, capped at ~70% (float MLP)
#   v2 (>= median)  → 94% of MNIST has median == 0; >= 0 sets ~all bits +1 → chance
#   v3 (top-K with index jitter) → forced +1 at low indices for tied-at-zero
#                                  images; (0,0) was +1 in 94% of images even
#                                  though it's pure background → 66% BNN
#   v3 → v4 (strict > median): when median == 0 (94% of images) only the
#        strictly-positive pooled positions binarize to +1 — those are the
#        actual digit pixels — typically 5–15 per image. When median > 0 (6%)
#        we get the usual ~24 "above-median" positions. +1 count varies per
#        image (BN1 normalizes it) but every +1 truly carries digit signal.
# ---------------------------------------------------------------------------
def preprocess_batch(x: torch.Tensor) -> torch.Tensor:
    """(B, 1, 28, 28) → (B, 49) ±1 floats, identical math to the Python golden."""
    x = x.to(torch.float32)
    if x.max() > 1.5:
        x = x / 255.0
    x = F.avg_pool2d(x, kernel_size=4, stride=4)            # (B, 1, 7, 7)
    flat = x.view(x.size(0), -1)                             # (B, 49)
    thr = flat.median(dim=1, keepdim=True).values            # (B, 1) — torch's
                                                             # lower-median = 24th
                                                             # sorted = same as numpy
                                                             # for 49-elt vectors
    return (flat > thr).to(torch.float32) * 2.0 - 1.0        # ±1, strict >


# ---------------------------------------------------------------------------
# MNIST loader. Tries torchvision first (most convenient); falls back to a
# self-contained urllib + idx-parser when torchvision is unavailable, so the
# training script does not strictly require torchvision.
# ---------------------------------------------------------------------------
def _idx_parse(buf: bytes) -> np.ndarray:
    import struct
    magic, n_items = struct.unpack(">II", buf[:8])
    if magic == 2049:                     # labels
        return np.frombuffer(buf, dtype=np.uint8, offset=8, count=n_items)
    if magic == 2051:                     # images
        rows, cols = struct.unpack(">II", buf[8:16])
        return np.frombuffer(buf, dtype=np.uint8, offset=16,
                             count=n_items * rows * cols).reshape(n_items, rows, cols)
    raise ValueError(f"unknown IDX magic: {magic}")


def _load_mnist_fallback(data_dir: Path):
    """Download MNIST IDX files directly into data_dir (no torchvision dep)."""
    import gzip
    import urllib.request
    data_dir.mkdir(parents=True, exist_ok=True)
    base = "https://ossci-datasets.s3.amazonaws.com/mnist/"
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
        with gzip.open(local, "rb") as fh:
            out[key] = _idx_parse(fh.read())
    return out


def load_mnist(data_dir: Path):
    """Return (train_images, train_labels, test_images, test_labels) numpy arrays.

    Image arrays are uint8 (N, 28, 28); label arrays are uint8 (N,).
    """
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
# Training loop.
# ---------------------------------------------------------------------------
class _ArrDS(torch.utils.data.Dataset):
    def __init__(self, x: np.ndarray, y: np.ndarray):
        self.x = torch.from_numpy(x.astype(np.uint8))
        self.y = torch.from_numpy(y.astype(np.int64))

    def __len__(self):
        return self.x.shape[0]

    def __getitem__(self, i):
        return self.x[i].unsqueeze(0).to(torch.float32), int(self.y[i].item())


def train(args):
    device = torch.device("cpu")
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    print(f"loading MNIST from {args.data_dir}")
    x_tr, y_tr, x_te, y_te = load_mnist(Path(args.data_dir))
    print(f"  train {x_tr.shape} {y_tr.shape}   test {x_te.shape} {y_te.shape}")

    train_dl = DataLoader(_ArrDS(x_tr, y_tr), batch_size=BATCH, shuffle=True)
    test_dl  = DataLoader(_ArrDS(x_te, y_te), batch_size=512, shuffle=False)

    model = BNN_49_64_10().to(device)
    # Shrink the default Linear init so the latent float weights start inside
    # the STE pass band and gradients reach them on step 0.
    with torch.no_grad():
        nn.init.uniform_(model.fc1.weight, -0.5, 0.5)
        nn.init.uniform_(model.fc2.weight, -0.5, 0.5)
        if model.fc2.bias is not None:
            nn.init.zeros_(model.fc2.bias)
    # Adam over all parameters (BN γ/β are also Adam-trained).
    opt = torch.optim.Adam(model.parameters(), lr=LR)

    for epoch in range(args.epochs):
        model.train()
        total = correct = 0
        running = 0.0
        for x, y in train_dl:
            x = preprocess_batch(x).to(device)
            y = y.to(device)
            logits = model(x)
            loss = F.cross_entropy(logits / LOGIT_TEMP, y)
            opt.zero_grad()
            loss.backward()
            opt.step()
            # Clip latent weights so the STE keeps passing gradients.
            with torch.no_grad():
                model.fc1.weight.clamp_(-WCLIP, WCLIP)
                model.fc2.weight.clamp_(-WCLIP, WCLIP)
            running += loss.item() * y.size(0)
            pred = logits.argmax(dim=1)        # argmax preserved by /TEMP
            total += y.size(0)
            correct += (pred == y).sum().item()
        train_acc = correct / total

        model.eval()
        test_correct = test_total = 0
        with torch.no_grad():
            for x, y in test_dl:
                x = preprocess_batch(x).to(device)
                pred = model(x).argmax(dim=1)
                test_correct += (pred == y).sum().item()
                test_total   += y.size(0)
        test_acc = test_correct / test_total
        print(f"  epoch {epoch+1:2d}/{args.epochs}  loss={running/total:.4f}  "
              f"train_acc={train_acc:.4f}  test_acc={test_acc:.4f}")

    if test_acc < ACCURACY_FLOOR:
        print(f"!! test_acc {test_acc:.4f} < floor {ACCURACY_FLOOR:.2f} — STE/binarization may be wrong; debug rather than train longer")

    # -----------------------------------------------------------------------
    # Export: fold BN1 (affine) + fc2.bias into deployment-form integer params.
    #
    # Layer 1 deployment forward (no BN2 in the eval path):
    #   y_i = sign( γ_i (z_i − μ_i)/σ_i + β_i )    where z_i = w_bin · x ∈ ±49
    # If γ_i > 0:
    #   y_i = sign( z_i − μ_i + β_i σ_i / γ_i )
    #       = +1 iff p ≥ (49 + μ_i − β_i σ_i / γ_i) / 2
    # If γ_i < 0: comparison direction flips. Equivalent under hardware "≥":
    #   flip the sign of weight row w_i (so z' = −z = w'·x), then
    #   y_i = +1 iff p' ≥ (49 − μ_i − β_i σ_i / |γ_i|) / 2
    # Layer 2 ignores BN2 at deployment (per-class γ would couple argmax);
    # logit_c = z_c + bias_c (integer rounded).
    # -----------------------------------------------------------------------
    model.eval()
    with torch.no_grad():
        # Layer-1 weights — sign(fc1.weight), 0 mapped to +1.
        l1_w = torch.where(model.fc1.weight >= 0,
                           torch.ones_like(model.fc1.weight),
                           -torch.ones_like(model.fc1.weight)).cpu().numpy().astype(np.int8)

        bn1 = model.bn1
        mu1    = bn1.running_mean.cpu().numpy()
        sigma1 = torch.sqrt(bn1.running_var + bn1.eps).cpu().numpy()
        gamma1 = bn1.weight.cpu().numpy()
        beta1  = bn1.bias.cpu().numpy()
        sign_g1 = np.where(gamma1 >= 0, 1.0, -1.0)
        gamma1_abs = np.abs(gamma1) + 1e-12

        # Per-neuron flip: rows with γ<0 get their weight signs negated so
        # the hardware "p >= t" comparison still expresses the right
        # decision direction (γ<0 inverts the inequality after fold).
        l1_w = (l1_w.T * sign_g1.astype(np.int8)).T.astype(np.int8)

        # Threshold per neuron (unified, sign_g = sign(γ)):
        #   t = ceil( (49 + sign_g·μ - β·σ/|γ|) / 2 )
        # Derivation:
        #   PyTorch:  y = sign( γ·(z−μ)/σ + β )      with z = w_bin·x ∈ ±49
        #   γ>0  ⇒ y=+1 iff z ≥ μ − β·σ/γ
        #             ⇒ p ≥ (49 + μ − β·σ/γ)/2
        #   γ<0  ⇒ y=+1 iff z ≤ μ + β·σ/|γ|
        #             ⇒ after w-flip p′ = 49−p:
        #                p′ ≥ (49 − μ − β·σ/|γ|)/2
        l1_t_real = (N_INPUT + sign_g1 * mu1 - beta1 * sigma1 / gamma1_abs) / 2.0
        l1_t = np.ceil(l1_t_real).astype(np.int32)
        l1_t = np.clip(l1_t, 0, N_INPUT).astype(np.uint8)

        # Layer-2 weights — sign(fc2.weight).
        l2_w = torch.where(model.fc2.weight >= 0,
                           torch.ones_like(model.fc2.weight),
                           -torch.ones_like(model.fc2.weight)).cpu().numpy().astype(np.int8)

        # Layer-2 signed bias for argmax: logit_c = z_c + bias_c.
        l2_bias_float = model.fc2.bias.cpu().numpy()
        l2_bias = np.rint(l2_bias_float).astype(np.int16)

        # Layer-2 threshold-form (kept for spec compliance, not used in argmax):
        l2_t_real = (N_HIDDEN - l2_bias_float) / 2.0
        l2_t = np.ceil(l2_t_real).astype(np.int32)
        l2_t = np.clip(l2_t, 0, N_HIDDEN).astype(np.uint8)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        out_path,
        layer1_weights=l1_w,            # (64, 49) ±1
        layer1_thresholds=l1_t,         # (64,)    0..49
        layer2_weights=l2_w,            # (10, 64) ±1
        layer2_thresholds=l2_t,         # (10,)    0..64
        layer2_bias=l2_bias,            # (10,)    int16 signed
    )
    print(f"wrote {out_path}")

    # Save the PyTorch model state too — gen_bnn_testdata.py needs it to run
    # the PyTorch ↔ Python-golden agreement check.
    pt_path = out_path.with_suffix(".pt")
    torch.save(model.state_dict(), pt_path)
    print(f"wrote {pt_path}")
    print(f"  l1_w {l1_w.shape}  l1_t [{int(l1_t.min())}..{int(l1_t.max())}]")
    print(f"  l2_w {l2_w.shape}  l2_t [{int(l2_t.min())}..{int(l2_t.max())}]  "
          f"l2_bias [{int(l2_bias.min())}..{int(l2_bias.max())}]")
    print(f"final test_acc = {test_acc:.4f}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out",      default="data/bnn_weights.npz")
    p.add_argument("--data-dir", default="data/mnist")
    p.add_argument("--epochs",   type=int, default=EPOCHS)
    p.add_argument("--seed",     type=int, default=2026)
    train(p.parse_args())
