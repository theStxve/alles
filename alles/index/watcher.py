"""Recursive folder watching with ReadDirectoryChangesW (pure ctypes)."""
from __future__ import annotations

import ctypes
import os
import threading
from collections.abc import Callable
from ctypes import wintypes

FILE_LIST_DIRECTORY = 0x0001
FILE_SHARE_ALL = 0x1 | 0x2 | 0x4
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
NOTIFY_FILTER = (0x001 | 0x002 | 0x008 | 0x010)  # FILE_NAME | DIR_NAME | SIZE | LAST_WRITE
INVALID_HANDLE = ctypes.c_void_p(-1).value
ERROR_NOTIFY_ENUM_DIR = 1022
ERROR_OPERATION_ABORTED = 995

ACTIONS = {1: "add", 2: "remove", 3: "modify", 4: "rename_old", 5: "rename_new"}

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.ReadDirectoryChangesW.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                       wintypes.BOOL, wintypes.DWORD,
                                       ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
                                       ctypes.c_void_p]
_k32.ReadDirectoryChangesW.restype = wintypes.BOOL
_k32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
_k32.CancelIoEx.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.CloseHandle.restype = wintypes.BOOL


def parse_notify_buffer(buf: bytes) -> list[tuple[str, str]]:
    """Decode FILE_NOTIFY_INFORMATION records -> [(action, relative_path)]."""
    out = []
    offset = 0
    while offset + 12 <= len(buf):
        next_off, action, name_len = (int.from_bytes(buf[offset + i:offset + i + 4], "little")
                                      for i in (0, 4, 8))
        name = buf[offset + 12:offset + 12 + name_len].decode("utf-16-le", "replace")
        out.append((ACTIONS.get(action, "modify"), name))
        if not next_off:
            break
        offset += next_off
    return out


class FolderWatcher:
    """Watches one root recursively in a background thread.

    on_events(root, [(action, full_path)]) is called from the watcher thread.
    on_overflow(root) is called when Windows dropped events (buffer overflow).
    """

    BUF_SIZE = 64 * 1024  # max for network shares

    def __init__(self, root: str, on_events: Callable, on_overflow: Callable):
        self.root = root.rstrip("\\")
        self.on_events = on_events
        self.on_overflow = on_overflow
        self._handle = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"watch {root}", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        h = self._handle
        if h:
            _k32.CancelIoEx(h, None)

    def _run(self):
        h = _k32.CreateFileW(self.root + "\\", FILE_LIST_DIRECTORY, FILE_SHARE_ALL, None,
                             OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, None)
        if not h or h == INVALID_HANDLE:
            return
        self._handle = h
        buf = ctypes.create_string_buffer(self.BUF_SIZE)
        returned = wintypes.DWORD()
        try:
            while not self._stop.is_set():
                ok = _k32.ReadDirectoryChangesW(h, buf, self.BUF_SIZE, True, NOTIFY_FILTER,
                                                ctypes.byref(returned), None, None)
                if self._stop.is_set():
                    break
                if not ok:
                    err = ctypes.get_last_error()
                    if err == ERROR_NOTIFY_ENUM_DIR:
                        self.on_overflow(self.root)
                        continue
                    break  # aborted, drive removed, ...
                if returned.value == 0:
                    self.on_overflow(self.root)
                    continue
                events = []
                for action, rel in parse_notify_buffer(buf.raw[:returned.value]):
                    full = self.root + "\\" + rel
                    if action == "rename_old":
                        action = "remove"
                    elif action == "rename_new":
                        action = "add"
                    events.append((action, full))
                if events:
                    self.on_events(self.root, events)
        finally:
            self._handle = None
            _k32.CloseHandle(h)


def coalesce(events: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Keep only the last action per path (case-insensitive), in order."""
    last: dict[str, tuple[str, str]] = {}
    for action, path in events:
        key = os.path.normcase(path)
        prev = last.pop(key, None)
        if prev and prev[0] == "add" and action == "modify":
            action = "add"
        last[key] = (action, path)
    # removes first so a re-created folder isn't deleted after being added
    ordered = list(last.values())
    return [e for e in ordered if e[0] == "remove"] + [e for e in ordered if e[0] != "remove"]
