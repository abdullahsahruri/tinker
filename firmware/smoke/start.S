# =============================================================================
# start.S — minimal RV32I startup for the Phase-3C SoC smoke test.
#
# Lives at the IMEM reset vector (0x0000_0000). Sets the stack pointer per
# PHASE3_ARCHITECTURE.md (top of DMEM = 0x1000_1000), zeroes a few caller-
# saved regs for determinism, calls main(), and hangs in a tight loop on
# return. No CRT0, no .bss zeroing (DMEM is RW and reset by wb_dmem to 0;
# REGS_INIT_ZERO=1 in PicoRV32 zeros the regfile).
# =============================================================================
    .section .text.startup, "ax"
    .globl   _reset
    .globl   _start
_start:
_reset:
    # Stack top per spec — DMEM end. Stack grows down.
    li      sp, 0x10000400
    li      gp, 0
    li      ra, 0
    call    main
.hang:
    j       .hang
