# ALLES – Everything, aber verständlich

[![CI](https://github.com/theStxve/alles/actions/workflows/ci.yml/badge.svg)](https://github.com/theStxve/alles/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Windows](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078d4)
![Python](https://img.shields.io/badge/python-3.10%2B-3776ab)

**ALLES** ist eine aufgeräumte Windows-Oberfläche für die blitzschnelle Dateisuche
[Everything](https://www.voidtools.com) von voidtools.

Die Ergebnisse kommen direkt aus deinem laufenden Everything über das offizielle SDK.
Es wird nichts nachgebaut oder geschätzt. ALLES nimmt dir nur die Suchsyntax ab:
Du klickst Filter an, ALLES schreibt die passende Everything-Abfrage und zeigt sie dir an.
So lernst du die Syntax nebenbei.

## Funktionen

- **Live-Suche beim Tippen** – stellt man die Suche um, werden veraltete Abfragen verworfen
- **Filter per Klick** für Typ (Dokumente, Bilder, Videos, Code …), Größe und Änderungsdatum
- **Laufwerke gezielt auswählen** (mit Laufwerksnamen) statt „alles oder nichts“
- **Generierte Everything-Syntax** sichtbar und kopierbar, auch direkt in Everything öffnen
- **Sortieren** per Klick auf die Spaltenköpfe
- **Mehrfachauswahl**: öffnen, im Explorer zeigen, Eigenschaften, Pfade/Namen kopieren
- **„In diesem Ordner suchen“** über das Kontextmenü
- **CSV-Export** der Ergebnisse (Excel-kompatibel)
- **Suchverlauf** (Alt+↓)
- **Tray-Icon + globaler Hotkey** (Standard: `Strg+Alt+Leertaste`), frei belegbar
- **Selbstheilung**: Läuft Everything nicht (z. B. nur als Dienst), startet ALLES es im Hintergrund
- **Diagnose**: zeigt, welche Laufwerke *nicht* im Everything-Index sind (typisch: exFAT/FAT/Netz)
- **Autostart mit Windows** (optional), Fensterposition, Spalten und Filter bleiben gespeichert
- Scharfe Darstellung auf HiDPI-Bildschirmen, **keine Abhängigkeiten** außer Python selbst

## Installation

### Variante A: fertige EXE

1. [Everything](https://www.voidtools.com/downloads/) installieren und starten
2. `ALLES-vX.Y.Z.exe` aus den [Releases](https://github.com/theStxve/alles/releases) laden und starten

> Windows SmartScreen kann bei unsignierten EXE-Dateien warnen („Weitere Informationen“ →
> „Trotzdem ausführen“). Die SHA-256-Prüfsumme liegt jedem Release bei.

### Variante B: aus dem Quellcode

```powershell
git clone https://github.com/theStxve/alles.git
cd alles
python scripts/fetch_sdk.py     # lädt Everything64.dll vom offiziellen voidtools-SDK
python -m alles                 # oder: pythonw run_alles.py (ohne Konsolenfenster)
```

Voraussetzung: Python 3.10+ (mit tkinter, ist im Standard-Installer enthalten).
Optional: `pip install psutil` für die Prozess-Suche nach Everything.exe.

### Kommandozeile

```text
alles [--tray] [--search TEXT] [--version]
  --tray     versteckt im Tray starten (für den Autostart)
  --search   direkt mit diesem Suchbegriff starten
```

## Tastenkürzel

| Taste | Aktion |
|---|---|
| `Strg+Alt+Leertaste` | Fenster ein-/ausblenden (global, änderbar) |
| `Strg+F` / `Strg+L` | Suchfeld fokussieren |
| `↓` / `↑` | Zwischen Suchfeld und Ergebnissen wechseln |
| `Enter` / `Strg+Enter` / `Alt+Enter` | Öffnen / Im Explorer zeigen / Eigenschaften |
| `Strg+C` / `Strg+Umschalt+C` | Pfade / Namen kopieren |
| `F5` | Suche wiederholen |
| `Strg+S` | Als CSV exportieren |
| `Esc` | Suche leeren, beim zweiten Mal in den Tray |

## Häufige Probleme

**„Everything läuft nicht (oder nur als Dienst)“**
Der Everything-*Dienst* allein beantwortet keine Suchanfragen, dafür muss `Everything.exe`
laufen. ALLES startet es automatisch im Hintergrund. Klappt das nicht, den Pfad unter
*Extras → Einstellungen* angeben.

**Ein Laufwerk liefert keine Treffer**
*Everything → Diagnose* ausführen. FAT/exFAT- und Netzlaufwerke indiziert Everything nicht
automatisch. Du musst sie in Everything unter *Extras → Optionen → Indizes → Ordner* hinzufügen.

**Wo liegen Einstellungen und Log?**
`%APPDATA%\ALLES\config.json` und `%APPDATA%\ALLES\alles.log`

## Entwicklung

```powershell
pip install -e ".[dev]"
python -m ruff check .
python -m pytest
python scripts/fetch_sdk.py ; python -m PyInstaller ALLES.spec   # -> dist/ALLES.exe
```

Projektstruktur:

```text
alles/
  app.py            Oberfläche (tkinter), Such-Worker, Einstellungen
  query.py          UI-Auswahl -> Everything-Syntax (reines Python, voll getestet)
  everything_sdk.py ctypes-Wrapper um Everything64.dll
  tray.py           Tray-Icon, globaler Hotkey, Single-Instance (reines ctypes)
  shell.py          Öffnen, Explorer, Eigenschaften, Autostart, Laufwerke
  locate.py         Everything.exe finden (Registry, Dienst, Standardpfade)
  config.py, util.py, win_style.py
tests/              pytest
scripts/            fetch_sdk.py, make_icon.py
```

Einen Release baust du, indem du die Version in `alles/__init__.py` erhöhst und dann einen Tag
pushst (`git tag v2.0.1 && git push --tags`). GitHub Actions baut die EXE und hängt sie an.

Ideen für die Zukunft: [docs/FEATURE_IDEAS.md](docs/FEATURE_IDEAS.md)

## Lizenz

[MIT](LICENSE) © theStxve

„Everything“ und das Everything-SDK sind Produkte von [voidtools](https://www.voidtools.com).
Sie sind nicht Teil dieses Repositories. ALLES ist ein inoffizielles Projekt und nicht mit
voidtools verbunden.
