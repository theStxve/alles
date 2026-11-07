"""Smoke tests against the real Everything64.dll (skipped when unavailable)."""
import sys

import pytest

from alles import everything_sdk as es

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def _sdk_or_skip():
    try:
        return es.EverythingSDK()
    except (OSError, FileNotFoundError):
        pytest.skip("Everything64.dll not available")


def test_dll_loads_and_reports_version_tuple():
    sdk = _sdk_or_skip()
    ver = sdk.get_version()
    assert len(ver) == 3 and all(isinstance(v, int) for v in ver)


def test_query_against_running_everything():
    sdk = _sdk_or_skip()
    if not sdk.is_running():
        pytest.skip("Everything is not running")
    sdk.reset()
    sdk.set_search("ext:exe")
    sdk.set_max(5)
    sdk.set_request_flags(es.REQUEST_FULL_PATH_AND_FILE_NAME | es.REQUEST_SIZE)
    n = sdk.query()
    assert n <= 5
    for i in range(n):
        assert sdk.get_result_full_path(i)


def test_missing_dll_gives_clear_error():
    with pytest.raises(FileNotFoundError, match="nicht gefunden"):
        es._resolve_dll("DoesNotExist123.dll")
