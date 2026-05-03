#!/usr/bin/env python3
"""Emit a per-(variant, seed) power testbench.

The TB instantiates exactly one DUT (whichever (variant_logic, variant_mode,
seed_id) it is built for), drives reset → optional cfg-write program → 1024
input vectors at the 2-cycle pipeline cadence, and dumps a VCD scoped to the
DUT instance.

Output: tb/phase2c/<dut_module>/tb_power.sv

The VCD is written to <dut_module>.vcd in the runtime cwd. We only dump the
DUT subtree (`$dumpvars(0, dut)`) — OpenSTA's `read_power_activities -vcd`
will auto-pick up clk/x_in/x_valid/etc. on the boundary and propagate
through the post-route netlist statistically. Internal RTL net names won't
match the post-route netlist (yosys+OpenROAD rename them), but boundary
matching is what activity-aware power analysis actually needs.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import gen_tile  # noqa: E402

CLOCK_PERIOD_NS = 10  # matches LibreLane CLOCK_PERIOD = 10 ns


def dut_module_name(variant_logic: str, variant_mode: str, seed_id: int) -> str:
    base = f"tile_{variant_logic}_{variant_mode}"
    # Loadable RTL is seed-invariant by construction (no weight constants
    # in the .v body), so only the seed-0 module exists — every seed_id
    # reuses it and differentiates via runtime cfg-write programs.
    if variant_mode == "ld":
        return base
    suffix = gen_tile.file_suffix_for(seed_id)
    return f"{base}{suffix}"


def emit_tb(variant_logic: str, variant_mode: str, seed_id: int,
            inputs_dir: Path, out_dir: Path, n_vectors: int = 1024,
            exclude_cfg: bool = False) -> Path:
    dut = dut_module_name(variant_logic, variant_mode, seed_id)
    is_ld = (variant_mode == "ld")
    # exclude_cfg only matters for ld variants (hc has no cfg phase). When
    # set, $dumpvars is delayed until the cfg-write transient has fully
    # settled, so OpenSTA's activity propagation sees only the inference
    # workload — not the regfile-write surge.
    exclude_cfg = exclude_cfg and is_ld
    out_dir.mkdir(parents=True, exist_ok=True)
    tb_path = out_dir / "tb_power.sv"

    xs_hex = (inputs_dir / "xs.hex").resolve()
    ws_hex = (inputs_dir / "ws.hex").resolve()
    ts_hex = (inputs_dir / "ts.hex").resolve()

    # $dumpvars placement. Default: at t=0, immediately after $dumpfile, so
    # the entire simulation (reset + cfg-writes + 1024 vectors) lands in the
    # VCD. When exclude_cfg is set on a ld variant, $dumpvars is moved to
    # the boundary between the cfg-write settle and the first vector — only
    # the steady-state inference window is recorded.
    if exclude_cfg:
        early_dumpvars = "        // $dumpvars deferred until after cfg-write phase (--exclude-cfg)\n"
        late_dumpvars  = "        $dumpvars(0, dut);\n"
    else:
        early_dumpvars = '        $dumpvars(0, dut);\n'
        late_dumpvars  = ""

    cfg_decl = ""
    cfg_port = ""
    cfg_init = ""
    cfg_program = ""
    if is_ld:
        cfg_decl = """
    reg        cfg_we;
    reg [5:0]  cfg_addr;
    reg [63:0] cfg_wdata;
    reg [63:0] w_set [0:15];
    reg [6:0]  t_set [0:15];
"""
        cfg_port = "        ,\n        .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata)"
        cfg_init = (
            "        cfg_we = 1'b0;\n"
            "        cfg_addr = 6'b0;\n"
            "        cfg_wdata = 64'b0;\n"
            f'        $readmemh("{ws_hex}", w_set);\n'
            f'        $readmemh("{ts_hex}", t_set);\n'
        )
        cfg_program = (
            "\n        // Program 16 weights then 16 thresholds.\n"
            "        for (i = 0; i < 16; i = i + 1) begin\n"
            "            @(negedge clk);\n"
            "            cfg_we    = 1'b1;\n"
            "            cfg_addr  = i[5:0];\n"
            "            cfg_wdata = w_set[i];\n"
            "        end\n"
            "        for (i = 0; i < 16; i = i + 1) begin\n"
            "            @(negedge clk);\n"
            "            cfg_we    = 1'b1;\n"
            "            cfg_addr  = (16 + i);\n"
            "            cfg_wdata = {57'b0, t_set[i]};\n"
            "        end\n"
            "        @(negedge clk);\n"
            "        cfg_we = 1'b0;\n"
            "        // Two-cycle settle so the regfile writes fully propagate before\n"
            "        // the first input vector arrives.\n"
            "        @(posedge clk); @(posedge clk);\n"
            f"{late_dumpvars}"
        )

    # Half-period for the 100 MHz clock (10 ns period → 5 ns half).
    half = CLOCK_PERIOD_NS // 2

    # $dumpvars placement. Default: at t=0, immediately after $dumpfile, so
    # the entire simulation (reset + cfg-writes + 1024 vectors) lands in the
    # VCD. When exclude_cfg is set on a ld variant, $dumpvars is moved to
    # the boundary between the cfg-write settle and the first vector — only
    # the steady-state inference window is recorded.
    if exclude_cfg:
        early_dumpvars = "// $dumpvars deferred until after cfg-write phase (--exclude-cfg)\n"
        late_dumpvars  = "        $dumpvars(0, dut);\n"
    else:
        early_dumpvars = '        $dumpvars(0, dut);\n'
        late_dumpvars  = ""

    tb_src = f"""// Auto-generated by scripts/emit_power_tb.py
