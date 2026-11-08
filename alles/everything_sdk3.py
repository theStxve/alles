"""
ctypes wrapper for the Everything 1.5 SDK (Everything3_x64.dll, MIT licensed).

Everything 1.5 talks over a named pipe and the alpha runs in a "1.5a" instance,
which the old 1.4 SDK (window-message IPC) cannot reach. Not thread-safe - the
caller serialises access with a lock.
"""
from __future__ import annotations

import ctypes
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

from .everything_sdk import dll_search_paths

PROPERTY_NAME, PROPERTY_PATH, PROPERTY_SIZE, PROPERTY_EXTENSION = 0, 1, 2, 3
PROPERTY_DATE_MODIFIED, PROPERTY_ATTRIBUTES = 5, 8
ERROR_IPC_PIPE_NOT_FOUND = 0xE0000002
UNKNOWN_SIZE = 0xFFFFFFFFFFFFFFFF

INSTANCES = ("", "1.5a")  # default instance first, then the 1.5 alpha instance

# SDK2 sort constants (used throughout ALLES) -> (SDK3 property id, ascending)
SORT_MAP = {1: (PROPERTY_NAME, True), 2: (PROPERTY_NAME, False),
            3: (PROPERTY_PATH, True), 4: (PROPERTY_PATH, False),
            5: (PROPERTY_SIZE, True), 6: (PROPERTY_SIZE, False),
            7: (PROPERTY_EXTENSION, True), 8: (PROPERTY_EXTENSION, False),
            13: (PROPERTY_DATE_MODIFIED, True), 14: (PROPERTY_DATE_MODIFIED, False)}


def dll_name() -> str:
    return "Everything3_x64.dll" if sys.maxsize > 2**32 else "Everything3_x86.dll"


@dataclass
class Item:
    path: str
    size: int | None
    filetime: int
    ext: str
    is_dir: bool


