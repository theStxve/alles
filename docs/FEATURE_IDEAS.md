# 37 Feature-Ideen für ALLES

✅ = umgesetzt in Version 2.1.0

Aufwand: **S** = ein Abend · **M** = ein paar Tage · **L** = größeres Projekt
Nutzen: ★ bis ★★★

## Suche & Filter

| # | Feature | Beschreibung | Aufwand | Nutzen |
|---|---|---|---|---|
| 1 | ✅ **Standalone-Modus ohne Everything** | Eigenes Such-Backend: eine Backend-Schnittstelle mit `EverythingBackend` und `BuiltinBackend`. Das eigene Backend baut seinen Index per `os.scandir` (oder MFT/USN-Journal mit Adminrechten) in SQLite/FTS5 auf und hält ihn über `ReadDirectoryChangesW` aktuell. | L | ★★★ |
| 2 | ✅ Eigene Filter-Presets | Aktuelle Filterkombination als „Meine Filter“ speichern, z. B. „Große Videos auf D:“ | S | ★★★ |
| 3 | Gespeicherte Suchen / Favoriten | Häufige Suchen anpinnen und optional mit eigenem Hotkey belegen | S | ★★ |
| 4 | Datumsbereich mit Kalender | Von/Bis-Auswahl, auch für Erstellt- und Zugriffsdatum (`dc:`, `da:`) | M | ★★ |
| 5 | Freie Größenangabe | Min/Max-Felder oder Slider statt fester Presets | S | ★★ |
| 6 | ✅ Ordner ausschließen | Ausschlussliste, z. B. `node_modules`, `$Recycle.Bin`, `WinSxS`, wird als `!path:` angehängt | S | ★★★ |
| 7 | ✅ Duplikat-Finder | Gleicher Name und gleiche Größe, optional per Hash bestätigt, mit Ersparnis-Anzeige | M | ★★★ |
| 8 | Inhaltssuche | `content:` mit Warnhinweis und Beschränkung auf ausgewählte Ordner, weil sie langsam ist | S | ★★ |
| 9 | Tippfehler-Toleranz | „Meintest du …?“, wenn es 0 Treffer gibt (Levenshtein gegen Dateinamen) | M | ★ |
| 10 | Natürliche Sprache → Syntax | „pdfs von letzter woche größer 5 mb“ → `ext:pdf dm:lastweek size:>5mb` (regelbasiert, offline) | M | ★★ |
| 11 | Syntax-Autovervollständigung | Vorschläge beim Tippen von `ext:`, `size:`, `dm:` … mit Erklärung | M | ★★ |
| 12 | Weitere Spalten | Erstellt, Zugriff, Attribute, Pfadlänge, einzeln ein- und ausblendbar | S | ★★ |

## Ergebnisse & Vorschau

| # | Feature | Beschreibung | Aufwand | Nutzen |
|---|---|---|---|---|
| 13 | ✅ Vorschau-Panel | Bild-Thumbnails, Text/Code mit Hervorhebung, Metadaten | M | ★★★ |
| 14 | ✅ Echte Datei-Icons | Windows-Symbole über `SHGetFileInfo` in der Liste | M | ★★ |
| 15 | Natives Explorer-Kontextmenü | `IContextMenu`: „Öffnen mit“, 7-Zip, Git … wie im Explorer | L | ★★★ |
| 16 | Drag & Drop | Treffer in den Explorer, in Mails oder Editoren ziehen | M | ★★★ |
| 17 | Gruppierung | Ergebnisse nach Ordner, Typ oder Datum gruppieren | M | ★ |
| 18 | Statistik | Treffer nach Typ und Laufwerk, Gesamtgröße der Auswahl | S | ★★ |
| 19 | Virtuelles Scrollen | Unendliche Liste statt „Weitere laden“, lädt seitenweise beim Scrollen nach | M | ★★ |
| 20 | Umbenennen | F2 inline, dazu Batch-Umbenennen mit Vorschau (Muster, Nummerierung) | M | ★★ |
| 21 | ✅ In den Papierkorb | `Entf` mit Bestätigung, über `SHFileOperation` (wiederherstellbar) | S | ★★ |
| 22 | Kopieren/Verschieben nach … | Zielordner-Dialog mit Verlauf der letzten Ziele | S | ★★ |
| 23 | ✅ „Öffnen mit“-Favoriten | VS Code, Notepad++, Terminal hier, PowerShell hier | S | ★★ |

## Oberfläche

| # | Feature | Beschreibung | Aufwand | Nutzen |
|---|---|---|---|---|
| 24 | ✅ Dark Mode | Folgt dem Windows-Theme, inklusive dunkler Titelleiste (Grundlage in `win_style.py`) | M | ★★★ |
| 25 | Mini-Suchfenster | Kompaktes Fenster am Hotkey wie bei PowerToys Run, `Enter` öffnet den ersten Treffer | M | ★★★ |
| 26 | Tabs | Mehrere Suchen parallel offen | M | ★★ |
| 27 | Englische Oberfläche | i18n mit `gettext`, Sprache automatisch erkennen | M | ★★ |
| 28 | Zoom | `Strg+Mausrad` für Schrift und Zeilenhöhe | S | ★ |
| 29 | Ranking nach Nutzung | Oft geöffnete Dateien steigen nach oben (Frecency) | M | ★★ |
| 30 | Windows-Benachrichtigungen | Toasts für „Everything gestartet“, „Index fertig“, „Export fertig“ | S | ★ |

## System & Integration

| # | Feature | Beschreibung | Aufwand | Nutzen |
|---|---|---|---|---|
| 31 | ✅ Explorer-Integration | Rechtsklick auf einen Ordner → „Mit ALLES hier suchen“ (HKCU-Registry, keine Adminrechte) | S | ★★★ |
| 32 | CLI / JSON-Ausgabe | `alles-cli "ext:pdf rechnung" --json` für Skripte und Automatisierung | S | ★★ |
| 33 | Ordner-Wächter | Regeln wie „neue Datei > 1 GB in Downloads“ lösen eine Benachrichtigung aus | M | ★★ |
| 34 | Everything 1.5 | Instanzname `1.5a` und SDK3 unterstützen (mehr Felder, schneller) | M | ★★★ |
| 35 | Everything-Server (ETP/HTTP) | Index eines anderen PCs oder NAS durchsuchen | M | ★★ |
| 36 | Auto-Update | Prüft GitHub Releases und lädt die neue EXE nach Nachfrage | M | ★★ |
| 37 | ✅ Installer & Paketmanager | Inno-Setup-Installer und portable ZIP sind fertig. Offen: `winget`- und Scoop-Manifest, Code-Signing gegen SmartScreen | M | ★★★ |
