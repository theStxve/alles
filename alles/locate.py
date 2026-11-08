"""Find the Everything.exe installation without hard-coded personal paths."""
from __future__ import annotations

import os
import shlex
import shutil

_REG_LOCATIONS = [
    # (hive name, key, value) - value None means "(Default)"
    ("HKLM", r"SYSTEM\CurrentControlSet\Services\Everything", "ImagePath"),
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Everything.exe", None),
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Everything", "UninstallString"),
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Everything",
     "UninstallString"),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Everything", "UninstallString"),
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Everything 1.5a",
     "UninstallString"),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Everything 1.5a",
     "UninstallString"),
]


def _common_paths() -> list[str]:
    paths = []
    for env in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            paths.append(os.path.join(base, "Everything", "Everything.exe"))
            # Everything 1.5 (alpha) installs side by side as Everything64.exe
            paths.append(os.path.join(base, "Everything 1.5a", "Everything64.exe"))
            if env == "LOCALAPPDATA":
                paths.append(os.path.join(base, "Programs", "Everything", "Everything.exe"))
    return paths


def exe_from_command(cmd: str) -> str | None:
    """Extract the Everything.exe path from a registry command line.

    Handles quoted paths with arguments (service ImagePath '"X:\\...\\Everything.exe" -svc')
    and uninstaller paths (sibling 'Uninstall.exe').
    """
    if not cmd:
        return None
    cmd = os.path.expandvars(cmd.strip())
    try:
        first = shlex.split(cmd, posix=False)[0].strip('"')
    except (ValueError, IndexError):
        first = cmd.strip('"')
    if not first.lower().endswith(".exe"):
        low = cmd.lower()
        end = low.find(".exe")
        if end < 0:
            return None
        first = cmd[:end + 4].strip('"')
    name = os.path.basename(first).lower()
    if name in ("everything.exe", "everything64.exe"):
        return first
    # e.g. Uninstall.exe -> Everything.exe in the same folder
    return os.path.join(os.path.dirname(first), "Everything.exe")


def _registry_candidates() -> list[str]:
    try:
        import winreg
    except ImportError:  # not on Windows
        return []
    hives = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    out = []
    for hive, key, value in _REG_LOCATIONS:
        try:
            with winreg.OpenKey(hives[hive], key) as k:
                raw, _ = winreg.QueryValueEx(k, value or "")
        except OSError:
            continue
        exe = exe_from_command(str(raw))
        if exe:
            out.append(exe)
    return out


def _running_process_exe() -> str | None:
    try:
        import psutil  # optional dependency
    except ImportError:
        return None
    try:
        for p in psutil.process_iter(["name", "exe"]):
            if (p.info.get("name") or "").lower() == "everything.exe" and p.info.get("exe"):
                return p.info["exe"]
    except Exception:  # noqa: BLE001 - psutil may raise AccessDenied etc.
        return None
    return None


def find_everything_exe(configured: str | None = None, exists=os.path.isfile) -> str | None:
    """Return the path of Everything.exe or None.

    Order: user setting -> registry (service, App Paths, uninstaller) ->
    common install folders -> PATH -> running process.
    """
    candidates: list[str] = []
    if configured:
        candidates.append(configured)
    candidates += _registry_candidates()
    candidates += _common_paths()
    which = shutil.which("Everything.exe") or shutil.which("everything")
    if which:
        candidates.append(which)
    for c in candidates:
        if not c:
            continue
        for option in (c, os.path.join(os.path.dirname(c), "Everything64.exe")):
            if exists(option):
                return os.path.normpath(option)
    return _running_process_exe()
