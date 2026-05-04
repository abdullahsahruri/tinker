#!/usr/bin/env python3
"""bucket_soc_cells.py — assign each post-route SoC standard-cell instance
to a top-level hierarchical bucket by inspecting its output-pin net name.

Yosys flattens hierarchy at synth time, but it preserves hierarchical wire
names (escaped identifiers like `\\u_imem.foo`) when the wire was
introduced inside a sub-module. The cell's flat numeric name (e.g.,
`_62651_`) tells us nothing about its origin, but its output-pin net
name does.

Buckets:
  u_cpu  — picorv32_wrapper hierarchy (incl. picorv32_wb internals)
  u_xbar — wb_interconnect (combinational, mostly zero flops)
  u_imem — wb_imem (storage; expected near-zero in this baseline because
           Yosys constant-propagated the all-zero `INIT_HEX=""` IMEM)
  u_dmem — wb_dmem
  u_tile — wb_tile_wrapper (wraps tile_tlg_ld)
  u_gpio — wb_gpio
  shared — top-level glue + Yosys-internal nets + OpenROAD
           timing-repair buffers (`net*` named) + clock tree

Output:
  results/phase3/power/buckets/<bucket>.cells   — one cell name per line
  results/phase3/power/buckets/summary.json     — per-bucket counts
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NETLIST = ROOT / "flow/phase3_soc/runs/phase3_soc/final/nl/soc_top.nl.v"
OUT_DIR = ROOT / "results/phase3/power/buckets"
OUT_DIR.mkdir(parents=True, exist_ok=True)

BUCKETS = ["u_cpu", "u_xbar", "u_imem", "u_dmem", "u_tile", "u_gpio", "shared"]


def parse_cells(text):
    """Yield (cell_inst, cell_type, output_net, [all_nets]) tuples.

    Captures both std cells (`sky130_fd_sc_hd__*`) and macros
    (`sky130_sram_*`). For macros, the instance name itself carries the
    hierarchical bucket (`\\u_imem.u_macro` / `\\u_dmem.u_macro`); the
    output_net is set to a synthetic value so the bucket_for_net pass
    routes the macro to the matching IMEM/DMEM bucket.
    """
    cell_re = re.compile(
        r"^\s+sky130_(?:fd_sc_hd__|sram_)(\S+?)\s+(\S+)\s*\(", re.MULTILINE
    )
    pos = 0
    while True:
        m = cell_re.search(text, pos)
        if not m:
            break
        cell_type = m.group(1)
        inst_name = m.group(2)
        depth = 0
        i = m.end() - 1
        end = -1
        while i < len(text):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
            i += 1
        if end < 0:
            break
        body = text[m.end() : end]
        pos = end + 1
        if cell_type.startswith("diode"):
            continue
        if cell_type.startswith(("fill", "tapvgnd", "tap", "decap", "endcap")):
            continue
        # All pin nets, in order of appearance.
        all_nets = [n.strip() for n in re.findall(r"\.[A-Z0-9]+\(([^)]+)\)", body)]
        # For OpenRAM macros (`2kbyte_1rw1r_32x512_8` etc.), use the
        # instance name itself to derive the hierarchy bucket. Yield a
        # synthetic "output_net" that carries the macro's hierarchy
        # prefix so bucket_for_net classifies it correctly.
        if cell_type.endswith("byte_1rw1r_32x512_8") or cell_type.endswith(
            "byte_1rw1r_32x256_8"
        ):
            yield inst_name, cell_type, inst_name, all_nets
            continue
        # Output pin: prefer .X, then .Q, then .Y.
        output_net = None
        for pin_re in (
            r"\.X\(([^)]+)\)",
            r"\.Q\(([^)]+)\)",
            r"\.Y\(([^)]+)\)",
        ):
            mp = re.search(pin_re, body)
            if mp:
                output_net = mp.group(1).strip()
                break
        if output_net is None:
            continue
        yield inst_name, cell_type, output_net, all_nets


def bucket_for_net(net):
    """Return a bucket name for a single net; None if the net carries
    no hierarchy info (Yosys-renamed `_NNNNN_`, OpenROAD `net*`, top-
    level signal, clock tree)."""
    if net.startswith("\\u_"):
        prefix = net.split(".", 1)[0].lstrip("\\").rstrip()
        if prefix in BUCKETS[:-1]:
            return prefix
    return None


def is_clock_net(net):
    """True if this net belongs to the CTS-built clock tree."""
    n = net.lstrip("\\").strip()
    return n.startswith("clknet") or n == "clk" or "_clk" in n


def main():
    text = NETLIST.read_text()
    cells = list(parse_cells(text))
    bucket_cells = {b: [] for b in BUCKETS + ["clock_tree"]}

    # Two-pass classification:
    # Pass 1 — output-net hierarchy.
    # Pass 2 — for cells whose output didn't carry hierarchy, look at
    #          ALL connected nets (inputs + output). If any pin connects
    #          to a hierarchical wire, attribute the cell to that
    #          hierarchy; on tie, prefer the most-frequent prefix.
    #          If a cell sits on the clock tree (outputs to a clk net,
    #          or its only non-clock input is also clock-named) classify
    #          it as `clock_tree`.
    n_total = 0
    for inst, ctype, out_net, all_nets in cells:
        n_total += 1
        # Strip Verilog escape from hierarchical instance names (`\u_imem.u_macro`
        # → `u_imem.u_macro`). OpenSTA's get_cells uses literal names without
        # the backslash escape.
        if inst.startswith("\\"):
            inst = inst.lstrip("\\").rstrip()
        # Clock-tree first: clk-named output → clock_tree.
        if is_clock_net(out_net):
            bucket_cells["clock_tree"].append(inst)
            continue
        # Pass 1: hierarchical output net wins.
        b = bucket_for_net(out_net)
        if b:
            bucket_cells[b].append(inst)
            continue
        # Pass 2: scan all pin nets and pick the most-frequent prefix.
        votes = {}
        for n in all_nets:
            v = bucket_for_net(n)
            if v:
                votes[v] = votes.get(v, 0) + 1
        if votes:
            winner = max(votes.items(), key=lambda kv: kv[1])[0]
            bucket_cells[winner].append(inst)
        else:
            bucket_cells["shared"].append(inst)

    summary = {"total_power_relevant_cells": n_total, "buckets": {}}
    for b in BUCKETS + ["clock_tree"]:
        path = OUT_DIR / f"{b}.cells"
        names = bucket_cells[b]
        path.write_text("\n".join(names) + ("\n" if names else ""))
        summary["buckets"][b] = len(names)
        print(f"{b:11s}: {len(names):>7d} cells")
    print(f"{'TOTAL':11s}: {n_total:>7d} cells")
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    sys.exit(main())
