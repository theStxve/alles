"""
The real Windows Explorer context menu (IContextMenu) for files and folders -
including shell extensions like 7-Zip, Git or "Send to" - via pure ctypes COM.

Must be called on the Tk (UI) thread.
"""
from __future__ import annotations

import ctypes
import os
from collections.abc import Callable
from ctypes import wintypes

HRESULT = ctypes.c_long
LRESULT = ctypes.c_ssize_t

CMF_NORMAL, CMF_EXPLORE, CMF_CANRENAME, CMF_EXTENDEDVERBS = 0x0, 0x4, 0x10, 0x100
TPM_RETURNCMD, TPM_RIGHTBUTTON = 0x100, 0x2
CMIC_MASK_UNICODE, CMIC_MASK_PTINVOKE = 0x4000, 0x20000000
CMIC_MASK_SHIFT_DOWN, CMIC_MASK_CONTROL_DOWN = 0x10000000, 0x40000000
GCS_VERBW = 4
ID_FIRST, ID_LAST = 1, 0x7FFF
SW_SHOWNORMAL = 1
MENU_MESSAGES = {0x0117, 0x002B, 0x002C, 0x0120, 0x011F}  # INITMENUPOPUP, DRAW/MEASUREITEM,
#                                                           MENUCHAR, MENUSELECT


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, text: str) -> GUID:
        t = text.strip("{}").replace("-", "")
        d4 = bytes.fromhex(t[16:])
        return cls(int(t[0:8], 16), int(t[8:12], 16), int(t[12:16], 16),
                   (ctypes.c_ubyte * 8)(*d4))


IID_IShellFolder = GUID.parse("{000214E6-0000-0000-C000-000000000046}")
IID_IContextMenu = GUID.parse("{000214E4-0000-0000-C000-000000000046}")
IID_IContextMenu2 = GUID.parse("{000214F4-0000-0000-C000-000000000046}")
IID_IContextMenu3 = GUID.parse("{BCFCE0A0-EC17-11D0-8D10-00A0C90F2719}")


class CMINVOKECOMMANDINFOEX(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", wintypes.DWORD),
                ("hwnd", wintypes.HWND), ("lpVerb", ctypes.c_void_p),
                ("lpParameters", ctypes.c_char_p), ("lpDirectory", ctypes.c_char_p),
                ("nShow", ctypes.c_int), ("dwHotKey", wintypes.DWORD),
                ("hIcon", wintypes.HANDLE), ("lpTitle", ctypes.c_char_p),
                ("lpVerbW", ctypes.c_void_p), ("lpParametersW", wintypes.LPCWSTR),
                ("lpDirectoryW", wintypes.LPCWSTR), ("lpTitleW", wintypes.LPCWSTR),
                ("ptInvoke", wintypes.POINT)]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                             wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


_shell = ctypes.WinDLL("shell32")
_ole = ctypes.WinDLL("ole32")
_u32 = ctypes.WinDLL("user32")
_k32 = ctypes.WinDLL("kernel32")

_shell.SHParseDisplayName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                      ctypes.POINTER(ctypes.c_void_p), wintypes.ULONG,
                                      ctypes.POINTER(wintypes.ULONG)]
_shell.SHParseDisplayName.restype = HRESULT
_shell.SHBindToParent.argtypes = [ctypes.c_void_p, ctypes.POINTER(GUID),
                                  ctypes.POINTER(ctypes.c_void_p),
                                  ctypes.POINTER(ctypes.c_void_p)]
_shell.SHBindToParent.restype = HRESULT
_shell.ILFindLastID.argtypes = [ctypes.c_void_p]
_shell.ILFindLastID.restype = ctypes.c_void_p
_ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
_ole.OleInitialize.argtypes = [ctypes.c_void_p]
_ole.OleInitialize.restype = HRESULT
_u32.CreatePopupMenu.restype = wintypes.HMENU
_u32.DestroyMenu.argtypes = [wintypes.HMENU]
_u32.TrackPopupMenuEx.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                  wintypes.HWND, ctypes.c_void_p]
_u32.TrackPopupMenuEx.restype = wintypes.BOOL
_u32.GetMenuItemCount.argtypes = [wintypes.HMENU]
_u32.GetMenuItemID.argtypes = [wintypes.HMENU, ctypes.c_int]
_u32.GetMenuItemID.restype = wintypes.UINT
_u32.GetMenuStringW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.LPWSTR, ctypes.c_int,
                                wintypes.UINT]
