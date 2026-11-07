"""
Thin ctypes wrapper around Everything64.dll (the official Everything SDK).

It talks to the running Everything instance over its IPC window, so all results
come from the real Everything engine - no scraping, no re-implementation.

The SDK keeps its query state in globals inside the DLL, so callers must
serialise access (the app does this with a lock).
"""
from __future__ import annotations

import ctypes
import datetime as _dt
import os
import sys

# --- Request flags (what data we want back per result) ---
REQUEST_FILE_NAME = 0x00000001
REQUEST_PATH = 0x00000002
REQUEST_FULL_PATH_AND_FILE_NAME = 0x00000004
REQUEST_EXTENSION = 0x00000008
REQUEST_SIZE = 0x00000010
REQUEST_DATE_CREATED = 0x00000020
REQUEST_DATE_MODIFIED = 0x00000040
REQUEST_DATE_ACCESSED = 0x00000080
REQUEST_ATTRIBUTES = 0x00000100

# --- Sort types ---
SORT_NAME_ASCENDING = 1
SORT_NAME_DESCENDING = 2
SORT_PATH_ASCENDING = 3
SORT_PATH_DESCENDING = 4
SORT_SIZE_ASCENDING = 5
SORT_SIZE_DESCENDING = 6
SORT_EXTENSION_ASCENDING = 7
SORT_EXTENSION_DESCENDING = 8
SORT_TYPE_NAME_ASCENDING = 9
SORT_TYPE_NAME_DESCENDING = 10
SORT_DATE_CREATED_ASCENDING = 11
SORT_DATE_CREATED_DESCENDING = 12
SORT_DATE_MODIFIED_ASCENDING = 13
SORT_DATE_MODIFIED_DESCENDING = 14
SORT_ATTRIBUTES_ASCENDING = 15
SORT_ATTRIBUTES_DESCENDING = 16

# --- Error codes ---
EVERYTHING_OK = 0
EVERYTHING_ERROR_MEMORY = 1
EVERYTHING_ERROR_IPC = 2
EVERYTHING_ERROR_REGISTERCLASSEX = 3
EVERYTHING_ERROR_CREATEWINDOW = 4
EVERYTHING_ERROR_CREATETHREAD = 5
EVERYTHING_ERROR_INVALIDINDEX = 6
EVERYTHING_ERROR_INVALIDCALL = 7
EVERYTHING_ERROR_INVALIDREQUEST = 8
EVERYTHING_ERROR_INVALIDPARAMETER = 9

ERROR_MESSAGES = {
    EVERYTHING_ERROR_MEMORY: "Nicht genug Speicher.",
    EVERYTHING_ERROR_IPC: "Everything läuft nicht (oder der IPC-Server ist deaktiviert).",
    EVERYTHING_ERROR_REGISTERCLASSEX: "Fensterklasse konnte nicht registriert werden.",
    EVERYTHING_ERROR_CREATEWINDOW: "Empfangsfenster konnte nicht erstellt werden.",
    EVERYTHING_ERROR_CREATETHREAD: "Empfangs-Thread konnte nicht erstellt werden.",
    EVERYTHING_ERROR_INVALIDINDEX: "Ungültiger Ergebnis-Index.",
    EVERYTHING_ERROR_INVALIDCALL: "Ungültiger Aufruf.",
    EVERYTHING_ERROR_INVALIDREQUEST: "Ungültige Anfrage.",
    EVERYTHING_ERROR_INVALIDPARAMETER: "Ungültiger Parameter.",
}

FILE_ATTRIBUTE_DIRECTORY = 0x10
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

_FILETIME_EPOCH = _dt.datetime(1601, 1, 1, tzinfo=_dt.timezone.utc)
_PATH_BUF_CHARS = 32768  # max. Windows long path


class EverythingError(RuntimeError):
    def __init__(self, code: int):
        self.code = code
        super().__init__(ERROR_MESSAGES.get(code, f"Unbekannter Everything-Fehler ({code})."))


