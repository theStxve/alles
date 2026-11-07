import pytest

from alles.assist import (
    close_words,
    current_token,
    is_simple_term,
    natural_to_syntax,
    probe_fragments,
    suggest,
)
from alles.index.syntax import compile_query
from alles.query import TYPE_PRESETS


def labels(text, cursor=None):
    start, sug = suggest(text, len(text) if cursor is None else cursor)
    return start, [s.insert for s in sug]


def test_current_token():
    assert current_token("rechnung ex", 11) == (9, "ex")
    assert current_token("<jpg|pn", 7) == (5, "pn")
    assert current_token("!tem", 4) == (1, "tem")


def test_suggest_modifiers():
    start, ins = labels("rechnung e")
    assert start == 9 and "ext:" in ins
    assert labels("si")[1] == ["size:"]
    assert labels("ext:")[1][:2] == ["ext:pdf", "ext:docx"]
    assert labels("")[1] == [] and labels("abc ")[1] == []


def test_suggest_values():
    assert labels("dm:la")[1] == ["dm:lastweek", "dm:lastmonth", "dm:lastyear",
                                  "dm:last7days", "dm:last30days"]
    assert "size:>1gb" in labels("size:>")[1]
    assert labels("ext:pdf;do")[1] == ["ext:pdf;docx"]
    assert labels("dm:today")[1] == []  # already complete
    assert labels('"ext')[1] == []      # inside a phrase


@pytest.mark.parametrize("text,expected", [
    ("pdfs von letzter woche größer 5 mb", "size:>5mb dm:lastweek ext:pdf"),
    ("bilder von gestern", "dm:yesterday " + TYPE_PRESETS["Bilder"]),
    ("rechnung aus 2024", "dm:2024 rechnung"),
    ("excel dateien in downloads", "\\downloads\\ ext:xls;xlsx;csv"),
    ("videos über 1 gb", "size:>1gb " + TYPE_PRESETS["Videos"]),
    ("dateien der letzten 7 tage", "dm:last7days"),
    ("leere dateien", "file: size:0"),
    ("musik kleiner als 3,5mb", "size:<3.5mb " + TYPE_PRESETS["Musik"]),
    ("angebot im ordner projekte", "\\projekte\\ angebot"),
])
def test_natural_to_syntax(text, expected):
    assert natural_to_syntax(text) == expected
    compile_query(expected)  # and the built-in index understands the result


@pytest.mark.parametrize("text", ["rechnung", "ext:pdf letzte woche", "", "urlaub 2026"])
def test_natural_leaves_plain_or_syntax_alone(text):
    assert natural_to_syntax(text) is None


def test_typos():
    names = ["Rechnung 2024.pdf", "Rechnungen", "Angebot.docx", "Urlaub.jpg"]
    assert close_words("rehcnung", names)[0] == "rechnung"
    assert close_words("angebto", names) == ["angebot"]
    assert close_words("xyzxyz", names) == []
    assert is_simple_term("rehcnung") and not is_simple_term("ext:pdf")
    assert not is_simple_term("abc")
    assert probe_fragments("rehcnung") == ["reh", "ung", "cnu"]
