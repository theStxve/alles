"""
English user interface without touching every string in the code.

German is the source language. When English is active, ``install()`` hooks the
places where text reaches the screen (Tk widget options, menus, headings, tabs,
window titles, message boxes, file dialogs) and translates it through CATALOG.
Entries with {0}, {1}, ... are templates for dynamic text; captured values are
translated recursively, multi-line messages line by line. Unknown text simply
stays German, so a missing entry can never break anything.
"""
from __future__ import annotations

import ctypes
import re
import tkinter as tk
from functools import lru_cache
from tkinter import filedialog, messagebox, simpledialog, ttk

LANG_AUTO, LANG_DE, LANG_EN = "auto", "de", "en"
LANGUAGE_LABELS = {LANG_AUTO: "Automatisch (wie Windows)", LANG_DE: "Deutsch",
                   LANG_EN: "English"}

_lang = LANG_DE

KEY_NAMES = {"Strg": "Ctrl", "Umschalt": "Shift", "Entf": "Del", "Leertaste": "Space",
             "Pos1": "Home", "Ende": "End", "Einfg": "Ins", "Bild↑": "PgUp", "Bild↓": "PgDn",
             "Rücktaste": "Backspace", "Rechtsklick": "Right-click"}

CATALOG: dict[str, str] = {
    # --- window, menus
    "ALLES – Dateisuche": "ALLES – File Search",
    "ALLES {0} – Dateisuche": "ALLES {0} – File Search",
    "Einblenden": "Show", "Datei": "File", "Ansicht": "View", "Werkzeuge": "Tools", "Hilfe": "Help",
    "Ergebnisse als CSV exportieren…": "Export results as CSV…",
    "In den Tray minimieren": "Minimize to tray", "Beenden": "Exit", "Vorschau": "Preview",
    "Darstellung": "Appearance", "Darstellung:": "Appearance:",
    "Wie Windows": "Like Windows", "Hell": "Light", "Dunkel": "Dark",
    "Duplikate finden…": "Find duplicates…", "Diagnose": "Diagnostics",
    "Everything starten": "Start Everything",
    "Aktuelle Suche in Everything öffnen": "Open current search in Everything",
    "Eigenen Index neu aufbauen": "Rebuild own index",
    "Laufwerksliste aktualisieren": "Refresh drive list", "Einstellungen…": "Settings…",
    "Suchverlauf löschen": "Clear search history", "Log-Datei öffnen": "Open log file",
    "Tastenkürzel": "Keyboard shortcuts", "Suchsyntax": "Search syntax",
    "Suchsyntax:": "Search syntax:", "Nach Updates suchen…": "Check for updates…",
    "Projektseite auf GitHub": "Project page on GitHub", "Über ALLES": "About ALLES",
    # --- main window
    "Leeren": "Clear", "Übernehmen": "Apply", "Typ": "Type", "Größe": "Size",
    "Geändert": "Modified", "Sortierung": "Sort", "Ordner": "Folder", "Name": "Name",
    "★ Filter": "★ Filters", "Groß/Klein beachten": "Match case", "Ganzes Wort": "Whole word",
    "Regex": "Regex", "Auch im Pfad suchen": "Search in path", "Inhalt:": "Content:",
    "Kopieren": "Copy", "Update verfügbar": "Update available", "Laufwerke": "Drives",
    "Alle": "All", "Initialisiere…": "Starting…", "(alles)": "(everything)",
    "{0} ▲": "{0} ▲", "{0} ▼": "{0} ▼",
    # --- context menu
    "Öffnen": "Open", "Öffnen mit…": "Open with…", "Im Explorer anzeigen": "Show in Explorer",
    "Terminal hier öffnen": "Open terminal here", "In VS Code öffnen": "Open in VS Code",
    "Pfad kopieren": "Copy path", "Name kopieren": "Copy name",
    "Ordnerpfad kopieren": "Copy folder path", "Kopieren nach": "Copy to",
    "Verschieben nach": "Move to", "Umbenennen": "Rename",
    "In diesem Ordner suchen": "Search in this folder", "Eigenschaften": "Properties",
    "In den Papierkorb": "Move to recycle bin", "Ordner wählen…": "Choose folder…",
    "Windows-Kontextmenü…": "Windows context menu…",
    "Windows-Menü gilt nur für einen Ordner: {0} von {1} Elementen.":
        "The Windows menu works for one folder only: {0} of {1} items.",
    "Windows-Kontextmenü nicht verfügbar: {0}": "Windows context menu not available: {0}",
    "F2": "F2", "Rechtsklick": "right click",
    # --- presets / filters (display only - stored values stay German)
    "Alles": "Everything", "Nur Dateien": "Files only", "Nur Ordner": "Folders only",
    "Dokumente": "Documents", "Bilder": "Pictures", "Videos": "Videos", "Musik": "Music",
    "Archive": "Archives", "Programme": "Programs", "Code": "Code", "Egal": "Any",
    "Leer (0 B)": "Empty (0 B)", "< 1 MB": "< 1 MB", "1 - 100 MB": "1 - 100 MB",
    "> 100 MB": "> 100 MB", "> 1 GB": "> 1 GB", "> 10 GB": "> 10 GB",
    "Heute": "Today", "Gestern": "Yesterday", "Diese Woche": "This week",
    "Letzte Woche": "Last week", "Dieser Monat": "This month", "Letzter Monat": "Last month",
    "Dieses Jahr": "This year", "Letztes Jahr": "Last year",
    "Name (A-Z)": "Name (A-Z)", "Name (Z-A)": "Name (Z-A)", "Pfad (A-Z)": "Path (A-Z)",
    "Pfad (Z-A)": "Path (Z-A)", "Größe (auf)": "Size (ascending)",
    "Größe (ab)": "Size (descending)", "Geändert (auf)": "Modified (oldest first)",
    "Geändert (ab)": "Modified (newest first)", "Erweiterung (A-Z)": "Extension (A-Z)",
    "Erweiterung (Z-A)": "Extension (Z-A)", "Große Dateien (> 1 GB)": "Large files (> 1 GB)",
    "Heute geändert": "Modified today", "Fotos dieses Jahr": "Photos this year",
    "Leere Dateien": "Empty files", "★ {0}": "★ {0}",
    "Aktuelle Filter speichern…": "Save current filters…",
    "Gespeicherten Filter löschen": "Delete saved filter",
    "Alle Filter zurücksetzen": "Reset all filters", "Filter speichern": "Save filters",
    "Name für diese Filterkombination:": "Name for this filter combination:",
    "Den aktuellen Suchbegriff mitspeichern?": "Also save the current search text?",
    "Filter „{0}“ gespeichert.": "Filter “{0}” saved.",
    # --- search modes / status
    "Suchmodus: {0}": "Search mode: {0}", "Everything": "Everything",
    "Eigener Index": "Own index", "Automatisch (Everything, sonst eigener Index)":
        "Automatic (Everything, otherwise own index)",
    "Everything (voidtools)": "Everything (voidtools)",
    "Eigener Index (ohne Everything)": "Own index (without Everything)",
    "{0} Treffer": "{0} results",
    "{0} Treffer ({1} geladen, mehr beim Scrollen)":
        "{0} results ({1} loaded, more when scrolling)",
    "{0}  ·  {1} ms  ·  {2}": "{0}  ·  {1} ms  ·  {2}",
    "Interner Fehler: {0} (Details in alles.log)": "Internal error: {0} (details in alles.log)",
    "Index-Fehler: {0}": "Index error: {0}",
    "Index wird aufgebaut: {0} Einträge  ·  {1}": "Building index: {0} entries  ·  {1}",
    "Index wird aufgebaut…": "Building index…",
    "Bereit · eigener Index mit {0} Einträgen": "Ready · own index with {0} entries",
    "Verbunden mit {0}.": "Connected to {0}.", "Everything {0}": "Everything {0}",
    "Everything wird gestartet…": "Starting Everything…",
    "Everything antwortet nicht. Läuft evtl. nur der Dienst? Die Everything-Oberfläche "
    "einmal manuell starten.": "Everything does not respond. Maybe only the service is "
                              "running? Start the Everything app once manually.",
    "Everything läuft nicht (oder nur als Dienst).":
        "Everything is not running (or only as a service).",
    "Everything lädt noch seine Datenbank…": "Everything is still loading its database…",
    "Everything-SDK nicht geladen: {0}": "Everything SDK not loaded: {0}",
    "Everything-Fehler: {0}": "Everything error: {0}",
    "Der Index wurde noch nicht aufgebaut.": "The index has not been built yet.",
    "Im eigenen Index nicht unterstützt: {0}": "Not supported by the own index: {0}",
    "Everything.exe wurde nicht gefunden.": "Everything.exe was not found.",
    "Konnte Everything nicht starten:\n{0}": "Could not start Everything:\n{0}",
    "Fehler": "Error", "Fehler: {0}": "Error: {0}",
    "Inhaltssuche liest Dateien – bitte zusätzlich einen Suchbegriff, Typ, Größe oder Datum "
    "wählen.": "Content search reads files – please also enter a search term or choose a "
              "type, size or date.",
    "Durchsuche Dateiinhalte … (Weitertippen bricht ab)":
        "Searching file contents … (keep typing to cancel)",
    "Meintest du:  {0}": "Did you mean:  {0}",
    "Keine Treffer – meintest du:  {0}": "No results – did you mean:  {0}",
    "Keine Treffer – meintest du:  {0}  (auch: {1})":
        "No results – did you mean:  {0}  (also: {1})",
    "{0} Elemente ausgewählt": "{0} items selected", "{0} Elemente": "{0} items",
    "{0} Elemente öffnen?": "Open {0} items?",
    "{0} in den Papierkorb verschieben?": "Move {0} to the recycle bin?",
    "{0} in den Papierkorb verschoben.": "{0} moved to the recycle bin.",
    "Nicht alles konnte verschoben werden.": "Not everything could be moved.",
    "Nicht alles konnte umbenannt werden:": "Not everything could be renamed:",
    "{0} Element(e) umbenannt – Strg+Z macht es rückgängig.":
        "{0} item(s) renamed – Ctrl+Z undoes it.",
    "Umbenennen rückgängig gemacht.": "Rename undone.",
    "{0} Element(e) werden kopiert …": "Copying {0} item(s) …",
    "{0} Element(e) werden verschoben …": "Moving {0} item(s) …",
    "{0} Element(e) nach {1} kopiert.": "{0} item(s) copied to {1}.",
    "{0} Element(e) nach {1} verschoben.": "{0} item(s) moved to {1}.",
    "Nicht alle Elemente wurden kopiert (abgebrochen oder Fehler).":
        "Not all items were copied (cancelled or error).",
    "Nicht alle Elemente wurden verschoben (abgebrochen oder Fehler).":
        "Not all items were moved (cancelled or error).",
    "Aktion fehlgeschlagen:": "Action failed:",
    "1 Eintrag kopiert.": "1 entry copied.", "{0} Einträge kopiert.": "{0} entries copied.",
    "Keine Ergebnisse zum Exportieren.": "No results to export.",
    "Ergebnisse exportieren": "Export results",
    "{0} Zeilen exportiert nach {1}": "{0} rows exported to {1}",
    "Kein globaler Hotkey frei (alle Kombinationen belegt).":
        "No global hotkey available (all combinations taken).",
    "Gewünschter Hotkey belegt – verwende {0}.": "Desired hotkey is taken – using {0}.",
    "Einstellungen gespeichert.": "Settings saved.",
    "Everything.exe auswählen": "Select Everything.exe",
    "Diagnose läuft…": "Running diagnostics…", "ALLES Diagnose": "ALLES diagnostics",
    "Diagnose fehlgeschlagen: {0}": "Diagnostics failed: {0}",
    # --- updates
    "Suche nach Updates…": "Checking for updates…", "Updates": "Updates",
    "Update-Prüfung fehlgeschlagen:": "Update check failed:",
    "Update auf {0}": "Update to {0}", "ALLES {0} ist aktuell.": "ALLES {0} is up to date.",
    "ALLES ist aktuell.": "ALLES is up to date.", "Update verfügbar…": "Update available…",
    "ALLES {0} ist verfügbar": "ALLES {0} is available", "Installiert: {0}": "Installed: {0}",
    "Keine Versionshinweise.": "No release notes.", "Später": "Later",
    "Diese Version überspringen": "Skip this version",
    "Zur Download-Seite": "Go to download page", "Jetzt aktualisieren": "Update now",
    "Der neue Installer wird geladen, geprüft und still ausgeführt. ALLES startet danach "
    "automatisch neu.": "The new installer is downloaded, verified and run silently. ALLES "
                      "restarts automatically afterwards.",
    "Die neue Version wird geladen, geprüft und ersetzt die portable EXE. Deine Daten bleiben "
    "erhalten.": "The new version is downloaded, verified and replaces the portable EXE. Your "
                "data is kept.",
    "Die neue Version wird geladen, geprüft und ersetzt diese EXE.":
        "The new version is downloaded, verified and replaces this EXE.",
    "Du nutzt ALLES aus dem Quellcode – aktualisiere mit „git pull“ oder lade die neue "
    "Version herunter.": "You run ALLES from source – update with “git pull” or download the "
                         "new version.",
    "Update": "Update", "Im Release fehlt die passende Datei.":
        "The release does not contain the matching file.",
    "Lade {0} …": "Downloading {0} …", "Download fehlgeschlagen: {0}": "Download failed: {0}",
    "Installiere Update …": "Installing update …",
    "Update konnte nicht installiert werden: {0}": "The update could not be installed: {0}",
    "Keine Verbindung zu GitHub: {0}": "No connection to GitHub: {0}",
    "Die Prüfsumme des Downloads stimmt nicht – Update abgebrochen.":
        "The checksum of the download does not match – update cancelled.",
    # --- index info / diagnose
    "Noch kein Index vorhanden.": "No index yet.",
    "Index-Informationen nicht verfügbar.": "Index information not available.",
    "{0} Einträge · {1} auf der Festplatte": "{0} entries · {1} on disk",
    "Zuletzt komplett aufgebaut: {0}": "Last full build: {0}",
    "Live-Überwachung: {0} Ordner": "Live monitoring: {0} folders",
    "Suchmodus: {0}\n": "Search mode: {0}\n", "Indizierte Ordner: {0}": "Indexed folders: {0}",
    "SDK: NICHT geladen ({0})": "SDK: NOT loaded ({0})",
    "Everything antwortet nicht (läuft evtl. nur der Dienst).":
        "Everything does not respond (maybe only the service is running).",
    "Everything {0}, Datenbank geladen": "Everything {0}, database loaded",
    "Everything {0}, Datenbank lädt noch": "Everything {0}, database still loading",
    "Im Everything-Index: {0}": "In the Everything index: {0}",
    "NICHT im Index: {0}": "NOT in the index: {0}",
    "Tipp: FAT/exFAT- und Netzlaufwerke müssen in Everything unter":
        "Tip: FAT/exFAT and network drives have to be added in Everything under",
    "Extras > Optionen > Indizes > Ordner hinzugefügt werden – oder":
        "Tools > Options > Indexes > Folders – or",
    "du nutzt den Suchmodus „Eigener Index“, der sie direkt einliest.":
        "use the search mode “Own index”, which reads them directly.",
    "Der eigene Index wird nur im Suchmodus „Eigener Index“ verwendet. Jetzt zu diesem Modus "
    "wechseln und den Index aufbauen?": "The own index is only used in the search mode “Own "
                                       "index”. Switch to it now and build the index?",
    # --- shortcuts / syntax help
    "{0}\tFenster ein-/ausblenden (global)": "{0}\tShow/hide window (global)",
    "Strg+F / Strg+L\tSuchfeld fokussieren": "Ctrl+F / Ctrl+L\tFocus search box",
    "↓ / ↑\tZwischen Suchfeld und Ergebnissen wechseln":
        "↓ / ↑\tSwitch between search box and results",
    "Alt+↓\tSuchverlauf öffnen": "Alt+↓\tOpen search history", "Enter\tÖffnen": "Enter\tOpen",
    "Strg+Enter\tIm Explorer anzeigen": "Ctrl+Enter\tShow in Explorer",
    "Alt+Enter\tEigenschaften": "Alt+Enter\tProperties",
    "Strg+T\tTerminal im Ordner öffnen": "Ctrl+T\tOpen terminal in folder",
    "Entf\tIn den Papierkorb": "Del\tMove to recycle bin",
    "Strg+C\tPfad(e) kopieren": "Ctrl+C\tCopy path(s)",
    "Strg+Umschalt+C\tName(n) kopieren": "Ctrl+Shift+C\tCopy name(s)",
    "Strg+A\tAlle Ergebnisse markieren": "Ctrl+A\tSelect all results",
    "Strg+P\tVorschau ein/aus": "Ctrl+P\tToggle preview",
    "F5\tSuche wiederholen": "F5\tRepeat search",
    "Strg+S\tAls CSV exportieren": "Ctrl+S\tExport as CSV",
    "Esc\tSuche leeren / in den Tray": "Esc\tClear search / to tray",
    "Strg+Q\tBeenden": "Ctrl+Q\tExit", "F2\tUmbenennen": "F2\tRename",
    "Leerzeichen\tUND:  rechnung 2024": "Space\tAND:  invoice 2024",
    "|\tODER:  jpg | png": "|\tOR:  jpg | png", "!\tNICHT:  !temp": "!\tNOT:  !temp",
    "< >\tGruppe:  <jpg | png> urlaub": "< >\tGroup:  <jpg | png> holiday",
    '" "\tGenaue Phrase:  "mein ordner"': '" "\tExact phrase:  "my folder"',
    "* ?\tPlatzhalter:  *.pdf  bericht?.doc": "* ?\tWildcards:  *.pdf  report?.doc",
    "\\\tPfad:  \\projekte\\ angebot": "\\\tPath:  \\projects\\ offer",
    "Die Filter oben erzeugen diese Syntax automatisch. Sie funktioniert":
        "The filters above create this syntax automatically. It works",
    "mit Everything und mit dem eigenen Index.": "with Everything and with the own index.",
    "Blitzschnelle Dateisuche für Windows – mit Everything oder dem eigenen Index.":
        "Lightning-fast file search for Windows – with Everything or its own index.",
    "Konfiguration: {0}": "Configuration: {0}",
    "MIT-Lizenz · github.com/theStxve/alles": "MIT license · github.com/theStxve/alles",
    "„Everything“ ist ein Produkt von voidtools. ALLES ist kein offizielles voidtools-Produkt.":
        "“Everything” is a product of voidtools. ALLES is not an official voidtools product.",
    "(keiner)": "(none)",
    # --- settings
    "ALLES Einstellungen": "ALLES settings", "Allgemein": "General", "Suche": "Search",
    "Globaler Hotkey (Fenster ein-/ausblenden):": "Global hotkey (show/hide window):",
    "Aufzeichnen…": "Record…", "Treffer pro Seite:": "Results per page:",
    "Schließen-Knopf minimiert in den Tray": "Close button minimizes to the tray",
    "ALLES mit Windows starten (im Tray)": "Start ALLES with Windows (in the tray)",
    "„Mit ALLES durchsuchen“ im Explorer-Kontextmenü":
        "“Search with ALLES” in the Explorer context menu",
    "Laufwerksnamen anzeigen": "Show drive names",
    "Automatisch nach Updates suchen (einmal täglich)": "Check for updates automatically (daily)",
    "Sprache (Neustart nötig):": "Language (restart required):",
    "Automatisch (wie Windows)": "Automatic (like Windows)", "Deutsch": "Deutsch",
    "English": "English", "Suchmodus:": "Search mode:",
    "Ausgeschlossene Ordner (einer pro Zeile):": "Excluded folders (one per line):",
    "Ordnername (z. B. node_modules) oder vollständiger Pfad. Gilt für beide Suchmodi.":
        "Folder name (e.g. node_modules) or full path. Applies to both search modes.",
    "Everything.exe (leer = automatisch suchen):": "Everything.exe (empty = find automatically):",
    "Durchsuchen…": "Browse…",
    "Everything bei Bedarf automatisch im Hintergrund starten":
        "Start Everything in the background when needed",
    "Gefunden: {0}": "Found: {0}",
    "Indizierte Laufwerke und Ordner:": "Indexed drives and folders:",
    "Ordner hinzufügen…": "Add folder…", "Entfernen": "Remove", "Alle Festplatten": "All disks",
    "Beim Start auffrischen, wenn älter als (Minuten, 0 = nie):":
        "Refresh at startup if older than (minutes, 0 = never):",
    "Index jetzt neu aufbauen": "Rebuild index now", "Abbrechen": "Cancel", "Speichern": "Save",
    "Tastenkombination drücken…": "Press a key combination…",
    "Bitte mit Strg, Alt oder Win kombinieren…": "Please combine with Ctrl, Alt or Win…",
    "Ordner für den Index wählen": "Choose a folder for the index",
    "Datei nicht gefunden:": "File not found:",
    "Bitte mindestens einen Ordner für den eigenen Index angeben.":
        "Please add at least one folder for the own index.",
    "Eine Windows-Integration konnte nicht geändert werden.":
        "A Windows integration could not be changed.",
    "Die Sprache wird nach einem Neustart von ALLES umgestellt.":
        "The language changes after restarting ALLES.",
    # --- duplicates
    "Duplikate finden": "Find duplicates",
    "Durchsucht wird die aktuelle Suche inkl. aller Filter.":
        "The current search including all filters is scanned.",
    "Gleicher Inhalt (sicher, liest die Dateien)": "Same content (safe, reads the files)",
    "Gleicher Name + Größe (schnell)": "Same name + size (fast)",
    "Mindestgröße (MB):": "Minimum size (MB):", "Suchen": "Search", "Bereit.": "Ready.",
    "Im Explorer zeigen": "Show in Explorer", "Ältere Kopien markieren": "Select older copies",
    "Lade Dateiliste…": "Loading file list…",
    "{0} Gruppe · {1} belegt durch Kopien · {2} Dateien geprüft in {3} s":
        "{0} group · {1} used by copies · {2} files checked in {3} s",
    "{0} Gruppen · {1} belegt durch Kopien · {2} Dateien geprüft in {3} s":
        "{0} groups · {1} used by copies · {2} files checked in {3} s",
    "{0}  –  {1}× ": "{0}  –  {1}× ",
    "In mindestens einer Gruppe sind alle Kopien markiert. Eine Datei muss übrig bleiben.":
        "In at least one group all copies are selected. One file has to stay.",
    "{0} Datei(en) in den Papierkorb verschieben?": "Move {0} file(s) to the recycle bin?",
    "{0} Datei(en) in den Papierkorb verschoben.": "{0} file(s) moved to the recycle bin.",
    "Nicht alle Dateien konnten verschoben werden.": "Not all files could be moved.",
    "Vergleiche Dateianfänge… {0}/{1}": "Comparing file beginnings… {0}/{1}",
    "Prüfe Inhalte… {0}/{1}": "Checking contents… {0}/{1}",
    # --- rename
    "{0} Elemente umbenennen": "Rename {0} items", "Neuer Name:": "New name:",
    "Suchen und ersetzen": "Find and replace", "Suchen:": "Find:", "Ersetzen:": "Replace:",
    "Regulärer Ausdruck": "Regular expression",
    "Neuer Name mit Platzhaltern": "New name with placeholders", "Muster:": "Pattern:",
    "Start bei:": "Start at:",
    "{name} Name  ·  {n} / {n:03} Nummer  ·  {ext} Endung  ·  {date} / {date:%Y-%m} "
    "Änderungsdatum": "{name} name  ·  {n} / {n:03} number  ·  {ext} extension  ·  {date} / "
                      "{date:%Y-%m} modified date",
    "Bisher": "Current", "Neu": "New", "{0} werden umbenannt": "{0} will be renamed",
    "{0} werden umbenannt · {1} mit Problem: {2}": "{0} will be renamed · {1} with a problem: {2}",
    "Name ist leer": "Name is empty",
    'Unerlaubtes Zeichen (\\ / : * ? " < > |)': 'Invalid character (\\ / : * ? " < > |)',
    "Name darf nicht auf Leerzeichen oder Punkt enden": "Name must not end with a space or dot",
    "Reservierter Windows-Name": "Reserved Windows name", "Name ist zu lang": "Name is too long",
    "Mehrere Dateien bekommen denselben Namen": "Several files would get the same name",
    "Datei mit diesem Namen existiert bereits": "A file with this name already exists",
    "Ungültiger regulärer Ausdruck: {0}": "Invalid regular expression: {0}",
    "Liegt in einem Ordner, der ebenfalls umbenannt wird":
        "Is inside a folder that is renamed too",
    # --- preview
    "Wähle eine Datei aus, um eine Vorschau zu sehen.": "Select a file to see a preview.",
    "Größe: {0} ({1} Bytes)": "Size: {0} ({1} bytes)", "Geändert: {0}": "Modified: {0}",
    "Datei nicht mehr vorhanden": "File no longer exists", "{0}-Datei": "{0} file",
    "Dateiordner": "File folder",
}