_u32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_u32.DefWindowProcW.restype = LRESULT
_u32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
_u32.RegisterClassW.restype = wintypes.ATOM
_u32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                 wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                 wintypes.HINSTANCE, ctypes.c_void_p]
_u32.CreateWindowExW.restype = wintypes.HWND
_u32.SetForegroundWindow.argtypes = [wintypes.HWND]
_u32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_u32.GetKeyState.argtypes = [ctypes.c_int]
_u32.GetKeyState.restype = ctypes.c_short
_k32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
_k32.GetModuleHandleW.restype = wintypes.HMODULE

# vtable signatures
_QueryInterface = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID),
                                     ctypes.POINTER(ctypes.c_void_p))
_Release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)
_GetUIObjectOf = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(GUID),
                                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
_QueryContextMenu = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, wintypes.HMENU, wintypes.UINT,
                                       wintypes.UINT, wintypes.UINT, wintypes.UINT)
_InvokeCommand = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p,
                                    ctypes.POINTER(CMINVOKECOMMANDINFOEX))
_GetCommandString = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, ctypes.c_size_t, wintypes.UINT,
                                       ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT)
_HandleMenuMsg2 = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, wintypes.UINT, wintypes.WPARAM,
                                     wintypes.LPARAM, ctypes.POINTER(LRESULT))
_HandleMenuMsg = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, wintypes.UINT, wintypes.WPARAM,
                                    wintypes.LPARAM)


def _vt(obj: ctypes.c_void_p, index: int, proto):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return proto(vtbl[index])


def _release(obj):
    if obj and obj.value:
        _vt(obj, 2, _Release)(obj)


class _MenuOwner:
    """Hidden window that forwards owner-draw/submenu messages to IContextMenu2/3."""

    CLASS = "ALLESShellMenuOwner"

    def __init__(self):
        self.cm2 = None
        self.cm3 = None
        self._proc = WNDPROC(self._wndproc)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = _k32.GetModuleHandleW(None)
        wc.lpszClassName = self.CLASS
        _u32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = _u32.CreateWindowExW(0, self.CLASS, "", 0, 0, 0, 0, 0, None, None,
                                         wc.hInstance, None)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg in MENU_MESSAGES:
                if self.cm3:
                    result = LRESULT(0)
                    if _vt(self.cm3, 7, _HandleMenuMsg2)(self.cm3, msg, wparam, lparam,
                                                         ctypes.byref(result)) >= 0:
                        return result.value
                elif (self.cm2 and msg != 0x0120 and
                      _vt(self.cm2, 6, _HandleMenuMsg)(self.cm2, msg, wparam, lparam) >= 0):
                    return 0
        except Exception:  # noqa: BLE001 - never raise across the C boundary
            pass
        return _u32.DefWindowProcW(hwnd, msg, wparam, lparam)


_owner: _MenuOwner | None = None
_ole_ready = False


def _ensure_init():
    global _owner, _ole_ready
    if not _ole_ready:
        _ole.OleInitialize(None)  # STA + clipboard/drag&drop for "Copy"/"Cut" entries
        _ole_ready = True
    if _owner is None:
        _owner = _MenuOwner()
    return _owner


def same_folder(paths: list[str]) -> bool:
    folders = {os.path.normcase(os.path.dirname(os.path.normpath(p))) for p in paths}
    return len(folders) == 1


