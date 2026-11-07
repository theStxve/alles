import pytest

from alles import i18n


@pytest.fixture
def english():
    i18n.set_language("en")
    yield
    i18n.set_language("de")


def test_german_is_identity():
    i18n.set_language("de")
    assert i18n._("Öffnen") == "Öffnen"
    assert i18n.keys("Strg+S") == "Strg+S"


def test_exact_and_whitespace(english):
    assert i18n._("Öffnen") == "Open"
    assert i18n._("  Öffnen ") == "  Open "
    assert i18n._("Völlig unbekannter Text") == "Völlig unbekannter Text"


def test_templates_and_recursion(english):
    assert i18n._("15 Treffer") == "15 results"
    assert i18n._("15 Treffer  ·  3 ms  ·  Eigener Index") == "15 results  ·  3 ms  ·  Own index"
    assert i18n._("2.000+ Treffer (2.000 geladen, mehr beim Scrollen)  ·  9 ms  ·  Everything") \
        == "2.000+ results (2.000 loaded, more when scrolling)  ·  9 ms  ·  Everything"
    assert i18n._("Suchmodus: Eigener Index") == "Search mode: Own index"
    assert i18n._("Name ▲") == "Name ▲" and i18n._("Größe ▼") == "Size ▼"


def test_multiline_and_tabs(english):
    msg = "Datei nicht gefunden:\nC:\\x.exe"
    assert i18n._(msg) == "File not found:\nC:\\x.exe"
    assert i18n._("Strg+Q\tBeenden") == "Ctrl+Q\tExit"


def test_keys(english):
    assert i18n.keys("Strg+Umschalt+C") == "Ctrl+Shift+C"
    assert i18n.keys("Entf") == "Del"


def test_every_template_compiles(english):
    for de in i18n.CATALOG:
        i18n._(de)  # must not raise


def test_catalog_covers_all_presets():
    from alles.query import BUILTIN_PRESETS, DATE_PRESETS, SIZE_PRESETS, SORT_OPTIONS, TYPE_PRESETS
    from alles.theme import THEME_LABELS
    for table in (TYPE_PRESETS, SIZE_PRESETS, DATE_PRESETS, SORT_OPTIONS, BUILTIN_PRESETS):
        for key in table:
            assert key in i18n.CATALOG, key
    for label in THEME_LABELS.values():
        assert label in i18n.CATALOG


def test_detect_language_returns_known_value():
    assert i18n.detect_windows_language() in ("de", "en")


def test_english_formats(english):
    import datetime as dt

    from alles.util import MOD_CONTROL, MOD_SHIFT, fmt_count, fmt_date, fmt_size, vk_display
    assert fmt_size(1536) == "1.5 KB" and fmt_count(1234567) == "1,234,567"
    assert fmt_date(dt.datetime(2026, 11, 8, 9, 5)) == "2026-11-08 09:05"
    assert vk_display(MOD_CONTROL | MOD_SHIFT, 0x20) == "Ctrl+Shift+Space"
    i18n.set_language("de")
    assert fmt_size(1536) == "1,5 KB" and vk_display(MOD_CONTROL, 0x20) == "Strg+Leertaste"
