"""Duplicate detection over search results (name+size, or size+content hash)."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable, Iterable

MODE_NAME_SIZE = "name_size"
MODE_CONTENT = "content"
QUICK_BYTES = 64 * 1024
CHUNK = 1024 * 1024


def _hash(path: str, limit: int | None, stop: Callable[[], bool]) -> bytes | None:
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as f:
            remaining = limit
            while True:
                if stop():
                    return None
                n = CHUNK if remaining is None else min(CHUNK, remaining)
                if n <= 0:
                    break
                data = f.read(n)
                if not data:
                    break
                h.update(data)
                if remaining is not None:
                    remaining -= len(data)
    except OSError:
        return None
    return h.digest()


def _refine(groups: Iterable[list], key: Callable, stop) -> list[list]:
    out = []
    for group in groups:
        buckets = defaultdict(list)
        for row in group:
            if stop():
                return out
            k = key(row)
            if k is not None:
                buckets[k].append(row)
        out.extend(b for b in buckets.values() if len(b) > 1)
    return out


def find_duplicates(rows: Iterable, mode: str = MODE_NAME_SIZE, min_size: int = 1,
                    progress: Callable[[str], None] | None = None,
                    stop: Callable[[], bool] = lambda: False) -> list[list]:
    """Group duplicate files. Rows need .path .name .size .is_dir. Biggest waste first."""
    files = [r for r in rows if not r.is_dir and r.size is not None and r.size >= min_size]
    by_size = defaultdict(list)
    for r in files:
        by_size[r.size].append(r)
    groups = [g for g in by_size.values() if len(g) > 1]
    if mode == MODE_NAME_SIZE:
        groups = _refine(groups, lambda r: r.name.lower(), stop)
    else:
        total = sum(len(g) for g in groups)
        done = [0]

        def quick(r):
            done[0] += 1
            if progress and done[0] % 25 == 0:
                progress(f"Vergleiche Dateianfänge… {done[0]}/{total}")
            return _hash(r.path, QUICK_BYTES, stop)

        groups = _refine(groups, quick, stop)
        total = sum(len(g) for g in groups)
        done[0] = 0

        def full(r):
            done[0] += 1
            if progress and (done[0] % 10 == 0 or r.size > 50 * CHUNK):
                progress(f"Prüfe Inhalte… {done[0]}/{total}")
            if r.size <= QUICK_BYTES:
                return b"small"  # quick hash already covered the whole file
            return _hash(r.path, None, stop)

        groups = _refine(groups, full, stop)
    for g in groups:
        g.sort(key=lambda r: r.path.lower())
    groups.sort(key=lambda g: g[0].size * (len(g) - 1), reverse=True)
    return groups


def wasted_bytes(groups: list[list]) -> int:
    return sum(g[0].size * (len(g) - 1) for g in groups)
