import datetime as dt
import os

from alles.rename import (
    MODE_REPLACE,
    MODE_TEMPLATE,
    execute,
    name_problem,
    plan,
    render_template,
    split_name,
    undo,
)

D = dt.datetime(2026, 11, 8, 12, 0)


def files(tmp_path, *names):
    out = []
    for n in names:
        p = tmp_path / n
        p.write_text(n)
        out.append((str(p), False, D))
    return out


def test_name_problem():
    assert name_problem("ok.txt") == ""
    assert name_problem("a:b") and name_problem("") and name_problem("x.")
    assert name_problem("CON.txt") and name_problem("a" * 300)


def test_split_name():
    assert split_name("bild.JPG") == ("bild", ".JPG")
    assert split_name(".gitignore") == (".gitignore", "")
    assert split_name("Ordner.v2", is_dir=True) == ("Ordner.v2", "")


def test_render_template():
    assert render_template("Urlaub_{n:03}", "IMG_1.jpg", 7, D) == "Urlaub_007.jpg"
    assert render_template("{date}_{name}", "a.txt", 1, D) == "2026-11-08_a.txt"
    assert render_template("{name}.{ext}.bak", "a.txt", 1, D) == "a.txt.bak"
    assert render_template("{date:%Y}", "x.pdf", 1, D) == "2026.pdf"


def test_replace_keeps_extension_and_is_case_insensitive(tmp_path):
    items = files(tmp_path, "IMG_001.jpg", "img_002.JPG")
    plans = plan(items, MODE_REPLACE, find="img_", replace="Urlaub-")
    assert [os.path.basename(p.new) for p in plans] == ["Urlaub-001.jpg", "Urlaub-002.JPG"]
    assert all(not p.error for p in plans)


def test_regex_replace_and_invalid_regex(tmp_path):
    items = files(tmp_path, "scan 12.pdf")
    p = plan(items, MODE_REPLACE, find=r"(\d+)", replace=r"Nr\1", regex=True)[0]
    assert os.path.basename(p.new) == "scan Nr12.pdf"
    assert "regulärer Ausdruck" in plan(items, MODE_REPLACE, find="(", regex=True)[0].error


def test_conflicts_detected(tmp_path):
    items = files(tmp_path, "a.txt", "b.txt", "c.txt")
    plans = plan(items, MODE_TEMPLATE, template="gleich")
    assert all("denselben Namen" in p.error for p in plans)
    (tmp_path / "exists.txt").write_text("x")
    p = plan(items[:1], MODE_TEMPLATE, template="exists")[0]
    assert "existiert bereits" in p.error


def test_swap_and_undo(tmp_path):
    items = files(tmp_path, "a.txt", "b.txt")
    plans = plan(items, MODE_REPLACE, find="", replace="")  # no-op
    assert not any(p.changed for p in plans)
    # swap a <-> b via template with explicit per-item names is not possible, so
    # simulate it by planning manually
    from alles.rename import RenamePlan
    swap = [RenamePlan(items[0][0], items[1][0]), RenamePlan(items[1][0], items[0][0])]
    done, errors = execute(swap)
    assert not errors and len(done) == 2
    assert (tmp_path / "a.txt").read_text() == "b.txt"
    reverted, errors = undo(done)
    assert errors == [] and len(reverted) == 2
    assert (tmp_path / "a.txt").read_text() == "a.txt"


def test_numbering_in_order(tmp_path):
    items = files(tmp_path, "z.jpg", "y.jpg", "x.jpg")
    plans = plan(items, MODE_TEMPLATE, template="Foto {n}", start=10)
    done, errors = execute(plans)
    assert not errors
    assert sorted(os.listdir(tmp_path)) == ["Foto 10.jpg", "Foto 11.jpg", "Foto 12.jpg"]
    assert (tmp_path / "Foto 10.jpg").read_text() == "z.jpg"


def test_folder_and_its_content_are_not_renamed_together(tmp_path):
    folder = tmp_path / "X"
    folder.mkdir()
    (folder / "a.txt").write_text("a")
    items = [(str(folder / "a.txt"), False, D), (str(folder), True, D)]
    plans = plan(items, MODE_TEMPLATE, template="neu_{n}")
    assert "ebenfalls umbenannt" in plans[0].error and not plans[1].error
    done, errors = execute(plans)
    assert not errors and (tmp_path / "neu_2" / "a.txt").exists()  # file untouched


def test_conflict_with_unchanged_selected_item(tmp_path):
    items = files(tmp_path, "a.txt", "b.txt")
    plans = plan(items, MODE_REPLACE, find="a", replace="b")  # a->b, b stays b
    assert "existiert bereits" in plans[0].error
