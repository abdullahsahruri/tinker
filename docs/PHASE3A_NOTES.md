# Phase 3 Session A — architecture spec + skeleton (notes)

> **Headline.** Architecture is locked: PicoRV32 master + Wishbone B4
> single shared bus + 4 slaves (IMEM 8 KB, DMEM 4 KB, TILE 512 B,
> GPIO 16 B), single clock domain, async-assert / sync-deassert
> reset, polled inference handshake. The full spec lives in
> `docs/PHASE3_ARCHITECTURE.md`. Seven skeleton RTL files under
> `rtl/soc/` elaborate cleanly with `iverilog -g2012` and lock in
> the inter-module port lists that 3B/3C/3D will implement against.
> No real logic was written. **GO for Session 3B.**

---

## 1. What this session produced

| Deliverable                                    | Where                                                |
| ---------------------------------------------- | ---------------------------------------------------- |
| 7-section architecture spec                    | `docs/PHASE3_ARCHITECTURE.md` (~620 lines)           |
| 7 skeleton RTL files (correct ports, stub bodies) | `rtl/soc/{soc_top,picorv32_wrapper,wb_interconnect,wb_imem,wb_dmem,wb_tile_wrapper,wb_gpio}.v` |
| Real `tile_tlg_ld` instantiation in the wrapper | `rtl/soc/wb_tile_wrapper.v` (clk/rst_n + tied-off cfg/x_in) |
| Elaboration check script (zero errors today)   | `scripts/check_soc_elab.sh`                          |
| This notes file                                | `docs/PHASE3A_NOTES.md`                              |

The elaboration check was the only "real" thing actually executed
this session. It exercises the cross-module port lists end-to-end,
including the Phase-2 `tile_tlg_ld` source — which is what catches
spec drift early.

## 2. Architectural decisions and the alternatives we rejected

### 2.1 Bus topology — single shared bus, no separate I/D

**Picked.** PicoRV32's native `mem_*` interface is unified
(instructions and data on the same port), so a Harvard split would
have required either two PicoRV32s or an arbiter on top of the
unified port — both worse than just sharing the bus. With a single
master there is no contention to arbitrate. Fetch and load/store
serialise at the core anyway.

**Rejected:** dual-bus split. Would have doubled the interconnect
size for zero throughput gain on a single-master system.

### 2.2 PicoRV32 → WB glue — use upstream `picorv32_wb` wrapper

**Picked.** It's audited, used in real designs, and exposes exactly
the WB-classic master interface the interconnect expects. Pulled in
3C; skeleton has a port-shaped placeholder.

**Rejected:** rolling our own native→WB bridge. ~150 lines of
Verilog plus its own test infra; pure cost, no benefit. The bridge's
signal naming is upstream-fixed and we have to live with that —
fine, the savings dwarf the inconvenience.

### 2.3 Interconnect — single-master 4-slave with comb decode

**Picked.** ~100 LoC of Verilog, all in one file. Decode on
`m_adr_i[31:28]`. No arbitration needed.

**Rejected:** `wb_intercon` / `wbxbar` style multi-master crossbar.
Overkill, more area, no benefit.

### 2.4 Inference handshake — polling on STATUS.BUSY

**Picked.** The tile's 2-cycle pipeline + the 4-5 cycle minimum
poll loop in firmware means the very first poll observes DONE in
nearly all cases. An IRQ controller would add area for ~zero
throughput benefit.

**Rejected:** IRQ-driven completion. Would require enabling
PicoRV32's IRQ unit (more flops in the core), an IRQ controller
peripheral, and IRQ entry/exit code in the firmware. All for the
ability to do other work during a 2-cycle window.

### 2.5 Concurrent-write edge case — silently drop while BUSY

**Picked.** If firmware writes `XIN.HI` (or any cfg register) while
`STATUS.BUSY = 1`, the wrapper acks the bus access normally but
ignores the data. Reasoning:

- Firmware following the §4.5 polling protocol cannot trigger this.
- Buggy firmware that does trigger it gets visibly stuck (the new
  input is never processed, BUSY clears, no new inference fires)
  rather than silently corrupting an in-flight inference.
- Returning a WB error would force firmware to handle bus-error
  exceptions — overkill for a research SoC.

Document in firmware comments. Phase 4 stress firmware can revisit.

### 2.6 Weight memory — exposed-by-wrapper, NOT mirrored in the wrapper

**Picked option (a) from the brief.** The wrapper does not maintain
a 16×64-bit shadow of the weights — it translates Wishbone register
writes directly into `cfg_*` transactions on the existing tile cfg
regfile. Exception: a 16×32-bit `w_lo_shadow` is kept in the
wrapper because each `cfg_we` pulse needs all 64 bits in one
cycle and the bus is 32-bit. Same idea for `XIN.LO`.

