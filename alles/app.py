"""
ALLES - a friendlier GUI front-end for "Everything" (voidtools) with an optional
built-in index, so it also works completely without Everything.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import json
import logging
import logging.handlers
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import __version__, shell, theme, win_style
from . import config as cfgmod
from .backends import (
    BACKEND_AUTO,
    BACKEND_EVERYTHING,
    BACKEND_INDEX,
    EverythingBackend,
    IndexBackend,
    Row,
    SearchError,
    Status,
)
from .index.service import IndexService, IndexState
from .index.store import IndexStore
from .locate import find_everything_exe
from .preview import PreviewPane
from .query import (
    BUILTIN_PRESETS,
    COLUMN_SORTS,
    DATE_PRESETS,
    DEFAULT_EXCLUDES,
    DEFAULT_SORT,
    SIZE_PRESETS,
    SORT_OPTIONS,
    TYPE_PRESETS,
    Query,
    SearchOptions,
    build_query,
    has_restricting_filter,
)
from .util import fmt_count, fmt_size, geometry_visible, parse_geometry, vk_display

WINDOW_TITLE = "ALLES – Dateisuche"
MUTEX_NAME = "Local\\ALLES_SingleInstance"
log = logging.getLogger("alles")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetForegroundWindow.restype = ctypes.c_void_p
_user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]

STATUS_COLORS = {"ok": "#2e9d5b", "warn": "#d08a1e", "err": "#d64545", "info": "#8a8a8a"}
COLUMNS = (("folder", "Ordner", 330, tk.W), ("size", "Größe", 85, tk.E),
           ("modified", "Geändert", 125, tk.W), ("type", "Typ", 130, tk.W))
NAME_COL_WIDTH = 270
WATCHDOG_INTERVAL = 5.0
AUTOSTART_COOLDOWN = 60.0
CONFIRM_OPEN_MANY = 10
LOCAL_DATA = cfgmod.DATA_DIR


def normalize_folder_arg(folder: str) -> str:
    """Explorer passes drives as "C:\\" - the backslash escapes the closing quote, so
    we receive 'C:"'. Strip stray quotes and give bare drive letters their root."""
    folder = folder.strip().strip('"').strip()
    if len(folder) == 2 and folder[1] == ":":
        folder += "\\"
    return folder


@dataclass
class SearchRequest:
    gen: int
    query: Query
    offset: int
    limit: int
    append: bool


def setup_logging() -> str:
    os.makedirs(cfgmod.CONFIG_DIR, exist_ok=True)
    path = os.path.join(cfgmod.CONFIG_DIR, "alles.log")
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=512_000, backupCount=2,
                                                   encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("alles")
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    return path


class AllesApp:
    def __init__(self, root: tk.Tk, cfg: dict, start_hidden: bool = False,
                 initial_text: str = ""):
        self.root = root
        self.cfg = cfg
        self.tray = None
        self.icon_path = win_style.app_icon_path()
        self._ui_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._closing = False
        self._search_timer = None
        self._preview_timer = None
        self._gen = 0
        self._req_cond = threading.Condition()
        self._pending: SearchRequest | None = None
        self._rows: list[Row] = []
        self._last_query: Query | None = None
        self._last_start_attempt = 0.0
        self._status: Status | None = None
        self._status_tip = None
        self._icons: dict[tuple[str, bool], object] = {}
        self._type_names: dict[tuple[str, bool], str] = {}
        self._icon_png: dict[tuple[str, bool], tuple[bytes | None, str]] = {}
        self._icon_lock = threading.Lock()

        # settings
        self.max_display = cfgmod.clamp_int(cfg.get("max_display"), cfgmod.DEFAULT_MAX_DISPLAY,
                                            cfgmod.MIN_MAX_DISPLAY, cfgmod.MAX_MAX_DISPLAY)
        self.auto_repair = bool(cfg.get("auto_repair", True))
        self.close_to_tray = bool(cfg.get("close_to_tray", True))
        self.history: list[str] = [h for h in cfg.get("history", []) if isinstance(h, str)]
        self.excludes: list[str] = list(cfg.get("excludes", DEFAULT_EXCLUDES))
        self.index_roots: list[str] = list(cfg.get("index_roots") or shell.fixed_drives())
        self.presets: dict[str, dict] = dict(cfg.get("presets") or {})
        self.auto_update = bool(cfg.get("auto_update", True))
        self.available_update = None  # update.Release once a newer version was found

        f = cfg.get("filters") if isinstance(cfg.get("filters"), dict) else {}

        def pick(key, table, default):
            v = f.get(key)
            return v if v in table else default

        self.v_text = tk.StringVar(value=initial_text)
        self.v_content = tk.StringVar()
        self.v_all_drives = tk.BooleanVar(value=bool(f.get("all_drives", True)))
        self.v_type = tk.StringVar(value=pick("type", TYPE_PRESETS, "Alles"))
        self.v_size = tk.StringVar(value=pick("size", SIZE_PRESETS, "Egal"))
        self.v_date = tk.StringVar(value=pick("date", DATE_PRESETS, "Egal"))
        self.v_sort = tk.StringVar(value=pick("sort", SORT_OPTIONS, DEFAULT_SORT))
        self.v_case = tk.BooleanVar(value=bool(f.get("case", False)))
        self.v_whole = tk.BooleanVar(value=bool(f.get("whole", False)))
        self.v_regex = tk.BooleanVar(value=bool(f.get("regex", False)))
        self.v_path = tk.BooleanVar(value=bool(f.get("path", False)))
        self.v_preview = tk.BooleanVar(value=bool(cfg.get("preview", True)))
        self.v_theme = tk.StringVar(value=cfg.get("theme", theme.THEME_SYSTEM))
        self.v_syntax = tk.StringVar()
        self.v_status = tk.StringVar(value="Initialisiere…")
        self.v_mode = tk.StringVar()
        self._saved_drives = set(f.get("drives", []) or [])
        self.drive_vars: dict[str, tk.BooleanVar] = {}

        # backends
        self.everything = EverythingBackend()
        self.index = IndexBackend(IndexStore(os.path.join(LOCAL_DATA, "index.db")))
        self.backend = None

        root.title(WINDOW_TITLE)
        root.minsize(820, 460)
        self.scale = root.winfo_fpixels("1i") / 96.0
        self._setup_fonts()
        self.palette = theme.apply(root, self.v_theme.get())
        self._restore_geometry()
        self._build_menu()
        self._build_ui()
        self._apply_palette()
        self._bind_keys()
        self._update_syntax()
        self.v_text.trace_add("write", lambda *_: self._on_filter_changed())
        root.report_callback_exception = self._report_exception

        threading.Thread(target=self._search_worker, name="search", daemon=True).start()
        self._pump()
        self._select_backend()
        threading.Thread(target=self._watchdog_loop, name="watchdog", daemon=True).start()
        root.after(8000, self._maybe_check_update)
        if start_hidden:
            root.withdraw()
        else:
            self.focus_search()

    # ------------------------------------------------------------------ infra
    def dispatch(self, fn, *args):
        """Thread-safe: run fn(*args) on the Tk thread."""
        self._ui_queue.put((fn, args))

    def _pump(self):
        while True:
            try:
                fn, args = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn(*args)
            except Exception:  # noqa: BLE001
                log.exception("UI callback failed")
        if not self._closing:
            self.root.after(25, self._pump)

    def _report_exception(self, exc, val, tb):
        log.error("Unhandled Tk exception", exc_info=(exc, val, tb))
        self.set_status(f"Interner Fehler: {val} (Details in alles.log)", "err")

    # ------------------------------------------------------------------ fonts / theme
    def _setup_fonts(self):
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family="Segoe UI", size=10)
            except tk.TclError:
                pass
        base = tkfont.nametofont("TkDefaultFont")
        self.font_search = base.copy()
        self.font_search.configure(size=13)
        self.row_height = int(base.metrics("linespace") * 1.55)

    def _apply_palette(self):
        p = self.palette
        ttk.Style(self.root).configure("Treeview", rowheight=self.row_height)
        self.tree.tag_configure("dir", foreground=p["dir"])
        self.status_dot.configure(bg=p["bg"])
        self.preview.apply_palette(p)
        for m in self._menus:
            m.configure(bg=p["surface"], fg=p["fg"], activebackground=p["select"],
                        activeforeground=p["select_fg"])

    def set_theme(self, mode: str):
        self.cfg["theme"] = mode
        self.palette = theme.apply(self.root, mode)
        self._apply_palette()

    # ------------------------------------------------------------------ UI
    def _build_menu(self):
        """Own menu bar (ttk menubuttons) so it follows the dark theme."""
        bar = ttk.Frame(self.root, padding=(6, 4, 6, 0))
        bar.pack(fill=tk.X)
        self._menus = []

        def menu(label):
            m = tk.Menu(self.root, tearoff=0)
            mb = ttk.Menubutton(bar, text=label, menu=m, underline=0, style="Toolbutton")
            mb.pack(side=tk.LEFT)
            self.root.bind_all(f"<Alt-{label[0].lower()}>",
                               lambda ev, b=mb: self._post_menubutton(b))
            self._menus.append(m)
            return m

        m = menu("Datei")
        m.add_command(label="Ergebnisse als CSV exportieren…", accelerator="Strg+S",
                      command=self.export_csv)
        m.add_separator()
        m.add_command(label="In den Tray minimieren", accelerator="Esc",
                      command=self.hide_to_tray)
        m.add_command(label="Beenden", accelerator="Strg+Q", command=self.quit)

        m = menu("Ansicht")
        m.add_checkbutton(label="Vorschau", accelerator="Strg+P", variable=self.v_preview,
                          command=self._toggle_preview)
        tm = tk.Menu(m, tearoff=0)
        self._menus.append(tm)
        for key, label in theme.THEME_LABELS.items():
            tm.add_radiobutton(label=label, value=key, variable=self.v_theme,
                               command=lambda k=key: self.set_theme(k))
        m.add_cascade(label="Darstellung", menu=tm)

        m = menu("Werkzeuge")
        m.add_command(label="Duplikate finden…", command=self.open_duplicates)
        m.add_command(label="Diagnose", command=self.run_diagnose)
        m.add_separator()
        m.add_command(label="Everything starten", command=self.start_everything)
        m.add_command(label="Aktuelle Suche in Everything öffnen",
                      command=self.open_in_everything)
        m.add_command(label="Eigenen Index neu aufbauen", command=self.rebuild_index)
        m.add_command(label="Laufwerksliste aktualisieren", command=self._rebuild_drives)
        m.add_separator()
        m.add_command(label="Einstellungen…", accelerator="Strg+,",
                      command=self.open_settings)
        m.add_command(label="Suchverlauf löschen", command=self.clear_history)
        m.add_command(label="Log-Datei öffnen", command=self._open_log)

        m = menu("Hilfe")
        m.add_command(label="Tastenkürzel", accelerator="F1", command=self.show_shortcuts)
        m.add_command(label="Suchsyntax", command=self.show_syntax_help)
        m.add_separator()
        m.add_command(label="Nach Updates suchen…",
                      command=lambda: self.check_for_update(manual=True))
        m.add_command(label="Projektseite auf GitHub",
                      command=lambda: os.startfile("https://github.com/theStxve/alles"))
        m.add_command(label="Über ALLES", command=self.show_about)

        ttk.Label(bar, textvariable=self.v_mode, style="Hint.TLabel").pack(side=tk.RIGHT, padx=6)

    def _post_menubutton(self, mb):
        menu = self.root.nametowidget(mb.cget("menu"))
        menu.tk_popup(mb.winfo_rootx(), mb.winfo_rooty() + mb.winfo_height())
        return "break"

    def _build_ui(self):
        root = self.root

        # --- search row
        top = ttk.Frame(root, padding=(10, 6, 10, 4))
        top.pack(fill=tk.X)
        self.search_entry = ttk.Combobox(top, textvariable=self.v_text, values=self.history,
                                         font=self.font_search)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=3)
        self.search_entry.bind("<<ComboboxSelected>>", lambda e: self.run_search())
        ttk.Button(top, text="Leeren", command=self.clear_search).pack(side=tk.LEFT, padx=(6, 0))
        self.start_btn = ttk.Button(top, text="Everything starten",
                                    command=self.start_everything)

        # --- filters
        fbar = ttk.Frame(root, padding=(10, 2, 10, 2))
        fbar.pack(fill=tk.X)
        for label, var, table, width in (("Typ", self.v_type, TYPE_PRESETS, 12),
                                         ("Größe", self.v_size, SIZE_PRESETS, 11),
                                         ("Geändert", self.v_date, DATE_PRESETS, 12),
                                         ("Sortierung", self.v_sort, SORT_OPTIONS, 16)):
            ttk.Label(fbar, text=label).pack(side=tk.LEFT)
            cb = ttk.Combobox(fbar, textvariable=var, values=list(table), state="readonly",
                              width=width)
            cb.pack(side=tk.LEFT, padx=(4, 12))
            cb.bind("<<ComboboxSelected>>", lambda e: self._on_filter_changed(now=True))
        self.preset_menu = tk.Menu(root, tearoff=0, postcommand=self._fill_preset_menu)
        self._menus.append(self.preset_menu)
        ttk.Menubutton(fbar, text="★ Filter", menu=self.preset_menu).pack(side=tk.LEFT)

        obar = ttk.Frame(root, padding=(10, 2, 10, 2))
        obar.pack(fill=tk.X)
        for label, var in (("Groß/Klein beachten", self.v_case), ("Ganzes Wort", self.v_whole),
                           ("Regex", self.v_regex), ("Auch im Pfad suchen", self.v_path)):
            ttk.Checkbutton(obar, text=label, variable=var,
                            command=lambda: self._on_filter_changed(now=True)).pack(
                side=tk.LEFT, padx=(0, 12))
        ttk.Label(obar, text="Inhalt:").pack(side=tk.LEFT, padx=(12, 4))
        content_entry = ttk.Entry(obar, textvariable=self.v_content, width=24)
        content_entry.pack(side=tk.LEFT)
        content_entry.bind("<Return>", lambda e: self.run_search())
        self.v_content.trace_add("write", lambda *_: self._on_filter_changed(delay=500))

        # --- drive scope
        self.drive_frame = ttk.Frame(root, padding=(10, 2, 10, 2))
        self.drive_frame.pack(fill=tk.X)
        self._rebuild_drives()

        # --- generated syntax
        syn = ttk.Frame(root, padding=(10, 2, 10, 4))
        syn.pack(fill=tk.X)
        ttk.Label(syn, text="Suchsyntax:", style="Hint.TLabel").pack(side=tk.LEFT)
        ttk.Entry(syn, textvariable=self.v_syntax, state="readonly").pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(syn, text="Kopieren",
                   command=lambda: self._to_clipboard(self.v_syntax.get())).pack(side=tk.LEFT)

        # --- status bar
        status = ttk.Frame(root, padding=(10, 3, 10, 6))
        status.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_dot = tk.Canvas(status, width=14, height=14, highlightthickness=0)
        self.status_dot.create_oval(3, 3, 11, 11, fill=STATUS_COLORS["info"], outline="",
                                    tags="dot")
        self.status_dot.pack(side=tk.LEFT)
        self.status_label = ttk.Label(status, textvariable=self.v_status, anchor=tk.W)
        self.status_label.pack(side=tk.LEFT, padx=(6, 0), fill=tk.X, expand=True)
        self.more_btn = ttk.Button(status, text="Weitere laden",
                                   command=lambda: self.run_search(append=True))
        self.update_btn = ttk.Button(status, text="Update verfügbar",
                                     command=lambda: self.open_update_dialog())
        self.status_label.bind("<Enter>", self._show_status_tip)
        self.status_label.bind("<Leave>", self._hide_status_tip)

        # --- results + preview
        self.paned = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=(2, 0))
        tree_frame = ttk.Frame(self.paned)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_frame, columns=[c[0] for c in COLUMNS],
                                 show="tree headings", selectmode="extended")
        widths = self.cfg.get("columns") if isinstance(self.cfg.get("columns"), dict) else {}
        self.tree.heading("#0", text="Name", anchor=tk.W,
                          command=lambda: self.sort_by_column("name"))
        self.tree.column("#0", width=cfgmod.clamp_int(widths.get("name"),
                                                      int(NAME_COL_WIDTH * self.scale), 60,
                                                      3000), stretch=True)
        for key, title, width, anchor in COLUMNS:
            self.tree.heading(key, text=title, anchor=anchor,
                              command=lambda k=key: self.sort_by_column(k))
            w = cfgmod.clamp_int(widths.get(key), int(width * self.scale), 30, 3000)
            self.tree.column(key, width=w, anchor=anchor, stretch=key == "folder")
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.paned.add(tree_frame, weight=3)
        self.preview = PreviewPane(self.paned, self)
        if self.v_preview.get():
            self.paned.add(self.preview, weight=1)
        self._update_sort_headings()
        self._build_context_menu()

    def _build_context_menu(self):
        c = self.ctx = tk.Menu(self.root, tearoff=0)
        self._menus.append(c)
        c.add_command(label="Öffnen", accelerator="Enter", command=self.open_selected)
        c.add_command(label="Öffnen mit…", command=lambda: self._single(shell.open_with))
        c.add_command(label="Im Explorer anzeigen", accelerator="Strg+Enter",
                      command=self.reveal_selected)
        c.add_command(label="Terminal hier öffnen", accelerator="Strg+T",
                      command=self.terminal_here)
        if shell.vscode_path():
            c.add_command(label="In VS Code öffnen",
                          command=lambda: self._single(shell.open_in_vscode))
        c.add_separator()
        c.add_command(label="Pfad kopieren", accelerator="Strg+C", command=self.copy_paths)
        c.add_command(label="Name kopieren", accelerator="Strg+Umschalt+C",
                      command=self.copy_names)
        c.add_command(label="Ordnerpfad kopieren", command=self.copy_folders)
        c.add_separator()
        for label, op in (("Kopieren nach", "copy"), ("Verschieben nach", "move")):
            sub = tk.Menu(c, tearoff=0)
            sub.configure(postcommand=lambda m=sub, o=op: self._fill_target_menu(m, o))
            self._menus.append(sub)
            c.add_cascade(label=label, menu=sub)
        c.add_separator()
        c.add_command(label="In diesem Ordner suchen", command=self.search_in_folder)
        c.add_command(label="Eigenschaften", accelerator="Alt+Enter",
                      command=self.properties_selected)
        c.add_separator()
        c.add_command(label="In den Papierkorb", accelerator="Entf",
                      command=self.recycle_selected)

    def _bind_keys(self):
        r, t, e = self.root, self.tree, self.search_entry
        for seq in ("<Control-f>", "<Control-l>", "<F3>"):
            r.bind_all(seq, lambda ev: self.focus_search())
        r.bind_all("<F5>", lambda ev: self.run_search())
        r.bind_all("<F1>", lambda ev: self.show_shortcuts())
        r.bind_all("<Control-s>", lambda ev: self.export_csv())
        r.bind_all("<Control-q>", lambda ev: self.quit())
        r.bind_all("<Control-comma>", lambda ev: self.open_settings())
        r.bind_all("<Control-p>", lambda ev: self._toggle_preview(flip=True))
        e.bind("<Return>", self._on_search_return)
        e.bind("<Down>", self._focus_results)
        e.bind("<Alt-Down>", lambda ev: self._post_history())
        e.bind("<Escape>", self._on_search_escape)
        t.bind("<Double-1>", self._on_double_click)
        t.bind("<Return>", lambda ev: self.open_selected())
        t.bind("<Control-Return>", lambda ev: self.reveal_selected())
        t.bind("<Alt-Return>", lambda ev: (self.properties_selected(), "break")[1])
        t.bind("<Control-c>", lambda ev: self.copy_paths())
        t.bind("<Control-C>", lambda ev: self.copy_names())
        t.bind("<Control-t>", lambda ev: self.terminal_here())
        t.bind("<Delete>", lambda ev: self.recycle_selected())
        t.bind("<Control-a>", lambda ev: (t.selection_set(t.get_children()), "break")[1])
        t.bind("<Escape>", lambda ev: self.focus_search())
        t.bind("<Up>", self._on_tree_up)
        t.bind("<Button-3>", self._on_right_click)
        t.bind("<<TreeviewSelect>>", lambda ev: self._on_select())

    # ------------------------------------------------------------------ drives
    def _rebuild_drives(self):
        for w in self.drive_frame.winfo_children():
            w.destroy()
        previous = {d for d, v in self.drive_vars.items() if v.get()} or self._saved_drives
        self.drive_vars = {}
        ttk.Label(self.drive_frame, text="Laufwerke").pack(side=tk.LEFT, padx=(0, 8))
        ttk.Checkbutton(self.drive_frame, text="Alle", variable=self.v_all_drives,
                        command=self._on_all_drives_toggle).pack(side=tk.LEFT, padx=(0, 12))
        self.drive_checks = []
        show_labels = self.cfg.get("show_drive_labels", True)
        for d in shell.logical_drives():
            label = shell.drive_label(d) if show_labels else ""
            text = d.rstrip("\\") + (f" {label}" if label else "")
            v = tk.BooleanVar(value=d in previous)
            self.drive_vars[d] = v
            cb = ttk.Checkbutton(self.drive_frame, text=text, variable=v,
                                 command=self._on_drive_toggle)
            cb.pack(side=tk.LEFT, padx=(0, 10))
            self.drive_checks.append(cb)
        self._sync_drive_state()

    def _sync_drive_state(self):
        state = "disabled" if self.v_all_drives.get() else "!disabled"
        for cb in self.drive_checks:
            cb.state([state])

    def _on_all_drives_toggle(self):
        if not self.v_all_drives.get() and not any(v.get() for v in self.drive_vars.values()):
            sysdrive = (os.environ.get("SYSTEMDRIVE", "C:") + "\\").upper()
            if sysdrive in self.drive_vars:
                self.drive_vars[sysdrive].set(True)
        self._sync_drive_state()
        self._on_filter_changed(now=True)

    def _on_drive_toggle(self):
        self.v_all_drives.set(not any(v.get() for v in self.drive_vars.values()))
        self._sync_drive_state()
        self._on_filter_changed(now=True)

    # ------------------------------------------------------------------ backends
    def _select_backend(self):
        mode = self.cfg.get("backend", BACKEND_AUTO)
        use_everything = False
        if mode == BACKEND_EVERYTHING:
            use_everything = True
            self.everything.load()
        elif mode == BACKEND_AUTO and self.everything.load():
            use_everything = self.everything.probe()[0] or bool(self.everything_exe())
        if use_everything:
            if self.index.service:
                self.index.service.stop()
                self.index.service = None
            self.backend = self.everything
        else:
            self.backend = self.index
            self._start_index_service()
        self.v_mode.set(f"Suchmodus: {self.backend.label}")
        log.info("backend: %s (mode=%s)", self.backend.label, mode)
        self._status = None
        self._update_syntax()
        self._check_status()

    def _start_index_service(self):
        if self.index.service:
            return
        minutes = cfgmod.clamp_int(self.cfg.get("index_refresh_minutes"), 60, 0, 10_080)
        svc = IndexService(self.index.store, lambda: list(self.index_roots),
                           lambda: list(self.excludes),
                           on_state=lambda st: self.dispatch(self._on_index_state, st),
                           max_age=minutes * 60 if minutes else float("inf"))
        self.index.service = svc
        svc.start()

    def _on_index_state(self, st: IndexState):
        if self.backend is not self.index:
            return
        was_busy = bool(self._status and self._status.busy)
        status = self.index.status()
        self._apply_status(status)
        if st.error:
            self.set_status(f"Index-Fehler: {st.error}", "err")
        elif st.building:
            folder = st.current if len(st.current) < 70 else "…" + st.current[-68:]
            self.set_status(f"Index wird aufgebaut: {fmt_count(st.scanned)} Einträge  ·  "
                            f"{folder}", "warn")
        elif was_busy:
            self._status = None
            self._apply_status(status)  # fresh index swapped in -> refresh results

    def _check_status(self):
        backend = self.backend
        threading.Thread(target=lambda: self.dispatch(self._apply_status, backend.status(),
                                                      backend), daemon=True).start()

    def _apply_status(self, status: Status, backend=None):
        if backend is not None and backend is not self.backend:
            return
        prev = self._status
        self._status = status
        if self.backend is self.everything and not status.ready and self.everything.available:
            if not self.start_btn.winfo_ismapped():
                self.start_btn.pack(side=tk.LEFT, padx=(6, 0))
        else:
            self.start_btn.pack_forget()
        changed = prev is None or (prev.ready, prev.busy, prev.message) != (
            status.ready, status.busy, status.message)
        if not changed:
            return
        if status.ready:
            if not status.busy:
                if self.backend is self.index:
                    st = self.index.service.state if self.index.service else None
                    n = fmt_count(st.entries) if st else "?"
                    self.set_status(f"Bereit · eigener Index mit {n} Einträgen", "ok")
                else:
                    self.set_status(f"Verbunden mit {status.message}.", "ok")
            self.run_search()
        elif not (self.backend is self.index and status.busy):
            self.set_status(status.message, status.kind)

    def _watchdog_loop(self):
        while not self._closing:
            time.sleep(WATCHDOG_INTERVAL)
            backend = self.backend
            if backend is not self.everything or not self.everything.available:
                continue
            try:
                status = backend.status()
            except Exception:  # noqa: BLE001
                log.exception("watchdog failed")
                continue
            self.dispatch(self._apply_status, status, backend)
            if (not status.ready and not status.busy and self.auto_repair
                    and time.time() - self._last_start_attempt > AUTOSTART_COOLDOWN):
                self.dispatch(self.start_everything, False)

    def everything_exe(self):
        return find_everything_exe(self.cfg.get("everything_exe") or None)

    def start_everything(self, manual=True):
        exe = self.everything_exe()
        if not exe:
            if not manual:
                return
            exe = filedialog.askopenfilename(parent=self.root, title="Everything.exe auswählen",
                                             filetypes=[("Everything", "Everything*.exe"),
                                                        ("Programme", "*.exe")])
            if not exe:
                return
            self.cfg["everything_exe"] = exe
            self.save_config()
        self._last_start_attempt = time.time()
        try:
            subprocess.Popen([exe, "-startup"], close_fds=True)
        except OSError as exc:
            log.error("start Everything failed: %s", exc)
            if manual:
                messagebox.showerror("Fehler", f"Konnte Everything nicht starten:\n{exc}",
                                     parent=self.root)
            return
        log.info("started %s", exe)
        self.set_status("Everything wird gestartet…", "warn")
        self.start_btn.state(["disabled"])
        threading.Thread(target=self._wait_for_everything, daemon=True).start()

    def _wait_for_everything(self):
        self.everything.load()
        deadline = time.time() + 30
        status = None
        while time.time() < deadline and not self._closing:
            time.sleep(0.75)
            status = self.everything.status()
            if status.ready:
                break
        self.dispatch(self._after_start_wait, status)

    def _after_start_wait(self, status):
        self.start_btn.state(["!disabled"])
        if status is None:
            return
        if self.backend is not self.everything:
            if status.ready and self.cfg.get("backend", BACKEND_AUTO) == BACKEND_AUTO:
                self._select_backend()
            return
        self._status = None
        self._apply_status(status)
        if not status.ready and not status.busy:
            self.set_status("Everything antwortet nicht. Läuft evtl. nur der Dienst? Die "
                            "Everything-Oberfläche einmal manuell starten.", "err")

    def open_in_everything(self):
        exe = self.everything_exe()
        if not exe:
            messagebox.showinfo("ALLES", "Everything.exe wurde nicht gefunden.",
                                parent=self.root)
            return
        q = build_query(self.options(), self.excludes)
        args = [exe, "-search", q.search,
                "-case" if q.match_case else "-nocase",
                "-ww" if q.whole_word else "-noww",
                "-matchpath" if q.match_path else "-nomatchpath"]
        try:
            subprocess.Popen(args, close_fds=True)
        except OSError as exc:
            messagebox.showerror("Fehler", str(exc), parent=self.root)

    def rebuild_index(self):
        if self.backend is not self.index:
            if not messagebox.askyesno(
                    "Eigener Index", "Der eigene Index wird nur im Suchmodus „Eigener Index“ "
                    "verwendet. Jetzt zu diesem Modus wechseln und den Index aufbauen?",
                    parent=self.root):
                return
            self.cfg["backend"] = BACKEND_INDEX
            self.save_config()
            self._select_backend()
        if self.index.service:
            self.index.service.rebuild(force=True)

    def index_info_text(self) -> str:
        st = self.index.service.state if self.index.service else None
        store = self.index.store
        if not store.exists():
            return "Noch kein Index vorhanden."
        try:
            stats = store.stats()
            built = float(store.meta().get("built_at", 0) or 0)
        except Exception:  # noqa: BLE001
            return "Index-Informationen nicht verfügbar."
        when = time.strftime("%d.%m.%Y %H:%M", time.localtime(built)) if built else "-"
        return "\n".join([
            f"{fmt_count(stats['entries'])} Einträge · {fmt_size(stats.get('bytes', 0))} "
            "auf der Festplatte",
            f"Zuletzt komplett aufgebaut: {when}",
            f"Live-Überwachung: {st.watching if st else 0} Ordner"])

    # ------------------------------------------------------------------ diagnose
    def run_diagnose(self):
        self.set_status("Diagnose läuft…", "info")
        threading.Thread(target=self._diagnose_worker, daemon=True).start()

    def _diagnose_worker(self):
        try:
            text = self._diagnose_text()
        except Exception as exc:  # noqa: BLE001
            log.exception("diagnose failed")
            text = f"Diagnose fehlgeschlagen: {exc}"
        self.dispatch(lambda: messagebox.showinfo("ALLES Diagnose", text, parent=self.root))
        self.dispatch(self._check_status)

    def _diagnose_text(self) -> str:
        lines = [f"ALLES {__version__}  ·  Python {sys.version.split()[0]}",
                 f"Suchmodus: {self.backend.label}", ""]
        if self.backend is self.index:
            lines.append(self.index_info_text())
            lines.append("Indizierte Ordner: " + ", ".join(self.index_roots))
            return "\n".join(lines)
        lines.append(f"Everything.exe: {self.everything_exe() or 'nicht gefunden'}")
        ev = self.everything
        if not ev.available:
            lines.append(f"SDK: NICHT geladen ({ev.error})")
            return "\n".join(lines)
        lines.append(f"SDK: {ev.sdk.dll_path}")
        alive, db, ver = ev.probe()
        if not alive:
            lines += ["", "Everything antwortet nicht (läuft evtl. nur der Dienst)."]
            return "\n".join(lines)
        lines.append(f"Everything {ver[0]}.{ver[1]}.{ver[2]}, Datenbank "
                     f"{'geladen' if db else 'lädt noch'}")
        indexed, missing = [], []
        for d in shell.logical_drives():
            n = ev.count_in(f'parent:"{d}"')
            (indexed if n > 0 else missing).append(d.rstrip("\\"))
        lines += ["", "Im Everything-Index: " + (", ".join(indexed) or "-")]
        if missing:
            lines += ["NICHT im Index: " + ", ".join(missing), "",
                      "Tipp: FAT/exFAT- und Netzlaufwerke müssen in Everything unter",
                      "Extras > Optionen > Indizes > Ordner hinzugefügt werden – oder",
                      "du nutzt den Suchmodus „Eigener Index“, der sie direkt einliest."]
        return "\n".join(lines)

    # ------------------------------------------------------------------ search
    def options(self) -> SearchOptions:
        return SearchOptions(
            text=self.v_text.get(), all_drives=self.v_all_drives.get(),
            drives=[d for d, v in self.drive_vars.items() if v.get()],
            type=self.v_type.get(), size=self.v_size.get(), date=self.v_date.get(),
            sort=self.v_sort.get(), match_case=self.v_case.get(),
            whole_word=self.v_whole.get(), regex=self.v_regex.get(),
            match_path=self.v_path.get(), content=self.v_content.get())

    def current_query(self, files_only: bool = False) -> Query:
        opts = self.options()
        if files_only and opts.type in ("Alles", "Nur Ordner"):
            opts.type = "Nur Dateien"
        # the built-in index never contains excluded folders -> no extra terms needed
        excludes = self.excludes if self.backend is self.everything else ()
        return build_query(opts, excludes)

    def _update_syntax(self):
        self.v_syntax.set(self.current_query().search or "(alles)")

    def _on_filter_changed(self, now=False, delay=150):
        self._update_sort_headings()
        self._update_syntax()
        if self._search_timer:
            self.root.after_cancel(self._search_timer)
        self._search_timer = self.root.after(0 if now else delay, self.run_search)

    def run_search(self, append=False):
        self._search_timer = None
        q = self._last_query if append and self._last_query else self.current_query()
        self.v_syntax.set(q.search or "(alles)")
        if self.backend is None or (self._status and not self._status.ready):
            return
        opts = self.options()
        if opts.content.strip() and not append:
            if not has_restricting_filter(opts):
                self._gen += 1  # drop results of an earlier search
                self.set_status("Inhaltssuche liest Dateien – bitte zusätzlich einen Suchbegriff, "
                                "Typ, Größe oder Datum wählen.", "warn")
                return
            self.set_status("Durchsuche Dateiinhalte … (Weitertippen bricht ab)", "info")
        self._gen += 1
        offset = len(self._rows) if append else 0
        req = SearchRequest(self._gen, q, offset, self.max_display, append)
        with self._req_cond:
            self._pending = req
            self._req_cond.notify()
        if not append:
            self._last_query = q

    def _search_worker(self):
        from . import thumbs
        while True:
            with self._req_cond:
                while self._pending is None:
                    self._req_cond.wait()
                req, self._pending = self._pending, None
            backend = self.backend
            try:
                result = backend.search(req.query, req.offset, req.limit,
                                        lambda g=req.gen: g != self._gen)
            except SearchError as exc:
                result = exc
            except Exception as exc:  # noqa: BLE001
                log.exception("search failed")
                result = exc
            if result is None:
                continue
            if not isinstance(result, Exception):
                self._prepare_icons(result.rows, thumbs)
            self.dispatch(self._on_search_done, req, result)

    def _prepare_icons(self, rows, thumbs):
        """Look up icons/type names for new extensions off the UI thread."""
        try:
            thumbs.com_init()
            for key in {(r.ext.lower(), r.is_dir) for r in rows}:
                with self._icon_lock:
                    if key in self._icon_png:
                        continue
                info = thumbs.type_info(key[0], key[1], max(16, int(16 * self.scale)))
                with self._icon_lock:
                    self._icon_png[key] = info
        except OSError:
            pass

    def _icon_for(self, row: Row):
        key = (row.ext.lower(), row.is_dir)
        img = self._icons.get(key)
        if img is None:
            with self._icon_lock:
                png, name = self._icon_png.get(key, (None, ""))
            self._type_names[key] = name
            try:
                img = tk.PhotoImage(data=png) if png else ""
            except tk.TclError:
                img = ""
            self._icons[key] = img
        return img

    def type_name(self, row: Row) -> str:
        key = (row.ext.lower(), row.is_dir)
        if key not in self._type_names:
            self._icon_for(row)
        return self._type_names.get(key) or ("Ordner" if row.is_dir else
                                             (row.ext.upper() + "-Datei" if row.ext else "Datei"))

    def _on_search_done(self, req: SearchRequest, result):
        if req.gen != self._gen:
            return
        if isinstance(result, Exception):
            self.set_status(str(result), "err")
            if self.backend is self.everything:
                self._check_status()
            return
        if not req.append:
            self.tree.delete(*self.tree.get_children())
            self._rows = []
            self.tree.yview_moveto(0)
        start = len(self._rows)
        for i, row in enumerate(result.rows, start):
            folder, size, date, _ = row.display()
            self.tree.insert("", tk.END, iid=str(i), text=" " + row.name,
                             image=self._icon_for(row),
                             values=(folder, size, date, self.type_name(row)),
                             tags=("dir",) if row.is_dir else ())
        self._rows.extend(result.rows)
        shown = len(self._rows)
        more = result.total > shown
        if more:
            self.more_btn.pack(side=tk.RIGHT)
        else:
            self.more_btn.pack_forget()
        total = fmt_count(result.total) + ("+" if result.capped else "")
        text = f"{total} Treffer"
        if more:
            text += f" ({fmt_count(shown)} angezeigt)"
        self.set_status(f"{text}  ·  {result.elapsed_ms:.0f} ms  ·  {self.backend.label}",
                        "ok" if result.total else "info")
        if not req.append:
            self.preview.show_empty()

    # ------------------------------------------------------------------ presets
    def _fill_preset_menu(self):
        m = self.preset_menu
        m.delete(0, tk.END)
        for name, data in BUILTIN_PRESETS.items():
            m.add_command(label=name, command=lambda d=data: self.apply_preset(d))
        if self.presets:
            m.add_separator()
            for name, data in sorted(self.presets.items()):
                m.add_command(label="★ " + name, command=lambda d=data: self.apply_preset(d))
        m.add_separator()
        m.add_command(label="Aktuelle Filter speichern…", command=self.save_preset)
        if self.presets:
            dm = tk.Menu(m, tearoff=0)
            for name in sorted(self.presets):
                dm.add_command(label=name, command=lambda n=name: self.delete_preset(n))
            m.add_cascade(label="Gespeicherten Filter löschen", menu=dm)
        m.add_command(label="Alle Filter zurücksetzen", command=lambda: self.apply_preset({
            "type": "Alles", "size": "Egal", "date": "Egal", "sort": DEFAULT_SORT,
            "case": False, "whole": False, "regex": False, "path": False,
            "all_drives": True}))

    def current_filters(self) -> dict:
        return {"type": self.v_type.get(), "size": self.v_size.get(),
                "date": self.v_date.get(), "sort": self.v_sort.get(),
                "case": self.v_case.get(), "whole": self.v_whole.get(),
                "regex": self.v_regex.get(), "path": self.v_path.get(),
                "all_drives": self.v_all_drives.get(),
                "drives": [d for d, v in self.drive_vars.items() if v.get()]}

    def apply_preset(self, data: dict):
        for key, var, table in (("type", self.v_type, TYPE_PRESETS),
                                ("size", self.v_size, SIZE_PRESETS),
                                ("date", self.v_date, DATE_PRESETS),
                                ("sort", self.v_sort, SORT_OPTIONS)):
            if data.get(key) in table:
                var.set(data[key])
        for key, var in (("case", self.v_case), ("whole", self.v_whole),
                         ("regex", self.v_regex), ("path", self.v_path)):
            if key in data:
                var.set(bool(data[key]))
        if "all_drives" in data:
            self.v_all_drives.set(bool(data["all_drives"]))
            wanted = set(data.get("drives", []))
            for d, v in self.drive_vars.items():
                v.set(d in wanted)
            self._sync_drive_state()
        if "text" in data:
            self.v_text.set(data["text"])
        self._on_filter_changed(now=True)

    def save_preset(self):
        name = simpledialog.askstring("Filter speichern", "Name für diese Filterkombination:",
                                      parent=self.root)
        if not name or not name.strip():
            return
        data = self.current_filters()
        if self.v_text.get().strip() and messagebox.askyesno(
                "Filter speichern", "Den aktuellen Suchbegriff mitspeichern?", parent=self.root):
            data["text"] = self.v_text.get()
        self.presets[name.strip()] = data
        self.save_config()
        self.set_status(f"Filter „{name.strip()}“ gespeichert.", "ok")

    def delete_preset(self, name):
        self.presets.pop(name, None)
        self.save_config()

    # ------------------------------------------------------------------ sorting
    def sort_by_column(self, column):
        asc, desc = COLUMN_SORTS[column]
        self.v_sort.set(desc if self.v_sort.get() == asc else asc)
        self._on_filter_changed(now=True)

    def _update_sort_headings(self):
        current = self.v_sort.get()
        for key, title in (("name", "Name"), *((c[0], c[1]) for c in COLUMNS)):
            asc, desc = COLUMN_SORTS[key]
            arrow = " ▲" if current == asc else " ▼" if current == desc else ""
            self.tree.heading("#0" if key == "name" else key, text=title + arrow)

    # ------------------------------------------------------------------ result actions
    def selected_rows(self) -> list[Row]:
        out = []
        for iid in self.tree.selection():
            try:
                out.append(self._rows[int(iid)])
            except (ValueError, IndexError):
                pass
        return out

    def _remember_search(self):
        text = self.v_text.get().strip()
        if text:
            self.history = cfgmod.push_history(self.history, text)
            self.search_entry.configure(values=self.history)

    def _on_double_click(self, event):
        if self.tree.identify_region(event.x, event.y) in ("tree", "cell"):
            self.open_selected()

    def open_selected(self):
        rows = self.selected_rows()
        if not rows:
            return
        if len(rows) > CONFIRM_OPEN_MANY and not messagebox.askyesno(
                "ALLES", f"{len(rows)} Elemente öffnen?", parent=self.root):
            return
        self._remember_search()
        for row in rows:
            self.shell_action(shell.open_path, row.path)

    def _single(self, fn):
        rows = self.selected_rows()
        if rows:
            self._remember_search()
            self.shell_action(fn, rows[0].path)

    def reveal_selected(self):
        self._single(shell.reveal_in_explorer)

    def properties_selected(self):
        self._single(shell.show_properties)

    def terminal_here(self):
        rows = self.selected_rows()
        if rows:
            r = rows[0]
            self.shell_action(shell.open_terminal, r.path if r.is_dir else r.folder)

    def recycle_selected(self):
        rows = self.selected_rows()
        if not rows:
            return
        what = f"„{rows[0].name}“" if len(rows) == 1 else f"{len(rows)} Elemente"
        if not messagebox.askyesno("In den Papierkorb",
                                   f"{what} in den Papierkorb verschieben?", parent=self.root):
            return
        ok = shell.recycle([r.path for r in rows], self.frame_hwnd())
        for iid in self.tree.selection():
            if not os.path.exists(self._rows[int(iid)].path):
                self.tree.delete(iid)
        self.set_status(f"{what} in den Papierkorb verschoben." if ok else
                        "Nicht alles konnte verschoben werden.", "ok" if ok else "err")

    # -- copy / move with the native Windows dialog
    def _fill_target_menu(self, menu: tk.Menu, op: str):
        menu.delete(0, tk.END)
        for target in self.cfg.get("recent_targets", [])[:8]:
            menu.add_command(label=target, command=lambda t=target: self.transfer(op, t))
        if self.cfg.get("recent_targets"):
            menu.add_separator()
        menu.add_command(label="Ordner wählen…", command=lambda: self.transfer(op))

    def transfer(self, op: str, folder: str | None = None):
        rows = self.selected_rows()
        if not rows:
            return
        if folder is None:
            recent = self.cfg.get("recent_targets") or []
            folder = filedialog.askdirectory(
                parent=self.root, initialdir=recent[0] if recent else None,
                title="Kopieren nach" if op == "copy" else "Verschieben nach")
            if not folder:
                return
        folder = os.path.normpath(folder)
        self.cfg["recent_targets"] = cfgmod.push_history(self.cfg.get("recent_targets", []),
                                                         folder, limit=8)
        paths, hwnd = [r.path for r in rows], self.frame_hwnd()
        fn = shell.copy_to if op == "copy" else shell.move_to
        verb = "kopiert" if op == "copy" else "verschoben"
        self.set_status(f"{len(paths)} Element(e) werden {verb} …", "info")

        def work():  # the shell shows its own progress/conflict dialogs
            try:
                ok = fn(paths, folder, hwnd)
            except OSError as exc:
                log.warning("transfer failed: %s", exc)
                ok = False
            self.dispatch(self._after_transfer, op, folder, len(paths), ok)

        threading.Thread(target=work, name="transfer", daemon=True).start()

    def _after_transfer(self, op, folder, count, ok):
        if op == "move":
            for iid in list(self.tree.get_children()):
                if not os.path.exists(self._rows[int(iid)].path):
                    self.tree.delete(iid)
        verb = "kopiert" if op == "copy" else "verschoben"
        if ok:
            self.set_status(f"{count} Element(e) nach {folder} {verb}.", "ok")
        else:
            self.set_status(f"Nicht alle Elemente wurden {verb} (abgebrochen oder Fehler).",
                            "warn")

    def shell_action(self, fn, path):
        try:
            fn(path)
        except OSError as exc:
            log.warning("%s(%s) failed: %s", fn.__name__, path, exc)
            messagebox.showerror("Fehler", f"Aktion fehlgeschlagen:\n{path}\n\n{exc}",
                                 parent=self.root)

    def _to_clipboard(self, text):
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            n = text.count("\n") + 1
            self.set_status("1 Eintrag kopiert." if n == 1 else f"{n} Einträge kopiert.", "ok")

    def copy_paths(self):
        self._to_clipboard("\n".join(r.path for r in self.selected_rows()))
        return "break"

    def copy_names(self):
        self._to_clipboard("\n".join(r.name for r in self.selected_rows()))
        return "break"

    def copy_folders(self):
        folders = dict.fromkeys(r.path if r.is_dir else r.folder for r in self.selected_rows())
        self._to_clipboard("\n".join(folders))

    def search_in_folder(self, folder: str | None = None):
        if folder is None:
            rows = self.selected_rows()
            if not rows:
                return
            folder = rows[0].path if rows[0].is_dir else rows[0].folder
        self.v_text.set(f'"{folder.rstrip(os.sep)}\\" ')
        self.focus_search(select=False)

    def _on_select(self):
        if self._preview_timer:
            self.root.after_cancel(self._preview_timer)
        self._preview_timer = self.root.after(120, self._update_preview)
        n = len(self.tree.selection())
        if n > 1:
            self.set_status(f"{n} Elemente ausgewählt", "info")

    def _update_preview(self):
        self._preview_timer = None
        if not self.v_preview.get():
            return
        rows = self.selected_rows()
        if not rows:
            self.preview.show_empty()
        else:
            self.preview.show(rows[0], len(rows))

    def _toggle_preview(self, flip=False):
        if flip:
            self.v_preview.set(not self.v_preview.get())
        panes = self.paned.panes()
        if self.v_preview.get() and str(self.preview) not in panes:
            self.paned.add(self.preview, weight=1)
            self._update_preview()
        elif not self.v_preview.get() and str(self.preview) in panes:
            self.paned.forget(self.preview)
        return "break"

    def export_csv(self):
        if not self._rows:
            messagebox.showinfo("ALLES", "Keine Ergebnisse zum Exportieren.", parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Ergebnisse exportieren", defaultextension=".csv",
            initialfile="alles-ergebnisse.csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["Name", "Ordner", "Größe (Bytes)", "Geändert", "Typ", "Pfad"])
                for r in self._rows:
                    w.writerow([r.name, r.folder, "" if r.size is None else r.size,
                                r.modified.isoformat(timespec="seconds") if r.modified else "",
                                self.type_name(r), r.path])
        except OSError as exc:
            messagebox.showerror("Fehler", str(exc), parent=self.root)
            return
        self.set_status(f"{fmt_count(len(self._rows))} Zeilen exportiert nach {path}", "ok")

    # ------------------------------------------------------------------ keyboard helpers
    def focus_search(self, select=True):
        self.search_entry.focus_set()
        if select:
            self.search_entry.selection_range(0, tk.END)
        else:
            self.search_entry.icursor(tk.END)
        return "break"

    def _on_search_return(self, event=None):
        self._remember_search()
        self.run_search()
        return "break"

    def _on_search_escape(self, event=None):
        if self.v_text.get():
            self.clear_search()
        else:
            self.hide_to_tray()
        return "break"

    def _focus_results(self, event=None):
        children = self.tree.get_children()
        if children:
            self.tree.focus_set()
            if not self.tree.selection():
                self.tree.selection_set(children[0])
            first = self.tree.selection()[0]
            self.tree.focus(first)
            self.tree.see(first)
        return "break"

    def _on_tree_up(self, event=None):
        children = self.tree.get_children()
        if children and self.tree.focus() == children[0]:
            return self.focus_search()
        return None

    def _post_history(self):
        try:
            self.search_entry.tk.call("ttk::combobox::Post", self.search_entry)
        except tk.TclError:
            pass
        return "break"

    def _on_right_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        if item not in self.tree.selection():
            self.tree.selection_set(item)
        self.tree.focus(item)
        self.ctx.tk_popup(event.x_root, event.y_root)

    def clear_search(self):
        self.v_text.set("")
        self.focus_search()

    def clear_history(self):
        self.history = []
        self.search_entry.configure(values=[])
        self.save_config()

    # ------------------------------------------------------------------ status
    def set_status(self, text, kind="info"):
        self.v_status.set(text)
        self.status_dot.itemconfigure("dot", fill=STATUS_COLORS.get(kind, STATUS_COLORS["info"]))

    def _show_status_tip(self, event=None):
        self._hide_status_tip()
        lbl = self.status_label
        text = self.v_status.get()
        if not text or tkfont.nametofont("TkDefaultFont").measure(text) < lbl.winfo_width():
            return
        tip = tk.Toplevel(self.root)
        tip.wm_overrideredirect(True)
        tip.wm_attributes("-topmost", True)
        ttk.Label(tip, text=text, padding=(6, 3), relief=tk.SOLID, wraplength=700).pack()
        tip.update_idletasks()
        tip.wm_geometry(f"+{lbl.winfo_rootx()}+{lbl.winfo_rooty() - tip.winfo_reqheight() - 4}")
        self._status_tip = tip

    def _hide_status_tip(self, event=None):
        if self._status_tip is not None:
            try:
                self._status_tip.destroy()
            except tk.TclError:
                pass
            self._status_tip = None

    # ------------------------------------------------------------------ window / tray
    def _restore_geometry(self):
        geo = self.cfg.get("geometry")
        if isinstance(geo, str) and self._geometry_on_screen(geo):
            self.root.geometry(geo)
        else:
            self.root.geometry(f"{int(1280 * self.scale)}x{int(760 * self.scale)}")
        if self.cfg.get("maximized"):
            self.root.state("zoomed")

    @staticmethod
    def _geometry_on_screen(geo: str) -> bool:
        parsed = parse_geometry(geo)
        if not parsed:
            return False
        try:
            gsm = _user32.GetSystemMetrics
            virtual = (gsm(76), gsm(77), gsm(78), gsm(79))
        except (AttributeError, OSError):
            return True
        return geometry_visible(parsed, virtual)

    def _remember_window(self):
        try:
            state = self.root.state()
            if state == "normal":
                self.cfg["geometry"] = self.root.geometry()
            if state in ("normal", "zoomed"):
                self.cfg["maximized"] = state == "zoomed"
        except tk.TclError:
            pass

    def frame_hwnd(self):
        try:
            return int(self.root.wm_frame(), 16)
        except (tk.TclError, ValueError):
            return None

    def show_window(self):
        self.root.deiconify()
        if self.root.state() == "iconic":
            self.root.state("normal")
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(50, lambda: self.root.attributes("-topmost", False))
        hwnd = self.frame_hwnd()
        if hwnd:
            _user32.SetForegroundWindow(hwnd)
        self.root.focus_force()
        self.focus_search()

    def hide_to_tray(self):
        if self.tray is None or self.tray.hwnd is None:
            self.root.iconify()
            return
        self._remember_window()
        self.save_config()
        self._hide_status_tip()
        self.root.withdraw()

    def toggle_window(self):
        visible = self.root.state() not in ("withdrawn", "iconic")
        hwnd = self.frame_hwnd()
        focused = bool(hwnd) and _user32.GetForegroundWindow() == hwnd
        if visible and focused:
            self.hide_to_tray()
        else:
            self.show_window()

    def on_close_button(self):
        if self.close_to_tray and self.tray is not None and self.tray.hwnd is not None:
            self.hide_to_tray()
        else:
            self.quit()

    def on_remote_message(self, text: str):
        """Arguments forwarded from a second instance (e.g. Explorer context menu)."""
        try:
            args = json.loads(text)
        except ValueError:
            args = {}
        self.handle_args(args if isinstance(args, dict) else {})
        self.show_window()

    def handle_args(self, args: dict):
        folder = normalize_folder_arg(str(args.get("folder") or ""))
        if folder:
            self.search_in_folder(folder)
        elif args.get("search"):
            self.v_text.set(str(args["search"]))

    def on_hotkey_changed(self, combo, is_preferred):
        if combo is None:
            self.set_status("Kein globaler Hotkey frei (alle Kombinationen belegt).", "warn")
        elif self.cfg.get("hotkey_vk") and not is_preferred:
            self.set_status(f"Gewünschter Hotkey belegt – verwende {vk_display(*combo)}.",
                            "warn")
        log.info("hotkey: %s", vk_display(*combo) if combo else None)

    # ------------------------------------------------------------------ settings
    def apply_settings(self, s: dict):
        cfg = self.cfg
        self.max_display = cfgmod.clamp_int(s["max_display"], self.max_display,
                                            cfgmod.MIN_MAX_DISPLAY, cfgmod.MAX_MAX_DISPLAY)
        self.close_to_tray = bool(s["close_to_tray"])
        self.auto_repair = bool(s["auto_repair"])
        self.auto_update = bool(s.get("auto_update", True))
        if s["everything_exe"]:
            cfg["everything_exe"] = s["everything_exe"]
        else:
            cfg.pop("everything_exe", None)
        if cfg.get("show_drive_labels", True) != s["show_drive_labels"]:
            cfg["show_drive_labels"] = s["show_drive_labels"]
            self._rebuild_drives()
        if s["theme"] != cfg.get("theme", theme.THEME_SYSTEM):
            self.v_theme.set(s["theme"])
            self.set_theme(s["theme"])
        index_changed = s["index_roots"] != self.index_roots or s["excludes"] != self.excludes
        self.excludes = s["excludes"]
        self.index_roots = s["index_roots"]
        cfg["index_refresh_minutes"] = cfgmod.clamp_int(s["index_refresh_minutes"], 60, 0,
                                                        10_080)
        if s["hotkey"]:
            cfg["hotkey_mod"], cfg["hotkey_vk"] = s["hotkey"]
            if self.tray:
                self.tray.request_reregister(s["hotkey"])
        backend_changed = s["backend"] != cfg.get("backend", BACKEND_AUTO)
        cfg["backend"] = s["backend"]
        self.save_config()
        had_service = self.index.service is not None
        if backend_changed:
            self._select_backend()
        # a service that was already running keeps its old roots unless told so;
        # a freshly started one already read the new settings
        if index_changed and had_service and self.index.service:
            self.index.service.reconfigure()
        self._on_filter_changed(now=True)
        self.set_status("Einstellungen gespeichert.", "ok")

    def save_config(self):
        self.cfg.update({
            "max_display": self.max_display, "auto_repair": self.auto_repair,
            "close_to_tray": self.close_to_tray, "history": self.history,
            "excludes": self.excludes, "index_roots": self.index_roots,
            "presets": self.presets, "preview": self.v_preview.get(),
            "auto_update": self.auto_update,
            "columns": {"name": self.tree.column("#0", "width"),
                        **{k: self.tree.column(k, "width") for k, *_ in COLUMNS}},
            "filters": self.current_filters(),
        })
        if not cfgmod.save_config(self.cfg):
            log.warning("could not save config")

    def quit(self):
        if self._closing:
            return
        self._remember_window()
        self.save_config()
        self._closing = True
        if self.tray:
            self.tray.stop()
        for backend in (self.everything, self.index):
            try:
                backend.close()
            except Exception:  # noqa: BLE001
                pass
        self.root.destroy()

    # ------------------------------------------------------------------ dialogs
    # ------------------------------------------------------------------ updates
    def _maybe_check_update(self):
        last = float(self.cfg.get("update_checked_at", 0) or 0)
        if self.auto_update and time.time() - last > 24 * 3600:
            self.check_for_update(manual=False)

    def check_for_update(self, manual: bool = False):
        from . import update
        if manual:
            self.set_status("Suche nach Updates…", "info")

        def work():
            try:
                result = update.fetch_latest()
            except update.UpdateError as exc:
                result = exc
            self.dispatch(self._on_update_result, result, manual)

        threading.Thread(target=work, name="update-check", daemon=True).start()

    def _on_update_result(self, result, manual: bool):
        from . import update
        if isinstance(result, Exception):
            log.info("update check failed: %s", result)
            if manual:
                messagebox.showwarning("Updates", f"Update-Prüfung fehlgeschlagen:\n{result}",
                                       parent=self.root)
            return
        self.cfg["update_checked_at"] = time.time()
        self.save_config()
        newer = update.is_newer(result.version)
        skipped = self.cfg.get("update_skip") == result.version
        log.info("update check: latest %s (newer=%s)", result.version, newer)
        if newer and (manual or not skipped):
            self.available_update = result
            self.update_btn.configure(text=f"Update auf {result.version}")
            self.update_btn.pack(side=tk.RIGHT, padx=(6, 0))
            if manual:
                self.open_update_dialog()
        elif manual:
            messagebox.showinfo("Updates", f"ALLES {__version__} ist aktuell.", parent=self.root)
            self.set_status("ALLES ist aktuell.", "ok")

    def open_update_dialog(self):
        if self.available_update is None:
            return
        from .dialogs import UpdateDialog
        UpdateDialog(self, self.available_update)

    def open_settings(self, tab: int = 0):
        from .dialogs import SettingsDialog
        SettingsDialog(self, tab)

    def open_duplicates(self):
        from .dialogs import DuplicatesDialog
        DuplicatesDialog(self)

    def _open_log(self):
        path = os.path.join(cfgmod.CONFIG_DIR, "alles.log")
        if os.path.exists(path):
            self.shell_action(shell.open_path, path)

    def show_shortcuts(self):
        hotkey = (vk_display(*self.tray.hotkey_combo)
                  if self.tray and self.tray.hotkey_combo else "(keiner)")
        messagebox.showinfo("Tastenkürzel", "\n".join([
            f"{hotkey}\tFenster ein-/ausblenden (global)",
            "Strg+F / Strg+L\tSuchfeld fokussieren",
            "↓ / ↑\tZwischen Suchfeld und Ergebnissen wechseln",
            "Alt+↓\tSuchverlauf öffnen",
            "Enter\tÖffnen",
            "Strg+Enter\tIm Explorer anzeigen",
            "Alt+Enter\tEigenschaften",
            "Strg+T\tTerminal im Ordner öffnen",
            "Entf\tIn den Papierkorb",
            "Strg+C\tPfad(e) kopieren",
            "Strg+Umschalt+C\tName(n) kopieren",
            "Strg+A\tAlle Ergebnisse markieren",
            "Strg+P\tVorschau ein/aus",
            "F5\tSuche wiederholen",
            "Strg+S\tAls CSV exportieren",
            "Esc\tSuche leeren / in den Tray",
            "Strg+Q\tBeenden",
        ]), parent=self.root)

    def show_syntax_help(self):
        messagebox.showinfo("Suchsyntax", "\n".join([
            "Leerzeichen\tUND:  rechnung 2024",
            "|\tODER:  jpg | png",
            "!\tNICHT:  !temp",
            "< >\tGruppe:  <jpg | png> urlaub",
            '" "\tGenaue Phrase:  "mein ordner"',
            "* ?\tPlatzhalter:  *.pdf  bericht?.doc",
            "\\\tPfad:  \\projekte\\ angebot",
            "ext:\text:pdf;docx",
            "size:\tsize:>10mb  size:1mb..5mb",
            "dm:\tdm:today  dm:2024  dm:lastweek",
            "parent:\tparent:C:\\Users",
            "regex:\tregex:^IMG_\\d+",
            "",
            "Die Filter oben erzeugen diese Syntax automatisch. Sie funktioniert",
            "mit Everything und mit dem eigenen Index.",
        ]), parent=self.root)

    def show_about(self):
        messagebox.showinfo("Über ALLES", (
            f"ALLES {__version__}\n"
            "Blitzschnelle Dateisuche für Windows – mit Everything oder dem eigenen Index.\n\n"
            f"Suchmodus: {self.backend.label if self.backend else '-'}\n"
            f"Konfiguration: {cfgmod.CONFIG_FILE}\n\n"
            "MIT-Lizenz · github.com/theStxve/alles\n"
            "„Everything“ ist ein Produkt von voidtools. ALLES ist kein offizielles "
            "voidtools-Produkt."), parent=self.root)


# ---------------------------------------------------------------------- entry point
def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="alles", description=WINDOW_TITLE)
    p.add_argument("--tray", action="store_true", help="versteckt im Tray starten")
    p.add_argument("--search", default="", help="mit diesem Suchbegriff starten")
    p.add_argument("--folder", default="", help="in diesem Ordner suchen")
    p.add_argument("--uninstall-cleanup", action="store_true",
                   help="Autostart und Explorer-Menü entfernen (für den Uninstaller)")
    p.add_argument("--wait-pid", type=int, default=0, help=argparse.SUPPRESS)
    p.add_argument("--version", action="version", version=f"ALLES {__version__}")
    return p.parse_args(argv)


def wait_for_process(pid: int, timeout_ms: int = 20_000) -> None:
    """After a self-update the new exe waits until the old process has exited."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if handle:
        k32.WaitForSingleObject(handle, timeout_ms)
        k32.CloseHandle(handle)


