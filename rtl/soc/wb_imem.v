// =============================================================================
// wb_imem.v — 2 KB Wishbone B4 classic instruction memory.
//
// Session 3.5 (OpenRAM): wraps a sky130_sram_2kbyte_1rw1r_32x512_8 macro
// from the sky130_sram_macros library. Replaces the Session 3E baseline
// register-file IMEM. Same external port list (drop-in replacement at
// soc_top), same memory map (2 KB at 0x0000_0000, RX), but the macro's
// 1-cycle synchronous read latency forces a wait-state FSM in this
// wrapper — the prior register-file's combinational read is gone.
//
// Bus protocol (Wishbone B4 classic, registered ack):
//   Read  (cyc&stb, ~we): cycle K drives macro inputs (csb0=0, web0=1),
//                         macro registers on posedge K→K+1, dout0 valid
//                         after negedge K+0.5; FSM enters READ_WAIT in
//                         K+1, asserts ack and presents dout0 in K+2 →
//                         3 cycles per read.
//   Write (cyc&stb,  we): cycle K drives macro inputs (csb0=0, web0=0,
//                         wmask0=sel, din0=dat); macro commits mem on
//                         negedge K+0.5; FSM acks in K+1 → 2 cycles
//                         per write.
//
// Sim-only INIT_HEX loader: an `initial` block reads the firmware hex
// into a temporary array and hierarchically copies it into u_macro.mem
// at sim time 0. The PicoRV32-visible reset hold in tb_soc_bnn.sv (16
// cycles) is unchanged; the load completes in zero sim time before any
// posedge clk reaches the macro. The loader is gated by `ifndef
// SYNTHESIS so Yosys never sees it.
//
// keep_hierarchy attribute removed in Session 3.5: LibreLane 3.0.3's macro
// placement and PDN steps emit "Macros inside hierarchical netlists are
// not currently supported" and skip submodules, requiring the macros to
// be direct children of soc_top after flatten. Power bucketing still
// works via the post-flatten escaped-identifier wire names.
// =============================================================================
`default_nettype none

// Sim-only firmware load: pass `+define+IMEM_INIT_HEX="path/to/firmware.hex"`
// to iverilog (see scripts/run_soc_{smoke,bnn}.sh). The define is
// invisible to Yosys / Verilator — synthesis produces no $paramod variant
// of this module (which would otherwise trip the LibreLane unmapped-cell
// checker on string-parameter overrides). The `INIT_HEX` parameter on
// soc_top is kept for TB compatibility but no longer forwarded here.
module wb_imem (
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

    localparam integer WORDS = 512;          // 2 KB / 32-bit words
    localparam integer AW    = 9;            // log2(WORDS)

    // -------------------------------------------------------------------------
    // Wait-state FSM
    // -------------------------------------------------------------------------
    localparam [0:0] S_IDLE = 1'b0, S_READ_WAIT = 1'b1;
    reg state;
    reg ack_q;

    wire bus_request = wb_cyc_i & wb_stb_i & ~ack_q;
    wire is_read     = bus_request & ~wb_we_i & (state == S_IDLE);
    wire is_write    = bus_request &  wb_we_i & (state == S_IDLE);

    always @(posedge clk) begin
        if (!rst_n) begin
            state <= S_IDLE;
            ack_q <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (is_read) begin
                        // Macro registered our inputs this edge; wait one
                        // cycle for dout0 to be valid.
                        state <= S_READ_WAIT;
                        ack_q <= 1'b0;
                    end else if (is_write) begin
                        // Macro registered the write this edge; commit on
                        // negedge. Single-cycle ack.
                        state <= S_IDLE;
                        ack_q <= 1'b1;
                    end else begin
                        ack_q <= 1'b0;
                    end
                end
                S_READ_WAIT: begin
                    state <= S_IDLE;
                    ack_q <= 1'b1;       // dout0 valid this cycle, ack now
                end
            endcase
        end
    end

    // -------------------------------------------------------------------------
    // Macro pin drivers — combinational from FSM-IDLE bus inputs.
    // Outside IDLE we deselect the macro (csb0=1) so a held cyc/stb after
    // ack doesn't double-trigger.
    // -------------------------------------------------------------------------
    wire        macro_active = (is_read | is_write);
    wire        csb0_int     = ~macro_active;        // active-low CS
    wire        web0_int     = ~wb_we_i;             // active-low WE
    wire [3:0]  wmask0_int   = wb_sel_i;             // byte mask (writes only)
    wire [AW-1:0] addr0_int  = wb_adr_i[AW+1:2];     // word address
    wire [31:0] din0_int     = wb_dat_i;
    wire [31:0] dout0_int;

    // Port 1 is read-only and unused — tie off.
    //
    // The behavioral macro model has body parameters (NOT port-list
    // parameters); the lint step can't override them via instance
    // `#(.X(Y))` syntax. Iverilog *can* override body parameters via
    // defparam, so the VERBOSE=0 override (which silences the macro's
    // per-access $display — ruinous for the BNN's 22 K-access × 16-image
    // run) lives in the __ICARUS__ block below.
    sky130_sram_2kbyte_1rw1r_32x512_8 u_macro (
        .clk0   (clk),
        .csb0   (csb0_int),
        .web0   (web0_int),
        .wmask0 (wmask0_int),
        .addr0  (addr0_int),
        .din0   (din0_int),
        .dout0  (dout0_int),
        .clk1   (clk),
        .csb1   (1'b1),                              // tie off
        .addr1  ({AW{1'b0}}),
        .dout1  ()                                   // unused
    );

    // -------------------------------------------------------------------------
    // Latch dout0 at the posedge that ends READ_WAIT.
    //
    // The macro's dout0 is only valid in a narrow window: from negedge K
    // (mem read fires at T_K+5+DELAY = T_K+8) through the next posedge
    // K+1, where dout0 is reset to X with T_HOLD delay. If we present
    // dout0 directly to the bus and let the master sample it on its
    // next clk edge (posedge K+2), dout0 has been X for ~9 ns by then.
    //
    // Capturing dout0 into dout0_q at posedge K+1 catches the pre-edge
    // value (mem[A] — the T_HOLD-delayed reset to X hasn't fired yet at
    // the simulation step where the wrapper's always block evaluates).
    // dout0_q then holds mem[A] throughout cycle K+1 for the master to
    // sample on posedge K+2 alongside ack_q=1.
    // -------------------------------------------------------------------------
    reg [31:0] dout0_q;
    always @(posedge clk) begin
        if (!rst_n)                          dout0_q <= 32'h0;
        else if (state == S_READ_WAIT)       dout0_q <= dout0_int;
    end

    assign wb_ack_o = ack_q;
    assign wb_err_o = 1'b0;
    assign wb_dat_o = dout0_q;

    // wb_we_i / wb_dat_i / wb_sel_i are intentionally ignored on the FSM
    // gating side — IMEM is RX in firmware, but the macro accepts byte-
    // strobed writes if the bus ever asserts we (e.g., a stray store).
    // Reads return 0 on the cycle ack is not asserted.

    // -------------------------------------------------------------------------
    // Sim-only INIT_HEX loader and macro-VERBOSE override.
    // Both paths use cross-module hierarchical writes / defparams which
    // the LibreLane lint step (verilator) rejects but Icarus accepts.
    // Gated on __ICARUS__ (defined automatically by iverilog only).
    // -------------------------------------------------------------------------
`ifdef __ICARUS__
    defparam u_macro.VERBOSE = 0;        // silence per-access $display

`ifdef IMEM_INIT_HEX
    reg [31:0] _init_tmp [0:WORDS-1];
    integer    _init_i;
    initial begin : sim_init
        for (_init_i = 0; _init_i < WORDS; _init_i = _init_i + 1)
            _init_tmp[_init_i] = 32'h0;
        $readmemh(`IMEM_INIT_HEX, _init_tmp);
        for (_init_i = 0; _init_i < WORDS; _init_i = _init_i + 1)
            u_macro.mem[_init_i] = _init_tmp[_init_i];
    end
`endif
`endif

endmodule

`default_nettype wire
