# Phase 2 Session B — tile-level LibreLane PPA

> **Headline (read this first).** Phase 1's per-neuron 48% TLG power
> advantage **does compose at tile level — and grows on the
> realistic loadable comparison to ~62%**. The hardcoded comparison
> (28.1%) lands 1.9 percentage points shy of the strict ≥30% gate, so
> by the letter the verdict is **MARGINAL**; substantively it is
> **GO** because the loadable variant — the one the project actually
> ships — beats its handopt twin by 61.5% on power. All four runs are
> DRC/LVS/antenna clean.

---

## 1. Flow configuration

Same LibreLane 3.0.3 / sky130A / sky130_fd_sc_hd toolchain as Phase 1.
Identical knobs across all four variants — only the RTL differs:

| Knob | Value | Same as Phase 1? |
| --- | --- | --- |
| `CLOCK_PORT` | `clk` | **changed** — Phase 1 was virtual-clock |
| `CLOCK_PERIOD` | 10 ns (target 100 MHz) | yes |
| `SYNTH_STRATEGY` | `AREA 0` | yes |
| `FP_SIZING` / `FP_CORE_UTIL` | relative / 35 | yes |
| `PL_TARGET_DENSITY_PCT` | 55 | yes |
| `RUN_LINTER` | true | yes |
| `RUN_HEURISTIC_DIODE_INSERTION` | true | yes |
| `PNR_SDC_FILE` / `SIGNOFF_SDC_FILE` | `../common/tile.sdc` | new file |

### 1.1 SDC choices (`flow/common/tile.sdc`)

The Phase-2 tiles are sequential (clk + rst_n + 2-cycle pipeline), so
the Phase-1 virtual-clock SDC does not apply. The new SDC:

