# Phase 0 — environment setup notes

This document records exactly what was installed, what versions were pinned,
and what to watch for in subsequent phases. Goal: be able to recreate this
toolchain six months from now.

## Pinned versions (the reproducibility table)

| Component                  | Version / commit                              | Source                                           |
| -------------------------- | --------------------------------------------- | ------------------------------------------------ |
| OS                         | Ubuntu 22.04.5 LTS (jammy) on WSL2 (kernel 6.6.87.2-microsoft-standard-WSL2) | machine baseline                                 |
| Docker Engine              | 28.4.0 (Docker Desktop integrated)            | Docker Desktop for Windows, WSL integration      |
| Python                     | 3.10.12                                       | apt (system)                                     |
| LibreLane (Python pkg)     | **3.0.3**                                     | `pip install 'librelane==3.0.3'` (PyPI) inside `.venv/` |
| LibreLane Docker image     | **`ghcr.io/librelane/librelane:3.0.3`**       | pulled via `docker pull`                          |
| volare                     | **0.20.6**                                    | `pip install 'volare==0.20.6'` inside `.venv/`   |
| sky130 PDK commit          | **`8afc8346a57fe1ab7934ba5a6056ea8b43078e71`** | from `librelane/pdk_hashes.yaml` in pkg 3.0.3     |
| Verilator                  | 4.038                                         | apt `verilator`                                  |
| Magic                      | 8.3.105                                       | apt `magic`                                      |
| Icarus Verilog             | 11.0                                          | apt `iverilog`                                   |
| GTKWave                    | 3.3.104                                       | apt `gtkwave`                                    |
| KLayout                    | 0.29.11                                       | apt `klayout`                                    |
| RISC-V GCC                 | 10.2.0 (binutils 2.35.1)                      | apt `gcc-riscv64-unknown-elf`                    |

The LibreLane Python package and the matching Docker image must agree — if you
upgrade one, upgrade the other. The PDK commit comes from
`pdk_hashes.yaml` *inside* the installed `librelane` package; if you change
the librelane version, re-read that file before running `volare enable`.

## Project layout

Project root: `/home/asahruri/work/2026/socc26-2/`

```
socc26-2/
├── rtl/            Verilog source (hello.v lives here)
├── tb/             testbenches
├── synth/          (reserved)
├── flow/           LibreLane configs and runs (gitignored output)
├── sim/            (reserved)
├── scripts/        env.sh
├── docs/           PHASE0_NOTES.md, future phase notes
├── results/        curated PPA / GDS artifacts
├── pdk/            sky130A install (gitignored, ~5 GB)
├── .venv/          project Python environment (gitignored)
├── README.md
└── .gitignore
```

`pdk/` is project-local rather than `~/.volare/`. Reasons: avoids a root-owned
`~/.volare` left behind by a previous failed install on this machine, and
makes the toolchain reproducible per-project (different projects can pin
different sky130 commits without collision).

## Environment activation

Activate with `source scripts/env.sh` from any shell. The script:
- activates `.venv/`
- exports `PDK_ROOT`, `PDK=sky130A`, `STD_CELL_LIBRARY=sky130_fd_sc_hd`,
  `LIBRELANE_IMAGE_OVERRIDE=ghcr.io/librelane/librelane:3.0.3`
- scrubs `/mnt/c/...` entries from `PATH` (Windows-mount pollution; one of the
  shims, `verilator`, points to a binary that no longer exists on the Windows
  side and would otherwise win).

The scrub is **reversible**: it edits `PATH` only in the sourcing shell.
Closing the shell restores the original `PATH`. **No system-wide config
(`~/.bashrc`, `/etc/profile.d`, etc.) is modified.**

## Non-obvious things I had to do

1. **`volare` is not a transitive dependency of `librelane==3.0.3`.** It used
   to be in earlier versions. Install it explicitly: `pip install volare`.
2. **The verilator on `PATH` was a broken shim** at `/mnt/c/tools/oss-cad-suite/bin/verilator`
   pointing into a Windows OSS CAD Suite that had been partially deleted —
   `verilator -V` would die with `Can't exec verilator_bin`. Apt's
   `/usr/bin/verilator` is fine; the env.sh PATH scrub makes it win.
3. **PDK installed inside the project**, not at `~/.volare/`. The default
   location was owned by root from a prior failed run; rather than `chown`
   it, we point `volare` at `pdk/` under the project. This also gives every
   project its own pinned PDK.

## ⚠️ Phase 2+ blocker — RAM is tight

Total RAM in this WSL2 instance is **7.6 GiB** with 2 GiB swap. LibreLane
recommends ≥8 GiB and PicoRV32-class designs frequently exceed that during
detailed routing or STA. Hello-world (4-bit counter) fits easily, so this is
**not** a Phase 0 problem — but it is a hard blocker for Phase 2.

