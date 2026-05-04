# =============================================================================
# start.S — minimal RV32I startup for the Phase-3D BNN inference firmware.
#
# Identical to firmware/smoke/start.S — sets the stack pointer to the top of
# DMEM (per PHASE3_ARCHITECTURE.md §5.1) and jumps to main(). DMEM is reset
# to 0 by wb_dmem's `initial` block; the testbench then preloads the 16
# packed test images at offsets 0..127 BEFORE rst_n is released.
# =============================================================================
    .section .text.startup, "ax"
    .globl   _reset
    .globl   _start
_start:
_reset:
    li      sp, 0x10000400
    li      gp, 0
    li      ra, 0
    call    main
.hang:
    j       .hang
