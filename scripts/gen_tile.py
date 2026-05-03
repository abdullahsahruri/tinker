#!/usr/bin/env python3
"""
gen_tile.py — emit Verilog for the Phase-2 BNN tile (16 neurons × 64 inputs).

Four variants, all functionally identical:

  tlg     hardcoded   — `tile_tlg_hc`     : 16 TLG-decomposed neurons, weights baked in
  tlg     loadable    — `tile_tlg_ld`     : 16 TLG-decomposed neurons, weights in regs
  handopt hardcoded   — `tile_handopt_hc` : 16 adder-tree neurons, weights baked in
  handopt loadable    — `tile_handopt_ld` : 16 adder-tree neurons, weights in regs

Tile interface (all variants):
    clk, rst_n
    x_in[63:0], x_valid                — registered at the boundary; latched
                                          on a clock edge while x_valid is high
    y_out[15:0], y_valid               — registered output; valid 2 cycles
                                          after x_valid (one cycle for the
                                          input flop, one cycle of comb logic
                                          captured by the output flop)

Loadable variants additionally have:
    cfg_we, cfg_addr[5:0], cfg_wdata[63:0]
        cfg_addr  0..15 → write neuron i's 64-bit weight
        cfg_addr 16..31 → write neuron (i-16)'s 7-bit threshold (low bits)

Weights / thresholds for the **hardcoded** variants are generated from
`numpy.random.RandomState(42)` (16 × 64 random bits). The loadable variants
expect the testbench to program the same values at runtime; with that done
the four variants must produce identical outputs for any x.

Usage:
    python gen_tile.py tlg     --hardcoded --out rtl/tile_tlg_hc/
    python gen_tile.py tlg     --loadable  --out rtl/tile_tlg_ld/
    python gen_tile.py handopt --hardcoded --out rtl/tile_handopt_hc/
    python gen_tile.py handopt --loadable  --out rtl/tile_handopt_ld/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tlg_lib  # noqa: E402

N_NEURONS = 16
# User-facing seed_id → numpy.random.RandomState seed.
#
# Phase 2A baked WEIGHT_SEED = 42 into the RTL. Phase 2B's first run used
# that. To preserve those committed artifacts as the canonical "seed 0" of
# the multi-seed sweep, we keep seed_id 0 mapped to numpy seed 42 and use
# numpy seed N directly for seed_id N >= 1. The mapping is documented in
# docs/PHASE2B5_NOTES.md.
SEED_ID_TO_NUMPY_SEED = {0: 42}
LEGACY_SEED_ID = 0
DEFAULT_THRESHOLD = tlg_lib.THRESHOLD  # 32


def numpy_seed_for(seed_id: int) -> int:
    return SEED_ID_TO_NUMPY_SEED.get(seed_id, seed_id)


def file_suffix_for(seed_id: int) -> str:
    """Return '' for the legacy seed (preserves existing rtl/tile_<v>/tile_<v>.v
    paths from Phase 2A) and '_s<N>' for any non-legacy seed."""
    return "" if seed_id == LEGACY_SEED_ID else f"_s{seed_id}"

# ----------------------------------------------------------------------------
# Tile-top emitters
# ----------------------------------------------------------------------------

def _emit_pipeline_regs(indent: str = "    ") -> str:
    """Common registered-boundary boilerplate. Two flops (x_in→x_reg comb→y_out_r)
    plus a 2-deep valid pipeline."""
    lines = [
        f"{indent}// 2-cycle pipeline: x_in -> x_reg -> [comb logic] -> y_out_r.",
        f"{indent}// y_valid tracks the x_valid pulse through both flops.",
        f"{indent}reg  [63:0] x_reg;",
        f"{indent}reg  [15:0] y_out_r;",
        f"{indent}reg         v_d1, v_d2;",
        f"{indent}wire [15:0] y_comb;",
        f"{indent}always @(posedge clk) begin",
        f"{indent}    if (!rst_n) begin",
        f"{indent}        x_reg   <= 64'b0;",
        f"{indent}        y_out_r <= 16'b0;",
        f"{indent}        v_d1    <= 1'b0;",
        f"{indent}        v_d2    <= 1'b0;",
        f"{indent}    end else begin",
        f"{indent}        if (x_valid) x_reg <= x_in;",
        f"{indent}        v_d1    <= x_valid;",
        f"{indent}        y_out_r <= y_comb;",
        f"{indent}        v_d2    <= v_d1;",
        f"{indent}    end",
        f"{indent}end",
        f"{indent}assign y_out   = y_out_r;",
        f"{indent}assign y_valid = v_d2;",
    ]
    return "\n".join(lines) + "\n"


def _emit_regfile(indent: str = "    ") -> str:
    """Register file for loadable variants: 16 × 64b weights + 16 × 7b
    thresholds, written via cfg_we / cfg_addr / cfg_wdata."""
    lines = [
        f"{indent}// Configuration register file: cfg_addr[5:4]==2'b00 selects",
        f"{indent}// weight regs (0..15), 2'b01 selects threshold regs (16..31).",
        f"{indent}reg [63:0] w_reg [0:15];",
        f"{indent}reg [6:0]  t_reg [0:15];",
        f"{indent}integer _i;",
        f"{indent}always @(posedge clk) begin",
        f"{indent}    if (!rst_n) begin",
        f"{indent}        for (_i = 0; _i < 16; _i = _i + 1) begin",
        f"{indent}            w_reg[_i] <= 64'b0;",
        f"{indent}            t_reg[_i] <= 7'b0;",
        f"{indent}        end",
        f"{indent}    end else if (cfg_we) begin",
        f"{indent}        case (cfg_addr[5:4])",
        f"{indent}            2'b00: w_reg[cfg_addr[3:0]] <= cfg_wdata;",
        f"{indent}            2'b01: t_reg[cfg_addr[3:0]] <= cfg_wdata[6:0];",
        f"{indent}            default: ;",
        f"{indent}        endcase",
        f"{indent}    end",
        f"{indent}end",
    ]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# Variant emitters
# ----------------------------------------------------------------------------

def emit_tile_tlg_hc(weights, out_path: Path, seed_id: int) -> dict:
    """tile_tlg_hc: 16 TLG-decomposed neurons with per-neuron baked-in weights.
    Each neuron has 11 unique chunk submodules (one per chunk_idx, encoding the
    chunk's slice of that neuron's weight as a truth table)."""
    suffix = file_suffix_for(seed_id)
    top = f"tile_tlg_hc{suffix}"
    parts = [
        "// Auto-generated by gen_tile.py — variant=tlg, mode=hardcoded, "
        f"seed_id={seed_id} (numpy seed {numpy_seed_for(seed_id)}), neurons={N_NEURONS}.",
        "// 16 BNN neurons, each TLG-decomposed into 11 chunk truth tables.",
        "`default_nettype none",
        "",
    ]

    # Per-neuron chunk + neuron submodules.
    for ni, w in enumerate(weights):
        prefix = f"{top}_n{ni:02d}"
        neuron_top, chunk_decls = tlg_lib.emit_tlg_neuron_hc(
            f"{prefix}_neuron", w, prefix)
        parts.extend(chunk_decls)
        parts.append("")
        parts.append(neuron_top)
        parts.append("")

    # Top tile module.
    parts.append(f"module {top} (")
    parts.append("    input  wire        clk,")
    parts.append("    input  wire        rst_n,")
    parts.append("    input  wire [63:0] x_in,")
    parts.append("    input  wire        x_valid,")
    parts.append("    output wire [15:0] y_out,")
    parts.append("    output wire        y_valid")
    parts.append(");")
    parts.append(_emit_pipeline_regs())
    for ni in range(N_NEURONS):
        parts.append(f"    {top}_n{ni:02d}_neuron u_n{ni:02d} "
                     f"(.x(x_reg), .y(y_comb[{ni}]));")
    parts.append("endmodule")
    parts.append("`default_nettype wire")

    text = "\n".join(parts) + "\n"
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / f"{top}.v").write_text(text)
    return {"top": top, "n_chunk_modules": N_NEURONS * 11,
            "n_neuron_modules": N_NEURONS}


def emit_tile_tlg_ld(weights, out_path: Path, seed_id: int) -> dict:
    """tile_tlg_ld: shared chunk6_ld + chunk4_ld + one ld neuron module +
    16 instances driven by the regfile.

    The .v file is **seed-invariant** by construction (truth tables encode
    `popcount(m)` for runtime `m = x XNOR w`; weights live in the regfile,
    not the RTL). The seed_id only affects the generated manifest's
    expected weight values for downstream testbench programming."""
    suffix = file_suffix_for(seed_id)
    top = f"tile_tlg_ld{suffix}"
    parts = [
        "// Auto-generated by gen_tile.py — variant=tlg, mode=loadable, "
        f"neurons={N_NEURONS} (RTL is seed-invariant; manifest carries "
        f"seed_id={seed_id}).",
        "// Generic TLG decomposition: weights/thresholds in a config regfile.",
        "`default_nettype none",
        "",
        tlg_lib.emit_tlg_chunk_ld(f"{top}_chunk6", 6),
        "",
        tlg_lib.emit_tlg_chunk_ld(f"{top}_chunk4", 4),
        "",
        tlg_lib.emit_tlg_neuron_ld(f"{top}_neuron",
                                   f"{top}_chunk6", f"{top}_chunk4"),
        "",
    ]

    parts.append(f"module {top} (")
    parts.append("    input  wire        clk,")
    parts.append("    input  wire        rst_n,")
    parts.append("    input  wire [63:0] x_in,")
    parts.append("    input  wire        x_valid,")
    parts.append("    output wire [15:0] y_out,")
    parts.append("    output wire        y_valid,")
    parts.append("    input  wire        cfg_we,")
    parts.append("    input  wire [5:0]  cfg_addr,")
    parts.append("    input  wire [63:0] cfg_wdata")
    parts.append(");")
    parts.append(_emit_pipeline_regs())
    parts.append(_emit_regfile())
    for ni in range(N_NEURONS):
        parts.append(f"    {top}_neuron u_n{ni:02d} "
                     f"(.x(x_reg), .w(w_reg[{ni}]), "
                     f".threshold(t_reg[{ni}]), .y(y_comb[{ni}]));")
    parts.append("endmodule")
    parts.append("`default_nettype wire")

    text = "\n".join(parts) + "\n"
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / f"{top}.v").write_text(text)
    return {"top": top, "n_chunk_modules": 2, "n_neuron_modules": 1}


def emit_tile_handopt_hc(weights, out_path: Path, seed_id: int) -> dict:
    """tile_handopt_hc: 16 adder-tree neurons, each with weights baked in."""
    suffix = file_suffix_for(seed_id)
    top = f"tile_handopt_hc{suffix}"
    parts = [
        "// Auto-generated by gen_tile.py — variant=handopt, mode=hardcoded, "
        f"seed_id={seed_id} (numpy seed {numpy_seed_for(seed_id)}), neurons={N_NEURONS}.",
        "// 16 BNN neurons, each implemented as a balanced adder-tree popcount.",
        "`default_nettype none",
        "",
    ]

    for ni, w in enumerate(weights):
        w_int = tlg_lib.w_to_int(w)
        parts.append(tlg_lib.emit_handopt_neuron(f"{top}_n{ni:02d}_neuron",
                                                 w_int=w_int))
        parts.append("")

    parts.append(f"module {top} (")
    parts.append("    input  wire        clk,")
    parts.append("    input  wire        rst_n,")
    parts.append("    input  wire [63:0] x_in,")
    parts.append("    input  wire        x_valid,")
    parts.append("    output wire [15:0] y_out,")
    parts.append("    output wire        y_valid")
    parts.append(");")
    parts.append(_emit_pipeline_regs())
    for ni in range(N_NEURONS):
        parts.append(f"    {top}_n{ni:02d}_neuron u_n{ni:02d} "
                     f"(.x(x_reg), .y(y_comb[{ni}]));")
    parts.append("endmodule")
    parts.append("`default_nettype wire")

    text = "\n".join(parts) + "\n"
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / f"{top}.v").write_text(text)
    return {"top": top, "n_chunk_modules": 0,
            "n_neuron_modules": N_NEURONS}


def emit_tile_handopt_ld(weights, out_path: Path, seed_id: int) -> dict:
    """tile_handopt_ld: 1 generic adder-tree neuron module, 16 instances driven
    by the regfile.

    The .v file is **seed-invariant** by construction (the neuron module
    takes `W` and `threshold` as ports, not localparams). The seed_id only
    affects the generated manifest's expected weight values for downstream
    testbench programming."""
    suffix = file_suffix_for(seed_id)
    top = f"tile_handopt_ld{suffix}"
    parts = [
        "// Auto-generated by gen_tile.py — variant=handopt, mode=loadable, "
        f"neurons={N_NEURONS} (RTL is seed-invariant; manifest carries "
        f"seed_id={seed_id}).",
        "// Adder-tree popcount with weights/thresholds in a config regfile.",
        "`default_nettype none",
        "",
        tlg_lib.emit_handopt_neuron(f"{top}_neuron"),
        "",
    ]

    parts.append(f"module {top} (")
    parts.append("    input  wire        clk,")
    parts.append("    input  wire        rst_n,")
    parts.append("    input  wire [63:0] x_in,")
    parts.append("    input  wire        x_valid,")
    parts.append("    output wire [15:0] y_out,")
    parts.append("    output wire        y_valid,")
    parts.append("    input  wire        cfg_we,")
    parts.append("    input  wire [5:0]  cfg_addr,")
    parts.append("    input  wire [63:0] cfg_wdata")
    parts.append(");")
    parts.append(_emit_pipeline_regs())
    parts.append(_emit_regfile())
    for ni in range(N_NEURONS):
        parts.append(f"    {top}_neuron u_n{ni:02d} "
                     f"(.x(x_reg), .W(w_reg[{ni}]), "
                     f".threshold(t_reg[{ni}]), .y(y_comb[{ni}]));")
    parts.append("endmodule")
    parts.append("`default_nettype wire")

    text = "\n".join(parts) + "\n"
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / f"{top}.v").write_text(text)
    return {"top": top, "n_chunk_modules": 0, "n_neuron_modules": 1}


EMITTERS = {
    ("tlg",     "hc"): emit_tile_tlg_hc,
    ("tlg",     "ld"): emit_tile_tlg_ld,
    ("handopt", "hc"): emit_tile_handopt_hc,
    ("handopt", "ld"): emit_tile_handopt_ld,
}


def write_manifest(out_path: Path, variant_logic: str, variant_mode: str,
                   seed_id: int, weights, thresholds, info: dict) -> None:
    """Manifest the tile's runtime parameters so the testbench (and any future
    consumer of this directory) can read the same (w, t) values that were
    baked into the hardcoded variants."""
    suffix = file_suffix_for(seed_id)
    manifest = {
        "variant_logic": variant_logic,
        "variant_mode": variant_mode,
        "seed_id": seed_id,
        "numpy_seed": numpy_seed_for(seed_id),
        "n_neurons": N_NEURONS,
        "n_inputs": tlg_lib.N_INPUTS,
        "weights_hex": [f"0x{tlg_lib.w_to_int(w):016x}" for w in weights],
        "thresholds": thresholds,
        **info,
    }
    manifest_name = f"manifest{suffix}.json" if suffix else "manifest.json"
    (out_path / manifest_name).write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("variant_logic", choices=["tlg", "handopt"])
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--hardcoded", action="store_const", const="hc",
                      dest="variant_mode")
    mode.add_argument("--loadable", action="store_const", const="ld",
                      dest="variant_mode")
    p.add_argument("--seed", type=int, default=LEGACY_SEED_ID,
                   help=f"seed_id (default {LEGACY_SEED_ID}); "
                        f"see SEED_ID_TO_NUMPY_SEED for the legacy mapping")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    weights = tlg_lib.gen_weight_set(numpy_seed_for(args.seed), N_NEURONS)
    thresholds = [DEFAULT_THRESHOLD] * N_NEURONS
    emit = EMITTERS[(args.variant_logic, args.variant_mode)]
    info = emit(weights, args.out, args.seed)
    write_manifest(args.out, args.variant_logic, args.variant_mode,
                   args.seed, weights, thresholds, info)
    print(f"wrote {args.out / (info['top'] + '.v')} "
          f"({info['n_chunk_modules']} chunk + {info['n_neuron_modules']} neuron submodules)")


if __name__ == "__main__":
    main()
