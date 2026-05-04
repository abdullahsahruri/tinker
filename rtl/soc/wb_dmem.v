// =============================================================================
// wb_dmem.v — 1 KB Wishbone B4 classic data memory (RW).
//
// Session 3.5 (OpenRAM): wraps a sky130_sram_1kbyte_1rw1r_32x256_8 macro.
// Same external port list as the Session 3E baseline; same wait-state FSM
// as wb_imem (1-cycle read latency from the macro). Writes are byte-
// strobed via wmask0.
//
// SRAM contents are undefined at reset. Firmware (or the testbench
// preload below) is responsible for initializing any DMEM word it
// depends on before reading.
//
// Sim-only TB-preload mirror: the Phase-3D testbench (tb_soc_bnn.sv,
// unchanged this session) hierarchically writes the 16 packed test
// images into `dut.u_dmem.mem[load_i]` after rst_n_i deasserts. We
// provide a sim-only `mem [0:WORDS-1]` reg array at the wb_dmem level
// for the testbench to write to, then mirror it into u_macro.mem on
// the second posedge clk after rst_n deasserts (i.e., one cycle past
// the testbench's preload @posedge). Yosys never sees the mirror —
// it lives inside `ifndef SYNTHESIS.
//
// keep_hierarchy attribute removed in Session 3.5 (see wb_imem.v header).
// =============================================================================
`default_nettype none

module wb_dmem (
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

    localparam integer WORDS = 256;          // 1 KB / 32-bit words
    localparam integer AW    = 8;            // log2(WORDS)

    // -------------------------------------------------------------------------
    // Wait-state FSM (same shape as wb_imem)
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
                        state <= S_READ_WAIT;
                        ack_q <= 1'b0;
                    end else if (is_write) begin
                        state <= S_IDLE;
                        ack_q <= 1'b1;
                    end else begin
                        ack_q <= 1'b0;
                    end
                end
                S_READ_WAIT: begin
                    state <= S_IDLE;
                    ack_q <= 1'b1;
                end
            endcase
        end
    end

    // -------------------------------------------------------------------------
    // Macro pin drivers
    // -------------------------------------------------------------------------
    wire        macro_active = (is_read | is_write);
    wire        csb0_int     = ~macro_active;
    wire        web0_int     = ~wb_we_i;
    wire [3:0]  wmask0_int   = wb_sel_i;
    wire [AW-1:0] addr0_int  = wb_adr_i[AW+1:2];
    wire [31:0] din0_int     = wb_dat_i;
    wire [31:0] dout0_int;

    sky130_sram_1kbyte_1rw1r_32x256_8 u_macro (
        .clk0   (clk),
        .csb0   (csb0_int),
        .web0   (web0_int),
        .wmask0 (wmask0_int),
        .addr0  (addr0_int),
        .din0   (din0_int),
        .dout0  (dout0_int),
        .clk1   (clk),
        .csb1   (1'b1),
        .addr1  ({AW{1'b0}}),
        .dout1  ()
    );

    // dout0 latch — same rationale as wb_imem.v. The macro resets dout0
    // to X with T_HOLD delay on every posedge, so we capture it at the
    // posedge that ends READ_WAIT and hold the value across the ack
    // cycle for the master to sample.
    reg [31:0] dout0_q;
    always @(posedge clk) begin
        if (!rst_n)                          dout0_q <= 32'h0;
        else if (state == S_READ_WAIT)       dout0_q <= dout0_int;
    end

    assign wb_ack_o = ack_q;
    assign wb_err_o = 1'b0;
    assign wb_dat_o = dout0_q;

    // -------------------------------------------------------------------------
    // Sim-only TB-preload mirror.
    // tb_soc_bnn.sv writes test images via `dut.u_dmem.mem[load_i] = …`
    // after rst_n_i deasserts (specifically, on the @(posedge clk) right
    // after `wait (rst_n_i === 1'b1)`). We declare `mem` at the wb_dmem
    // level so that hierarchical write succeeds, then on the FOLLOWING
    // posedge clk we mirror its contents into the macro's storage so
    // subsequent reads return the preloaded data.
    // -------------------------------------------------------------------------
`ifdef __ICARUS__
    defparam u_macro.VERBOSE = 0;        // silence per-access $display

    reg [31:0] mem [0:WORDS-1];          // visible at dut.u_dmem.mem
    integer _mirror_i;
    initial begin : sim_preload_mirror
        for (_mirror_i = 0; _mirror_i < WORDS; _mirror_i = _mirror_i + 1)
            mem[_mirror_i] = 32'h0;
        wait (rst_n === 1'b1);
        @(posedge clk);                  // matches the TB's preload @posedge
        @(posedge clk);                  // one cycle later — TB has now written
        for (_mirror_i = 0; _mirror_i < WORDS; _mirror_i = _mirror_i + 1)
            u_macro.mem[_mirror_i] = mem[_mirror_i];
    end
`endif

endmodule

`default_nettype wire
