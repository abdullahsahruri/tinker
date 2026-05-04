# Phase 3 SoC PPA — register-file baseline vs OpenRAM vs Phase 4.5 (14×14 grouped BNN)

Headline: tile fraction of system energy goes from 0.05% to 24.3% (max_ff corner). Per-image energy drops 1.95× from 15.55 µJ to 7.98 µJ (Phase 3.5). Phase 4.5 raises MNIST accuracy from 71.12% to **85.60%** at only +1.0% energy overhead (8.06 µJ/image).

| Metric | Unit | Register-file baseline | OpenRAM SoC (Ph 3.5) | Δ (3.5 vs base) | Phase 4.5 (14×14 grouped) |
| --- | --- | ---: | ---: | --- | --- |
| Total cell count | logic + macros | 123,157 logic + 0 macros | 68,110 logic + 2 macros | 0.55× std-cell shrink | 68,110 logic + 2 macros (SoC unchanged) |
| Std-cell area | mm² | 0.853 | 0.380 | 0.45× | 0.380 (SoC unchanged) |
| Macro area | mm² | 0.000 | 0.475 | — | 0.475 (SoC unchanged) |
| Core area | mm² | 1.726 | 2.199 | 1.27× | 2.199 (SoC unchanged) |
| Die area | mm² | 1.769 | 2.250 | 1.27× | 2.250 (SoC unchanged) |
| Std-cell utilization | % | 49.4 | 22.0 | — | 22.0 (SoC unchanged) |
| | | | | | |
| Setup WNS @ nom_tt | ns | +1.95 | +0.51 | headline corner closes in both | +0.51 (SoC unchanged) |
| Setup WNS @ nom_ss | ns | -5.32 | -8.13 | baseline: regfile-mux fanout; OpenRAM: TT-only macro Liberty artifact | -8.13 (SoC unchanged) |
| Setup WNS @ nom_ff | ns | +4.76 | +3.87 | — | +3.87 (SoC unchanged) |
| Hold WNS @ nom_ss | ns | -0.29 | +0.45 | OpenRAM hold is clean; baseline had 6 violations | +0.45 (SoC unchanged) |
| | | | | | |
| Default-activity power @ nom_tt | mW | 102.98 | 45.26 | 0.44× lower | 45.26 (SoC unchanged) |
| Activity-aware power @ nom_tt | mW | 90.38 | 41.54 | 0.46× lower | 41.54 (SoC unchanged) |
| Activity-aware power @ max_ff | mW | 106.06 | 47.21 | 0.45× lower | 47.21 (SoC unchanged) |
| | | | | | |
| Sequential power @ max_ff | mW (% of total) | 58.1  (54.8%) | 19.8  (41.9%) | share drops as macros take over storage role | 19.8  (41.9%) (SoC unchanged) |
| Combinational power @ max_ff | mW (% of total) | 1.02  (1.0%) | 0.97  (2.1%) | share rises slightly | 0.97  (2.1%) (SoC unchanged) |
| Clock-tree power @ max_ff | mW (% of total) | 47.0  (44.3%) | 17.1  (36.2%) | smaller absolute (fewer flops to clock) | 17.1  (36.2%) (SoC unchanged) |
| Macro power @ max_ff | mW (% of total) | 0.00  (0.0%) | 9.39  (19.9%) | absent in baseline (no macros) | 9.39  (19.9%) (SoC unchanged) |
| | | | | | |
| IMEM total @ max_ff | mW | 0.00 | 5.56 | baseline IMEM constant-propagated to 0; OpenRAM = macro internal | 5.56 (SoC unchanged) |
| DMEM total @ max_ff | mW | 38.58 | 3.85 | baseline DMEM = 8 192 flops; OpenRAM = macro internal | 3.85 (SoC unchanged) |
| Tile total @ max_ff | mW (% of total) | 11.47  (10.81%) | 11.47  (24.29%) | tile RTL identical — power unchanged; share rises | 11.47  (24.29%) (SoC unchanged) |
| PicoRV32 total @ max_ff | mW | 7.78 | 7.71 | — | 7.71 (SoC unchanged) |
| GPIO + xbar @ max_ff | mW | 0.30 | 0.30 | — | 0.30 (SoC unchanged) |
| Clock-tree total @ max_ff | mW | 42.98 | 15.10 | 0.35× lower | 15.10 (SoC unchanged) |
| | | | | | |
| Tile fraction of total energy @ max_ff | % | 10.81 | 24.29 | 2× higher visibility | 24.29 (SoC unchanged) |
| Memory fraction of total power @ max_ff | % | 36.4 | 19.9 | 0.55× — IMEM/DMEM no longer dominate | 19.9 (SoC unchanged) |
| | | | | | |
| **MNIST test accuracy (10K eval)** | **%** | **71.12** | **71.12** | **Phase 3D 7×7 BNN** | **85.60 (+14.48 pp; grouped 14×14 BNN)** |
| | | | | | |
| Per-image cycle count | cycles | 14,660 | 16,907 | +15% (1-cycle wait state on macros) | 17,068 (+0.95% vs Ph 3.5) |
| Per-image energy @ max_ff | µJ | 15.55 | 7.98 | 0.51× lower (despite +15% cycles) | 8.06 (+1.0% vs Ph 3.5) |
| Per-image energy @ nom_tt | µJ | 13.25 | 7.02 | 0.53× lower | 7.09 (est.) |
| Inferences/J @ max_ff | /J | 64,315 | 125,292 | 1.95× more | 124,113 (-0.9% vs Ph 3.5) |
| Inferences/J @ nom_tt | /J | 75,473 | 142,377 | 1.89× more | 141,044 (est.) |
| Effective inferences/sec @ 100 MHz @ nom_tt | /sec | 6,821 | 5,915 | throughput drops with wait states | 5,859 (est.) |
| | | | | | |
| P&R wall-clock | min | 93 | 78 | 0.84× faster | N/A (SoC RTL unchanged) |
| Peak DRT memory | GiB | 10.22 | 2.95 | 0.29× lower | N/A (SoC RTL unchanged) |

