"""
tlg_lib — shared decomposition / Verilog-emit primitives.

Used by:
  scripts/gen_neuron.py   (Phase 1: single-neuron variants)
  scripts/gen_tile.py     (Phase 2: 16-neuron tile variants, hc + ld)

The Phase 1 generator predates this module; after this refactor it imports
the constants and the chunk emitter from here. Output of `gen_neuron.py`
is verified byte-identical to what Phase 1 committed.

Conventions
-----------
- Inputs / weights are 64-bit unsigned ints with bit i representing input/weight
  position i (LSB at position 0, matching the Verilog `[63:0]` convention).
- Each weight bit ∈ {0,1} encodes ±1 in the BNN (1→+1, 0→−1). The neuron
  computes `y = (popcount(x XNOR W) >= THRESHOLD)`.
- THRESHOLD = 32 (the natural midpoint of a 64-input popcount).
"""
from __future__ import annotations

import numpy as np

# --- Configuration constants ---------------------------------------------------
N_INPUTS = 64
THRESHOLD = 32
CHUNK_SIZE = 6  # 10 chunks of 6 + 1 chunk of 4 = 64


# --- Numeric helpers -----------------------------------------------------------

def gen_weights(seed: int, n_inputs: int = N_INPUTS) -> np.ndarray:
    """Reproducible per-seed weight vector (uint8, bits in {0,1})."""
    rng = np.random.RandomState(seed)
    return rng.randint(0, 2, size=n_inputs).astype(np.uint8)


def gen_weight_set(seed: int, n_neurons: int, n_inputs: int = N_INPUTS):
    """Return a list of `n_neurons` independent weight vectors.

    A single np.random.RandomState(seed) draws all n*N bits in row-major order,
    so the result is deterministic in seed and reproducible across machines.
    """
    rng = np.random.RandomState(seed)
    bits = rng.randint(0, 2, size=(n_neurons, n_inputs)).astype(np.uint8)
    return [bits[i] for i in range(n_neurons)]


def w_to_int(bits: np.ndarray) -> int:
    """Pack a bit array (LSB at index 0) into an integer."""
    return int(sum(int(b) << i for i, b in enumerate(bits)))


def reference_y(x_int: int, w_int: int, threshold: int = THRESHOLD,
                n_inputs: int = N_INPUTS) -> int:
    """Golden model: 1 iff popcount(x XNOR w) >= threshold."""
    mask = (1 << n_inputs) - 1
    xnor = (~(x_int ^ w_int)) & mask
    return int(bin(xnor).count("1") >= threshold)


def chunk_partition(n_inputs: int = N_INPUTS, chunk_size: int = CHUNK_SIZE):
    """Yield (lo, hi, size) for the standard partition: 10×6 + 1×4 for 64 inputs."""
    bit = 0
    while bit + chunk_size <= n_inputs:
        yield (bit, bit + chunk_size, chunk_size)
        bit += chunk_size
    if bit < n_inputs:
        yield (bit, n_inputs, n_inputs - bit)


# --- Verilog-fragment emitters ------------------------------------------------

def emit_tlg_chunk_hc(module_name: str, chunk_size: int,
                      chunk_w_int: int) -> str:
    """One TLG chunk for the hardcoded variant: 6→3 (or 4→3) truth table for
    popcount(x XNOR chunk_w_const) expressed as `case (x)`.

    Phase 1 used the same body via gen_neuron.emit_tlg_chunk_module; this is
    the canonical implementation now."""
    mask = (1 << chunk_size) - 1
    out = [f"module {module_name} (",
           f"    input  wire [{chunk_size-1}:0] x,",
           "    output reg  [2:0] pc",
           ");",
           "    always @* begin",
           "        case (x)"]
    for v in range(1 << chunk_size):
        xnor_v = (~(v ^ chunk_w_int)) & mask
        out.append(f"            {chunk_size}'d{v:>3}: pc = 3'd{bin(xnor_v).count('1')};")
    out.append("            default: pc = 3'd0;")
    out.append("        endcase")
    out.append("    end")
    out.append("endmodule")
    return "\n".join(out) + "\n"


def emit_tlg_chunk_ld(module_name: str, chunk_size: int) -> str:
    """One TLG chunk for the loadable variant: x[chunk] XNOR w[chunk] then
    popcount of the resulting bits, expressed as `case (m)` so ABC sees the
    same flat 6→3 / 4→3 truth-table mapping problem as the hardcoded variant.

    A single such module is shared by all 16×11 chunk instances in the tile —
    weights come in via the `w` port instead of being baked in."""
    out = [f"module {module_name} (",
           f"    input  wire [{chunk_size-1}:0] x,",
           f"    input  wire [{chunk_size-1}:0] w,",
           "    output reg  [2:0] pc",
           ");",
           f"    wire [{chunk_size-1}:0] m = x ^~ w;",
           "    always @* begin",
           "        case (m)"]
    for v in range(1 << chunk_size):
        out.append(f"            {chunk_size}'d{v:>3}: pc = 3'd{bin(v).count('1')};")
    out.append("            default: pc = 3'd0;")
    out.append("        endcase")
    out.append("    end")
    out.append("endmodule")
    return "\n".join(out) + "\n"


