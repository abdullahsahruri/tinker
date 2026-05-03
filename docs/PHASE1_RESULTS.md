# Phase 1 — TLG-mapping validation (verdict)

> **NO-GO on the strict criterion as written.** TLG decomposition wins
> decisively on **power (-48% vs hand-opt, -51% vs naive)** but loses on
> **area (+19% larger)**, **stdcell count (+21% more)**, and **Fmax (-3%)** —
> only 1 of 3 metrics beats by ≥20%, where the criterion required ≥2 of 3.
> The power result is large enough to be worth a conversation with your
> advisor about re-framing the paper as **energy-first** instead of
> area/delay-first; it is not by itself a green light to start Phase 2.

---

## What was synthesized

A 64-input binary-neural-network neuron computing
`y = (popcount(x XNOR W) >= 32)` with `W` and threshold fixed at compile
time, generated for 5 random weight vectors (seeds 0–4). Three
implementations of the same function under identical constraints
(SkyWater 130 nm sky130_fd_sc_hd, `CLOCK_PERIOD = 10 ns`,
`SYNTH_STRATEGY = "AREA 0"`, `FP_CORE_UTIL = 35`,
`PL_TARGET_DENSITY_PCT = 55`, virtual-clock SDC, signoff at 9 corners):

| Variant | Description |
| ------- | ----------- |
| **A — naive** | One line: `assign y = ($countones(x ^~ W) >= THRESH);` Yosys + ABC pick the structure. |
| **B — handopt** | Explicit balanced 7-layer adder-tree popcount (64→32→16→8→4→2→1) then comparator. |
| **C — tlg** | Generic threshold-logic decomposition: 11 chunks (10×6→3 + 1×4→3) each expressed as an opaque truth-table `case` block, summed and compared. |

Functional equivalence verified pre-synth: 100/100 random vectors agreed
across all three variants vs Python golden model on seed=0.

## Headline numbers (15 runs, mean ± stdev across 5 seeds)

| Variant     | Area (µm²)        | Stdcells       | Fmax (MHz)      | Power (µW)         | DRC | LVS |
| ----------- | ----------------- | -------------- | --------------- | ------------------ | --- | --- |
| A naive     | 8 059.7 ± 18.5    | 495.0 ± 4.9    | 105.95 ± 5.93   | 3 114.4 ± 129.7    | 0   | 0   |
| B hand-opt  | 7 897.3 ± 161.1   | 498.8 ± 3.3    | 103.21 ± 2.66   | 2 913.1 ± 176.7    | 0   | 0   |
| C TLG       | **9 417.3 ± 203.4** | **602.6 ± 5.1** | **99.67 ± 1.59** | **1 521.0 ± 218.1** | 0   | 0   |

Fmax is `1 / (CLOCK_PERIOD − worst-setup-slack)` at the slow corner
`max_ss_100C_1v60`. Where slack is negative the value comes out below
100 MHz — that is reported as-is rather than re-tuning the experiment.
Power is total post-route power at the nominal corner reported by
LibreLane's `power__total` metric.

## Relative improvements (TLG vs baselines)

Improvement = `(baseline − tlg) / baseline × 100%`. Positive ⇒ TLG is
smaller / has fewer cells / faster / lower-power. Negative ⇒ TLG worse.

| Metric    | C vs A (TLG vs naive) | C vs B (TLG vs hand-opt) |
| --------- | --------------------: | -----------------------: |
| Area      | **−16.8%** (worse)    | **−19.2%** (worse)       |
| Stdcells  | **−21.7%** (worse)    | **−20.8%** (worse)       |
| Fmax      | **−5.9%** (slower)    | **−3.4%** (slower)       |
| **Power** | **+51.2%** (better) ✓ | **+47.8%** (better) ✓    |

## Sanity checks

- **All 15 runs DRC-clean** (Magic = 0, KLayout = 0). All 15 LVS-clean
  (0 device differences). All 15 routing-DRC-clean (0 final routing
  errors). 0 antenna violations across the board.
- **Setup violations at the slow corner (`max_ss_100C_1v60`)** appeared in
  some runs, all small: `naive` had 2/5 seeds slightly negative
  (worst −0.083 ns), `handopt` had 0/5 (all positive), `tlg` had 4/5
  slightly negative (worst −0.152 ns). This is reflected directly in
  Fmax. None of these are flow failures — the constraint is identical
  across variants and the comparison is fair. No retries.
