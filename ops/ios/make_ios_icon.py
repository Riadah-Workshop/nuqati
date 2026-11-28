"""Builds the 1024x1024 iOS app icon: the existing Nuqati mark redrawn at full size.

Apple requires a square, fully opaque 1024x1024 PNG (no transparency, no rounded corners: iOS applies its own mask). The current icon
(driver_app/assets/nuqati_icon.png) is 110x95 with transparency, so it cannot be used. The mark is simple geometry (a lime route line
ending in two rings, on the navy of the app); this redraws it from measurements of the existing icon, at 4x size and scaled down for
smooth edges. Replace the result with a designer's artwork whenever one exists; then run nothing, just keep the PNG names.
    python3 ops/ios/make_ios_icon.py   # writes <app>/assets/nuqati_icon_ios.png for driver_app and manager_app
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
NAVY = (0x0B, 0x1C, 0x30)
LIME = (0xA8, 0xD9, 0x41)
SIZE = 1024
SUPER = 4


def build() -> Image.Image:
    s = SUPER
    image = Image.new("RGB", (SIZE * s, SIZE * s), NAVY)
    draw = ImageDraw.Draw(image)
    stroke = 46
    ring_out, ring_in = 98, 52
    top_ring, bottom_ring = (668, 330), (363, 687)
    y1, y3 = top_ring[1], bottom_ring[1]
    y2 = (y1 + y3) / 2
    radius = (y2 - y1) / 2          # centre line radius of both turns
    left_x, right_x = 380, 640      # where the horizontals turn

    def box(cx, cy, r):
        return [(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s]

    def line(x1, y, x2):
        draw.line([(x1 * s, y * s), (x2 * s, y * s)], fill=LIME, width=stroke * s)

    line(top_ring[0] - ring_out + 20, y1, left_x)                 # top bar, from the top ring to the left turn
    draw.arc(box(left_x, (y1 + y2) / 2, radius + stroke / 2), 90, 270, fill=LIME, width=stroke * s)
    line(left_x, y2, right_x)                                     # middle bar
    draw.arc(box(right_x, (y2 + y3) / 2, radius + stroke / 2), -90, 90, fill=LIME, width=stroke * s)
    line(bottom_ring[0] + ring_out - 20, y3, right_x)             # bottom bar, to the bottom ring
    for cx, cy in (top_ring, bottom_ring):
        draw.ellipse(box(cx, cy, ring_out), fill=LIME)
        draw.ellipse(box(cx, cy, ring_in), fill=NAVY)
    return image.resize((SIZE, SIZE), Image.LANCZOS)


if __name__ == "__main__":
    icon = build()
    for app in ("driver_app", "manager_app"):
        destination = ROOT / app / "assets" / "nuqati_icon_ios.png"
        icon.save(destination, optimize=True)
        print("wrote", destination.relative_to(ROOT), icon.size, icon.mode)
