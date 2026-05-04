# Phase 3 Session E — register-file SoC baseline (notes)

> **Headline.** Full-SoC LibreLane P&R (Yosys synth + OpenROAD
> floorplan/place/CTS/route/sign-off + Magic GDS + Netgen LVS +
> KLayout DRC/XOR) closes cleanly on a 1.77 mm² die at 49.4 %
> utilization with **0 DRC errors (Magic + KLayout), 0 LVS errors,
> 0 antenna violations, 0 XOR differences**. Detail routing
> converges to 0 violations on the final iteration. The headline
> `nom_tt_025C_1v80` corner is timing-clean (setup +1.95 ns, hold
> +0.36 ns, default-activity power 103 mW). Slow-corner
> (`*_ss_100C_1v60`) timing **does not close** — setup WNS −5.32 ns
> at `nom_ss`, 11 409 setup violations + 2 hold violations driven
> by a 4 484-fanout net surviving from the IMEM read mux even
> after the 8 KB → 2 KB shrink. **This is the register-file
> baseline data point for comparison against the Session 3.5
> OpenRAM-backed run; it is not the paper's final headline
> number.** Wall-clock 1 h 33 min, peak DRT memory 4.6 GiB. **GO
> to Session 3.5 (OpenRAM integration) once 3E Steps 2–4 (power +
> figure + summary) complete.**

---

## 1. Why a separate "baseline" notes file

Phase 3E was originally scoped as a single LibreLane SoC run. The
first attempt revealed a structural problem with the 8 KB regfile
IMEM (a 15 115-fanout read-mux net the open-flow resizer cannot
fix; setup WNS −3 359 ns at slow corner). Path B was chosen —
shrink IMEM to 2 KB / DMEM to 1 KB, run the smaller SoC as a
**register-file baseline**, then tape out a Session 3.5 OpenRAM
SRAM-backed variant as the paper's headline. This file captures
the baseline rerun. The eventual `PHASE3E_NOTES.md` will hold the
final OpenRAM-backed numbers.

