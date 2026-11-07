import json

from alles.config import clamp_int, load_config, push_history, save_config


def test_roundtrip(tmp_path):
    path = tmp_path / "sub" / "config.json"
    cfg = {"max_display": 500, "history": ["äöü", "x"]}
    assert save_config(cfg, str(path))
    assert load_config(str(path)) == cfg
    assert not list(path.parent.glob("*.tmp"))  # temp file cleaned up


def test_load_missing_or_corrupt(tmp_path):
    assert load_config(str(tmp_path / "nope.json")) == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_config(str(bad)) == {}
    arr = tmp_path / "arr.json"
    arr.write_text(json.dumps([1, 2]), encoding="utf-8")
    assert load_config(str(arr)) == {}


def test_save_unserialisable_keeps_old_file(tmp_path):
    path = tmp_path / "config.json"
    save_config({"a": 1}, str(path))
    assert not save_config({"a": object()}, str(path))
    assert load_config(str(path)) == {"a": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_clamp_int():
    assert clamp_int("50", 7, 100, 1000) == 100
    assert clamp_int(5000, 7, 100, 1000) == 1000
    assert clamp_int("abc", 7, 100, 1000) == 7
    assert clamp_int(None, 7, 100, 1000) == 7


def test_push_history():
    h = push_history(["b", "a"], "a")
    assert h == ["a", "b"]
    assert push_history(h, "   ") == h
    assert len(push_history([str(i) for i in range(30)], "new", limit=5)) == 5
