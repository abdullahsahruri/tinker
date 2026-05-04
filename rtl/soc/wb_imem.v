// =============================================================================
// wb_imem.v — 8 KB Wishbone B4 classic instruction memory
//              (Phase 3A skeleton).
//
// Backed by a register-file array (no OpenRAM, by project decision — see
// PHASE3_ARCHITECTURE.md §7). Loaded in simulation via `$readmemh` of the
// firmware hex; loaded in the LibreLane flow via a mechanism Session 3E
// will pick. Read-only at runtime; writes are silently dropped (a future
// revision could raise wb_err_o on write — undecided).
//
// SKELETON: ack=0, err=0, data=0. Session 3B implements the real memory
// model and `$readmemh` plumbing. Port list is FINAL.
//
// Address decode: byte address inside the slave is wb_adr_i[12:0] (8 KB);
// upper bits already filtered by the interconnect.
// =============================================================================
`default_nettype none

module wb_imem #(
    parameter integer SIZE_BYTES = 8192,
    parameter         INIT_HEX   = ""           // path to $readmemh file (3B)
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

    // TODO(3B): declare `reg [31:0] mem [0:(SIZE_BYTES/4)-1];`,
    // implement single-cycle ack on (cyc_i & stb_i), and gate
    // writes (or err on writes — pick in 3B).
    assign wb_dat_o = 32'b0;
    assign wb_ack_o = 1'b0;
    assign wb_err_o = 1'b0;

    wire _unused_ok = &{1'b0, clk, rst_n, wb_cyc_i, wb_stb_i, wb_we_i,
                        wb_sel_i, wb_adr_i, wb_dat_i, 1'b0};

    // Document the parameters so they can't be optimised away by lint.
    initial begin
        if (SIZE_BYTES == 0 || INIT_HEX == "INTENTIONALLY_UNUSED") begin
            // never taken at runtime; keeps the parameters referenced.
        end
    end

endmodule

`default_nettype wire
