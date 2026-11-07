"""
Auto-update via GitHub Releases.

* installed with the installer -> download the new setup and run it silently
* portable / plain exe          -> download the new exe and swap it in place
  (a running exe can be renamed on Windows, just not deleted)
* running from source           -> only point to the release page

Every download is verified against SHA256SUMS.txt of the release.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

from . import __version__

REPO = "theStxve/alles"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
APP_ID = "{6F1E4C3A-9B57-4E1D-A7C2-0D5B8E2F11A1}_is1"  # Inno Setup uninstall key
USER_AGENT = f"ALLES-Updater/{__version__}"

KIND_INSTALLER, KIND_PORTABLE, KIND_EXE, KIND_SOURCE = "installer", "portable", "exe", "source"


class UpdateError(RuntimeError):
    pass


@dataclass
class Release:
    version: str
    tag: str
    page: str
    notes: str
    assets: dict[str, str] = field(default_factory=dict)  # name -> download url


# ----------------------------------------------------------------------------- versions
def parse_version(text: str) -> tuple[int, ...]:
    """'v2.10.1' -> (2, 10, 1); anything after the numbers (e.g. '-beta') is ignored."""
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", text or "")
    if not m:
        return (0,)
    parts = [int(p) for p in m.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_newer(remote: str, local: str = __version__) -> bool:
    return parse_version(remote) > parse_version(local)


# ----------------------------------------------------------------------------- http
def http_get(url: str, timeout: float = 15.0) -> bytes:
    """GET with urllib; falls back to Windows' curl.exe (e.g. when a proxy or an
    antivirus TLS scanner breaks Python's certificate check)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, OSError) as exc:
        curl = shutil.which("curl.exe") or shutil.which("curl")
        if not curl:
            raise UpdateError(f"Keine Verbindung zu GitHub: {exc}") from exc
        proc = subprocess.run([curl, "-fsSL", "--max-time", str(int(timeout)), "-A", USER_AGENT,
                               url], capture_output=True, creationflags=_NO_WINDOW)
        if proc.returncode != 0:
            raise UpdateError(f"Keine Verbindung zu GitHub: {exc}") from exc
        return proc.stdout


_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def parse_release(data: dict) -> Release:
    tag = data.get("tag_name") or ""
    return Release(version=".".join(map(str, parse_version(tag))), tag=tag,
                   page=data.get("html_url") or RELEASES_PAGE,
                   notes=(data.get("body") or "").strip(),
                   assets={a["name"]: a["browser_download_url"]
                           for a in data.get("assets", []) if a.get("name")})


def fetch_latest(timeout: float = 15.0) -> Release:
    try:
        data = json.loads(http_get(API_LATEST, timeout))
    except ValueError as exc:
        raise UpdateError("Ungültige Antwort von GitHub.") from exc
    if not isinstance(data, dict) or "tag_name" not in data:
        raise UpdateError("Kein Release gefunden.")
    return parse_release(data)