This commits firmware to the "load weights once per network"
discipline. `T[i]` writes are atomic (7 bits fit in one bus word
so no shadow needed).

### 2.7 Reset — async-assert, sync-deassert, single domain

**Picked.** A 2-FF reset synchronizer in `soc_top` produces internal
`rst_n` from the chip-pin `rst_n_i`. All sequential logic uses
`always @(posedge clk) if (!rst_n)` reset clauses (synchronous
reset clause, async-deassert handled by the synchronizer). This
matches the existing Phase-2 tile convention so the Phase-2 SDC
extends naturally to the SoC.

The synchronizer is the **only** flop in the whole SoC that uses
`always @(posedge clk or negedge rst_n_i)`.

### 2.8 Storage — register-file IMEM/DMEM, not OpenRAM

**Inherited from project decision.** Documented honestly in the
spec §7: ~100 K flops for ~12 KB total storage, dominated by IMEM
register file. The SoC will be ~5–10× the cell count of the tile
itself, and the tile will be 10–20% of SoC area. The paper's area
discussion needs to acknowledge this; tile-fraction comparisons
against OpenRAM-backed accelerators are not apples-to-apples.

This also flags a Phase-4 expectation: SoC activity-aware power
will likely be IMEM-fetch-dominated, not tile-dominated, **inverting
the Phase-2C narrative at the system level.** Phase 4 measures it.

### 2.9 GPIO — single small peripheral, sentinel-based test exit

**Picked.** 16-byte window with `SIM_END` (write `0xDEADBEEF` to
finish), `OUT` (drives 8-bit gpio_o), `IN` (reads 8-bit gpio_i). No
UART. The `SIM_END` sentinel is the cleanest way to terminate a
firmware-driven testbench without a special "stop simulation"
primitive.

## 3. Spec ambiguities resolved (and how)

| Ambiguity from the brief                              | Resolution |
| ----------------------------------------------------- | ---------- |
| Concrete base addresses                               | IMEM = `0x0000_0000`, DMEM = `0x1000_0000`, TILE = `0x2000_0000`, GPIO = `0x3000_0000`. Decode bits = `adr[31:28]`. Aligns with PicoRV32's default `PROGADDR_RESET = 0`. |
| Polling vs separate "go" register                     | Polling on `STATUS.BUSY`; the "go" event is implicit in writing `XIN.HI`. One fewer register, one fewer write per inference. |
| Weight write order — low or high word first?          | LO first, HI commits. Reason: writing HI=committing makes the "ready to fire" instant explicit at a single firmware instruction. |
| Threshold packing in 32-bit words                     | One threshold per 32-bit word, low 7 bits used. Wastes 25 bits per threshold but makes the firmware loop trivial; thresholds are 64 B total so the waste is negligible. |
| Tile window padded size                               | 512 B (`0x200`). Used: through `0x110`. Headroom for Phase-4 status registers (cycle counter, error flags, etc.) without re-allocating address space. |
| What `SOFT_RESET` resets                              | Only the wrapper's FSM + shadows; **not** the tile's cfg regfile. Lets firmware abort a stuck inference without losing the loaded weights. |
| Whether reads of weight/threshold registers return data | No — return 0. The tile cfg regfile is write-only at the tile boundary; mirroring it in the wrapper would double the weight storage for read-back convenience. Verify-by-inference is the discipline. |
| Stack pointer initial value                           | `0x1000_1000` (top of DMEM). Stack grows down. |
| `picorv32_wb` parameter overrides                     | Locked the full table in `PHASE3_ARCHITECTURE.md` §3.4 (BARREL_SHIFTER off, no IRQ, no MUL/DIV, no compressed). 3C verifies upstream supports them all. |
| Whether decode-miss raises `wb_err`                   | Yes — interconnect drives `m_err = 1` on unmapped accesses. Firmware never generates these in normal operation; the err path makes a wild pointer hang visibly rather than silently. |

## 4. Intentionally underspecified — for Sessions 3B/3C/3D/3E

Listed in `PHASE3_ARCHITECTURE.md` §10. Cross-referenced here with
the session that owns each:

| Topic | Owner |
| --- | --- |
| `wb_imem` / `wb_dmem` register-file model + `$readmemh` plumbing | 3B |
| Real address decoder + read-data mux in `wb_interconnect` | 3B |
| Real register-bank FSM in `wb_tile_wrapper` (the meatiest 3B work) | 3B |
| Optional `ifdef SIM` debug backdoor for tile cfg | 3B |
| PicoRV32 vendor pull (commit-pinned) + real `picorv32_wb` instantiation | 3C |
| PicoRV32 boot ROM + smoke firmware | 3C |
| Real firmware (weight load + inference loop) and toolchain settings | 3D |
| MNIST data path: `.rodata` table vs runtime UART | 3D |
| Optional cycle counter peripheral for benchmarking | 3D / 4 |
| LibreLane SDC + flow knobs for the SoC | 3E |
| IMEM init mechanism inside LibreLane (vendor BRAM init vs `initial`) | 3E |

