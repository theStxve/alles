import pytest

from alles.index import store as store_mod
from alles.index.store import IndexStore, content_match
from alles.index.syntax import compile_query
from alles.query import SearchOptions, build_query, has_restricting_filter


def write(p, text, enc="utf-8"):
    p.write_bytes(text.encode(enc))
    return str(p), p.stat().st_size


@pytest.mark.parametrize("enc", ["utf-8", "utf-16", "cp1252"])
def test_content_match_encodings(tmp_path, enc):
    path, size = write(tmp_path / "f.txt", "Die Größe der RECHNUNG beträgt 42 €", enc)
    assert content_match(path, size, 0, "rechnung")
    assert content_match(path, size, 0, "größe")
    assert not content_match(path, size, 0, "angebot")


def test_content_match_across_chunk_border(tmp_path, monkeypatch):
    monkeypatch.setattr(store_mod, "_CONTENT_CHUNK", 16)
    path, size = write(tmp_path / "f.txt", "x" * 13 + "geheimwort" + "y" * 40)
    assert content_match(path, size, 0, "geheimwort")  # split over two 16-byte chunks
    path, size = write(tmp_path / "g.txt", "x" * 14 + "Übersicht" + "y" * 40)
    assert content_match(path, size, 0, "übersicht")


def test_content_match_skips_dirs_big_and_missing(tmp_path):
    path, size = write(tmp_path / "f.txt", "treffer")
    assert not content_match(path, size, 1, "treffer")
    assert not content_match(path, store_mod.CONTENT_MAX_BYTES + 1, 0, "treffer")
    assert not content_match(str(tmp_path / "fehlt.txt"), 5, 0, "treffer")


def test_content_query_in_index(tmp_path):
    root = tmp_path / "d"
    root.mkdir()
    (root / "a.txt").write_text("Bitte Angebot prüfen", encoding="utf-8")
    (root / "b.txt").write_text("nichts", encoding="utf-8")
    (root / "c.md").write_text("Angebot", encoding="utf-8")
    s = IndexStore(str(tmp_path / "i.db"))
    s.rebuild([str(root)], [])
    q = build_query(SearchOptions(text=".txt", content="angebot"))
    assert q.search == '.txt content:"angebot"'
    hits, total = s.search(compile_query(q.search), 1, 0, 50)
    s.close()
    assert [h.name for h in hits] == ["a.txt"] and total == 1


def test_restricting_filter_rule():
    assert not has_restricting_filter(SearchOptions(content="x"))
    assert has_restricting_filter(SearchOptions(content="x", text="bericht"))
    assert has_restricting_filter(SearchOptions(content="x", type="Dokumente"))
    assert has_restricting_filter(SearchOptions(content="x", date="Heute"))


def test_content_is_only_read_for_rows_passing_other_filters(tmp_path, monkeypatch):
    calls = []
    real = store_mod.content_match

    def counting(*args):
        calls.append(args[0])
        return real(*args)

    monkeypatch.setattr(store_mod, "content_match", counting)
    root = tmp_path / "d"
    root.mkdir()
    for i in range(200):
        (root / f"datei{i}.log").write_text("x")
    (root / "bericht.txt").write_text("treffer")
    s = IndexStore(str(tmp_path / "i.db"))
    s.rebuild([str(root)], [])
    hits, _ = s.search(compile_query('bericht content:"treffer"'), 1, 0, 50)
    s.close()
    assert [h.name for h in hits] == ["bericht.txt"]
    assert len(calls) == 1  # not 201 file reads
