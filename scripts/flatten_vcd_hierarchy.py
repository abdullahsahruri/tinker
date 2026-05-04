#!/usr/bin/env python3
"""flatten_vcd_hierarchy.py — rewrite a VCD so signals below a target scope
appear as flat-named wires *at* the target scope.

Why: OpenSTA's `read_vcd -scope <s>` matches VCD-hierarchy nesting against
the loaded design's instance tree. After Yosys flatten + LibreLane P&R the
SoC is one flat module (`soc_top`); its hierarchical wires (`u_cpu.u_core.
mem_addr[2]` etc.) are *literal* dotted-name wires, not nested instances.
So an unmodified iverilog VCD only annotates the chip-pin boundary (here
18 pins).

Fix: post-process the VCD to relocate every $var declaration below
`<src_scope>` up into `<src_scope>` itself, prefixing the variable's
reference name with the dotted path it came from. Value-change records
reference vars by short identifier, so they need no rewriting; only the
$scope/$var/$upscope header structure changes.

Usage:
  flatten_vcd_hierarchy.py <input.vcd> <output.vcd> --src-scope tb_soc_bnn.dut

After flattening, OpenSTA can be invoked as:
  read_vcd -scope tb_soc_bnn/dut <flat.vcd>
and every signal that was originally `tb_soc_bnn.dut.u_X.foo[N]` will be
visible to the matcher as a flat name `u_X.foo[N]` at scope
`tb_soc_bnn.dut` — which lines up with the netlist's escaped-identifier
wire of the same name.
"""
import argparse
import re
import sys
import time
from pathlib import Path


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument(
        "--src-scope",
        required=True,
        help="VCD scope path (dot-separated) below which to flatten "
        "(e.g., tb_soc_bnn.dut).",
    )
    return ap.parse_args()


def main():
    args = parse_args()
    src_path = args.src_scope.split(".")
    src_in = Path(args.input)
    src_out = Path(args.output)

    fp_in = src_in.open("r", buffering=4 * 1024 * 1024)
    fp_out = src_out.open("w", buffering=4 * 1024 * 1024)

    # Pass 1 — read the header (until $enddefinitions). Track scope stack.
    # For every $var inside a sub-scope of src_scope, rewrite its reference
    # name to <relative_path>.<orig_name>; emit it at src_scope level.
    # Drop $scope and $upscope tokens for sub-scopes of src_scope.
    scope_stack = []
    in_var_block = True
    n_vars_total = 0
    n_vars_relocated = 0
    # Buffer the header so we can re-emit it cleanly.
    header_lines = []
    t0 = time.time()
    for line in fp_in:
        s = line.strip()
        if not in_var_block:
            # Should not happen — we exit pass 1 at $enddefinitions.
            break
        if s.startswith("$scope"):
            # $scope <type> <name> $end
            toks = s.split()
            scope_name = toks[2]
            scope_stack.append(scope_name)
            below_src = (
                len(scope_stack) > len(src_path)
                and scope_stack[: len(src_path)] == src_path
            )
            at_src_or_above = (
                len(scope_stack) <= len(src_path)
                and scope_stack == src_path[: len(scope_stack)]
            )
            if at_src_or_above:
                # Keep the scope line; we'll re-emit nothing for sub-scopes.
                header_lines.append(line)
            elif below_src:
                # Drop this $scope line — we're flattening into src_scope.
                pass
            else:
                # Off-tree: keep as-is.
                header_lines.append(line)
            continue
        if s.startswith("$upscope"):
            below_src = (
                len(scope_stack) > len(src_path)
                and scope_stack[: len(src_path)] == src_path
            )
            scope_stack.pop()
            at_src_or_above = (
                len(scope_stack) < len(src_path)
                and scope_stack == src_path[: len(scope_stack)]
            )
            if below_src:
                # Dropped scope. Drop its upscope too.
                pass
            else:
                header_lines.append(line)
            continue
        if s.startswith("$var"):
            n_vars_total += 1
            # $var <type> <width> <id> <name> [<bit-range>] $end
            toks = s.split()
            # last token is $end; before that may be a [N] or [N:M] bit-range.
            if toks[-1] != "$end":
                header_lines.append(line)
                continue
            below_src = (
                len(scope_stack) > len(src_path)
                and scope_stack[: len(src_path)] == src_path
            )
            if below_src:
                # Reconstruct relative path.
                rel_path = scope_stack[len(src_path) :]
                # toks[4] is the variable name (no whitespace inside an
                # identifier per Verilog spec). Possible bit-range comes
                # after as toks[5] or so. Find the boundary by inspecting:
                # the var name is toks[4]; if toks[5] starts with '[' it's
                # the range; everything else up to $end is bit-range tokens.
                var_type = toks[1]
                width = toks[2]
                ident = toks[3]
                name = toks[4]
                # rest before $end:
                rest = toks[5:-1]
                # Build new name with hierarchy prefix dotted in.
                new_name = ".".join(rel_path + [name])
                rest_str = (" " + " ".join(rest)) if rest else ""
                new_line = f"$var {var_type} {width} {ident} {new_name}{rest_str} $end\n"
                header_lines.append(new_line)
                n_vars_relocated += 1
            else:
                header_lines.append(line)
            continue
        if s == "$enddefinitions $end":
            header_lines.append(line)
            in_var_block = False
            break
        # Pre-header / non-var lines (date, version, timescale, etc.).
        header_lines.append(line)

    # Emit header.
    fp_out.writelines(header_lines)

    # Pass 2 — copy the value-change body verbatim.
    # The VCD body uses short identifiers (not names) so no rewrite needed.
    chunk_size = 16 * 1024 * 1024
    while True:
        chunk = fp_in.read(chunk_size)
        if not chunk:
            break
        fp_out.write(chunk)

    fp_in.close()
    fp_out.close()

    print(
        f"flatten_vcd: {n_vars_total} vars total, "
        f"{n_vars_relocated} relocated to scope {args.src_scope!r} "
        f"in {time.time() - t0:.1f}s",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
