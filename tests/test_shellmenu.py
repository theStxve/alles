"""Builds the real Explorer context menu (without showing it) and checks its entries."""
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def test_menu_for_file_has_standard_verbs(tmp_path):
    from alles import shellmenu
    f = tmp_path / "notiz.txt"
    f.write_text("x")
    items = shellmenu.list_items([str(f)])
    verbs = {v for _, v in items}
    assert len(items) >= 5
    assert {"delete", "properties"} <= verbs, items
    assert "copy" in verbs or "cut" in verbs


def test_menu_for_multiple_files_and_folder(tmp_path):
    from alles import shellmenu
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text("a")
    b.write_text("b")
    sub = tmp_path / "ordner"
    sub.mkdir()
    assert "delete" in {v for _, v in shellmenu.list_items([str(a), str(b)])}
    assert "properties" in {v for _, v in shellmenu.list_items([str(sub)])}


def test_missing_path_raises(tmp_path):
    from alles import shellmenu
    with pytest.raises(OSError):
        shellmenu.list_items([str(tmp_path / "gibt-es-nicht.txt")])
