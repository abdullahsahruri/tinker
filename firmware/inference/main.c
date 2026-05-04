/* =============================================================================
 * main.c — Phase-3D BNN inference firmware.
 *
 * Network (49 → 64 → 10) is deployed by:
 *   - HIDDEN_BATCHES (=4) sequential tile evaluations for layer 1 (16 hidden
 *     neurons per evaluation), each loading the corresponding 16 weights and
 *     16 thresholds and running one inference per image.
 *   - software popcount + argmax for layer 2 (the tile only emits a binary
 *     above/below-threshold output, but argmax across 10 classes needs the
 *     pre-threshold sums).
 *
 * Per image:
 *   read 64-bit packed input from DMEM at 0x10000000 + 8*image_idx
 *   accumulate 64 hidden bits over 4 tile evaluations
 *   compute logit_c = 2*popcount(hidden XNOR L2W[c]) - 64 + L2_BIAS[c]
 *   predicted_class = argmax_c(logit)
 *   GPIO_OUT     = predicted_class & 0xFF      (drives gpio_o[7:0])
 *   GPIO_SIM_END = 0xC0FE0000 | predicted_class (per-image sentinel)
 *
 * After all images:
 *   GPIO_SIM_END = 0xCAFEBABE
 *   spin
 *
 * The testbench preloads the 16 packed images into DMEM hierarchically before
 * deasserting reset, snoops the WB master bus for the per-image GPIO writes,
 * and compares the predicted-class stream to the precomputed Python golden.
 *
 * NOTE: writes to the tile during BUSY are silently dropped per
 * PHASE3B_NOTES §2.4 — the firmware therefore polls STATUS.BUSY before
 * starting the next tile programming or inference.
 * ============================================================================= */

typedef unsigned int    uint32_t;
typedef int             int32_t;
typedef unsigned short  uint16_t;
typedef short           int16_t;
typedef unsigned char   uint8_t;

/* ---------------------------------------------------------------------------
 * Memory map.
 * ------------------------------------------------------------------------- */
#define DMEM_BASE       0x10000000u
#define TILE_BASE       0x20000000u
#define GPIO_BASE       0x30000000u

#define TILE_W_LO(i)    (TILE_BASE + 0x000u + 8u * (i))
#define TILE_W_HI(i)    (TILE_BASE + 0x004u + 8u * (i))
#define TILE_T(i)       (TILE_BASE + 0x080u + 4u * (i))
#define TILE_XIN_LO     (TILE_BASE + 0x100u)
#define TILE_XIN_HI     (TILE_BASE + 0x104u)
#define TILE_STATUS     (TILE_BASE + 0x108u)
#define TILE_YOUT       (TILE_BASE + 0x10Cu)
#define TILE_CTRL       (TILE_BASE + 0x110u)

#define GPIO_SIM_END    (GPIO_BASE + 0x0u)
#define GPIO_OUT        (GPIO_BASE + 0x4u)

#define MMIO(addr)      (*(volatile uint32_t *)(addr))

#define N_IMAGES        16
#define N_HIDDEN        64

#include "weights.h"        /* HIDDEN_BATCHES, N_OUTPUT, L1_W_*, L1_T,
                             * L2_W_*, L2_BIAS */

/* ---------------------------------------------------------------------------
 * MMIO helpers.
 * ------------------------------------------------------------------------- */
static inline uint32_t mmio_rd(uint32_t addr) { return MMIO(addr); }
static inline void     mmio_wr(uint32_t addr, uint32_t data) { MMIO(addr) = data; }

/* ---------------------------------------------------------------------------
 * Tile programming + inference.
 * ------------------------------------------------------------------------- */
static void program_hidden_batch(uint32_t k) {
    /* 16 weights LO+HI then 16 thresholds. Order LO before HI per spec §4.3
     * (writes during BUSY are silently dropped — caller must ensure BUSY=0). */
    uint32_t i;
    for (i = 0; i < 16u; i++) {
        mmio_wr(TILE_W_LO(i), L1_W_LO[k][i]);
        mmio_wr(TILE_W_HI(i), L1_W_HI[k][i]);
    }
    for (i = 0; i < 16u; i++) {
        mmio_wr(TILE_T(i), (uint32_t)L1_T[k][i]);
    }
}

