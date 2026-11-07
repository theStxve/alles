import datetime as dt

import pytest

from alles.index.syntax import (
    And,
    Flags,
    Not,
    Or,
    Term,
    UnsupportedSyntax,
    compile_query,
    date_range,
    parse,
    parse_size,
    tokenize,
)

NOW = dt.datetime(2026, 11, 7, 15, 30)  # a Saturday


def test_tokenize_quotes_and_modifiers():
    toks = tokenize('ext:pdf "mein ordner" path:"C:\\a b" !temp')
    assert toks[0] == Term("ext", "pdf")
    assert toks[1] == Term("", "mein ordner", True)
    assert toks[2] == Term("path", "C:\\a b", True)
    assert toks[3] == "!" and toks[4] == Term("", "temp")


def test_drive_letter_is_not_a_modifier():
    assert tokenize("C:\\Users") == [Term("", "C:\\Users")]


def test_parse_precedence_or_binds_tighter_than_and():
    tree = parse("a b | c")
    assert tree == And([Term("", "a"), Or([Term("", "b"), Term("", "c")])])


def test_parse_groups_and_not():
    tree = parse("<a | b> !c")
    assert tree == And([And([Or([Term("", "a"), Term("", "b")])]), Not(Term("", "c"))])


def test_parse_is_forgiving():
    parse("a | | b > <")  # must not raise
    parse("")
    parse("!!!")


def test_compile_plain_text_case_insensitive():
    c = compile_query("Rechnung")
    assert "instr(e.name_lc, ?)" in c.where
    assert c.params == ["rechnung"]


def test_compile_match_case():
    c = compile_query("Rechnung", Flags(match_case=True))
    assert "instr(e.name, ?)" in c.where and c.params == ["Rechnung"]


def test_compile_backslash_matches_path():
    c = compile_query("\\node_modules\\")
    assert "SELECT id FROM dirs WHERE instr(path_lc" in c.where


def test_compile_wildcards_use_glob_and_escape_brackets():
    c = compile_query("*[1].pdf")
    assert "GLOB" in c.where
    assert c.params == ["*[[]1[]].pdf"]


def test_compile_ext_and_size_and_folder():
    c = compile_query("ext:PDF;.docx size:>1mb file:")
    assert c.params[:2] == ["pdf", "docx"]
    assert 1024 * 1024 in c.params
    assert "e.is_dir = 0" in c.where


def test_compile_drive_scope_group():
    c = compile_query("<path:C:\\ | path:D:\\>")
    assert c.params == ["c:", "c:\\*", "d:", "d:\\*"]


def test_compile_regex_validation():
    with pytest.raises(UnsupportedSyntax):
        compile_query("regex:(unclosed")
    c = compile_query("regex:^IMG_\\d+$")
    assert "REGEXP" in c.where and c.params == ["(?i)^IMG_\\d+$"]


def test_unsupported_modifier_is_reported():
    with pytest.raises(UnsupportedSyntax, match="content:"):
        compile_query("content:secret")


def test_empty_query_matches_everything():
    assert compile_query("").where == "1"


@pytest.mark.parametrize("text,expected", [
    ("1kb", 1024), ("1,5 MB", int(1.5 * 1024**2)), ("10", 10), ("2g", 2 * 1024**3)])
def test_parse_size(text, expected):
    assert parse_size(text) == expected


def test_parse_size_rejects_garbage():
    with pytest.raises(UnsupportedSyntax):
        parse_size("viel")


def test_date_constants():
    assert date_range("today", NOW) == (dt.datetime(2026, 11, 7), dt.datetime(2026, 11, 8))
    assert date_range("thisweek", NOW)[0] == dt.datetime(2026, 11, 2)  # Monday
    assert date_range("lastmonth", NOW) == (dt.datetime(2026, 10, 1), dt.datetime(2026, 11, 1))
    assert date_range("lastyear", NOW) == (dt.datetime(2025, 1, 1), dt.datetime(2026, 1, 1))


def test_date_values():
    assert date_range("2024", NOW) == (dt.datetime(2024, 1, 1), dt.datetime(2025, 1, 1))
    assert date_range("2024-12", NOW) == (dt.datetime(2024, 12, 1), dt.datetime(2025, 1, 1))
    assert date_range("31.12.2024", NOW)[0] == dt.datetime(2024, 12, 31)
    assert date_range(">2024-05-01", NOW) == (dt.datetime(2024, 5, 2), None)
    assert date_range("2020..2021", NOW) == (dt.datetime(2020, 1, 1), dt.datetime(2022, 1, 1))
    assert date_range("last7days", NOW)[0] == dt.datetime(2026, 11, 1)


def test_date_garbage():
    with pytest.raises(UnsupportedSyntax):
        date_range("gestern abend", NOW)