_TEMPLATES: list[tuple[re.Pattern, str]] = []


def _compile_templates():
    _TEMPLATES.clear()
    for de, en in CATALOG.items():
        if re.search(r"\{\d\}", de):
            parts = re.split(r"(\{\d\})", de)
            rx = "".join(f"(?P<g{p[1]}>.+?)" if re.fullmatch(r"\{\d\}", p) else re.escape(p)
                         for p in parts)
            _TEMPLATES.append((re.compile(rx + r"\Z", re.S), en))
    # most specific (longest literal text) first
    _TEMPLATES.sort(key=lambda t: -len(re.sub(r"\(\?P<g\d>\.\+\?\)", "", t[0].pattern)))


def detect_windows_language() -> str:
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return LANG_DE if (lang_id & 0x3FF) == 0x07 else LANG_EN
    except (AttributeError, OSError):
        return LANG_DE


def set_language(choice: str) -> str:
    global _lang
    _lang = detect_windows_language() if choice in (None, "", LANG_AUTO) else choice
    if _lang not in (LANG_DE, LANG_EN):
        _lang = LANG_DE
    if _lang == LANG_EN:
        _compile_templates()
    from . import util
    util.STYLE = _lang
    translate.cache_clear()
    return _lang


def language() -> str:
    return _lang