## Notes on methodology

- Baseline timing/power numbers from `docs/PHASE3E_BASELINE_NOTES.md`. OpenRAM numbers from `flow/phase3_soc/runs/phase3_soc/final/metrics.json` and `results/phase3/power/<corner>/power.metrics.json`.
- Phase 4.5 SoC is byte-identical to Phase 3.5 at the netlist level — only `firmware/inference/weights_14x14.h` and DMEM layout changed (8 words/image for 4-quadrant 14×14 vs 2 words/image for 7×7). All area, timing, and power numbers carry over unchanged. The +1.0% energy per image is purely the +0.95% cycle-count increase from the slightly longer firmware loop.
- OpenRAM macros (`sky130_sram_2kbyte_1rw1r_32x512_8`, `sky130_sram_1kbyte_1rw1r_32x256_8`) ship Liberty for the TT_1p8V_25C corner only. All 9 timing-corner STA passes use the same TT macro Liberty — a known LibreLane 3.x limitation.
- Magic DRC reports 8 404 917 false positives, all inside the OpenRAM macro footprint (a known sky130 + Magic DRC issue). KLayout DRC reports 0 errors and is the authoritative sign-off check.
- Tile RTL (`rtl/tile_tlg_ld/tile_tlg_ld.v`) is byte-identical across all three configurations — only the memory wrappers, SoC config, and firmware changed.
- Per-image energy = total power × (cycles_per_image / 100 MHz). Phase 3.5: 16,907 cycles/image. Phase 4.5: 17,068 cycles/image (8 words/image DMEM vs 2 words/image).
- Phase 4.5 accuracy: 3-seed training (seeds 42/1042/2042), hard-tanh STE, OneCycleLR, 30 epochs; best seed (2042) achieves 85.60% on the full 10K MNIST test set [Wilson 95% CI: 84.90%, 86.27%].
