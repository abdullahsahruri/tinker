# Phase 3 — SoC architecture specification

**Status: locked in Session 3A (architectural decisions only).** This
document defines the interface contract and module hierarchy that
sessions 3B–3E will implement and bring up. Anything not specified
here is either deferred to a later session by design (and called out
in §10) or is an implementation freedom of the relevant session.

The goal of the SoC: a minimal RISC-V system-on-chip whose sole
purpose is to demonstrate the Phase-2C TLG_ld accelerator tile under
software control. PicoRV32 boots from on-chip ROM, programs the
tile's weight regfile once per network, then loops over MNIST input
vectors driving the tile and capturing classification outputs. The
SoC exists to make the tile measurable end-to-end (functional and
power) inside a system context, not to be a generally-useful
microcontroller.

---

## 1. Top-level block diagram

```
                  +--------------------------------------------------+
                  |                       soc_top                    |
                  |                                                  |
   clk     ------>|--+                                               |
   rst_n_i ----+  |  |                                               |
               v  |  v                                               |
          +---------------+                                          |
          | reset_sync    |  rst_n (synchronous-deassert)            |
          +---------------+                                          |
                  |                                                  |
                  v                                                  |
          +-----------------+         WB-master                      |
          | picorv32_wrap   |---------------------------+            |
          | (RV32I core +   |  cyc/stb/we/sel/adr/dat   |            |
          |  native->WB     |<--------------------------+            |
          |  bridge)        |                                        |
          +-----------------+                                        |
                  |                                                  |
                  v                                                  |
          +-----------------------------------------------+          |
          |              wb_interconnect                  |          |
          | (single-master, 4-slave, comb. address dec)   |          |
          | decode = adr[31:28]                           |          |
          +-----------------------------------------------+          |
            |          |             |              |                |
   adr31:28 |          |             |              |                |
   = 0x0    | = 0x1    | = 0x2       | = 0x3        |                |
            v          v             v              v                |
       +---------+ +---------+ +-----------------+ +-----------+     |
       | wb_imem | | wb_dmem | | wb_tile_wrapper | |  wb_gpio  |---->| gpio_o[7:0]
       | 8 KB    | | 4 KB    | | (cfg regs +     | |           |<----| gpio_i[7:0]
       | RX      | | RW      | |  tile_tlg_ld)   | |           |     |
       +---------+ +---------+ +-----------------+ +-----------+     |
                                       |                             |
                                       | clk/rst_n + cfg_*           |
                                       | + x_in/x_valid/y_*          |
                                       v                             |
                               +-----------------+                   |
                               |  tile_tlg_ld    |                   |
                               |  (Phase 2C IP,  |                   |
                               |   unmodified)   |                   |
                               +-----------------+                   |
                  +--------------------------------------------------+
```

All blocks share a single clock domain. The only chip-boundary inputs
are `clk`, `rst_n_i`, and (optional, sim-only) `gpio_i[7:0]`; outputs
are `gpio_o[7:0]`. There is no off-chip memory bus, no DDR, no
external flash — the SoC self-contains everything. This is
deliberate: the experiment we want to publish is the
tile-in-system, not a general-purpose MCU.

---

## 2. Memory map

Address space: 32-bit, byte-addressable. RISC-V little-endian. All
slaves are 32-bit data wide with byte-strobe granularity; PicoRV32's
`mem_wstrb[3:0]` maps directly onto Wishbone `sel[3:0]`.

Decode: `adr[31:28]` selects the slave; lower bits are the in-slave
offset. Unmapped accesses raise `wb_err_i` to PicoRV32 (the
interconnect drives `m_err` high when no slave is selected — see
§3.4). Firmware will not generate such accesses in normal operation;
the err path exists so a wild pointer hangs visibly rather than
silently.

