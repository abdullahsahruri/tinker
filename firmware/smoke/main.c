// =============================================================================
// main.c — Phase-3C SoC smoke test firmware.
//
// Writes a known low byte to GPIO_OUT (drives the gpio_o[7:0] pin), then
// writes the 0xCAFE_BABE sentinel to GPIO_SIM_END. The testbench watches
// gpio_o for the OUT byte and the GPIO sim_end register for the sentinel;
// observing both proves that:
//
//   - PicoRV32 fetched at least one instruction from IMEM,
//   - the instruction stream reached main() (i.e., the linker placed code
//     correctly and the reset vector is wired),
//   - the WB master/interconnect/GPIO slave path is functional end-to-end,
//   - byte-strobed writes are honored (OUT is byte 0 of a 32-b register).
//
// The tile is *not* exercised in this session — that is Session 3D.
// =============================================================================

#define GPIO_BASE       0x30000000u
#define GPIO_SIM_END    (*(volatile unsigned int *)(GPIO_BASE + 0x0))
#define GPIO_OUT        (*(volatile unsigned int *)(GPIO_BASE + 0x4))

#define SENTINEL        0xCAFEBABEu
#define OUT_BYTE        0x000000BEu

void main(void) {
    GPIO_OUT     = OUT_BYTE;
    GPIO_SIM_END = SENTINEL;
    for (;;) {
    }
}