// variant_logic={variant_logic}, variant_mode={variant_mode}, seed_id={seed_id}
// dut module = {dut}
// vectors = {n_vectors} (xs.hex)
// dump-window: {"steady-state inference only (cfg-writes excluded)" if exclude_cfg else "full simulation (reset + cfg + inference)"}
//
// Drives reset, {'optional cfg-write program, ' if is_ld else ''}then {n_vectors}
// input vectors at the 3-cycle cadence specified in the Phase-2C brief:
// one cycle of x_valid=1 followed by two idle cycles. Total active-window
// length = N_VEC * 3 = {n_vectors * 3} cycles. This matches the tile's
// 2-cycle pipeline latency — vector i's y_out lands two cycles after the
// x_valid pulse, and the third cycle is the natural inter-vector gap that
// a downstream consumer would see at one inference per 3 cycles.
// Dumps a VCD scoped to the DUT for activity-aware power.

`timescale 1ns/1ps
module tb_power;
    localparam integer N_VEC = {n_vectors};

    reg clk;
    initial clk = 0;
    always #{half} clk = ~clk;        // {CLOCK_PERIOD_NS} ns period
    reg rst_n;

    reg [63:0] x_in;
    reg        x_valid;

    wire [15:0] y_out;
    wire        y_valid;
{cfg_decl}
    reg [63:0] xs [0:N_VEC-1];
    integer i;

    {dut} dut (
        .clk(clk), .rst_n(rst_n),
        .x_in(x_in), .x_valid(x_valid),
        .y_out(y_out), .y_valid(y_valid){cfg_port}
    );

    initial begin
        // Open VCD dump scoped to the DUT subtree only — the testbench
        // wrapper signals are uninteresting and would inflate the file.
        $dumpfile("{dut}.vcd");
{early_dumpvars}
        $readmemh("{xs_hex}", xs);

        rst_n   = 0;
        x_in    = 64'b0;
        x_valid = 1'b0;
{cfg_init}
        // Hold reset for 4 cycles, then deassert.
        repeat (4) @(posedge clk);
        rst_n = 1;
        @(posedge clk);
{cfg_program}
        // Drive N_VEC vectors at the 3-cycle cadence (1 valid + 2 idle).
        for (i = 0; i < N_VEC; i = i + 1) begin
            @(negedge clk);
            x_in    = xs[i];
            x_valid = 1'b1;
            @(posedge clk);    // input flop latches xs[i]
            @(negedge clk);
            x_valid = 1'b0;
            @(posedge clk);    // y_out_r captures y_comb(xs[i])
            @(posedge clk);    // idle cycle — inter-vector gap
        end

        // Two cycles of tail to drain the pipeline.
        @(posedge clk); @(posedge clk);
        $finish;
    end
endmodule
"""
    tb_path.write_text(tb_src)
    return tb_path


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("variant_logic", choices=["tlg", "handopt"])
    p.add_argument("variant_mode", choices=["hc", "ld"])
    p.add_argument("seed_id", type=int)
    p.add_argument("--inputs",
                   default=ROOT / "results" / "phase2c" / "inputs",
                   type=Path)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--n", type=int, default=1024)
    p.add_argument("--exclude-cfg", action="store_true",
                   help="ld variants only: defer $dumpvars until after cfg-write phase, so OpenSTA sees only the inference window")
    args = p.parse_args()

    dut = dut_module_name(args.variant_logic, args.variant_mode, args.seed_id)
    out_dir = args.out or (ROOT / "tb" / "phase2c" / dut)
    inputs_dir = args.inputs / f"seed{args.seed_id}"
    if not inputs_dir.is_dir():
        sys.exit(f"missing input vectors at {inputs_dir} — run gen_input_vectors.py first")
    tb = emit_tb(args.variant_logic, args.variant_mode, args.seed_id,
                 inputs_dir, out_dir, n_vectors=args.n,
                 exclude_cfg=args.exclude_cfg)
    print(f"wrote {tb} (DUT: {dut}, exclude_cfg={args.exclude_cfg})")


if __name__ == "__main__":
    main()
