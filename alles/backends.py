"""
Search backends. Both take the same Query (Everything syntax + flags) and
return the same Row objects, so the UI does not care where results come from.
"""
from __future__ import annotations

import datetime as _dt
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import everything_sdk as es
from .index.store import COUNT_CAP, IndexStore
from .index.syntax import Flags, UnsupportedSyntax, compile_query
from .query import Query
from .util import fmt_date, fmt_size

BACKEND_AUTO = "auto"
BACKEND_EVERYTHING = "everything"
BACKEND_INDEX = "index"
BACKEND_LABELS = {BACKEND_AUTO: "Automatisch (Everything, sonst eigener Index)",
                  BACKEND_EVERYTHING: "Everything (voidtools)",
                  BACKEND_INDEX: "Eigener Index (ohne Everything)"}

REQUEST_FLAGS = (es.REQUEST_FULL_PATH_AND_FILE_NAME | es.REQUEST_SIZE |
                 es.REQUEST_DATE_MODIFIED | es.REQUEST_EXTENSION | es.REQUEST_ATTRIBUTES)

_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)


def unix_to_local(ts: float | None) -> _dt.datetime | None:
    if ts is None:
        return None
    try:
        return _dt.datetime.fromtimestamp(ts)
    except (OverflowError, OSError, ValueError):
        try:  # Windows can't do negative timestamps
            local = _dt.datetime.now().astimezone().tzinfo
            return (_EPOCH + _dt.timedelta(seconds=ts)).astimezone(local).replace(tzinfo=None)
        except (OverflowError, ValueError):
            return None


@dataclass(frozen=True)
class Row:
    path: str
    name: str
    folder: str
    size: int | None
    modified: _dt.datetime | None
    ext: str
    is_dir: bool

    def display(self):
        kind = "Ordner" if self.is_dir else self.ext.lower()
        size = "" if self.is_dir else fmt_size(self.size)
        return (self.folder, size, fmt_date(self.modified), kind)


@dataclass
class SearchResult:
    rows: list[Row]
    total: int
    elapsed_ms: float
    capped: bool = False  # total is a lower bound ("100.000+")


@dataclass
class Status:
    ready: bool
    kind: str  # ok / warn / err / info
    message: str
    busy: bool = False


class SearchError(RuntimeError):
    pass


