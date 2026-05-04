// =============================================================================
// wb_tile_wrapper.v — Wishbone B4 slave wrapping the Phase-2C tile_tlg_ld
//                      (Phase 3A skeleton — bus-side logic stubbed; tile
//                       instantiation is REAL so port-list mismatches with
//                       rtl/tile_tlg_ld/ are caught at elaboration time).
//
// Spec: see PHASE3_ARCHITECTURE.md §4. Summary of the register layout
// (byte offsets within the 512 B slave window, all 32-bit accesses):
//   0x000..0x07F : W[i].LO / W[i].HI (8 B per neuron, i = 0..15)
//                   write to .HI commits {.HI, .LO} to tile cfg via one
//                   cfg_we pulse with cfg_addr = {2'b00, i[3:0]}
//   0x080..0x0BF : T[i] (4 B per neuron, low 7 bits used)
//                   write commits to tile cfg via one cfg_we pulse with
//                   cfg_addr = {2'b01, i[3:0]}
//   0x100        : XIN.LO (32-bit shadow)
//   0x104        : XIN.HI -- writing this commits {XIN.HI, XIN.LO} into
//                  the tile by pulsing x_valid for one cycle
//   0x108        : STATUS [RO] {30'b0, DONE, BUSY}
//   0x10C        : YOUT   [RO] {15'b0, y_valid_sticky, y_out[15:0]}
//   0x110        : CTRL   [W1C/RW] bit0=CLR_DONE, bit1=SOFT_RESET
//
// SKELETON: bus-side ack/err/dat tied to 0; tile cfg + x_in + x_valid tied
// to 0; tile y_out / y_valid wired to internal nets but not consumed by the
// stub bus side. Session 3B implements the real register-bank + FSM. Port
// list is FINAL on the WB side.
// =============================================================================
`default_nettype none

module wb_tile_wrapper (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        wb_cyc_i,
    input  wire        wb_stb_i,
    input  wire        wb_we_i,
    input  wire [3:0]  wb_sel_i,
    input  wire [31:0] wb_adr_i,
    input  wire [31:0] wb_dat_i,
    output wire [31:0] wb_dat_o,
    output wire        wb_ack_o,
    output wire        wb_err_o
);

    // -------------------------------------------------------------------------
    // Tile-facing signals. These mirror tile_tlg_ld's port list exactly.
    // 3B drives them from the register-bank FSM; 3A ties them to safe
    // defaults (no cfg activity, no inference triggered).
    // -------------------------------------------------------------------------
    wire        tile_x_valid;
    wire [63:0] tile_x_in;
    wire        tile_cfg_we;
    wire [5:0]  tile_cfg_addr;
    wire [63:0] tile_cfg_wdata;
    wire [15:0] tile_y_out;
    wire        tile_y_valid;

    // TODO(3B): drive these from the register-bank decode + commit FSM.
    assign tile_x_valid   = 1'b0;
    assign tile_x_in      = 64'b0;
    assign tile_cfg_we    = 1'b0;
    assign tile_cfg_addr  = 6'b0;
    assign tile_cfg_wdata = 64'b0;

    tile_tlg_ld u_tile (
        .clk        (clk),
        .rst_n      (rst_n),
        .x_in       (tile_x_in),
        .x_valid    (tile_x_valid),
        .y_out      (tile_y_out),
        .y_valid    (tile_y_valid),
        .cfg_we     (tile_cfg_we),
        .cfg_addr   (tile_cfg_addr),
        .cfg_wdata  (tile_cfg_wdata)
    );

    // -------------------------------------------------------------------------
    // WB slave side. Stubbed.
    // -------------------------------------------------------------------------
    // TODO(3B): implement the register-bank decode + commit FSM described
    // in PHASE3_ARCHITECTURE.md §4. The FSM owns:
    //   - 16 × 32 w_lo_shadow regs (one per neuron's low half)
    //   - 32-bit XIN.LO shadow
    //   - BUSY / DONE flags + sticky YOUT capture on y_valid
    //   - WB ack: single-cycle, 0 wait states
    //   - SOFT_RESET / CLR_DONE write-1 strobes
    assign wb_dat_o = 32'b0;
    assign wb_ack_o = 1'b0;
    assign wb_err_o = 1'b0;

    wire _unused_ok = &{1'b0, wb_cyc_i, wb_stb_i, wb_we_i, wb_sel_i,
                        wb_adr_i, wb_dat_i, tile_y_out, tile_y_valid, 1'b0};

endmodule

`default_nettype wire
