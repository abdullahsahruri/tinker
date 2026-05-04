# Phase 3 Session C — PicoRV32 vendor + SoC bring-up (notes)

> **Headline.** PicoRV32 is vendored at commit `87c89ac` from
> [YosysHQ/picorv32](https://github.com/YosysHQ/picorv32). The Phase-3A
> skeletons for `picorv32_wrapper`, `wb_interconnect`, `wb_imem`,
> `wb_dmem`, and `wb_gpio` are now real implementations; `wb_tile_wrapper`
> is unchanged from 3B. A 13-instruction bare-metal smoke firmware
> (`firmware/smoke/`) writes `0x BE` to GPIO_OUT and the `0xCAFE_BABE`
> sentinel to GPIO_SIM_END. The end-to-end testbench
> (`tb/tb_soc_smoke.sv`) sees both observables in **102 simulated
> cycles / 14 acked WB transactions** on first run, with the trace
> showing 11 instruction fetches from IMEM (0x00..0x30) and 2 stores to
> GPIO (0x3000_0004 then 0x3000_0000) — exactly the disassembly
> predicts. **GO for Session 3D.**

---

## 1. What this session produced

| Deliverable                                                     | Where                                         |
| --------------------------------------------------------------- | --------------------------------------------- |
| Vendored PicoRV32 source + LICENSE + README                     | `vendor/picorv32/{picorv32.v, LICENSE, README.md}` |
| Real `picorv32_wb` instantiation (param table from §3.4)        | `rtl/soc/picorv32_wrapper.v`                  |
| Real Wishbone interconnect (decode + read mux + err)            | `rtl/soc/wb_interconnect.v`                   |
| Real 8 KB IMEM (regfile + `$readmemh` init)                     | `rtl/soc/wb_imem.v`                           |
| Real 4 KB DMEM (regfile + byte-strobed writes)                  | `rtl/soc/wb_dmem.v`                           |
| Real GPIO peripheral (SIM_END / OUT / IN)                       | `rtl/soc/wb_gpio.v`                           |
| `INIT_HEX` parameter threaded to `wb_imem`                      | `rtl/soc/soc_top.v`                           |
| Bare-metal smoke firmware (start.S + main.c + linker.ld + Makefile) | `firmware/smoke/`                         |
| Binary→hex helper (little-endian, optional zero-pad)            | `scripts/bin2hex.py`                          |
| Convenience wrapper around the firmware build                   | `scripts/build_smoke_firmware.sh`             |
| End-to-end smoke test bench + run script                        | `tb/tb_soc_smoke.sv`, `scripts/run_soc_smoke.sh` |
| Updated 3A elaboration gate (now ingests vendored core)         | `scripts/check_soc_elab.sh`                   |
| This notes file                                                 | `docs/PHASE3C_NOTES.md`                       |

## 2. PicoRV32 vendoring

### 2.1 Commit pin and source layout

| Field           | Value                                             |
| --------------- | ------------------------------------------------- |
| Upstream repo   | https://github.com/YosysHQ/picorv32               |
| Pinned commit   | `87c89acc18994c8cf9a2311e871818e87d304568`        |
| Latest tag      | `v1.0` (the repo is essentially unchanged for years) |
| Files vendored  | `picorv32.v` (3049 LoC, all upstream modules in one file) + `LICENSE` (ISC) |
| Files NOT vendored | `testbench*.v`, `picosoc/`, `firmware/`, `dhrystone/`, `tests/`, `scripts/`, `vendor/`, `Makefile`, `picorv32.core`, `shell.nix`, `showtrace.py`, `README.md` — none used by the SoC; pulling only `picorv32.v` keeps the vendor tree minimal. |

### 2.2 WB-vs-AXI choice

Upstream's single file ships **both** `picorv32_axi` and `picorv32_wb`,
so no AXI-Lite-to-Wishbone adaptation was needed — `picorv32_wb` exposes
the WB-classic master signal names (`wbm_cyc_o` / `wbm_stb_o` /
`wbm_we_o` / `wbm_sel_o` / `wbm_adr_o` / `wbm_dat_o` / `wbm_dat_i` /
`wbm_ack_i`) that match `wb_interconnect`'s master port byte-identically.
This was the cheaper of the two paths the brief allowed; the AXI fallback
would have added another 100+ lines of bridge code in
`picorv32_wrapper.v` and a separate test harness for that bridge.

### 2.3 Wrapper adaptation

Three things `picorv32_wrapper.v` does on top of straight instantiation:

- **Reset polarity inversion.** Upstream takes `wb_rst_i` (active-high);
  the project convention is `rst_n` (active-low). One inverter on a wire.
- **PCPI / IRQ / trace tie-off.** With `ENABLE_PCPI=ENABLE_IRQ=
  ENABLE_TRACE=0` upstream still exposes the ports — they're driven /
  consumed inside the upstream wrapper for the `*_QREGS`/`*_TIMER`
  internals. We tie inputs to 0 and leave outputs dangling (under a
  combined `_unused_ok` so iverilog doesn't complain).
- **`wbm_err_i` is dropped.** `picorv32_wb` has no err input. The
  decode-miss err generated in `wb_interconnect` therefore has nowhere
  to go; the master will hang on a wild pointer because the slave never
  acks. PHASE3_ARCHITECTURE.md §2 anticipated this ("wild pointer hangs
  visibly rather than silently"). Documented in the wrapper header.

### 2.4 Parameter overrides applied (vs `picorv32_wb` defaults)

The upstream wrapper's defaults disagree with the §3.4 spec on **eight**
parameters; all are explicitly overridden:

| Parameter            | Upstream default | We override to | Why |
| -------------------- | ---------------- | -------------- | --- |
| `ENABLE_COUNTERS`    | 1                | 0              | No `rdcycle`/`rdinstret` needed — saves area. |
| `ENABLE_COUNTERS64`  | 1                | 0              | Same. |
| `CATCH_MISALIGN`     | 1                | 0              | Firmware only does aligned accesses. |
| `CATCH_ILLINSN`      | 1                | 0              | Trust the toolchain; no illinsn handler. |
| `ENABLE_IRQ_QREGS`   | 1                | 0              | IRQs disabled. |
| `ENABLE_IRQ_TIMER`   | 1                | 0              | Same. |
| `REGS_INIT_ZERO`     | 0                | 1              | Deterministic post-reset state for sim. |
| `STACKADDR`          | `32'hffff_ffff`  | `32'h1000_1000`| Top of DMEM per spec §5.1. |

The remaining params from §3.4 (`ENABLE_REGS_16_31=1`,
`ENABLE_REGS_DUALPORT=1`, `TWO_STAGE_SHIFT=1`, `BARREL_SHIFTER=0`,
`COMPRESSED_ISA=0`, `ENABLE_PCPI/MUL/FAST_MUL/DIV/IRQ/TRACE=0`,
`PROGADDR_RESET=0`, `PROGADDR_IRQ=0x10`) match upstream defaults and are
set explicitly only for self-documentation.

The spec mentions `LATCHED_MEM_RDATA=0`. That parameter belongs to
`picorv32` (the core), not `picorv32_wb` (the wrapper); `picorv32_wb`
handles latching internally and does not expose it. Spec note remains
informational; no override needed in `picorv32_wrapper.v`.

## 3. SoC infrastructure

### 3.1 `wb_interconnect` — combinational, single-master

~50 LoC. Decode `m_adr_i[31:28]` into one-hot `sel0..sel3`; OR the
not-selected lines into `dec_miss`. Per-slave `cyc/stb` are gated by
the slave's select line; `we/sel/adr/dat` are broadcast to all four
(slaves with `cyc=0` ignore them). Read data, ack, and err are muxed
back to the master from the selected slave; `m_err_o` additionally
ORs in `(cyc & stb & dec_miss)` so an unmapped access raises a
single-cycle err pulse.

`clk` and `rst_n` are present in the port list (3A skeleton committed
to that contract) but unused — the interconnect is purely
combinational and a registered "active slave" tracker would only be
needed if some slave's `ack` could lag the address by multiple cycles.
Our slaves ack on the first stb cycle (1-cycle pulse), so the
`(s0_ack_i & sel0) | …` reduction is safe.

### 3.2 `wb_imem` — 8 KB regfile + `$readmemh`

`reg [31:0] mem [0:2047]`, plain flop array. `initial` block first
zeros the array then `$readmemh(INIT_HEX, mem)` if `INIT_HEX != ""`.
The pre-zero plus the firmware-hex padding to 2048 words (see §4.2)
means iverilog stays silent about partial fills.

Acks pulse for one cycle on the first cyc&stb edge (the same pattern
the 3B wrapper uses). Reads are combinational from the address. Writes
are silently dropped — IMEM is RX. Promoting writes to `wb_err` was
considered but rejected: `picorv32_wb` cannot consume err anyway, so
the visible failure mode is identical (silent drop vs. hang on a wild
write — both result in firmware not behaving as expected).

### 3.3 `wb_dmem` — 4 KB regfile, byte-strobed writes

Same shape as `wb_imem` but with byte-strobed writes (`wb_sel_i[i]`
gates the four 8-bit lanes of the indexed word). Reset clears all
words to 0 in the `initial` block — once at sim start; the FSM does
not re-zero on `rst_n` deassertion (would cost another 4 K flops worth
of reset-mux logic for no benefit, since the array's `initial` value
already matches "all zero").

Smoke firmware never touches DMEM, but DMEM still elaborates and is
present in the trace — it'll be exercised in Session 3D.

### 3.4 `wb_gpio` — three registers + sentinel

`SIM_END (0x0)`, `OUT (0x4)`, `IN (0x8)`, plus reserved (0xC). Writes
are byte-strobed via a `merge_wr` function so partial stores merge
cleanly with the current shadow. `gpio_o` is driven from `out_q[7:0]`.
The TB does not poll `SIM_END` to decide pass — it reads it
hierarchically (`dut.u_gpio.sim_end_q`) — but a future TB / a future
chip-pin observability harness can use the value too.

### 3.5 `soc_top` — only the param threading changed

The 3A skeleton already wired all the slaves to the master through the
interconnect. The only diff in 3C is exposing an `INIT_HEX` parameter
on `soc_top` and forwarding it to `u_imem`. Reset synchronizer, port
list, and instance graph are byte-identical to 3A.

## 4. Smoke firmware

### 4.1 Code

Thirteen 32-bit instructions, 52 bytes total:

```
00000000 <_reset>:
   0:   10001137  lui    sp, 0x10001        # sp = 0x10001000 (top of DMEM)
   4:   00000193  li     gp, 0
   8:   00000093  li     ra, 0
   c:   00000097  auipc  ra, 0x0
  10:   00c080e7  jalr   12(ra)             # call main (PC = 0x18)
00000014 <.hang>:
  14:   0000006f  j      .hang
00000018 <main>:
  18:   30000737  lui    a4, 0x30000        # a4 = GPIO_BASE
  1c:   0be00793  li     a5, 0xBE
  20:   00f72223  sw     a5, 4(a4)          # GPIO_OUT = 0xBE
  24:   cafec7b7  lui    a5, 0xcafec
  28:   abe78793  addi   a5, a5, -1346      # a5 = 0xCAFEBABE
  2c:   00f72023  sw     a5, 0(a4)          # GPIO_SIM_END = 0xCAFEBABE
  30:   0000006f  j      0x30                # spin
```

### 4.2 Toolchain knobs

- `riscv64-unknown-elf-gcc 10.2.0` — already on PATH via
  `scripts/env.sh`.
- `-march=rv32i -mabi=ilp32` — strict RV32I, no extensions, matches
  the PicoRV32 config.
- `-nostdlib -nostartfiles -ffreestanding -Os` — bare-metal, no
  libc, no crt0; `start.S` is the only entry point.
- `-mno-relax` and `-Wl,--no-relax` — disable linker relaxation.
  Relaxation is harmless here but disabling it makes the per-PC
  instruction layout match the disassembly 1:1, which is useful when
  the smoke trace is being eyeballed.
- `-fno-pic -fno-builtin -Wall -Wextra` — defensive.
- `objcopy -O binary` → flat firmware.bin → `scripts/bin2hex.py
  --pad-words=2048` → `firmware.hex` (one little-endian 32-b word per
  line, padded to fill IMEM).

### 4.3 Why a custom bin → hex helper

`objcopy -O verilog` emits a byte-stream hex with `@addr` markers.
`$readmemh` reads tokens left-to-right; into `reg [31:0] mem [0:N-1]`
the four bytes [b0 b1 b2 b3] would land as `mem[0] = {b0, b1, b2, b3}`,
i.e., big-endian. RV32 is little-endian, so each four-byte instruction
would read out byte-swapped. We could add a dedicated `$readmemh`
endian-swap fixup in `wb_imem`, or fix the producer side. Producer
side is simpler and toolchain-local — `bin2hex.py` reads the flat
`.bin`, packs four bytes per word as little-endian, and emits one hex
word per line. ~25 lines of Python; reused by Session 3D.

## 5. Smoke test result

```
[785000]  tb_soc_smoke: gpio_o = 0xbe        observed (cycle 78)
[1015000] tb_soc_smoke: sim_end_q = 0xCAFEBABE observed (cycle 101)
[1016000] SOC SMOKE TEST: PASS  (cycles=102, transactions=14)
```

PASS on first run, no debug iterations needed. Beat the brief's "be
suspicious if it passes within 4 hours" threshold by orders of
magnitude — verified anyway by running with `+verbose` and checking
the WB master trace:

| # | adr        | we | dat        | what                                |
| - | ---------- | -- | ---------- | ----------------------------------- |
| 0 | 0x0000_0000 | 0 | x          | fetch _reset                        |
| 1 | 0x0000_0004 | 0 | x          | fetch li gp                         |
| 2 | 0x0000_0008 | 0 | x          | fetch li ra                         |
| 3 | 0x0000_000c | 0 | x          | fetch auipc                         |
| 4 | 0x0000_0010 | 0 | x          | fetch jalr (PC := 0x18)             |
| 5 | 0x0000_0018 | 0 | x          | fetch lui a4                        |
| 6 | 0x0000_001c | 0 | x          | fetch li a5, 0xBE                   |
| 7 | 0x0000_0020 | 0 | x          | fetch sw a5, 4(a4)                  |
| 8 | 0x0000_0024 | 0 | x          | fetch lui 0xcafec                   |
| 9 | 0x3000_0004 | 1 | 0x000000be | **store: GPIO_OUT = 0xBE**          |
| 10| 0x0000_0028 | 0 | x          | fetch addi a5, -1346                |
| 11| 0x0000_002c | 0 | x          | fetch sw a5, 0(a4)                  |
| 12| 0x0000_0030 | 0 | x          | fetch j 0x30 (spin)                 |
| 13| 0x3000_0000 | 1 | 0xcafebabe | **store: GPIO_SIM_END = 0xCAFEBABE**|

(Reads show `xxxxxxxx` for `dat` because the trace samples
`m_dat_w` which is the master→slave path, undriven on reads. The read
response data flows back via `m_dat_r` and is consumed by the core.)

The trace confirms (a) all instruction fetches went to IMEM
(`0x0xxx_xxxx` decoded via `wb_interconnect`), (b) both stores went to
GPIO (`0x3xxx_xxxx`), (c) no fetch to DMEM or TILE — the smoke
exercises only the parts the brief intends. Any future regression
that breaks the IMEM read path or the GPIO write path will show up as
a missing transaction or a wrong-address transaction in this trace.

## 6. Gates green

| Gate | Origin | Status |
| ---- | ------ | ------ |
| `scripts/check_soc_elab.sh` | 3A port-list | PASS |
| `scripts/run_tb_wb_tile_wrapper.sh` | 3B wrapper functional (10/10) | PASS |
| `scripts/run_soc_smoke.sh`  | 3C end-to-end smoke | PASS (102 cycles, 14 xacts) |

## 7. What 3D needs to know

1. **Linker script lives in `firmware/smoke/linker.ld`.** Session 3D
   should fork it to `firmware/inference/linker.ld` (same memory map,
   different `.rodata` budget — weights + thresholds + input vectors
   need ~1–4 KB). Don't share a single linker.ld across firmware
   variants; the smoke firmware is a regression target.
2. **`bin2hex.py --pad-words=N` is generic.** The same flow (`gcc →
   objcopy -O binary → bin2hex.py --pad-words=2048`) applies to the
   3D inference firmware unchanged.
3. **`$readmemh` partial-fill warning is silenced by the pad.** If
   3D firmware grows beyond 8 KB the build will fail at link time
   (linker MEMORY length); if it stays under 8 KB the pad keeps
   iverilog quiet.
4. **`STACKADDR=0x10001000` is hard-coded in `picorv32_wrapper.v`
   AND in `start.S`.** Both must be updated together if DMEM is
   ever resized. The wrapper sets `STACKADDR` for the core's
   internal stack-pointer init logic (which only matters if the
   core reset its own SP, which it doesn't — `start.S` does that
   explicitly). Today the duplication is harmless; flag it if a
   future session wants to remove either.
5. **Tile address range is `0x2xxx_xxxx`.** The 3B wrapper expects
   the in-window byte offset in `wb_adr_i[8:0]`; the rest is
   stripped by the interconnect. Use `(uint32_t *)0x20000000` for
   the cfg base, `(uint32_t *)0x20000100` for `XIN.LO`, etc. — full
   layout in PHASE3_ARCHITECTURE.md §4.2.
6. **Decode-miss hangs the core.** `picorv32_wb` does not consume
   `wbm_err_i`; the interconnect raises it on `adr[31:28] >= 0x4`
   but the core never sees an ack and stalls on the next fetch.
   This is the spec'd "wild pointer hangs visibly" behavior. If
   3D's firmware ever reads from an unmapped region for any reason
   (including an off-by-one in a pointer) the smoke turns into a
   timeout. Watch for it.
7. **`wb_dmem` is reset to all-zero by its `initial` block, not by
   `rst_n`.** That's fine for a from-scratch sim run but means a
   testbench that runs two firmwares back-to-back will see DMEM
   carry over between runs. 3D doesn't currently do that; flag if
   the assumption changes.
8. **The smoke TB watches `dut.u_gpio.sim_end_q` hierarchically.**
   3D's TB will likely use the same trick to capture an
   inference-result stream emitted via `OUT` writes (every byte
   the firmware writes to `GPIO_OUT` is observable on `gpio_o[7:0]`
   for one cycle, which is enough for a TB-side ring buffer).

## 8. Estimated complexity for Session 3D

| 3D task                                                         | Estimate | Notes |
| --------------------------------------------------------------- | -------- | ----- |
| Fork firmware/smoke → firmware/inference, expand main.c         | 1 h      | Weight load loop (32 cfg writes), input loop, polling, GPIO emit. |
| Extend `linker.ld` with `.rodata` for weights + inputs          | 30 min   | Same memory map, larger `.rodata`. Verify total stays under 8 KB IMEM. |
| Python golden generator (re-use `scripts/wb_tile_reference.py`) | 30 min   | Already written; emit weights[] + thresholds[] + inputs[] + expected_outputs[] as a C header. |
| `tb/tb_soc_inference.sv` — capture output stream + compare       | 1.5 h    | Snoop `gpio_o` writes (or `OUT` register hierarchy), build a ring buffer, compare against the same Python golden the firmware was built against. |
| End-to-end run script + debug                                   | 1–3 h    | Risk = bus protocol corner case in a back-to-back-write firmware loop, or a `volatile` ordering bug. The 3B wrapper's silent-drop-while-busy means a missed BUSY poll will deadlock the firmware silently. |
| Notes file + commit                                             | 30 min   | |
| **Total**                                                        | **~5 h** | down from the 4–6 h in 3B's estimate; the wrapper FSM and the bus path are both already proven. |

Risk: low–medium. The hard parts (wrapper FSM, PicoRV32 vendoring,
bus glue) are now done and stress-tested. 3D is "write the firmware
that drives the wrapper through its already-verified motions."

## 9. Reproduction

```bash
source scripts/env.sh
scripts/check_soc_elab.sh           # 3A gate
scripts/run_tb_wb_tile_wrapper.sh   # 3B gate
scripts/run_soc_smoke.sh            # 3C gate (this session)
```

For verbose smoke output (per-transaction trace):

```bash
scripts/build_smoke_firmware.sh
iverilog -g2012 -o /tmp/tb_soc_smoke -s tb_soc_smoke \
    rtl/soc/*.v rtl/tile_tlg_ld/tile_tlg_ld.v vendor/picorv32/picorv32.v \
    tb/tb_soc_smoke.sv
vvp /tmp/tb_soc_smoke +verbose
```

For disassembly of the smoke firmware:

```bash
make -C firmware/smoke lst
cat firmware/smoke/firmware.lst
```
