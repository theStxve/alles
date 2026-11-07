"""
Translate the friendly UI state into a real Everything search string.

This module is pure Python (no Tk, no ctypes) so it can be unit-tested on any OS.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import everything_sdk as es

TYPE_PRESETS: dict[str, str | None] = {
    "Alles": None,
    "Nur Dateien": "file:",
    "Nur Ordner": "folder:",
    "Dokumente": "ext:doc;docx;pdf;txt;rtf;odt;ods;odp;xls;xlsx;ppt;pptx;csv;md",
    "Bilder": "ext:png;jpg;jpeg;gif;bmp;webp;tiff;tif;svg;heic;avif;ico;raw",
    "Videos": "ext:mp4;mkv;avi;mov;wmv;flv;webm;m4v;mpg;mpeg",
    "Musik": "ext:mp3;wav;flac;aac;ogg;m4a;wma;opus",
    "Archive": "ext:zip;rar;7z;tar;gz;tgz;bz2;xz;zst;iso",
    "Programme": "ext:exe;msi;bat;cmd;ps1;lnk",
    "Code": "ext:py;js;ts;jsx;tsx;cpp;c;h;hpp;java;kt;cs;html;htm;css;scss;json;"
            "xml;yaml;yml;toml;php;rb;go;rs;sh;sql",
}

SIZE_PRESETS: dict[str, str | None] = {
    "Egal": None,
    "Leer (0 B)": "size:0",
    "< 1 MB": "size:<1mb",
    "1 - 100 MB": "size:1mb..100mb",
    "> 100 MB": "size:>100mb",
    "> 1 GB": "size:>1gb",
    "> 10 GB": "size:>10gb",
}

DATE_PRESETS: dict[str, str | None] = {
    "Egal": None,
    "Heute": "dm:today",
    "Gestern": "dm:yesterday",
    "Diese Woche": "dm:thisweek",
    "Letzte Woche": "dm:lastweek",
    "Dieser Monat": "dm:thismonth",
    "Letzter Monat": "dm:lastmonth",
    "Dieses Jahr": "dm:thisyear",
    "Letztes Jahr": "dm:lastyear",
}

# label -> (ascending, descending) is not needed; each label is one sort.
SORT_OPTIONS: dict[str, int] = {
    "Name (A-Z)": es.SORT_NAME_ASCENDING,
    "Name (Z-A)": es.SORT_NAME_DESCENDING,
    "Pfad (A-Z)": es.SORT_PATH_ASCENDING,
    "Pfad (Z-A)": es.SORT_PATH_DESCENDING,
    "Größe (auf)": es.SORT_SIZE_ASCENDING,
    "Größe (ab)": es.SORT_SIZE_DESCENDING,
    "Geändert (auf)": es.SORT_DATE_MODIFIED_ASCENDING,
    "Geändert (ab)": es.SORT_DATE_MODIFIED_DESCENDING,
    "Erweiterung (A-Z)": es.SORT_EXTENSION_ASCENDING,
    "Erweiterung (Z-A)": es.SORT_EXTENSION_DESCENDING,
}

# Result column -> (sort label ascending, sort label descending)
COLUMN_SORTS: dict[str, tuple[str, str]] = {
    "name": ("Name (A-Z)", "Name (Z-A)"),
    "folder": ("Pfad (A-Z)", "Pfad (Z-A)"),
    "size": ("Größe (auf)", "Größe (ab)"),
    "modified": ("Geändert (auf)", "Geändert (ab)"),
    "type": ("Erweiterung (A-Z)", "Erweiterung (Z-A)"),
}

DEFAULT_SORT = "Name (A-Z)"

DEFAULT_EXCLUDES = ["C:\\Windows\\WinSxS", "node_modules", ".git", "__pycache__"]

# Built-in filter presets (users can save their own on top)
BUILTIN_PRESETS: dict[str, dict] = {
    "Große Dateien (> 1 GB)": {"type": "Nur Dateien", "size": "> 1 GB", "date": "Egal",
                               "sort": "Größe (ab)"},
    "Heute geändert": {"type": "Alles", "size": "Egal", "date": "Heute",
                       "sort": "Geändert (ab)"},
    "Fotos dieses Jahr": {"type": "Bilder", "size": "Egal", "date": "Dieses Jahr",
                          "sort": "Geändert (ab)"},
    "Leere Dateien": {"type": "Nur Dateien", "size": "Leer (0 B)", "date": "Egal",
                      "sort": "Pfad (A-Z)"},
}


@dataclass
class SearchOptions:
    """Plain snapshot of everything the user selected in the UI."""

    text: str = ""
    all_drives: bool = True
    drives: list[str] = field(default_factory=list)
    type: str = "Alles"
    size: str = "Egal"
    date: str = "Egal"
    sort: str = DEFAULT_SORT
    match_case: bool = False
    whole_word: bool = False
    regex: bool = False
    match_path: bool = False
    content: str = ""  # search inside files (content:)


@dataclass(frozen=True)
class Query:
    search: str
    match_case: bool
    whole_word: bool
    match_path: bool
    sort: int


def _quote(term: str) -> str:
    """Wrap a term in quotes if Everything would otherwise split it."""
    if term and (" " in term or "|" in term) and '"' not in term:
        return f'"{term}"'
    return term


def drive_scope(drives: list[str]) -> str:
    """Build an OR-group restricting results to the given drive roots."""
    roots = []
    for d in drives:
        d = d.strip().rstrip("\\/")
        if not d:
            continue
        roots.append(f"path:{d.upper()}\\")
    if not roots:
        return ""
    if len(roots) == 1:
        return roots[0]
    # In Everything '|' binds tighter than the implicit AND (space), but the
    # brackets make the intent explicit and robust against user text.
    return "<" + " | ".join(roots) + ">"


def exclusion_terms(excludes) -> list[str]:
    r"""Hide the contents of excluded folders: 'node_modules' -> !"\node_modules\"."""
    from .index.store import classify_exclude  # same rules as the built-in index

    terms = []
    for raw in excludes or ():
        kind, e = classify_exclude(raw)
        if kind == "abs":  # that folder
            terms.append(f'!"{e}\\"')
        elif kind in ("name", "fragment"):  # folder name / path fragment anywhere
            terms.append(f'!"\\{e}\\"')
    return terms


