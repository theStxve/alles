"""Persistent settings in %APPDATA%\\ALLES\\config.json (atomic writes)."""
from __future__ import annotations

import json
import os
import sys
import tempfile

APP_NAME = "ALLES"
PORTABLE_DIR_NAME = "ALLES-Daten"


def _portable_dir() -> str | None:
    """Portable mode: $ALLES_HOME, or an 'ALLES-Daten' folder next to the program."""
    env = os.environ.get("ALLES_HOME")
    if env:
        return os.path.abspath(env)
    base = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False)
                                           else sys.argv[0] or "."))
    candidate = os.path.join(base, PORTABLE_DIR_NAME)
    return candidate if os.path.isdir(candidate) else None


PORTABLE_DIR = _portable_dir()
CONFIG_DIR = PORTABLE_DIR or os.path.join(
    os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
DATA_DIR = PORTABLE_DIR or os.path.join(
    os.environ.get("LOCALAPPDATA") or CONFIG_DIR, APP_NAME)  # big files (search index)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_MAX_DISPLAY = 2000
MIN_MAX_DISPLAY = 100
MAX_MAX_DISPLAY = 100_000
HISTORY_SIZE = 25


def load_config(path: str = CONFIG_FILE) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(cfg: dict, path: str = CONFIG_FILE) -> bool:
    """Write the config atomically so a crash never leaves a corrupt file."""
    try:
        folder = os.path.dirname(path)
        os.makedirs(folder, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=folder)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except (OSError, TypeError, ValueError):
        return False


def clamp_int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def push_history(history: list[str], entry: str, limit: int = HISTORY_SIZE) -> list[str]:
    """Most-recent-first history without duplicates."""
    entry = entry.strip()
    if not entry:
        return list(history)
    out = [entry] + [h for h in history if h != entry]
    return out[:limit]
