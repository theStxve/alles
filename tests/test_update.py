import hashlib
import io
import os

import pytest

from alles import update
from alles.update import (
    KIND_EXE,
    KIND_INSTALLER,
    KIND_PORTABLE,
    KIND_SOURCE,
    Release,
    UpdateError,
    install_kind,
    is_newer,
    parse_release,
    parse_sha256sums,
    parse_version,
    pick_asset,
)


def test_parse_version():
    assert parse_version("v2.1.0") == (2, 1)
    assert parse_version("2.10.3-beta") == (2, 10, 3)
    assert parse_version("garbage") == (0,)


def test_is_newer():
    assert is_newer("v2.2.0", "2.1.0")
    assert is_newer("2.10", "2.9.9")
    assert not is_newer("v2.1", "2.1.0")
    assert not is_newer("2.0.9", "2.1.0")


def make_release():
    return parse_release({
        "tag_name": "v2.2.0", "html_url": "https://example/rel", "body": " Neu! ",
        "assets": [{"name": n, "browser_download_url": f"https://dl/{n}"} for n in (
            "ALLES-Setup-2.2.0.exe", "ALLES-2.2.0-x64.exe", "ALLES-2.2.0-portable.zip",
            "SHA256SUMS.txt")]})


def test_parse_release_and_pick_asset():
    rel = make_release()
    assert rel.version == "2.2" and rel.notes == "Neu!"
    assert pick_asset(rel, KIND_INSTALLER) == "ALLES-Setup-2.2.0.exe"
    assert pick_asset(rel, KIND_PORTABLE) == "ALLES-2.2.0-x64.exe"
    assert pick_asset(rel, KIND_EXE) == "ALLES-2.2.0-x64.exe"
    assert pick_asset(rel, KIND_SOURCE) is None


def test_parse_sha256sums():
    h = "a" * 64
    sums = parse_sha256sums(f"{h}  ALLES-2.2.0-x64.exe\n{h.upper()} *dist/ALLES-Setup-2.2.0.exe\n"
                            "kaputt\n")
    assert sums == {"ALLES-2.2.0-x64.exe": h, "ALLES-Setup-2.2.0.exe": h}


def test_install_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "_uninstall_location", lambda: None)
    exe = tmp_path / "ALLES.exe"
    exe.write_bytes(b"x")
    assert install_kind(str(exe), frozen=False) == KIND_SOURCE
    assert install_kind(str(exe), frozen=True) == KIND_EXE
    (tmp_path / "unins000.exe").write_bytes(b"x")
    assert install_kind(str(exe), frozen=True) == KIND_INSTALLER
    os.remove(tmp_path / "unins000.exe")
    monkeypatch.setattr(update, "_uninstall_location", lambda: str(tmp_path) + "\\")
    assert install_kind(str(exe), frozen=True) == KIND_INSTALLER
    (tmp_path / "ALLES-Daten").mkdir()
    assert install_kind(str(exe), frozen=True) == KIND_PORTABLE


class FakeResp(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_verifies_checksum(monkeypatch):
    payload = b"new exe" * 1000
    good = hashlib.sha256(payload).hexdigest()
    rel = make_release()
    monkeypatch.setattr(update.urllib.request, "urlopen", lambda req, timeout: FakeResp(payload))
    monkeypatch.setattr(update, "http_get",
                        lambda url, timeout=15: f"{good}  ALLES-2.2.0-x64.exe\n".encode())
    seen = []
    path = update.download(rel, "ALLES-2.2.0-x64.exe", lambda d, t: seen.append((d, t)))
    with open(path, "rb") as f:
        assert f.read() == payload
    assert seen[-1] == (len(payload), len(payload))
    monkeypatch.setattr(update, "http_get",
                        lambda url, timeout=15: f"{'0' * 64}  ALLES-2.2.0-x64.exe\n".encode())
    with pytest.raises(UpdateError, match="Prüfsumme"):
        update.download(rel, "ALLES-2.2.0-x64.exe")


def test_download_requires_checksums():
    rel = Release("2.2", "v2.2.0", "", "", {"ALLES-2.2.0-x64.exe": "https://dl/x"})
    with pytest.raises(UpdateError, match="SHA256SUMS"):
        update.download(rel, "ALLES-2.2.0-x64.exe")


def test_apply_exe_swaps_and_cleans_up(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(update.subprocess, "Popen", lambda args, **kw: started.append(args))
    current = tmp_path / "ALLES.exe"
    current.write_bytes(b"old")
    new = tmp_path / "dl" / "ALLES-2.2.0-x64.exe"
    new.parent.mkdir()
    new.write_bytes(b"new")
    update.apply_exe(str(new), str(current), ["--tray"])
    assert current.read_bytes() == b"new"
    assert (tmp_path / "ALLES.exe.old").read_bytes() == b"old"
    assert started == [[str(current), "--tray"]]
    update.cleanup_old_versions(str(current))
    assert not (tmp_path / "ALLES.exe.old").exists()


@pytest.mark.network
def test_fetch_latest_live():
    try:
        rel = update.fetch_latest(timeout=10)
    except UpdateError as exc:
        pytest.skip(f"offline: {exc}")
    assert parse_version(rel.version) >= (2, 1)
    assert "SHA256SUMS.txt" in rel.assets
    assert pick_asset(rel, KIND_INSTALLER) and pick_asset(rel, KIND_EXE)


def test_installer_command_waits_and_quotes():
    cmd = update.installer_command(r"C:\Temp\O'Brien\ALLES-Setup-2.2.0.exe", 1234)
    script = cmd[-1]
    assert cmd[0] == "powershell.exe" and "Hidden" in cmd
    assert script.startswith("Wait-Process -Id 1234")
    assert "O''Brien" in script  # single quote escaped for PowerShell
    assert "'/UPDATE=1'" in script and "'/SILENT'" in script