# ----------------------------------------------------------------------------- install kind
def _uninstall_location() -> str | None:
    try:
        import winreg
    except ImportError:
        return None
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for base in (r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                     r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
            try:
                with winreg.OpenKey(hive, base + "\\" + APP_ID) as k:
                    return winreg.QueryValueEx(k, "InstallLocation")[0]
            except OSError:
                continue
    return None


def install_kind(exe: str | None = None, frozen: bool | None = None) -> str:
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if not frozen:
        return KIND_SOURCE
    exe = exe or sys.executable
    folder = os.path.dirname(os.path.abspath(exe))
    if os.path.isdir(os.path.join(folder, "ALLES-Daten")):
        return KIND_PORTABLE
    location = _uninstall_location()
    if os.path.isfile(os.path.join(folder, "unins000.exe")) or (
            location and os.path.normcase(os.path.abspath(location.rstrip("\\")))
            == os.path.normcase(folder)):
        return KIND_INSTALLER
    return KIND_EXE


def pick_asset(release: Release, kind: str) -> str | None:
    """Name of the asset to download for this kind of installation."""
    for name in release.assets:
        if kind == KIND_INSTALLER and re.fullmatch(r"ALLES-Setup-[\d.]+\.exe", name):
            return name
        if kind in (KIND_PORTABLE, KIND_EXE) and re.fullmatch(r"ALLES-[\d.]+-x64\.exe", name):
            return name
    return None


def parse_sha256sums(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"\s*([0-9a-fA-F]{64})\s+\*?(\S.*?)\s*$", line)
        if m:
            out[os.path.basename(m.group(2))] = m.group(1).lower()
    return out


# ----------------------------------------------------------------------------- download
def download(release: Release, asset: str, progress: Callable[[int, int], None] | None = None,
             should_stop: Callable[[], bool] = lambda: False) -> str:
    """Download an asset to a temp folder and verify its SHA-256. Returns the path."""
    sums_url = release.assets.get("SHA256SUMS.txt")
    if not sums_url:
        raise UpdateError("Das Release enthält keine Prüfsummen (SHA256SUMS.txt).")
    expected = parse_sha256sums(http_get(sums_url).decode("utf-8", "replace")).get(asset)
    if not expected:
        raise UpdateError(f"Keine Prüfsumme für {asset} gefunden.")
    folder = tempfile.mkdtemp(prefix="alles-update-")
    dest = os.path.join(folder, asset)
    h = hashlib.sha256()
    req = urllib.request.Request(release.assets[asset], headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp, open(dest, "wb") as f:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if should_stop():
                    raise UpdateError("Abgebrochen.")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, OSError):
        data = http_get(release.assets[asset], timeout=300)  # curl fallback
        with open(dest, "wb") as f:
            f.write(data)
        h = hashlib.sha256(data)
    if h.hexdigest() != expected:
        os.remove(dest)
        raise UpdateError("Die Prüfsumme des Downloads stimmt nicht – Update abgebrochen.")
    return dest


# ----------------------------------------------------------------------------- apply
SETUP_ARGS = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/UPDATE=1"]


def installer_command(setup: str, wait_pid: int) -> list[str]:
    """A hidden PowerShell first waits until ALLES (wait_pid) has exited and then runs
    the setup silently - otherwise the silent setup could see ALLES still running and
    give up. /UPDATE=1 makes the setup restart ALLES afterwards."""
    args = ",".join("'" + a + "'" for a in SETUP_ARGS)
    script = (f"Wait-Process -Id {int(wait_pid)} -Timeout 60 -ErrorAction SilentlyContinue; "
              f"Start-Process -FilePath '{setup.replace(chr(39), chr(39) * 2)}' "
              f"-ArgumentList {args}")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
            "-Command", script]


def apply_installer(setup: str, wait_pid: int | None = None) -> None:
    subprocess.Popen(installer_command(setup, wait_pid or os.getpid()), close_fds=True,
                     creationflags=_NO_WINDOW)


def apply_exe(new_exe: str, current: str | None = None, restart_args=()) -> None:
    """Swap the running exe for the new one and start it."""
    current = current or sys.executable
    old = current + ".old"
    try:
        if os.path.exists(old):
            os.remove(old)
    except OSError:
        old = current + f".{os.getpid()}.old"
    os.replace(current, old)          # allowed while running
    try:
        shutil.move(new_exe, current)
    except OSError:
        os.replace(old, current)      # roll back
        raise
    subprocess.Popen([current, *restart_args], close_fds=True)


def cleanup_old_versions(exe: str | None = None) -> None:
    """Delete leftovers of a previous exe swap (call at startup)."""
    if not getattr(sys, "frozen", False) and exe is None:
        return
    exe = exe or sys.executable
    folder, name = os.path.split(exe)
    try:
        for f in os.listdir(folder):
            if f.startswith(name) and f.endswith(".old"):
                try:
                    os.remove(os.path.join(folder, f))
                except OSError:
                    pass
    except OSError:
        pass
