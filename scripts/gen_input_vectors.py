#!/usr/bin/env python3
"""Phase 2C — generate reproducible input vectors and per-seed cfg programs
for activity-aware power simulation.

For each seed_id in {0, 1, 2}:
  - 1024 random 64-bit input vectors using numpy.random.RandomState(1000 + seed_id)
    (independent namespace from the weight seeds, so input randomness is
    decoupled from weight randomness — same vectors are seen by every variant
    sharing this seed_id).
  - 16 64-bit weights and 16 thresholds drawn from the same RandomState that
    gen_tile.py uses (numpy seed = SEED_ID_TO_NUMPY_SEED[seed_id], default
    seed_id), so that the loadable variants can be programmed with the same
    weights that the hardcoded variants baked in for the same seed_id.

Outputs:
  results/phase2c/inputs/seed<N>/xs.hex   (1024 lines, 16 hex digits)
  results/phase2c/inputs/seed<N>/ws.hex   (16 lines, 16 hex digits)
  results/phase2c/inputs/seed<N>/ts.hex   (16 lines, 7-bit threshold)
  results/phase2c/inputs/seed<N>/manifest.json   (knobs + checksums)
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import numpy as np  # noqa: E402
import gen_tile  # noqa: E402
import tlg_lib  # noqa: E402

N_VECTORS = 1024
INPUT_SEED_BASE = 1000  # seed_id 0 → RandomState(1000)
SEED_IDS = [0, 1, 2]


def gen_seed(seed_id: int, out_root: Path) -> dict:
    out = out_root / f"seed{seed_id}"
    out.mkdir(parents=True, exist_ok=True)

    # Inputs: independent namespace from weight seeds.
    rng = np.random.RandomState(INPUT_SEED_BASE + seed_id)
    xs_path = out / "xs.hex"
    with xs_path.open("w") as f:
        for _ in range(N_VECTORS):
            hi = int(rng.randint(0, 1 << 32))
            lo = int(rng.randint(0, 1 << 32))
            x = (hi << 32) | lo
            f.write(f"{x:016x}\n")

    # Weights/thresholds: match what gen_tile.py emits for this seed_id.
    np_seed = gen_tile.numpy_seed_for(seed_id)
    weights = tlg_lib.gen_weight_set(np_seed, gen_tile.N_NEURONS)
    w_ints = [tlg_lib.w_to_int(w) for w in weights]
    thresholds = [tlg_lib.THRESHOLD] * gen_tile.N_NEURONS

    ws_path = out / "ws.hex"
    with ws_path.open("w") as f:
        for w in w_ints:
            f.write(f"{w:016x}\n")
    ts_path = out / "ts.hex"
    with ts_path.open("w") as f:
        for t in thresholds:
            f.write(f"{t:02x}\n")

    def md5(p: Path) -> str:
        return hashlib.md5(p.read_bytes()).hexdigest()

    manifest = {
        "seed_id": seed_id,
        "input_seed": INPUT_SEED_BASE + seed_id,
        "weight_seed": np_seed,
        "n_vectors": N_VECTORS,
        "n_neurons": gen_tile.N_NEURONS,
        "n_inputs": tlg_lib.N_INPUTS,
        "threshold": tlg_lib.THRESHOLD,
        "files": {
            "xs.hex": md5(xs_path),
            "ws.hex": md5(ws_path),
            "ts.hex": md5(ts_path),
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path,
                   default=ROOT / "results" / "phase2c" / "inputs")
    args = p.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    for sid in SEED_IDS:
        m = gen_seed(sid, args.out)
        print(f"seed_id {sid}: input_seed={m['input_seed']}  "
              f"weight_seed={m['weight_seed']}  vectors={m['n_vectors']}  "
              f"xs.md5={m['files']['xs.hex'][:8]}  ws.md5={m['files']['ws.hex'][:8]}")


if __name__ == "__main__":
    main()