**Nothing in this list contradicts the locked spec — they are
implementation freedoms within the contract.** Anything that *does*
require revisiting the spec gets a note in the relevant session's
notes file plus a corresponding edit to `PHASE3_ARCHITECTURE.md`
with a `> Updated 2026-MM-DD by Session 3X.` block.

## 5. Estimated complexity of subsequent sessions

| Session | Scope | Wall-clock estimate | Risk |
| --- | --- | --- | --- |
| **3B — bus + tile wrapper bring-up** | Real `wb_interconnect` decoder + read mux, `wb_imem` + `wb_dmem` register-file models with `$readmemh`, `wb_gpio`, and the `wb_tile_wrapper` FSM (the meatiest part: shadow regs + weight-commit + XIN-commit + busy/done capture). Unit testbench at the WB-master level (drive transactions, no PicoRV32 yet). | 4–6 h | Medium. The wrapper FSM has several concurrent commit paths (W_HI, T, XIN_HI) and edge cases (writes during BUSY); easy to get wrong. Unit-test it hard before integrating with PicoRV32. |
| **3C — PicoRV32 + memory bring-up** | Vendor `picorv32` at a pinned commit, replace `picorv32_wrapper.v` body with `picorv32_wb` instantiation, write a minimal "blink-the-GPIO" firmware that boots from IMEM and writes to GPIO, run end-to-end in iverilog. | 3–4 h | Low–medium. The wrapper is upstream-tested; the main risks are linker-script errors and the IMEM `$readmemh` plumbing. RV32I toolchain is already installed (apt's `gcc-riscv64-unknown-elf`). |
| **3D — firmware + end-to-end inference** | Write the C inference firmware (weight table + threshold table + input vectors as `.rodata`, polling loop), build with `-Os`, load into IMEM, run end-to-end. Verify the SoC's outputs match a Python golden model on the same input vectors. | 4–6 h | Medium. The functional check has to round-trip through the firmware → bus → tile → back, so any bug in 3B's wrapper FSM or 3C's bus glue resurfaces here. Catch-up debug cost can be large if 3B was rushed. |
| **3E — SoC P&R** | Wrap everything in a LibreLane config, reuse the Phase-2 SDC as a starting point, run the flow, collect PPA. Likely needs SDC adjustments for the bigger clock tree and the IMEM register file's read-port load. | 6–10 h, of which most is wall-clock waiting on the LibreLane flow. | Medium–high. The SoC is ~5–10× the tile's cell count; routing and STA may run for hours, and the regfile-IMEM is unfriendly to congestion-driven place. Memory pressure is the main worry — confirmed 13 GiB WSL is enough for the tile but the SoC will be the first real test. |

**Total Phase 3 budget (3B–3E):** ~17–26 h of focused work across
4 sessions, plus LibreLane wall-clock. Well within the project
schedule.

## 6. Sanity checks done this session

- `iverilog -g2012 -Wall` elaborates `rtl/soc/*.v` + `rtl/tile_tlg_ld/
  tile_tlg_ld.v` without errors. Compiles to `/tmp/soc_elab_check`.
- The tile is instantiated *for real* inside `wb_tile_wrapper`
  (not just port-listed), so a future change to `tile_tlg_ld`'s
  port list breaks the elaboration check immediately rather than
  later.
- Every skeleton output is driven (mostly to constants) so iverilog
  doesn't silently leave a Z on a port — port-list mismatches
  surface as elaboration errors, not as runtime X-propagation.
- Memory map address bits are non-overlapping: IMEM 0x0–, DMEM
  0x1–, TILE 0x2–, GPIO 0x3–, decode-miss 0x4–0xF. No collision
  possible.
- Reset polarity and synchronizer style match the Phase-2 tile
  convention (synchronous reset clause inside `always @(posedge
  clk)`), so the Phase-2 SDC's reset handling extends to the SoC.

## 7. What did NOT happen this session (intentionally)

- No real logic in any skeleton module beyond the reset
  synchronizer (which is the only block whose function is fully
  defined by the spec — three lines, no FSM, hard to defer).
- No PicoRV32 source pulled — that's 3C.
- No firmware written — that's 3D.
- No LibreLane runs — that's 3E.
- No simulation runs — there's nothing to simulate yet (everything's
  a stub that drives 0).
- No changes to `rtl/tile_tlg_ld/`, `scripts/gen_tile.py`, or any
  Phase-2 artifact. The Phase-2 result is frozen.

## 8. Reproduction

```bash
source scripts/env.sh
scripts/check_soc_elab.sh        # exits 0 if the skeleton elaborates
```

Read the spec at `docs/PHASE3_ARCHITECTURE.md` before kicking off
3B. Skeleton port lists are the contract.