class _ShellMenu:
    """Builds the IContextMenu + HMENU for some paths; use as a context manager."""

    def __init__(self, paths: list[str], extended: bool = False):
        if not same_folder(paths):
            paths = paths[:1]  # the shell only builds menus for items of one folder
        self.paths = paths
        self.extended = extended
        self.owner = _ensure_init()
        self.pidls: list[ctypes.c_void_p] = []
        self.folder = ctypes.c_void_p()
        self.cm = ctypes.c_void_p()
        self.menu = None

    def __enter__(self):
        try:
            self._build()
        except BaseException:
            self.__exit__()
            raise
        return self

    def _build(self):
        owner, folder, cm = self.owner, self.folder, self.cm
        pidls = self.pidls
        for p in self.paths:
            pidl = ctypes.c_void_p()
            if _shell.SHParseDisplayName(os.path.normpath(p), None, ctypes.byref(pidl), 0,
                                         None) < 0 or not pidl.value:
                raise OSError(f"Pfad nicht gefunden: {p}")
            pidls.append(pidl)
        child = ctypes.c_void_p()
        if _shell.SHBindToParent(pidls[0], ctypes.byref(IID_IShellFolder), ctypes.byref(folder),
                                 ctypes.byref(child)) < 0:
            raise OSError("Elternordner nicht verfügbar")
        children = (ctypes.c_void_p * len(pidls))(
            child.value, *(_shell.ILFindLastID(p) for p in pidls[1:]))
        if _vt(folder, 10, _GetUIObjectOf)(folder, owner.hwnd, len(pidls), children,
                                           ctypes.byref(IID_IContextMenu), None,
                                           ctypes.byref(cm)) < 0:
            raise OSError("Kein Kontextmenü verfügbar")
        for iid, attr in ((IID_IContextMenu3, "cm3"), (IID_IContextMenu2, "cm2")):
            ptr = ctypes.c_void_p()
            if _vt(cm, 0, _QueryInterface)(cm, ctypes.byref(iid), ctypes.byref(ptr)) >= 0:
                setattr(owner, attr, ptr)
        self.menu = menu = _u32.CreatePopupMenu()
        flags = CMF_NORMAL | CMF_EXPLORE | CMF_CANRENAME | (
            CMF_EXTENDEDVERBS if self.extended else 0)
        if _vt(cm, 3, _QueryContextMenu)(cm, menu, 0, ID_FIRST, ID_LAST, flags) < 0:
            raise OSError("Menü konnte nicht erstellt werden")

    def __exit__(self, *exc):
        if self.menu:
            _u32.DestroyMenu(self.menu)
            self.menu = None
        for attr in ("cm3", "cm2"):
            _release(getattr(self.owner, attr))
            setattr(self.owner, attr, None)
        _release(self.cm)
        _release(self.folder)
        for p in self.pidls:
            _ole.CoTaskMemFree(p)
        self.pidls = []
        return False

    def items(self) -> list[tuple[str, str]]:
        """(text, verb) of the top-level entries - for tests and diagnostics."""
        out = []
        buf = ctypes.create_unicode_buffer(256)
        for i in range(_u32.GetMenuItemCount(self.menu)):
            n = _u32.GetMenuStringW(self.menu, i, buf, 256, 0x400)  # MF_BYPOSITION
            text = buf.value if n else ""
            cmd = _u32.GetMenuItemID(self.menu, i)
            verb = _command_verb(self.cm, cmd - ID_FIRST) if ID_FIRST <= cmd <= ID_LAST else ""
            if text:
                out.append((text.replace("&", ""), verb))
        return out


def list_items(paths: list[str], extended: bool = False) -> list[tuple[str, str]]:
    with _ShellMenu(paths, extended) as sm:
        return sm.items()


def show(paths: list[str], x: int, y: int, extended: bool = False,
         on_verb: Callable[[str], bool] | None = None) -> str | None:
    """Show the Explorer context menu for `paths` at screen position (x, y).

    on_verb(verb) may handle a command itself (return True), e.g. "rename".
    Returns the canonical verb that was chosen (or None).
    """
    if not paths:
        return None
    with _ShellMenu(paths, extended) as sm:
        owner, cm, menu = sm.owner, sm.cm, sm.menu
        _u32.SetForegroundWindow(owner.hwnd)
        cmd = _u32.TrackPopupMenuEx(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, x, y, owner.hwnd,
                                    None)
        _u32.PostMessageW(owner.hwnd, 0, 0, 0)  # WM_NULL, see TrackPopupMenu docs
        if cmd <= 0:
            return None
        verb = _command_verb(cm, cmd - ID_FIRST)
        if on_verb and verb and on_verb(verb):
            return verb
        info = CMINVOKECOMMANDINFOEX()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = CMIC_MASK_UNICODE | CMIC_MASK_PTINVOKE
        if _u32.GetKeyState(0x10) < 0:
            info.fMask |= CMIC_MASK_SHIFT_DOWN
        if _u32.GetKeyState(0x11) < 0:
            info.fMask |= CMIC_MASK_CONTROL_DOWN
        info.hwnd = owner.hwnd
        info.lpVerb = cmd - ID_FIRST       # MAKEINTRESOURCE(offset)
        info.lpVerbW = cmd - ID_FIRST
        info.nShow = SW_SHOWNORMAL
        info.ptInvoke = wintypes.POINT(x, y)
        _vt(cm, 4, _InvokeCommand)(cm, ctypes.byref(info))
        return verb or ""


def _command_verb(cm, offset: int) -> str:
    buf = ctypes.create_unicode_buffer(260)
    try:
        if _vt(cm, 5, _GetCommandString)(cm, offset, GCS_VERBW, None, buf, 260) >= 0:
            return buf.value.lower()
    except OSError:
        pass
    return ""