| Region   | Base         | Size  | Decode (adr[31:28]) | Access | Word width | Notes                                                        |
| -------- | ------------ | ----- | ------------------- | ------ | ---------- | ------------------------------------------------------------ |
| **IMEM** | `0x0000_0000`| 2 KB  | `0x0`               | RX     | 32-bit     | Reset vector at base. Firmware lives here. Read-only at run-time; loaded by the testbench (or Session 3E flow) via `$readmemh`. Sized to 2 KB in the Session 3E baseline rerun (down from the 8 KB Session 3A spec) to fix a 15 115-fanout IMEM read-mux that the open-flow resizer could not close at the slow corner — see §7. |
| **DMEM** | `0x1000_0000`| 1 KB  | `0x1`               | RW     | 32-bit     | Stack, heap, scratchpad, MNIST input/output buffers. Initialised to 0 on reset. Shrunk from 4 KB in the Session 3E baseline rerun for symmetry with the IMEM reduction; the 32-word test-image preload + small stack still fit comfortably. |
| **TILE** | `0x2000_0000`| 512 B | `0x2`               | RW     | 32-bit     | Tile cfg regfile + control/status + I/O windows. See §4 for the per-byte layout. |
| **GPIO** | `0x3000_0000`| 16 B  | `0x3`               | RW     | 32-bit     | Sim observability: write a byte to print or otherwise emit it; pulse a "done" pin to end-of-test the bench. See §6. |

Reserved decode values (`0x4`–`0xF`) are unmapped and assert
`m_err`. Total mapped on-chip storage in the Session 3E baseline:
3 KB across IMEM + DMEM (originally specified as 12 KB in 3A; see §7
for rationale), plus ~144 bytes of architectural state in the tile
cfg regfile (§4). Decode bits, base addresses, and the chip-pin
contract are unchanged from 3A — only the in-slave depths shrunk,
so firmware that respects the SIZE_BYTES parameter recompiles
cleanly without code-side changes.

### 2.1 Reset vector

`PROGADDR_RESET = 0x0000_0000` (top of IMEM). PicoRV32 starts
fetching from there on the cycle after `rst_n` deasserts. No
interrupt vector is used — all SoC operation is bare-metal polled
(see §5).

### 2.2 Why no MMIO timer / IRQ controller

The brief mandates polling for the inference handshake (§4.5). With
no asynchronous events to service, an IRQ controller and timer would
be dead area. Adding them is an explicit non-goal of Phase 3.

---

## 3. Wishbone bus

### 3.1 Variant

**Wishbone B4 classic, single-read / single-write, no burst, no
pipelining.** This is the simplest legal Wishbone profile and is
sufficient for a single-master, low-bandwidth control bus. All
transactions complete in 1 cycle of `STB & CYC` plus N wait states
(slave-defined; expect 0 wait states for our slaves). No
`tagn_i`/`tagn_o` signals.

### 3.2 Widths

| Signal       | Width   | Notes                                              |
| ------------ | ------- | -------------------------------------------------- |
| `adr`        | 32-bit  | Byte address. Slaves are word-aligned; `adr[1:0]` is unused on word accesses but routed for completeness so byte/halfword addressing remains possible if a slave wants it. |
| `dat_o`/`dat_i` | 32-bit | Single data width for the whole bus.            |
| `sel`        | 4-bit   | Byte-enable per byte lane. Wired from PicoRV32's `mem_wstrb` on writes; tied to `4'b1111` on reads. |
| `we`         | 1-bit   | 1 = write, 0 = read.                              |
| `stb` / `cyc`| 1-bit   | Both asserted together for a single transaction. |
| `ack`        | 1-bit   | Slave asserts for one cycle to terminate.        |
| `err`        | 1-bit   | Slave asserts for one cycle to signal a faulted access (e.g., write to a RO register, decode miss). The interconnect aggregates per-slave `err` and a decode-miss `err` into the master `err` line. |

No `rty` (we never need to retry) and no `lock` (single master).

### 3.3 Granularity

Byte. PicoRV32 issues `mem_wstrb[3:0]` on writes; the wrapper passes
this through as `sel[3:0]`. On reads PicoRV32 always wants a full
word, so `sel = 4'b1111` and slaves return the full 32-bit value.
RW slave registers may be implemented as 32-bit only (i.e., ignore
`sel` on writes and require the firmware to do read-modify-write for
sub-word updates) — the only place sub-word writes will actually
matter is DMEM, which must support them (RISC-V `sb`/`sh`).

### 3.4 PicoRV32 → Wishbone glue