def has_restricting_filter(opts: SearchOptions) -> bool:
    """Content search reads files - only allow it together with another filter."""
    return bool(opts.text.strip() or opts.type != "Alles" or opts.size != "Egal"
                or opts.date != "Egal")


def build_query(opts: SearchOptions, excludes=()) -> Query:
    """Return the Everything query for the given UI options."""
    parts: list[str] = []

    if not opts.all_drives:
        scope = drive_scope(opts.drives)
        if scope:
            parts.append(scope)

    for preset, table in ((opts.type, TYPE_PRESETS),
                          (opts.size, SIZE_PRESETS),
                          (opts.date, DATE_PRESETS)):
        value = table.get(preset)
        if value:
            parts.append(value)

    text = opts.text.strip()
    if text:
        # Everything_SetRegex() would turn the WHOLE query into a regex and break
        # the generated filters (ext:, size:, ...). The regex: modifier only
        # applies to the user's text.
        parts.append("regex:" + _quote(text) if opts.regex else text)

    content = opts.content.strip().replace('"', "")
    if content:
        parts.append(f'content:"{content}"')

    parts += exclusion_terms(excludes)

    return Query(
        search=" ".join(parts),
        match_case=opts.match_case,
        whole_word=opts.whole_word,
        match_path=opts.match_path,
        sort=SORT_OPTIONS.get(opts.sort, SORT_OPTIONS[DEFAULT_SORT]),
    )
