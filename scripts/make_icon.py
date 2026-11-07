"""Render the ALLES app icon (assets/alles.ico + assets/logo.png). Requires Pillow.

Design: a squircle with an indigo -> cyan gradient, a soft top highlight and a
white magnifying glass with a bold "A" inside the lens. Small sizes (16/24 px)
get a simplified glyph so they stay crisp in the tray.
"""
import math
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
S = 1024  # master resolution

TOP_LEFT = (99, 102, 241)      # indigo-500
BOTTOM_RIGHT = (6, 182, 212)   # cyan-500


def squircle_mask(size, n=5.0, inset=0):
    """Superellipse mask (iOS/Windows 11 style rounded square)."""
    m = Image.new("L", (size, size), 0)
    px = m.load()
    r = size / 2 - inset
    c = size / 2
    for y in range(size):
        dy = abs((y + 0.5 - c) / r)
        if dy > 1:
            continue
        dx = (1 - dy ** n) ** (1 / n)
        x0 = int(round(c - dx * r))
        x1 = int(round(c + dx * r))
        for x in range(max(0, x0), min(size, x1)):
            px[x, y] = 255
    return m


def gradient(size):
    g = Image.new("RGB", (size, size))
    px = g.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            t = t * t * (3 - 2 * t)  # smoothstep
            px[x, y] = tuple(int(TOP_LEFT[i] * (1 - t) + BOTTOM_RIGHT[i] * t) for i in range(3))
    return g


def load_font(px):
    for name in ("segoeuib.ttf", "seguisb.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def render(size, detailed=True):
    s = S
    base = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    mask = squircle_mask(s, inset=s * 0.03)
    bg = gradient(s).convert("RGBA")
    base.paste(bg, (0, 0), mask)

    # soft highlight on the upper half
    hl = Image.new("L", (s, s), 0)
    ImageDraw.Draw(hl).ellipse((-s * 0.4, -s * 0.9, s * 1.4, s * 0.42), fill=42)
    hl = ImageChops.multiply(hl.filter(ImageFilter.GaussianBlur(s * 0.12)), mask)
    base = Image.composite(Image.new("RGBA", (s, s), (255, 255, 255, 255)), base, hl)

    # magnifier: lens ring + handle, with a subtle drop shadow
    glyph = Image.new("L", (s, s), 0)
    d = ImageDraw.Draw(glyph)
    cx, cy, r = s * 0.44, s * 0.43, s * 0.235
    ring = s * (0.075 if detailed else 0.11)
    d.ellipse((cx - r - ring / 2, cy - r - ring / 2, cx + r + ring / 2, cy + r + ring / 2),
              fill=255)
    d.ellipse((cx - r + ring / 2, cy - r + ring / 2, cx + r - ring / 2, cy + r - ring / 2),
              fill=0)
    ang = math.radians(45)
    hx0, hy0 = cx + (r + ring * 0.3) * math.cos(ang), cy + (r + ring * 0.3) * math.sin(ang)
    hx1, hy1 = cx + r * 2.05 * math.cos(ang), cy + r * 2.05 * math.sin(ang)
    hw = s * (0.105 if detailed else 0.13)
    d.line((hx0, hy0, hx1, hy1), fill=255, width=int(hw))
    d.ellipse((hx1 - hw / 2, hy1 - hw / 2, hx1 + hw / 2, hy1 + hw / 2), fill=255)
    if detailed:
        font = load_font(int(r * 1.45))
        bbox = d.textbbox((0, 0), "A", font=font)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        d.text((cx - w / 2 - bbox[0], cy - h / 2 - bbox[1] + s * 0.005), "A", fill=255,
               font=font)

    shadow = glyph.filter(ImageFilter.GaussianBlur(s * 0.02))
    shadow_layer = Image.new("RGBA", (s, s), (20, 20, 60, 0))
    shadow_layer.putalpha(ImageChops.multiply(shadow.point(lambda v: v * 0.45), mask))
    base = Image.alpha_composite(base, _offset(shadow_layer, int(s * 0.012), int(s * 0.02)))
    white = Image.new("RGBA", (s, s), (255, 255, 255, 255))
    white.putalpha(glyph)
    base = Image.alpha_composite(base, white)
    return base.resize((size, size), Image.LANCZOS)


def _offset(img, dx, dy):
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (dx, dy))
    return out


def main():
    os.makedirs(ASSETS, exist_ok=True)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    frames = {sz: render(sz, detailed=sz >= 32) for sz in sizes}
    frames[256].save(os.path.join(ASSETS, "alles.ico"), format="ICO",
                     sizes=[(sz, sz) for sz in sizes],
                     append_images=[frames[sz] for sz in sizes if sz != 256])
    render(512).save(os.path.join(ASSETS, "logo.png"))
    print("wrote assets/alles.ico and assets/logo.png")


if __name__ == "__main__":
    main()
