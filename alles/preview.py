"""Preview pane: Explorer thumbnail, file details and text content."""
from __future__ import annotations

import codecs
import os
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from .i18n import _
from .util import fmt_count, fmt_date, fmt_size

TEXT_EXTS = {
    "txt", "md", "log", "ini", "cfg", "conf", "toml", "yaml", "yml", "json", "xml", "csv",
    "tsv", "py", "pyw", "js", "mjs", "ts", "tsx", "jsx", "c", "h", "cpp", "hpp", "cs", "java",
    "kt", "go", "rs", "rb", "php", "html", "htm", "css", "scss", "sql", "sh", "bat", "cmd",
    "ps1", "psm1", "lua", "pl", "r", "swift", "vb", "vbs", "reg", "gitignore", "env", "spec",
    "iss", "nfo", "srt", "properties", "gradle", "dockerfile", "makefile",
}
MAX_TEXT_BYTES = 64 * 1024
THUMB_SIZE = 256


def read_text_preview(path: str, limit: int = MAX_TEXT_BYTES) -> str | None:
    """First bytes of a text file, or None for binary files."""
    try:
        with open(path, "rb") as f:
            data = f.read(limit)
    except OSError:
        return None
    truncated = len(data) == limit
    if b"\x00" in data[:4096]:
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return data[:len(data) & ~1].decode("utf-16", "replace")
        return None
    try:
        # incremental decoder: a multibyte char cut off at the limit is simply dropped
        dec = codecs.getincrementaldecoder("utf-8-sig")()
        return dec.decode(data, final=not truncated)
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


class PreviewPane(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, style="Preview.TFrame", padding=12)
        self.app = app
        self._gen = 0
        self._photo = None
        self._cond = threading.Condition()
        self._request = None
        threading.Thread(target=self._worker, name="preview", daemon=True).start()

        self.columnconfigure(0, weight=1)
        self.image = ttk.Label(self, style="Preview.TLabel", anchor=tk.CENTER)
        self.image.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold", size=bold.cget("size") + 1)
        # textvariables bypass the translation hook - file names must stay untouched
        self.v_title, self.v_details = tk.StringVar(), tk.StringVar()
        self.title = ttk.Label(self, style="Preview.TLabel", font=bold, wraplength=280,
                               justify=tk.LEFT, textvariable=self.v_title)
        self.title.grid(row=1, column=0, sticky="w")
        self.details = ttk.Label(self, style="PreviewHint.TLabel", justify=tk.LEFT,
                                 wraplength=280, textvariable=self.v_details)
        self.details.grid(row=2, column=0, sticky="w", pady=(4, 8))
        mono = tkfont.Font(family="Cascadia Mono", size=9)
        if "Cascadia Mono" not in tkfont.families():
            mono = tkfont.Font(family="Consolas", size=9)
        self.text = tk.Text(self, wrap="none", height=12, font=mono, relief="flat",
                            borderwidth=0, highlightthickness=0, padx=6, pady=6)
        self.text_scroll = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.text.yview)
        self.text.configure(yscrollcommand=self.text_scroll.set, state="disabled")
        self.rowconfigure(3, weight=1)
        self.bind("<Configure>", self._on_resize)
        self.show_empty()

    def apply_palette(self, pal: dict):
        self.text.configure(bg=pal["field"], fg=pal["fg"], insertbackground=pal["fg"],
                            selectbackground=pal["select"])

    def _on_resize(self, event):
        wrap = max(120, event.width - 30)
        self.title.configure(wraplength=wrap)
        self.details.configure(wraplength=wrap)

    def show_empty(self, text="Wähle eine Datei aus, um eine Vorschau zu sehen."):
        self._gen += 1
        self._photo = None
        self.image.configure(image="", text="")
        self.v_title.set("")
        self.v_details.set(_(text))
        self._hide_text()

    def _hide_text(self):
        self.text.grid_remove()
        self.text_scroll.grid_remove()

    def show(self, row, count: int = 1):
        if count > 1:
            self.show_empty(f"{count} Elemente ausgewählt")
            return
        self._gen += 1
        gen = self._gen
        self.v_title.set(row.name)
        lines = [self.app.type_name(row)]
        if not row.is_dir and row.size is not None:
            lines.append(_(f"Größe: {fmt_size(row.size)} ({fmt_count(row.size)} Bytes)"))
        if row.modified:
            lines.append(_(f"Geändert: {fmt_date(row.modified)}"))
        lines.append(row.folder)  # a path - never translated
        self.v_details.set("\n".join(lines))
        self.image.configure(image="", text="…")
        self._hide_text()
        is_text = not row.is_dir and (row.ext.lower() in TEXT_EXTS or (
            not row.ext and row.size is not None and row.size < 512 * 1024))
        # thumbnails fit the pane; text files only get a small icon above the content
        size = 48 if is_text else max(64, min(THUMB_SIZE, self.winfo_width() - 40))
        with self._cond:
            self._request = (gen, row, size, is_text)
            self._cond.notify()

    # -- background loading
    def _worker(self):
        from . import thumbs
        while True:
            with self._cond:
                while self._request is None:
                    self._cond.wait()
                (gen, row, size, is_text), self._request = self._request, None
            png = text = None
            try:
                png = thumbs.thumbnail_png(row.path, size, icon_only=is_text)
            except OSError:
                png = None
            if gen != self._gen:
                continue
            if is_text:
                text = read_text_preview(row.path)
            self.app.dispatch(self._show_loaded, gen, row, png, text)

    def _show_loaded(self, gen, row, png, text):
        if gen != self._gen:
            return
        if png:
            try:
                self._photo = tk.PhotoImage(data=png)
                self.image.configure(image=self._photo, text="")
            except tk.TclError:
                self.image.configure(image="", text="")
        else:
            exists = os.path.exists(row.path)
            self.image.configure(image="", text="" if exists else "Datei nicht mehr vorhanden")
        if text is not None:
            self.text.configure(state="normal")
            self.text.delete("1.0", tk.END)
            self.text.insert("1.0", text)
            self.text.configure(state="disabled")
            self.text.grid(row=3, column=0, sticky="nsew")
            self.text_scroll.grid(row=3, column=1, sticky="ns")
