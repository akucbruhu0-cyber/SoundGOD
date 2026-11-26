#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pillow"]
# ///
"""Draw the app icon (mint tile, forest waveform, one spark) into an .iconset folder.  usage: make-icon.py OUT.iconset"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

N = 1024 * 2  # draw at 2x, downsample for clean edges
MINT, MINT_SOFT, FOREST, SPARK = (205, 235, 213), (230, 245, 234), (30, 106, 46), (255, 181, 116)

img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
tile = Image.new("RGBA", (N, N))
px = tile.load()
for y in range(N):  # soft vertical gradient
    t = y / N
    c = tuple(int(MINT_SOFT[i] * (1 - t) + MINT[i] * t) for i in range(3)) + (255,)
    for x in range(N):
        px[x, y] = c
mask = Image.new("L", (N, N), 0)
m = int(N * 0.08)  # macOS icon grid leaves a margin around the tile
ImageDraw.Draw(mask).rounded_rectangle((m, m, N - m, N - m), radius=int(N * 0.19), fill=255)
img.paste(tile, (0, 0), mask)

d = ImageDraw.Draw(img)
heights = [0.14, 0.26, 0.42, 0.30, 0.50, 0.34, 0.20, 0.12]
bw, gap = int(N * 0.058), int(N * 0.032)
total = len(heights) * bw + (len(heights) - 1) * gap
x0, cy = (N - total) // 2, int(N * 0.54)
for i, h in enumerate(heights):
    x = x0 + i * (bw + gap)
    d.rounded_rectangle((x, cy - h * N / 2, x + bw, cy + h * N / 2), radius=bw // 2, fill=FOREST)

def star(cx, cy, r):  # four-point spark
    k = 0.28
    pts = [(cx, cy - r), (cx + r * k, cy - r * k), (cx + r, cy), (cx + r * k, cy + r * k),
           (cx, cy + r), (cx - r * k, cy + r * k), (cx - r, cy), (cx - r * k, cy - r * k)]
    d.polygon(pts, fill=SPARK)

star(int(N * 0.73), int(N * 0.27), int(N * 0.115))
star(int(N * 0.83), int(N * 0.40), int(N * 0.045))

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for size in (16, 32, 128, 256, 512):
    img.resize((size, size), Image.LANCZOS).save(out / f"icon_{size}x{size}.png")
    img.resize((size * 2, size * 2), Image.LANCZOS).save(out / f"icon_{size}x{size}@2x.png")
