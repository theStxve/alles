import os
import sys
import time

import pytest

from alles import everything_sdk as es
from alles.index.store import Excluder, IndexStore, dedupe_roots, norm_root
from alles.index.syntax import Flags, compile_query
from alles.index.watcher import coalesce, parse_notify_buffer
from alles.query import SearchOptions, build_query

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


def make_tree(base):
    files = {
        "Projekte/alles/README.md": b"hello",
        "Projekte/alles/app.py": b"print(1)" * 100,
        "Projekte/alles/node_modules/junk.js": b"x",
        "Projekte/Rechnung 2024.pdf": b"%PDF" + b"0" * 5000,
        "Bilder/Urlaub/IMG_0001.JPG": b"\xff" * 3000,
        "Bilder/Urlaub/IMG_0002.jpg": b"\xff" * 2000,
        "Bilder/logo.png": b"png",
        "leer.txt": b"",
    }
    for rel, data in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return files


@pytest.fixture
def index(tmp_path):
    root = tmp_path / "data"
    make_tree(root)
    store = IndexStore(str(tmp_path / "idx" / "index.db"))
    n = store.rebuild([str(root)], ["node_modules"])
    yield store, root, n
    store.close()


def search(store, text, sort=es.SORT_NAME_ASCENDING, flags=None, limit=100):
    hits, total = store.search(compile_query(text, flags or Flags()), sort, 0, limit)
    return [h.name for h in hits], total


def test_rebuild_counts_and_skips_excluded(index):
    store, root, n = index
    names, total = search(store, "")
    assert "junk.js" not in names and "node_modules" not in names
    assert total == n == len(names)
    assert {"README.md", "Projekte", "Bilder", "Urlaub"} <= set(names)


def test_substring_and_case(index):
    store, *_ = index
    assert search(store, "img")[0] == ["IMG_0001.JPG", "IMG_0002.jpg"]
    assert search(store, "img_0002", flags=Flags(match_case=True))[0] == []
    assert search(store, "IMG_0002", flags=Flags(match_case=True))[0] == ["IMG_0002.jpg"]


def test_filters_from_query_builder(index):
    store, root, _ = index
    q = build_query(SearchOptions(type="Bilder", size="< 1 MB"))
    names, _ = search(store, q.search)
    assert set(names) == {"IMG_0001.JPG", "IMG_0002.jpg", "logo.png"}
    q = build_query(SearchOptions(type="Nur Ordner"))
    assert set(search(store, q.search)[0]) == {"Projekte", "alles", "Bilder", "Urlaub"}


def test_or_not_wildcards_and_path(index):
    store, *_ = index
    assert set(search(store, "*.pdf | *.md")[0]) == {"Rechnung 2024.pdf", "README.md"}
    assert search(store, "ext:jpg !0001")[0] == ["IMG_0002.jpg"]
    assert set(search(store, "\\urlaub\\")[0]) == {"IMG_0001.JPG", "IMG_0002.jpg"}
    assert search(store, '"rechnung 2024"')[0] == ["Rechnung 2024.pdf"]
    assert search(store, "size:0")[0] == ["leer.txt"]


def test_parent_and_regex(index):
    store, root, _ = index
    names, _ = search(store, f'parent:"{root / "Bilder"}"')
    assert set(names) == {"Urlaub", "logo.png"}
    assert search(store, r"regex:^img_\d+\.jpg$")[0] == ["IMG_0001.JPG", "IMG_0002.jpg"]


def test_sorting_and_paging(index):
    store, *_ = index
    names, _ = search(store, "ext:jpg;pdf;png", sort=es.SORT_SIZE_DESCENDING)
    assert names[0] == "Rechnung 2024.pdf" and names[-1] == "logo.png"
    hits, total = store.search(compile_query("ext:jpg;pdf;png"), 1, 1, 2)
    assert total == 4 and len(hits) == 2  # offset 1, limit 2 -> total counted


def test_hit_paths_are_correct(index):
    store, root, _ = index
    hits, _ = store.search(compile_query("logo.png"), 1, 0, 10)
    assert hits[0].path == str(root / "Bilder" / "logo.png")
    assert hits[0].folder == str(root / "Bilder")
    assert hits[0].size == 3 and not hits[0].is_dir


def test_apply_changes_add_modify_remove(index):
    store, root, _ = index
    new = root / "Projekte" / "neu.txt"
    new.write_bytes(b"12345")
    store.apply_changes([("add", str(new))], [])
    assert search(store, "neu.txt")[0] == ["neu.txt"]
    new.write_bytes(b"1234567890")
    store.apply_changes([("modify", str(new))], [])
    hits, _ = store.search(compile_query("neu.txt"), 1, 0, 10)
    assert hits[0].size == 10
    # new folder with content is scanned recursively
    sub = root / "Neu" / "tief"
    sub.mkdir(parents=True)
    (sub / "datei.bin").write_bytes(b"x")
    store.apply_changes([("add", str(root / "Neu"))], [])
    assert search(store, "datei.bin")[0] == ["datei.bin"]
    # removing a folder removes its whole subtree
    store.apply_changes([("remove", str(root / "Neu"))], [])
    assert search(store, "datei.bin")[0] == [] and search(store, "tief")[0] == []
    store.apply_changes([("remove", str(new))], [])
    assert search(store, "neu.txt")[0] == []


