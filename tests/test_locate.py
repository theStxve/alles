import os

from alles import locate


def test_exe_from_service_command():
    cmd = r'"D:\Programme\Everything\Everything.exe" -svc'
    assert locate.exe_from_command(cmd) == r"D:\Programme\Everything\Everything.exe"


def test_exe_from_unquoted_uninstaller_with_spaces():
    cmd = r"C:\Program Files\Everything\Uninstall.exe"
    assert locate.exe_from_command(cmd) == os.path.join(
        r"C:\Program Files\Everything", "Everything.exe")


def test_exe_from_garbage():
    assert locate.exe_from_command("") is None
    assert locate.exe_from_command("no executable here") is None


def test_configured_path_wins(monkeypatch):
    monkeypatch.setattr(locate, "_registry_candidates", lambda: [r"X:\reg\Everything.exe"])
    found = locate.find_everything_exe(r"Y:\mine\Everything.exe", exists=lambda p: True)
    assert found == os.path.normpath(r"Y:\mine\Everything.exe")


def test_falls_back_to_registry(monkeypatch):
    monkeypatch.setattr(locate, "_registry_candidates", lambda: [r"X:\reg\Everything.exe"])
    found = locate.find_everything_exe(r"Y:\missing.exe",
                                       exists=lambda p: p.startswith("X:"))
    assert found == os.path.normpath(r"X:\reg\Everything.exe")


def test_nothing_found(monkeypatch):
    monkeypatch.setattr(locate, "_registry_candidates", lambda: [])
    monkeypatch.setattr(locate, "_running_process_exe", lambda: None)
    monkeypatch.setattr(locate.shutil, "which", lambda name: None)
    assert locate.find_everything_exe(None, exists=lambda p: False) is None


def test_everything_15_side_by_side(monkeypatch):
    monkeypatch.setattr(locate, "_registry_candidates", lambda: [])
    monkeypatch.setattr(locate, "_running_process_exe", lambda: None)
    monkeypatch.setattr(locate.shutil, "which", lambda name: None)
    found = locate.find_everything_exe(None, exists=lambda p: p.endswith(
        os.path.join("Everything 1.5a", "Everything64.exe")))
    assert found and found.endswith("Everything64.exe")
    assert locate.exe_from_command(r'"C:\X\Everything64.exe" -startup').endswith("64.exe")
