"""Persistent settings in %APPDATA%\\ALLES\\config.json (atomic writes)."""
from __future__ import annotations

import json
import os
import tempfile

APP_NAME = "ALLES"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
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