**Fix before starting Phase 2** — on the **Windows side**, edit
`C:\Users\<user>\.wslconfig` (create if absent):

```ini
[wsl2]
memory=14GB
swap=8GB
processors=12
```

Then from PowerShell: `wsl --shutdown` and reopen the WSL terminal. Verify
inside WSL with `free -h` (should show `14Gi`) and `nproc` (should show 12).

The host has 16 GB total / 16 threads — leaving 2 GB / 4 threads for Windows
is the recommended split.

## Fragile spots / things to watch

- **Docker Desktop is the daemon source.** If Docker Desktop isn't running,
  `docker` calls hang. Confirm with `docker info` before kicking off long
  flows.
- **`/mnt/c` PATH pollution returns in any new shell** — env.sh must be
  re-sourced. If a flow is invoked without sourcing first, the broken
  verilator shim could be invoked unexpectedly. (LibreLane runs verilator
  inside its container anyway, but native testbenches via Icarus/Verilator
  on the host will hit this.)
- **Yosys and OpenROAD are also installed natively** (yosys 0.9, openroad
  v2.0-17598). LibreLane uses the bundled versions inside the container, so
  these don't matter for the flow — but if you ever invoke them directly
  outside Docker, they will be very out of date.
- **First `librelane` run pulls the image** if it isn't already cached. To
  pre-cache: `docker pull ghcr.io/librelane/librelane:3.0.3`.

## TODOs for future me

- [ ] Bump `.wslconfig` memory before Phase 2 (see above).
- [ ] Decide whether to also apt-install `klayout` ≥ 0.30 from a backport for
      newer DRC decks; 0.29.11 has been fine for sky130A so far.
- [ ] If verilator simulation throughput becomes a bottleneck, build a
      newer verilator from source (apt's 4.038 is from 2020).

## Phase 0 hello-world results

Run tag: `phase0_smoke`. Wall-clock for the flow: ~3 minutes.
GDS archived to `results/hello/hello.gds` (full metrics in
`results/hello/metrics.json`).

### Design

`rtl/hello.v` — a 4-bit synchronous-reset counter.
Constraints: 10 ns clock period, 100 × 100 µm absolute die.

### PPA

| Metric                   | Value                                |
| ------------------------ | ------------------------------------ |
| Std-cell instances       | 115                                  |
| Core area                | 6 761.48 µm²                          |
| Die area                 | 10 000 µm² (100 × 100 µm)             |
| Utilization              | 6.35 %                                |
| Routed wirelength        | 564 µm                                |
| Setup WNS / hold WNS     | 0 / 0 (clean across all 9 corners)    |
| Worst setup slack        | +5.46 ns (slowest corner: max_ss_100C_1v60) |
| Worst hold slack         | +0.126 ns (min_ff_n40C_1v95)          |
| Max achievable frequency | ≈ 220 MHz at the slow corner (1 / (10 − 5.46) ns) |

### Sign-off verdicts

| Check                          | Result      |
| ------------------------------ | ----------- |
| Magic DRC                      | 0 errors    |
| KLayout DRC                    | 0 errors    |
| LVS (Netgen)                   | 0 errors, 0 device differences |
| KLayout XOR (vs Magic GDS)     | 0 differences |
| Antenna (nets / pins)          | 0 / 0       |
| Routing DRC                    | 0 errors    |
| Max slew / max fanout / max cap | 0 / 0 / 0   |

### GDS validation

```
top_cell=hello  dbu=0.001 µm  bbox=100.00 × 100.00 µm  cells=18  layers=41
```

KLayout opens the file cleanly. Three GDS variants are emitted by the flow:
`final/gds/hello.gds` (OpenROAD), `final/klayout_gds/hello.klayout.gds`,
`final/mag_gds/hello.magic.gds` — XOR between them is 0.

### Clean-shell reproducibility

`env.sh` was tested in a stripped shell (`env -i HOME=$HOME PATH=/usr/bin:/bin bash`):
sourcing it activates the venv, exposes `librelane v3.0.3`, and points
`PDK_ROOT` at the populated sky130A install. No re-installation required.

### Things to revisit when scaling up

- `PNR_SDC_FILE` / `SIGNOFF_SDC_FILE` were unset, so the flow used a generic
  fallback SDC. For real designs, write proper SDC files per design.
- `VSRC_LOC_FILES` unset → IR-drop analysis used defaults. Fine for hello,
  must be set for tape-out-grade work.
- `[RSZ-0020] found 2 floating nets` — these were the unused upper bits of
  the counter being reported by the resizer. Harmless for hello. For real
  designs, verify the toplevel wiring before tape-out.
- `LEF58_ENCLOSURE with no CUTCLASS is not supported` — known LEF parser
  limitation in OpenROAD's DRT for this PDK; benign for sky130A.
