// =============================================================================
// wb_gpio.v — small GPIO peripheral for sim observability.
//
// Layout (16 B window, 32-bit accesses; in-window byte offset = wb_adr_i[3:2]):
//   0x0 SIM_END  RW   firmware writes 0xDEADBEEF to terminate the bench
//   0x4 OUT      RW   drives gpio_o[7:0] from data[7:0]
//   0x8 IN       RO   reads gpio_i[7:0] zero-extended
//   0xC reserved      reads return 0, writes ignored
//
// Wishbone B4 classic slave: 1-cycle registered ack on the first stb cycle.
// Writes commit on the same edge that ack pulses, so the next read returns
// the new value. Sub-word writes honor wb_sel_i.
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

    // 1-cycle registered ack pulse.
    reg ack_q;
    always @(posedge clk) begin
        if (!rst_n)                            ack_q <= 1'b0;
        else if (wb_cyc_i & wb_stb_i & ~ack_q) ack_q <= 1'b1;
        else                                   ack_q <= 1'b0;
    end

    wire [1:0] off = wb_adr_i[3:2];     // 0..3 selects SIM_END/OUT/IN/reserved
    wire bus_wr    = wb_cyc_i & wb_stb_i & ~ack_q & wb_we_i;

    reg [31:0] sim_end_q;
    reg [31:0] out_q;

    // Combinational byte-merged write data — applies wb_sel_i to the current
    // shadow so sub-word stores merge cleanly.
    function automatic [31:0] merge_wr(input [31:0] cur);
        merge_wr = {
            wb_sel_i[3] ? wb_dat_i[31:24] : cur[31:24],
            wb_sel_i[2] ? wb_dat_i[23:16] : cur[23:16],
            wb_sel_i[1] ? wb_dat_i[15: 8] : cur[15: 8],
            wb_sel_i[0] ? wb_dat_i[ 7: 0] : cur[ 7: 0]
        };
    endfunction

    always @(posedge clk) begin
        if (!rst_n) begin
            sim_end_q <= 32'b0;
            out_q     <= 32'b0;
        end else if (bus_wr) begin
            case (off)
                2'd0: sim_end_q <= merge_wr(sim_end_q);
                2'd1: out_q     <= merge_wr(out_q);
                default: ;     // 0x8 (IN, RO) and 0xC (reserved) ignore writes
            endcase
        end
    end

    reg [31:0] rd_data;
    always @* begin
        case (off)
            2'd0:    rd_data = sim_end_q;
            2'd1:    rd_data = out_q;
            2'd2:    rd_data = {24'b0, gpio_i};
            default: rd_data = 32'b0;
        endcase
    end

    assign wb_dat_o = rd_data;
    assign wb_ack_o = ack_q;
    assign wb_err_o = 1'b0;
    assign gpio_o   = out_q[7:0];

endmodule

`default_nettype wire
