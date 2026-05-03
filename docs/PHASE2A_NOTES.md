# Phase 2A — tile generators and functional verification

Session 2A built the four tile variants and verified them in iverilog. No
synthesis. Phase 1 results are unchanged. Session 2B will run the four
tiles through LibreLane.

## Verification summary

```
TILE FUNCTIONAL CHECK [tile_tlg_hc]:     PASS (200/200)
TILE FUNCTIONAL CHECK [tile_tlg_ld]:     PASS (200/200)
TILE FUNCTIONAL CHECK [tile_handopt_hc]: PASS (200/200)
TILE FUNCTIONAL CHECK [tile_handopt_ld]: PASS (200/200)
```

200 random 64-bit input vectors driven into all four DUTs in a single
simulation. The two loadable variants are programmed via cfg writes
(16 weight regs + 16 threshold regs) before vector replay, with the
same (W, t) values that gen_tile.py bakes into the hardcoded variants
(`numpy.random.RandomState(42)`, thresholds = 32 each).

## Module / instance counts (grep, not synthesis)

These are the structural shape of each generated `.v` file before any
synthesis pass — they do **not** correspond to stdcell counts. Session
2B will produce the actual stdcell numbers.

| Tile               | `module` decls | `<name> u…(` instantiations | File LOC |
| ------------------ | -------------: | --------------------------: | -------: |
| `tile_tlg_hc`      | 193            | 192                         | 12 996   |
| `tile_tlg_ld`      | 4              | 27                          |    216   |
| `tile_handopt_hc`  | 17             | 16                          |  1 364   |
| `tile_handopt_ld`  | 2              | 16                          |    158   |

How to read this:

- `tile_tlg_hc` has 1 top + 16 per-neuron + 16×11 per-chunk = **193 modules**;
  the truth tables encode each neuron's weight slice, so chunk modules cannot
  be shared. Instantiation count is 16 (neurons in tile) + 16×11 (chunks per
  neuron) = 192.
- `tile_tlg_ld` has 1 top + 1 generic neuron + 1 generic 6→3 chunk + 1 generic
  4→3 chunk = **4 modules**. The neuron is instantiated 16 times in the top;
  the chunks are instantiated 11 times in the neuron (10×size-6 + 1×size-4).
  Across the file: 16 + 11 = 27 instantiation lines.
- Hardcoded handopt has 16 unique neuron modules (each with `localparam W`).
- Loadable handopt has 1 generic neuron module with `W` / `threshold` ports.

The asymmetry matters for Session 2B: the hardcoded TLG variant ships ~13 kLOC
of Verilog into Yosys and will be the slowest to synthesize. None of this
predicts the post-synthesis cell count, just the pre-synthesis source size.

## Refactor — what moved to `tlg_lib.py`

Shared with Phase 1 (imported by `gen_neuron.py`):

- Constants: `N_INPUTS`, `THRESHOLD`, `CHUNK_SIZE`
- Helpers: `gen_weights`, `w_to_int`, `reference_y`, `chunk_partition`

Phase 1 verified byte-identical after refactor:

```
naive   IDENTICAL  (md5 135663ce4e5e9127919b0d2ccb7844c2)
handopt IDENTICAL  (md5 5c6abca2780614ef810169f6d2101119)
tlg     IDENTICAL  (md5 61676cc27d30c87ec4ac4ca7b2f9a9d3)
```

`gen_neuron.py`'s `emit_tlg_chunk_module` was kept verbatim rather than
replaced by `tlg_lib.emit_tlg_chunk_hc`, because the Phase-1 emitter wraps
the module body with a per-chunk `// chunk N: ... weight=0x...` header
comment that the new (tile-oriented) emitter does not. Strict byte-identical
output for Phase 1 was the safer choice; the duplicated `case`-statement body
is small and stable.

New, used by `gen_tile.py`:

- `gen_weight_set(seed, n_neurons)` — deterministic 16-neuron weight matrix
- `emit_tlg_chunk_hc(name, size, w_int)` — hardcoded 6→3 / 4→3 truth table
- `emit_tlg_chunk_ld(name, size)` — generic XNOR + popcount truth table
- `emit_handopt_neuron(name, w_int=…)` — adder tree, with W as either a
  `localparam` (hardcoded) or a port (loadable)