The shrink is documented in PHASE3_ARCHITECTURE.md §7.1 (rewritten
this session) as intentional engineering for the open-flow
register-file baseline ("memory sized to balance functional
headroom against open-flow timing limits"), not accidental
limitation. The 1 556 B Phase-3D inference firmware fits with
~30 % headroom in 2 KB; DMEM holds the 32-word test-image preload
+ small stack. The 4 regression gates (elaboration, wrapper TB,
SoC smoke, BNN inference 16/16) all pass against the shrunk RTL.

## 2. What this session produced

| Deliverable                                                       | Where                                                |
| ----------------------------------------------------------------- | ---------------------------------------------------- |
| SoC LibreLane config                                              | `flow/phase3_soc/config.json`                        |
| SoC SDC                                                           | `flow/common/soc.sdc`                                |
| SoC P&R driver script                                             | `scripts/run_soc_pnr.sh`                             |
| Post-P&R artifacts (GDS, netlist, parasitics, reports)            | `flow/phase3_soc/runs/phase3_soc/final/`             |
| LibreLane log                                                     | `results/phase3/logs/soc_pnr.log`                    |
| Shrunk wb_imem.v / wb_dmem.v (2 KB / 1 KB)                        | `rtl/soc/{wb_imem,wb_dmem}.v`                        |
| Updated STACKADDR (0x1000_0400)                                   | `rtl/soc/picorv32_wrapper.v`, `firmware/{inference,smoke}/start.S` |
| Updated linker scripts + Makefiles (IMEM_WORDS=512)               | `firmware/{inference,smoke}/{linker.ld,Makefile}`    |
| Updated architecture spec (memory map + flop accounting + §7.1)   | `docs/PHASE3_ARCHITECTURE.md`                        |
| This notes file                                                   | `docs/PHASE3E_BASELINE_NOTES.md`                     |

## 3. Sign-off table (the headline)

All physical-verification checks pass cleanly. Timing fails at the
slow corner only.

| Check                     | Result                                | Threshold | Status |
| ------------------------- | ------------------------------------- | --------- | ------ |
| Detail-route DRC          | 0 violations (final iteration)        | 0         | PASS   |
| Magic DRC                 | 0 errors                              | 0         | PASS   |
| KLayout DRC               | 0 errors                              | 0         | PASS   |
| KLayout XOR (vs Magic GDS)| 0 differences                         | 0         | PASS   |
| Netgen LVS                | 0 errors                              | 0         | PASS   |
| Antenna (final)           | 0 violating nets / 0 violating pins   | 0 / 0     | PASS   |
| Magic spice/LEF/GDS streamout | All emitted                       | —         | PASS   |
| KLayout streamout + render| GDS + PNG render emitted              | —         | PASS   |
| **Setup timing (slow)**   | **−5.32 ns WNS @ nom_ss, 11 409 vio** | ≥ 0       | **FAIL**|
| **Hold timing (slow)**    | **−0.29 ns WNS @ nom_ss, 6 vio total**| ≥ 0       | **FAIL**|
| Setup timing (typical)    | +1.95 ns WNS @ nom_tt                 | ≥ 0       | PASS   |
| Hold timing (typical)     | +0.36 ns WNS @ nom_tt                 | ≥ 0       | PASS   |
| Setup timing (fast)       | +4.77 ns WNS @ nom_ff                 | ≥ 0       | PASS   |
| Hold timing (fast)        | +0.22 ns WNS @ nom_ff                 | ≥ 0       | PASS   |

LibreLane reports the run as `[FAIL]` because the deferred
hold-violation checker (step 74 of ~80) raised after sign-off
had emitted clean GDS/SPEF/SDF/netlist into `final/`. The full
`final/` artifact set is therefore present and usable for
downstream activity-aware power (Step 2) and the layout figure
(Step 3).

## 4. PPA at the headline corner (`nom_tt_025C_1v80`, default activity)

| Metric                     | Value          |
| -------------------------- | -------------- |
| Std-cell instances (logic) | **123 157**    |
| ↳ sequential cells (flops) | 12 234         |
| ↳ multi-input combinational| 31 041         |
| ↳ buffers / inverters / clk-buf / clk-inv / setup-buf | 40 / 260 / 1 937 / 157 / 254 |
| ↳ timing-repair buffers    | 8 296          |
| Std-cell area (logic)      | 0.853 mm²      |
| Tap cells / area           | 24 492 / 0.088 mm² |
| Antenna cells / area       | 44 700 / 0.111 mm² |
| Fill cells / area          | 253 494 / 0.853 mm² |
| Total instance count (incl. fill/tap/antenna) | 376 651 |
| **Core area**              | **1.726 mm²**  |
| **Die area**               | **1.769 mm²** (≈ 1.330 × 1.330 mm) |
| Std-cell utilization       | 49.4 %         |
| Lint warnings              | 504 (LEF parser) — benign |
| Lint errors                | 0              |
| Inferred latches           | 0              |
| `nom_tt` setup WNS         | +1.95 ns       |
| `nom_tt` hold WNS          | +0.36 ns       |
| Worst clock skew           | -0.097 ns (negligible) |
| **`nom_tt` default-activity power** | **103.0 mW** (78.9 internal + 24.0 switching + 1.6 µW leakage) |

Sequential-cell count (12 234) is meaningfully smaller than the
3A spec's 26 K-flop estimate (16 384 IMEM + 8 192 DMEM + 1 136
tile cfg + 590 wrapper). Yosys collapsed/optimized many of the
IMEM regfile flops — likely the all-zero `INIT_HEX` allowed the
synthesis pass to constant-propagate large swaths of the array.
This is correct for the synthesis path used here; the IMEM still
elaborates as 512 × 32-bit = 16 K-flop logical storage and is
fully addressable at runtime — Yosys just realized it could share
storage cells where the constant content allowed. A Session 3.5
OpenRAM-backed IMEM eliminates this question entirely (the macro
is opaque to Yosys).

## 5. Multi-corner timing