static uint32_t run_inference(uint32_t xlo, uint32_t xhi) {
    /* Kick: write XIN.LO (shadow), then XIN.HI (commits + pulses x_valid).
     * Poll STATUS.BUSY (bit 0); the tile clears it 2 cycles after x_valid
     * — the first poll loop iteration typically already sees BUSY=0. */
    mmio_wr(TILE_XIN_LO, xlo);
    mmio_wr(TILE_XIN_HI, xhi);
    while (mmio_rd(TILE_STATUS) & 1u) { /* spin */ }
    return mmio_rd(TILE_YOUT) & 0xFFFFu;
}

/* ---------------------------------------------------------------------------
 * popcount — RV32I has no PCNT instruction; use an 8-bit lookup table.
 * Living in .rodata costs 256 bytes of IMEM; computing per-byte saves the
 * dependency chain on the tight inner loop.
 * ------------------------------------------------------------------------- */
static const uint8_t POPCOUNT8[256] = {
#define B2(n) n,     n + 1, n + 1, n + 2
#define B4(n) B2(n), B2(n + 1), B2(n + 1), B2(n + 2)
#define B6(n) B4(n), B4(n + 1), B4(n + 1), B4(n + 2)
    B6(0), B6(1), B6(1), B6(2)
#undef B2
#undef B4
#undef B6
};

static uint32_t popcount32(uint32_t x) {
    return (uint32_t)POPCOUNT8[(x      ) & 0xFFu]
         + (uint32_t)POPCOUNT8[(x >>  8) & 0xFFu]
         + (uint32_t)POPCOUNT8[(x >> 16) & 0xFFu]
         + (uint32_t)POPCOUNT8[(x >> 24) & 0xFFu];
}

/* ---------------------------------------------------------------------------
 * Image accessor — DMEM holds 16 packed inputs as (lo, hi) word pairs at
 * offsets 0, 4, 8, 12, ... (i.e. word indices 0..31). Each image occupies
 * two 32-bit words: word 2i = bits [31:0] of the 49-b packed input,
 * word 2i+1 = bits [63:32] (with bits [63:49] = 0 by gen_bnn_testdata
 * convention).
 * ------------------------------------------------------------------------- */
static const volatile uint32_t * const IMAGES_PTR =
    (const volatile uint32_t *)DMEM_BASE;

void main(void) {
    uint32_t img;

    for (img = 0; img < N_IMAGES; img++) {
        uint32_t xlo = IMAGES_PTR[2u * img + 0u];
        uint32_t xhi = IMAGES_PTR[2u * img + 1u];

        uint32_t hidden_lo = 0u;
        uint32_t hidden_hi = 0u;
        uint32_t k;
        for (k = 0u; k < HIDDEN_BATCHES; k++) {
            program_hidden_batch(k);
            uint32_t y = run_inference(xlo, xhi);
            /* y is 16 bits; place at hidden bits [k*16 .. k*16+15].
             *   k=0 → hidden_lo[15:0]
             *   k=1 → hidden_lo[31:16]
             *   k=2 → hidden_hi[15:0]
             *   k=3 → hidden_hi[31:16]
             */
            if (k < 2u) hidden_lo |= y << (16u * k);
            else        hidden_hi |= y << (16u * (k - 2u));
        }

        /* Output layer in software: argmax over N_OUTPUT logits. */
        int32_t  best_logit = -1000000;
        uint32_t best_class = 0u;
        uint32_t c;
        for (c = 0u; c < N_OUTPUT; c++) {
            uint32_t xn_lo = ~(hidden_lo ^ L2_W_LO[c]);
            uint32_t xn_hi = ~(hidden_hi ^ L2_W_HI[c]);
            uint32_t p = popcount32(xn_lo) + popcount32(xn_hi);
            int32_t logit = (int32_t)(2u * p) - (int32_t)N_HIDDEN
                          + (int32_t)L2_BIAS[c];
            if (logit > best_logit) {
                best_logit = logit;
                best_class = c;
            }
        }

        /* Emit prediction: GPIO_OUT for the byte stream, then SIM_END as
         * the per-image sentinel so the TB can sync per image. */
        mmio_wr(GPIO_OUT,     best_class & 0xFFu);
        mmio_wr(GPIO_SIM_END, 0xC0FE0000u | (best_class & 0xFu));
    }

    /* Final completion sentinel — TB stops watching after this. */
    mmio_wr(GPIO_SIM_END, 0xCAFEBABEu);
    for (;;) { }
}
