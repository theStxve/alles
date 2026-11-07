"""Real file operations through the Windows shell (temp folders only)."""
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_copy_and_move(tmp_path):
    from alles import shell
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("A")
    (src / "ordner").mkdir()
    (src / "ordner" / "b.txt").write_text("B")
    dest = tmp_path / "ziel" / "neu"  # does not exist yet -> created silently
    assert shell.copy_to([str(src / "a.txt"), str(src / "ordner")], str(dest))
    assert (dest / "a.txt").read_text() == "A" and (dest / "ordner" / "b.txt").exists()
    assert (src / "a.txt").exists()  # copy keeps the source
    moved = tmp_path / "moved"
    assert shell.move_to([str(src / "a.txt")], str(moved))
    assert (moved / "a.txt").exists() and not (src / "a.txt").exists()


def test_empty_list_is_noop(tmp_path):
    from alles import shell
    assert shell.copy_to([], str(tmp_path))
