#!/usr/bin/env python3
"""render_soc_layout.py — render the post-route SoC GDS with major blocks
labelled, to results/phase3/figures/soc_layout_openram_labeled.png.

Uses KLayout's pya Python module via `klayout -b -r`. The headless
rendering writes a PNG; we then post-process with PIL to add labels
and a scale bar.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GDS = ROOT / "flow/phase3_soc/runs/phase3_soc/final/gds/soc_top.gds"
OUT_DIR = ROOT / "results/phase3/figures"
OUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_PNG = OUT_DIR / "soc_layout_openram_raw.png"
LABELED_PNG = OUT_DIR / "soc_layout_openram_labeled.png"

KLAYOUT_SCRIPT = f"""
# KLayout rendering script — reads the SoC GDS and renders to PNG.
import pya
ly = pya.Layout()
ly.read("{GDS}")
top = ly.top_cell()
print("Top cell:", top.name, "bbox:", top.bbox().to_s())

# Render via the Image class, no GUI required.
img = pya.Image(2400, 2400, pya.Image.PixelFormatRGBA)
# Use the basic-display mode: each layer's color from the technology's
# default if available, else default black-on-white.
view = pya.LayoutView()
view.show_layout(ly, False)
view.zoom_fit()
view.set_config("background-color", "#ffffff")
view.save_image("{RAW_PNG}", 2400, 2400)
print("Wrote", "{RAW_PNG}")
"""


def main():
    # 1. KLayout headless render via temp script file (klayout's -r option
    # requires a real file path; /dev/stdin is rejected as "no interpreter").
    klayout_script_path = OUT_DIR / "_render_klayout.py"
    # Hunt for the sky130A layer-property file so the render gets
    # proper colors per layer instead of just bbox outlines.
    lyp_candidates = list(
        (ROOT / "pdk").glob("**/sky130A/libs.tech/klayout/tech/sky130A.lyp")
    )
    lyp = str(lyp_candidates[0]) if lyp_candidates else ""
    klayout_script_path.write_text(f"""\
import pya
ly = pya.Layout()
ly.read("{GDS}")
top = ly.top_cell()
print("Top cell:", top.name, "bbox:", top.bbox().to_s())
view = pya.LayoutView()
view.show_layout(ly, False)
lyp = "{lyp}"
if lyp:
    view.load_layer_props(lyp)
    print("Loaded layer props from", lyp)
view.zoom_fit()
view.set_config("background-color", "#ffffff")
view.set_config("text-visible", "false")
view.save_image("{RAW_PNG}", 2400, 2400)
print("Wrote raw render")
""")
    print(f"Rendering {GDS} to {RAW_PNG} via KLayout headless…")
    proc = subprocess.run(
        ["klayout", "-b", "-r", str(klayout_script_path)],
        capture_output=True, text=True,
    )
    print(proc.stdout)
    if proc.returncode != 0 or not RAW_PNG.exists():
        print("STDERR:", proc.stderr, file=sys.stderr)
        fallback = ROOT / "flow/phase3_soc/runs/phase3_soc/final/render/soc_top.png"
        if fallback.exists():
            print(f"KLayout headless rendering failed; using LibreLane render at {fallback}")
            import shutil
            shutil.copy(fallback, RAW_PNG)
        else:
            sys.exit(proc.returncode)

    # 2. Label with PIL.
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(RAW_PNG).convert("RGBA")
    W, H = img.size
    # The render is at die scale: 1500 µm × 1500 µm → W × H pixels.
    um_per_px = 1500.0 / W
    px_per_um = 1.0 / um_per_px

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Try to load a TrueType font; fall back to default if not available.
    font_size = max(24, W // 60)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except (OSError, IOError):
        font = ImageFont.load_default()

    # Macro positions in µm space (lower-left corner).
    # IMEM: 683.10 × 416.54 at (50, 1033.46)
    # DMEM: 479.78 × 397.50 at (783.10, 1052.50)
    # KLayout image origin is typically top-left with y growing down. We
    # need to convert from layout-space (origin bottom-left) to image-
    # space (origin top-left): img_y = H - layout_y * px_per_um.
    def to_img(x_um, y_um):
        return (x_um * px_per_um, H - y_um * px_per_um)

    macros = [
        ("IMEM", 50.0, 1033.46, 683.10, 416.54, (255, 64, 64, 192)),
        ("DMEM", 783.10, 1052.50, 479.78, 397.50, (255, 64, 64, 192)),
    ]
    for name, x, y, w, h, color in macros:
        ll = to_img(x, y)
        ur = to_img(x + w, y + h)
        # Image-space rectangle (note y flip)
        rect = [min(ll[0], ur[0]), min(ll[1], ur[1]),
                max(ll[0], ur[0]), max(ll[1], ur[1])]
        draw.rectangle(rect, outline=color, width=4)
        cx = (rect[0] + rect[2]) / 2
        cy = (rect[1] + rect[3]) / 2
        # Centered label with a contrasting background pad.
        text = name
        text_bbox = draw.textbbox((cx, cy), text, font=font, anchor="mm")
        pad = 6
        draw.rectangle([text_bbox[0] - pad, text_bbox[1] - pad,
                        text_bbox[2] + pad, text_bbox[3] + pad],
                       fill=(0, 0, 0, 192))
        draw.text((cx, cy), text, fill=(255, 255, 255, 255), font=font, anchor="mm")

    # PicoRV32 + tile + GPIO regions are post-flatten; mark a rough
    # zone label below the macros.
    label_y = H - 700 * px_per_um  # ~around y=800 in µm space
    draw.text((W // 2, label_y),
              "PicoRV32 + tile_tlg_ld + interconnect (std cells)",
              fill=(0, 0, 0, 255), font=font, anchor="mm",
              stroke_fill=(255, 255, 255, 200), stroke_width=4)

    # Scale bar — bottom-left, 200 µm long.
    bar_um = 200.0
    bar_px = bar_um * px_per_um
    bar_x = 30
    bar_y = H - 30
    draw.rectangle([bar_x, bar_y - 8, bar_x + bar_px, bar_y], fill=(0, 0, 0, 255))
    draw.text((bar_x + bar_px / 2, bar_y - 25),
              f"{bar_um:.0f} µm",
              fill=(0, 0, 0, 255), font=font, anchor="mb",
              stroke_fill=(255, 255, 255, 220), stroke_width=3)

    # Title
    draw.text((W // 2, 30),
              "SoC post-P&R layout — OpenRAM SRAM (1.5 × 1.5 mm die)",
              fill=(0, 0, 0, 255), font=font, anchor="mt",
              stroke_fill=(255, 255, 255, 220), stroke_width=3)

    out = Image.alpha_composite(img, overlay)
    out.convert("RGB").save(LABELED_PNG, dpi=(300, 300))
    print(f"Wrote {LABELED_PNG} ({out.size[0]} × {out.size[1]} px @ 300 DPI)")


if __name__ == "__main__":
    main()
