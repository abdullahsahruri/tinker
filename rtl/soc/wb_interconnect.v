// =============================================================================
// wb_interconnect.v — single-master, four-slave Wishbone B4 classic crossbar.
//
// Address decode: m_adr_i[31:28] selects one of four slaves
//   0x0 -> s0 (IMEM)
//   0x1 -> s1 (DMEM)
//   0x2 -> s2 (TILE)
//   0x3 -> s3 (GPIO)
//   else -> decode-miss: m_err_o asserted for the cycle, no slave selected.
//
// Topology: pure combinational. cyc/stb to slaves are gated by their
// per-slave select line; we/sel/adr/dat are broadcast to all slaves (cheap,
// and slaves with cyc=0 ignore them). dat/ack/err from slaves are muxed back
// to the master based on the registered (one-hot) select. m_err_o aggregates
// per-slave err with the decode-miss err.
//
// PicoRV32 (master) does not consume m_err_o (its WB wrapper has no err
// input). A decode-miss therefore never asserts ack to the master and the
// core hangs visibly on the offending access — see PHASE3_ARCHITECTURE.md §2
// "wild pointer hangs visibly rather than silently". The err line exists
// for STA/visibility and for any future master that does consume it.
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

    // -------------------------------------------------------------------------
    // 1. Address decode (one-hot).
    // -------------------------------------------------------------------------
    wire [3:0] dec = m_adr_i[31:28];

    wire sel0 = (dec == 4'h0);
    wire sel1 = (dec == 4'h1);
    wire sel2 = (dec == 4'h2);
    wire sel3 = (dec == 4'h3);
    wire dec_miss = ~(sel0 | sel1 | sel2 | sel3);

    wire xact = m_cyc_i & m_stb_i;

    // -------------------------------------------------------------------------
    // 2. Demuxed cyc/stb to each slave; broadcast we/sel/adr/dat.
    // -------------------------------------------------------------------------
    assign s0_cyc_o = m_cyc_i & sel0;
    assign s0_stb_o = m_stb_i & sel0;
    assign s0_we_o  = m_we_i;
    assign s0_sel_o = m_sel_i;
    assign s0_adr_o = m_adr_i;
    assign s0_dat_o = m_dat_i;

    assign s1_cyc_o = m_cyc_i & sel1;
    assign s1_stb_o = m_stb_i & sel1;
    assign s1_we_o  = m_we_i;
    assign s1_sel_o = m_sel_i;
    assign s1_adr_o = m_adr_i;
    assign s1_dat_o = m_dat_i;

    assign s2_cyc_o = m_cyc_i & sel2;
    assign s2_stb_o = m_stb_i & sel2;
    assign s2_we_o  = m_we_i;
    assign s2_sel_o = m_sel_i;
    assign s2_adr_o = m_adr_i;
    assign s2_dat_o = m_dat_i;

    assign s3_cyc_o = m_cyc_i & sel3;
    assign s3_stb_o = m_stb_i & sel3;
    assign s3_we_o  = m_we_i;
    assign s3_sel_o = m_sel_i;
    assign s3_adr_o = m_adr_i;
    assign s3_dat_o = m_dat_i;

    // -------------------------------------------------------------------------
    // 3. Read-data / ack / err mux back to master.
    //    Selection is comb. on the address — slaves only assert ack when
    //    they themselves see cyc&stb=1, so the OR-of-acks form is safe and
    //    avoids a separate registered "active slave" tracker.
    // -------------------------------------------------------------------------
    assign m_dat_o = sel0 ? s0_dat_i :
                     sel1 ? s1_dat_i :
                     sel2 ? s2_dat_i :
                     sel3 ? s3_dat_i : 32'b0;

    assign m_ack_o = (s0_ack_i & sel0) |
                     (s1_ack_i & sel1) |
                     (s2_ack_i & sel2) |
                     (s3_ack_i & sel3);

    assign m_err_o = (s0_err_i & sel0) |
                     (s1_err_i & sel1) |
                     (s2_err_i & sel2) |
                     (s3_err_i & sel3) |
                     (xact & dec_miss);

    // clk/rst_n are intentionally unused — interconnect is purely combinational.
    wire _unused_ok = &{1'b0, clk, rst_n, 1'b0};

endmodule

`default_nettype wire