def test_stats_and_meta(index):
    store, root, n = index
    st = store.stats()
    assert st["entries"] == n and st["roots"] == [norm_root(str(root))]
    assert float(store.meta()["built_at"]) <= time.time()


def test_rebuild_can_be_cancelled(tmp_path):
    root = tmp_path / "d"
    make_tree(root)
    store = IndexStore(str(tmp_path / "i.db"))
    assert store.rebuild([str(root)], [], should_stop=lambda: True) == -1
    assert not store.exists()


def test_excluder_rules():
    ex = Excluder(["node_modules", "C:\\Windows\\WinSxS", "AppData\\Local\\Temp", "*.tmp"])
    assert ex.skip_dir("d:\\x\\node_modules", "node_modules")
    assert ex.skip_dir("c:\\windows\\winsxs\\amd64", "amd64")
    assert ex.skip_dir("c:\\users\\a\\appdata\\local\\temp", "temp")  # fragment
    assert ex.skip_dir("c:\\users\\a\\appdata\\local\\temp\\x", "x")
    assert ex.skip_dir("c:\\$recycle.bin", "$recycle.bin")
    assert not ex.skip_dir("c:\\windows\\system32", "system32")
    assert not ex.skip_dir("c:\\data\\x.tmp", "x.tmp")  # wildcards are ignored


def test_exclusions_behave_the_same_in_both_modes(index):
    """The Everything terms, evaluated by our own syntax engine, must hide the same
    folders' contents as the indexer does."""
    from alles.query import exclusion_terms
    store, root, _ = index
    for rule in ["Urlaub", "Bilder\\Urlaub", str(root / "Bilder" / "Urlaub"), "*.jpg"]:
        q = build_query(SearchOptions(text="img"), excludes=[rule])
        names, _ = search(store, q.search)
        hidden = rule != "*.jpg"
        assert ("IMG_0001.JPG" not in names) is hidden, (rule, exclusion_terms([rule]))
        sub = IndexStore(str(root.parent / f"sub{abs(hash(rule))}.db"))
        sub.rebuild([str(root)], [rule])
        sub_names, _ = search(sub, "img")
        sub.close()
        assert ("IMG_0001.JPG" not in sub_names) is hidden, rule


def test_dedupe_roots():
    roots = dedupe_roots(["c:\\", "C:\\Users", "d:\\data\\", "D:\\Data"])
    assert [r.lower() for r in roots] == ["c:", "d:\\data"]


def test_parse_notify_buffer():
    def rec(action, name, last=False):
        raw = name.encode("utf-16-le")
        size = 12 + len(raw)
        size += (-size) % 4
        nxt = 0 if last else size
        body = (nxt.to_bytes(4, "little") + action.to_bytes(4, "little")
                + len(raw).to_bytes(4, "little") + raw)
        return body.ljust(size, b"\0")
    buf = rec(1, "a.txt") + rec(4, "old\\x") + rec(5, "new\\x", last=True)
    assert parse_notify_buffer(buf) == [("add", "a.txt"), ("rename_old", "old\\x"),
                                        ("rename_new", "new\\x")]


def test_coalesce():
    ev = [("add", "C:\\a"), ("modify", "C:\\A"), ("remove", "C:\\b"), ("add", "C:\\b")]
    assert coalesce(ev) == [("add", "C:\\A"), ("add", "C:\\b")]
    assert coalesce([("add", "x"), ("remove", "x")]) == [("remove", "x")]


@windows_only
def test_watcher_picks_up_real_changes(tmp_path):
    from alles.index.watcher import FolderWatcher

    got = []
    w = FolderWatcher(str(tmp_path), lambda root, ev: got.extend(ev), lambda root: None)
    w.start()
    time.sleep(0.3)
    (tmp_path / "hello.txt").write_text("hi")
    os.rename(tmp_path / "hello.txt", tmp_path / "bye.txt")
    deadline = time.time() + 5
    while time.time() < deadline and not any(p.endswith("bye.txt") for _, p in got):
        time.sleep(0.05)
    w.stop()
    actions = {(a, os.path.basename(p)) for a, p in got}
    assert ("add", "hello.txt") in actions
    assert ("remove", "hello.txt") in actions and ("add", "bye.txt") in actions


def test_exclusion_terms_work_in_index(index):
    store, *_ = index
    q = build_query(SearchOptions(text=""), excludes=["Urlaub"])
    names, _ = search(store, q.search)
    assert "IMG_0001.JPG" not in names and "Urlaub" in names  # folder itself stays


@windows_only
def test_service_does_not_feed_on_its_own_database(tmp_path):
    """Regression: the index lives on an indexed drive. Its own writes must not
    trigger endless re-indexing."""
    from alles.index.service import IndexService

    root = tmp_path / "root"
    make_tree(root)
    store = IndexStore(str(root / "AppData" / "ALLES" / "index.db"))
    states = []
    svc = IndexService(store, lambda: [str(root)], lambda: [], states.append, max_age=0)
    svc.start()
    deadline = time.time() + 10
    while time.time() < deadline and not (states and not states[-1].building
                                          and store.exists()):
        time.sleep(0.05)
    assert store.exists()
    names, _ = search(store, "index")
    assert names == []  # our own database is not indexed
    (root / "live.txt").write_text("x")  # a real change still gets in
    time.sleep(2.0)
    assert search(store, "live.txt")[0] == ["live.txt"]
    before = len(states)
    time.sleep(2.5)  # idle: nothing may happen any more
    svc.stop()
    assert len(states) == before
