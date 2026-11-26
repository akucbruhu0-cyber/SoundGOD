#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pillow"]
# ///
"""Turn assets/logo.jpg into the app icon: a rounded macOS tile, written as an .iconset folder.  usage: make-icon.py OUT.iconset"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

LOGO = Path(__file__).resolve().parent.parent / "assets" / "logo.jpg"
N = 1024 * 2  # compose at 2x, downsample for clean edges
CENTER, SIDE = (1004, 1032), 1560  # square crop of the 2000 px artwork: the mark centred with room to breathe

src = Image.open(LOGO).convert("RGB")
cx, cy = CENTER
m = int(N * 0.08)  # the macOS icon grid leaves a margin around the tile
tile = N - 2 * m
art = src.crop((cx - SIDE // 2, cy - SIDE // 2, cx + SIDE // 2, cy + SIDE // 2)).resize((tile, tile), Image.LANCZOS)

img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
mask = Image.new("L", (tile, tile), 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, tile, tile), radius=int(N * 0.19), fill=255)
img.paste(art, (m, m), mask)

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for size in (16, 32, 128, 256, 512):
    img.resize((size, size), Image.LANCZOS).save(out / f"icon_{size}x{size}.png")
    img.resize((size * 2, size * 2), Image.LANCZOS).save(out / f"icon_{size}x{size}@2x.png")
