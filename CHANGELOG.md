# Changelog

## [2.0.0] – 2026-11-07

Kompletter Umbau zu einem Python-Paket mit Tests, CI und automatischen Releases.

### Behoben
- Bei mehreren ausgewählten Laufwerken kam **nie ein Treffer**: Everything gruppiert mit `< >`,
  nicht mit `( )`. Dazu kam, dass `path:c:\` mit „Groß/Klein“ nichts mehr fand.
- **Regex zusammen mit einem Filter** (Typ/Größe/Datum) brachte 0 Treffer, weil der globale
  Regex-Schalter auch `ext:`/`size:` als Regex las. Jetzt wird der Modifikator `regex:` verwendet.
- Suchfehler führten zu einem `NameError` statt einer Fehlermeldung (`e` in einer Lambda nach dem `except`).
- Änderungsdaten wurden in **UTC statt in Ortszeit** angezeigt. Daten vor 1970 fehlten ganz.
- Ohne Pillow startete weder das Tray-Icon noch der Hotkey (der Thread brach still ab).
- 64-Bit-Handles konnten abgeschnitten werden (fehlende ctypes-Prototypen).
- Das Tray-Fenster wurde aus dem falschen Thread zerstört, Tk-Aufrufe kamen aus Hintergrund-Threads.
- Globale Hotkeys ließen sich ohne Modifier belegen (z. B. nur „A“). Alt wurde falsch erkannt.
- `size:1mb-100mb` wurde durch die dokumentierte Syntax `size:1mb..100mb` ersetzt.
- Bei „Beenden“ über das Tray gingen Fenstergröße und Einstellungen verloren.
- Tooltip-Fenster sammelten sich an. Das Fenster konnte auf einem getrennten Monitor landen.
- Der Pfad zu Everything war fest eingetragen (`D:\Programme\...`). Jetzt wird er automatisch gefunden.
- Nach einem Neustart des Explorers fehlte das Tray-Icon.
- War der Tray nicht verfügbar, verschwand das Fenster beim Schließen unerreichbar.

### Neu
- Menüleiste, sichtbare und kopierbare Everything-Syntax, „In Everything öffnen“
- Sortieren per Spaltenkopf, Mehrfachauswahl, Eigenschaften-Dialog, Namen/Ordner kopieren
- „In diesem Ordner suchen“, CSV-Export, Suchverlauf, „Weitere laden“ (Paging)
- Laufwerksnamen, Ordner werden hervorgehoben, neue Presets (Programme, Gestern, Letzte Woche …)
- Tastenkürzel (siehe README), Autostart mit Windows, `--tray`/`--search`
- Filter, Spaltenbreiten und Laufwerksauswahl werden gespeichert. Die Konfiguration wird atomar geschrieben.
- Log-Datei, DPI-Unterstützung, eigenes Taskleisten-Icon
- Eine zweite Instanz holt das vorhandene Fenster zuverlässig nach vorn, auch aus dem Tray.
- Die EXE ist 12 MB statt 32 MB groß (kein Pillow, kein UPX mehr, weniger Fehlalarme von Virenscannern).
