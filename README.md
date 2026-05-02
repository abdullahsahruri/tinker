# socc26-2

Open-source ASIC design flow targeting the SkyWater 130 nm PDK (sky130A) using
LibreLane (the maintained successor to OpenLane2). The project is structured to
support a small SoC built around PicoRV32 and to serve as the substrate for
threshold-logic-gate experimentation in subsequent phases. Phase 0 (this
checkpoint) brings up the toolchain and demonstrates a hello-world counter
running through the entire RTL-to-GDS flow.

## Layout

| Directory  | Purpose                                                  |
| ---------- | -------------------------------------------------------- |
| `rtl/`     | Verilog source                                           |
| `tb/`      | Testbenches                                              |
| `synth/`   | Synthesis scripts and outputs                            |
| `flow/`    | LibreLane configurations and run directories             |
| `sim/`     | Simulation scripts                                       |
| `scripts/` | Helper scripts (`env.sh`, etc.)                          |
| `docs/`    | Notes, including `PHASE0_NOTES.md`                       |
| `results/` | PPA results, layouts, reports for archiving              |

## Getting started

```bash
source scripts/env.sh        # activates venv + sky130A env, scrubs PATH
librelane flow/hello/config.json
```

See `docs/PHASE0_NOTES.md` for pinned versions and Phase 0 history.