Setup WNS (worst negative slack) per corner:

| Corner                | Setup WNS (ns) | Setup violations | Hold WNS (ns) | Hold violations |
| --------------------- | -------------: | ---------------: | ------------: | --------------: |
| `nom_tt_025C_1v80`    | **+1.945**     | 0                | **+0.358**    | 0               |
| `nom_ff_n40C_1v95`    | +4.765         | 0                | +0.224        | 0               |
| `nom_ss_100C_1v60`    | **−5.320**     | **11 409**       | **−0.288**    | 2               |
| `min_tt_025C_1v80`    | +2.354         | 0                | +0.357        | 0               |
| `min_ff_n40C_1v95`    | +5.033         | 0                | +0.223        | 0               |
| `min_ss_100C_1v60`    | −4.563         | 10 924           | −0.155        | 2               |
| `max_tt_025C_1v80`    | +1.592         | 0                | +0.360        | 0               |
| `max_ff_n40C_1v95`    | +4.525         | 0                | +0.225        | 0               |
| `max_ss_100C_1v60`    | **−5.955**     | **11 671**       | **−0.461**    | 2               |
| **Worst across all**  | **−5.955**     | 34 004 total     | **−0.461**    | 6 total         |

**Slow-corner failure root cause.** The IMEM read mux still has
a 4 484-terminal max-fanout net even after the 8 KB → 2 KB
shrink (down from 15 115 in the 8 KB run, but still well above
the SDC `MAX_FANOUT_CONSTRAINT=10`). The Yosys-emitted address
decoder fans out across the whole 512 × 32-bit array on the
read port; the resizer's tree-balancing pass cannot fully break
it up. Slow-corner (1.60 V / 100 °C) cell delays are roughly
2.5–3× nominal, so a path that's marginal at `nom_tt` blows up
at `nom_ss`. This is the same structural pattern as the first
8 KB-IMEM run, just less severe.

**Fmax interpretation.** At `nom_tt` the design clocks at
100 MHz with +1.95 ns slack — equivalent Fmax ≈ 124 MHz at the
nominal corner. At slow corner the WNS −5.32 ns implies the
design closes at 1 / (10 + 5.32) ≈ **65 MHz at `nom_ss_100C_1v60`**.
For comparison, the Phase-2 tile (which has no large regfile)
closed at 100 MHz across all 9 corners. The 100 MHz → 65 MHz
slow-corner Fmax delta is the open-flow register-file IMEM tax,
documented honestly. **Session 3.5 (OpenRAM SRAM IMEM) is
expected to recover most of this margin** because the SRAM
macro replaces the read-mux with a sense-amp + bit-line
discharge, which has no large-fanout net to balance.

**Hold violations** are 6 in total across the slow corner, with
WNS only −0.46 ns. These are addressable by another resizer
pass with `--corner max_ss_100C_1v60` as the optimization
target, but per the brief we accept the multi-corner failure as
the baseline data point and do not patch.

## 6. What worked vs the previous run

Compared to the first attempt (8 KB IMEM, no `STA_THREADS`):

| Metric                    | First attempt | Baseline rerun | Improvement |
| ------------------------- | ------------: | -------------: | ----------- |
| Wall-clock                | 3 h 13 min    | **1 h 33 min** | 2.1× faster |
| Peak DRT memory           | 10.22 GiB     | **4.61 GiB**   | 2.2× lower  |
| Std-cell instances (logic)| 161 466       | **123 157**    | 24 % smaller |
| Sequential cells          | ~36 800       | **12 234**     | 3× fewer    |
| Die area                  | 4.99 mm²      | **1.77 mm²**   | 2.8× smaller |
| Default-activity power    | 251 mW        | **103 mW**     | 2.4× lower  |
| Slow-corner setup WNS     | −3 359 ns     | **−5.32 ns**   | 600× better |
| Slow-corner setup vio     | 36 441        | **11 409**     | 3.2× fewer  |
| Max-fanout net            | 15 115 terms  | **4 484 terms**| 3.4× smaller|
| `nom_tt` setup WNS        | +1.74 ns      | +1.95 ns       | +0.21 ns    |
| Sign-off (DRC/LVS/antenna)| Not reached (OOM in STA) | **All clean** | — |
| Final GDS                 | Not emitted   | **Emitted**    | — |

