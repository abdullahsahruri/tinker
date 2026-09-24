#!/usr/bin/env python3
# Hierarchical activity-aware power decomposition (Fig. 4).
# Side-by-side comparison: regfile-IMEM/DMEM baseline (106.06 mW) vs
# OpenRAM-macro configuration (47.21 mW). The same TLG-tile RTL is the
# red bucket in both bars, so the eye reads the share-shift directly.
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

NAVY  = "#1F3A5F"
RED   = "#A83232"
NAVY2 = "#34547A"
NAVY3 = "#4A6E96"
NAVY4 = "#6B8AAE"
NAVY5 = "#8FA6C2"
GRAY  = "#B7BDC6"
GRAY2 = "#E4E7EB"

# Bucket order (left -> right inside each bar). Same order in both bars.
ORDER = ["Clock", "Tile", "CPU", "IMEM", "DMEM", "Shared", "GPIO", "Other"]
COLOR = {
    "Clock":  NAVY,
    "Tile":   RED,
    "CPU":    NAVY2,
    "IMEM":   NAVY3,
    "DMEM":   NAVY4,
    "Shared": NAVY5,
    "GPIO":   GRAY,
    "Other":  GRAY2,
}

# OpenRAM (this work, headline configuration)
OPENRAM = {
    "Clock":  15.10, "Tile":   11.47, "CPU":    7.71,
    "IMEM":    5.56, "DMEM":    3.85, "Shared": 1.24,
    "GPIO":    0.30, "Other":   1.98,
}
# Baseline (regfile IMEM/DMEM); same Tile RTL. From comparison_baseline_vs_openram.csv.
# IMEM=0 (constant-propagated); GPIO+xbar combined into Shared/GPIO; remainder -> Other.
BASELINE = {
    "Clock":  42.98, "Tile":   11.47, "CPU":    7.78,
    "IMEM":    0.00, "DMEM":   38.58, "Shared": 0.00,
    "GPIO":    0.30, "Other":   4.95,
}
TOTAL_OR  = 47.21
TOTAL_BL  = 106.06
assert abs(sum(OPENRAM.values())  - TOTAL_OR) < 0.05
assert abs(sum(BASELINE.values()) - TOTAL_BL) < 0.05

fig, ax = plt.subplots(figsize=(3.4, 2.10))

bar_h = 0.42
y_BL  = 1.0
y_OR  = 0.0


def draw_stack(y, totals, total, label):
    left = 0.0
    for name in ORDER:
        v = totals[name]
        if v <= 0:
            continue
        c = COLOR[name]
        ax.barh(y, v, left=left, height=bar_h, color=c,
                edgecolor=NAVY, linewidth=0.5)
        left += v
    # Tile callout: extra-emphasized red border on top of the Tile segment
    cum = 0.0
    for name in ORDER:
        v = totals[name]
        if name == "Tile" and v > 0:
            ax.add_patch(Rectangle((cum, y - bar_h / 2), v, bar_h,
                                   fill=False, edgecolor=RED, linewidth=1.0))
            tile_pct = 100.0 * v / total
            tile_cx  = cum + v / 2
            ax.annotate(f"{tile_pct:.1f}%",
                        xy=(tile_cx, y),
                        xytext=(tile_cx, y),
                        ha="center", va="center",
                        fontsize=7.0, color="white", fontweight="bold")
            break
        cum += v
    # Total annotation at the right end of the bar
    ax.text(total + 1.5, y, f"total {total:.2f} mW",
            ha="left", va="center",
            fontsize=6.5, color=NAVY)
    # Bar label on the left
    ax.text(-2.5, y, label, ha="right", va="center",
            fontsize=7.0, color=NAVY)


draw_stack(y_BL, BASELINE, TOTAL_BL,
           "regfile baseline\n(pre-OpenRAM)")
draw_stack(y_OR, OPENRAM,  TOTAL_OR,
           "OpenRAM macros\n(this work)")

# Tile-share callout connecting the two Tile segments visually.
# Both Tile segments span [Clock, Clock+Tile] horizontally.
bl_tile_cx = BASELINE["Clock"] + BASELINE["Tile"] / 2  # ~48.72 mW
or_tile_cx = OPENRAM["Clock"]  + OPENRAM["Tile"]  / 2  # ~20.84 mW
# Drop a thin red bracket over the Tile segments to signal "same RTL".
ax.annotate("",
            xy=(bl_tile_cx, y_BL - bar_h / 2 - 0.04),
            xytext=(or_tile_cx, y_OR + bar_h / 2 + 0.04),
            arrowprops=dict(arrowstyle="-", lw=0.5, color=RED,
                            linestyle=(0, (1.5, 1.5))))
ax.text((bl_tile_cx + or_tile_cx) / 2 - 1.5, (y_BL + y_OR) / 2,
        "same Tile RTL\n(11.47 mW)",
        ha="right", va="center",
        fontsize=5.5, color=RED, fontweight="bold")

# X axis
xmax = TOTAL_BL + 8
ax.set_xlim(-3.5, xmax)
ax.set_xticks([0, 20, 40, 60, 80, 100])
ax.set_xticklabels(["0", "20", "40", "60", "80", "100"],
                   fontsize=6.5, color=NAVY)
ax.set_xlabel("Power (mW) at max_ff_n40C_1v95",
              fontsize=7.0, color=NAVY, labelpad=2)
ax.tick_params(axis="x", which="major", width=0.5, length=2.5,
               color=NAVY, labelcolor=NAVY, pad=2)

# Y axis: hide
ax.set_yticks([])
ax.set_ylim(-0.55, 1.65)

# Light grid at major x-ticks only
ax.xaxis.grid(True, which="major", linestyle=":", linewidth=0.4,
              color="#BBBBBB")
ax.set_axisbelow(True)

for s in ("top", "right", "left"):
    ax.spines[s].set_visible(False)
ax.spines["bottom"].set_color(NAVY)
ax.spines["bottom"].set_linewidth(0.6)

# Legend (tight, positioned in the upper-right margin)
legend_entries = [
    ("Clock",  NAVY),
    ("Tile",   RED),
    ("CPU",    NAVY2),
    ("IMEM",   NAVY3),
    ("DMEM",   NAVY4),
    ("Shared", NAVY5),
    ("GPIO",   GRAY),
    ("Other",  GRAY2),
]
# Place legend below the bars in two rows.
legend_y = -0.42
sw_w, sw_h = 1.6, 0.10
legend_xs = [0, 14, 28, 42, 56, 70, 84, 98]
for (name, c), x in zip(legend_entries, legend_xs):
    is_tile = (name == "Tile")
    border = RED if is_tile else NAVY
    bw     = 0.9 if is_tile else 0.4
    ax.add_patch(Rectangle((x, legend_y), sw_w, sw_h,
                           facecolor=c, edgecolor=border, linewidth=bw,
                           clip_on=False))
    txt_color = RED if is_tile else NAVY
    ax.text(x + sw_w + 0.7, legend_y + sw_h / 2, name,
            ha="left", va="center",
            fontsize=5.6, color=txt_color,
            fontweight="bold" if is_tile else "normal")

plt.tight_layout(pad=0.15)
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "fig4_power_breakdown.pdf")
plt.savefig(out_path, format="pdf", bbox_inches="tight", pad_inches=0.04)
print(f"wrote {out_path}")
