// =============================================================================
// wb_interconnect.v — single-master, four-slave Wishbone B4 classic crossbar
//                      (Phase 3A skeleton).
//
// Address decode: m_adr_i[31:28] selects one of four slaves
//   0x0 -> s0 (IMEM)
//   0x1 -> s1 (DMEM)
//   0x2 -> s2 (TILE)
//   0x3 -> s3 (GPIO)
//   else -> decode-miss (interconnect drives m_err_o = 1, no slave selected)
//
// SKELETON behaviour: no real decode is implemented. All slaves see
// cyc/stb = 0 and the master sees ack = 0, err = 0, dat = 0. Session 3B
// implements the real decoder + read-data mux. Port lists are FINAL.
// =============================================================================
`default_nettype none

module wb_interconnect (
    input  wire        clk,
    input  wire        rst_n,

    // Master-side (signals from PicoRV32's WB master).
    input  wire        m_cyc_i,
    input  wire        m_stb_i,
    input  wire        m_we_i,
    input  wire [3:0]  m_sel_i,
    input  wire [31:0] m_adr_i,
    input  wire [31:0] m_dat_i,    // master -> slave
    output wire [31:0] m_dat_o,    // slave  -> master
    output wire        m_ack_o,
    output wire        m_err_o,

    // Slave 0 — IMEM.
    output wire        s0_cyc_o, output wire s0_stb_o, output wire s0_we_o,
    output wire [3:0]  s0_sel_o, output wire [31:0] s0_adr_o,
    output wire [31:0] s0_dat_o,
    input  wire [31:0] s0_dat_i, input wire s0_ack_i, input wire s0_err_i,

    // Slave 1 — DMEM.
    output wire        s1_cyc_o, output wire s1_stb_o, output wire s1_we_o,
    output wire [3:0]  s1_sel_o, output wire [31:0] s1_adr_o,
    output wire [31:0] s1_dat_o,
    input  wire [31:0] s1_dat_i, input wire s1_ack_i, input wire s1_err_i,

    // Slave 2 — TILE.
    output wire        s2_cyc_o, output wire s2_stb_o, output wire s2_we_o,
    output wire [3:0]  s2_sel_o, output wire [31:0] s2_adr_o,
    output wire [31:0] s2_dat_o,
    input  wire [31:0] s2_dat_i, input wire s2_ack_i, input wire s2_err_i,

    // Slave 3 — GPIO.
    output wire        s3_cyc_o, output wire s3_stb_o, output wire s3_we_o,
    output wire [3:0]  s3_sel_o, output wire [31:0] s3_adr_o,
    output wire [31:0] s3_dat_o,
    input  wire [31:0] s3_dat_i, input wire s3_ack_i, input wire s3_err_i
);

    // TODO(3B): real address decode. For now, drive everything to idle.
    assign s0_cyc_o = 1'b0; assign s0_stb_o = 1'b0; assign s0_we_o = 1'b0;
    assign s0_sel_o = 4'b0; assign s0_adr_o = 32'b0; assign s0_dat_o = 32'b0;
    assign s1_cyc_o = 1'b0; assign s1_stb_o = 1'b0; assign s1_we_o = 1'b0;
    assign s1_sel_o = 4'b0; assign s1_adr_o = 32'b0; assign s1_dat_o = 32'b0;
    assign s2_cyc_o = 1'b0; assign s2_stb_o = 1'b0; assign s2_we_o = 1'b0;
    assign s2_sel_o = 4'b0; assign s2_adr_o = 32'b0; assign s2_dat_o = 32'b0;
    assign s3_cyc_o = 1'b0; assign s3_stb_o = 1'b0; assign s3_we_o = 1'b0;
    assign s3_sel_o = 4'b0; assign s3_adr_o = 32'b0; assign s3_dat_o = 32'b0;

    assign m_dat_o  = 32'b0;
    assign m_ack_o  = 1'b0;
    assign m_err_o  = 1'b0;

    // Tap unused signals to keep lint quiet.
    wire _unused_ok = &{1'b0, clk, rst_n, m_cyc_i, m_stb_i, m_we_i,
                        m_sel_i, m_adr_i, m_dat_i,
                        s0_dat_i, s0_ack_i, s0_err_i,
                        s1_dat_i, s1_ack_i, s1_err_i,
                        s2_dat_i, s2_ack_i, s2_err_i,
                        s3_dat_i, s3_ack_i, s3_err_i, 1'b0};

endmodule

`default_nettype wire