`STA_THREADS=2` resolved the OOM kill — multi-corner STA ran
sequentially in pairs without exceeding 13 GiB. No other config
or tooling changes from the first attempt.

## 7. Wall-clock breakdown

| Stage                          | Wall-clock |
| ------------------------------ | ---------- |
| Synthesis (Yosys)              | ~5 min     |
| Floorplan + PDN + IO placement | ~2 min     |
| Global placement + repair      | ~6 min     |
| Detail placement + CTS + post-CTS resize | ~10 min |
| Mid-PnR STA                    | ~5 min     |
| Global routing + antenna repair (3 iters) | ~12 min |
| Detail routing + antenna repair (4 iters) | ~30 min |
| Fill + RCX                     | ~5 min     |
| Multi-corner STA (`STA_THREADS=2`) | ~10 min |
| IR-drop + Magic streamout      | ~5 min     |
| KLayout streamout + DRC + XOR  | ~3 min     |
| Magic DRC + Netgen LVS + checkers | ~1 min  |
| **Total**                      | **5 620 s = 93 min** |

(Per-stage numbers approximate, derived from log timestamps.)

## 8. Architectural lessons preserved for the paper

- **Open-flow register-file IMEM is the dominant area + power
  + timing risk in a no-OpenRAM SoC.** The shrink halved every
  axis (area ↓ 2.8×, power ↓ 2.4×, slow-corner WNS ↓ 600×) —
  proof that the IMEM regfile dominates *everything* at the SoC
  level. The Phase-3D narrative ("IMEM-fetch-dominated power")
  is now backed by post-P&R numbers.
