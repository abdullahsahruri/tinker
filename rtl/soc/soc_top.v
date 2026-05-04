// =============================================================================
// soc_top.v — SoC top level (Phase 3A skeleton)
//
// Single-clock RV32I SoC built around the PicoRV32 core and the Phase-2C
// `tile_tlg_ld` accelerator. Reset is async-asserted / sync-deasserted via
// a 2-FF reset synchronizer. Wishbone B4 classic bus with 32-bit data and
// 32-bit address; address decode on adr[31:28] selects one of four slaves
// (IMEM @ 0x0, DMEM @ 0x1, TILE @ 0x2, GPIO @ 0x3).
//
// See docs/PHASE3_ARCHITECTURE.md for the full spec. This file is a
// SKELETON: every block is wired, but the bodies of most submodules are
// intentionally minimal stubs (Sessions 3B/3C/3D fill them in). The
// purpose of the skeleton is to lock in port lists and hierarchy.
// =============================================================================
`default_nettype none

module soc_top #(
    parameter INIT_HEX = ""        // path to firmware $readmemh; testbench sets this
) (
    input  wire       clk,
    input  wire       rst_n_i,    // chip-pin reset, async-assert
    input  wire [7:0] gpio_i,
    output wire [7:0] gpio_o
);

    // -------------------------------------------------------------------------
    // Reset synchronizer: async-assert, sync-deassert.
    // Two-FF chain that takes rst_n_i (treated async) and produces an
    // internal rst_n that all sequential logic consumes synchronously.
    // -------------------------------------------------------------------------
    reg rst_sync_q1, rst_sync_q2;
    always @(posedge clk or negedge rst_n_i) begin
        if (!rst_n_i) begin
            rst_sync_q1 <= 1'b0;
            rst_sync_q2 <= 1'b0;
        end else begin
            rst_sync_q1 <= 1'b1;
            rst_sync_q2 <= rst_sync_q1;
        end
    end
    wire rst_n = rst_sync_q2;

    // -------------------------------------------------------------------------
    // Wishbone master (PicoRV32 wrapper output).
    // -------------------------------------------------------------------------
    wire        m_cyc;
    wire        m_stb;
    wire        m_we;
    wire [3:0]  m_sel;
    wire [31:0] m_adr;
    wire [31:0] m_dat_w;     // master -> slave
    wire [31:0] m_dat_r;     // slave  -> master
    wire        m_ack;
    wire        m_err;

    picorv32_wrapper u_cpu (
        .clk         (clk),
        .rst_n       (rst_n),
        .wbm_cyc_o   (m_cyc),
        .wbm_stb_o   (m_stb),
        .wbm_we_o    (m_we),
        .wbm_sel_o   (m_sel),
        .wbm_adr_o   (m_adr),
        .wbm_dat_o   (m_dat_w),
        .wbm_dat_i   (m_dat_r),
        .wbm_ack_i   (m_ack),
        .wbm_err_i   (m_err)
    );

    // -------------------------------------------------------------------------
    // Per-slave Wishbone wires.
    //   s0 = IMEM   (0x0xxx_xxxx)
    //   s1 = DMEM   (0x1xxx_xxxx)
    //   s2 = TILE   (0x2xxx_xxxx)
    //   s3 = GPIO   (0x3xxx_xxxx)
    // -------------------------------------------------------------------------
    wire        s0_cyc, s0_stb, s0_we, s0_ack, s0_err;
    wire [3:0]  s0_sel;
    wire [31:0] s0_adr, s0_dat_w, s0_dat_r;

    wire        s1_cyc, s1_stb, s1_we, s1_ack, s1_err;
    wire [3:0]  s1_sel;
    wire [31:0] s1_adr, s1_dat_w, s1_dat_r;

    wire        s2_cyc, s2_stb, s2_we, s2_ack, s2_err;
    wire [3:0]  s2_sel;
    wire [31:0] s2_adr, s2_dat_w, s2_dat_r;

    wire        s3_cyc, s3_stb, s3_we, s3_ack, s3_err;
    wire [3:0]  s3_sel;
    wire [31:0] s3_adr, s3_dat_w, s3_dat_r;

    wb_interconnect u_xbar (
        .clk        (clk),
        .rst_n      (rst_n),
        // master
        .m_cyc_i    (m_cyc),
        .m_stb_i    (m_stb),
        .m_we_i     (m_we),
        .m_sel_i    (m_sel),
        .m_adr_i    (m_adr),
        .m_dat_i    (m_dat_w),
        .m_dat_o    (m_dat_r),
        .m_ack_o    (m_ack),
        .m_err_o    (m_err),
        // slave 0 - IMEM
        .s0_cyc_o   (s0_cyc), .s0_stb_o(s0_stb), .s0_we_o(s0_we),
        .s0_sel_o   (s0_sel), .s0_adr_o(s0_adr), .s0_dat_o(s0_dat_w),
        .s0_dat_i   (s0_dat_r), .s0_ack_i(s0_ack), .s0_err_i(s0_err),
        // slave 1 - DMEM
        .s1_cyc_o   (s1_cyc), .s1_stb_o(s1_stb), .s1_we_o(s1_we),
        .s1_sel_o   (s1_sel), .s1_adr_o(s1_adr), .s1_dat_o(s1_dat_w),
        .s1_dat_i   (s1_dat_r), .s1_ack_i(s1_ack), .s1_err_i(s1_err),
        // slave 2 - TILE
        .s2_cyc_o   (s2_cyc), .s2_stb_o(s2_stb), .s2_we_o(s2_we),
        .s2_sel_o   (s2_sel), .s2_adr_o(s2_adr), .s2_dat_o(s2_dat_w),
        .s2_dat_i   (s2_dat_r), .s2_ack_i(s2_ack), .s2_err_i(s2_err),
        // slave 3 - GPIO
        .s3_cyc_o   (s3_cyc), .s3_stb_o(s3_stb), .s3_we_o(s3_we),
        .s3_sel_o   (s3_sel), .s3_adr_o(s3_adr), .s3_dat_o(s3_dat_w),
        .s3_dat_i   (s3_dat_r), .s3_ack_i(s3_ack), .s3_err_i(s3_err)
    );

    wb_imem #(.INIT_HEX(INIT_HEX)) u_imem (
        .clk      (clk),
        .rst_n    (rst_n),
        .wb_cyc_i (s0_cyc),
        .wb_stb_i (s0_stb),
        .wb_we_i  (s0_we),
        .wb_sel_i (s0_sel),
        .wb_adr_i (s0_adr),
        .wb_dat_i (s0_dat_w),
        .wb_dat_o (s0_dat_r),
        .wb_ack_o (s0_ack),
        .wb_err_o (s0_err)
    );

    wb_dmem u_dmem (
        .clk      (clk),
        .rst_n    (rst_n),
        .wb_cyc_i (s1_cyc),
        .wb_stb_i (s1_stb),
        .wb_we_i  (s1_we),
        .wb_sel_i (s1_sel),
        .wb_adr_i (s1_adr),
        .wb_dat_i (s1_dat_w),
        .wb_dat_o (s1_dat_r),
        .wb_ack_o (s1_ack),
        .wb_err_o (s1_err)
    );

    wb_tile_wrapper u_tile (
        .clk      (clk),
        .rst_n    (rst_n),
        .wb_cyc_i (s2_cyc),
        .wb_stb_i (s2_stb),
        .wb_we_i  (s2_we),
        .wb_sel_i (s2_sel),
        .wb_adr_i (s2_adr),
        .wb_dat_i (s2_dat_w),
        .wb_dat_o (s2_dat_r),
        .wb_ack_o (s2_ack),
        .wb_err_o (s2_err)
    );

    wb_gpio u_gpio (
        .clk      (clk),
        .rst_n    (rst_n),
        .wb_cyc_i (s3_cyc),
        .wb_stb_i (s3_stb),
        .wb_we_i  (s3_we),
        .wb_sel_i (s3_sel),
        .wb_adr_i (s3_adr),
        .wb_dat_i (s3_dat_w),
        .wb_dat_o (s3_dat_r),
        .wb_ack_o (s3_ack),
        .wb_err_o (s3_err),
        .gpio_i   (gpio_i),
        .gpio_o   (gpio_o)
    );

endmodule

`default_nettype wire
