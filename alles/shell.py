"""Windows shell integration: open files, reveal in Explorer, properties, autostart."""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from ctypes import wintypes

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "ALLES"

SEE_MASK_INVOKEIDLIST = 0x0000000C
SEE_MASK_FLAG_NO_UI = 0x00000400
SW_SHOWNORMAL = 1


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong),
                ("hwnd", wintypes.HWND), ("lpVerb", wintypes.LPCWSTR),
                ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE)]


def open_path(path: str) -> None:
    os.startfile(path)  # raises OSError with a readable message


def reveal_in_explorer(path: str) -> None:
    """Open the parent folder in Explorer with the item selected."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    # explorer.exe needs the comma form and its own quoting rules
    subprocess.Popen(f'explorer.exe /select,"{os.path.normpath(path)}"')


def show_properties(path: str, hwnd: int | None = None) -> None:
    """Show the standard Explorer 'Properties' dialog for a file or folder."""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_INVOKEIDLIST | SEE_MASK_FLAG_NO_UI
    info.hwnd = hwnd
    info.lpVerb = "properties"
    info.lpFile = path
    info.nShow = SW_SHOWNORMAL
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())


def launch_command(tray: bool = True) -> str:
    """Command line used for autostart (works for source and frozen builds)."""
    if getattr(sys, "frozen", False):
        cmd = f'"{sys.executable}"'
    else:
        exe = sys.executable
        pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.isfile(pyw):
            exe = pyw
        cmd = f'"{exe}" -m alles'
    return cmd + (" --tray" if tray else "")


def get_autostart() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_VALUE)
        return True
    except (ImportError, OSError):
        return False


def set_autostart(enabled: bool) -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(k, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return True
    except (ImportError, OSError):
        return False


def drive_label(root: str) -> str:
    """Volume label for 'C:\\' (empty for network/removable drives without media)."""
    k32 = ctypes.windll.kernel32
    DRIVE_REMOTE, DRIVE_CDROM = 4, 5
    if k32.GetDriveTypeW(root) in (DRIVE_REMOTE, DRIVE_CDROM):
        return ""  # can block for seconds / no media
    buf = ctypes.create_unicode_buffer(261)
    old = k32.SetErrorMode(0x0001)  # SEM_FAILCRITICALERRORS: no "insert disk" popups
    try:
        ok = k32.GetVolumeInformationW(root, buf, 261, None, None, None, None, 0)
    finally:
        k32.SetErrorMode(old)
    return buf.value if ok else ""


def logical_drives() -> list[str]:
    buf = ctypes.create_unicode_buffer(512)
    n = ctypes.windll.kernel32.GetLogicalDriveStringsW(511, buf)
    if not n:
        return []
    return [d for d in ctypes.wstring_at(buf, n).split("\x00") if d]
