# Phase 2C — activity-aware power summary

Corner: `max_ff_n40C_1v95` (the corner LibreLane reports as the headline `power__total` metric).

Workload: 1024 random-uniform 64-bit input vectors at the 1+2 cadence (1 cycle x_valid + 2 idle, 3 cycles per vector). Loadable variants programmed with the seed's weight set before vector replay (cfg-included).


## Per-(variant, seed) results

| variant | seed | act. power (mW) | default power (mW) | ratio (act/def) |
|---|---:|---:|---:|---:|
| tlg_hc | 0 | 72.995 | 26.638 | 2.74× |
| tlg_hc | 1 | 73.882 | 27.364 | 2.70× |
| tlg_hc | 2 | 72.190 | 26.901 | 2.68× |
| tlg_ld | 0 | 360.464 | 64.566 | 5.58× |
| tlg_ld | 1 | 359.158 | 64.566 | 5.56× |
| tlg_ld | 2 | 358.920 | 64.566 | 5.56× |
| handopt_hc | 0 | 355.435 | 37.064 | 9.59× |
| handopt_hc | 1 | 382.151 | 41.181 | 9.28× |
| handopt_hc | 2 | 372.260 | 39.554 | 9.41× |
| handopt_ld | 0 | 706.267 | 167.858 | 4.21× |
| handopt_ld | 1 | 706.432 | 167.858 | 4.21× |
| handopt_ld | 2 | 704.951 | 167.858 | 4.20× |

## Aggregate per variant (mean ± stdev across 3 seeds)

| variant | N | act. power (mW) | act. ratio (act/def) | switching share | internal share |
|---|---:|---:|---:|---:|---:|
| tlg_hc | 3 | 73.02 ± 0.85 | 2.708 ± 0.029 | 49.5% | 50.5% |
| tlg_ld | 3 | 359.51 ± 0.83 | 5.568 ± 0.013 | 50.1% | 49.9% |
| handopt_hc | 3 | 369.95 ± 13.51 | 9.427 ± 0.156 | 47.8% | 52.2% |
| handopt_ld | 3 | 705.88 ± 0.81 | 4.205 ± 0.005 | 51.7% | 48.3% |

## Headline TLG advantages under activity-aware power

Sign convention: positive = TLG wins. Advantage = (handopt − tlg) / handopt × 100%.

| pair | TLG mean (mW) | handopt mean (mW) | TLG advantage (mean) | seed-0 (single sample) |
|---|---:|---:|---:|---:|
| **TLG hc vs handopt hc** | 73.02 | 369.95 | **80.25% ± 0.68%** | 79.46% |
| **TLG ld vs handopt ld** | 359.51 | 705.88 | **49.07% ± 0.10%** | 48.96% |

## Single-seed → 3-seed delta on the activity-aware headlines (parallels the 2B.5 §4.3 table)

| comparison | 2C seed-0 | 2C 3-seed mean | movement |
|---|---:|---:|---|
| TLG hc vs handopt hc — power | 79.46% | 80.25% ± 0.68% | widens (+0.78 pp) |
| TLG ld vs handopt ld — power | 48.96% | 49.07% ± 0.10% | stable (+0.11 pp) |

## Default-activity (2B.5) vs activity-aware (2C) — TLG advantage by methodology

Default-activity numbers are 2B.5's published results (`power__total` from the existing post-route metrics.json). Activity-aware are this session.

| pair | default-activity (2B.5) | activity-aware (2C) | movement |
|---|---:|---:|---|
| **TLG hc vs handopt hc** | 31.22% ± 2.79% | 80.25% ± 0.68% | **WIDENS** (+49.02 pp) |
| **TLG ld vs handopt ld** | 61.54% ± 0.00% | 49.07% ± 0.10% | **SHRINKS** (-12.47 pp) |

## Variance comparison vs 2B.5

2B.5 default-activity power CV (across 3 hc seeds):
- TLG hc: 1.4%
- handopt hc: 5.3%

Phase 2C activity-aware power CV (across 3 hc seeds):

- tlg_hc: 1.16%
- handopt_hc: 3.65%

Phase 2C activity-aware power CV (across 3 ld weight programs):

- tlg_ld: 0.23%
- handopt_ld: 0.11%
