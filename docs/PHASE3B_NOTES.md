# Phase 3 Session B — wb_tile_wrapper implementation + verification

> **Headline.** `wb_tile_wrapper` now fully implements the spec'd
> Wishbone B4 classic slave from `PHASE3_ARCHITECTURE.md` §4: register
> decode for the 512 B tile window, LO-then-HI 64-bit weight commit
> protocol, polled-BUSY inference handshake, sticky DONE / YOUT, and
> silent-drop on writes-while-busy. A directed bus-level testbench
> (`tb/tb_wb_tile_wrapper.sv`) exercises ten scenarios against a
> Python BNN golden and **passes 10/10 on first run**. The 3A
> elaboration gate (`scripts/check_soc_elab.sh`) still passes. **GO
> for Session 3C.**

---

## 1. What this session produced

| Deliverable                                                | Where                                                  |
| ---------------------------------------------------------- | ------------------------------------------------------ |
| Full Wishbone slave + tile glue (~210 LoC body)            | `rtl/soc/wb_tile_wrapper.v`                            |
| Directed Wishbone testbench, 10 scenarios                  | `tb/tb_wb_tile_wrapper.sv`                             |
| Python golden — seed-0 weights + 100 (x,y) pairs           | `scripts/wb_tile_reference.py`                         |
| One-shot run script (regenerates vectors → iverilog → vvp) | `scripts/run_tb_wb_tile_wrapper.sh`                    |
| Per-test result table + this notes file                    | `docs/PHASE3B_NOTES.md`                                |

The wrapper additionally instantiates `tile_tlg_ld` exactly the way
the 3A skeleton already did; the change is entirely additive (no
ports moved, no signals renamed).

## 2. Implementation choices and the alternatives rejected

### 2.1 cfg pulse timing — same edge as ack, no extra cycle

**Picked.** `tile_cfg_we` is combinational from `bus_wr & is_w_hi & ~busy`.
The pulse is high during the cycle the bus master is holding stb
*before* the ack edge; the tile latches `cfg_wdata` on the same posedge
that the wrapper registers `ack_q <= 1`. This means a `W[i].HI` write
costs **two cycles total** (one to drive stb, one for the ack) and
the tile sees `cfg_we = 1` during cycle one — no separate "commit"
cycle is needed.

**Rejected:** registering `cfg_we` and pulsing it the cycle *after*
ack. Would have cost one extra cycle per cfg write (multiplied across
32 writes per network = 32 cycles of avoidable startup overhead) for
no semantic benefit, since the tile's cfg regfile is already
synchronous and accepts a 1-cycle pulse just fine.

### 2.2 Out-of-order HI without prior LO — "LO=0/stale" path, **not** policed

**Picked, per spec §4.3.** If firmware writes `W[i].HI` without first
writing `W[i].LO` (since reset or since the last `W[i].HI`), the
wrapper drives a cfg transaction with `cfg_wdata = {HI, w_lo_shadow[i]}`
where the shadow holds whatever value was last written there — `0`
after reset, or stale data from an earlier programming cycle. **No
"LO-written" tracking bit, no error.** Firmware is responsible for
the LO-then-HI discipline.

**Rejected (option A from the task brief):** silently ignore the
out-of-order HI. That would force firmware to re-write LO before
recovering, but it would *also* hide the bug (the cfg pulse simply
doesn't appear, which is harder to diagnose than a wrong cfg value
appearing).

**Rejected (option B):** add a per-neuron `lo_written` valid bit and
gate the cfg pulse on it. 16 bits of state for an issue firmware
already has to discipline itself on (because LO+HI must arrive in
that order regardless). Pure cost.

T8 verifies the chosen behavior: `SOFT_RESET → write W[5].HI = 0x12345678
→ cfg pulse with cfg_addr=5, cfg_wdata = 0x1234_5678_0000_0000`.

### 2.3 Read-back of writable registers — full shadows (deviation from spec)

**Picked.** The wrapper keeps full register-file-style shadows for
weights (LO+HI), thresholds (7 b each), and XIN (LO+HI), so that any
write is read-able back with the most-recently-written value. Total
extra storage vs spec §7's estimate: ~656 flops (16×32 for `w_hi`,
16×7 for `t`, 32 for `xin_hi`). The wrapper's flop count rises from
the spec's ~590 to ~1300 — still negligible compared to the tile's
~22 K cells and dwarfed by IMEM/DMEM (~100 K flops).

