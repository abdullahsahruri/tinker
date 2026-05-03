# Phase 1 — synthesis comparison summary

Slow corner: `max_ss_100C_1v60`. CLOCK_PERIOD = 10.0 ns (target 100 MHz). All 15 runs use SYNTH_STRATEGY = AREA 0.

| Variant | Area (µm²) mean±std | Stdcells mean±std | Fmax (MHz) mean±std | Power (µW) mean±std | DRC | LVS |
|---|---|---|---|---|---|---|
| naive | 8059.73 ± 18.47 | 495.0 ± 4.9 | 105.95 ± 5.93 | 3114.36 ± 129.70 | 0 | 0 |
| handopt | 7897.32 ± 161.06 | 498.8 ± 3.3 | 103.21 ± 2.66 | 2913.10 ± 176.69 | 0 | 0 |
| tlg | 9417.28 ± 203.41 | 602.6 ± 5.1 | 99.67 ± 1.59 | 1521.05 ± 218.07 | 0 | 0 |

## Relative improvements (TLG vs baselines)

Improvement = `(baseline_mean - tlg_mean) / baseline_mean × 100%`. Positive ⇒ TLG is smaller / faster / lower-power.

| Metric | C vs A (TLG vs naive) | C vs B (TLG vs hand-opt) |
|---|---|---|
| Area | -16.8% | -19.2% |
| Stdcells | -21.7% | -20.8% |
| Fmax | -5.9% | -3.4% |
| Power | +51.2% | +47.8% |
