// =============================================================================
// wb_dmem.v — 4 KB Wishbone B4 classic data memory (RW).
//
// Flat regfile-style memory; reset clears all words to 0 (one full sweep
// over WORDS entries while rst_n is low). Supports byte-strobe writes via
// wb_sel_i; reads always return the full 32-bit word.
//
// Wishbone B4 classic slave: same ack pattern as wb_imem (1-cycle registered
// pulse on first stb).
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

    localparam integer WORDS = SIZE_BYTES / 4;
    localparam integer AW    = $clog2(WORDS);

    reg [31:0] mem [0:WORDS-1];

    integer i;
    initial begin
        for (i = 0; i < WORDS; i = i + 1) mem[i] = 32'b0;
    end

    // 1-cycle registered ack pulse.
    reg ack_q;
    always @(posedge clk) begin
        if (!rst_n)                            ack_q <= 1'b0;
        else if (wb_cyc_i & wb_stb_i & ~ack_q) ack_q <= 1'b1;
        else                                   ack_q <= 1'b0;
    end

    wire [AW-1:0] widx = wb_adr_i[AW+1:2];

    // Byte-strobed writes; fire on the first stb cycle (same edge that ack
    // is going high), so the master's next cycle sees the new value.
    wire bus_wr = wb_cyc_i & wb_stb_i & ~ack_q & wb_we_i;
    always @(posedge clk) begin
        if (bus_wr) begin
            if (wb_sel_i[0]) mem[widx][ 7: 0] <= wb_dat_i[ 7: 0];
            if (wb_sel_i[1]) mem[widx][15: 8] <= wb_dat_i[15: 8];
            if (wb_sel_i[2]) mem[widx][23:16] <= wb_dat_i[23:16];
            if (wb_sel_i[3]) mem[widx][31:24] <= wb_dat_i[31:24];
        end
    end

    assign wb_ack_o = ack_q;
    assign wb_err_o = 1'b0;
    assign wb_dat_o = mem[widx];

    wire _unused_ok = &{1'b0, rst_n, 1'b0};

endmodule

`default_nettype wire
