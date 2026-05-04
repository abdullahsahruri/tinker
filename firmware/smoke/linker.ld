/* =============================================================================
 * linker.ld — bare-metal linker script for the Phase-3C SoC smoke test.
 *
 * Memory map per PHASE3_ARCHITECTURE.md §2:
 *   IMEM at 0x0000_0000, 2 KB, RX
 *   DMEM at 0x1000_0000, 1 KB, RW
 *   Stack top at 0x1000_0400 (set by start.S, not by the linker).
 *
 * `.text.startup` comes first in IMEM so that _reset lives at byte 0 (the
 * PicoRV32 PROGADDR_RESET). `.rodata` follows. Smoke firmware has no
 * non-zero `.data`, so no LMA copying is needed; if a future firmware
 * needs it the AT > IMEM relocation can be added.
 *
 * Sizes shrunk in Session 3E (2026-05-04) — see firmware/inference/linker.ld
 * for rationale.
 * ============================================================================= */
ENTRY(_reset)

MEMORY {
    IMEM (rx) : ORIGIN = 0x00000000, LENGTH = 2K
    DMEM (rw) : ORIGIN = 0x10000000, LENGTH = 1K
}

SECTIONS {
    .text : {
        KEEP(*(.text.startup))
        *(.text)
        *(.text.*)
    } > IMEM

    .rodata : {
        *(.rodata)
        *(.rodata.*)
        *(.srodata)
        *(.srodata.*)
    } > IMEM

    .data : {
        *(.data)
        *(.data.*)
        *(.sdata)
        *(.sdata.*)
    } > DMEM

    .bss : {
        *(.bss)
        *(.bss.*)
        *(.sbss)
        *(.sbss.*)
        *(COMMON)
    } > DMEM

    /DISCARD/ : { *(.note*) *(.comment) *(.eh_frame) *(.debug_*) }
}
