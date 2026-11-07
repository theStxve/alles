"""Background service: builds the index, watches folders, applies live changes."""
from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .store import IndexStore, dedupe_roots
from .watcher import FolderWatcher, coalesce

log = logging.getLogger("alles.index")

APPLY_INTERVAL = 0.7
OVERFLOW_REBUILD_COOLDOWN = 600


@dataclass
class IndexState:
    building: bool = False
    scanned: int = 0
    current: str = ""
    entries: int = 0
    built_at: float = 0.0
    error: str = ""
    watching: int = 0


class IndexService:
    def __init__(self, store: IndexStore, roots: Callable[[], list[str]],
                 excludes: Callable[[], list[str]],
                 on_state: Callable[[IndexState], None] | None = None,
                 max_age: float = 3600.0):
        self.store = store
        self._roots = roots
        self._excludes = excludes
        self.on_state = on_state or (lambda s: None)
        self.max_age = max_age
        self.state = IndexState()
        self._pending: list[tuple[str, str]] = []
        self._pending_lock = threading.Lock()
        self._stop = threading.Event()
        self._build_lock = threading.Lock()
        self._cancel_build = threading.Event()
        self._watchers: list[FolderWatcher] = []
        self._last_overflow_rebuild = 0.0
        self._rebuild_due_at = 0.0  # deferred rebuild after an overflow inside the cooldown
        self._started = False
        # our own database lives on an indexed drive: never index/watch it
        self._own_dir = os.path.normcase(os.path.dirname(os.path.abspath(store.path)))

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        """Non-blocking: stats, watchers and the rebuild check run in the background."""
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._apply_loop, name="index-apply", daemon=True).start()
        threading.Thread(target=self._startup, name="index-start", daemon=True).start()

    def excludes(self) -> list[str]:
        return [*self._excludes(), self._own_dir]

    def _startup(self):
        self._refresh_stats()
        self._start_watchers()
        meta = self.store.meta()
        roots_changed = meta.get("roots", "") != "\n".join(dedupe_roots(self._roots()))
        excl_changed = meta.get("excludes", "") != "\n".join(self.excludes())
        age = time.time() - float(meta.get("built_at", 0) or 0)
        if not self.store.exists() or roots_changed or excl_changed or age > self.max_age:
            self.rebuild()
        else:
            self._emit()

    def stop(self):
        self._stop.set()
        self._cancel_build.set()
        for w in self._watchers:
            w.stop()
        self._watchers = []
        self.store.close()

    def _start_watchers(self):
        for w in self._watchers:
            w.stop()
        self._watchers = []
        for root in dedupe_roots(self._roots()):
            w = FolderWatcher(root, self._on_events, self._on_overflow)
            w.start()
            self._watchers.append(w)
        self.state.watching = len(self._watchers)

    def reconfigure(self):
        """Roots or excludes changed: restart watchers and rebuild."""
        self._start_watchers()
        self.rebuild(force=True)

    # ------------------------------------------------------------------ rebuild
    def rebuild(self, force: bool = False):
        if self.state.building:
            if not force:
                return
            self._cancel_build.set()
        threading.Thread(target=self._rebuild_worker, name="index-build", daemon=True).start()

    def _rebuild_worker(self):
        with self._build_lock:  # wait for a cancelled build to finish
            if self._stop.is_set():
                return
            self._cancel_build.clear()
            self.state.building = True
            self.state.scanned = 0
            self.state.error = ""
            self._emit()
            t0 = time.time()
            last_emit = [0.0]

            def progress(count, folder):
                self.state.scanned = count
                self.state.current = folder
                now = time.time()
                if now - last_emit[0] > 0.3:
                    last_emit[0] = now
                    self._emit()

            try:
                n = self.store.rebuild(self._roots(), self.excludes(), progress,
                                       lambda: self._cancel_build.is_set() or self._stop.is_set())
                if n >= 0:
                    log.info("index rebuilt: %d entries in %.1fs", n, time.time() - t0)
            except Exception as exc:  # noqa: BLE001 - report any failure in the UI
                log.exception("index rebuild failed")
                self.state.error = str(exc)
            finally:
                self.state.building = False
                self.state.current = ""
                self._refresh_stats()
                self._emit()

    # ------------------------------------------------------------------ live updates
    def _on_events(self, root, events):
        own = self._own_dir + os.sep
        # writes to our own index.db would otherwise feed back into the index forever
        events = [e for e in events if not os.path.normcase(e[1]).startswith(own)]
        if events:
            with self._pending_lock:
                self._pending.extend(events)

    def _on_overflow(self, root):
        log.warning("watch buffer overflow on %s", root)
        now = time.time()
        if now - self._last_overflow_rebuild > OVERFLOW_REBUILD_COOLDOWN:
            self._last_overflow_rebuild = now
            self.rebuild()
        else:  # don't drop it: re-sync once the cooldown is over
            self._rebuild_due_at = self._last_overflow_rebuild + OVERFLOW_REBUILD_COOLDOWN

    def _apply_loop(self):
        while not self._stop.wait(APPLY_INTERVAL):
            due = self._rebuild_due_at
            if due and time.time() >= due and not self.state.building:
                self._rebuild_due_at = 0.0
                self._last_overflow_rebuild = time.time()
                self.rebuild()
            if self.state.building:
                continue  # keep queuing; applied to the new index after the swap
            with self._pending_lock:
                batch, self._pending = self._pending, []
            if not batch:
                continue
            try:
                changed = self.store.apply_changes(coalesce(batch), self.excludes())
            except Exception:  # noqa: BLE001
                log.exception("applying %d changes failed", len(batch))
                continue
            if changed:
                self._refresh_stats(cheap=True)
                self._emit()

    # ------------------------------------------------------------------ state
    def _refresh_stats(self, cheap: bool = False):
        try:
            if not cheap:
                self.state.entries = self.store.stats()["entries"]
            self.state.built_at = float(self.store.meta().get("built_at", 0) or 0)
        except Exception:  # noqa: BLE001
            pass

    def _emit(self):
        try:
            self.on_state(IndexState(**vars(self.state)))
        except Exception:  # noqa: BLE001
            log.exception("on_state callback failed")