**Decision: use the upstream `picorv32_wb` wrapper that ships in
[YosysHQ/picorv32](https://github.com/YosysHQ/picorv32).** That
wrapper exposes a Wishbone-classic master interface
(`wbm_cyc_o`/`wbm_stb_o`/`wbm_we_o`/`wbm_sel_o`/`wbm_adr_o`/
`wbm_dat_o`/`wbm_dat_i`/`wbm_ack_i`) directly, which is exactly
what our interconnect expects.

Why the wrapper rather than rolling our own native→WB bridge:

- The wrapper is upstream-maintained, used in real designs, and
  already handles the corner cases (look-ahead read, single-cycle
  ack, etc.) that the native PicoRV32 `mem_*` interface needs.
- Writing our own bridge is ~150 lines of Verilog plus its own
  testbench — pointless when an audited one exists.
- Tradeoff: it pulls in a few hundred extra lines from upstream
  and locks us to upstream's signal naming. Both are fine.

Session 3C pulls the picorv32 source, vendors it under `rtl/vendor/
picorv32/`, and pins the commit hash in `docs/PHASE3C_NOTES.md`.
Session 3A's `picorv32_wrapper.v` is a port-shaped placeholder that
3C replaces with a real `picorv32_wb` instantiation (see §8.2).

PicoRV32 parameter choices (locked here, applied in 3C):

| Parameter              | Value | Rationale                                           |
| ---------------------- | ----- | --------------------------------------------------- |
| `ENABLE_COUNTERS`      | 0     | No `rdcycle`/`rdinstret` needed; saves area.        |
| `ENABLE_COUNTERS64`    | 0     | Same.                                               |
| `ENABLE_REGS_16_31`    | 1     | RV32I requires it.                                  |
| `ENABLE_REGS_DUALPORT` | 1     | Faster regfile, ~no area cost in flop-based regfile. |
| `LATCHED_MEM_RDATA`    | 0     | Default; the WB wrapper handles latching.           |
| `TWO_STAGE_SHIFT`      | 1     | Default; smaller area.                              |
| `BARREL_SHIFTER`       | 0     | Inference loop has no shifts on the hot path.       |
| `TWO_CYCLE_COMPARE`    | 0     | Default.                                            |
| `TWO_CYCLE_ALU`        | 0     | Default.                                            |
| `COMPRESSED_ISA`       | 0     | Use rv32i, not rv32ic — simpler firmware build.     |
| `CATCH_MISALIGN`       | 0     | Firmware only does aligned accesses.                |
| `CATCH_ILLINSN`        | 0     | Same.                                               |
| `ENABLE_PCPI`          | 0     | No coprocessor.                                     |
| `ENABLE_MUL` / `_DIV`  | 0     | M extension not used.                               |
| `ENABLE_FAST_MUL`      | 0     | Same.                                               |
| `ENABLE_IRQ`           | 0     | Polled handshake (§4.5).                            |
| `ENABLE_IRQ_QREGS`     | 0     | Same.                                               |
| `ENABLE_IRQ_TIMER`     | 0     | Same.                                               |
| `REGS_INIT_ZERO`       | 1     | Deterministic post-reset state for sim.             |
| `MASKED_IRQ`           | n/a   | IRQs disabled.                                      |
| `PROGADDR_RESET`       | `32'h0000_0000` | Top of IMEM.                                |
| `PROGADDR_IRQ`         | `32'h0000_0010` | Default; unused (IRQs off).                 |
| `STACKADDR`            | `32'h1000_0400` | Top of DMEM (1 KB in the Session 3E baseline; was `0x1000_1000` for the 4 KB DMEM in 3A–3D). Stack grows down. |

### 3.5 Interconnect topology

Single shared bus, combinational address decode, no arbitration —
PicoRV32 is the only master. The interconnect is one Verilog file
(`wb_interconnect.v`) with:

- A 4-way address decoder on `adr[31:28]` selecting one of {IMEM,
  DMEM, TILE, GPIO}.
- A demuxed `cyc`/`stb`/`we` to the selected slave; all other slaves
  see `cyc = 0`.
- A muxed read-data path back to the master based on which slave is
  currently selected.
- An OR of all slaves' `ack` lines (only the selected slave should
  assert) and an OR of all `err` lines plus a decode-miss `err`.

This is small (≈100 LoC) and adequate. We do **not** use the
`wbxbar`/`wb_intercon` style multi-master crossbar — overkill for
single-master.

---

## 4. Tile wrapper interface (`wb_tile_wrapper`)

This is the most spec-heavy block in the SoC. The wrapper exposes
the existing `tile_tlg_ld` (whose interface is fixed by Phase 2 — do
not modify) as a memory-mapped peripheral.

### 4.1 Tile cfg regfile and the decision NOT to mirror it

