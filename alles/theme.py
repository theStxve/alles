"""Light (native Windows) and dark ttk themes."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import win_style

THEME_SYSTEM, THEME_LIGHT, THEME_DARK = "system", "light", "dark"
THEME_LABELS = {THEME_SYSTEM: "Wie Windows", THEME_LIGHT: "Hell", THEME_DARK: "Dunkel"}

LIGHT = {
    "bg": "#f3f3f3", "surface": "#ffffff", "field": "#ffffff", "fg": "#1b1b1b",
    "muted": "#6b6b6b", "accent": "#2563eb", "select": "#cfe0ff", "select_fg": "#1b1b1b",
    "border": "#d6d6d6", "dir": "#1f5fbf", "heading": "#f3f3f3", "group": "#eef3ff",
}
DARK = {
    "bg": "#202020", "surface": "#272727", "field": "#1b1b1b", "fg": "#e8e8e8",
    "muted": "#9d9d9d", "accent": "#5b9aff", "select": "#2f4f86", "select_fg": "#ffffff",
    "border": "#3b3b3b", "dir": "#7fb0ff", "heading": "#2c2c2c", "group": "#25324a",
}


def resolve(mode: str) -> bool:
    """True for dark."""
    if mode == THEME_DARK:
        return True
    if mode == THEME_LIGHT:
        return False
    return win_style.detect_dark_mode()


def apply(root: tk.Tk, mode: str) -> dict:
    """Apply the theme to all ttk widgets. Returns the palette for tk widgets."""
    dark = resolve(mode)
    style = ttk.Style(root)
    pal = DARK if dark else LIGHT
    if not dark and "vista" in style.theme_names():
        style.theme_use("vista")
        style.configure("Treeview", background=pal["surface"], fieldbackground=pal["surface"],
                        foreground=pal["fg"])
        style.map("Treeview", background=[("selected", "#cce4f7")],
                  foreground=[("selected", pal["fg"])])
    else:
        style.theme_use("clam")
        _configure_clam(style, pal)
    style.configure("Hint.TLabel", foreground=pal["muted"])
    style.configure("Accent.TLabel", foreground=pal["accent"])
    style.configure("Preview.TFrame", background=pal["surface"])
    style.configure("Preview.TLabel", background=pal["surface"], foreground=pal["fg"])
    style.configure("PreviewHint.TLabel", background=pal["surface"], foreground=pal["muted"])
    root.configure(bg=pal["bg"])
    # tk (non-ttk) widgets: combobox drop-downs, menus, text
    for pattern, value in (("*TCombobox*Listbox.background", pal["field"]),
                           ("*TCombobox*Listbox.foreground", pal["fg"]),
                           ("*TCombobox*Listbox.selectBackground", pal["select"]),
                           ("*TCombobox*Listbox.selectForeground", pal["select_fg"]),
                           ("*Menu.background", pal["surface"]),
                           ("*Menu.foreground", pal["fg"]),
                           ("*Menu.activeBackground", pal["select"]),
                           ("*Menu.activeForeground", pal["select_fg"])):
        root.option_add(pattern, value)
    win_style.set_dark_title_bar(root, dark)
    return dict(pal, dark=dark)


def style_toplevel(win: tk.Toplevel, pal: dict) -> None:
    """Dialogs: matching background and (dark) title bar."""
    win.configure(bg=pal["bg"])
    win_style.set_dark_title_bar(win, pal.get("dark", False))


def _configure_clam(style: ttk.Style, p: dict) -> None:
    style.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["field"],
                    bordercolor=p["border"], lightcolor=p["bg"], darkcolor=p["bg"],
                    troughcolor=p["bg"], focuscolor=p["accent"], selectbackground=p["select"],
                    selectforeground=p["select_fg"], insertcolor=p["fg"], arrowcolor=p["fg"])
    style.map(".", foreground=[("disabled", p["muted"])])
    style.configure("TButton", background=p["surface"], padding=(10, 4), relief="flat")
    style.map("TButton", background=[("pressed", p["select"]), ("active", p["heading"])],
              bordercolor=[("focus", p["accent"])])
    style.configure("TCheckbutton", background=p["bg"], indicatorbackground=p["field"],
                    indicatorforeground=p["fg"])
    style.map("TCheckbutton", background=[("active", p["bg"])],
              indicatorbackground=[("selected", p["accent"]), ("disabled", p["bg"])],
              indicatorforeground=[("selected", "#ffffff")])
    style.configure("TRadiobutton", background=p["bg"], indicatorbackground=p["field"],
                    indicatorforeground=p["fg"])
    style.map("TRadiobutton", background=[("active", p["bg"])],
              indicatorbackground=[("selected", p["accent"]), ("disabled", p["bg"])],
              indicatorforeground=[("selected", "#ffffff")])
    style.configure("TEntry", fieldbackground=p["field"], foreground=p["fg"], padding=4)
    style.map("TEntry", fieldbackground=[("readonly", p["surface"])],
              bordercolor=[("focus", p["accent"])])
    style.configure("TCombobox", fieldbackground=p["field"], background=p["surface"],
                    foreground=p["fg"], padding=3)
    style.map("TCombobox", fieldbackground=[("readonly", p["field"])],
              foreground=[("readonly", p["fg"])], background=[("active", p["heading"])],
              bordercolor=[("focus", p["accent"])],
              selectbackground=[("readonly", p["field"])],
              selectforeground=[("readonly", p["fg"])])
    style.configure("TSpinbox", fieldbackground=p["field"], foreground=p["fg"],
                    background=p["surface"])
    style.configure("TLabelframe", background=p["bg"], bordercolor=p["border"])
    style.configure("TLabelframe.Label", background=p["bg"], foreground=p["muted"])
    style.configure("Treeview", background=p["surface"], fieldbackground=p["surface"],
                    foreground=p["fg"], bordercolor=p["border"])
    style.map("Treeview", background=[("selected", p["select"])],
              foreground=[("selected", p["select_fg"])])
    style.configure("Treeview.Heading", background=p["heading"], foreground=p["fg"],
                    relief="flat", bordercolor=p["border"])
    style.map("Treeview.Heading", background=[("active", p["select"])])
    style.configure("TScrollbar", background=p["heading"], troughcolor=p["bg"],
                    bordercolor=p["bg"], arrowcolor=p["muted"])
    style.map("TScrollbar", background=[("active", p["border"])])
    style.configure("TPanedwindow", background=p["bg"])
    style.configure("Sash", sashthickness=6, gripcount=0, background=p["bg"])
    style.configure("TNotebook", background=p["bg"], bordercolor=p["border"])
    style.configure("TNotebook.Tab", background=p["heading"], foreground=p["fg"],
                    padding=(10, 4))
    style.map("TNotebook.Tab", background=[("selected", p["surface"])])
    style.configure("TMenubutton", background=p["bg"], foreground=p["fg"], padding=(8, 3))
    style.map("TMenubutton", background=[("active", p["heading"])])
