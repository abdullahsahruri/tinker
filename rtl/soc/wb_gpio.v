// =============================================================================
// wb_gpio.v — small GPIO peripheral for sim observability
//              (Phase 3A skeleton).
//
// Layout (16 B window, 32-bit accesses):
//   0x0 SIM_END  RW   firmware writes 0xDEADBEEF to terminate the bench
//   0x4 OUT      RW   drives gpio_o[7:0] from data[7:0]
//   0x8 IN       RO   reads gpio_i[7:0] zero-extended
//   0xC reserved
//
// SKELETON: gpio_o tied to 0, ack/err/dat tied to 0. Session 3B / 3D
// implement the real peripheral. Port list is FINAL.
// =============================================================================
`default_nettype none

module wb_gpio (
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
    output wire        wb_err_o,

    input  wire [7:0]  gpio_i,
    output wire [7:0]  gpio_o
);

    // TODO(3B/3D): real registers + WB decode + SIM_END sentinel that the
    // testbench monitors via a `force` or a hierarchical reference.
    assign wb_dat_o = 32'b0;
    assign wb_ack_o = 1'b0;
    assign wb_err_o = 1'b0;
    assign gpio_o   = 8'b0;

    wire _unused_ok = &{1'b0, clk, rst_n, wb_cyc_i, wb_stb_i, wb_we_i,
                        wb_sel_i, wb_adr_i, wb_dat_i, gpio_i, 1'b0};

endmodule

`default_nettype wire
