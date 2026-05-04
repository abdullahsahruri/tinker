/* =============================================================================
 * linker.ld — bare-metal linker script for the Phase-3D BNN inference firmware.
 *
 * Memory map per PHASE3_ARCHITECTURE.md §2 (forked verbatim from
 * firmware/smoke/linker.ld; same memory map, larger .rodata budget for the
 * BNN weight tables in weights.h).
 *
 *   IMEM at 0x0000_0000, 8 KB, RX  — code + weight/threshold tables (.rodata)
 *   DMEM at 0x1000_0000, 4 KB, RW  — stack + 16 packed test images preloaded
 *                                   by the testbench at offsets 0..127.
 *   Stack top at 0x1000_1000 (set by start.S, not by the linker).
 * ============================================================================= */
ENTRY(_reset)

MEMORY {
    IMEM (rx) : ORIGIN = 0x00000000, LENGTH = 8K
    DMEM (rw) : ORIGIN = 0x10000000, LENGTH = 4K
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