_mutex_handle = None  # keep the single-instance mutex alive for the process lifetime


def acquire_single_instance(payload: str | None) -> bool:
    """True if we are the first instance. Otherwise the running one is activated."""
    global _mutex_handle
    from . import tray
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    _mutex_handle = k32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        for _ in range(30):  # the other instance may still be starting up
            if tray.signal_existing_instance(payload):
                break
            time.sleep(0.1)
        return False
    return True


def main(argv=None):
    args = parse_args(argv)
    if args.uninstall_cleanup:
        shell.remove_integrations()
        return 0
    win_style.hide_own_console()
    if args.wait_pid:
        wait_for_process(args.wait_pid)
    from . import update
    update.cleanup_old_versions()
    remote = {k: v for k, v in (("folder", args.folder), ("search", args.search)) if v}
    if not acquire_single_instance(json.dumps(remote) if remote else None):
        return 0
    log_path = setup_logging()
    log.info("ALLES %s starting (log: %s)", __version__, log_path)
    win_style.set_app_user_model_id()
    win_style.enable_dpi_awareness()

    from . import tray as tray_mod

    root = tk.Tk(className="ALLES")
    icon = win_style.app_icon_path()
    if icon:
        try:
            root.iconbitmap(default=icon)
        except tk.TclError:
            pass

    cfg = cfgmod.load_config()
    app = AllesApp(root, cfg, start_hidden=args.tray, initial_text=args.search)
    if args.folder:
        app.handle_args({"folder": args.folder})

    preferred = None
    if "hotkey_mod" in cfg and "hotkey_vk" in cfg:
        try:
            preferred = (int(cfg["hotkey_mod"]), int(cfg["hotkey_vk"]))
        except (TypeError, ValueError):
            preferred = None
    tray = tray_mod.TrayHotkey(app.dispatch, app.toggle_window, app.show_window, app.quit,
                               on_hotkey_changed=app.on_hotkey_changed,
                               preferred_combo=preferred, icon_path=icon,
                               tooltip=f"ALLES {__version__} – Dateisuche",
                               on_message=app.on_remote_message)
    app.tray = tray
    if not tray.start():
        log.warning("tray icon could not be created")
        if args.tray:
            root.deiconify()
    root.protocol("WM_DELETE_WINDOW", app.on_close_button)
    try:
        root.mainloop()
    finally:
        if not app._closing:
            app.quit()
        log.info("ALLES stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
