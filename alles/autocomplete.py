"""Autocomplete popup for Everything syntax under the search box."""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont

from .assist import suggest

_IGNORE_KEYS = {"Up", "Down", "Return", "KP_Enter", "Escape", "Tab", "Shift_L", "Shift_R",
                "Control_L", "Control_R", "Alt_L", "Alt_R", "Left", "Right", "Home", "End"}


class SyntaxCompleter:
    def __init__(self, entry, palette: callable, on_accept: callable):
        self.entry = entry
        self.palette = palette
        self.on_accept = on_accept
        self.top: tk.Toplevel | None = None
        self.listbox: tk.Listbox | None = None
        self.items = []
        self.start = 0
        entry.bind("<KeyRelease>", self._on_key, add="+")
        entry.bind("<FocusOut>", lambda e: entry.after(200, self._hide_if_unfocused), add="+")

    @property
    def active(self) -> bool:
        return self.top is not None and bool(self.items)

    def _on_key(self, event):
        if event.keysym not in _IGNORE_KEYS:
            self.refresh()

    def refresh(self):
        text = self.entry.get()
        cursor = self.entry.index(tk.INSERT)
        self.start, self.items = suggest(text, cursor)
        if self.items:
            self._show()
        else:
            self.hide()

    def _show(self):
        p = self.palette()
        if self.top is None:
            self.top = tk.Toplevel(self.entry)
            self.top.wm_overrideredirect(True)
            self.top.wm_attributes("-topmost", True)
            font = tkfont.nametofont("TkDefaultFont")
            self.listbox = tk.Listbox(self.top, activestyle="none", relief="solid",
                                      borderwidth=1, highlightthickness=0, font=font,
                                      exportselection=False)
            self.listbox.pack(fill=tk.BOTH, expand=True)
            self.listbox.bind("<ButtonRelease-1>", lambda e: self.accept())
        lb = self.listbox
        lb.configure(bg=p["surface"], fg=p["fg"], selectbackground=p["select"],
                     selectforeground=p["select_fg"])
        lb.delete(0, tk.END)
        for s in self.items:
            lb.insert(tk.END, f"  {s.label:<14}{s.hint}")
        lb.configure(height=len(self.items), width=max(34, max(len(s.label) + len(s.hint) + 6
                                                             for s in self.items)))
        lb.selection_clear(0, tk.END)
        lb.selection_set(0)
        try:
            x_off = self.entry.bbox(self.start)[0]
        except (tk.TclError, TypeError, IndexError):
            x_off = 0
        x = self.entry.winfo_rootx() + x_off
        y = self.entry.winfo_rooty() + self.entry.winfo_height() + 2
        self.top.wm_geometry(f"+{x}+{y}")
        self.top.deiconify()

    def move(self, delta: int):
        if not self.active:
            return
        cur = self.listbox.curselection()
        i = (cur[0] if cur else 0) + delta
        i = max(0, min(len(self.items) - 1, i))
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(i)
        self.listbox.see(i)

    def accept(self) -> bool:
        if not self.active:
            return False
        cur = self.listbox.curselection()
        s = self.items[cur[0] if cur else 0]
        text = self.entry.get()
        cursor = self.entry.index(tk.INSERT)
        new = text[:self.start] + s.insert + text[cursor:]
        self.entry.delete(0, tk.END)
        self.entry.insert(0, new)
        self.entry.icursor(self.start + len(s.insert))
        self.entry.focus_set()
        self.hide()
        self.on_accept()
        if s.insert.endswith(":"):  # directly offer values, e.g. after "dm:"
            self.entry.after(10, self.refresh)
        return True

    def _hide_if_unfocused(self):
        focus = self.entry.focus_get()
        if focus is not self.entry and focus is not self.listbox:
            self.hide()

    def hide(self):
        self.items = []
        if self.top is not None:
            self.top.destroy()
            self.top = None
            self.listbox = None
