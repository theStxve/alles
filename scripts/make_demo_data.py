"""Create a realistic demo folder (used for README screenshots). Requires Pillow.

Usage: python scripts/make_demo_data.py <target-folder>
"""
import os
import random
import sys
import time

from PIL import Image, ImageDraw, ImageFilter

random.seed(7)


def photo(path, palette):
    w, h = 1200, 800
    img = Image.new("RGB", (w, h), palette[0])
    d = ImageDraw.Draw(img)
    for i in range(h):  # sky gradient
        t = i / h
        c = tuple(int(palette[0][k] * (1 - t) + palette[1][k] * t) for k in range(3))
        d.line([(0, i), (w, i)], fill=c)
    d.ellipse((w * 0.68, h * 0.12, w * 0.82, h * 0.33), fill=palette[2])
    for layer, col in enumerate(palette[3:]):
        base = h * (0.55 + layer * 0.12)
        pts = [(0, h)]
        for x in range(0, w + 60, 60):
            pts.append((x, base - random.randint(0, 140) + layer * 20))
        pts.append((w, h))
        d.polygon(pts, fill=col)
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    img.save(path, quality=88)


PALETTES = [
    [(255, 183, 120), (255, 120, 140), (255, 240, 200), (120, 70, 110), (70, 40, 80)],
    [(140, 200, 255), (220, 240, 255), (255, 255, 230), (90, 150, 110), (50, 100, 70)],
    [(30, 40, 90), (120, 80, 160), (250, 250, 255), (40, 40, 70), (20, 20, 40)],
    [(255, 220, 150), (255, 170, 90), (255, 255, 255), (200, 120, 60), (120, 70, 40)],
]

FILES = {
    "Projekte/alles/README.md": "# ALLES\n\nBlitzschnelle Dateisuche für Windows.\n",
    "Projekte/alles/app.py": (
        'import tkinter as tk\n\n\ndef main():\n    root = tk.Tk()\n'
        '    root.title("ALLES")\n    root.mainloop()\n\n\nif __name__ == "__main__":\n'
        '    main()\n'),
    "Projekte/alles/pyproject.toml": '[project]\nname = "alles"\nversion = "2.1.0"\n',
    "Projekte/Website/index.html": "<!doctype html>\n<title>Hallo</title>\n<h1>Hallo Welt</h1>\n",
    "Projekte/Website/style.css": "body { font-family: system-ui; margin: 2rem; }\n",
    "Projekte/Angebot Website Relaunch.docx": b"PK" + bytes(18000),
    "Dokumente/Rechnungen/Rechnung 2026-0142.pdf": b"%PDF-1.7" + bytes(84000),
    "Dokumente/Rechnungen/Rechnung 2026-0187.pdf": b"%PDF-1.7" + bytes(91000),
    "Dokumente/Rechnungen/Rechnung 2025-1203.pdf": b"%PDF-1.7" + bytes(77000),
    "Dokumente/Steuer/Steuererklärung 2025.pdf": b"%PDF-1.7" + bytes(412000),
    "Dokumente/Steuer/Belege 2025.xlsx": b"PK" + bytes(56000),
    "Dokumente/Mietvertrag.pdf": b"%PDF-1.7" + bytes(230000),
    "Dokumente/Notizen.txt": "Einkaufsliste:\n- Kaffee\n- Hafermilch\n- Brot\n\nIdeen:\n"
                             "- ALLES als winget-Paket\n- Dark Mode testen\n",
    "Dokumente/Lebenslauf.docx": b"PK" + bytes(34000),
    "Musik/Lo-Fi Beats/01 - Morning Coffee.mp3": bytes(3_400_000),
    "Musik/Lo-Fi Beats/02 - Rainy Window.mp3": bytes(2_900_000),
    "Musik/Lo-Fi Beats/03 - Late Night Code.mp3": bytes(3_100_000),
    "Videos/Urlaub 2026 Schnitt.mp4": bytes(48_000_000),
    "Videos/Bildschirmaufnahme 2026-11-03.mp4": bytes(12_000_000),
    "Backups/Fotos-Backup.zip": bytes(25_000_000),
    "Downloads/python-3.13.0-amd64.exe": bytes(27_000_000),
    "Downloads/Rechnung 2026-0142.pdf": b"%PDF-1.7" + bytes(84000),
    "Downloads/Everything-1.4.1.1026.x64-Setup.exe": bytes(1_800_000),
}


def main():
    target = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "ALLES-Demo")
    for rel, content in FILES.items():
        p = os.path.join(target, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(content.encode("utf-8") if isinstance(content, str) else content)
    fotos = os.path.join(target, "Fotos", "Urlaub 2026")
    os.makedirs(fotos, exist_ok=True)
    for i, pal in enumerate(PALETTES * 2):
        random.seed(i)
        photo(os.path.join(fotos, f"IMG_{2041 + i:04d}.jpg"), pal)
    # spread modification dates over the last months
    now = time.time()
    for i, (dirpath, _dirs, files) in enumerate(os.walk(target)):
        for j, name in enumerate(files):
            t = now - (i * 7 + j * 3) * 86400 * random.random()
            os.utime(os.path.join(dirpath, name), (t, t))
    print("demo data in", target)


if __name__ == "__main__":
    main()