- `emit_tlg_neuron_hc(name, w_bits, prefix)` — neuron + per-chunk modules
- `emit_tlg_neuron_ld(name, chunk6_module, chunk4_module)` — neuron that
  delegates to shared chunk modules

## Loadable vs hardcoded — structural deltas beyond "add registers"

The loadable variants are not a trivial wrapper around the hardcoded
neuron with the constants replaced by register reads. Specifically:

1. **TLG chunk truth-table changes shape.** The hardcoded chunk encodes
   `popcount(x XNOR W_const)` as a 6→3 (or 4→3) function of the 6 input
   bits. The loadable chunk computes `m = x XNOR w_runtime` and then
   encodes `popcount(m)` — also a 6→3 truth table, but the case statement
   indexes `m`, not `x`. The two truth tables compute logically equivalent
   things, but ABC sees them as different mapping problems and will produce
   different netlists. This is the intended outcome — the loadable variant
   cannot fold the weight into the truth table because the weight is no
   longer constant — and it is what gives the loadable variants different
   PPA in Session 2B.

2. **Handopt loadable threshold.** The hardcoded handopt neuron uses
   `assign y = (total >= 7'd32);` (constant comparator). The loadable form
   uses `assign y = (total >= threshold);` where `threshold` is a port.
   Yosys cannot fold the comparator's right-hand side, so the comparator
   must be implemented in full. Same change applies to the loadable TLG
   neuron's final compare.

3. **Configuration register file.** Both loadable tiles add a 16×64-bit
   weight bank + 16×7-bit threshold bank with a write-only port (no read
   from the cfg side; reads come from the neuron logic via the `w_reg[i]`
   / `t_reg[i]` array reads). The address layout is `cfg_addr[5:4]==00`
   for weights, `==01` for thresholds, low 4 bits index the neuron.

4. **Weight propagation latency.** Cfg writes are sampled at the rising
   edge; neuron logic sees the new weights one clock later. The testbench
   accounts for this by inserting a dead cycle between the last cfg write
   and the first vector.

## Pipeline timing — spec ambiguity resolution

The spec says both:

- "x_in registered at the tile boundary … combinational path from x_in
  registered → y_out registered" — implies **two** flops (one input,
  one output), so the combinational logic sits between two register
  endpoints.
- "tile evaluates in 1 cycle once inputs are loaded. y_valid asserts
  the cycle after x_valid" — implies a **1-cycle** latency from x_valid
  to y_valid.

These are not jointly satisfiable. Resolved as: **2 flops, 2-cycle latency
from x_valid to y_valid**. The "1 cycle" is interpreted as the comb path
between the two register endpoints; "the cycle after x_valid" is read as
informal phrasing for "after the x_valid pulse propagates through the
pipeline".

Concretely, the pipeline is:

```
   x_valid:  __|""|________
   v_d1   :  ____|""|______
   v_d2   :  ______|""|____  ← y_valid
   x_in   : XX< v >XXXXXXXX
   x_reg  : XXXXX< v >XXXXX
   y_comb : XXXXXXX< y >XXX
   y_out_r: XXXXXXXXX< y >X  ← y_out
```

Reasoning: registering both ends gives clean STA boundaries for Session
2B. Without the output flop, OpenSTA would constrain a primary-output
path with an output-delay assumption, and we already saw in Phase 1 that
combinational virtual-clock SDC is fiddly. Two flops is the more
synthesizable, easier-to-measure design and matches the literal reading
of "x_in registered → y_out registered". Testbench knows to wait 2
cycles and reports PASS on all four.

## Reproduction

```bash
source scripts/env.sh

# (Re)generate the tile RTL and TB data:
python scripts/gen_tile.py tlg     --hardcoded --out rtl/tile_tlg_hc/
python scripts/gen_tile.py tlg     --loadable  --out rtl/tile_tlg_ld/
python scripts/gen_tile.py handopt --hardcoded --out rtl/tile_handopt_hc/
python scripts/gen_tile.py handopt --loadable  --out rtl/tile_handopt_ld/
python scripts/gen_tile_tb_data.py

# Compile + run the unified testbench:
scripts/run_tile_tb.sh
```

Expected output: 4 `PASS (200/200)` lines.