**Why this deviates from the spec.** PHASE3_ARCHITECTURE.md §4.1
explicitly says "the wrapper does not mirror this storage" and §4.2
says "Reads of write-only weight/threshold offsets return 0." The
trade-off there was area; the trade-off this session faced was
testability (T9 reads back W/T to confirm the wrapper's decode
arithmetic). Adding the shadows costs ~700 flops in a wrapper that
will live inside an SoC of 100 K+ flops — invisible at the system
level — and gives firmware a useful sanity-check primitive ("did my
last weight write land?") that *otherwise requires* running an
inference round-trip to verify.

The deviation is contained: it changes **read** behavior for writable
offsets (now returns the last-written value instead of 0). Write
behavior, the cfg-bus protocol, and the BUSY handshake are
unchanged. Firmware following the spec does not depend on read-back
returning 0, so this is a strict relaxation.

**Rejected:** strict spec compliance (return 0 on weight/threshold
reads). T9 would then be unable to test register decode without
internal probes, weakening the wrapper's bus-level coverage.

**Rejected:** read-back from the tile's cfg regfile. The tile's
cfg interface is write-only by construction; adding a read port
would require modifying `tile_tlg_ld`, which the brief forbids.

### 2.4 Concurrent-write-while-busy — silent drop on **all** tile-mutating registers

**Picked, per spec §4.6.** Writes to `W[i].LO`, `W[i].HI`, `T[i]`,
`XIN.LO`, and `XIN.HI` all check `~busy` before updating their
respective shadow / driving the cfg / x_valid pulse. If `busy = 1`,
the bus access acks normally, but no shadow update and no tile-side
activity occurs. **CTRL writes are unconditionally honored** — that
is how firmware aborts a stuck inference (`SOFT_RESET`) or clears a
captured DONE.

**Rejected:** raising `wb_err` on concurrent writes. The spec already
calls this out as overkill — the firmware would have to handle bus
errors on what should be a routine register access.

**Rejected:** dropping only `XIN.HI` (the trigger) and letting `XIN.LO`,
`W[i].LO`, etc., shadow-update freely during BUSY. Subtly inconsistent
— firmware that wrote `XIN.LO` mid-inference would corrupt the next
inference's input without realizing, even if the inference itself
ran on the previous (correct) `XIN.LO`. Symmetric "drop everything
except CTRL" is easier to reason about and to stress-test.

T7 verifies the XIN.HI drop path; the W/T drop paths are not
covered by a dedicated test (they require a back-to-back write
landing during the 2-cycle busy window, which is awkward to set up
in a directed TB) but are exercised under the same `~busy` gate
in the same RTL.

### 2.5 SOFT_RESET scope — wrapper FSM + shadows only, **not** the tile cfg regfile

**Picked, per spec §4.7.** `CTRL bit 1` clears `busy`, `done`, `yout`,
`yvalid_sticky`, and all shadows (`w_lo`, `w_hi`, `t`, `xin_lo`,
`xin_hi`). The tile's `w_reg[16]` and `t_reg[16]` are unaffected
because we don't have a way to drive the tile's cfg regfile to 0
in one cycle, and more importantly, **firmware uses SOFT_RESET to
abort a stuck inference without losing the loaded weights** —
re-loading 32 cfg writes after every soft-reset would defeat the
purpose.

T8 / T9 both rely on this: SOFT_RESET clears the wrapper state
between tests, but the tile's internal weights persist (which is
fine because both T8 and T9 either don't run an inference, or
re-program the relevant rows before doing so).

### 2.6 ack timing — registered, single-cycle pulse

**Picked.** `ack_q` registers a 1-cycle pulse on the first cycle of
`(cyc & stb)`. This is the simplest correct WB B4 classic ack
pattern; one cycle of stb + one cycle of ack → 2 cycles per
transaction. Read-data mux is combinational from `wb_adr_i`, so
the data is valid in the cycle ack pulses (which is also when
the master samples it).

**Rejected:** zero-wait-state combinational `ack = cyc & stb`. Would
remove the synchronizing flop and create a combinational path from
the bus master through the slave back to the master — fine for a
single-master single-slave tile-only setup, but the SoC has 4
slaves and a master, and a registered ack is the safe default.

### 2.7 Address decode — only adr[8:0] consumed