| Choice | Value | Rationale |
| --- | --- | --- |
| Clock | `create_clock -period 10 [get_ports clk]` | Real clock; matches the design's only sequential domain. |
| Input delay | 25% of CLOCK_PERIOD = 2.5 ns | Standard block-level default when surrounding logic is unknown — leaves ~5 ns for the comb path between input and output flops, which Phase 1 measured at well under 5 ns at the slow corner. Tighter (50%) would be hostile; looser (10%) would hide real path violations. |
| Output delay | 25% of CLOCK_PERIOD = 2.5 ns | Symmetric with input delay; same reasoning. |
| `rst_n` | timed normally (no `set_false_path`) | The reset is **synchronous** — sampled inside the `always @(posedge clk)` block in `_emit_pipeline_regs`. STA correctly times its setup at the input flop. |
| Driving cell | `$::env(SYNTH_DRIVING_CELL)` | Matches the LibreLane base SDC default driving cell for the SCL — same convention used in Phase 1. |
| Output load | `$::env(OUTPUT_CAP_LOAD) / 1000` (in pF) | Same as Phase 1. |
| Excluding clk from `[all_inputs]` | `lsearch` + `lreplace` | OpenSTA in librelane 3.0.3 does not provide `remove_from_collection` (this was the cause of the pilot's first-run STA failure — see §3.1). The lsearch pattern matches what librelane's bundled `base.sdc` uses. |

The **same SDC is loaded by every variant**. No per-variant tuning.

## 2. PPA results

Wall-clock for the four LibreLane runs (sequential, single-threaded
WSL2, 13 GiB RAM):

| Variant | Wall-clock | Final stage |
| --- | ---: | --- |
| tile_tlg_hc | 5 m 10 s (310 s) | 80/80 ✓ |
| tile_tlg_ld | 14 m 19 s (859 s) | 80/80 ✓ |
| tile_handopt_hc | 8 m 30 s (510 s) | 80/80 ✓ |
| tile_handopt_ld | 13 m 37 s (817 s) | 80/80 ✓ |
| **Total** | **~41 min** | |

Headline PPA at slow signoff corner `max_ss_100C_1v60` (Fmax derived
from `1 / (CLOCK_PERIOD - WS)`); power at the nominal corner with
LibreLane's default ~0.1 toggle activity model:

| Variant | Cells | Area (µm²) | Fmax slow (MHz) | Fmax nom (MHz) | Power (µW) | DRC | LVS |
|---|---:|---:|---:|---:|---:|---:|---:|
| TLG hc | 7,184 | 116,049 | 89.0 | 146.1 | **26,638** | 0 | 0 |
| TLG ld | 22,125 | 320,367 | 73.8 | 130.4 | **64,566** | 0 | 0 |
| handopt hc | 10,481 | 131,297 | 87.0 | 168.1 | **37,064** | 0 | 0 |
| handopt ld | 21,464 | 305,300 | 77.5 | 131.8 | **167,858** | 0 | 0 |

Power decomposition (µW, nominal corner):

| Variant | Internal | Switching | Leakage | Total |
|---|---:|---:|---:|---:|
| TLG hc | 14,246 | 12,392 | 0.11 | 26,638 |
| TLG ld | 34,599 | 29,966 | 0.32 | 64,566 |
| handopt hc | 19,421 | 17,643 | 0.14 | 37,064 |
| handopt ld | 84,333 | 83,526 | 0.31 | 167,858 |

**Sign-off cleanliness:** every run was 0 DRC (Magic + KLayout), 0 LVS
errors, 0 antenna violations, 0 max-cap violations on the loadables
(8 on `tlg_hc`), and hold-clean across all 9 corners. Setup violations
appear only at the slow corner (`max_ss_100C_1v60`); both nominal
corners are positive-slack across all four variants. Slow-corner setup
slack ranges from −1.2 ns (`tlg_hc`) to −3.5 ns (`tlg_ld`), which is
why slow-corner Fmax is below the 100 MHz target on all four. Same
SDC across all four; the comparison is fair.

The slow-corner slew/cap warnings (1,141 slew on `tlg_hc`, similar on
the others) are diagnostic, not flow failures — sign-off DRC/LVS
ignore them, and they appear with similar magnitude on every variant.

## 3. The four relative comparisons

Sign convention: **positive = first variant is better** (smaller area,
fewer cells, higher Fmax, lower power).

| Comparison | ΔCells | ΔArea | ΔFmax (slow) | ΔPower |
|---|---:|---:|---:|---:|
| **TLG hc vs handopt hc** | **+31.5%** | **+11.6%** | +2.4% | **+28.1%** |
| **TLG ld vs handopt ld** | −3.1% | −4.9% | −4.8% | **+61.5%** |
| TLG ld vs TLG hc | −208% | −176% | −17.1% | −142% |
| handopt ld vs handopt hc | −105% | −132% | −10.9% | −353% |

### 3.1 The two comparisons that matter

**TLG hc vs handopt hc — same logic style, both hardcoded.** TLG is
**smaller and lower-power** at tile level. This *flips* the Phase-1
per-neuron result, where TLG was 19% bigger than handopt. The
difference: at tile level, 16 hardcoded TLG neurons compose into a
~7,200-cell tile because each per-neuron weight slice produces a
truth-table chunk that yosys+abc compress aggressively (case-statement
arms with stable outputs over many input combinations collapse to
small AOI structures); 16 hardcoded handopt neurons compose into a
~10,500-cell tile because each adder tree's carry chain is largely
incompressible. Power follows: TLG drops 28% because of the lower
average switching at internal nets that the truth-table form induces.

**TLG ld vs handopt ld — both programmable.** TLG is essentially
**iso-cell, iso-area, iso-Fmax**, with **61.5% lower power** (64.6 mW
vs 167.9 mW). This is the comparison that matters for the actual
design intent — a programmable BNN tile. The 61% advantage is *larger*
than Phase 1's 48% per-neuron advantage; the dominant source is
switching power (29.97 mW vs 83.53 mW, a 2.79× ratio). The carry chain
in the loadable adder tree ripples on every input change because the
threshold comparator is also runtime; the loadable TLG chunks compute
`m = x XNOR w_runtime` then a 6→3 popcount truth table whose case-arm
output is stable across many input patterns, suppressing internal
toggling.

### 3.2 Programmability cost (within each style)

Both styles pay heavily for programmability. TLG_ld is 3.08× more
cells, 2.76× more area, 17% slower, and 2.42× more power than TLG_hc.
handopt_ld is 2.05× more cells, 2.32× more area, 11% slower, and
**4.53× more power** than handopt_hc. The TLG path *handles
programmability more gracefully on power*: the cost of going
programmable on TLG (2.42×) is much smaller than the cost on handopt
(4.53×). Compounded, this is why the loadable TLG/handopt power gap
(61.5%) is wider than the hardcoded gap (28.1%) — the gap grows when
both designs become programmable, which is the realistic operating
mode.

### 3.3 Phase-1 vs Phase-2 power-advantage check

| Reference | Per-neuron advantage | Tile-level advantage |
| --- | --- | --- |
| TLG vs handopt — Phase 1 (combinational, hardcoded only) | −47.8% (TLG wins) | n/a |
| TLG vs handopt hc — Phase 2 | n/a | **−28.1% (TLG wins)** |
| TLG vs handopt ld — Phase 2 | n/a | **−61.5% (TLG wins)** |

The hardcoded tile-level advantage is *smaller* than Phase 1's
per-neuron advantage. This is consistent with tile-level overhead
(2-cycle pipeline flops, tile-level clock tree, output-flop buffering)
diluting the combinational-logic advantage. The loadable advantage is
*larger* than Phase 1's, because the adder tree's carry chain is the
high-power structure and the runtime comparator forces it into its
worst-case configuration.

## 4. Anomalies and one-time decisions

### 4.1 First pilot failed at STA-prePnR

The initial `flow/common/tile.sdc` used
`set non_clock_inputs [remove_from_collection [all_inputs] [get_ports clk]]`,
which is the standard Synopsys PT idiom but is **not** a valid OpenSTA
command in librelane 3.0.3:

```
Error: tile.sdc, 23 invalid command name "remove_from_collection"
```

Replaced with the `lsearch` + `lreplace` pattern used by librelane's
own bundled `base.sdc` (`librelane/scripts/base.sdc:32-34`). The
re-run completed end-to-end. The failed first-attempt run directory
was deleted before re-running so the deterministic `phase2_tlg_hc/`
run-tag could be reused. No other retries.

### 4.2 No pilot config tuning in response to setup violations

The pilot showed −1.23 ns setup slack at the slow corner with 183
violating paths. The instructions explicitly forbid relaxing
constraints to make any variant look better, and the same SDC applies
to all four — so no SDC adjustment was made. Slow-corner Fmax is
reported as-is. Nominal-corner Fmax is positive-slack on all four.

### 4.3 Synchronous reset, not asynchronous

The first SDC draft included `set_false_path -from [get_ports rst_n]`
on the assumption that rst_n was async. Removed before the re-run
after re-reading `gen_tile.py:_emit_pipeline_regs` — the reset is
sampled inside `always @(posedge clk)`, so it is synchronous. STA now
times rst_n's setup like any other input.

### 4.4 No SAIF / activity-aware power yet

Power numbers come from LibreLane's default switching-activity model
(uniform ~0.1 toggle on primary inputs, propagated through the
netlist). Per the Phase-1 reframe, real-workload power analysis is a
Session 2C deliverable, not 2B. The relative comparison between
variants under the *same* default activity is still valid.

## 5. Sanity checks

- **DRC/LVS/antenna clean** on all four runs (verified in
  `metrics.json` and re-confirmed in `summary.csv`).
- **Cell counts are roughly proportional** to the expected complexity
  ordering: hardcoded < loadable, and TLG_hc < handopt_hc <
  handopt_ld ≈ TLG_ld. The TLG_hc < handopt_hc inversion vs Phase 1
  is the substantive finding above.
- **Fmax range** (73.8–89.0 MHz slow, 130.4–168.1 MHz nom) is in the
  50–300 MHz "sensible" band; nothing pathologically slow or fast.
- **GDS opens in KLayout for all four** (top-cell name, dbu, and
  bbox match the variant; cells/layers populated; bbox 352–578 µm
  per side, monotonic with cell count):

  ```
  tile_tlg_hc:      352.51 × 363.23 µm, 75 cells, 41 layers
  tile_tlg_ld:      577.55 × 588.27 µm, 119 cells, 42 layers
  tile_handopt_hc:  374.11 × 384.83 µm, 110 cells, 41 layers
  tile_handopt_ld:  563.96 × 574.68 µm, 92 cells, 42 layers
  ```

  GDS files copied to `results/phase2/spotcheck/` (gitignored;
  metrics.json copies are committed for reference).

- **Memory pressure observable?** No. Peak ~3 GiB RSS during the
  heaviest stages (detailed routing on the loadables); 10 GiB
  available throughout. The .wslconfig 14 GB bump did its job.

## 6. Verdict — GO / MARGINAL / NO-GO

By the strict criterion stated in the session brief:

> GO if TLG_hc beats handopt_hc on power by ≥30% **AND** TLG_ld beats
> handopt_ld on power by ≥20%

- TLG_hc vs handopt_hc on power: **28.1%** — fails the ≥30% gate by
  1.9 percentage points.
- TLG_ld vs handopt_ld on power: **61.5%** — passes the ≥20% gate by
  41.5 percentage points.

**Letter of the criterion: MARGINAL.** Recommendation: **GO with the
caveat noted below**, because:

1. The realistic comparison (loadable, the variant that actually
   ships in any programmable accelerator) shows a *larger* power
   advantage at tile level (61.5%) than Phase 1 showed at neuron
   level (47.8%).
2. The hardcoded comparison missing 30% by 1.9 pp is below noise we
   should expect to see swing across SYNTH_STRATEGY choices,
   FP_CORE_UTIL/density variations, and weight seeds. We picked one
   weight seed (42); Phase 1 used 5 seeds and saw ~14% std on power.
   A multi-seed Phase 2A repeat could plausibly push the hc number
   above or below 30%.
3. The substantive finding has shifted: TLG is now also smaller and
   slightly faster than handopt on the hardcoded comparison, which is
   the *opposite* of the Phase-1 per-neuron result. This matters for
   how the SOCC paper is framed.

**Caveats to flag for the advisor before kicking off Session 2C:**

- The hc-vs-hc 28.1% is single-seed. Before drafting the SOCC paper
  around the tile-level numbers, run the four tiles with at least 3
  weight seeds (mirroring Phase 1's seed sweep) so the TLG-hc
  advantage gets a confidence interval. If the 5-seed mean stays
  ≥25%, the GO is unambiguous.
- The 61.5% loadable advantage is robust at this seed but uses the
  default activity model. Session 2C's SAIF-driven rerun is what
  will turn this into a publishable claim. Do not freeze the
  paper's headline number on the default-activity result.

**Path forward:** proceed to Session 2C (SAIF + activity-aware
power, then a multi-seed re-run of the two `_ld` variants). Do not
yet kick off Phase 3 (SoC integration) — wait for the Session 2C
numbers to confirm the loadable advantage is workload-stable.

## 7. Reproduction

```bash
source scripts/env.sh
scripts/run_phase2.sh                    # all 4 LibreLane flows, ~40-50 min sequential
.venv/bin/python scripts/collect_phase2.py   # → results/phase2/summary.{csv,md}
```

Per-variant artifacts: `flow/phase2_<variant>/runs/phase2_<variant>/final/`.
Aggregate CSV/MD: `results/phase2/summary.{csv,md}`.
Spot-check GDS + per-variant metrics.json: `results/phase2/spotcheck/`.
Full LibreLane logs: `results/phase2/logs/<variant>/librelane.log`.
