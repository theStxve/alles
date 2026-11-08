"""
SQLite storage for the built-in index.

Layout
  dirs(id, path, path_lc)        every indexed folder; roots have negative ids
  entries(id, parent, name, ...) every file/folder; folders share their id with dirs

Full rebuilds are written to a separate file and swapped in atomically, so the
old index keeps answering searches while a new one is built.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from .syntax import Compiled

FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS dirs(
    id INTEGER PRIMARY KEY, path TEXT NOT NULL, path_lc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entries(
    id INTEGER PRIMARY KEY, parent INTEGER NOT NULL, name TEXT NOT NULL,
    name_lc TEXT NOT NULL, ext TEXT NOT NULL, size INTEGER, mtime INTEGER,
    is_dir INTEGER NOT NULL);
"""
INDEXES = """
CREATE INDEX IF NOT EXISTS i_dirs_path ON dirs(path_lc);
CREATE INDEX IF NOT EXISTS i_parent ON entries(parent);
CREATE INDEX IF NOT EXISTS i_size ON entries(size);
CREATE INDEX IF NOT EXISTS i_mtime ON entries(mtime);
CREATE INDEX IF NOT EXISTS i_ext ON entries(ext);
"""

# Never worth indexing; matched against the folder name
ALWAYS_SKIP_NAMES = {"$recycle.bin", "system volume information", "$windows.~bt",
                     "$windows.~ws", "$sysreset", "config.msi"}

# The unary "+" turns each sort key into an expression, so SQLite filters via the
# best WHERE index and sorts the hits with a top-N sorter instead of walking an
# ordered index with one table lookup per row (10x faster on big indexes).
SORT_SQL = {
    1: "+e.name_lc", 2: "+e.name_lc DESC",
    3: "+d.path_lc, e.name_lc", 4: "+d.path_lc DESC, e.name_lc DESC",
    5: "+e.size, e.name_lc", 6: "+e.size DESC, e.name_lc",
    7: "+e.ext, e.name_lc", 8: "+e.ext DESC, e.name_lc",
    13: "+e.mtime, e.name_lc", 14: "+e.mtime DESC, e.name_lc",
}
COUNT_CAP = 100_000


@dataclass
class Hit:
    path: str
    name: str
    folder: str
    size: int | None
    mtime: float | None
    ext: str
    is_dir: bool


def norm_root(path: str) -> str:
    """'c:\\' -> 'C:', 'D:\\Data\\' -> 'D:\\Data' (no trailing backslash)."""
    p = os.path.normpath(path).rstrip("\\/")
    if len(p) >= 2 and p[1] == ":":
        p = p[0].upper() + p[1:]
    return p


def dedupe_roots(roots: Iterable[str]) -> list[str]:
    """Normalise roots and drop ones that live inside another root."""
    out: list[str] = []
    for r in sorted({norm_root(r) for r in roots if r and r.strip()}, key=str.lower):
        low = r.lower()
        if not any(low == o.lower() or low.startswith(o.lower() + "\\") for o in out):
            out.append(r)
    return out


def display_folder(path: str) -> str:
    return path + "\\" if len(path) == 2 and path[1] == ":" else path


def split_ext(name: str, is_dir: bool) -> str:
    if is_dir:
        return ""
    dot = name.rfind(".")
    return name[dot + 1:].lower() if dot > 0 else ""


def classify_exclude(raw: str) -> tuple[str, str]:
    """-> ('name'|'abs'|'fragment'|'skip', normalised value). Shared by both modes."""
    e = (raw or "").strip().replace("/", "\\").rstrip("\\")
    if not e or any(c in e for c in '*?"<>|'):
        return "skip", ""
    if ":" in e or e.startswith("\\\\"):
        return "abs", e
    e = e.strip("\\")
    return ("fragment" if "\\" in e else "name"), e


class Excluder:
    """Decides which folders are skipped while indexing.

    Same rules as query.exclusion_terms() uses for Everything:
      'node_modules'      -> any folder with that name
      'C:\\Windows\\WinSxS' -> that folder (absolute path)
      'Users\\Temp'       -> any folder whose path ends with that fragment
    Entries with wildcards are ignored (Everything can't express them the same way).
    """

    def __init__(self, patterns: Iterable[str] = ()):
        self.names: set[str] = set(ALWAYS_SKIP_NAMES)
        self.paths: list[str] = []
        self.fragments: list[str] = []
        for kind, value in (classify_exclude(p) for p in patterns):
            if kind == "name":
                self.names.add(value.lower())
            elif kind == "abs":
                self.paths.append(norm_root(value).lower())
            elif kind == "fragment":
                self.fragments.append("\\" + value.lower())

    def skip_dir(self, full_lc: str, name_lc: str) -> bool:
        if name_lc in self.names:
            return True
        for p in self.paths:
            if full_lc == p or full_lc.startswith(p + "\\"):
                return True
        return any(full_lc.endswith(f) or f + "\\" in full_lc for f in self.fragments)