class Everything3:
    def __init__(self, dll_path: str | None = None):
        from ctypes import wintypes as wt

        path = dll_path
        if not path:
            path = next((p for p in dll_search_paths(dll_name()) if os.path.exists(p)), None)
        if not path:
            raise FileNotFoundError(f"{dll_name()} nicht gefunden")
        self.dll_path = path
        d = self.dll = ctypes.WinDLL(path)
        P, SZ, B, DW, U64 = ctypes.c_void_p, ctypes.c_size_t, wt.BOOL, wt.DWORD, ctypes.c_uint64

        def proto(name, args, res):
            fn = getattr(d, name)
            fn.argtypes, fn.restype = args, res

        proto("Everything3_ConnectW", [wt.LPCWSTR], P)
        proto("Everything3_DestroyClient", [P], B)
        for name in ("Everything3_GetMajorVersion", "Everything3_GetMinorVersion",
                     "Everything3_GetRevision"):
            proto(name, [P], DW)
        proto("Everything3_IsDBLoaded", [P], B)
        proto("Everything3_GetLastError", [], DW)
        proto("Everything3_CreateSearchState", [], P)
        proto("Everything3_DestroySearchState", [P], B)
        for name in ("Everything3_SetSearchMatchCase", "Everything3_SetSearchMatchWholeWords",
                     "Everything3_SetSearchMatchPath"):
            proto(name, [P, B], B)
        proto("Everything3_SetSearchTextW", [P, wt.LPCWSTR], B)
        proto("Everything3_AddSearchPropertyRequest", [P, DW], B)
        proto("Everything3_SetSearchViewportOffset", [P, SZ], B)
        proto("Everything3_SetSearchViewportCount", [P, SZ], B)
        proto("Everything3_SetSearchSort", [P, DW, B], B)
        proto("Everything3_Search", [P, P], P)
        proto("Everything3_DestroyResultList", [P], B)
        proto("Everything3_GetResultListCount", [P], SZ)
        proto("Everything3_GetResultListViewportCount", [P], SZ)
        for name in ("Everything3_GetResultFullPathNameW", "Everything3_GetResultExtensionW"):
            proto(name, [P, SZ, wt.LPWSTR, SZ], SZ)
        proto("Everything3_GetResultSize", [P, SZ], U64)
        proto("Everything3_GetResultDateModified", [P, SZ], U64)
        proto("Everything3_IsFolderResult", [P, SZ], B)
        self.client = None
        self.instance = None
        self._buf = ctypes.create_unicode_buffer(32768)
        self._ext = ctypes.create_unicode_buffer(260)

    # ---- connection
    def connect(self) -> bool:
        if self.client:
            return True
        for name in INSTANCES:
            c = self.dll.Everything3_ConnectW(name or None)
            if c:
                self.client, self.instance = c, name
                return True
        return False

    def disconnect(self):
        if self.client:
            self.dll.Everything3_DestroyClient(self.client)
        self.client = None

    def version(self) -> tuple[int, int, int]:
        if not self.client:
            return (0, 0, 0)
        d = self.dll
        return (d.Everything3_GetMajorVersion(self.client),
                d.Everything3_GetMinorVersion(self.client), d.Everything3_GetRevision(self.client))

    def is_db_loaded(self) -> bool:
        return bool(self.client and self.dll.Everything3_IsDBLoaded(self.client))

    # ---- search
    def search(self, text: str, match_case=False, whole_word=False, match_path=False,
               sort: int = 1, offset: int = 0, limit: int = 1000, details: bool = True,
               is_stale: Callable[[], bool] = lambda: False) -> tuple[list[Item], int] | None:
        """Returns (items, total) or None if the search went stale. Raises OSError."""
        if not self.connect():
            raise OSError("Everything 1.5 ist nicht erreichbar.")
        d = self.dll
        state = d.Everything3_CreateSearchState()
        if not state:
            raise MemoryError("Everything3_CreateSearchState failed")
        results = None
        try:
            d.Everything3_SetSearchTextW(state, text)
            d.Everything3_SetSearchMatchCase(state, bool(match_case))
            d.Everything3_SetSearchMatchWholeWords(state, bool(whole_word))
            d.Everything3_SetSearchMatchPath(state, bool(match_path))
            prop, asc = SORT_MAP.get(sort, SORT_MAP[1])
            d.Everything3_SetSearchSort(state, prop, asc)
            if details:
                for p in (PROPERTY_SIZE, PROPERTY_DATE_MODIFIED, PROPERTY_EXTENSION):
                    d.Everything3_AddSearchPropertyRequest(state, p)
            d.Everything3_SetSearchViewportOffset(state, offset)
            d.Everything3_SetSearchViewportCount(state, limit)
            results = d.Everything3_Search(self.client, state)
            if not results:
                err = d.Everything3_GetLastError()
                if err == ERROR_IPC_PIPE_NOT_FOUND:
                    self.disconnect()
                raise OSError(f"Everything 1.5 meldet Fehler 0x{err:08X}")
            total = d.Everything3_GetResultListCount(results)
            count = d.Everything3_GetResultListViewportCount(results)
            items = []
            for i in range(count):  # indices are relative to the viewport
                if i % 256 == 0 and is_stale():
                    return None
                n = d.Everything3_GetResultFullPathNameW(results, i, self._buf, 32768)
                if not n:
                    continue
                path = self._buf.value
                if not details:
                    items.append(Item(path, None, 0, "", False))
                    continue
                size = d.Everything3_GetResultSize(results, i)
                d.Everything3_GetResultExtensionW(results, i, self._ext, 260)
                items.append(Item(path, None if size == UNKNOWN_SIZE else size,
                                  d.Everything3_GetResultDateModified(results, i),
                                  self._ext.value, bool(d.Everything3_IsFolderResult(results, i))))
            return items, total
        finally:
            if results:
                d.Everything3_DestroyResultList(results)
            d.Everything3_DestroySearchState(state)
