import datetime as dt

import pytest

from alles.everything_sdk import filetime_to_datetime
from alles.util import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    fmt_count,
    fmt_date,
    fmt_size,
    geometry_visible,
    is_valid_hotkey,
    parse_geometry,
    vk_display,
)


@pytest.mark.parametrize("size,expected", [
    (None, ""), (-1, ""), (0, "0 B"), (1023, "1023 B"), (1024, "1,0 KB"),
    (1536, "1,5 KB"), (5 * 1024**2, "5,0 MB"), (3 * 1024**4, "3,0 TB"),
    (1500 * 1024**3, "1,5 TB"),
])
def test_fmt_size(size, expected):
    assert fmt_size(size) == expected


def test_fmt_size_thousands_separator():
    assert fmt_size(1023 * 1024**5) == "1.023,0 PB"


def test_fmt_count_and_date():
    assert fmt_count(1234567) == "1.234.567"
    assert fmt_date(None) == ""
    assert fmt_date(dt.datetime(2024, 3, 5, 7, 9)) == "05.03.2024 07:09"


def test_vk_display():
    assert vk_display(MOD_CONTROL | MOD_ALT, 0x20) == "Strg+Alt+Leertaste"
    assert vk_display(MOD_WIN | MOD_SHIFT, 0x41) == "Umschalt+Win+A"
    assert vk_display(0, 0x70) == "F1"
    assert vk_display(MOD_ALT, 0x63) == "Alt+Num3"


@pytest.mark.parametrize("mod,vk,ok", [
    (MOD_CONTROL | MOD_ALT, 0x20, True),
    (MOD_ALT, 0x53, True),
    (0, 0x41, False),            # plain "A" would swallow typing
    (MOD_SHIFT, 0x41, False),    # Shift+A is just a capital A
    (0, 0x7B, True),             # F12 alone is fine
    (MOD_CONTROL, 0x11, False),  # modifier as main key
])
def test_is_valid_hotkey(mod, vk, ok):
    assert is_valid_hotkey(mod, vk) is ok


def test_filetime_conversion_is_local_and_correct():
    # 2021-01-01 00:00:00 UTC
    ft = (1609459200 + 11644473600) * 10_000_000
    value = filetime_to_datetime(ft)
    assert value.tzinfo is not None
    assert value.astimezone(dt.timezone.utc) == dt.datetime(2021, 1, 1, tzinfo=dt.timezone.utc)


def test_filetime_before_1970_and_invalid():
    assert filetime_to_datetime(10**15).year < 1970
    assert filetime_to_datetime(0) is None
    assert filetime_to_datetime(0x7FFFFFFFFFFFFFFF) is None


def test_parse_geometry():
    assert parse_geometry("1100x720+10+20") == (1100, 720, 10, 20)
    assert parse_geometry("800x600+-8+-8") == (800, 600, -8, -8)
    assert parse_geometry("garbage") is None
    assert parse_geometry("") is None


def test_geometry_visible():
    screen = (0, 0, 1920, 1080)
    assert geometry_visible((1100, 720, 100, 100), screen)
    assert geometry_visible((800, 600, -8, -8), screen)
    assert not geometry_visible((800, 600, 3000, 100), screen)  # monitor gone
    assert not geometry_visible((50, 50, 10, 10), screen)  # too small
