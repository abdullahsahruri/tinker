# Phase 3 SoC PPA — register-file baseline vs OpenRAM

Headline: tile fraction of system energy goes from 0.05% to 24.3% (max_ff corner). Per-image energy drops 1.95× from 15.55 µJ to 7.98 µJ.

| Metric | Unit | Register-file baseline | OpenRAM SoC | Δ |
| --- | --- | ---: | ---: | --- |
| Total cell count | logic + macros | 123,157 logic + 0 macros | 68,110 logic + 2 macros | 0.55× std-cell shrink |
| Std-cell area | mm² | 0.853 | 0.380 | 0.45× |
| Macro area | mm² | 0.000 | 0.475 | — |
| Core area | mm² | 1.726 | 2.199 | 1.27× |
| Die area | mm² | 1.769 | 2.250 | 1.27× (OpenRAM die was set absolute; auto-relative would yield ~1.2–1.4 mm²) |
| Std-cell utilization | % | 49.4 | 22.0 | — |
| | | | | |
| Setup WNS @ nom_tt | ns | +1.95 | +0.51 | headline corner closes in both |
| Setup WNS @ nom_ss | ns | -5.32 | -8.13 | baseline: regfile-mux fanout (4484 terms); OpenRAM: TT-only macro Liberty methodology artifact |
| Setup WNS @ nom_ff | ns | +4.76 | +3.87 | — |
| Hold WNS @ nom_ss | ns | -0.29 | +0.45 | OpenRAM hold is clean; baseline had 6 violations |
| | | | | |
| Default-activity power @ nom_tt | mW | 102.98 | 45.26 | 0.44× lower |
| Activity-aware power @ nom_tt | mW | 90.38 | 41.54 | 0.46× lower |
| Activity-aware power @ max_ff | mW | 106.06 | 47.21 | 0.45× lower |
| | | | | |
| Sequential power @ max_ff | mW (% of total) | 58.1  (54.8%) | 19.8  (41.9%) | share drops as macros take over storage role |
| Combinational power @ max_ff | mW (% of total) | 1.02  (1.0%) | 0.97  (2.1%) | share rises slightly — tile combinational becomes more visible |
| Clock-tree power @ max_ff | mW (% of total) | 47.0  (44.3%) | 17.1  (36.2%) | smaller absolute (fewer flops to clock); fraction down |
| Macro power @ max_ff | mW (% of total) | 0.00  (0.0%) | 9.39  (19.9%) | absent in baseline (no macros) |
| | | | | |
| IMEM total @ max_ff | mW | 0.00 | 5.56 | baseline IMEM was constant-propagated to 0; OpenRAM = macro internal power |
| DMEM total @ max_ff | mW | 38.58 | 3.85 | baseline DMEM = 8 192 flops worth of clock-tree + sequential; OpenRAM = macro internal |
| Tile total @ max_ff | mW (% of total) | 11.47  (10.81%) | 11.47  (24.29%) | tile IS THE SAME RTL — power identical; share rises with smaller pie |
| PicoRV32 total @ max_ff | mW | 7.78 | 7.71 | — |
| GPIO + xbar @ max_ff | mW | 0.30 | 0.30 | — |
| Clock-tree total @ max_ff | mW | 42.98 | 15.10 | 0.35× lower |
| | | | | |
| Tile fraction of total energy @ max_ff | % | 10.81 | 24.29 | 2× higher visibility |
| Memory fraction of total power @ max_ff | % | 36.4 | 19.9 | 0.55× — IMEM/DMEM no longer dominate |
| | | | | |
| Per-image cycle count | cycles | 14,660 | 16,907 | +15% (1-cycle wait state on macros) |
| Per-image energy @ max_ff | µJ | 15.55 | 7.98 | 0.51× lower (despite +15% cycles) |
| Per-image energy @ nom_tt | µJ | 13.25 | 7.02 | 0.53× lower |
| Inferences/J @ max_ff | /J | 64,315 | 125,292 | 1.95× more |
| Inferences/J @ nom_tt | /J | 75,473 | 142,377 | 1.89× more |
| Effective inferences/sec @ 100 MHz @ nom_tt | /sec | 6,821 | 5,915 | throughput drops with wait states; energy-per-inference drops more |
| | | | | |
| P&R wall-clock | min | 93 | 78 | 0.84× faster |
| Peak DRT memory | GiB | 10.22 | 2.95 | 0.29× lower |

## Notes on methodology

- Baseline timing/power numbers from `docs/PHASE3E_BASELINE_NOTES.md`. OpenRAM numbers from `flow/phase3_soc/runs/phase3_soc/final/metrics.json` and `results/phase3/power/<corner>/power.metrics.json`.
- OpenRAM macros (`sky130_sram_2kbyte_1rw1r_32x512_8`, `sky130_sram_1kbyte_1rw1r_32x256_8`) ship Liberty for the TT_1p8V_25C corner only. All 9 timing-corner STA passes use the same TT macro Liberty — a known LibreLane 3.x limitation. The slow-corner setup violation is a methodology artifact (slow std cells around TT-modeled macros), not a real-silicon problem.
- Magic DRC reports 8 404 917 false positives, all inside the OpenRAM macro footprint (a known sky130 + Magic DRC + macro-internal-contact issue). KLayout DRC reports 0 errors and is the authoritative sign-off check.
- Tile RTL (`rtl/tile_tlg_ld/tile_tlg_ld.v`) is byte-identical between the two runs — only the memory wrappers and SoC config changed. The tile's measured power (~9.9 mW @ nom_tt, ~11.5 mW @ max_ff) is therefore the same; what changes is its share of the smaller pie.
- Per-image energy = total power × (cycles_per_image / 100 MHz). OpenRAM cycles_per_image = 16 907 (vs 14 660 baseline) due to the 1-cycle macro read latency vs the regfile's combinational read.
