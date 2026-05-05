#!/usr/bin/env python3
# Extract per-module floorplan bboxes from soc_top.def by:
#   1. Parsing the NETS section. Hierarchical net names of the form
#      "u_<module>.<something>" reveal which cells live in which
#      sub-hierarchy, since the connected pins reference flat cell IDs.
#   2. Voting each cell into the module that owns most of its
#      connected hierarchical nets.
#   3. Looking up each cell's placement in the COMPONENTS section.
#   4. Reporting axis-aligned bboxes per module.
#
# Output: paper/figures/src/fig3_floorplan_data.json

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEF = ROOT / "flow/phase3_soc/runs/phase3_soc/final/def/soc_top.def"
OUT = Path(__file__).resolve().parent / "fig3_floorplan_data.json"
DBU = 1000  # DEF UNITS DISTANCE MICRONS 1000 → 1 µm = 1000 dbu
DIE_UM = 1500.0

PREFIXES = ["u_cpu", "u_tile", "u_gpio", "u_xbar"]  # std-cell modules of interest
MACROS = {
    # name: (x_um, y_um, w_um, h_um) — from manual macro placement / LEF
    "u_imem": (50.0,    1033.46, 683.10, 416.54),
    "u_dmem": (783.10,  1052.50, 479.78, 397.50),
}

# ---------------------------------------------------------------------------
# Pass 1: scan NETS to vote each cell into a module by net-prefix majority.
# ---------------------------------------------------------------------------
HIER_NET = re.compile(r'^\s+-\s+(u_[a-z]+)\.[^\s(]+(.+)$')
PIN_TUP  = re.compile(r'\(\s*([^\s)]+)\s+[^\s)]+\s*\)')

# A cell may appear in many nets (each pin → one net). Vote by module
# across all nets that touch that cell.
votes = defaultdict(Counter)  # cell_id -> Counter of module
print("Scanning NETS section...")
in_nets = False
processed = 0
with open(DEF) as f:
    for line in f:
        if line.startswith("NETS"):
            in_nets = True
            continue
        if line.startswith("END NETS"):
            break
        if not in_nets:
            continue
        m = HIER_NET.match(line)
        if not m:
            continue
        module = m.group(1)
        if module not in PREFIXES:
            continue
        # Collect pins on this line; physical routing continues on
        # subsequent lines starting with "  + ROUTED" or "  NEW", which
        # we don't need.
        for pm in PIN_TUP.finditer(line):
            cell = pm.group(1)
            # Skip macro-pin antenna patterns and DEF-syntax tokens
            if cell == "PIN" or cell.startswith("ANTENNA_"):
                continue
            votes[cell][module] += 1
        processed += 1
        if processed % 2000 == 0:
            print(f"  {processed} hierarchical nets parsed, "
                  f"{len(votes)} unique cells")
print(f"  -> {len(votes)} cells with at least one hierarchical-net vote")

# Resolve each cell's module by majority of votes; require a clear winner.
cell_module = {}
for cell, ctr in votes.items():
    (mod1, n1), *rest = ctr.most_common(2)
    if rest and rest[0][1] >= n1:  # tie -> ambiguous, drop
        continue
    cell_module[cell] = mod1
print(f"  {len(cell_module)} cells assigned to a unique module")

# ---------------------------------------------------------------------------
# Pass 2: scan COMPONENTS to get each cell's placement, then compute
# quantile bboxes (10-90 percentile) per module so a few outlier cells
# don't make a module's footprint overlap its neighbours visually.
# ---------------------------------------------------------------------------
COMP = re.compile(
    r'^\s+-\s+(\S+)\s+(\S+)\s+\+\s+(?:PLACED|FIXED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)'
)
positions = {p: [] for p in PREFIXES}    # list of (x, y) per module
cell_count = {p: 0 for p in PREFIXES}
print("Scanning COMPONENTS section...")
in_comp = False
total_cells = 0
with open(DEF) as f:
    for line in f:
        if line.startswith("COMPONENTS"):
            in_comp = True
            continue
        if line.startswith("END COMPONENTS"):
            break
        if not in_comp:
            continue
        m = COMP.match(line)
        if not m:
            continue
        cell = m.group(1)
        x_um = int(m.group(3)) / DBU
        y_um = int(m.group(4)) / DBU
        total_cells += 1
        mod = cell_module.get(cell)
        if mod is None:
            continue
        positions[mod].append((x_um, y_um))
        cell_count[mod] += 1
print(f"  {total_cells} total cells; assigned per module: {cell_count}")

# Helper: percentile of a sorted list
def quantile(sorted_xs, q):
    if not sorted_xs:
        return None
    k = max(0, min(len(sorted_xs) - 1, int(round(q * (len(sorted_xs) - 1)))))
    return sorted_xs[k]

# Build full bboxes (extreme) AND quantile bboxes (10-90 percentile core).
zones_full = {}
zones_core = {}
for mod, pts in positions.items():
    if not pts:
        continue
    xs = sorted(p[0] for p in pts)
    ys = sorted(p[1] for p in pts)
    zones_full[mod] = (xs[0], ys[0], xs[-1], ys[-1])
    zones_core[mod] = (quantile(xs, 0.05), quantile(ys, 0.05),
                       quantile(xs, 0.95), quantile(ys, 0.95))

# ---------------------------------------------------------------------------
# Build the JSON output.
# ---------------------------------------------------------------------------
result = {
    "die": {"w_um": DIE_UM, "h_um": DIE_UM},
    "macros": {},
    "stdcell_modules": {},
    "cell_counts": cell_count,
    "extraction_method":
        "Per-cell module assignment by majority-vote of the cells "
        "hierarchical NET prefixes (u_cpu/u_tile/u_gpio/u_xbar). "
        "Bounding boxes are min/max of placed-cell origins; padded by 4 µm.",
}
for name, (x, y, w, h) in MACROS.items():
    result["macros"][name] = {
        "xmin": x, "ymin": y, "xmax": x + w, "ymax": y + h,
        "w": w, "h": h,
    }
PAD = 4.0
for mod in PREFIXES:
    if mod not in zones_core:
        continue
    cxmin, cymin, cxmax, cymax = zones_core[mod]
    fxmin, fymin, fxmax, fymax = zones_full[mod]
    result["stdcell_modules"][mod] = {
        "core_bbox": {
            "xmin": round(cxmin - PAD, 2),
            "ymin": round(cymin - PAD, 2),
            "xmax": round(cxmax + PAD, 2),
            "ymax": round(cymax + PAD, 2),
            "w":    round(cxmax - cxmin + 2 * PAD, 2),
            "h":    round(cymax - cymin + 2 * PAD, 2),
        },
        "full_bbox": {
            "xmin": round(fxmin, 2),
            "ymin": round(fymin, 2),
            "xmax": round(fxmax, 2),
            "ymax": round(fymax, 2),
        },
        "n_cells": cell_count[mod],
    }

with open(OUT, "w") as f:
    json.dump(result, f, indent=2)
print(f"Wrote {OUT}")
print(json.dumps(result, indent=2))
