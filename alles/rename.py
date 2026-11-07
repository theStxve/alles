"""Planning and executing (batch) renames - pure logic, no UI."""
from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass

INVALID_CHARS = set('<>:"/\\|?*') | {chr(c) for c in range(32)}
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
            *(f"lpt{i}" for i in range(1, 10))}

MODE_REPLACE = "replace"
MODE_TEMPLATE = "template"


@dataclass
class RenamePlan:
    old: str          # full path
    new: str          # full path
    error: str = ""   # non-empty -> this item can't be renamed

    @property
    def changed(self) -> bool:
        return os.path.basename(self.old) != os.path.basename(self.new)


def name_problem(name: str) -> str:
    """Why `name` is not a valid Windows file name ('' if it is fine)."""
    if not name or not name.strip():
        return "Name ist leer"
    if any(c in INVALID_CHARS for c in name):
        return 'Unerlaubtes Zeichen (\\ / : * ? " < > |)'
    if name.endswith((" ", ".")):
        return "Name darf nicht auf Leerzeichen oder Punkt enden"
    if name.split(".")[0].lower() in RESERVED:
        return "Reservierter Windows-Name"
    if len(name) > 255:
        return "Name ist zu lang"
    return ""


def split_name(name: str, is_dir: bool = False) -> tuple[str, str]:
    """'bild.jpg' -> ('bild', '.jpg'); folders and dotfiles keep the whole name."""
    if is_dir:
        return name, ""
    stem, ext = os.path.splitext(name)
    if not stem:  # ".gitignore"
        return name, ""
    return stem, ext


def render_template(template: str, name: str, index: int, modified: _dt.datetime | None,
                    is_dir: bool = False) -> str:
    """Placeholders: {name} {ext} {n} {n:03} {date} {date:%Y-%m-%d}."""
    stem, ext = split_name(name, is_dir)

    def repl(m):
        key, fmt = m.group(1), m.group(2)
        if key == "name":
            return stem
        if key == "ext":
            return ext.lstrip(".")
        if key == "n":
            return format(index, fmt or "d")
        if key == "date":
            return (modified or _dt.datetime.now()).strftime(fmt or "%Y-%m-%d")
        return m.group(0)

    out = re.sub(r"\{(name|ext|n|date)(?::([^}]*))?\}", repl, template)
    if "{ext}" not in template and ext and not out.lower().endswith(ext.lower()):
        out += ext  # keep the extension unless the template handles it
    return out


def plan(items: list[tuple[str, bool, _dt.datetime | None]], mode: str, *, find: str = "",
         replace: str = "", regex: bool = False, case: bool = False, template: str = "",
         start: int = 1) -> list[RenamePlan]:
    """items: (full path, is_dir, modified). Returns one plan per item in order."""
    plans: list[RenamePlan] = []
    pattern = None
    if mode == MODE_REPLACE and find:
        try:
            pattern = re.compile(find if regex else re.escape(find), 0 if case else re.I)
        except re.error as exc:
            return [RenamePlan(p, p, f"Ungültiger regulärer Ausdruck: {exc}") for p, _, _ in items]
    for i, (path, is_dir, modified) in enumerate(items):
        folder, name = os.path.split(path)
        if mode == MODE_REPLACE:
            stem, ext = split_name(name, is_dir)
            new_name = (pattern.sub(replace, stem) if pattern else stem) + ext
        else:
            new_name = render_template(template, name, start + i, modified, is_dir)
        new_name = new_name.strip()
        plans.append(RenamePlan(path, os.path.join(folder, new_name), name_problem(new_name)))
    _mark_conflicts(plans)
    return plans


def _mark_conflicts(plans: list[RenamePlan]) -> None:
    targets: dict[str, int] = {}
    olds = {os.path.normcase(p.old) for p in plans}
    for p in plans:
        if p.error or not p.changed:
            continue
        key = os.path.normcase(p.new)
        targets[key] = targets.get(key, 0) + 1
    for p in plans:
        if p.error or not p.changed:
            continue
        key = os.path.normcase(p.new)
        if targets[key] > 1:
            p.error = "Mehrere Dateien bekommen denselben Namen"
        elif key != os.path.normcase(p.old) and key not in olds and os.path.exists(p.new):
            p.error = "Datei mit diesem Namen existiert bereits"


def execute(plans: list[RenamePlan]) -> tuple[list[tuple[str, str]], list[str]]:
    """Run the valid, changed plans. Uses temporary names so swaps (a<->b) work.
    Returns (done [(old, new)], errors)."""
    todo = [p for p in plans if p.changed and not p.error]
    done, errors, temp = [], [], []
    for i, p in enumerate(todo):
        tmp = os.path.join(os.path.dirname(p.old), f".alles-rename-{os.getpid()}-{i}")
        try:
            os.rename(p.old, tmp)
            temp.append((tmp, p))
        except OSError as exc:
            errors.append(f"{os.path.basename(p.old)}: {exc.strerror or exc}")
    for tmp, p in temp:
        try:
            os.rename(tmp, p.new)
            done.append((p.old, p.new))
        except OSError as exc:
            try:
                os.rename(tmp, p.old)
            except OSError:
                pass
            errors.append(f"{os.path.basename(p.old)}: {exc.strerror or exc}")
    return done, errors


def undo(done: list[tuple[str, str]]) -> list[str]:
    plans = [RenamePlan(new, old) for old, new in done]
    return execute(plans)[1]
