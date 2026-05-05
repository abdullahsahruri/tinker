#!/usr/bin/env python3
"""render_soc_layout.py — produce paper/figures fig3 base PNG.

Uses the actual LibreLane KLayout render as the base (so what appears
in the paper is a real flow output, not a synthetic floorplan sketch).
Overlays die outline, macro boundaries, an std-cell zone label, and a
scale bar. Output:
  results/phase3/figures/soc_layout_openram_raw.png      (untouched copy)
  results/phase3/figures/soc_layout_openram_labeled.png  (annotated)
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_RENDER = ROOT / "flow/phase3_soc/runs/phase3_soc/final/render/soc_top.png"
OUT_DIR = ROOT / "results/phase3/figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_PNG = OUT_DIR / "soc_layout_openram_raw.png"
LABELED_PNG = OUT_DIR / "soc_layout_openram_labeled.png"

# Die: 1500 × 1500 µm
DIE_UM = 1500.0
# Macro positions / sizes in µm (from manual macro placement and macro LEFs)
MACROS = [
    # (label, x_um, y_um, w_um, h_um)
    ("IMEM",  50.0,    1033.46, 683.10, 416.54),
    ("DMEM",  783.10,  1052.50, 479.78, 397.50),
]


def main():
    if not SRC_RENDER.exists():
        print(f"ERROR: LibreLane render missing at {SRC_RENDER}", file=sys.stderr)
        sys.exit(2)
    shutil.copy(SRC_RENDER, RAW_PNG)
    print(f"Copied real flow render -> {RAW_PNG}")

    from PIL import Image, ImageDraw, ImageFont
    base = Image.open(RAW_PNG).convert("RGBA")
    # Upscale 2× so labels and overlays are crisp at print resolution.
    UPSCALE = 2
    W0, H0 = base.size
    W, H = W0 * UPSCALE, H0 * UPSCALE
    base = base.resize((W, H), Image.LANCZOS)
    px_per_um = W / DIE_UM

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    NAVY = (31, 58, 95, 255)
    RED  = (168, 50, 50, 255)
    NAVY_FILL_T = (31, 58, 95, 32)

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        font_lg = ImageFont.truetype(font_path, max(28, W // 56))
        font_md = ImageFont.truetype(font_path, max(22, W // 80))
        font_sm = ImageFont.truetype(font_path, max(18, W // 110))
    except (OSError, IOError):
        font_lg = font_md = font_sm = ImageFont.load_default()

    def to_img(x_um, y_um):
        # KLayout image: y grows downward; layout: y grows upward.
        return (x_um * px_per_um, H - y_um * px_per_um)

    # Die outline (draw a navy rectangle around the full die for sharp edges).
    draw.rectangle([0, 0, W - 1, H - 1], outline=NAVY, width=4)

    # Macro overlays
    for name, x, y, w, h in MACROS:
        ll = to_img(x, y)
        ur = to_img(x + w, y + h)
        rect = [min(ll[0], ur[0]), min(ll[1], ur[1]),
                max(ll[0], ur[0]), max(ll[1], ur[1])]
        draw.rectangle(rect, outline=RED, width=6)
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        # Macro label with white pad and navy text
        text = f"{name}"
        sub  = f"{w:.0f} × {h:.0f} µm"
        bbox = draw.textbbox((cx, cy - 18), text, font=font_lg, anchor="mm")
        pad = 6
        draw.rectangle([bbox[0] - pad, bbox[1] - pad,
                        bbox[2] + pad, bbox[3] + pad],
                       fill=(255, 255, 255, 235), outline=NAVY, width=2)
        draw.text((cx, cy - 18), text, fill=NAVY, font=font_lg, anchor="mm")
        bbox2 = draw.textbbox((cx, cy + 30), sub, font=font_sm, anchor="mm")
        draw.rectangle([bbox2[0] - 4, bbox2[1] - 2,
                        bbox2[2] + 4, bbox2[3] + 2],
                       fill=(255, 255, 255, 215))
        draw.text((cx, cy + 30), sub, fill=NAVY, font=font_sm, anchor="mm")

    # Std-cell zone label spanning the bulk below the macros.
    # Macro bottoms are around y_um = 1033, so std-cell zone is roughly
    # y_um in [10, 1020].
    std_cx = W * 0.50
    std_cy = H - (520 * px_per_um)  # near vertical middle of std-cell zone
    label = "std-cell logic"
    sublabel = "(PicoRV32 + TLG-mapped tile + Wishbone fabric + GPIO)"
    bbox_main = draw.textbbox((std_cx, std_cy), label, font=font_lg, anchor="mm")
    pad = 10
    draw.rectangle([bbox_main[0] - pad, bbox_main[1] - pad,
                    bbox_main[2] + pad, bbox_main[3] + pad],
                   fill=(255, 255, 255, 230), outline=NAVY, width=2)
    draw.text((std_cx, std_cy), label, fill=NAVY, font=font_lg, anchor="mm")
    bbox_sub = draw.textbbox((std_cx, std_cy + 36), sublabel,
                             font=font_sm, anchor="mm")
    draw.rectangle([bbox_sub[0] - 6, bbox_sub[1] - 4,
                    bbox_sub[2] + 6, bbox_sub[3] + 4],
                   fill=(255, 255, 255, 220))
    draw.text((std_cx, std_cy + 36), sublabel,
              fill=NAVY, font=font_sm, anchor="mm")

    # Die-size annotation (top-right corner)
    die_lbl = f"die {DIE_UM:.0f} × {DIE_UM:.0f} µm"
    bbox_d = draw.textbbox((W - 18, 18), die_lbl, font=font_md, anchor="rt")
    draw.rectangle([bbox_d[0] - 6, bbox_d[1] - 4,
                    bbox_d[2] + 6, bbox_d[3] + 4],
                   fill=(255, 255, 255, 230), outline=NAVY, width=2)
    draw.text((W - 18, 18), die_lbl, fill=NAVY, font=font_md, anchor="rt")

    # Scale bar bottom-left (200 µm)
    bar_um = 200.0
    bar_px = bar_um * px_per_um
    bar_x = 20
    bar_y = H - 24
    draw.rectangle([bar_x, bar_y - 14, bar_x + bar_px, bar_y - 4],
                   fill=NAVY)
    draw.text((bar_x + bar_px / 2, bar_y - 24),
              f"{bar_um:.0f} µm",
              fill=NAVY, font=font_md, anchor="mb",
              stroke_fill=(255, 255, 255, 240), stroke_width=4)

    out = Image.alpha_composite(base, overlay)
    out.convert("RGB").save(LABELED_PNG, dpi=(300, 300), optimize=True)
    print(f"Wrote {LABELED_PNG} ({out.size[0]}×{out.size[1]} px)")


if __name__ == "__main__":
    main()