`tile_tlg_ld` already contains a `16 × 64-bit` weight regfile and
`16 × 7-bit` threshold regfile addressed via
`(cfg_we, cfg_addr[5:0], cfg_wdata[63:0])`. Per the Phase 3 brief
(option (a)), **the wrapper does not mirror this storage** — it
translates Wishbone register writes into one or two `cfg_*`
transactions on the tile and drops them. Exception: the LOW half of
each weight is held in a 32-bit shadow inside the wrapper because
each tile cfg write needs 64 bits in one cycle; see §4.3.

Practical consequence: **firmware writes weights once per network**,
not per inference. The 32 cfg writes in §5 are amortized over
thousands of inferences.

### 4.2 Register layout (byte offsets within the 512 B window)

| Offset       | Name             | W/R/RO | Width     | Purpose |
| ------------ | ---------------- | ------ | --------- | ------- |
| `0x000`–`0x07F` | `W[i].LO`/`W[i].HI` (interleaved, 8 B per neuron, i = 0..15) | RW (writes only) | 32 b each | Weight programming. `W[i].LO` at `0x000 + 8*i`, `W[i].HI` at `0x004 + 8*i`. See §4.3 for the commit rule. |
| `0x080`–`0x0BF` | `T[i]` (i = 0..15) | RW (writes only) | 7 b in low bits of a 32 b word | Threshold programming. Each write at `0x080 + 4*i` immediately drives one cfg transaction (`cfg_addr = {2'b01, i[3:0]}`, `cfg_wdata[6:0] = data[6:0]`). |
| `0x0C0`–`0x0FF` | reserved          |   —    |     —     | Reads return 0; writes ignored (no err). |
| `0x100`      | `XIN.LO`         | RW     | 32 b     | Input vector low 32 bits. Stored in a 32-bit shadow. |
| `0x104`      | `XIN.HI`         | RW     | 32 b     | Input vector high 32 bits. Writing this **commits** `{XIN.HI, XIN.LO}` into the tile by pulsing `x_valid` for one cycle on the next clock edge. See §4.4–4.5. |
| `0x108`      | `STATUS`         | RO     | 32 b     | bit 0 = `BUSY` (high while an inference is in flight); bit 1 = `DONE` (sticky, set when `y_valid` is captured); all other bits 0. |
| `0x10C`      | `YOUT`           | RO     | 32 b     | bits 15:0 = last captured `y_out`, bit 16 = the corresponding captured `y_valid` (sticky). Reading this register does **not** clear `DONE`. |
| `0x110`      | `CTRL`           | W1C/RW | 32 b     | bit 0 = `CLR_DONE` (write-1-to-clear the sticky `DONE` and `YOUT.bit16`); bit 1 = `SOFT_RESET` (write-1 pulses an internal reset of the wrapper's FSM and shadows for one cycle — does **not** reset the tile cfg regfile). All other bits ignored. Reads return 0. |
| `0x114`–`0x1FF` | reserved          |   —    |     —     | Reads return 0; writes ignored. |

Reads of write-only weight/threshold offsets return 0. The wrapper
does not re-derive the contents of the tile's cfg regfile, since the
tile cfg regfile is not readable. Firmware that wants to verify a
load must write a known weight, run a known input, and check the
output.

### 4.3 Weight write commit rule

A 32-bit Wishbone bus cannot deliver a 64-bit cfg write atomically.
Two-write protocol:

1. Firmware writes `W[i].LO` (offset `0x000 + 8*i`). The wrapper
   stores the 32 bits in `w_lo_shadow[i]` (a 16-deep × 32-bit
   register file inside the wrapper). The tile sees no cfg
   activity. Wishbone `ack` is asserted normally.
2. Firmware writes `W[i].HI` (offset `0x004 + 8*i`). On the next
   clock edge the wrapper drives one cfg transaction:
   - `cfg_addr = {2'b00, i[3:0]}`
   - `cfg_wdata = {W[i].HI, w_lo_shadow[i]}`
   - `cfg_we = 1` for one cycle.
   Wishbone `ack` is asserted normally; the cfg transaction completes
   in parallel with the bus handshake (the tile's cfg interface is
   write-only and accepts back-to-back cycles, so no stall is
   needed).

**Order is fixed: LO before HI.** Firmware that writes HI without
having written LO since the last HI (or since reset) gets a cfg
transaction with `w_lo_shadow[i] = 0` (or whatever stale value
sits there). This is documented but not policed in hardware —
adding a "LO-written" tracking bit is unnecessary if firmware
follows the convention.

Threshold writes are atomic (one bus write = one cfg transaction);
no shadow is needed since `cfg_wdata[6:0]` fits in one 32-bit
data word.

### 4.4 Input vector commit rule

Same idea as weights, two-write protocol. `XIN.LO` is held in a
32-bit shadow; writing `XIN.HI` commits `{XIN.HI, XIN.LO}` to the
tile by driving `x_in = {XIN.HI, XIN.LO}` and `x_valid = 1` for
exactly one cycle on the cycle that the wrapper acks the `XIN.HI`
write. (The tile latches `x_in` into `x_reg` on the rising edge
where `x_valid = 1`; one cycle is sufficient and matches the
testbench from Phase 2A.)

### 4.5 Inference handshake — polled

When `XIN.HI` is written, the wrapper:

1. Sets `STATUS.BUSY = 1`.
2. Pulses `x_valid = 1` for one cycle.
3. Waits for `y_valid = 1` from the tile (2 cycles later in the
   nominal pipeline).
4. On the cycle `y_valid = 1` is observed, captures `y_out` into
   `YOUT[15:0]`, sets `YOUT[16] = 1`, sets `STATUS.DONE = 1`, and
   clears `STATUS.BUSY`.

Firmware loop is then:

```
write XIN.LO
write XIN.HI            ; kicks off inference
do { s = read STATUS } while (s.BUSY)   ; or: while (!s.DONE)
y = read YOUT
write CTRL = 1                          ; clear DONE for the next round
```

Polling cost: one Wishbone read per poll. The inference completes
in 2 cycles after `XIN.HI` is acked; the firmware's tightest poll
loop is `lw / andi / bnez ≈ 4–5 cycles`, so the very first poll
will already see `DONE` set in nearly all cases. There is no
material throughput gain from adding an IRQ.

### 4.6 Concurrent-write edge case

If firmware writes `XIN.HI` while `STATUS.BUSY = 1` (i.e., a previous
inference is still in flight), **the wrapper ignores the write**:
the bus access is acked normally (no `err`), the shadow `XIN` is
**not** updated, and no new `x_valid` pulse is generated. This is
the safest of the three options:

- (Reject with `err`) — would force firmware to handle bus-error
  exception logic; overkill.
- (Allow and overwrite) — would corrupt the in-flight inference's
  output capture.
- **(Silently drop, chosen)** — firmware that follows the polling
  protocol in §4.5 will never trigger this; firmware that doesn't
  follow it gets visibly stuck (the new input is never processed)
  rather than silently corrupting state.

Document this rule in the firmware comments. Phase 4 stress-test
firmware can re-evaluate.

Writes to `W[i].*` and `T[i]` while `BUSY = 1` are also dropped on
the floor (cfg writes during an inference would change the weight
state mid-classification). Firmware loads weights once at startup,
so this is conservative.

### 4.7 Reset behavior

On `rst_n = 0`:
- All shadows (`w_lo_shadow[*]`, `XIN.LO`, `XIN.HI`) → 0.
- `STATUS.BUSY` → 0, `STATUS.DONE` → 0, `YOUT` → 0.
- `cfg_we` → 0, `x_valid` → 0.
- The tile's own cfg regfile resets independently via the same
  `rst_n` (so all weights/thresholds → 0).

After `SOFT_RESET` (CTRL bit 1, single-cycle internal pulse): the
wrapper's BUSY/DONE/YOUT and shadows are cleared, but the tile's
cfg regfile is **not** touched. This lets firmware abort a stuck
inference without losing the loaded weights.

---

## 5. Firmware boot and inference loop

Pseudocode only — actual C lives in Session 3D.

### 5.1 Boot

```
_reset:                        ; PROGADDR_RESET = 0x0000_0000
    li sp, 0x1000_1000         ; STACKADDR = top of DMEM
    j  main
```

No global-pointer relocation, no `.bss` clear (it's already zero
post-reset thanks to `REGS_INIT_ZERO=1` and the IMEM/DMEM models
zeroing on reset), no constructor calls.

### 5.2 main()

```
main():
    # 1. Load weights from a const table baked into IMEM
    for i in 0..15:
        write_word(TILE_BASE + 0x000 + 8*i, weights[i].lo)
        write_word(TILE_BASE + 0x004 + 8*i, weights[i].hi)
    # 2. Load thresholds (all 32 in the BNN-popcount-half convention)
    for i in 0..15:
        write_word(TILE_BASE + 0x080 + 4*i, thresholds[i])
    # 3. Inference loop over MNIST input vectors (a const table in IMEM
    #    or a buffer in DMEM, depending on dataset size — see §5.3)
    for v in input_vectors:
        write_word(TILE_BASE + 0x100, v.lo)
        write_word(TILE_BASE + 0x104, v.hi)        # kicks off inference
        while (read_word(TILE_BASE + 0x108) & 1):  # poll BUSY
            ;
        y = read_word(TILE_BASE + 0x10C) & 0xFFFF
        write_word(GPIO_BASE + 0x4, y)             # emit to GPIO
        write_word(TILE_BASE + 0x110, 1)           # CLR_DONE
    write_word(GPIO_BASE + 0x0, 0xDEADBEEF)        # done sentinel
    halt: j halt
```

### 5.3 What the firmware needs from the linker script

```
MEMORY {
    IMEM (rx) : ORIGIN = 0x00000000, LENGTH = 8K
    DMEM (rw) : ORIGIN = 0x10000000, LENGTH = 4K
}
SECTIONS {
    .text : { *(.text*) }                   > IMEM
    .rodata : { *(.rodata*) }               > IMEM   ; weights table lives here
    .data : { *(.data*) }                   > DMEM   ; AT > IMEM if non-zero init
    .bss : { *(.bss*) *(COMMON) }           > DMEM
    /* stack grows down from STACKADDR = 0x1000_1000 */
}
ENTRY(_reset)
```

**Why weights live in `.rodata` (IMEM), not `.data` (DMEM):** the
weights are deterministic constants per network and we don't want
to consume DMEM for them. IMEM has 8 KB and the weight table is
~144 B; plenty of room. The MNIST input vectors are similarly a
`const` table in `.rodata` for the integration smoke test (Session
3D); a real-world deployment would stream them in via UART/DMA
which is out of Phase-3 scope.

---

## 6. GPIO (sim observability)

`wb_gpio` is an optional but useful peripheral. Layout (within the
16 B window):

| Offset | Name      | W/R | Purpose |
| ------ | --------- | --- | ------- |
| `0x0`  | `SIM_END` | RW  | Writing any non-zero word here is a "test ended" sentinel that the testbench monitors and uses to call `$finish`. Writing `0xDEADBEEF` is the convention. |
| `0x4`  | `OUT`     | RW  | Drives `gpio_o[7:0]` from `data[7:0]`. Wider data bits are ignored. Read returns the last written value. |
| `0x8`  | `IN`      | RO  | Reads return `gpio_i[7:0]` zero-extended. |
| `0xC`  | reserved  | —   | Read 0, write ignored. |

In Session 3D's testbench, `SIM_END` writes terminate the run and
`OUT` writes are tee'd into a log so the firmware's classification
output stream is captured.

---

## 7. SoC parameters and sizing — the register-file-heavy reality

We are not using OpenRAM. IMEM and DMEM are implemented as
register-file memory (flop arrays), the same as the tile's cfg
regfile. Honest accounting:

| Storage    | Size (3A) | Size (3E baseline) | Implementation                | Approx flop count (3E) |
| ---------- | --------- | ------------------ | ----------------------------- | ---------------------: |
| IMEM       | 8 KB      | **2 KB**           | 512 × 32-bit reg              | 16,384                 |
| DMEM       | 4 KB      | **1 KB**           | 256 × 32-bit reg              |  8,192                 |
| Tile cfg   | ~144 B    | ~144 B             | 16 × 64 + 16 × 7              |  1,136                 |
| Wrapper shadow | 68 B  | 68 B               | 16 × 32 (W lo) + 64 (XIN) + ~10 (FSM) | ~590           |
| **Total**  | ~12 KB    | **~3 KB**          | mostly flops                  | **~26 K flops**        |

For comparison, the tile alone is ~22 K cells (Phase 2C numbers for
`tile_tlg_ld`). The SoC will therefore be **~5×–10× the cell count
of the tile**, dominated by IMEM/DMEM register files. **This is by
design and a known limitation of running without OpenRAM.** The
paper's area discussion must call this out: the tile-as-percent-of-
SoC will be small (~10–20%), and the SoC's headline area numbers
will not be directly comparable to OpenRAM-backed BNN
accelerators.

The power picture is more nuanced: the IMEM is RX only after boot,
so it's read on every instruction fetch (high switching). DMEM is
mostly idle during the polling loop. Tile is the only real
combinational power consumer. We expect the SoC's activity-aware
power to be IMEM-fetch-dominated (clock tree of the IMEM regfile +
read-port switching) rather than tile-dominated, which **inverts
the Phase-2C claim** at the system level. Phase 4 will quantify
this. The architectural decision here is to accept this as the
honest cost of a no-OpenRAM SoC and to report it transparently.

### 7.1 Why 2 KB / 1 KB in the Session 3E baseline

The original 3A spec called for 8 KB IMEM / 4 KB DMEM, with the
rationale that 8 KB IMEM gives 8× headroom over a ~1 KB inference
loop and 4 KB DMEM is generous stack + scratch. The Phase-3D
firmware ended up at 1 556 B (text + rodata: see PHASE3D_NOTES §4.1).

Session 3E's first SoC P&R run revealed the structural cost of an
8 KB regfile-IMEM: Yosys synthesizes the 2048 × 32-bit read mux as
a single net with **15 115 terminals**, which the open-flow resizer
cannot break up (`RSZ-0062: Unable to repair all setup violations`).
The headline `nom_tt_025C_1v80` corner closed (+1.74 ns slack), but
the slow + fast corners diverged catastrophically (WNS −3 359 ns at
`nom_ss`, −5 000 ns at `nom_ff`). This is a register-file-baseline
artifact, not a tile or interconnect issue.

The shrink:

- IMEM 8 KB → **2 KB / 512 words.** Read-mux fanout drops ~4×;
  firmware fits with ~30 % headroom (1 556 / 2 048 B).
- DMEM 4 KB → **1 KB / 256 words.** Symmetric reduction; the 32-word
  test-image preload + small stack still fit comfortably.

The shrink is framed as **intentional engineering for the
register-file baseline** ("memory sized to balance functional
headroom against open-flow timing limits"), not accidental
limitation. A separate Session 3.5 will integrate OpenRAM SRAM
macros for IMEM + DMEM, which removes the read-mux fanout problem
and lets the depths grow back to the 3A spec — that becomes the
final headline number for the paper. **The 3E baseline is the
register-file data point against which 3.5 is compared.**

If a later session needs different depths, the sizes are
parameterised at the top of `soc_top.v` so changing them is a
one-line edit.

---

## 8. Module hierarchy and skeleton commitments

### 8.1 Files (all under `rtl/soc/`)

| File                     | Top module             | What it does                                                        |
| ------------------------ | ---------------------- | ------------------------------------------------------------------- |
| `soc_top.v`              | `soc_top`              | Top level. Reset sync, instantiates everything, wires it.           |
| `picorv32_wrapper.v`     | `picorv32_wrapper`     | Wraps `picorv32_wb` (in 3C). Skeleton: ports only, no body.         |
| `wb_interconnect.v`      | `wb_interconnect`      | 1-master, 4-slave, comb. address decoder. Skeleton: ports + decode placeholder. |
| `wb_imem.v`              | `wb_imem`              | 8 KB read-only memory. Skeleton: ports only, returns 0.             |
| `wb_dmem.v`              | `wb_dmem`              | 4 KB RW memory. Skeleton: ports only, returns 0.                    |
| `wb_tile_wrapper.v`      | `wb_tile_wrapper`      | The big one (§4). Skeleton: instantiates `tile_tlg_ld` with clk/rst_n + tied-off cfg/x_in/x_valid; WB port surface is correct but no logic. |
| `wb_gpio.v`              | `wb_gpio`              | 16 B GPIO + sim sentinel. Skeleton: ports only.                     |

### 8.2 What "skeleton" means in 3A

Each module:

- Has the **final** port list (signal names + widths) that 3B/3C/3D
  will implement against. Renaming a port post-skeleton is a churn
  cost we want to pay zero of.
- Has a header comment summarising what it does and what session
  fills in the body.
- Has stubs that elaborate cleanly: `wire`/`reg` declarations as
  needed to silence "implicit net" complaints; output drivers tied
  to constants (or to the inputs in trivial pass-through cases).
- Contains `// TODO(3B/3C/3D)` markers where real logic will go.

`wb_tile_wrapper.v` additionally instantiates `tile_tlg_ld` and
hooks up `clk`, `rst_n`, plus tied-off `cfg_we = 0`, `cfg_addr = 0`,
`cfg_wdata = 0`, `x_in = 0`, `x_valid = 0`. Its `y_out`/`y_valid`
outputs are wired but unused at the wrapper's WB-side outputs (which
return 0). This proves the tile's port list lines up with the
wrapper's expectation.

### 8.3 Elaboration check

`scripts/check_soc_elab.sh` runs:

```
iverilog -g2012 -Wall \
    -I rtl/soc -I rtl/tile_tlg_ld \
    rtl/soc/soc_top.v \
    rtl/soc/picorv32_wrapper.v \
    rtl/soc/wb_interconnect.v \
    rtl/soc/wb_imem.v \
    rtl/soc/wb_dmem.v \
    rtl/soc/wb_tile_wrapper.v \
    rtl/soc/wb_gpio.v \
    rtl/tile_tlg_ld/tile_tlg_ld.v \
    -o /tmp/soc_elab_check
```

PASS criterion: zero errors. Warnings about unused signals are
expected (most stub bodies don't read their inputs) and are
allow-listed.

---

## 9. Reset and clock distribution

- **One clock**, named `clk`, reaching every block. No PLLs, no
  divided clocks, no gated clocks. Nominal target: 100 MHz (matches
  the Phase-2 SDC).
- **Reset polarity: active-low (`rst_n`).** The chip pin
  `rst_n_i` is sampled by a 2-FF reset synchronizer
  (`reset_sync.v`, instantiated inside `soc_top`) producing
  internal `rst_n` that is **asynchronously asserted** (so a glitch-
  free async reset wakes the synchronizer's flops on time) and
  **synchronously deasserted** (so all downstream flops come out of
  reset on the same edge). The synchronizer guarantees ≥2 cycles of
  `rst_n = 0` after `rst_n_i` releases.
- All sequential logic uses `always @(posedge clk)` with a
  synchronous `if (!rst_n)` reset clause. The tile already does
  this (Phase 2A); the SoC follows the same convention for STA
  consistency with the existing tile SDC.

---

## 10. Deliberately deferred / underspecified — pointers for 3B/3C/3D

| Topic | Decision deferred to | Notes |
| --- | --- | --- |
| Exact IMEM/DMEM `$readmemh` mechanism for sim and for LibreLane | 3D / 3E | sim uses `$readmemh("firmware.hex")`; for LibreLane, the IMEM is a regfile pre-loaded by an init block (one of: vendor-specific BRAM init, `initial` with `$readmemh`, or a separate ROM module generated by a Python script). 3E picks. |
| Whether `wb_imem` is implemented as plain `reg [31:0] mem [0:2047]` or as a more synthesis-friendly form | 3B | Safe default: plain reg array with `$readmemh` initialization. |
| Whether `wb_tile_wrapper` exposes a debug "force cfg-write" backdoor for testbench setup | 3B | Probably yes, but only inside `ifdef SIM`. |
| Concrete `picorv32_wb` parameter overrides if any (vs the §3.4 table) | 3C | Table is the spec; 3C verifies upstream wrapper supports them all. |
| MNIST data path: pre-baked `.rodata` table vs runtime UART feed | 3D | Defaulting to `.rodata` for the smoke test; UART is out of Phase-3 scope. |
| Whether to add a cycle counter peripheral for benchmarking | 3D / 3E | If we want measured cycles-per-inference numbers in the paper, a 32-bit free-running counter at GPIO+0x10 is ~20 lines. Decide in 3D after seeing the firmware. |
| Power-aware optimizations of IMEM (e.g., gating reads when PC isn't fetching) | 4 | Phase 4 work; the 3A skeleton is correctness-first. |
| LibreLane SDC for the SoC | 3E | Reuse the Phase-2 tile SDC as a starting point; the SoC's clock tree is bigger so retiming/timing-driven place will be slower. |

---

## 11. Reproduction

The architecture is markdown only; nothing to run in Session 3A
beyond elaboration:

```bash
source scripts/env.sh
scripts/check_soc_elab.sh        # exits 0 if the skeleton elaborates
```

Sessions 3B onward will add their own reproduction notes to
`docs/PHASE3<X>_NOTES.md`.
