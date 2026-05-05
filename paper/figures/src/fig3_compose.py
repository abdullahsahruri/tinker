#!/usr/bin/env python3
# Compose paper/figures/fig3_layout.pdf:
#   - Base: fig3_base.png (KLayout render of soc_top.gds with metals
#     suppressed)
#   - Overlay: extracted-bbox rectangles for IMEM, DMEM, PicoRV32,
#     TLG-mapped tile, GPIO + Wishbone-fabric annotation, scale bar,
#     die-size label.
import json
import os
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

mpl.rcParams.update({
    "font.family": "serif",
    "font.serif": ["STIXGeneral", "Liberation Serif", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})

NAVY      = "#1F3A5F"
RED       = "#A83232"
RED_FILL  = "#F5DCDC"
NAVY_FILL = "#D6DEEC"
GRAY_FILL = "#F2F2F2"

HERE = Path(__file__).resolve().parent
BASE_PNG = HERE / "fig3_base.png"
DATA_JSON = HERE / "fig3_floorplan_data.json"
POS_JSON = HERE / "fig3_cell_positions.json"
OUT_PDF = HERE.parent / "fig3_layout.pdf"

with open(DATA_JSON) as f:
    fp = json.load(f)
with open(POS_JSON) as f:
    cell_positions = json.load(f)
DIE_W = fp["die"]["w_um"]
DIE_H = fp["die"]["h_um"]

fig, ax = plt.subplots(figsize=(3.4, 3.4))
ax.set_xlim(0, DIE_W)
ax.set_ylim(0, DIE_H)
ax.set_aspect("equal")
ax.set_xticks([])
ax.set_yticks([])
for s in ("top", "right", "bottom", "left"):
    ax.spines[s].set_visible(False)

# --- Base: real layout PNG ---------------------------------------------
import matplotlib.image as mpimg
img = mpimg.imread(str(BASE_PNG))
ax.imshow(img, extent=(0, DIE_W, 0, DIE_H), zorder=0,
          interpolation="bilinear", alpha=0.55)

# --- Macros: navy outline, no fill (the macros are visible in base) ----
for key, label, dims_label in [
    ("u_imem", "IMEM", "683 × 417 µm"),
    ("u_dmem", "DMEM", "480 × 398 µm"),
]:
    m = fp["macros"][key]
    x, y, w, h = m["xmin"], m["ymin"], m["w"], m["h"]
    ax.add_patch(Rectangle((x, y), w, h, fill=False,
                           edgecolor=NAVY, linewidth=0.9, zorder=2))
    cx, cy = x + w / 2, y + h / 2
    # White-pad label so it reads against the dense bitcell texture
    ax.text(cx, cy + 35, label,
            ha="center", va="center", fontsize=8, color=NAVY,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.20", fc="white",
                      ec=NAVY, lw=0.5), zorder=3)
    ax.text(cx, cy - 35, dims_label,
            ha="center", va="center", fontsize=6.5, color=NAVY,
            bbox=dict(boxstyle="round,pad=0.12", fc="white",
                      ec="none", alpha=0.85), zorder=3)

# --- Std-cell modules: full bbox with semi-transparent fills -----------
sc = fp["stdcell_modules"]


def add_module(name, color_fill, color_edge, lw, ls, fill_alpha,
               label_text, label_color, label_weight="normal",
               use_full=True, label_offset=(0, 0), zorder=2,
               label_zorder=4):
    if name not in sc:
        return None
    bbox = sc[name]["full_bbox" if use_full else "core_bbox"]
    x, y = bbox["xmin"], bbox["ymin"]
    w = bbox["xmax"] - bbox["xmin"]
    h = bbox["ymax"] - bbox["ymin"]
    # Semi-transparent fill
    ax.add_patch(Rectangle((x, y), w, h,
                           facecolor=color_fill, alpha=fill_alpha,
                           edgecolor="none", zorder=zorder - 0.5))
    # Solid outline
    ax.add_patch(Rectangle((x, y), w, h, fill=False,
                           edgecolor=color_edge, linewidth=lw,
                           linestyle=ls, zorder=zorder))
    cx = x + w / 2 + label_offset[0]
    cy = y + h / 2 + label_offset[1]
    ax.text(cx, cy, label_text,
            ha="center", va="center", fontsize=8.5,
            color=label_color, fontweight=label_weight,
            bbox=dict(boxstyle="round,pad=0.22", fc="white",
                      ec=label_color, lw=0.5, alpha=0.95),
            zorder=label_zorder)
    return (x, y, w, h)


