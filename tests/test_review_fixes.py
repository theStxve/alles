"""Regression tests for issues found in the 2.1.0 review."""
import sys

import pytest

from alles.preview import read_text_preview

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


@windows_only
@pytest.mark.parametrize("raw,expected", [
    ('C:"', "C:\\"),           # Explorer drive: "C:\" -> backslash ate the quote
    ("C:", "C:\\"),
    ('"D:\\Daten"', "D:\\Daten"),
    ("  E:\\x  ", "E:\\x"),
    ("", ""),
])
def test_normalize_folder_arg(raw, expected):
    from alles.app import normalize_folder_arg
    assert normalize_folder_arg(raw) == expected


def test_text_preview_survives_cut_multibyte_char(tmp_path):
    p = tmp_path / "umlaute.txt"
    text = "x" + "ä" * 40_000  # odd offset: the 64 KiB cut lands inside an 'ä'
    p.write_text(text, encoding="utf-8")
    out = read_text_preview(str(p))
    assert out and out[0] == "x" and set(out[1:]) == {"ä"}  # no mojibake like 'Ã¤'


def test_text_preview_binary_and_cp1252(tmp_path):
    b = tmp_path / "x.bin"
    b.write_bytes(b"\x00\x01\x02" * 100)
    assert read_text_preview(str(b)) is None
    c = tmp_path / "alt.txt"
    c.write_bytes("Größe".encode("cp1252"))
    assert read_text_preview(str(c)) == "Größe"


def test_mark_older_sort_key_handles_missing_dates():
    import datetime as dt
    rows = [dt.datetime(2024, 1, 1), None, dt.datetime(2025, 1, 1)]
    ordered = sorted(rows, key=lambda m: m.timestamp() if m else 0.0, reverse=True)
    assert ordered[0].year == 2025 and ordered[-1] is None
