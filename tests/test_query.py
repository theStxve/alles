import pytest

from alles import everything_sdk as es
from alles.query import (
    COLUMN_SORTS,
    DATE_PRESETS,
    SIZE_PRESETS,
    SORT_OPTIONS,
    TYPE_PRESETS,
    SearchOptions,
    build_query,
    drive_scope,
)


def test_empty_query_is_empty_string():
    q = build_query(SearchOptions())
    assert q.search == ""
    assert q.sort == es.SORT_NAME_ASCENDING


def test_text_is_passed_through_untouched():
    q = build_query(SearchOptions(text="  rechnung <2024 | 2025>  "))
    assert q.search == "rechnung <2024 | 2025>"


def test_filters_are_combined_in_stable_order():
    q = build_query(SearchOptions(text="urlaub", type="Bilder", size="> 1 GB", date="Heute"))
    assert q.search == f"{TYPE_PRESETS['Bilder']} size:>1gb dm:today urlaub"


def test_single_drive_scope_without_group():
    q = build_query(SearchOptions(all_drives=False, drives=["d:\\"]))
    assert q.search == "path:D:\\"


def test_multi_drive_scope_uses_everything_grouping():
    # Everything groups with < >, NOT with parentheses
    assert drive_scope(["C:\\", "E:\\"]) == "<path:C:\\ | path:E:\\>"


def test_all_drives_ignores_drive_list():
    q = build_query(SearchOptions(all_drives=True, drives=["C:\\"]))
    assert "path:" not in q.search


def test_no_drive_selected_means_no_scope():
    assert drive_scope([]) == ""
    assert drive_scope(["", "\\"]) == ""


def test_regex_uses_modifier_not_global_flag():
    q = build_query(SearchOptions(text=r"^IMG_\d+", regex=True, type="Bilder"))
    assert q.search.endswith(r"regex:^IMG_\d+")
    assert q.search.startswith("ext:")  # filters stay normal Everything syntax


def test_regex_with_spaces_is_quoted():
    q = build_query(SearchOptions(text="foo bar", regex=True))
    assert q.search == 'regex:"foo bar"'


def test_flags_and_sort_are_forwarded():
    q = build_query(SearchOptions(match_case=True, whole_word=True, match_path=True,
                                  sort="Größe (ab)"))
    assert (q.match_case, q.whole_word, q.match_path) == (True, True, True)
    assert q.sort == es.SORT_SIZE_DESCENDING


def test_unknown_preset_values_fall_back_safely():
    q = build_query(SearchOptions(type="???", size="???", date="???", sort="???"))
    assert q.search == ""
    assert q.sort == es.SORT_NAME_ASCENDING


def test_size_range_uses_dotdot_syntax():
    assert SIZE_PRESETS["1 - 100 MB"] == "size:1mb..100mb"


@pytest.mark.parametrize("table", [TYPE_PRESETS, SIZE_PRESETS, DATE_PRESETS])
def test_preset_values_have_no_spaces(table):
    # a space would split the filter into two AND terms
    for value in table.values():
        assert value is None or " " not in value


def test_column_sorts_reference_existing_options():
    for asc, desc in COLUMN_SORTS.values():
        assert asc in SORT_OPTIONS and desc in SORT_OPTIONS


def test_exclusion_terms():
    from alles.query import exclusion_terms
    assert exclusion_terms(["node_modules", "C:\\Windows\\WinSxS\\", " ", 'x"y']) == [
        r'!"\node_modules\"', r'!"C:\Windows\WinSxS\"']


def test_build_query_appends_exclusions():
    q = build_query(SearchOptions(text="app"), excludes=[".git"])
    assert q.search == r'app !"\.git\"'


def test_builtin_presets_use_valid_values():
    from alles.query import BUILTIN_PRESETS
    for preset in BUILTIN_PRESETS.values():
        assert preset["type"] in TYPE_PRESETS and preset["size"] in SIZE_PRESETS
        assert preset["date"] in DATE_PRESETS and preset["sort"] in SORT_OPTIONS