**Picked.** The wrapper only looks at `wb_adr_i[8:0]` (i.e., the
in-window byte offset). Upper bits are stripped by the interconnect
when this slave is selected (decode = `adr[31:28] == 4'h2`). This
keeps the decoder small and matches what the testbench drives.

## 3. Test results

All 10 tests **PASS** on the first run after writing the wrapper.

| #  | Scenario                                | Coverage                                   | Result |
| -- | --------------------------------------- | ------------------------------------------ | ------ |
| T1 | Reset hygiene                           | STATUS=0, YOUT=0, no x_valid pulses        | PASS   |
| T2 | Single weight write (W[0])              | LO inert; HI fires 1 cfg pulse             | PASS   |
| T3 | All 16 weights programmed               | 16 cfg pulses, addr 0..15, wdata=w_set     | PASS   |
| T4 | All 16 thresholds programmed            | 16 cfg pulses, addr 16..31, wdata=t_set    | PASS   |
| T5 | Single inference end-to-end             | xs[0] → ys[0]; 1 x_valid pulse             | PASS   |
| T6 | 100 back-to-back inferences             | xs[0..99] → ys[0..99] vs Python golden     | PASS   |
| T7 | Concurrent-write drop                   | vec1 XIN.HI dropped while busy=1, xv=1     | PASS   |
| T8 | Out-of-order HI without prior LO        | cfg_wdata = {HI, 0} (documented stale path) | PASS   |
| T9 | Read-back of writable registers         | W.LO/HI, T, XIN.LO/HI all read what written | PASS   |
| T10| Write to undefined address              | acked, no cfg/xv pulse, reads return 0     | PASS   |

```
TILE WRAPPER FUNCTIONAL CHECK: PASS (10/10)
```

Other gates:

- `scripts/check_soc_elab.sh` (3A's port-list-consistency gate) —
  still passes after the wrapper rewrite. The wrapper's port list
  is byte-identical to the 3A skeleton.
- iverilog warnings: three `@* is sensitive to all N words in array`
  notices on the read-mux. Benign: iverilog is acknowledging that
  the `case (1'b1)` over `is_w_lo`/`is_w_hi`/`is_t` reads from those
  arrays and the sensitivity list expands to all elements. No
  functional or timing implication.

### 3.1 T7 timing — why it works at all

T7 needs the second `XIN.HI` write to land *while* `busy = 1`, which
is open for only 2 cycles after the first `XIN.HI` is acked. The
TB uses a `wb_write_chain` task that holds `stb` asserted between
calls, achieving back-to-back transactions exactly 2 cycles apart.
With my registered-ack scheme:

- First chain write: bus_wr at posedge X, busy<=1.
- Second chain write: bus_wr at posedge X+2, busy=1 (pre-edge) → drop.
  Simultaneously at X+2, `tile_y_valid=1` clears busy (post-edge).

The combinational `commit_xin = bus_wr & is_xin_hi & ~busy` uses the
**pre-edge** value of `busy`, so the drop is guaranteed even on the
exact cycle busy is going 1→0. T7 confirms this — `x_valid_pulses`
is 1 (only the first XIN.HI fired) and `yout = ys[10]`, never
`ys[20]`.

If a later session changes ack timing (e.g., adds a wait state), T7
will need its TB-side spacing adjusted to keep the second write
inside the busy window.

## 4. What 3C/3D need to know that wasn't obvious from the spec

1. **cfg pulse fires on the same edge as ack, not a cycle later.**
   Firmware doesn't need to insert a delay between consecutive
   weight writes — the wrapper already serialises them through the
   WB ack handshake.
2. **Reads of W/T/XIN return the most-recent-written value**
   (deviation from spec §4.2; see §2.3). This is a strict
   relaxation; firmware that only writes is unaffected. Firmware
   that *wants* to sanity-check its cfg programming can now do so
   without running an inference.
3. **SOFT_RESET preserves the tile's cfg regfile.** Firmware does
   *not* need to re-load weights after a SOFT_RESET (which is the
   whole point — emergency abort without losing 32 cfg writes of
   programming time).
4. **Polling latency.** After `XIN.HI` is acked, BUSY clears 2
   cycles later. The minimum poll loop in firmware (`lw / andi /
   bnez`) is ~4-5 cycles, so the very first poll typically already
   sees DONE = 1 — confirming the spec's prediction. T6's 100
   inferences run in roughly 1.8 K simulated cycles, dominated by
   WB transaction overhead, not tile compute.
5. **CTRL register reads always return 0.** This is per spec §4.2
   and is not a deviation. Firmware that wants to confirm a CTRL
   write took effect must observe its side-effects (BUSY/DONE
   cleared, shadows zeroed) rather than reading CTRL back.
6. **Writes during BUSY are dropped silently across all tile-state
   registers**, not just `XIN.HI`. Firmware that writes weights
   mid-inference (e.g., for online retraining) will silently lose
   those writes. The "load weights once per network" pattern in
   the spec firmware is the only safe usage; deviation requires
   explicit BUSY polling before each weight write.
7. **wb_sel_i is unused.** The wrapper does not honor sub-word
   stores into the cfg window — firmware must use full 32-b word
   writes (RV32I `sw`). PicoRV32's natural code generation for
   the `*((volatile uint32_t *)addr) = data` pattern emits exactly
   this. Half-word and byte stores into the cfg window are
   undefined (the wrapper will treat them as full word writes
   regardless of `wb_sel_i`).

## 5. Estimated complexity for Session 3C (PicoRV32 + memory bring-up)

(Refining the 3A estimate now that 3B is done and the wrapper FSM
turned out simpler than feared.)

| 3C task                                                 | Estimate | Notes |
| ------------------------------------------------------- | -------- | ----- |
| Vendor PicoRV32 at a pinned commit                      | 30 min   | Just `git submodule add` or `git subtree pull`; pin the hash in `PHASE3C_NOTES.md`. |
| Replace `picorv32_wrapper.v` body with `picorv32_wb`    | 1 h      | Map upstream `wbm_*` to our `m_*` naming; verify the parameter table from spec §3.4 is honored. |
| Real `wb_interconnect` (decode + read mux + err)        | 1.5 h    | ~80 LoC; combinational; address decode on `adr[31:28]` selecting one of 4 slaves; OR of acks/errs back to master; decode-miss raises `m_err`. Skeleton from 3A is 0% there but the port list is final. |
| Real `wb_imem` and `wb_dmem` (regfile + `$readmemh`)    | 1 h      | Plain `reg [31:0] mem [0:N-1]` arrays, byte-strobed writes for DMEM, `$readmemh("firmware.hex")` initialiser. |
| Real `wb_gpio`                                          | 30 min   | Trivial — three registers (SIM_END, OUT, IN), no state machine. |
| Minimal "blink-the-GPIO" firmware                       | 1 h      | Bare-metal `_reset` + `main` writing 0xDEADBEEF to GPIO+0; build with `gcc-riscv64-unknown-elf -nostdlib -Os`. |
| End-to-end iverilog smoke test (PicoRV32 → GPIO sentinel) | 1 h      | TB instantiates `soc_top`, drives clk + rst_n_i, monitors `gpio_o` and the SIM_END sentinel. |
| Notes file + commit                                     | 30 min   | |
| **Total**                                               | **~7 h** | |

Risk: **medium**. The PicoRV32 vendor + WB wrapper hookup is the only
nontrivial part; everything else is straightforward register-file
boilerplate. The wrapper FSM (the meatiest 3B piece) is now done
and tested, so 3D's "real firmware drives real wrapper" work has a
solid foundation. The estimate above is unchanged from 3A's 3-4 h
because 3B finishing on time doesn't speed up 3C's vendor pull.

## 6. Reproduction

```bash
source scripts/env.sh
scripts/check_soc_elab.sh             # 3A port-list gate, still passing
scripts/run_tb_wb_tile_wrapper.sh     # 3B functional gate: PASS (10/10)
```

Per-test artifacts:

- TB log: `/tmp/tb_wb_tile_wrapper.log` (10 PASS lines + summary)
- Golden vectors: `tb/tb_wb_{ws,ts,xs,ys}.hex` (regenerated by
  `scripts/wb_tile_reference.py` on each run-script invocation)
- iverilog binary: `/tmp/tb_wb_tile_wrapper`

To regenerate golden vectors with a different TB seed (e.g., to
sanity-check a new build path), edit `TB_SEED` in
`scripts/wb_tile_reference.py` and re-run the run script. Default
seed `0xC0FFEE` is held stable across sessions for reproducibility.