def _regexp(pattern, value, _cache={}):  # noqa: B006 - intentional memo cache
    if value is None:
        return False
    rx = _cache.get(pattern)
    if rx is None:
        if len(_cache) > 64:
            _cache.clear()
        rx = _cache[pattern] = re.compile(pattern)
    return rx.search(value) is not None


CONTENT_MAX_BYTES = 50 * 1024 * 1024
_CONTENT_CHUNK = 1024 * 1024


def content_match(path, size, is_dir, needle) -> bool:
    """True if the file contains `needle` (case-insensitive; UTF-8, UTF-16, cp1252)."""
    if is_dir or not needle or size is None or size > CONTENT_MAX_BYTES:
        return False
    low = needle.lower()
    patterns = {low.encode("utf-8"), low.encode("utf-16-le"), low.encode("cp1252", "ignore")}
    patterns.discard(b"")
    ascii_only = low.isascii()
    keep = max(len(p) for p in patterns)
    keep += keep % 2  # even overlap keeps every chunk aligned for UTF-16 decoding
    tail = b""
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(_CONTENT_CHUNK)
                if not chunk:
                    return False
                data = tail + chunk
                if ascii_only:
                    hay = data.lower()  # bytes.lower() only touches ASCII - fine here
                    if any(p in hay for p in patterns):
                        return True
                else:
                    for enc in ("utf-8", "cp1252"):
                        if low in data.decode(enc, "ignore").lower():
                            return True
                    if low in data.decode("utf-16-le", "ignore").lower():
                        return True
                tail = data[-keep:] if keep else b""
    except OSError:
        return False


def connect(path: str, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = "file:" + path.replace("\\", "/") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=10)
    else:
        conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.create_function("REGEXP", 2, _regexp, deterministic=True)
    conn.create_function("CONTENT_MATCH", 4, content_match)
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-32000")
    return conn


# ----------------------------------------------------------------------------- scanning
class Scanner:
    """Walks folders with os.scandir and writes rows in big batches."""

    BATCH = 20_000

    def __init__(self, conn: sqlite3.Connection, excluder: Excluder,
                 next_id: int, progress: Callable[[int, str], None] | None = None,
                 should_stop: Callable[[], bool] | None = None):
        self.conn = conn
        self.ex = excluder
        self.next_id = next_id
        self.progress = progress
        self.should_stop = should_stop or (lambda: False)
        self.count = 0
        self._entries: list[tuple] = []
        self._dirs: list[tuple] = []

    def _flush(self):
        if self._dirs:
            self.conn.executemany(
                "INSERT OR REPLACE INTO dirs(id, path, path_lc) VALUES (?,?,?)", self._dirs)
            self._dirs.clear()
        if self._entries:
            self.conn.executemany(
                "INSERT OR REPLACE INTO entries(id, parent, name, name_lc, ext, size, mtime,"
                " is_dir) VALUES (?,?,?,?,?,?,?,?)", self._entries)
            self._entries.clear()

    def scan(self, path: str, dir_id: int) -> None:
        """Index everything below `path` (which must already exist in dirs)."""
        stack = [(path, dir_id)]
        while stack:
            if self.should_stop():
                break
            folder, fid = stack.pop()
            try:
                it = os.scandir(folder + "\\")
            except OSError:
                continue
            with it:
                for de in it:
                    try:
                        st = de.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    name = de.name
                    attrs = getattr(st, "st_file_attributes", 0)
                    is_dir = bool(attrs & FILE_ATTRIBUTE_DIRECTORY) or (
                        not attrs and de.is_dir(follow_symlinks=False))
                    full = folder + "\\" + name
                    name_lc = name.lower()
                    if is_dir and self.ex.skip_dir(full.lower(), name_lc):
                        continue
                    eid = self.next_id
                    self.next_id += 1
                    self._entries.append((eid, fid, name, name_lc, split_ext(name, is_dir),
                                          None if is_dir else st.st_size, int(st.st_mtime),
                                          1 if is_dir else 0))
                    if is_dir and not attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                        self._dirs.append((eid, full, full.lower()))
                        stack.append((full, eid))
            if len(self._entries) >= self.BATCH:
                self.count += len(self._entries)
                self._flush()
                if self.progress:
                    self.progress(self.count, folder)
        self.count += len(self._entries)
        self._flush()


