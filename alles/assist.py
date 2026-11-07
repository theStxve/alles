"""
Search helpers (pure logic):
  * suggest()           - autocomplete for Everything syntax in the search box
  * natural_to_syntax() - "pdfs von letzter woche größer 5 mb" -> "ext:pdf dm:lastweek size:>5mb"
  * close_words()       - "did you mean" for typos
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from .query import TYPE_PRESETS


@dataclass(frozen=True)
class Suggestion:
    insert: str        # text that replaces the current token
    label: str         # shown in the list
    hint: str = ""     # short explanation


MODIFIERS = [
    ("ext:", "Dateiendung, z. B. ext:pdf;docx"),
    ("size:", "Größe, z. B. size:>100mb"),
    ("dm:", "Änderungsdatum, z. B. dm:lastweek"),
    ("path:", "im ganzen Pfad suchen"),
    ("parent:", "direkt in diesem Ordner"),
    ("file:", "nur Dateien"),
    ("folder:", "nur Ordner"),
    ("regex:", "regulärer Ausdruck"),
    ("content:", "im Dateiinhalt suchen"),
    ("case:", "Groß/Klein beachten"),
    ("ww:", "ganzes Wort"),
]
VALUES = {
    "dm": [("today", "heute"), ("yesterday", "gestern"), ("thisweek", "diese Woche"),
           ("lastweek", "letzte Woche"), ("thismonth", "dieser Monat"),
           ("lastmonth", "letzter Monat"), ("thisyear", "dieses Jahr"),
           ("lastyear", "letztes Jahr"), ("last7days", "letzte 7 Tage"),
           ("last30days", "letzte 30 Tage")],
    "size": [(">1mb", "größer als 1 MB"), (">100mb", "größer als 100 MB"),
             (">1gb", "größer als 1 GB"), ("<1mb", "kleiner als 1 MB"),
             ("1mb..10mb", "zwischen 1 und 10 MB"), ("empty", "leer"), ("tiny", "< 10 KB"),
             ("small", "10–100 KB"), ("medium", "100 KB–1 MB"), ("large", "1–16 MB"),
             ("huge", "16–128 MB"), ("gigantic", "> 128 MB")],
    "ext": [(e, "") for e in ("pdf", "docx", "xlsx", "pptx", "txt", "md", "jpg", "png", "gif",
                              "mp4", "mkv", "mp3", "zip", "7z", "exe", "msi", "py", "js",
                              "html", "css", "json", "csv", "iso", "lnk")],
}
VALUES["datemodified"] = VALUES["dm"]
_TOKEN_START = re.compile(r'[\s<>|!]')


def current_token(text: str, cursor: int) -> tuple[int, str]:
    """Start index and text of the token that ends at the cursor."""
    start = cursor
    while start > 0:
        ch = text[start - 1]
        if ch in "<>" and start >= 2 and text[start - 2] in ":<>=":
            start -= 1  # size:>1mb - a comparison, not a group bracket
            continue
        if _TOKEN_START.match(ch):
            break
        start -= 1
    return start, text[start:cursor]


def suggest(text: str, cursor: int, limit: int = 8) -> tuple[int, list[Suggestion]]:
    """Returns (token start, suggestions). Replace text[start:cursor] with .insert."""
    start, token = current_token(text, cursor)
    if not token or '"' in token:
        return start, []
    low = token.lower()
    if ":" in low:
        mod, value = low.split(":", 1)
        options = VALUES.get(mod, [])
        prefix = token[:len(mod) + 1]
        if mod == "ext" and ";" in value:  # complete the last extension of a list
            head, value = value.rsplit(";", 1)
            prefix += head + ";"
        out = [Suggestion(prefix + v, v, h) for v, h in options
               if v.startswith(value) and v != value]
        return start, out[:limit]
    out = [Suggestion(m, m, h) for m, h in MODIFIERS if m.startswith(low) and m != low]
    return start, out[:limit]


# ----------------------------------------------------------------------------- natural language
_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"\s*(kb|mb|gb|tb|k|m|g|t|byte|bytes)\b"
_TYPE_WORDS = {
    r"pdfs?(?:[- ]dateien)?": "ext:pdf",
    r"word[- ]?(?:dateien|dokumente)?": "ext:doc;docx",
    r"excel[- ]?(?:dateien|tabellen)?|tabellen": "ext:xls;xlsx;csv",
    r"powerpoints?|präsentationen": "ext:ppt;pptx",
    r"bilder|fotos|photos|bild": TYPE_PRESETS["Bilder"],
    r"videos?|filme": TYPE_PRESETS["Videos"],
    r"musik|songs|lieder|mp3s?": TYPE_PRESETS["Musik"],
    r"dokumente": TYPE_PRESETS["Dokumente"],
    r"archive|zips?": TYPE_PRESETS["Archive"],
    r"programme|exe-dateien": TYPE_PRESETS["Programme"],
    r"code|quellcode": TYPE_PRESETS["Code"],
    r"ordner|verzeichnisse": "folder:",
}
_DATE_PHRASES = [
    (r"(?:von |vom |seit )?heute", "dm:today"),
    (r"(?:von |vom )?gestern", "dm:yesterday"),
    (r"(?:von |aus |in )?(?:dieser|diese) woche", "dm:thisweek"),
    (r"(?:von |aus |in )?(?:der )?(?:letzte[nr]?|vorige[nr]?) woche", "dm:lastweek"),
    (r"(?:von |aus |in )?(?:diesem|diesen|dieser) monat", "dm:thismonth"),
    (r"(?:von |aus |im )?(?:letzte[nmr]?|vorige[nmr]?) monat", "dm:lastmonth"),
    (r"(?:von |aus )?(?:diesem|dieses) jahr", "dm:thisyear"),
    (r"(?:von |aus |im )?(?:letzte[nms]?|vorige[nms]?) jahr", "dm:lastyear"),
]
_STOPWORDS = {"alle", "die", "der", "das", "den", "dem", "des", "meine", "mein", "meiner",
              "von", "vom", "mit", "und", "dateien", "datei", "files", "zeige", "zeig", "mir",
              "finde", "such", "suche", "nach", "welche", "aus", "im", "in", "ein", "eine",
              "geändert", "bearbeitet", "erstellt", "als", "sind", "ist", "wo", "gib"}


def natural_to_syntax(text: str) -> str | None:
    """Translate a German sentence into Everything syntax, or None if it isn't one."""
    s = " " + text.strip().lower() + " "
    if not s.strip() or any(c in s for c in ':<>|"*?\\'):
        return None  # already syntax
    parts: list[str] = []

    def take(pattern, value):
        nonlocal s
        rx = re.compile(r"(?<!\w)(?:" + pattern + r")(?!\w)")
        if rx.search(s):
            s = rx.sub(" ", s, count=1)
            parts.append(value)
            return True
        return False

    m = re.search(r"(?:größer|grösser|über|mehr als|ab|mindestens)\s*(?:als\s*)?" + _NUM + _UNIT,
                  s)
    if m:
        parts.append(f"size:>{m.group(1).replace(',', '.')}{_unit(m.group(2))}")
        s = s.replace(m.group(0), " ", 1)
    m = re.search(r"(?:kleiner|unter|weniger als|bis|höchstens)\s*(?:als\s*)?" + _NUM + _UNIT, s)
    if m:
        parts.append(f"size:<{m.group(1).replace(',', '.')}{_unit(m.group(2))}")
        s = s.replace(m.group(0), " ", 1)
    m = re.search(r"(?:in den |der )?(?:letzten|vergangenen|seit)\s+(\d+)\s+tag(?:en|e)?", s)
    if m:
        parts.append(f"dm:last{m.group(1)}days")
        s = s.replace(m.group(0), " ", 1)
    for pattern, value in _DATE_PHRASES:
        if take(pattern, value):
            break
    m = re.search(r"(?:aus|von|im jahr|vom jahr|in)\s+((?:19|20)\d{2})(?!\d)", s)
    if m:
        parts.append(f"dm:{m.group(1)}")
        s = s.replace(m.group(0), " ", 1)
    if take(r"leere?n?(?: dateien)?", "file: size:0"):
        pass
    m = re.search(r"(?:im ordner|in ordner|im verzeichnis|in den|in|im)\s+"
                  r"(downloads|desktop|dokumenten?|documents|bildern|musik|videos|appdata|"
                  r"programme|program files)", s)
    if m:
        parts.append("\\" + m.group(1).rstrip("n") + "\\" if m.group(1) == "dokumenten"
                     else "\\" + m.group(1) + "\\")
        s = s.replace(m.group(0), " ", 1)
    m = re.search(r"im ordner\s+(\S+)", s)
    if m:
        parts.append(f"\\{m.group(1)}\\")
        s = s.replace(m.group(0), " ", 1)
    for pattern, value in _TYPE_WORDS.items():
        if take(pattern, value):
            break
    if not parts:
        return None
    words = [w for w in re.split(r"\s+", s) if w and w not in _STOPWORDS]
    return " ".join(parts + words)


def _unit(u: str) -> str:
    u = u.lower()
    return {"k": "kb", "m": "mb", "g": "gb", "t": "tb", "byte": "", "bytes": ""}.get(u, u)


# ----------------------------------------------------------------------------- typos
def is_simple_term(text: str) -> bool:
    t = text.strip()
    return bool(re.fullmatch(r"[\w\-.äöüÄÖÜß]{4,}", t))


def close_words(term: str, names, n: int = 3, cutoff: float = 0.75) -> list[str]:
    """Words from file names that look like `term` (for 'Meintest du …?')."""
    term = term.lower()
    words = set()
    for name in names:
        stem = name.rsplit(".", 1)[0].lower()
        for w in re.split(r"[^\wäöüß]+", stem):
            if len(w) >= 3 and w != term:
                words.add(w)
        if len(words) > 20_000:
            break
    return difflib.get_close_matches(term, list(words), n=n, cutoff=cutoff)


def probe_fragments(term: str) -> list[str]:
    """Short pieces of a (misspelled) word used to fetch candidate names."""
    t = term.lower()
    if len(t) < 4:
        return [t]
    return list(dict.fromkeys([t[:3], t[-3:], t[len(t) // 2 - 1:len(t) // 2 + 2]]))
