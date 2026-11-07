from dataclasses import dataclass

from alles.dupes import MODE_CONTENT, MODE_NAME_SIZE, find_duplicates, wasted_bytes


@dataclass
class R:
    path: str
    name: str
    size: int
    is_dir: bool = False


def rows_for(tmp_path, files):
    out = []
    for rel, data in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        out.append(R(str(p), p.name, len(data)))
    return out


def test_name_and_size(tmp_path):
    rows = rows_for(tmp_path, {"a/x.txt": b"1234", "b/x.txt": b"abcd", "c/X.TXT": b"zzzz",
                               "d/y.txt": b"1234", "e/x.txt": b"12345"})
    groups = find_duplicates(rows, MODE_NAME_SIZE)
    assert len(groups) == 1 and len(groups[0]) == 3


def test_content_hash_ignores_names(tmp_path):
    big = b"A" * 200_000
    rows = rows_for(tmp_path, {"a/1.bin": big, "b/2.bin": big, "c/3.bin": big[:-1] + b"B",
                               "d/s1": b"same", "e/s2": b"same", "f/s3": b"diff"})
    groups = find_duplicates(rows, MODE_CONTENT)
    sets = sorted(sorted(r.name for r in g) for g in groups)
    assert sets == [["1.bin", "2.bin"], ["s1", "s2"]]
    assert groups[0][0].size == 200_000  # biggest waste first
    assert wasted_bytes(groups) == 200_000 + 4


def test_min_size_dirs_and_missing_files(tmp_path):
    rows = [R("C:\\nope\\a", "a", 10), R("C:\\nope\\b", "a", 10), R("C:\\d", "d", 0, True)]
    assert find_duplicates(rows, MODE_NAME_SIZE, min_size=11) == []
    assert find_duplicates(rows, MODE_CONTENT) == []  # unreadable -> skipped


def test_stop_returns_quickly(tmp_path):
    rows = rows_for(tmp_path, {"a": b"x" * 10, "b": b"x" * 10})
    assert find_duplicates(rows, MODE_CONTENT, stop=lambda: True) == []
