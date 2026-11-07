"""Regenerate assets/alles.ico (requires Pillow). Run: python scripts/make_icon.py"""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "alles.ico")
SIZE = 256


def load_font(px):
    for name in ("segoeuib.ttf", "seguisb.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, SIZE - 8, SIZE - 8), radius=56, fill=(37, 99, 235, 255))
    font = load_font(168)
    bbox = d.textbbox((0, 0), "A", font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((SIZE - w) / 2 - bbox[0], (SIZE - h) / 2 - bbox[1] - 4), "A",
           fill=(255, 255, 255, 255), font=font)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    img.save(OUT, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                                        (64, 64), (128, 128), (256, 256)])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
