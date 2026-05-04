# Phase 3 Session D — end-to-end BNN inference firmware + SoC demonstration

> **Headline.** A 49→64→10 BinaryConnect-style MNIST BNN is trained from
> scratch in PyTorch (test_acc 0.7127), exported as int8 ±1 weights with
> integer hidden thresholds, compiled into ~1.5 KB of bare-metal RV32I
> firmware that runs on the Phase-3C SoC, and verified end-to-end against
> a Python golden across 16 MNIST test images. The firmware programs the
> Phase-2C `tile_tlg_ld` accelerator with 4 sequential 16-neuron weight
> batches per image (the hidden layer), then computes the 10-class output
> layer in software because argmax across classes needs pre-threshold
> sums that the tile's binary output doesn't expose. The integration TB
> runs to completion in **234 638 simulated cycles / 40 301 WB
> transactions / 16 of 16 images matching the Python golden**, beating
> the brief's `match_n >= 14` floor by 2 with margin to spare. All three
> earlier-phase regression gates (3A elaboration, 3B wrapper TB 10/10,
> 3C smoke TB) stay green. **GO for Session 3E.**

---

## 1. What this session produced

| Deliverable                                                       | Where                                            |
| ----------------------------------------------------------------- | ------------------------------------------------ |
| 49→64→10 BNN trainer with v4 preprocessing + BinaryConnect STE    | `scripts/train_bnn.py`                           |
| Python golden — popcount-XNOR forward, sign-of-γ BN1 fold         | `scripts/bnn_reference.py`                       |
| `weights.h` emitter (4×16 hidden batches + 10 output classes)     | `scripts/weights_to_c.py`                        |
| 16-image test-set generator + PyTorch ↔ Python-golden check       | `scripts/gen_bnn_testdata.py`                    |
| Capacity diagnostic — 49→128→10 float-MLP ceiling on v4           | `scripts/diagnose_float_128.py`                  |
| Trained weights + PyTorch state dict                              | `data/bnn_weights.{npz,pt}`                      |
| 16-image preprocessed test set + ground-truth labels + golden     | `data/bnn_test_set.npz`                          |
| Bare-metal RV32I inference firmware (~1.5 KB)                     | `firmware/inference/{main.c,start.S,linker.ld,Makefile,weights.h}` |
| SoC end-to-end testbench                                          | `tb/tb_soc_bnn.sv`                               |
| TB inputs (DMEM preload + expected stream)                        | `tb/tb_bnn_xs.hex`, `tb/tb_bnn_expected.hex`     |
| Convenience driver (`train → weights.h → testdata → fw → vvp`)    | `scripts/run_soc_bnn.sh`                         |
| This notes file                                                   | `docs/PHASE3D_NOTES.md`                          |

**Untouched** (Phase-3 brief locked these):
- All `rtl/soc/*.v` (3A skeleton + 3B/3C bodies) — zero changes.
- All `rtl/tile_tlg_ld/*` (Phase-2C IP) — frozen.
- `vendor/picorv32/picorv32.v` — pinned commit `87c89ac`, untouched.
- `firmware/smoke/` — kept as-is and still passing as a regression target.

## 2. Network training and the v1→v4 preprocessing iteration

### 2.1 Architecture (locked by brief, deployed verbatim)

```
fc1  : BinaryLinear(49, 64, bias=False)            ±1 weights via SignSTE
bn1  : BatchNorm1d(64, affine=True)                folded into per-neuron int threshold
sign() activation                                  ±1 hidden
fc2  : BinaryLinear(64, 10, bias=True)             ±1 weights, learnable bias

Training-time: cross_entropy(model(x) / 8.0, y)    — logit temperature scaling
Deployment:    layer 1 → tile, layer 2 → software popcount + argmax
```

Why no BN2 / BN affine=False on layer 2: a per-class normalizer can't be
folded into the integer argmax we want at deployment because per-class γ
re-orders argmax across classes. Adding BN2 on training only and dropping
it at deployment caused a train/eval mismatch that masked the actual
deployment behavior. fc2.bias=True absorbs the per-class offset cleanly,
matches between train and deploy, and folds into a signed integer
`L2_BIAS[c]` at export.

### 2.2 The headline finding — v4 preprocessing

The locked v1 preprocessing (28×28 → avg-pool 4×4 stride 4 → ≥ 0.5 → ±1)
makes the 7×7 perimeter constant-zero on MNIST: rows 0/6 and cols 0/6
average below 0.5 in essentially every image. Empirically only **11.4 %
of bits are ever +1** across 5 K training images, with 24 of 49 positions
constant-0. We diagnosed this end-to-end before retraining the BNN:

