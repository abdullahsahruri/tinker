// =============================================================================
// picorv32_wrapper.v — Wishbone-master wrapper around the PicoRV32 RV32I core
//                      (Phase 3A skeleton — replaced in Session 3C).
//
// Session 3C will:
//   - Vendor YosysHQ/picorv32 under rtl/vendor/picorv32/ at a pinned commit.
//   - Replace the body of this module with an instantiation of `picorv32_wb`
//     using the parameter set documented in PHASE3_ARCHITECTURE.md §3.4.
//
// In 3A this module is a port-shaped placeholder: master-side outputs are
// driven to safe idle values so the SoC elaborates and so a synthesis pass
// would yield "no bus activity" (which is the correct behaviour of a system
// with no CPU). The skeleton's sole purpose is to commit to the wrapper's
// port list so downstream modules can be wired against it.
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

    // TODO(3C): instantiate `picorv32_wb` with the parameter set from
    // PHASE3_ARCHITECTURE.md §3.4. Until then the master is idle.
    assign wbm_cyc_o = 1'b0;
    assign wbm_stb_o = 1'b0;
    assign wbm_we_o  = 1'b0;
    assign wbm_sel_o = 4'b0000;
    assign wbm_adr_o = 32'b0;
    assign wbm_dat_o = 32'b0;

    // Reads from inputs are illegal in stub form; tap them via a wire to
    // suppress "unused" warnings without mutating state.
    wire _unused_ok = &{1'b0, wbm_dat_i, wbm_ack_i, wbm_err_i, rst_n, clk, 1'b0};

endmodule

`default_nettype wire
