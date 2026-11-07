"""Windows look & feel helpers: DPI awareness, app icon, dark title bar, console hiding."""
from __future__ import annotations

import ctypes
import os
import sys

ICON_NAME = "alles.ico"


def resource_path(*parts: str) -> str:
    """Path to a bundled resource (works from source and from a PyInstaller build)."""
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def app_icon_path() -> str | None:
    path = resource_path("assets", ICON_NAME)
    return path if os.path.isfile(path) else None


def enable_dpi_awareness() -> None:
    """Sharp text on HiDPI screens. Must run before the first window is created."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # PROCESS_SYSTEM_DPI_AWARE
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def set_app_user_model_id(app_id: str = "ALLES.EverythingFrontEnd") -> None:
    """Own taskbar group + correct icon instead of the python.exe icon."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):
        pass


def detect_dark_mode() -> bool:
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return not val
    except (ImportError, OSError):
        return False


def set_dark_title_bar(root, dark: bool) -> None:
    try:
        root.update_idletasks()
        user32 = ctypes.windll.user32
        user32.GetParent.restype = ctypes.c_void_p
        user32.GetParent.argtypes = [ctypes.c_void_p]
        hwnd = user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), 20, ctypes.byref(value), ctypes.sizeof(value))
    except (AttributeError, OSError):
        pass


def hide_own_console() -> None:
    """Hide the console if it was created just for this process (double-click on
    a .py file). A terminal the user started us from stays visible."""
    try:
        k32 = ctypes.windll.kernel32
        k32.GetConsoleWindow.restype = ctypes.c_void_p
        hwnd = k32.GetConsoleWindow()
        if not hwnd:
            return
        buf = (ctypes.c_uint * 2)()
        if k32.GetConsoleProcessList(buf, 2) <= 1:
            ctypes.windll.user32.ShowWindow(ctypes.c_void_p(hwnd), 0)  # SW_HIDE
    except (AttributeError, OSError):
        pass