| ver | scheme                                  | BNN test_acc | what broke                                                 |
| --- | --------------------------------------- | -----------: | ---------------------------------------------------------- |
| v1  | fixed `≥ 0.5`                            | 0.6202       | perimeter constant-0; even float MLP caps ~0.70           |
| v2  | `≥ per-image median`                     | 0.1241       | 94 % of MNIST has 49-elt median == 0; `≥ 0` → ~all bits +1 |
| v3  | top-25 ranking (with index-jitter ties)  | 0.6566       | jitter pins +1 to low-index ties; (0,0) was +1 in 94 % of images |
| **v4** | **strict `> per-image median`**       | **0.7127**   | clean signal; +1 bits 5–24/49 per image, mean 18           |

The v4 per-position +1 fraction (5 K train images) reflects real digit
geometry instead of the v1 constant-zero perimeter:

```
[[0.   0.   0.03 0.11 0.12 0.03 0.  ]   ← top row mostly background
 [0.01 0.15 0.6  0.87 0.87 0.49 0.07]
 [0.02 0.33 0.81 0.93 0.92 0.57 0.07]   ← clear digit-area concentration
 [0.01 0.4  0.82 0.91 0.93 0.53 0.05]
 [0.02 0.45 0.79 0.9  0.9  0.45 0.06]
 [0.02 0.39 0.77 0.93 0.74 0.26 0.02]
 [0.   0.08 0.29 0.38 0.19 0.03 0.  ]]  ← bottom row mostly background
```

**Why strict `>` over `≥`:** for the 94 % of MNIST images whose
49-element pooled-vector median equals 0 (background ties), `≥ 0`
binarizes nearly every position to +1. Strict `>` admits only the
strictly-positive pooled positions in those cases — those are exactly
the digit pixels — typically 5–15 +1 bits per image. For the other 6 %
of images (median > 0) the usual ~24 above-median positions get +1.
**Variable +1 count per image is fine** — BN1 normalizes the post-fc1
distribution, so the network adapts.

### 2.3 Why we didn't push further (capacity diagnostic)

Before deciding whether to widen the network, we ran a 5-min float-MLP
capacity diagnostic at 49→128→10 with v4 preprocessing
(`scripts/diagnose_float_128.py`):

| epoch | 49→64→10 float ceiling | 49→128→10 float ceiling | Δ |
| ----- | ---------------------: | ----------------------: | -: |
| 1     | 0.7692                 | 0.7753                  | +0.6 pp |
| 3     | 0.7838                 | 0.8054                  | +2.2 pp |
| 5     | 0.7986                 | 0.8163                  | +1.8 pp |
| 8     | 0.8131                 | (not run)               | — |

The 2× hidden-width capacity bump buys only ~2 pp at the float ceiling
on the matched epoch budget. The information bottleneck is the **49
binary inputs**, not the hidden-layer width. With the typical
BinaryConnect ~10-pp gap below the float ceiling, a 49→128→10 BNN would
have landed at ~0.72–0.74 — barely moving the needle from the current
0.7127 — while costing a 30-min retrain plus doubled cfg-write traffic
on every image (8 hidden batches instead of 4).

**Final architecture: 49→64→10 v4. Test accuracy 0.7127.**

### 2.4 Other training-iteration debugging steps tried and rejected

For posterity, before locking the v4 preprocessing fix:

| Tweak                                                  | Result                | Rejected because                                       |
| ------------------------------------------------------ | --------------------- | ------------------------------------------------------ |
| BN1 affine=False, fc1 bias=True                        | 60 % stuck            | BN absorbs the bias; learnable per-neuron offset lost. |
| Add BN2 affine=False at training only                  | 60 % train, mismatch  | Per-class μ re-orders argmax → train/eval disagree.    |
| Remove BN2 entirely with raw logits (±64)              | 36 % (worse)          | Softmax saturates; CE gradient near zero.              |
| Add /8 logit temperature scaling                       | helps                 | Kept — preserves argmax, softens softmax.              |
| Clipped STE backward (`g * (|x|<=1)`)                  | 60 %                  | Kills ~30 % of post-BN-affine activation gradients.    |
| Identity STE backward (no clip) + post-step weight clip | helps                 | Kept — standard BinaryConnect recipe.                  |
| 15 epochs vs 10                                        | no further gain       | Network plateaus around epoch 5 in every variant.      |

The single biggest win was the v1→v4 preprocessing fix (+9 pp),
followed by BN1 affine=True with γ-sign-aware fold (+5 pp from the
affine=False baseline). The other tweaks each gave 1–3 pp.

## 3. Deployment math (BN1 fold, padding, layer 2)