class EverythingBackend:
    """Everything 1.4 (SDK2, window messages) or Everything 1.5 (SDK3, named pipe)."""

    key = BACKEND_EVERYTHING
    label = "Everything"

    def __init__(self):
        self.sdk: es.EverythingSDK | None = None
        self.sdk3 = None  # everything_sdk3.Everything3
        self.error: str | None = None
        self.lock = threading.Lock()
        self.api = 2  # which SDK answered last

    def load(self) -> bool:
        if self.sdk is None:
            try:
                self.sdk = es.EverythingSDK()
            except (OSError, FileNotFoundError) as exc:
                self.error = str(exc)
        if self.sdk3 is None:
            try:
                from .everything_sdk3 import Everything3
                self.sdk3 = Everything3()
            except (OSError, FileNotFoundError):
                self.sdk3 = None
        if self.available:
            self.error = None
        return self.available

    @property
    def available(self) -> bool:
        return self.sdk is not None or self.sdk3 is not None

    def probe(self) -> tuple[bool, bool, tuple[int, int, int]]:
        """(alive, db_loaded, version) - tries Everything 1.4 first, then 1.5."""
        with self.lock:
            if self.sdk is not None:
                ver = self.sdk.get_version()
                if ver[0]:
                    self.api = 2
                    return (True, self.sdk.is_db_loaded(), ver)
            if self.sdk3 is not None and self.sdk3.connect():
                ver = self.sdk3.version()
                if ver[0]:
                    self.api = 3
                    return (True, self.sdk3.is_db_loaded(), ver)
                self.sdk3.disconnect()
        return (False, False, (0, 0, 0))

    def status(self) -> Status:
        if not self.available:
            return Status(False, "err", f"Everything-SDK nicht geladen: {self.error}")
        alive, db, ver = self.probe()
        if not alive:
            return Status(False, "err", "Everything läuft nicht (oder nur als Dienst).")
        if not db:
            return Status(False, "warn", "Everything lädt noch seine Datenbank…", busy=True)
        return Status(True, "ok", f"Everything {ver[0]}.{ver[1]}.{ver[2]}")

    def search(self, q: Query, offset: int, limit: int,
               is_stale: Callable[[], bool]) -> SearchResult | None:
        if self.api == 3 and self.sdk3 is not None:
            return self._search3(q, offset, limit, is_stale)
        with self.lock:
            if is_stale() or self.sdk is None:
                return None
            s = self.sdk
            s.reset()
            s.set_search(q.search)
            s.set_match_case(q.match_case)
            s.set_match_whole_word(q.whole_word)
            s.set_match_path(q.match_path)
            s.set_sort(q.sort)
            s.set_request_flags(REQUEST_FLAGS)
            s.set_max(limit)
            s.set_offset(offset)
            t0 = time.perf_counter()
            try:
                num = s.query(wait=True)
            except es.EverythingError as exc:
                raise SearchError(f"Everything-Fehler: {exc}") from exc
            total = s.get_total_results()
            rows = []
            for i in range(num):
                if i % 256 == 0 and is_stale():
                    return None
                path = s.get_result_full_path(i)
                if not path:
                    continue
                folder, name = os.path.split(path)
                rows.append(Row(path, name or path, folder, s.get_result_size(i),
                                _naive(s.get_result_date_modified(i)),
                                s.get_result_extension(i), s.is_result_folder(i)))
            return SearchResult(rows, total, (time.perf_counter() - t0) * 1000)

    def _search3(self, q: Query, offset: int, limit: int,
                 is_stale: Callable[[], bool]) -> SearchResult | None:
        with self.lock:
            if is_stale():
                return None
            t0 = time.perf_counter()
            try:
                found = self.sdk3.search(q.search, q.match_case, q.whole_word, q.match_path,
                                         q.sort, offset, limit, True, is_stale)
            except OSError as exc:
                raise SearchError(f"Everything-Fehler: {exc}") from exc
            if found is None:
                return None
            items, total = found
            rows = []
            for it in items:
                folder, name = os.path.split(it.path)
                rows.append(Row(it.path, name or it.path, folder,
                                None if it.is_dir else it.size,
                                _naive(es.filetime_to_datetime(it.filetime)), it.ext.lower(),
                                it.is_dir))
            return SearchResult(rows, total, (time.perf_counter() - t0) * 1000)

    def _names(self, search: str, limit: int) -> tuple[list[str], int]:
        """Full paths + total count for a search (diagnostics, typo hints)."""
        with self.lock:
            if self.api == 3 and self.sdk3 is not None:
                try:
                    found = self.sdk3.search(search, limit=limit, details=False)
                except OSError:
                    return [], 0
                return ([it.path for it in found[0]], found[1]) if found else ([], 0)
            if self.sdk is None:
                return [], 0
            s = self.sdk
            s.reset()
            s.set_search(search)
            s.set_max(limit)
            s.set_request_flags(es.REQUEST_FULL_PATH_AND_FILE_NAME)
            try:
                n = s.query(wait=True)
            except es.EverythingError:
                return [], 0
            return [s.get_result_full_path(i) for i in range(n)], s.get_total_results()

    def sample_names(self, fragments: list[str], limit: int = 5000) -> list[str]:
        if not fragments:
            return []
        return [os.path.basename(p) for p in self._names(" | ".join(fragments), limit)[0]]

    def count_in(self, search: str) -> int:
        return self._names(search, 1)[1]

    @property
    def dll_path(self) -> str:
        if self.api == 3 and self.sdk3 is not None:
            return self.sdk3.dll_path
        return self.sdk.dll_path if self.sdk else "-"

    def close(self):
        with self.lock:
            if self.sdk is not None:
                self.sdk.cleanup()
            if self.sdk3 is not None:
                self.sdk3.disconnect()


def _naive(value: _dt.datetime | None) -> _dt.datetime | None:
    return value.replace(tzinfo=None) if value is not None and value.tzinfo else value


class IndexBackend:
    key = BACKEND_INDEX
    label = "Eigener Index"

    def __init__(self, store: IndexStore):
        self.store = store
        self.service = None  # set by the app (IndexService)

    @property
    def available(self) -> bool:
        return True

    def status(self) -> Status:
        st = self.service.state if self.service else None
        if st and st.building:
            # constant message: progress is shown separately, otherwise every progress
            # tick would look like a status change and re-run the search
            return Status(self.store.exists(), "warn", "Index wird aufgebaut…", busy=True)
        if not self.store.exists():
            return Status(False, "warn", "Der Index wurde noch nicht aufgebaut.")
        return Status(True, "ok", "Eigener Index")

    def search(self, q: Query, offset: int, limit: int,
               is_stale: Callable[[], bool]) -> SearchResult | None:
        t0 = time.perf_counter()
        try:
            compiled = compile_query(q.search, Flags(q.match_case, q.whole_word, q.match_path))
        except UnsupportedSyntax as exc:
            raise SearchError(f"Im eigenen Index nicht unterstützt: {exc}") from exc
        try:
            hits, total = self.store.search(compiled, q.sort, offset, limit, is_stale)
        except Exception as exc:  # sqlite3.OperationalError on interrupt etc.
            if is_stale():
                return None
            raise SearchError(f"Index-Fehler: {exc}") from exc
        rows = [Row(h.path, h.name, h.folder, h.size, unix_to_local(h.mtime), h.ext, h.is_dir)
                for h in hits]
        return SearchResult(rows, total, (time.perf_counter() - t0) * 1000,
                            capped=total >= COUNT_CAP)

    def sample_names(self, fragments: list[str], limit: int = 5000) -> list[str]:
        return self.store.sample_names(fragments, limit)

    def close(self):
        if self.service:
            self.service.stop()
        self.store.close()
