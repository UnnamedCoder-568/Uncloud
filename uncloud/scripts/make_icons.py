"""Build the Uncloud icon set from the supplied cloud mark.

Drawn rather than cropped. The artwork on the sheet is 141 pixels across, and
an app icon is 1024 — upscaling it would be soft where this mark is crisp. So
the same geometry the interface draws is rendered here at full size, filled
with the gradient sampled from the artwork itself and set on the dark tile the
sheet specifies.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(sys.argv[1] if len(sys.argv) > 1
           else Path(__file__).resolve().parents[1] / "src-tauri" / "icons")

# The measured mark, in a 100-wide box. Same numbers as Wordmark.tsx; a test
# asserts the two agree.
OUTER = dict(w=100.0, h=72.34, r1=29.08, cy1=28.37, rl=26.24, yl=46.10,
             rb=26.24, top=40.43)
INNER = dict(w=58.87, h=34.04, r1=15.60, cy1=15.60, rl=9.93, yl=24.11,
             rb=9.93, top=22.70)
INNER_AT = (20.57, 21.28)

GROUND = (23, 45, 58)          # the sheet's dark tile
TOP = (254, 196, 77)           # the cloud's gradient, sampled top and bottom
BOTTOM = (254, 123, 5)

SS = 4                          # supersample; the shapes are drawn, then downed


def cloud(draw, c, ox, oy, scale, fill):
    def e(x, y, r):
        draw.ellipse([ox + (x - r) * scale, oy + (y - r) * scale,
                      ox + (x + r) * scale, oy + (y + r) * scale], fill=fill)
    e(c["w"] / 2, c["cy1"], c["r1"])
    e(c["rl"], c["yl"], c["rl"])
    e(c["w"] - c["rl"], c["yl"], c["rl"])
    e(c["rb"], c["h"] - c["rb"], c["rb"])
    e(c["w"] - c["rb"], c["h"] - c["rb"], c["rb"])
    draw.rectangle([ox + c["rb"] * scale, oy + c["top"] * scale,
                    ox + (c["w"] - c["rb"]) * scale, oy + c["h"] * scale], fill=fill)
    draw.rectangle([ox, oy + c["yl"] * scale,
                    ox + c["w"] * scale, oy + (c["h"] - c["rb"]) * scale], fill=fill)


def glyph(width_px: int) -> Image.Image:
    """The cloud, gradient-filled, with the middle knocked out to transparent."""
    scale = width_px * SS / OUTER["w"]
    w = int(OUTER["w"] * scale)
    h = int(round(OUTER["h"] * scale))

    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    cloud(d, OUTER, 0, 0, scale, 255)
    cloud(d, INNER, INNER_AT[0] * scale, INNER_AT[1] * scale, scale, 0)

    gradient = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        gradient.putpixel((0, y), tuple(
            round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)))
    art = gradient.resize((w, h))
    art.putalpha(mask)
    return art.resize((width_px, round(h / SS)), Image.LANCZOS)


def rounded(size: int, radius_ratio: float = 0.2237) -> Image.Image:
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size * 4 - 1, size * 4 - 1),
        radius=int(size * 4 * radius_ratio), fill=255)
    return mask.resize((size, size), Image.LANCZOS)


def icon(size: int = 1024) -> Image.Image:
    tile = Image.new("RGBA", (size, size), (*GROUND, 255))
    tile.putalpha(rounded(size))
    art = glyph(int(size * 0.70))
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # Optically centred: a cloud is bottom-heavy, so geometric centring leaves
    # it looking low.
    layer.paste(art, ((size - art.width) // 2,
                      int(size * 0.5 - art.height * 0.52)), art)
    return Image.alpha_composite(tile, layer)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    master = icon(1024)
    master.save(OUT / "icon.png")
    for name, size in (("32x32.png", 32), ("64x64.png", 64),
                       ("128x128.png", 128), ("128x128@2x.png", 256)):
        master.resize((size, size), Image.LANCZOS).save(OUT / name)
    for size in (30, 44, 71, 89, 107, 142, 150, 284, 310):
        master.resize((size, size), Image.LANCZOS).save(
            OUT / f"Square{size}x{size}Logo.png")
    master.resize((50, 50), Image.LANCZOS).save(OUT / "StoreLogo.png")
    master.resize((256, 256), Image.LANCZOS).save(
        OUT / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])

    iconset = OUT / "icon.iconset"
    iconset.mkdir(exist_ok=True)
    for size in (16, 32, 128, 256, 512):
        master.resize((size, size), Image.LANCZOS).save(
            iconset / f"icon_{size}x{size}.png")
        master.resize((size * 2, size * 2), Image.LANCZOS).save(
            iconset / f"icon_{size}x{size}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset),
                    "-o", str(OUT / "icon.icns")], check=True)
    for leftover in iconset.iterdir():
        leftover.unlink()
    iconset.rmdir()

    # The mark on its own, for anywhere a raster is wanted.
    brand = OUT.parent / "brand"
    brand.mkdir(parents=True, exist_ok=True)
    glyph(512).save(brand / "mark.png")
    print("icons written to", OUT)


main()