@lru_cache(maxsize=4096)
def translate(text: str) -> str:
    """German -> current language (identity for German)."""
    if _lang == LANG_DE or not text or not isinstance(text, str):
        return text
    if "\n" in text:
        return "\n".join(translate(line) for line in text.split("\n"))
    hit = CATALOG.get(text)
    if hit is not None:
        return hit
    stripped = text.strip()
    if stripped != text and stripped:
        lead = text[:len(text) - len(text.lstrip())]
        trail = text[len(text.rstrip()):]
        return lead + translate(stripped) + trail
    for rx, en in _TEMPLATES:
        m = rx.match(text)
        if m:
            groups = {k[1:]: translate(v) for k, v in m.groupdict().items()}
            return re.sub(r"\{(\d)\}", lambda g, gr=groups: gr.get(g.group(1), g.group(0)), en)
    return text


_ = translate


def keys(text: str) -> str:
    """Translate German key names inside an accelerator like 'Strg+Umschalt+C'."""
    if _lang == LANG_DE or not text:
        return text
    return "+".join(KEY_NAMES.get(p, p) for p in text.split("+"))


# ----------------------------------------------------------------------------- Tk hooks
_installed = False


def install() -> None:
    """Translate text at the Tk boundary. Only needed (and done) for English."""
    global _installed
    if _installed or _lang == LANG_DE:
        return
    _installed = True

    orig_options = tk.Misc._options

    def _options(self, cnf, kw=None):
        def fix(d):
            if not d or not isinstance(d, dict):
                return d
            d = dict(d)
            for key in ("text", "label"):
                if isinstance(d.get(key), str):
                    d[key] = translate(d[key])
            if isinstance(d.get("accelerator"), str):
                d["accelerator"] = keys(d["accelerator"])
            return d
        return orig_options(self, fix(cnf), fix(kw))

    tk.Misc._options = _options

    def wrap_kw(cls, name, fields=("text",)):
        orig = getattr(cls, name)

        def method(self, *args, **kw):
            for f in fields:
                if isinstance(kw.get(f), str):
                    kw[f] = translate(kw[f])
            return orig(self, *args, **kw)
        setattr(cls, name, method)

    wrap_kw(ttk.Treeview, "heading")
    wrap_kw(ttk.Notebook, "add")
    wrap_kw(ttk.Notebook, "tab")

    orig_title = tk.Wm.wm_title

    def wm_title(self, string=None):
        return orig_title(self, translate(string) if isinstance(string, str) else string)
    tk.Wm.wm_title = tk.Wm.title = wm_title

    orig_show = messagebox._show

    def _show(title=None, message=None, _icon=None, _type=None, **options):
        return orig_show(translate(title) if title else title,
                         translate(message) if message else message, _icon, _type, **options)
    messagebox._show = _show

    orig_ask = simpledialog.askstring

    def askstring(title, prompt, **kw):
        return orig_ask(translate(title), translate(prompt), **kw)
    simpledialog.askstring = askstring

    for name in ("askopenfilename", "asksaveasfilename", "askdirectory"):
        orig = getattr(filedialog, name)

        def dialog(*a, _orig=orig, **kw):
            if isinstance(kw.get("title"), str):
                kw["title"] = translate(kw["title"])
            return _orig(*a, **kw)
        setattr(filedialog, name, dialog)


class KeyCombobox(ttk.Combobox):
    """Readonly combobox that shows translated labels but stores the (German) key."""

    def __init__(self, master, variable: tk.StringVar, keys_: list[str], labels=None, **kw):
        self._keys = list(keys_)
        self._labels = [translate(lbl) for lbl in (labels or keys_)]
        super().__init__(master, values=self._labels, state="readonly", **kw)
        self._var = variable
        self.bind("<<ComboboxSelected>>", self._picked, add="+")
        variable.trace_add("write", lambda *_: self._sync())
        self._sync()

    def _picked(self, _event=None):
        i = self.current()
        if 0 <= i < len(self._keys):
            self._var.set(self._keys[i])

    def _sync(self):
        key = self._var.get()
        self.set(self._labels[self._keys.index(key)] if key in self._keys else key)


class TStringVar(tk.StringVar):
    """StringVar for UI messages: everything set into it is translated."""

    def __init__(self, master=None, value=None, name=None):
        super().__init__(master, translate(value) if isinstance(value, str) else value, name)

    def set(self, value):
        super().set(translate(value) if isinstance(value, str) else value)