def emit_handopt_neuron(name: str, *, w_int: int | None = None) -> str:
    """Hand-optimized 7-layer balanced adder-tree neuron.

    If `w_int` is given, weights are baked in as a localparam and the threshold
    is the canonical 32 (used by gen_tile's hardcoded handopt variant). If
    `w_int` is None, the module exposes `W[63:0]` and `threshold[6:0]` as ports
    (used by the loadable handopt variant)."""
    out = ["`default_nettype none"]
    if w_int is None:
        out.append(f"module {name} (")
        out.append("    input  wire [63:0] x,")
        out.append("    input  wire [63:0] W,")
        out.append("    input  wire [6:0]  threshold,")
        out.append("    output wire        y")
        out.append(");")
    else:
        out.append(f"module {name} (")
        out.append("    input  wire [63:0] x,")
        out.append("    output wire        y")
        out.append(");")
        out.append(f"    localparam [63:0] W = 64'h{w_int:016x};")
    out.append("    wire [63:0] m;")
    out.append("    assign m = x ^~ W;")
    out.append("    // L1: 32 partial sums of 2 bits each")
    for i in range(32):
        out.append(f"    wire [1:0] s1_{i:02d} = m[{2*i}] + m[{2*i+1}];")
    out.append("    // L2: 16 partial sums of 3 bits each")
    for i in range(16):
        out.append(f"    wire [2:0] s2_{i:02d} = s1_{2*i:02d} + s1_{2*i+1:02d};")
    out.append("    // L3: 8 partial sums of 4 bits each")
    for i in range(8):
        out.append(f"    wire [3:0] s3_{i:02d} = s2_{2*i:02d} + s2_{2*i+1:02d};")
    out.append("    // L4: 4 partial sums of 5 bits each")
    for i in range(4):
        out.append(f"    wire [4:0] s4_{i:02d} = s3_{2*i:02d} + s3_{2*i+1:02d};")
    out.append("    // L5: 2 partial sums of 6 bits each")
    for i in range(2):
        out.append(f"    wire [5:0] s5_{i:02d} = s4_{2*i:02d} + s4_{2*i+1:02d};")
    out.append("    // L6: total popcount, 7 bits")
    out.append("    wire [6:0] total = s5_00 + s5_01;")
    out.append("    assign y = (total >= " +
               (f"7'd{THRESHOLD});" if w_int is not None else "threshold);"))
    out.append("endmodule")
    out.append("`default_nettype wire")
    return "\n".join(out) + "\n"


def emit_tlg_neuron_hc(name: str, w_bits: np.ndarray,
                       chunk_module_prefix: str) -> tuple[str, list[str]]:
    """Hardcoded TLG neuron: 11 chunk submodules (unique per neuron because the
    truth tables encode the per-neuron weight slice) + a top with a flat sum
    + threshold compare. Returns (top_module_text, list_of_chunk_module_decls).
    """
    chunks = []
    for ci, (lo, hi, csz) in enumerate(chunk_partition()):
        cw_int = w_to_int(w_bits[lo:hi])
        chunks.append((ci, lo, hi, csz, cw_int))

    chunk_decls = [
        emit_tlg_chunk_hc(f"{chunk_module_prefix}_c{ci:02d}", csz, cw_int)
        for ci, _, _, csz, cw_int in chunks
    ]

    out = [f"module {name} (",
           "    input  wire [63:0] x,",
           "    output wire        y",
           ");"]
    for ci, lo, hi, csz, _ in chunks:
        out.append(f"    wire [2:0] pc{ci:02d};")
        out.append(f"    {chunk_module_prefix}_c{ci:02d} u{ci:02d} "
                   f"(.x(x[{hi-1}:{lo}]), .pc(pc{ci:02d}));")
    pc_terms = " + ".join(f"pc{ci:02d}" for ci in range(len(chunks)))
    out.append(f"    wire [6:0] total = {pc_terms};")
    out.append(f"    assign y = (total >= 7'd{THRESHOLD});")
    out.append("endmodule")
    return ("\n".join(out) + "\n", chunk_decls)


def emit_tlg_neuron_ld(name: str, chunk6_module: str,
                       chunk4_module: str) -> str:
    """Loadable TLG neuron: takes 64-bit `w` and 7-bit `threshold` as ports;
    instantiates the shared chunk6_ld / chunk4_ld modules (one definition each
    in the tile, used by all 16 neurons)."""
    out = [f"module {name} (",
           "    input  wire [63:0] x,",
           "    input  wire [63:0] w,",
           "    input  wire [6:0]  threshold,",
           "    output wire        y",
           ");"]
    chunks = list(chunk_partition())
    for ci, (lo, hi, csz) in enumerate(chunks):
        mod = chunk6_module if csz == 6 else chunk4_module
        out.append(f"    wire [2:0] pc{ci:02d};")
        out.append(f"    {mod} u{ci:02d} "
                   f"(.x(x[{hi-1}:{lo}]), .w(w[{hi-1}:{lo}]), .pc(pc{ci:02d}));")
    pc_terms = " + ".join(f"pc{ci:02d}" for ci in range(len(chunks)))
    out.append(f"    wire [6:0] total = {pc_terms};")
    out.append("    assign y = (total >= threshold);")
    out.append("endmodule")
    return "\n".join(out) + "\n"