# ----------------------------------------------------------------------------- store
class IndexStore:
    def __init__(self, path: str):
        self.path = path
        self.tmp_path = path + ".building"
        self._lock = threading.RLock()
        self._reader: sqlite3.Connection | None = None
        self._writer: sqlite3.Connection | None = None
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    # -- connections
    def exists(self) -> bool:
        return os.path.isfile(self.path)

    def _get_reader(self) -> sqlite3.Connection | None:
        if self._reader is None and self.exists():
            self._reader = connect(self.path)
        return self._reader

    def _get_writer(self) -> sqlite3.Connection | None:
        if self._writer is None and self.exists():
            self._writer = connect(self.path)
        return self._writer

    def close(self):
        with self._lock:
            for c in (self._reader, self._writer):
                if c is not None:
                    try:
                        c.close()
                    except sqlite3.Error:
                        pass
            self._reader = self._writer = None

    # -- metadata
    def meta(self) -> dict:
        with self._lock:
            conn = self._get_reader()
            if conn is None:
                return {}
            try:
                return dict(conn.execute("SELECT key, value FROM meta").fetchall())
            except sqlite3.Error:
                return {}

    def stats(self) -> dict:
        with self._lock:
            conn = self._get_reader()
            if conn is None:
                return {"entries": 0, "roots": []}
            n = conn.execute("SELECT count(*) FROM entries").fetchone()[0]
            roots = [r[0] for r in conn.execute("SELECT path FROM dirs WHERE id < 0")]
        return {"entries": n, "roots": roots, "bytes": os.path.getsize(self.path)}

    # -- full rebuild
    def rebuild(self, roots: list[str], excludes: list[str],
                progress: Callable[[int, str], None] | None = None,
                should_stop: Callable[[], bool] | None = None) -> int:
        """Build a fresh index in a temp file and swap it in. Returns entry count."""
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(self.tmp_path + suffix)
            except FileNotFoundError:
                pass
        conn = connect(self.tmp_path)
        try:
            conn.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;" + SCHEMA)
            ex = Excluder(excludes)
            scanner = Scanner(conn, ex, 1, progress, should_stop)
            norm = dedupe_roots(roots)
            conn.executemany("INSERT INTO dirs(id, path, path_lc) VALUES (?,?,?)",
                             [(-(i + 1), r, r.lower()) for i, r in enumerate(norm)])
            for i, r in enumerate(norm):
                if should_stop and should_stop():
                    break
                if os.path.isdir(r + "\\"):
                    scanner.scan(r, -(i + 1))
            if should_stop and should_stop():
                conn.close()
                os.remove(self.tmp_path)
                return -1
            if progress:
                progress(scanner.count, "Suchindex wird optimiert…")
            conn.executescript(INDEXES)
            conn.executemany("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)", [
                ("built_at", str(time.time())), ("roots", "\n".join(norm)),
                ("excludes", "\n".join(excludes)), ("schema", "1")])
            conn.commit()
            conn.execute("PRAGMA journal_mode=WAL")
            conn.close()
        except BaseException:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            raise
        with self._lock:
            self.close()
            os.replace(self.tmp_path, self.path)
        return scanner.count

    # -- search
    def search(self, compiled: Compiled, sort: int, offset: int, limit: int,
               is_stale: Callable[[], bool] = lambda: False) -> tuple[list[Hit], int]:
        order = SORT_SQL.get(sort, SORT_SQL[1])
        base = f"FROM entries e JOIN dirs d ON d.id = e.parent WHERE {compiled.where}"
        sql = (f"SELECT d.path, e.name, e.size, e.mtime, e.ext, e.is_dir {base} "
               f"ORDER BY {order} LIMIT ? OFFSET ?")
        with self._lock:
            conn = self._get_reader()
            if conn is None:
                return [], 0
            conn.set_progress_handler(lambda: 1 if is_stale() else 0, 20_000)
            try:
                rows = conn.execute(sql, [*compiled.params, limit, offset]).fetchall()
                if len(rows) < limit:
                    total = offset + len(rows)
                elif "CONTENT_MATCH" in compiled.where:
                    # counting would read every candidate file a second time
                    total = offset + len(rows) + 1
                else:
                    total = conn.execute(
                        f"SELECT count(*) FROM (SELECT 1 {base} LIMIT {COUNT_CAP})",
                        compiled.params).fetchone()[0]
            finally:
                conn.set_progress_handler(None, 0)
        hits = []
        for folder, name, size, mtime, ext, is_dir in rows:
            disp = display_folder(folder)
            hits.append(Hit(disp.rstrip("\\") + "\\" + name, name, disp, size, mtime, ext,
                            bool(is_dir)))
        return hits, total

    def sample_names(self, fragments: list[str], limit: int = 5000) -> list[str]:
        """File names containing any of the fragments (candidates for typo hints)."""
        frags = [f.lower() for f in fragments if f]
        if not frags:
            return []
        where = " OR ".join("instr(name_lc, ?) > 0" for _ in frags)
        with self._lock:
            conn = self._get_reader()
            if conn is None:
                return []
            rows = conn.execute(f"SELECT name FROM entries WHERE {where} LIMIT ?",
                                [*frags, limit]).fetchall()
        return [r[0] for r in rows]

    # -- incremental updates (from the file watcher)
    def apply_changes(self, changes: list[tuple[str, str]], excludes: Iterable[str]) -> int:
        """changes: list of (action, full_path) with action in add/remove/modify."""
        with self._lock:
            conn = self._get_writer()
            if conn is None:
                return 0
            ex = Excluder(excludes)
            applied = 0
            with conn:
                for action, path in changes:
                    try:
                        if action == "remove":
                            applied += self._remove(conn, path)
                        elif action == "add":
                            applied += self._add(conn, path, ex)
                        elif action == "modify":
                            applied += self._modify(conn, path, ex)
                    except (OSError, sqlite3.Error):
                        continue
            return applied

    @staticmethod
    def _dir_id(conn, path: str) -> int | None:
        row = conn.execute("SELECT id FROM dirs WHERE path_lc = ?",
                           (norm_root(path).lower(),)).fetchone()
        return row[0] if row else None

    def _remove(self, conn, path: str) -> int:
        parent, name = os.path.split(norm_root(path))
        pid = self._dir_id(conn, parent)
        if pid is None:
            return 0
        row = conn.execute("SELECT id, is_dir FROM entries WHERE parent = ? AND name_lc = ?",
                           (pid, name.lower())).fetchone()
        if not row:
            return 0
        eid, is_dir = row
        conn.execute("DELETE FROM entries WHERE id = ?", (eid,))
        if is_dir:
            p = norm_root(path).lower()
            ids = [r[0] for r in conn.execute(
                "SELECT id FROM dirs WHERE path_lc = ? OR (path_lc > ? AND path_lc < ?)",
                (p, p + "\\", p + "]"))]
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                marks = ",".join("?" * len(chunk))
                conn.execute(f"DELETE FROM entries WHERE parent IN ({marks})", chunk)
                conn.execute(f"DELETE FROM dirs WHERE id IN ({marks})", chunk)
        return 1

    def _add(self, conn, path: str, ex: Excluder) -> int:
        path = norm_root(path)
        parent, name = os.path.split(path)
        pid = self._dir_id(conn, parent)
        if pid is None or not name:
            return 0
        st = os.stat(path, follow_symlinks=False)
        attrs = getattr(st, "st_file_attributes", 0)
        is_dir = bool(attrs & FILE_ATTRIBUTE_DIRECTORY)
        if is_dir and ex.skip_dir(path.lower(), name.lower()):
            return 0
        self._remove(conn, path)  # replace (also clears an old subtree)
        cur = conn.execute(
            "INSERT INTO entries(parent, name, name_lc, ext, size, mtime, is_dir)"
            " VALUES (?,?,?,?,?,?,?)",
            (pid, name, name.lower(), split_ext(name, is_dir), None if is_dir else st.st_size,
             int(st.st_mtime), 1 if is_dir else 0))
        if is_dir and not attrs & FILE_ATTRIBUTE_REPARSE_POINT:
            eid = cur.lastrowid
            conn.execute("INSERT OR REPLACE INTO dirs(id, path, path_lc) VALUES (?,?,?)",
                         (eid, path, path.lower()))
            next_id = conn.execute("SELECT coalesce(max(id), 0) + 1 FROM entries").fetchone()[0]
            Scanner(conn, ex, next_id).scan(path, eid)
        return 1

    def _modify(self, conn, path: str, ex: Excluder) -> int:
        path = norm_root(path)
        parent, name = os.path.split(path)
        pid = self._dir_id(conn, parent)
        if pid is None:
            return 0
        st = os.stat(path, follow_symlinks=False)
        is_dir = bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_DIRECTORY)
        cur = conn.execute(
            "UPDATE entries SET size = ?, mtime = ? WHERE parent = ? AND name_lc = ?",
            (None if is_dir else st.st_size, int(st.st_mtime), pid, name.lower()))
        if cur.rowcount == 0:
            return self._add(conn, path, ex)
        return 1
