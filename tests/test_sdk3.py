import sys

import pytest

from alles import everything_sdk3 as e3
from alles.query import SORT_OPTIONS


def test_every_sort_option_maps_to_sdk3():
    for sort in SORT_OPTIONS.values():
        assert sort in e3.SORT_MAP


def test_instances_try_default_then_alpha():
    assert e3.INSTANCES == ("", "1.5a")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_dll_loads_and_connect_is_safe():
    try:
        sdk = e3.Everything3()
    except (OSError, FileNotFoundError):
        pytest.skip("Everything3_x64.dll not available")
    if sdk.connect():  # Everything 1.5 running -> a real query must work
        assert sdk.version()[0] >= 1
        items, total = sdk.search("ext:exe", limit=5)
        assert len(items) <= 5 and total >= len(items)
        sdk.disconnect()
    else:
        assert sdk.version() == (0, 0, 0)
        with pytest.raises(OSError):
            sdk.search("x")