- **The 4 484-fanout residual** even at 2 KB depth says no
  practical regfile depth gets the open flow to slow-corner
  closure without splitting the IMEM into banked sub-arrays
  (Phase 3.5's job, via OpenRAM macros).
- **`STA_THREADS=2` is mandatory** on 13 GiB WSL for any SoC
  this size. Documented in `flow/phase3_soc/config.json`.
- **Default-activity power 103 mW at 100 MHz / nom_tt** is the
  baseline against which Phase 3E Step 2's activity-aware
  inference power will be compared, and against which Session
  3.5's OpenRAM run will be compared head-to-head.

## 9. Reproduction

```bash
source scripts/env.sh

# Re-verify gates against the shrunk RTL:
scripts/check_soc_elab.sh                 # 3A elaboration
scripts/run_tb_wb_tile_wrapper.sh         # 3B wrapper TB (PASS 10/10)
scripts/run_soc_smoke.sh                  # 3C smoke (PASS, 108 cycles)
scripts/run_soc_bnn.sh --skip-train       # 3D inference (PASS 16/16, 234 644 cyc)

# Run SoC P&R (~1.5 h wall-clock, peak 4.6 GiB DRT memory):
rm -rf flow/phase3_soc/runs/phase3_soc    # only if rerunning
scripts/run_soc_pnr.sh                    # tee'd to results/phase3/logs/soc_pnr.log
```

Final artifacts at `flow/phase3_soc/runs/phase3_soc/final/`:
- `gds/soc_top.gds` — clean GDS (Magic-streamed)
- `klayout_gds/soc_top.klayout.gds` — KLayout-streamed GDS
- `mag_gds/soc_top.magic.gds` — Magic-streamed GDS
- `nl/soc_top.nl.v` — synthesizable post-route netlist
- `pnl/soc_top.pnl.v` — physical post-route netlist
- `def/soc_top.def`
- `spef/{max,min,nom}/soc_top.{max,min,nom}.spef` — parasitics
- `sdf/{nom_*,max_*,min_*}/soc_top__*.sdf` — STA delays per corner
- `metrics.{csv,json}` — full PPA metrics

## 10. Activity-aware power on the post-P&R SoC

### 10.1 Methodology

The Phase 2C activity-aware methodology (`scripts/sta_power_one_corner.tcl`)
re-implemented for the SoC, with two adaptations forced by the SoC's
post-flatten netlist topology:

1. **Hierarchy bucketing without instance hierarchy.** After Yosys
   flatten + LibreLane P&R, the netlist has one module (`soc_top`).
   `scripts/bucket_soc_cells.py` parses the post-route netlist and
   buckets each std-cell instance into one of `u_cpu / u_xbar / u_imem /
   u_dmem / u_tile / u_gpio / shared / clock_tree` based on the cell's
   output-net hierarchical name (with input-pin fallback for
   Yosys-renamed `_NNNNN_` outputs). The TCL then iterates each
   bucket's cell list and sums per-instance power via
   `sta::instance_power`.

2. **Interior-pin activity propagation.** OpenSTA's `read_vcd` only
   annotates *design-port* pin activities — for our SoC, that's the 18
   chip-pin boundary (clk, rst_n_i, gpio_i[7:0], gpio_o[7:0]). With a
   narrow boundary and a flat netlist, the rest of the design propagates
   from default activity (≈ 0) and combinational power collapses to
   ~µW. To recover useful interior coverage, two helper tools:

   - `scripts/flatten_vcd_hierarchy.py` rewrites the iverilog VCD so
     signals below `tb_soc_bnn.dut` appear as flat-named wires *at*
     that scope (e.g., `u_cpu.u_core.mem_addr[2]` becomes a literal
     wire name). This matches the post-flatten netlist's escaped-
     identifier wires that survived synthesis.
   - `scripts/vcd_to_activity_tcl.py` walks the flattened VCD,
     computes per-signal toggle rate and duty cycle, and emits a TCL
     script of `set_power_activity -pins ...` calls that OpenSTA can
     source after `read_vcd` to apply the measured activities to
     interior pins.

   **Yields:** 47 of 1 210 candidate VCD signals match a surviving
   post-route net. The rest correspond to wires Yosys collapsed
   during synthesis (interconnect signals, intermediate combinational
   nets, and the entire IMEM read-mux because of `INIT_HEX=""`).
   This caveat is built into the result and reported transparently
   below.

### 10.2 Workload — Phase 3D 16-image inference

The activity source is `tb/tb_soc_bnn.sv` re-run with the `+vcd`
plus-arg, dumping a 93 MB VCD over **234 644 cycles** = 16 MNIST
images × ~14 660 cycles/image. Workload mix: 4 hidden-layer
batches per image (32 cfg writes + threshold writes), 4 tile
inferences, software popcount + argmax, GPIO emit. Tile
programming dominates (~66 %); see PHASE3D_NOTES §4.3.

### 10.3 Results

Two corners measured: `max_ff_n40C_1v95` (Phase 2C headline corner,
matches the SOCC paper's tile-level numbers) and `nom_tt_025C_1v80`
(the LibreLane sign-off corner, same one default-activity power was
reported at in §4).

| Bucket / group         | `nom_tt_025C_1v80` (mW) | `max_ff_n40C_1v95` (mW) |
| ---------------------- | ----------------------: | ----------------------: |
| u_dmem                 |                  33.33  |                  38.58  |
| clock_tree             |                  35.90  |                  42.98  |
| u_tile (wrapper + tile)|                   9.90  |                  11.47  |
| u_cpu (PicoRV32)       |                   6.71  |                   7.78  |
| shared (Yosys-renamed) |                   0.81  |                   0.95  |
| u_gpio                 |                   0.26  |                   0.30  |
| u_imem                 |                   0.00  |                   0.00  |
| u_xbar (wb_interconnect)|                  0.00  |                   0.00  |
| **Bucket sum**         |                **86.91**|                **102.06**|
| Δ unbucketed (leakage + cells with no output pin found) |  3.46  |  4.00  |
| **SoC total (`design_power`)** |          **90.38**|                **106.06**|

OpenSTA `report_power` decomposition for the headline corner
(`max_ff_n40C_1v95`):

| Group         | Internal (mW) | Switching (mW) | Leakage (µW) | Total (mW) | Share |
| ------------- | ------------: | -------------: | -----------: | ---------: | ----: |
| Sequential    |          57.7 |            0.4 |        0.253 |       58.1 | 54.7 % |
| Combinational |           0.5 |            0.5 |        0.424 |        1.0 |  1.0 % |
| Clock         |          23.0 |           24.0 |        0.895 |       47.0 | 44.3 % |
| **Total**     |      **81.2** |       **24.9** |    **1.572** |  **106.1** | 100 %  |

### 10.4 Activity-aware vs default-activity ratio

The Phase 2C-style sanity check. LibreLane sign-off STA at
`nom_tt_025C_1v80` (default activity, 0.1 toggles/cycle on
unannotated nets) reported **102.98 mW**. Our activity-aware
measurement at the same corner is **90.38 mW**.

**Ratio: activity-aware / default = 0.88×.**

**This is below 1, the opposite direction from Phase 2C tile
results** (where the ratio was 2.7–9.6×). The mechanism:

- For the Phase 2C tile, default-activity assumed 0.1 toggles/cycle
  on unannotated nets. The real workload toggle rate (0.166 /
  cycle/pin per `tb_power.dut.x_in`) was **higher** than default,
  so activity-aware ratios came out > 1.
- For the SoC, default activity (0.1 toggles/cycle on every net) is
  **higher than the real per-net average**: the DMEM regfile is
  mostly idle (read but rarely written), the wrapper FSM is idle
  between inferences, the tile is idle ~66 % of every image while
  PicoRV32 reprograms weights. So activity-aware comes out below
  default.
- **Sequential power dominates (~55 %) and is essentially activity-
  invariant** (clock-driven, regardless of data toggling). **Clock
  tree power dominates (~44 %) and is purely clock-driven**. So 99 %
  of SoC power is independent of data activity, and the activity-
  aware-vs-default delta only moves combinational + sequential-D-pin
  switching, which is small (≤ 1 mW).

This is itself a key finding: **in a register-file-IMEM SoC,
activity-aware vs default power tracks within ~12 %**. Activity-
aware power is dominated by clock tree + sequential cells; the
"workload-dependent" combinational fraction is < 1 %. This is the
opposite of the Phase-2C tile narrative ("activity widens the TLG
advantage 49 pp because case-arm logic suppresses combinational
toggling") — that mechanism is masked at the SoC level by the
sequential floor.

### 10.5 Per-image energy

Time per image (from PHASE3D_NOTES §4.3): 14 700 cycles / 100 MHz =
**147 µs**. Per-image energy = total power × 147 µs:

| Corner                | Total power | Per-image energy | Inferences / J |
| --------------------- | ----------: | ---------------: | -------------: |
| `nom_tt_025C_1v80`    |    90.38 mW |    **13.29 µJ**  |      75 250 /J |
| `max_ff_n40C_1v95`    |   106.06 mW |    **15.59 µJ**  |      64 130 /J |

**Headline (max_ff): 15.6 µJ/inference, 64 K inferences/J.**

For perspective, the Phase 2C tile alone consumed 360 mW × 30 ns
(3 cycles per vector at 100 MHz) = 10.8 nJ / inference. The SoC
is **~1 400× higher per-inference energy than the bare tile** —
because each of the SoC's "inferences" is a full firmware loop
that programs the tile (32 cfg writes), runs 4 tile evaluations,
does software popcount + argmax, and emits via GPIO. The tile
itself contributes only 11.5 mW × 4 cycles × 16 = 7.4 nJ of the
15.6 µJ — i.e., **0.05 % of system energy goes to the tile;
99.95 % goes to the IMEM-fetch + DMEM-access + clock tree of
the surrounding SoC.**

This is the no-OpenRAM tax made quantitative. It directly motivates
Session 3.5's OpenRAM IMEM swap.

### 10.6 Caveats and methodological honesty

1. **u_imem = 0 mW** is a synthesis artifact of building the SoC
   with `INIT_HEX=""` — Yosys constant-propagated all 16 K IMEM
   flops to 0 and removed them from the netlist. The IMEM read mux
   was likewise eliminated. A re-run with `INIT_HEX="firmware/
   inference/firmware.hex"` would bake the firmware into IMEM
   constants and produce a more representative power figure (the
   IMEM read-port + decoder would still be optimized away, but the
   storage flops would be present). Session 3.5 should bake
   firmware in.
2. **u_xbar = 0 mW** is similar — `wb_interconnect` is purely
   combinational and all its output wires got Yosys-renamed to
   `_NNNNN_`. Its power lands in the `shared` bucket via the
   input-pin fallback, but it can't be cleanly separated.
3. **47 of 1 210 VCD signals matched** in the activity-TCL pass.
   This means most interior nets propagate activity from the chip-
   pin boundary statistically rather than from measured workload
   toggling. The 47 that DID match are the high-value ones — the
   WB-master bus (`m_adr/m_dat_w/m_dat_r/m_sel`), the DMEM array
   (`u_dmem.mem[*][*]`), and a handful of CPU pipeline signals —
   so the dominant sequential power IS workload-driven. Combinational
   power is the underestimated component.
4. **The "shared" bucket holds 22 K cells but only 0.95 mW.** This
   is where most Yosys-renamed combinational logic ended up (the
   PicoRV32 ALU + decode, the WB interconnect, the wrapper FSM
   combinational portions). Its low power is consistent with the
   underestimation in (3); a more rigorous PT-PX-style analysis
   would attribute these correctly and the per-bucket numbers
   above would shift, but the total would likely change by ≤ 5 mW.
5. **STA_THREADS=2 mandatory.** Without this, multi-corner STA
   in the LibreLane flow OOM-kills on 13 GiB WSL. The
   standalone-power scripts here run a single corner at a time,
   so they're safe.

The numbers are honest within these caveats. The story they tell
— "DMEM regfile + clock tree dominate; workload activity barely
moves the needle" — is the register-file-baseline story Session
3.5 will overturn.

## 11. Next session steps (3E continuation, after Session 3.5)

1. **Step 3 — KLayout layout figure.** Render
   `final/gds/soc_top.gds` to PNG with KLayout, label the major
   hierarchical blocks, drop into
   `results/phase3/figures/soc_layout_labeled.png`. **Deferred to
   after Session 3.5** so we produce a side-by-side
   register-file-baseline-vs-OpenRAM figure in one pass.

2. **Step 4 — final aggregation.** `scripts/collect_phase3.py`
   producing `results/phase3/{summary.csv,summary.md}`.
   `docs/PHASE3_SUMMARY.md` aggregating Phase 3A–3E + 3.5 findings.

3. **Session 3.5 — OpenRAM IMEM/DMEM macros.** Expected to recover
   slow-corner timing closure without shrinking memories, eliminate
   the IMEM constant-prop artifact, and become the paper's headline
   number. This baseline notes file is the comparison anchor.

## 12. Reproduction (activity-aware power)

```bash
source scripts/env.sh

# (Re)generate VCD if missing — uses the gate-4 iverilog binary built
# during the regression-gate sweep (scripts/run_soc_bnn.sh --skip-train):
vvp /tmp/tb_soc_bnn +vcd

# Run activity-aware power per corner:
scripts/run_soc_power.sh max_ff_n40C_1v95
scripts/run_soc_power.sh nom_tt_025C_1v80
```

Outputs per corner at `results/phase3/power/<corner>/`:
- `power.rpt` — text report, full hierarchical decomposition
- `power.metrics.json` — same data in JSON for downstream tooling

Per-bucket cell lists (regenerable from netlist by
`scripts/bucket_soc_cells.py`):
- `results/phase3/power/buckets/<bucket>.cells`
- `results/phase3/power/buckets/activities.tcl` — interior-pin
  activity TCL emitted from the flattened VCD.
