#!/usr/bin/env python3
# Hierarchical activity-aware power decomposition (Fig. 4).
# Single horizontal stacked bar at max_ff_n40C_1v95 (47.21 mW) plus a
# two-column legend giving each bucket's mW/percentage.
# Output: fig4_power_breakdown.pdf (vector, IEEE column width).

import os
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

mpl.rcParams.update({
    "font.family": "serif",
    "font.serif": ["STIXGeneral", "Liberation Serif", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "axes.linewidth": 0.6,
})

NAVY     = "#1F3A5F"
RED      = "#A83232"
NAVY2    = "#34547A"
NAVY3    = "#4A6E96"
NAVY4    = "#6B8AAE"
NAVY5    = "#8FA6C2"
GRAY1    = "#B7BDC6"
GRAY2    = "#CDD2D8"

# Buckets in plotting order (left -> right within the stacked bar):
# (name, value mW, fill color, inside-text color, optional in-bar label)
buckets = [
    ("Clock",  15.10, NAVY,  "white", "Clock"),
    ("Tile",   11.47, RED,   "white", "Tile"),
    ("CPU",     7.71, NAVY2, "white", "CPU"),
    ("IMEM",    5.56, NAVY3, "white", "IMEM"),
    ("DMEM",    3.85, NAVY4, "white", "DMEM"),
    ("Shared",  1.24, NAVY5, NAVY,    None),
    ("GPIO",    0.30, GRAY1, NAVY,    None),
    ("Other",   1.98, GRAY2, NAVY,    None),
]
TOTAL = 47.21
assert abs(sum(v for _, v, _, _, _ in buckets) - TOTAL) < 0.05

fig = plt.figure(figsize=(3.4, 2.20))

# Two stacked axes: bar (top), legend (bottom). Generous gap so the
# bar's "Power (mW)" xlabel does not collide with legend entries.
ax  = fig.add_axes([0.06, 0.74, 0.92, 0.20])  # bar
axl = fig.add_axes([0.04, 0.02, 0.94, 0.46])  # legend
axl.set_xlim(0, 1); axl.set_ylim(0, 1); axl.axis("off")

# --- Bar -----------------------------------------------------------------
bar_y = 0.0
bar_h = 0.55
left = 0.0
for name, v, color, txtcolor, in_label in buckets:
    ax.barh(bar_y, v, left=left, height=bar_h, color=color,
            edgecolor=NAVY, linewidth=0.5)
    if in_label is not None:
        ax.text(left + v / 2, bar_y, in_label,
                ha="center", va="center",
                fontsize=6.8, color=txtcolor)
    left += v

# Tile segment outline emphasis (slightly heavier red border).
clock_w = buckets[0][1]
tile_w  = buckets[1][1]
ax.add_patch(Rectangle((clock_w, bar_y - bar_h / 2), tile_w, bar_h,
                       fill=False, edgecolor=RED, linewidth=1.0))

ax.set_xlim(-0.3, TOTAL + 0.3)
ax.set_xticks([0, 10, 20, 30, 40, TOTAL])
ax.set_xticklabels(["0", "10", "20", "30", "40", f"{TOTAL:.2f}"],
                   fontsize=6.5, color=NAVY)
ax.set_xlabel("Power (mW)", fontsize=7.5, color=NAVY, labelpad=2)
ax.tick_params(axis="x", which="major", width=0.5, length=2.5,
               color=NAVY, labelcolor=NAVY, pad=2)
ax.set_yticks([])
ax.set_ylim(-bar_h / 2 - 0.05, bar_h / 2 + 0.05)
ax.xaxis.grid(True, which="major", linestyle=":", linewidth=0.4,
              color="#BBBBBB")
ax.set_axisbelow(True)
for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color(NAVY)
ax.spines["bottom"].set_linewidth(0.6)

# --- Legend (two columns of four entries) -------------------------------
# Order entries by descending mW so the eye sweeps top-to-bottom.
entries = sorted([(n, v, c) for n, v, c, *_ in buckets],
                 key=lambda r: -r[1])

# Layout: 4 rows x 2 cols. Column 0: rows 0..3. Column 1: rows 4..7.
n_rows = 4
sw_w, sw_h = 0.022, 0.16     # swatch width/height (axes coords)
col_x = [0.02, 0.51]
row_y = [0.78, 0.55, 0.32, 0.09]

for i, (name, v, color) in enumerate(entries):
    col, row = divmod(i, n_rows)
    x = col_x[col]
    y = row_y[row]
    is_tile = (name == "Tile")
    txt_color  = RED if is_tile else NAVY
    weight     = "bold" if is_tile else "normal"
    border     = RED if is_tile else NAVY
    border_w   = 0.9 if is_tile else 0.4
    axl.add_patch(Rectangle((x, y), sw_w, sw_h,
                            facecolor=color, edgecolor=border,
                            linewidth=border_w))
    pct = 100.0 * v / TOTAL
    axl.text(x + sw_w + 0.012, y + sw_h / 2,
             f"{name}",
             ha="left", va="center",
             fontsize=6.5, color=txt_color, fontweight=weight)
    axl.text(x + sw_w + 0.13, y + sw_h / 2,
             f"{v:5.2f} mW  ({pct:4.1f}%)",
             ha="left", va="center",
             fontsize=6.2, color=txt_color, fontweight=weight,
             family="monospace")

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fig4_power_breakdown.pdf")
plt.savefig(out_path, format="pdf", bbox_inches="tight", pad_inches=0.04)
print(f"wrote {out_path}")
