"""Windows shell integration: open files, reveal in Explorer, properties, autostart."""
from __future__ import annotations

import ctypes
import os
import shutil
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
        # absolute script path: Explorer/autostart launch us from another folder
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "run_alles.py")
        cmd = f'"{exe}" "{script}"' if os.path.isfile(script) else f'"{exe}" -m alles'
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


DRIVE_REMOVABLE, DRIVE_FIXED = 2, 3


def drive_type(root: str) -> int:
    return ctypes.windll.kernel32.GetDriveTypeW(root)


def fixed_drives() -> list[str]:
    """Local hard disks - the default roots for the built-in index."""
    return [d for d in logical_drives() if drive_type(d) == DRIVE_FIXED]


# ----------------------------------------------------------------------------- file ops
class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                ("pFrom", ctypes.c_void_p), ("pTo", ctypes.c_void_p),
                ("fFlags", wintypes.WORD), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


FO_DELETE = 3
FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
FOF_WANTNUKEWARNING = 0x4000


def recycle(paths: list[str], hwnd: int | None = None) -> bool:
    """Move files/folders to the recycle bin. Returns False if anything failed.

    On drives without a recycle bin (USB sticks, network shares) Windows asks
    before deleting permanently (FOF_WANTNUKEWARNING) instead of silently nuking.
    """
    if not paths:
        return True
    buf = ctypes.create_unicode_buffer("\0".join(os.path.normpath(p) for p in paths) + "\0\0")
    op = SHFILEOPSTRUCTW()
    op.hwnd = hwnd
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(buf, ctypes.c_void_p)
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_WANTNUKEWARNING
    shell32 = ctypes.WinDLL("shell32")
    shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
    rc = shell32.SHFileOperationW(ctypes.byref(op))
    return rc == 0 and not op.fAnyOperationsAborted


def open_with(path: str) -> None:
    """Windows 'Open with...' dialog."""
    subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", os.path.normpath(path)])


def open_terminal(folder: str) -> None:
    """Windows Terminal if installed, otherwise PowerShell, in the given folder."""
    folder = os.path.normpath(folder)
    wt = shutil.which("wt.exe")
    if wt:
        subprocess.Popen([wt, "-d", folder])
    else:
        subprocess.Popen(["powershell.exe", "-NoExit"], cwd=folder,
                         creationflags=subprocess.CREATE_NEW_CONSOLE)


def vscode_path() -> str | None:
    return shutil.which("code.cmd") or shutil.which("code")


def open_in_vscode(path: str) -> None:
    code = vscode_path()
    if not code:
        raise FileNotFoundError("Visual Studio Code (code) wurde nicht gefunden.")
    subprocess.Popen([code, os.path.normpath(path)], creationflags=0x08000000)  # no window


# ----------------------------------------------------------------------------- Explorer menu
EXPLORER_KEYS = (r"Software\Classes\Directory\shell\ALLES",
                 r"Software\Classes\Directory\Background\shell\ALLES",
                 r"Software\Classes\Drive\shell\ALLES")
EXPLORER_LABEL = "Mit ALLES durchsuchen"


def app_command() -> str:
    return launch_command(tray=False)


def get_explorer_integration() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, EXPLORER_KEYS[0]):
            return True
    except (ImportError, OSError):
        return False


def set_explorer_integration(enabled: bool, icon: str | None = None) -> bool:
    """Adds/removes 'Mit ALLES durchsuchen' to the folder context menu (per user)."""
    try:
        import winreg
    except ImportError:
        return False
    try:
        for key in EXPLORER_KEYS:
            if enabled:
                arg = "%V"
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as k:
                    winreg.SetValueEx(k, "", 0, winreg.REG_SZ, EXPLORER_LABEL)
                    winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ,
                                      icon or app_command().split('"')[1])
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as k:
                    winreg.SetValueEx(k, "", 0, winreg.REG_SZ,
                                      f'{app_command()} --folder "{arg}"')
            else:
                for sub in (key + r"\command", key):
                    try:
                        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
                    except FileNotFoundError:
                        pass
        return True
    except OSError:
        return False


def remove_integrations() -> None:
    """Used by the uninstaller: autostart + Explorer menu."""
    set_autostart(False)
    set_explorer_integration(False)
