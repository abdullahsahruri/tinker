// =============================================================================
// picorv32_wrapper.v — Wishbone-master wrapper around the PicoRV32 RV32I core.
//
// Phase 3C implementation: instantiates the upstream `picorv32_wb` (vendored
// at vendor/picorv32/picorv32.v, commit 87c89ac) configured per
// PHASE3_ARCHITECTURE.md §3.4. The upstream wrapper already does the core
// `mem_*` → Wishbone master translation; this module's only added value is:
//
//   - Active-low rst_n (project convention) → active-high wb_rst_i (upstream).
//   - Tying off PCPI / IRQ / trace ports we do not use.
//   - Discarding wbm_err_i (upstream has no err input — decode-miss errors
//     hang the core via "no ack", which matches spec §2's "wild pointer
//     hangs visibly" semantics).
//
// Parameter overrides apply the §3.4 table verbatim. Defaults in `picorv32_wb`
// disagree with our needs on CATCH_MISALIGN, CATCH_ILLINSN, ENABLE_IRQ_QREGS,
// ENABLE_IRQ_TIMER, ENABLE_COUNTERS, ENABLE_COUNTERS64, REGS_INIT_ZERO, and
// STACKADDR — all explicitly overridden below.
// =============================================================================
`default_nettype none

module picorv32_wrapper (
    input  wire        clk,
    input  wire        rst_n,

    // Wishbone B4 classic master.
    output wire        wbm_cyc_o,
    output wire        wbm_stb_o,
    output wire        wbm_we_o,
    output wire [3:0]  wbm_sel_o,
    output wire [31:0] wbm_adr_o,
    output wire [31:0] wbm_dat_o,
    input  wire [31:0] wbm_dat_i,
    input  wire        wbm_ack_i,
    input  wire        wbm_err_i
);

    wire wb_rst = ~rst_n;     // upstream takes active-high reset

    // Tied-off PCPI / IRQ / trace nets (driven by upstream, ignored here).
    wire        u_pcpi_valid;
    wire [31:0] u_pcpi_insn;
    wire [31:0] u_pcpi_rs1;
    wire [31:0] u_pcpi_rs2;
    wire [31:0] u_eoi;
    wire        u_trace_valid;
    wire [35:0] u_trace_data;
    wire        u_trap;
    wire        u_mem_instr;

    picorv32_wb #(
        .ENABLE_COUNTERS      (1'b0),
        .ENABLE_COUNTERS64    (1'b0),
        .ENABLE_REGS_16_31    (1'b1),
        .ENABLE_REGS_DUALPORT (1'b1),
        .TWO_STAGE_SHIFT      (1'b1),
        .BARREL_SHIFTER       (1'b0),
        .TWO_CYCLE_COMPARE    (1'b0),
        .TWO_CYCLE_ALU        (1'b0),
        .COMPRESSED_ISA       (1'b0),
        .CATCH_MISALIGN       (1'b0),
        .CATCH_ILLINSN        (1'b0),
        .ENABLE_PCPI          (1'b0),
        .ENABLE_MUL           (1'b0),
        .ENABLE_FAST_MUL      (1'b0),
        .ENABLE_DIV           (1'b0),
        .ENABLE_IRQ           (1'b0),
        .ENABLE_IRQ_QREGS     (1'b0),
        .ENABLE_IRQ_TIMER     (1'b0),
        .ENABLE_TRACE         (1'b0),
        .REGS_INIT_ZERO       (1'b1),
        .MASKED_IRQ           (32'h0000_0000),
        .LATCHED_IRQ          (32'hffff_ffff),
        .PROGADDR_RESET       (32'h0000_0000),
        .PROGADDR_IRQ         (32'h0000_0010),
        .STACKADDR            (32'h1000_1000)
    ) u_core (
        .trap        (u_trap),
        .wb_rst_i    (wb_rst),
        .wb_clk_i    (clk),

        .wbm_adr_o   (wbm_adr_o),
        .wbm_dat_o   (wbm_dat_o),
        .wbm_dat_i   (wbm_dat_i),
        .wbm_we_o    (wbm_we_o),
        .wbm_sel_o   (wbm_sel_o),
        .wbm_stb_o   (wbm_stb_o),
        .wbm_ack_i   (wbm_ack_i),
        .wbm_cyc_o   (wbm_cyc_o),

        // PCPI tied off (ENABLE_PCPI=0).
        .pcpi_valid  (u_pcpi_valid),
        .pcpi_insn   (u_pcpi_insn),
        .pcpi_rs1    (u_pcpi_rs1),
        .pcpi_rs2    (u_pcpi_rs2),
        .pcpi_wr     (1'b0),
        .pcpi_rd     (32'b0),
        .pcpi_wait   (1'b0),
        .pcpi_ready  (1'b0),

        // IRQ tied off (ENABLE_IRQ=0).
        .irq         (32'b0),
        .eoi         (u_eoi),

        .trace_valid (u_trace_valid),
        .trace_data  (u_trace_data),

        .mem_instr   (u_mem_instr)
    );

    // Suppress lint on wbm_err_i — upstream wrapper has no err input.
    // A decode-miss currently never asserts ack, which hangs the core.
    // That matches PHASE3_ARCHITECTURE.md §2 ("wild pointer hangs visibly").
    wire _unused_ok = &{1'b0, wbm_err_i, u_trap, u_mem_instr,
                        u_pcpi_valid, u_pcpi_insn, u_pcpi_rs1, u_pcpi_rs2,
                        u_eoi, u_trace_valid, u_trace_data, 1'b0};

endmodule

`default_nettype wire