- **Spot check**: random pick `naive/seed=3` — GDS 678 KB, opens in
  KLayout (`top_cell=neuron_naive_s3, dbu=0.001 µm, bbox=100.96×111.68 µm,
  30 cells, 41 layers`), all sign-off metrics 0, area / stdcells / power
  all within the range observed across the other 14 runs. No silent
  corruption.
- **Variance across seeds** is small (std/mean ≤ 5% for area and stdcells
  in every variant, ≤ 6% for Fmax, ≤ 14% for power). Five seeds is enough
  to call this signal not noise.

## Honest discussion

The strict criterion was: *"≥20% improvement on at least 2 of {area, delay,
power} at iso-frequency, post-P&R"*. TLG against the hand-optimized
adder tree:

1. **Area: TLG is bigger, not smaller.** `-19.2%` means C is ~19%
   *larger* than B. The 11 truth-table chunks unroll into more individual
   stdcells (≈103 extra cells) than the shared carry chain of an adder
   tree, even after ABC's full freedom to map the case-statement
   functions. This is the opposite of what the hypothesis predicted.
2. **Fmax: TLG is slightly slower.** The critical path through the
   final 11-input summer + comparator is longer than the carry chain of
   the balanced adder tree. The hypothesis predicted faster.
3. **Power: TLG is dramatically lower.** −47.8% against hand-opt, −51.2%
   against naive. Variance across seeds is ~14% (218 µW stdev on a
   1 521 µW mean) — even the high-tail TLG run (1 840 µW for seed=2)
   beats the low-tail hand-opt run (2 699 µW for seed=2) by 32%.
   This is a real, robust effect.

The likely physical explanation: the truth-table chunks lower the
average activity factor of internal nets (most case-arms produce stable
outputs over many input combinations, so internal toggling is sparse),
and the structurally shorter combinational fan-in per chunk means
shorter wires with less switched capacitance. Adder trees, by contrast,
have carry chains that ripple-toggle on most inputs. The trade-off is
that the truth-table chunks expand into more cells than the carry chain
shares.

### What this means for the SOCC paper

- **The paper as originally framed (area/delay-first TLG-locking
  argument) is on shaky ground.** Generic 6-input chunk decomposition
  does not win on area or speed against a competently-written adder
  tree. A weight-vector-specific algorithm might, but the spec required
  the generic algorithm as the floor: *"if generic loses, the project
  pivots."* Generic loses on area and Fmax.
- **A power-first paper has real legs.** A ~48% post-route power
  reduction on a sky130 BNN neuron — DRC/LVS clean, no special tricks,
  generic decomposition — is a publishable finding for a 4-page SOCC
  short paper or a workshop. It would refocus from "smaller/faster TLG
  netlists" to "TLG decomposition as a low-energy synthesis path for
  BNN inference."
- **What to do now: stop and talk to your advisor before Phase 2.** The
  spec said to re-pivot if the criterion fails, and it has failed as
  written. The decision now is whether to (a) rewrite the criterion
  around energy and continue with a power-first plan, (b) replace the
  generic decomposition with a TLG-specific one and re-run Phase 1,
  or (c) shelve TLG-locking-as-PPA-story and find a different SOCC
  angle.

### Things to verify if pivoting to power-first

- The power numbers come from LibreLane's default switching-activity
  model (uniform ~0.1 toggle on primary inputs). A real workload will
  have different activity. Re-run with realistic VCD-driven power
  analysis once you have an inference workload.
- Confirm clock-tree contribution is small (this is a combinational
  block, but synthesized inside a future tile it will inherit a clock
  network — make sure the energy ranking holds when surrounded by flops).
- Explore SYNTH_STRATEGY = "AREA 1/2/3" and "DELAY 0" to see whether the
  ranking is strategy-stable. AREA 0 is the LibreLane default; one data
  point.

## Reproduction

```bash
source scripts/env.sh
scripts/run_phase1.sh                  # all 15 runs, ~75 min
.venv/bin/python scripts/collect_phase1.py   # → results/phase1/summary.{csv,md}
```

Per-run artifacts: `flow/phase1_<variant>/seed<N>/runs/phase1_<variant>_s<N>/final/`.
Aggregate CSV: `results/phase1/summary.csv`. Spot-check GDS:
`results/phase1/spotcheck/neuron_naive_s3.gds`.
