#!/usr/bin/env python3
# Render the SoC GDS into paper/figures/src/fig3_base.png with metal
# layers suppressed so std-cell texture is visible.
import sys
from pathlib import Path

import pya  # KLayout's Python binding (available when invoked via `klayout -b -r`)

ROOT = Path(__file__).resolve().parents[3]
GDS  = ROOT / "flow/phase3_soc/runs/phase3_soc/final/gds/soc_top.gds"
LYP  = Path(__file__).parent / "fig3_clean.lyp"
OUT  = Path(__file__).parent / "fig3_base.png"

ly = pya.Layout()
ly.read(str(GDS))
top = ly.top_cell()
print(f"top={top.name} bbox={top.bbox()}", file=sys.stderr)

view = pya.LayoutView()
view.show_layout(ly, False)
view.add_missing_layers()
view.load_layer_props(str(LYP))
view.max_hier()
view.zoom_fit()
view.set_config("background-color", "#ffffff")
view.set_config("text-visible", "false")
view.save_image(str(OUT), 2000, 2000)
print(f"wrote {OUT}", file=sys.stderr)
