"""Small pure helpers (formatting, hotkey names). No Tk, no ctypes."""
from __future__ import annotations

import datetime as _dt

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

_SPECIAL_KEYS = {
    0x08: "Rücktaste", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc", 0x20: "Leertaste",
    0x21: "Bild↑", 0x22: "Bild↓", 0x23: "Ende", 0x24: "Pos1",
    0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓", 0x2D: "Einfg", 0x2E: "Entf",
    0xBA: "Ü", 0xBB: "+", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "#", 0xC0: "Ö",
    0xDC: "^", 0xDE: "Ä",
}

# Keys that are modifiers themselves and cannot be the "main" key of a hotkey.
MODIFIER_VKS = frozenset({0x10, 0x11, 0x12, 0x14, 0x5B, 0x5C,
                          0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5})


def vk_name(vk: int) -> str:
    if vk in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[vk]
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    if 0x60 <= vk <= 0x69:
        return f"Num{vk - 0x60}"
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    return f"VK 0x{vk:02X}"


def vk_display(mod: int, vk: int) -> str:
    parts = []
    if mod & MOD_CONTROL:
        parts.append("Strg")
    if mod & MOD_ALT:
        parts.append("Alt")
    if mod & MOD_SHIFT:
        parts.append("Umschalt")
    if mod & MOD_WIN:
        parts.append("Win")
    return "+".join(parts + [vk_name(vk)])


def is_valid_hotkey(mod: int, vk: int) -> bool:
    """A global hotkey needs a non-modifier key and Ctrl/Alt/Win (Shift alone is
    not enough - it would swallow normal typing)."""
    if vk in MODIFIER_VKS or not (0 < vk < 0xFF):
        return False
    is_fkey = 0x70 <= vk <= 0x87
    return bool(mod & (MOD_CONTROL | MOD_ALT | MOD_WIN)) or is_fkey


def fmt_size(size: int | None) -> str:
    if size is None or size < 0:
        return ""
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KB", "MB", "GB", "TB", "PB"):
        value /= 1024
        if value < 1024 or unit == "PB":
            return f"{value:,.1f} {unit}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ""  # pragma: no cover


def fmt_date(value: _dt.datetime | None) -> str:
    return value.strftime("%d.%m.%Y %H:%M") if value else ""


def fmt_count(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def parse_geometry(geo: str) -> tuple[int, int, int, int] | None:
    """'WxH+X+Y' (Tk geometry, X/Y may be negative) -> (w, h, x, y)."""
    import re

    m = re.fullmatch(r"\s*(\d+)x(\d+)\+(-?\d+)\+(-?\d+)\s*", geo or "")
    if not m:
        return None
    w, h, x, y = (int(v) for v in m.groups())
    return w, h, x, y


def geometry_visible(geo: tuple[int, int, int, int],
                     virtual: tuple[int, int, int, int]) -> bool:
    """True if a window at geo is reachable on the virtual screen (vx, vy, vw, vh)."""
    w, h, x, y = geo
    vx, vy, vw, vh = virtual
    if w < 200 or h < 150:
        return False
    # at least the title bar area must be on screen
    return vx - w + 100 <= x <= vx + vw - 100 and vy - 10 <= y <= vy + vh - 50
