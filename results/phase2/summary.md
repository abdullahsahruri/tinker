# Phase 2 Session B / B.5 — tile-level synthesis comparison

Slow corner: `max_ss_100C_1v60`. CLOCK_PERIOD = 10.0 ns (target 100 MHz). All runs use SYNTH_STRATEGY = AREA 0, FP_CORE_UTIL = 35, PL_TARGET_DENSITY_PCT = 55, identical SDC (`flow/common/tile.sdc`). Only the RTL differs across runs.

Hardcoded variants are run for **3 weight seeds** (seed_id 0/1/2). Loadable variants are run for seed_id 0 only — their RTL is seed-invariant by construction (no weight constants in the file), so re-running them on additional weight seeds would produce identical metrics.

| Variant | N | Cells (µ ± σ) | Area µm² (µ ± σ) | Fmax slow MHz (µ ± σ) | Power µW (µ ± σ) | DRC | LVS |
|---|---:|---:|---:|---:|---:|---:|---:|
| TLG hc | 3 | 7153 ± 30 | 116464.67 ± 1150.28 | 87.77 ± 1.71 | 26967.55 ± 367.73 | 0 | 0 |
| TLG ld | 1 | 22125 | 320367.00 | 73.81 | 64565.99 | 0 | 0 |
| handopt hc | 3 | 10522 ± 44 | 133014.67 ± 1748.26 | 82.93 ± 4.51 | 39266.50 ± 2073.22 | 0 | 0 |
| handopt ld | 1 | 21464 | 305300.00 | 77.51 | 167858.38 | 0 | 0 |

## Per-seed detail

| Variant | Seed | Cells | Area (µm²) | Fmax slow (MHz) | Power (µW) | WS slow (ns) | DRC | LVS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| TLG hc | 0 | 7184 | 116049.00 | 89.02 | 26637.73 | -1.233 | 0 | 0 |
| TLG hc | 1 | 7150 | 117765.00 | 85.82 | 27364.06 | -1.652 | 0 | 0 |
| TLG hc | 2 | 7124 | 115580.00 | 88.46 | 26900.87 | -1.305 | 0 | 0 |
| TLG ld | 0 | 22125 | 320367.00 | 73.81 | 64565.99 | -3.548 | 0 | 0 |
| handopt hc | 0 | 10481 | 131297.00 | 86.98 | 37064.48 | -1.498 | 0 | 0 |
| handopt hc | 1 | 10569 | 132955.00 | 78.06 | 41180.89 | -2.810 | 0 | 0 |
| handopt hc | 2 | 10516 | 134792.00 | 83.77 | 39554.13 | -1.938 | 0 | 0 |
| handopt ld | 0 | 21464 | 305300.00 | 77.51 | 167858.38 | -2.902 | 0 | 0 |

## Power decomposition (mean µW, nominal corner)

| Variant | N | Internal | Switching | Leakage | Total |
|---|---:|---:|---:|---:|---:|
| TLG hc | 3 | 14370.47 ± 218.16 | 12596.97 ± 182.42 | 0.1089 ± 0.0014 | 26967.55 ± 367.73 |
| TLG ld | 1 | 34599.49 | 29966.19 | 0.3154 | 64565.99 |
| handopt hc | 3 | 20431.58 ± 1185.52 | 18834.79 ± 1031.81 | 0.1383 ± 0.0012 | 39266.50 ± 2073.22 |
| handopt ld | 1 | 84332.53 | 83525.55 | 0.3052 | 167858.38 |

## Relative comparisons (means)

Sign convention: **positive = first variant is better** (smaller area, fewer cells, higher Fmax, lower power). All comparisons are taken between per-variant means; for hardcoded variants this is over 3 seeds, for loadable over 1 seed.

| Comparison | ΔCells | ΔArea | ΔFmax (slow) | ΔPower |
|---|---:|---:|---:|---:|
| TLG hc vs handopt hc | 32.0% | 12.4% | 5.8% | 31.3% |
| TLG ld vs handopt ld | -3.1% | -4.9% | -4.8% | 61.5% |
| TLG ld vs TLG hc | -209.3% | -175.1% | -15.9% | -139.4% |
| handopt ld vs handopt hc | -104.0% | -129.5% | -6.5% | -327.5% |

Comparison rationale:

- **TLG hc vs handopt hc** — Same logic-style isolation — both hardcoded, both no regfile, synthesis methodology only.
- **TLG ld vs handopt ld** — Realistic comparison — both programmable, methodology cost with the regfile present in both.
- **TLG ld vs TLG hc** — Programmability cost on the TLG path.
- **handopt ld vs handopt hc** — Programmability cost on the adder-tree path.
