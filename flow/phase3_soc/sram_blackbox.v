/// sta-blackbox
//
// Phase 3.5 — port-only blackbox stubs for the OpenRAM macros.
// OpenSTA's Verilog parser cannot handle the behavioral PDK macro models
// (they use simulation-only constructs like #DELAY, $display, etc.). The
// timing/power data for OpenSTA comes from the Liberty files; OpenSTA
// only needs the port list to know about the macros' boundary nets.
// `/// sta-blackbox` at the top tells OpenSTA to treat these as opaque.
//
// iverilog simulation continues to use the full PDK Verilog models
// directly (added on the iverilog command line in scripts/run_soc_*.sh)
// — this file is for the LibreLane synthesis + STA path only.
`default_nettype none

module sky130_sram_2kbyte_1rw1r_32x512_8 (
    `ifdef USE_POWER_PINS
    inout  vccd1,
    inout  vssd1,
    `endif
    input  wire        clk0,
    input  wire        csb0,
    input  wire        web0,
    input  wire [3:0]  wmask0,
    input  wire [8:0]  addr0,
    input  wire [31:0] din0,
    output wire [31:0] dout0,
    input  wire        clk1,
    input  wire        csb1,
    input  wire [8:0]  addr1,
    output wire [31:0] dout1
);
endmodule

module sky130_sram_1kbyte_1rw1r_32x256_8 (
    `ifdef USE_POWER_PINS
    inout  vccd1,
    inout  vssd1,
    `endif
    input  wire        clk0,
    input  wire        csb0,
    input  wire        web0,
    input  wire [3:0]  wmask0,
    input  wire [7:0]  addr0,
    input  wire [31:0] din0,
    output wire [31:0] dout0,
    input  wire        clk1,
    input  wire        csb1,
    input  wire [7:0]  addr1,
    output wire [31:0] dout1
);
endmodule

`default_nettype wire
