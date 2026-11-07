"""
Windows tray icon + global hotkey, implemented with pure ctypes (no pywin32 /
pystray dependency) so it works in a single-file PyInstaller build.

All Win32 calls that touch the hidden tray window run on the tray thread that
owns it. Callbacks into the GUI go through ``dispatch`` (a thread-safe
"run this on the Tk thread" function supplied by the app).
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from .util import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_WIN

WINDOW_CLASS = "ALLESTrayWindow"

WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1
WM_APP_REHOTKEY = WM_APP + 2
WM_APP_SHOW = WM_APP + 3
WM_NULL = 0x0000
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_CONTEXTMENU = 0x007B
WM_HOTKEY = 0x0312
WM_COPYDATA = 0x004A
COPYDATA_MAGIC = 0xA11E5
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205

ID_TRAY = 1
ID_HOTKEY = 100
CMD_SHOW, CMD_QUIT = 1, 2

NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
MF_STRING, MF_SEPARATOR = 0x0, 0x800
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x2, 0x100, 0x80
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
IDI_APPLICATION = 32512
ASFW_ANY = 0xFFFFFFFF

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class COPYDATASTRUCT(ctypes.Structure):
    _fields_ = [("dwData", ctypes.c_size_t), ("cbData", wintypes.DWORD),
                ("lpData", ctypes.c_void_p)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", wintypes.BYTE * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uTimeout", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", GUID),
                ("hBalloonIcon", wintypes.HICON)]


def _load_libs():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    def proto(lib, name, argtypes, restype):
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = argtypes, restype

    H, U, INT, P = wintypes.HWND, wintypes.UINT, ctypes.c_int, ctypes.c_void_p
    proto(user32, "DefWindowProcW", [H, U, wintypes.WPARAM, wintypes.LPARAM], LRESULT)
    proto(user32, "RegisterClassW", [ctypes.POINTER(WNDCLASSW)], wintypes.ATOM)
    proto(user32, "CreateWindowExW", [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                      wintypes.DWORD, INT, INT, INT, INT, H, wintypes.HMENU,
                                      wintypes.HINSTANCE, P], H)
    proto(user32, "DestroyWindow", [H], wintypes.BOOL)
    proto(user32, "GetMessageW", [ctypes.POINTER(wintypes.MSG), H, U, U], wintypes.BOOL)
    proto(user32, "TranslateMessage", [ctypes.POINTER(wintypes.MSG)], wintypes.BOOL)
    proto(user32, "DispatchMessageW", [ctypes.POINTER(wintypes.MSG)], LRESULT)
    proto(user32, "PostMessageW", [H, U, wintypes.WPARAM, wintypes.LPARAM], wintypes.BOOL)
    proto(user32, "PostQuitMessage", [INT], None)
    proto(user32, "RegisterHotKey", [H, INT, U, U], wintypes.BOOL)
    proto(user32, "UnregisterHotKey", [H, INT], wintypes.BOOL)
    proto(user32, "RegisterWindowMessageW", [wintypes.LPCWSTR], U)
    proto(user32, "CreatePopupMenu", [], wintypes.HMENU)
    proto(user32, "AppendMenuW", [wintypes.HMENU, U, ctypes.c_size_t, wintypes.LPCWSTR],
          wintypes.BOOL)
    proto(user32, "SetMenuDefaultItem", [wintypes.HMENU, U, U], wintypes.BOOL)
    proto(user32, "TrackPopupMenu", [wintypes.HMENU, U, INT, INT, INT, H, P], wintypes.BOOL)
    proto(user32, "DestroyMenu", [wintypes.HMENU], wintypes.BOOL)
    proto(user32, "GetCursorPos", [ctypes.POINTER(wintypes.POINT)], wintypes.BOOL)
    proto(user32, "SetForegroundWindow", [H], wintypes.BOOL)
    proto(user32, "LoadImageW", [wintypes.HINSTANCE, wintypes.LPCWSTR, U, INT, INT, U],
          wintypes.HANDLE)
    proto(user32, "LoadIconW", [wintypes.HINSTANCE, P], wintypes.HICON)
    proto(user32, "DestroyIcon", [wintypes.HICON], wintypes.BOOL)
    proto(user32, "FindWindowW", [wintypes.LPCWSTR, wintypes.LPCWSTR], H)
    proto(user32, "GetWindowThreadProcessId", [H, ctypes.POINTER(wintypes.DWORD)],
          wintypes.DWORD)
    proto(user32, "AllowSetForegroundWindow", [wintypes.DWORD], wintypes.BOOL)
    proto(user32, "SendMessageTimeoutW", [H, U, wintypes.WPARAM, P, U, U,
                                          ctypes.POINTER(ctypes.c_size_t)], LRESULT)
    proto(kernel32, "GetModuleHandleW", [wintypes.LPCWSTR], wintypes.HMODULE)
    proto(shell32, "Shell_NotifyIconW", [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)],
          wintypes.BOOL)
    return user32, kernel32, shell32


user32, kernel32, shell32 = _load_libs()


def signal_existing_instance(payload: str | None = None) -> bool:
    """If another ALLES is running, activate it (optionally passing a JSON payload
    such as {"folder": ...}). Returns True if an instance was found."""
    hwnd = user32.FindWindowW(WINDOW_CLASS, None)
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value:
        user32.AllowSetForegroundWindow(pid.value)  # let it take the foreground
    if payload:
        data = payload.encode("utf-8")
        buf = ctypes.create_string_buffer(data, len(data))
        cds = COPYDATASTRUCT(COPYDATA_MAGIC, len(data), ctypes.cast(buf, ctypes.c_void_p))
        result = ctypes.c_size_t()
        user32.SendMessageTimeoutW(hwnd, WM_COPYDATA, 0, ctypes.byref(cds),
                                   0x0002, 3000, ctypes.byref(result))  # SMTO_ABORTIFHUNG
    else:
        user32.PostMessageW(hwnd, WM_APP_SHOW, 0, 0)
    return True


class TrayHotkey:
    DEFAULT_COMBOS = [
        (MOD_CONTROL | MOD_ALT, 0x20),  # Ctrl+Alt+Space
        (MOD_CONTROL | MOD_ALT, 0x53),  # Ctrl+Alt+S
        (MOD_CONTROL | MOD_WIN, 0x20),  # Ctrl+Win+Space
        (MOD_ALT, 0x53),                # Alt+S
    ]

    def __init__(self, dispatch, on_toggle, on_show, on_quit,
                 on_hotkey_changed=None, preferred_combo=None, icon_path=None,
                 tooltip="ALLES", on_message=None):
        self.dispatch = dispatch
        self.on_toggle = on_toggle
        self.on_show = on_show
        self.on_quit = on_quit
        self.on_hotkey_changed = on_hotkey_changed
        self.on_message = on_message
        self.preferred_combo = tuple(preferred_combo) if preferred_combo else None
        self.icon_path = icon_path
        self.tooltip = tooltip[:127]
        self.hwnd = None
        self.hicon = None
        self._own_icon = False
        self._wndproc = WNDPROC(self._wnd_proc)  # keep a reference!
        self._thread = None
        self._ready = threading.Event()
        self._msg_taskbar_created = 0
        self.hotkey_combo = None

    # ---- lifecycle ----
    def start(self, timeout: float = 3.0) -> bool:
        self._thread = threading.Thread(target=self._run, name="tray", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self.hwnd is not None

    def stop(self, timeout: float = 2.0):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def request_reregister(self, combo):
        """Switch the global hotkey (safe from any thread)."""
        self.preferred_combo = tuple(combo)
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_APP_REHOTKEY, 0, 0)

    # ---- tray thread ----
    def _run(self):
        try:
            hinst = kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW()
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinst
            wc.lpszClassName = WINDOW_CLASS
            user32.RegisterClassW(ctypes.byref(wc))  # may already exist: fine
            # Top-level (not message-only) so we receive the TaskbarCreated broadcast.
            self.hwnd = user32.CreateWindowExW(0, WINDOW_CLASS, "ALLES", 0, 0, 0, 0, 0,
                                               None, None, hinst, None)
            if not self.hwnd:
                return
            self._msg_taskbar_created = user32.RegisterWindowMessageW("TaskbarCreated")
            self._load_icon()
            self._add_icon()
            self._register_hotkey()
        finally:
            self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _load_icon(self):
        if self.icon_path:
            h = user32.LoadImageW(None, self.icon_path, IMAGE_ICON, 0, 0,
                                  LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                self.hicon, self._own_icon = h, True
                return
        self.hicon = user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))

    def _nid(self) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = ID_TRAY
        return nid

    def _add_icon(self):
        nid = self._nid()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self.hicon
        nid.szTip = self.tooltip
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _remove_icon(self):
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid()))

    def _register_hotkey(self):
        user32.UnregisterHotKey(self.hwnd, ID_HOTKEY)
        combos = [self.preferred_combo] if self.preferred_combo else []
        combos += [c for c in self.DEFAULT_COMBOS if c not in combos]
        self.hotkey_combo = None
        for mod, vk in combos:
            if user32.RegisterHotKey(self.hwnd, ID_HOTKEY, mod | MOD_NOREPEAT, vk):
                self.hotkey_combo = (mod, vk)
                break
        if self.on_hotkey_changed:
            self.dispatch(self.on_hotkey_changed, self.hotkey_combo,
                          self.hotkey_combo == self.preferred_combo)

    def _show_menu(self):
        from .i18n import _
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, CMD_SHOW, _("Einblenden"))
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, CMD_QUIT, _("Beenden"))
        user32.SetMenuDefaultItem(menu, CMD_SHOW, 0)
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)  # required so the menu closes properly
        cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                    pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if cmd == CMD_SHOW:
            self.dispatch(self.on_show)
        elif cmd == CMD_QUIT:
            self.dispatch(self.on_quit)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_HOTKEY and wparam == ID_HOTKEY:
                self.dispatch(self.on_toggle)
                return 0
            if msg == WM_TRAYICON:
                event = lparam & 0xFFFF
                if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self.dispatch(self.on_show)
                elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._show_menu()
                return 0
            if msg == WM_COPYDATA and lparam:
                cds = ctypes.cast(lparam, ctypes.POINTER(COPYDATASTRUCT)).contents
                if cds.dwData == COPYDATA_MAGIC and 0 < cds.cbData < 65536:
                    text = ctypes.string_at(cds.lpData, cds.cbData).decode("utf-8", "replace")
                    self.dispatch(self.on_message or (lambda _t: self.on_show()), text)
                    return 1
                return 0
            if msg == WM_APP_SHOW:
                self.dispatch(self.on_show)
                return 0
            if msg == WM_APP_REHOTKEY:
                self._register_hotkey()
                return 0
            if msg == self._msg_taskbar_created and msg:
                self._add_icon()  # Explorer was restarted
                return 0
            if msg == WM_CLOSE:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                user32.UnregisterHotKey(hwnd, ID_HOTKEY)
                self._remove_icon()
                if self._own_icon and self.hicon:
                    user32.DestroyIcon(self.hicon)
                self.hwnd = None
                user32.PostQuitMessage(0)
                return 0
        except Exception:  # noqa: BLE001 - never let an exception cross the C boundary
            pass
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
