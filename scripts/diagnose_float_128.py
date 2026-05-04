"""Phase-3D float-MLP capacity diagnostic at hidden_dim=128.

Mirrors the 49→64→10 float baseline but with the wider hidden layer that
Option B would deploy. Uses the v4 preprocessing (strict-> per-image median,
imported from train_bnn.preprocess_batch). Same 5-epoch / Adam-1e-3 budget.

Decision rule — see the user's instructions:
  float ceiling >= 0.84  → Option B (retrain 49→128→10 BNN)
  0.81 <= float ceiling < 0.84 → Option A (accept 71%)
  float ceiling < 0.80  → Option A + document; capacity does not help
"""
from __future__ import annotations
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_bnn      # noqa: E402

EPOCHS  = 5
BATCH   = 128
LR      = 1e-3
SEED    = 2026
HIDDEN  = 128


class FloatMLP_128(nn.Module):
    def __init__(self):
        super().__init__()
        self.fc1 = nn.Linear(train_bnn.N_INPUT, HIDDEN)
        self.fc2 = nn.Linear(HIDDEN, train_bnn.N_OUTPUT)

    def forward(self, x):
        return self.fc2(torch.relu(self.fc1(x)))


def main() -> None:
    torch.manual_seed(SEED)
    x_tr, y_tr, x_te, y_te = train_bnn.load_mnist(Path("data/mnist"))
    train_dl = DataLoader(train_bnn._ArrDS(x_tr, y_tr), batch_size=BATCH, shuffle=True)
    test_dl  = DataLoader(train_bnn._ArrDS(x_te, y_te), batch_size=512, shuffle=False)

    model = FloatMLP_128()
    opt = torch.optim.Adam(model.parameters(), lr=LR)

    print(f"float MLP 49→{HIDDEN}→10 on v4 strict-> median preprocessing")
    print(f"  {EPOCHS} epochs, batch={BATCH}, Adam lr={LR}")

    for ep in range(EPOCHS):
        model.train()
        for x, y in train_dl:
            x = train_bnn.preprocess_batch(x)
            loss = F.cross_entropy(model(x), y)
            opt.zero_grad(); loss.backward(); opt.step()
        model.eval()
        cor = tot = 0
        with torch.no_grad():
            for x, y in test_dl:
                x = train_bnn.preprocess_batch(x)
                cor += (model(x).argmax(dim=1) == y).sum().item()
                tot += y.size(0)
        print(f"  epoch {ep+1}/{EPOCHS}: test_acc={cor/tot:.4f}")


if __name__ == "__main__":
    main()
