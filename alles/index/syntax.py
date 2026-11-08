"""
Translate (a practical subset of) Everything's search syntax into SQL for the
built-in index.

Supported:
  space = AND, | = OR, ! = NOT, < > grouping, "quoted phrases",
  wildcards * ?, terms containing a backslash match the full path,
  ext:  file:  folder:  size:  dm:/datemodified:  path:  parent:  regex:
  plus the global flags match case / whole word / match path.

Anything else that looks like an Everything modifier raises UnsupportedSyntax
so the UI can tell the user instead of silently returning wrong results.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

# SQL expressions (table aliases: e = entries, d = dirs of the parent folder)
NAME = "e.name"
NAME_LC = "e.name_lc"
PATH = "(d.path || '\\' || e.name)"
PATH_LC = "(d.path_lc || '\\' || e.name_lc)"

SUPPORTED_MODIFIERS = {"ext", "file", "folder", "size", "dm", "datemodified", "path",
                       "parent", "regex", "nopath", "case", "nocase", "ww", "noww",
                       "content"}
KNOWN_UNSUPPORTED = {
    "utf8content", "ansicontent", "dc", "datecreated", "da", "dateaccessed",
    "dr", "daterun", "attrib", "attributes", "len", "child", "childcount", "dupe",
    "sizedupe", "namedupe", "empty", "type", "startwith", "endwith", "wfn",
    "wholefilename", "infolder", "depth", "root", "shell", "count", "width", "height",
    "dimensions", "bitdepth", "orientation", "title", "artist", "album", "genre",
    "comment", "track", "year", "frn", "fsi", "recentchange", "rc", "runcount",
    "diacritics", "nodiacritics", "prefix", "suffix", "wildcards", "nowildcards",
    "utf16content", "utf16becontent", "filelist", "filelistfilename", "zip", "nozip",
}

SIZE_UNITS = {"": 1, "b": 1, "kb": 1024, "k": 1024, "mb": 1024**2, "m": 1024**2,
              "gb": 1024**3, "g": 1024**3, "tb": 1024**4, "t": 1024**4}
SIZE_KEYWORDS = {  # Everything's named sizes
    "empty": (0, 0), "tiny": (0, 10 * 1024), "small": (10 * 1024, 100 * 1024),
    "medium": (100 * 1024, 1024**2), "large": (1024**2, 16 * 1024**2),
    "huge": (16 * 1024**2, 128 * 1024**2), "gigantic": (128 * 1024**2, None),
}


class UnsupportedSyntax(ValueError):
    """Raised for Everything features the built-in index cannot evaluate."""


# ----------------------------------------------------------------------------- AST
@dataclass
class Term:
    modifier: str  # "" for plain text
    value: str
    quoted: bool = False


@dataclass
class Not:
    child: object


@dataclass
class And:
    items: list = field(default_factory=list)


@dataclass
class Or:
    items: list = field(default_factory=list)


# ----------------------------------------------------------------------------- lexer
_MOD_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*):(.*)$", re.S)


def tokenize(text: str) -> list[str | Term]:
    """Split into Terms and the operators '|', '!', '<', '>'."""
    tokens: list[str | Term] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "|<>":
            tokens.append(ch)
            i += 1
            continue
        if ch == "!":
            tokens.append("!")
            i += 1
            continue
        # read one term (quotes may appear anywhere inside it)
        buf, quoted, in_q = [], False, False
        while i < n:
            ch = text[i]
            if ch == '"':
                in_q = not in_q
                quoted = True
                i += 1
                continue
            if not in_q and (ch.isspace() or ch in "|<>"):
                # size:<1mb / dm:>=2024 -> comparison operators belong to the value
                is_cmp = ch in "<>" and buf and buf[-1] in ":<>=" and _MOD_RE.match(
                    "".join(buf))
                if not is_cmp:
                    break
            buf.append(ch)
            i += 1
        raw = "".join(buf)
        m = _MOD_RE.match(raw)
        mod = m.group(1).lower() if m else ""
        if m and (mod in SUPPORTED_MODIFIERS or mod in KNOWN_UNSUPPORTED):
            tokens.append(Term(mod, m.group(2), quoted))
        else:
            tokens.append(Term("", raw, quoted))
    return tokens


# ----------------------------------------------------------------------------- parser
class _Parser:
    def __init__(self, tokens):
        self.t = tokens
        self.i = 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def parse_and(self, closing=None) -> And:
        node = And()
        while True:
            tok = self.peek()
            if tok is None or tok == closing:
                return node
            if tok == ">":  # stray closing bracket: ignore
                self.take()
                continue
            node.items.append(self.parse_or(closing))

    def parse_or(self, closing):
        items = [self.parse_not(closing)]
        while self.peek() == "|":
            self.take()
            if self.peek() in (None, closing, "|"):
                break
            items.append(self.parse_not(closing))
        items = [x for x in items if x is not None]
        return items[0] if len(items) == 1 else Or(items)

    def parse_not(self, closing):
        negate = False
        while self.peek() == "!":
            self.take()
            negate = not negate
        node = self.parse_atom(closing)
        return Not(node) if negate and node is not None else node

    def parse_atom(self, closing):
        tok = self.take()
        if tok == "<":
            inner = self.parse_and(">")
            if self.peek() == ">":
                self.take()
            return inner
        if isinstance(tok, Term):
            return tok
        return None  # '|' at weird places etc.


def parse(text: str) -> And:
    return _Parser(tokenize(text)).parse_and()


# ----------------------------------------------------------------------------- dates
def _start_of_day(d: _dt.date) -> _dt.datetime:
    return _dt.datetime(d.year, d.month, d.day)


def _month_start(year: int, month: int) -> _dt.datetime:
    while month < 1:
        month += 12
        year -= 1
    while month > 12:
        month -= 12
        year += 1
    return _dt.datetime(year, month, 1)


def date_range(value: str, now: _dt.datetime | None = None
               ) -> tuple[_dt.datetime | None, _dt.datetime | None]:
    """Everything date value -> [start, end) in local time. None = open end."""
    now = now or _dt.datetime.now()
    v = value.strip().lower()
    today = _start_of_day(now.date())
    day = _dt.timedelta(days=1)
    week_start = today - _dt.timedelta(days=today.weekday())  # Monday
    consts = {
        "today": (today, today + day),
        "yesterday": (today - day, today),
        "thisweek": (week_start, week_start + 7 * day),
        "lastweek": (week_start - 7 * day, week_start),
        "thismonth": (_month_start(now.year, now.month), _month_start(now.year, now.month + 1)),
        "lastmonth": (_month_start(now.year, now.month - 1), _month_start(now.year, now.month)),
        "thisyear": (_dt.datetime(now.year, 1, 1), _dt.datetime(now.year + 1, 1, 1)),
        "lastyear": (_dt.datetime(now.year - 1, 1, 1), _dt.datetime(now.year, 1, 1)),
    }
    if v in consts:
        return consts[v]
    m = re.fullmatch(r"(last|past)(\d+)(days|weeks|months|years)", v)
    if m:
        n, unit = int(m.group(2)), m.group(3)
        if unit == "days":
            return today - (n - 1) * day, None
        if unit == "weeks":
            return now - _dt.timedelta(weeks=n), None
        if unit == "months":
            return _month_start(now.year, now.month - n).replace(day=1), None
        return _dt.datetime(now.year - n, 1, 1), None
    for op in (">=", "<=", ">", "<"):
        if v.startswith(op):
            start, end = _abs_date(v[len(op):])
            return {">=": (start, None), ">": (end, None),
                    "<=": (None, end), "<": (None, start)}[op]
    if ".." in v:
        a, b = v.split("..", 1)
        return (_abs_date(a)[0] if a else None, _abs_date(b)[1] if b else None)
    if v.count("-") == 1 and re.fullmatch(r"\d{4}-\d{4}", v):  # 2020-2022
        a, b = v.split("-")
        return _abs_date(a)[0], _abs_date(b)[1]
    return _abs_date(v)


def _abs_date(v: str) -> tuple[_dt.datetime, _dt.datetime]:
    v = v.strip()
    m = re.fullmatch(r"(\d{4})(?:[-/.](\d{1,2})(?:[-/.](\d{1,2}))?)?", v)
    if not m:
        m2 = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", v)  # German 31.12.2024
        if not m2:
            raise UnsupportedSyntax(f"dm:{v}")
        d = _dt.datetime(int(m2.group(3)), int(m2.group(2)), int(m2.group(1)))
        return d, d + _dt.timedelta(days=1)
    y = int(m.group(1))
    if m.group(3):
        d = _dt.datetime(y, int(m.group(2)), int(m.group(3)))
        return d, d + _dt.timedelta(days=1)
    if m.group(2):
        mo = int(m.group(2))
        return _month_start(y, mo), _month_start(y, mo + 1)
    return _dt.datetime(y, 1, 1), _dt.datetime(y + 1, 1, 1)


# ----------------------------------------------------------------------------- sizes
def parse_size(text: str) -> int:
    m = re.fullmatch(r"\s*(\d+(?:[.,]\d+)?)\s*([a-z]*)\s*", text.lower())
    if not m or m.group(2) not in SIZE_UNITS:
        raise UnsupportedSyntax(f"size:{text}")
    return int(float(m.group(1).replace(",", ".")) * SIZE_UNITS[m.group(2)])


def size_condition(value: str) -> tuple[str, list]:
    v = value.strip().lower()
    if v in SIZE_KEYWORDS:
        lo, hi = SIZE_KEYWORDS[v]
        if lo == hi:
            return "e.size = ?", [lo]
        if hi is None:
            return "e.size > ?", [lo]
        return "(e.size > ? AND e.size <= ?)", [lo, hi]
    if ".." in v or (re.fullmatch(r"[\d.,]+[a-z]*-[\d.,]+[a-z]*", v)):
        a, b = re.split(r"\.\.|-", v, maxsplit=1)
        return "(e.size >= ? AND e.size <= ?)", [parse_size(a), parse_size(b)]
    for op in (">=", "<=", ">", "<", "="):
        if v.startswith(op):
            return f"e.size {op} ?", [parse_size(v[len(op):])]
    return "e.size = ?", [parse_size(v)]


# ----------------------------------------------------------------------------- compiler
@dataclass
class Flags:
    match_case: bool = False
    whole_word: bool = False
    match_path: bool = False


@dataclass
class Compiled:
    where: str
    params: list
    needs_path: bool  # whether the SQL references the parent folder (d.*)


def _glob_escape(text: str) -> str:
    return re.sub(r"([\[\]])", r"[\1]", text)


def _wildcard_to_regex(text: str) -> str:
    return "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in text)


def _reads_files(node) -> bool:
    if isinstance(node, Term):
        return node.modifier == "content"
    if isinstance(node, Not):
        return _reads_files(node.child)
    if isinstance(node, (And, Or)):
        return any(_reads_files(x) for x in node.items)
    return False


def needs_content_guard(text: str) -> bool:
    """True if the query searches file contents without any other positive term
    (that would read every file on the disk)."""
    tokens = tokenize(text)
    has_content, other = False, False
    negated = False
    for tok in tokens:
        if tok == "!":
            negated = True
            continue
        if isinstance(tok, Term):
            if tok.modifier == "content":
                has_content = True
            elif not negated and (tok.value or tok.modifier in ("file", "folder")):
                other = True
        negated = False
    return has_content and not other


class _Compiler:
    def __init__(self, flags: Flags, now=None):
        self.flags = flags
        self.now = now

    def compile(self, node) -> tuple[str, list]:
        if isinstance(node, And):
            # content: reads files -> always evaluate it after every cheap condition
            items = sorted(node.items, key=_reads_files)
            parts = [self.compile(x) for x in items]
            parts = [p for p in parts if p[0]]
            if not parts:
                return "", []
            return "(" + " AND ".join(p[0] for p in parts) + ")", sum((p[1] for p in parts), [])
        if isinstance(node, Or):
            parts = [self.compile(x) for x in node.items]
            parts = [p for p in parts if p[0]]
            if not parts:
                return "", []
            return "(" + " OR ".join(p[0] for p in parts) + ")", sum((p[1] for p in parts), [])
        if isinstance(node, Not):
            sql, params = self.compile(node.child)
            return (f"NOT {sql}", params) if sql else ("", [])
        if isinstance(node, Term):
            return self.term(node)
        return "", []

    # -- text matching
    def text(self, value: str, force_path: bool = False) -> tuple[str, list]:
        if value == "":
            return "", []
        f = self.flags
        use_path = force_path or f.match_path or "\\" in value or "/" in value
        value = value.replace("/", "\\") if use_path else value
        has_wild = "*" in value or "?" in value
        if f.whole_word or (has_wild and f.match_case):
            body = _wildcard_to_regex(value) if has_wild else re.escape(value)
            if has_wild:
                pattern = "^" + body + "$"
            else:
                pattern = r"(?<!\w)" + body + r"(?!\w)"
            if not f.match_case:
                pattern = "(?i)" + pattern
            return f"{PATH if use_path else NAME} REGEXP ?", [pattern]
        if has_wild:
            target = PATH_LC if use_path else NAME_LC
            return f"{target} GLOB ?", [_glob_escape(value.lower())]
        needle = value if f.match_case else value.lower()
        name_col, path_col = (NAME, PATH) if f.match_case else (NAME_LC, PATH_LC)
        if not use_path:
            return f"instr({name_col}, ?) > 0", [needle]
        # Full-path substring without building the path for every row:
        # either the folder path (+ '\') contains the needle, or the match runs
        # into the file name - then the name must contain the last segment.
        dir_col = "path" if f.match_case else "path_lc"
        seg = needle.rsplit("\\", 1)[-1]
        in_dirs = (f"e.parent IN (SELECT id FROM dirs WHERE instr({dir_col} || '\\', ?) > 0)")
        if not seg:
            return in_dirs, [needle]
        return (f"({in_dirs} OR (instr({name_col}, ?) > 0 AND instr({path_col}, ?) > 0))",
                [needle, seg, needle])

    def term(self, t: Term) -> tuple[str, list]:
        mod, value = t.modifier, t.value
        if mod == "content":
            needle = value.strip()
            if not needle:
                return "", []
            # evaluated last by SQLite thanks to its position in the AND chain; the
            # function reads the file (see store.content_match)
            return f"CONTENT_MATCH({PATH}, e.size, e.is_dir, ?)", [needle]
        if mod in KNOWN_UNSUPPORTED:
            raise UnsupportedSyntax(f"{mod}:")
        if mod == "":
            return self.text(value)
        if mod == "ext":
            exts = [x.strip().lstrip(".").lower() for x in value.split(";") if x.strip()]
            if not exts:
                return "e.ext = ''", []
            return f"(e.is_dir = 0 AND e.ext IN ({','.join('?' * len(exts))}))", exts
        if mod in ("file", "folder"):
            cond = "e.is_dir = 0" if mod == "file" else "e.is_dir = 1"
            sql, params = self.text(value)
            return (f"({cond} AND {sql})", params) if sql else (cond, [])
        if mod == "size":
            sql, params = size_condition(value)
            return f"(e.is_dir = 0 AND {sql})", params
        if mod in ("dm", "datemodified"):
            start, end = date_range(value, self.now)
            conds, params = [], []
            if start is not None:
                conds.append("e.mtime >= ?")
                params.append(start.timestamp())
            if end is not None:
                conds.append("e.mtime < ?")
                params.append(end.timestamp())
            return ("(" + " AND ".join(conds) + ")" if conds else ""), params
        if mod == "path":
            v = value.replace("/", "\\")
            if re.fullmatch(r"[A-Za-z]:\\?", v):  # whole drive -> indexed prefix match
                root = v[:2].lower()
                return ("e.parent IN (SELECT id FROM dirs WHERE path_lc = ? OR path_lc GLOB ?)",
                        [root, root + "\\*"])
            return self.text(v, force_path=True)
        if mod == "parent":
            p = value.replace("/", "\\").rstrip("\\").lower()
            return "e.parent IN (SELECT id FROM dirs WHERE path_lc = ?)", [p]
        if mod == "regex":
            pattern = value if self.flags.match_case else "(?i)" + value
            try:
                re.compile(pattern)
            except re.error as exc:
                raise UnsupportedSyntax(f"Ungültiger regulärer Ausdruck: {exc}") from exc
            target = PATH if self.flags.match_path else NAME
            return f"{target} REGEXP ?", [pattern]
        # case:/nocase:/ww:/noww:/nopath: apply a flag to the following text
        sub = Flags(self.flags.match_case, self.flags.whole_word, self.flags.match_path)
        if mod == "case":
            sub.match_case = True
        elif mod == "nocase":
            sub.match_case = False
        elif mod == "ww":
            sub.whole_word = True
        elif mod == "noww":
            sub.whole_word = False
        elif mod == "nopath":
            sub.match_path = False
        return _Compiler(sub, self.now).text(value)


def compile_query(text: str, flags: Flags | None = None, now=None) -> Compiled:
    sql, params = _Compiler(flags or Flags(), now).compile(parse(text))
    return Compiled(sql or "1", params, "d." in sql)