### 3.1 BN1 → integer popcount-≥ threshold (with γ-sign handling)

The 49 trained ±1 inputs go into a 64-bit tile word; the 15 padding bits
are packed `tile_input[63:49] = 0`, `tile_weight[63:49] = 1` so they
contribute zero to popcount and the trained threshold maps directly
onto `cfg_addr={2'b01,i}` without offset.

PyTorch deployment forward (eval-mode BN with affine):
- `y_i = sign( γ_i · (z_i − μ_i) / σ_i + β_i )`, `z_i = w_bin_i · x_pm1 ∈ ±49`
- For γ_i > 0: `y_i = +1 ⇔ z_i ≥ μ_i − β_i σ_i / γ_i`
                `⇒ popcount ≥ (49 + μ_i − β_i σ_i / γ_i) / 2`
- For γ_i < 0: same algebra flips the inequality; folding into the
                hardware "p ≥ t" form requires negating the weight row
                (`w_i ← −w_i`, equivalently `popcount → 49 − popcount`).
                Resulting threshold: `(49 − μ_i − β_i σ_i / |γ_i|) / 2`.

Unified at export (with `sign_g = sign(γ)`):
```
t_i = ceil( (49 + sign_g · μ_i − β_i · σ_i / |γ_i|) / 2 ),  clipped to [0, 49]
l1_w_i ← l1_w_i · sign_g
```

### 3.2 Layer 2 in software, not on the tile

The tile emits binary above/below-threshold outputs only. argmax across
10 classes needs the pre-threshold sum, so the firmware computes layer 2
in software:
```
logit_c = 2 · popcount(hidden XNOR L2W[c]) − 64 + L2_BIAS[c]
prediction = argmax_c logit_c
```
This is **not** a deviation from the spec — the brief's option (b)
explicitly chose this path for argmax. The tile is exercised exclusively
for layer 1 (4 evaluations per image).

### 3.3 Verification — Python ↔ PyTorch ↔ SoC