def filetime_to_datetime(value: int) -> _dt.datetime | None:
    """Convert a FILETIME integer (100 ns since 1601 UTC) to a local datetime."""
    if not value or value >= 0x7FFFFFFFFFFFFFFF:
        return None
    try:
        utc = _FILETIME_EPOCH + _dt.timedelta(microseconds=value // 10)
    except (OverflowError, ValueError):
        return None
    try:
        return utc.astimezone()  # local time zone (incl. DST of that date)
    except (OverflowError, OSError, ValueError):
        # Windows can't resolve time zones before 1970 -> use today's offset
        local_tz = _dt.datetime.now().astimezone().tzinfo
        return utc.astimezone(local_tz)


def dll_name() -> str:
    return "Everything64.dll" if sys.maxsize > 2**32 else "Everything32.dll"


def dll_search_paths(name: str) -> list[str]:
    """Places where the SDK DLL is looked for (first hit wins)."""
    here = os.path.dirname(os.path.abspath(__file__))
    paths = []
    bundle = getattr(sys, "_MEIPASS", None)  # PyInstaller one-file bundle
    if bundle:
        paths.append(os.path.join(bundle, name))
    paths += [
        os.path.join(here, name),
        os.path.join(os.path.dirname(here), name),
        os.path.join(os.path.dirname(os.path.abspath(sys.argv[0] or ".")), name),
    ]
    return paths


def _resolve_dll(dll_path: str | None) -> str:
    if dll_path and os.path.isabs(dll_path):
        return dll_path
    name = dll_path or dll_name()
    for candidate in dll_search_paths(name):
        if os.path.exists(candidate):
            return candidate
    raise FileNotFoundError(
        f"{name} nicht gefunden. Lege die Datei aus dem Everything-SDK neben ALLES "
        f"(oder führe 'python scripts/fetch_sdk.py' aus).")


class EverythingSDK:
    def __init__(self, dll_path: str | None = None):
        from ctypes import wintypes  # Windows only

        self._wt = wintypes
        self.dll_path = _resolve_dll(dll_path)
        self.dll = ctypes.WinDLL(self.dll_path)
        self._path_buf = ctypes.create_unicode_buffer(_PATH_BUF_CHARS)
        self._setup_prototypes()

    def _setup_prototypes(self):
        wt = self._wt
        d = self.dll

        def proto(name, argtypes, restype):
            fn = getattr(d, name)
            fn.argtypes = argtypes
            fn.restype = restype

        proto("Everything_SetSearchW", [wt.LPCWSTR], None)
        for name in ("Everything_SetMatchPath", "Everything_SetMatchCase",
                     "Everything_SetMatchWholeWord", "Everything_SetRegex"):
            proto(name, [wt.BOOL], None)
        for name in ("Everything_SetMax", "Everything_SetOffset",
                     "Everything_SetSort", "Everything_SetRequestFlags"):
            proto(name, [wt.DWORD], None)
        proto("Everything_QueryW", [wt.BOOL], wt.BOOL)
        for name in ("Everything_GetLastError", "Everything_GetNumResults",
                     "Everything_GetTotResults", "Everything_GetMajorVersion",
                     "Everything_GetMinorVersion", "Everything_GetRevision"):
            proto(name, [], wt.DWORD)
        proto("Everything_GetResultFullPathNameW", [wt.DWORD, wt.LPWSTR, wt.DWORD], wt.DWORD)
        proto("Everything_GetResultSize", [wt.DWORD, ctypes.POINTER(ctypes.c_longlong)], wt.BOOL)
        proto("Everything_GetResultDateModified",
              [wt.DWORD, ctypes.POINTER(ctypes.c_ulonglong)], wt.BOOL)
        proto("Everything_GetResultAttributes", [wt.DWORD], wt.DWORD)
        proto("Everything_GetResultExtensionW", [wt.DWORD], wt.LPCWSTR)
        proto("Everything_Reset", [], None)
        proto("Everything_CleanUp", [], None)
        proto("Everything_IsDBLoaded", [], wt.BOOL)

    # ---- query state ----
    def reset(self):
        self.dll.Everything_Reset()

    def set_search(self, text: str):
        self.dll.Everything_SetSearchW(text)

    def set_match_path(self, enabled: bool):
        self.dll.Everything_SetMatchPath(bool(enabled))

    def set_match_case(self, enabled: bool):
        self.dll.Everything_SetMatchCase(bool(enabled))

    def set_match_whole_word(self, enabled: bool):
        self.dll.Everything_SetMatchWholeWord(bool(enabled))

    def set_regex(self, enabled: bool):
        self.dll.Everything_SetRegex(bool(enabled))

    def set_max(self, value: int):
        self.dll.Everything_SetMax(int(value))

    def set_offset(self, value: int):
        self.dll.Everything_SetOffset(int(value))

    def set_sort(self, sort_type: int):
        self.dll.Everything_SetSort(int(sort_type))

    def set_request_flags(self, flags: int):
        self.dll.Everything_SetRequestFlags(int(flags))

    def query(self, wait: bool = True) -> int:
        if not self.dll.Everything_QueryW(bool(wait)):
            raise EverythingError(self.dll.Everything_GetLastError())
        return self.dll.Everything_GetNumResults()

    # ---- results ----
    def get_num_results(self) -> int:
        return self.dll.Everything_GetNumResults()

    def get_total_results(self) -> int:
        return self.dll.Everything_GetTotResults()

    def get_result_full_path(self, index: int) -> str:
        n = self.dll.Everything_GetResultFullPathNameW(index, self._path_buf, _PATH_BUF_CHARS)
        return self._path_buf.value if n else ""

    def get_result_size(self, index: int) -> int | None:
        val = ctypes.c_longlong()
        if not self.dll.Everything_GetResultSize(index, ctypes.byref(val)):
            return None
        return val.value if val.value >= 0 else None

    def get_result_date_modified(self, index: int) -> _dt.datetime | None:
        ft = ctypes.c_ulonglong()
        if not self.dll.Everything_GetResultDateModified(index, ctypes.byref(ft)):
            return None
        return filetime_to_datetime(ft.value)

    def get_result_attributes(self, index: int) -> int:
        return self.dll.Everything_GetResultAttributes(index)

    def is_result_folder(self, index: int) -> bool:
        attrs = self.get_result_attributes(index)
        return attrs != INVALID_FILE_ATTRIBUTES and bool(attrs & FILE_ATTRIBUTE_DIRECTORY)

    def get_result_extension(self, index: int) -> str:
        return self.dll.Everything_GetResultExtensionW(index) or ""

    # ---- misc ----
    def is_db_loaded(self) -> bool:
        return bool(self.dll.Everything_IsDBLoaded())

    def get_version(self) -> tuple[int, int, int]:
        """(major, minor, revision); (0, 0, 0) if Everything is not reachable."""
        return (self.dll.Everything_GetMajorVersion(),
                self.dll.Everything_GetMinorVersion(),
                self.dll.Everything_GetRevision())

    def is_running(self) -> bool:
        return self.get_version()[0] != 0

    def cleanup(self):
        self.dll.Everything_CleanUp()
