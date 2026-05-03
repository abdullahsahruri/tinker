# Phase 2 Session B — tile-level synthesis comparison

Slow corner: `max_ss_100C_1v60`. CLOCK_PERIOD = 10.0 ns (target 100 MHz). All four runs use SYNTH_STRATEGY = AREA 0, FP_CORE_UTIL = 35, PL_TARGET_DENSITY_PCT = 55, identical SDC (`flow/common/tile.sdc`). Only the RTL differs across runs.

| Variant | Cells | Area (µm²) | Fmax slow (MHz) | Fmax nom (MHz) | Power (µW) | DRC | LVS |
|---|---:|---:|---:|---:|---:|---:|---:|
| TLG hc | 7184 | 116049.00 | 89.02 | 146.12 | 26637.73 | 0 | 0 |
| TLG ld | 22125 | 320367.00 | 73.81 | 130.41 | 64565.99 | 0 | 0 |
| handopt hc | 10481 | 131297.00 | 86.98 | 168.14 | 37064.48 | 0 | 0 |
| handopt ld | 21464 | 305300.00 | 77.51 | 131.75 | 167858.38 | 0 | 0 |

## Power decomposition (µW, nominal corner)

| Variant | Internal | Switching | Leakage | Total |
|---|---:|---:|---:|---:|
| TLG hc | 14245.60 | 12392.02 | 0.1085 | 26637.73 |
| TLG ld | 34599.49 | 29966.19 | 0.3154 | 64565.99 |
| handopt hc | 19420.88 | 17643.46 | 0.1369 | 37064.48 |
| handopt ld | 84332.53 | 83525.55 | 0.3052 | 167858.38 |

## Relative comparisons

Sign convention: **positive = first variant is better** (smaller area, fewer cells, higher Fmax, lower power).

| Comparison | ΔCells | ΔArea | ΔFmax (slow) | ΔPower |
|---|---:|---:|---:|---:|
| TLG hc vs handopt hc | 31.5% | 11.6% | 2.4% | 28.1% |
| TLG ld vs handopt ld | -3.1% | -4.9% | -4.8% | 61.5% |
| TLG ld vs TLG hc | -208.0% | -176.1% | -17.1% | -142.4% |
| handopt ld vs handopt hc | -104.8% | -132.5% | -10.9% | -352.9% |

Comparison rationale:

- **TLG hc vs handopt hc** — Same logic-style isolation — both hardcoded, both no regfile, synthesis methodology only.
- **TLG ld vs handopt ld** — Realistic comparison — both programmable, methodology cost with the regfile present in both.
- **TLG ld vs TLG hc** — Programmability cost on the TLG path.
- **handopt ld vs handopt hc** — Programmability cost on the adder-tree path.
