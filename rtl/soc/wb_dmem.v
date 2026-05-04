// =============================================================================
// wb_dmem.v — 4 KB Wishbone B4 classic data memory (RW).
//              (Phase 3A skeleton).
//
// Backed by a register-file array. Supports byte/halfword/word writes via
// wb_sel_i; reads always return the full 32-bit word. Initialised to 0 on
// reset (no `$readmemh` for DMEM by default).
//
// SKELETON: ack=0, err=0, data=0. Session 3B implements the real model.
// Port list is FINAL.
// =============================================================================
`default_nettype none

module wb_dmem #(
    parameter integer SIZE_BYTES = 4096
) (
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

    // TODO(3B): declare `reg [31:0] mem [0:(SIZE_BYTES/4)-1];`,
    // implement byte-strobe writes and single-cycle ack.
    assign wb_dat_o = 32'b0;
    assign wb_ack_o = 1'b0;
    assign wb_err_o = 1'b0;

    wire _unused_ok = &{1'b0, clk, rst_n, wb_cyc_i, wb_stb_i, wb_we_i,
                        wb_sel_i, wb_adr_i, wb_dat_i, 1'b0};

    initial begin
        if (SIZE_BYTES == 0) begin
            // keeps parameter referenced
        end
    end

endmodule

`default_nettype wire