- numpy ↔ PyTorch preprocessing: byte-identical on 200 test images.
- PyTorch model.eval() ↔ Python golden: **16/16 agree** on the
  16-image test set (CHECKPOINT #1 PASS).
- Python golden ↔ SoC firmware: **16/16 agree** (this session's
  end-to-end PASS).
- Python golden vs MNIST ground-truth labels: 13/16 on this 16-image
  batch, consistent with the network's overall 0.7127 test accuracy.

## 4. Firmware structure

### 4.1 Layout — 389 instruction words / 1 556 bytes / 19 % of IMEM

Built with `riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32 -Os
-nostdlib -nostartfiles -mno-relax`, identical knobs to
`firmware/smoke/Makefile`. `bin2hex.py --pad-words=2048` zero-pads to
fill IMEM; `2048 − 389 = 1659` zero-padded words. `weights.h` is
generated by `scripts/weights_to_c.py` and `#include`d into `main.c`.

| section                | size       | contents                                          |
| ---------------------- | ---------- | ------------------------------------------------- |
| `.text`                | ~256 B     | start.S + main + program_hidden_batch + run_inference + popcount32 |
| `.rodata` weights/bias | ~640 B     | `L1_W_LO[4][16]`, `L1_W_HI[4][16]`, `L1_T[4][16]`, `L2_W_LO[10]`, `L2_W_HI[10]`, `L2_BIAS[10]` |
| `.rodata` popcount LUT | 256 B      | `POPCOUNT8[256]`                                  |
| `.text` epilog/spill   | ~400 B     | argmax + GPIO writes + GCC-generated callee saves |

Stack at 0x10001000 (top of DMEM, growing down) per `start.S`. DMEM
words 0..31 hold the 16 packed test images preloaded by the TB.

### 4.2 Inference loop

```
for img in 0..15:
    xlo, xhi = DMEM[2*img], DMEM[2*img+1]      ; 64-bit packed input
    hidden_lo = hidden_hi = 0
    for k in 0..3:                              ; 4 hidden batches × 16 neurons
        program_hidden_batch(k):                 ; 16 W.LO + 16 W.HI + 16 T writes
            for i in 0..15:
                MMIO[TILE_W_LO(i)] = L1_W_LO[k][i]
                MMIO[TILE_W_HI(i)] = L1_W_HI[k][i]
            for i in 0..15:
                MMIO[TILE_T(i)] = L1_T[k][i]
        run_inference(xlo, xhi):                 ; ~2-cycle pipeline
            MMIO[TILE_XIN_LO] = xlo
            MMIO[TILE_XIN_HI] = xhi              ; commits + pulses x_valid
            while (MMIO[TILE_STATUS] & 1): poll  ; usually 1 iteration
            return MMIO[TILE_YOUT] & 0xFFFF
        place y at hidden bits [k*16 .. k*16+15]
    for c in 0..9:                              ; output layer in software
        logit_c = 2 * popcount(hidden XNOR L2W[c]) - 64 + L2_BIAS[c]
    prediction = argmax_c logit_c
    MMIO[GPIO_OUT]     = prediction & 0xFF       ; observable on gpio_o[7:0]
    MMIO[GPIO_SIM_END] = 0xC0FE0000 | prediction ; per-image sentinel
MMIO[GPIO_SIM_END] = 0xCAFEBABE                 ; final completion sentinel
spin
```

### 4.3 Per-image cost in cycles (measured)

`(234 638 − ε_init) / 16 ≈ 14 600` cycles per image. Decomposition
(approximate, from `+verbose` traces):

| component                                                     | per-image cycles |
| ------------------------------------------------------------- | ---------------: |
| 4 × program_hidden_batch (32 cfg writes + threshold writes)   | ~9 600 |
| 4 × run_inference (XIN + 1-shot poll + YOUT read + CTRL clear)| ~1 200 |
| Layer-2 software popcount + argmax over 10 classes            | ~3 600 |
| GPIO emit + per-image sentinel                                | ~80   |
| Loop bookkeeping                                              | ~120  |

Tile programming dominates (~66 %). A smaller-cfg-traffic structure
(e.g., processing all 16 images for batch k before reprogramming for
batch k+1) would cut total cfg traffic by 4× but is out of scope for
the brief. Phase 4 may revisit when measuring activity-aware power on
the SoC.

## 5. Testbench — `tb/tb_soc_bnn.sv`

- Instantiates `soc_top` with `INIT_HEX = "firmware/inference/firmware.hex"`.
- Hierarchically preloads the 16 packed images into `dut.u_dmem.mem[0..31]`
  AFTER reset deassertion (DMEM's `initial` block already zeros it at sim
  time 0). Two 32-bit words per image: word `2i` = bits [31:0] of the 49-b
  packed input, word `2i+1` = bits [63:32] (high 15 bits zero by
  PAD_INPUT_BITS).
- Loads the 16 expected classifications from `tb/tb_bnn_expected.hex` into
  a SystemVerilog reg array.
- Snoops the WB master bus for two address patterns:
  - `0x3000_0004` (GPIO_OUT) writes — latches the predicted byte.
  - `0x3000_0000` (GPIO_SIM_END) writes — `(data & 0xFFFF0000) ==
    0xC0FE0000` is a per-image sync; `data == 0xCAFEBABE` is final-done.
- 5 M-cycle timeout with last-256-WB-transactions trace dump on failure.
- Naming gotcha: SystemVerilog 2012 reserves `matches` as a pattern-match
  keyword, so the local match counter is named `match_n`.

```
TB output ⟶  cycle 14938  img[0]  pred=7  expected=7  OK
            cycle 29586  img[1]  pred=2  expected=2  OK
            …            (16 of 16)
            cycle 234638 BNN INFERENCE TEST: PASS (16/16) cycles=234638 xacts=40301
```

## 6. End-to-end results

| Gate                              | Origin           | Status |
| --------------------------------- | ---------------- | ------ |
| `scripts/check_soc_elab.sh`       | 3A port-list     | PASS   |
| `scripts/run_tb_wb_tile_wrapper.sh` | 3B wrapper TB  | PASS (10/10) |
| `scripts/run_soc_smoke.sh`        | 3C smoke TB      | PASS (102 cyc, 14 xacts) |
| `scripts/run_soc_bnn.sh`          | **3D this session** | **PASS (16/16, 234 638 cyc, 40 301 xacts)** |

## 7. Spec deviations and what 3E needs to know

### 7.1 Preprocessing: v4 strict-`>` median, not v1 fixed-0.5

Documented in §2.2. The v1 fixed-0.5 threshold capped any classifier
(BNN or float MLP) at ~70 % accuracy because of the constant-zero
perimeter on MNIST. v4 strict-`>` per-image median replaced it.
**Reproducible across numpy and PyTorch byte-for-byte** (verified on
200 test images).

The firmware does not care how the input was binarized — it operates on
already-binarized 49-bit vectors that the testbench produces. So this
deviation lives entirely in `scripts/{train_bnn,bnn_reference,
gen_bnn_testdata}.py`. If a future session changes preprocessing again,
only those three files (and the test-set hex files they produce) need
updating; firmware, RTL, and TB are unchanged.

### 7.2 Layer 2 in software, not via a 5th tile evaluation

Per the brief's option (b) ("recompute pre-threshold sums in firmware …
this is simpler and correct"). Not actually a deviation — the brief
allowed it.

Implication for 3E (P&R / power): the tile is loaded with hidden-layer
weights only. There is no "output-layer cfg-write phase." Activity-aware
power measurements that profile the cfg interface should treat the
hidden-batch reprogramming pattern (4 reloads × 16-neuron-batches per
image) as the workload, not 5 reloads.

### 7.3 Read-back of writable wrapper registers

Inherited from 3B (PHASE3B_NOTES §2.3). Not used by this firmware — the
inference loop never reads back W/T/XIN — so the deviation has no
runtime effect here. The shadows still cost their ~700 wrapper flops.

### 7.4 Decode-miss still hangs the core

Inherited from 3C (PHASE3C_NOTES §7, item 6). The inference firmware
never accesses an unmapped region in the verified flow. If a future
session adds optional cycle-counter MMIO at e.g. `GPIO_BASE+0x10`, the
stride must stay inside the GPIO 16 B window or the master will hang.

### 7.5 `STACKADDR` still duplicated in `picorv32_wrapper.v` and
`firmware/inference/start.S`

Same as 3C. Both are pinned to `0x1000_1000`. Resizing DMEM requires
updating both.

## 8. Estimated complexity for Session 3E (SoC P&R)

Refining 3C's 6–10 h estimate now that the SoC is known to be
~5–10× the cell count of the tile and dominated by IMEM/DMEM register
files:

| 3E task                                                | Estimate | Notes |
| ------------------------------------------------------ | -------- | ----- |
| Wire `soc_top.v` into a LibreLane config              | 1 h      | Reuse `flow/common/tile.sdc` as a starting SDC; clock period 10 ns. |
| Initial synth + STA pass (single corner)              | 2–3 h wall | The SoC's clock tree is ~5× larger than the tile's; synth itself is fast but timing-driven elaboration of the IMEM/DMEM regfiles will be the bottleneck. |
| Floorplan + place + route                              | 4–8 h wall | The 100 K-flop register file SoC is congestion-prone. Likely needs `--save-views` between stages and at least one congestion-driven re-place if the first attempt routes poorly. |
| IMEM init mechanism inside LibreLane                   | 1 h      | Pick between (a) `$readmemh` in `initial` and let synth capture as constants, (b) a generated separate ROM module from the firmware hex, (c) vendor BRAM init. (a) is cheapest if synth handles it; otherwise (b). |
| All-corner STA + activity-aware power on the BNN VCD  | 2–3 h wall | Reuse Phase-2C's SAIF/VCD methodology (`scripts/sta_power_one_corner.tcl`); the VCD will be longer (235 K cycles) so size-on-disk is a concern (~1 GB compressed). |
| Notes file + commit                                    | 30 min   |        |
| **Total**                                              | **~10–15 h** of focused work + LibreLane wall-clock | |

Risk: **medium–high**. The 100 K-flop SoC is the first real test of
the no-OpenRAM accounting from the architecture spec. Memory pressure
on WSL (13 GiB) will be the main worry — Phase 2 tile flows peaked at
~6 GiB; a 5–10× larger design on the same flow could push close to the
limit. If routing OOMs, the fallback is to reduce IMEM/DMEM size in
`soc_top.v`'s parameters (which are already a one-line edit per spec
§7.1) and rerun. The functional firmware fits well under the reduced
sizes — 1.5 KB code+rodata easily fits in a 4 KB IMEM.

## 9. Reproduction

```bash
source scripts/env.sh

# All four gates in dependency order:
scripts/check_soc_elab.sh             # 3A port-list
scripts/run_tb_wb_tile_wrapper.sh     # 3B wrapper TB (PASS 10/10)
scripts/run_soc_smoke.sh              # 3C smoke TB (PASS 102 cycles)
scripts/run_soc_bnn.sh --skip-train   # 3D end-to-end (PASS 16/16)
```

The first invocation of `run_soc_bnn.sh` without `--skip-train` will
download MNIST (~12 MB) into `data/mnist/` and train the BNN
(~3–5 min on 6-core CPU). Subsequent `--skip-train` runs reuse
`data/bnn_weights.npz` and complete the full end-to-end pipeline in
under 30 seconds.

To regenerate firmware artifacts only (e.g., after editing `main.c`):

```bash
python3 scripts/weights_to_c.py
make -C firmware/inference clean all
```

Verbose simulation trace + VCD dump:

```bash
vvp /tmp/tb_soc_bnn +vcd        # → /tmp/tb_soc_bnn.vcd
```