# --- Per-module cell scatter: shows ACTUAL placement of each module's
#     cells, since the placer interleaves modules across the same rows.
SCATTER_STYLE = {
    "soc_top_glue": dict(color="#A0A8B5", size=0.50, alpha=0.65,
                         zorder=1.3),  # light gray-navy: glue background
    "u_cpu":        dict(color="#13284A", size=0.85, alpha=0.95,
                         zorder=1.6),  # deep navy — distinct from base
    "u_tile":       dict(color=RED,       size=0.85, alpha=0.95,
                         zorder=1.7),  # red — emphasized
    "u_gpio":       dict(color="#D9831F", size=2.0,  alpha=1.00,
                         zorder=1.8),  # orange (small count, larger marker)
}
for mod, style in SCATTER_STYLE.items():
    pts = cell_positions.get(mod, [])
    if not pts:
        continue
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ax.scatter(xs, ys, s=style["size"], c=style["color"],
               alpha=style["alpha"], marker="s", linewidths=0,
               zorder=style["zorder"])

# --- Bbox outlines on top of the scatter, with labels centered ---------
# TLG-mapped tile — RED HIGHLIGHT, the contribution
add_module("u_tile", RED_FILL, RED, 1.0, "-", 0.18,
           "TLG-mapped tile", RED, label_weight="bold",
           zorder=2.2, label_zorder=4)

# PicoRV32 — full bbox; overlap with u_tile is honestly visible
add_module("u_cpu", NAVY, NAVY, 0.7, (0, (4, 2)), 0.06,
           "PicoRV32", NAVY,
           zorder=2.1, label_zorder=4,
           label_offset=(-180, -50))

# Wishbone fabric & glue: outline only, faint, label below the others
add_module("soc_top_glue",
           NAVY, NAVY, 0.5, (0, (1, 2)), 0.0,
           "Wishbone B4 fabric & glue", NAVY,
           label_offset=(0, -240), zorder=2.0, label_zorder=3.8)

# GPIO — small block; offset label to the side via an arrow
gpio_bbox = sc.get("u_gpio", {}).get("full_bbox")
if gpio_bbox:
    x, y = gpio_bbox["xmin"], gpio_bbox["ymin"]
    w = gpio_bbox["xmax"] - gpio_bbox["xmin"]
    h = gpio_bbox["ymax"] - gpio_bbox["ymin"]
    ax.add_patch(Rectangle((x, y), w, h, fill=False,
                           edgecolor=NAVY, linewidth=0.6,
                           linestyle=(0, (4, 2)), zorder=2))
    ax.add_patch(Rectangle((x, y), w, h,
                           facecolor=NAVY, alpha=0.10,
                           edgecolor="none", zorder=1.5))
    # Leader to a label outside the box
    cx, cy = x + w / 2, y + h / 2
    label_xy = (1280, 880)
    ax.annotate("GPIO",
                xy=(x + w, cy), xytext=label_xy,
                ha="center", va="center", fontsize=7.5,
                color=NAVY,
                bbox=dict(boxstyle="round,pad=0.20", fc="white",
                          ec=NAVY, lw=0.5),
                arrowprops=dict(arrowstyle="-", lw=0.5, color=NAVY),
                zorder=4)

# (Wishbone B4 fabric & glue is now an extracted overlay above.)

# --- Die-size annotation (top-right inset) -----------------------------
ax.text(DIE_W - 20, DIE_H - 20,
        f"die {int(DIE_W)} × {int(DIE_H)} µm",
        ha="right", va="top", fontsize=7, color=NAVY,
        bbox=dict(boxstyle="round,pad=0.25", fc="white",
                  ec=NAVY, lw=0.5, alpha=0.95),
        zorder=5)

# --- Scale bar (bottom-left) -------------------------------------------
SCALE_UM = 200
sx0, sy0 = 60, 60
ax.plot([sx0, sx0 + SCALE_UM], [sy0, sy0],
        color=NAVY, linewidth=1.5, zorder=5)
ax.plot([sx0, sx0], [sy0 - 14, sy0 + 14], color=NAVY, linewidth=0.8, zorder=5)
ax.plot([sx0 + SCALE_UM, sx0 + SCALE_UM], [sy0 - 14, sy0 + 14],
        color=NAVY, linewidth=0.8, zorder=5)
ax.text(sx0 + SCALE_UM / 2, sy0 + 30, f"{SCALE_UM} µm",
        ha="center", va="bottom", fontsize=7, color=NAVY, zorder=5)

# --- Die outline (subtle, navy) ----------------------------------------
ax.add_patch(Rectangle((0, 0), DIE_W, DIE_H, fill=False,
                       edgecolor=NAVY, linewidth=0.8, zorder=2))

plt.tight_layout(pad=0.05)
plt.savefig(OUT_PDF, format="pdf", bbox_inches="tight",
            pad_inches=0.04, facecolor="white", dpi=300)
print(f"wrote {OUT_PDF}")
