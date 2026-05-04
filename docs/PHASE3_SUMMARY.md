# Phase 3 Summary — PicoRV32 + TLG Tile SoC on sky130A

## Headline (Phase 4.5, latest)

**85.60% MNIST accuracy** on a fully-placed-and-routed sky130A ASIC.
47.21 mW @ max_ff / **8.06 µJ per image** / **124,113 inferences/J** at 100 MHz.
Die area: 2.250 mm² (OpenRAM SoC). Tile fraction of system energy: **24.3%**.
95% Wilson CI: [84.90%, 86.27%] on 10,000 MNIST test images.

---

## Phase Roadmap

| Phase | Milestone | MNIST acc | Energy/img | Notes |
|-------|-----------|-----------|------------|-------|
| 3A | SoC architecture spec + skeleton RTL | — | — | PicoRV32 + tile bus spec |
| 3B | Tile wrapper RTL + bus-level TB | — | — | 10/10 PASS |
| 3C | PicoRV32 vendored + SoC bring-up | — | — | 102-cycle smoke PASS |
| 3D | End-to-end 7×7 BNN firmware | 71.12% | — | 16/16 SoC PASS |
| 3E | Full LibreLane P&R + activity-aware power | 71.12% | — | Baseline: register-file memories |
| 3.5 | OpenRAM SRAM macros | 71.12% | 7.98 µJ | 125,292 inf/J; 2.250 mm² die |
| **4.5** | **Grouped 14×14 BNN** | **85.60%** | **8.06 µJ** | **+14.48 pp; same SoC netlist** |

---

## SoC Architecture

```
          ┌────────────────────────────────────────────────┐
          │  soc_top (sky130A, 2.250 mm² die)               │
          │                                                  │
          │  ┌────────┐   Wishbone   ┌──────────────────┐  │
          │  │PicoRV32│─────────────▶│  u_xbar (1-to-4) │  │
          │  └────────┘              └─┬──┬──┬──────────┘  │
          │                            │  │  │              │
          │               ┌────────────┘  │  └────────┐    │
          │               ▼               ▼           ▼    │
          │         ┌──────────┐   ┌──────────┐  ┌───────┐ │
          │         │u_imem    │   │u_dmem    │  │u_tile │ │
          │         │2KB SRAM  │   │1KB SRAM  │  │TLG acc│ │
          │         │(sky130)  │   │(sky130)  │  │64-bit │ │
          │         └──────────┘   └──────────┘  └───────┘ │
          │                                                  │
          │         u_gpio (UART + LEDs)                     │
          └────────────────────────────────────────────────┘
```

**IMEM**: `sky130_sram_2kbyte_1rw1r_32x512_8` — PicoRV32 firmware (compiled C).
**DMEM**: `sky130_sram_1kbyte_1rw1r_32x256_8` — input image data (8 words/image for Phase 4.5).
**Tile**: 64-bit XNOR-popcount engine, 16 neurons/eval, binary threshold output.

---

## BNN Architecture (Phase 4.5 — Grouped 14×14)

```
28×28 uint8 → 2×2 avg pool → 14×14 → 4 non-overlapping 7×7 quadrants
→ per-quadrant strict>median binarization (49 ±1 bits each)
→ 4 branches: BinaryLinear(49,16) + BN + sign  [tile hardware: 4 XNOR-popcount evals]
→ concat(64) → BinaryLinear(64,10,bias=True)
```

**Why grouped?** A single tile eval covers 64 bits (2 × 32-bit words). With 49-bit quadrant inputs, 4 evals handle the full L1 layer in one firmware pass. Full 784→64 would require 13 evals and 2× the DMEM.

**Training (Stage 1)**: Hard-tanh STE (Hubara 2016) + OneCycleLR (max_lr=1e-3, 30 ep, 3 seeds), best-seed selection. See `docs/PHASE4_5_NOTES.md` §4 for details.

**7×7 comparison**: Phase 3D used a direct 7×7 downsample (4×4 pool). 14×14 adds +161 cycles/image (+0.95%) for the larger DMEM footprint but gains +14.48 pp accuracy.

---

## Power Breakdown (max_ff_n40C_1v95, Phase 4.5 VCD)

| Bucket | mW | Share |
|--------|----|-------|
| PicoRV32 | 7.71 | 16.3% |
| IMEM 2KB SRAM | 5.56 | 11.8% |
| DMEM 1KB SRAM | 3.85 | 8.2% |
| **TLG Tile** | **11.47** | **24.3%** |
| GPIO | 0.30 | 0.6% |
| Shared std-cells | 1.24 | 2.6% |
| Clock tree | 15.10 | 32.0% |
| **Total** | **47.21** | |

---

## Baseline Comparison (Register-file vs OpenRAM vs Phase 4.5)

Full table: `results/phase3/comparison_baseline_vs_openram.{csv,md}`

| Metric | Reg-file | OpenRAM (Ph 3.5) | Phase 4.5 |
|--------|----------|-----------------|-----------|
| Die area (mm²) | 1.769 | 2.250 | 2.250 (same SoC) |
| Total power @ max_ff (mW) | 106.06 | 47.21 | 47.21 (same SoC) |
| MNIST accuracy (%) | 71.12 | 71.12 | **85.60** |
| Energy/image @ max_ff (µJ) | 15.55 | 7.98 | 8.06 |
| Inferences/J @ max_ff | 64,315 | 125,292 | 124,113 |
| Tile share of system energy (%) | 10.81 | 24.29 | 24.29 (same SoC) |

---

## Verification Status

All gates green:

| Gate | Phase 3D (7×7) | Phase 4.5 (14×14) |
|------|---------------|------------------|
| SoC smoke test (firmware boot) | PASS | PASS |
| SoC BNN inference (16/16 images) | 16/16 PASS | 16/16 PASS |
| Full MNIST test-set eval | 71.12% | **85.60%** |
| LibreLane P&R (sky130A) | PASS | N/A (same netlist) |
| OpenSTA timing @ nom_tt | +0.51 ns WNS | +0.51 ns WNS |
| KLayout DRC | 0 errors | 0 errors |

---

## Key Files

| Path | Purpose |
|------|---------|
| `rtl/soc/soc_top.v` | Top-level SoC RTL |
| `rtl/tile_tlg_ld/tile_tlg_ld.v` | TLG tile accelerator |
| `firmware/inference/main.c` | BNN inference firmware (C) |
| `firmware/inference/weights_14x14.h` | Phase 4.5 BN-folded weights |
| `scripts/bnn_reference.py` | Integer-exact golden reference |
| `scripts/train_bnn.py` | BNN training (hard-tanh STE, OneCycleLR) |
| `scripts/eval_full_mnist_14x14.py` | Full 10K MNIST evaluation |
| `flow/phase3_soc/` | LibreLane P&R configuration |
| `results/phase3/power/max_ff_n40C_1v95/power.metrics.json` | Activity-aware power |
| `results/phase4_prep/full_mnist_accuracy_14x14.json` | Phase 4.5 eval results |
| `docs/PHASE4_5_NOTES.md` | Full Phase 4.5 diagnostic + training notes |
| `docs/PHASE3_5_NOTES.md` | OpenRAM SoC integration notes |
