"""
ALLES - a friendlier GUI front-end for "Everything" (voidtools).

It queries the live Everything instance through the official SDK, so results are
100 % real Everything search - with a clearer interface and filters that build
the correct search syntax for you.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
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
from tkinter import filedialog, messagebox, ttk

from . import __version__, shell, win_style
from . import config as cfgmod
from . import everything_sdk as es
from .locate import find_everything_exe
from .query import (
    COLUMN_SORTS,
    DATE_PRESETS,
    DEFAULT_SORT,
    SIZE_PRESETS,
    SORT_OPTIONS,
    TYPE_PRESETS,
    Query,
    SearchOptions,
    build_query,
)
from .util import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    MODIFIER_VKS,
    fmt_count,
    fmt_date,
    fmt_size,
    geometry_visible,
    is_valid_hotkey,
    parse_geometry,
    vk_display,
)

APP_TITLE = "ALLES - Everything Front-End"
MUTEX_NAME = "Local\\ALLES_SingleInstance"
log = logging.getLogger("alles")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetForegroundWindow.restype = ctypes.c_void_p
_user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short

STATUS_COLORS = {"ok": "#2e9d5b", "warn": "#d08a1e", "err": "#d64545", "info": "#8a8a8a"}
COLUMNS = (("name", "Name", 280, tk.W), ("folder", "Ordner", 420, tk.W),
           ("size", "Größe", 95, tk.E), ("modified", "Geändert", 135, tk.W),
           ("type", "Typ", 70, tk.W))
REQUEST_FLAGS = (es.REQUEST_FULL_PATH_AND_FILE_NAME | es.REQUEST_SIZE |
                 es.REQUEST_DATE_MODIFIED | es.REQUEST_EXTENSION | es.REQUEST_ATTRIBUTES)
WATCHDOG_INTERVAL = 5.0
AUTOSTART_COOLDOWN = 60.0
CONFIRM_OPEN_MANY = 10


@dataclass(frozen=True)
class Row:
    path: str
    name: str
    folder: str
    size: int | None
    modified: object  # datetime | None
    ext: str
    is_dir: bool

    def display(self):
        kind = "Ordner" if self.is_dir else self.ext.lower()
        size = "" if self.is_dir else fmt_size(self.size)
        return (self.name, self.folder, size, fmt_date(self.modified), kind)


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
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return path


class AllesApp:
    def __init__(self, root: tk.Tk, cfg: dict, start_hidden: bool = False,
                 initial_text: str = ""):
        self.root = root
        self.cfg = cfg
        self.sdk: es.EverythingSDK | None = None
        self.sdk_error: str | None = None
        self.tray = None
        self._sdk_lock = threading.Lock()
        self._ui_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._closing = False
        self._search_timer = None
        self._gen = 0
        self._req_cond = threading.Condition()
        self._pending: SearchRequest | None = None
        self._rows: list[Row] = []
        self._total = 0
        self._last_query: Query | None = None
        self._last_start_attempt = 0.0
        self._conn_state = None
        self._status_tip = None
        self._suspend_trace = False

        self.max_display = cfgmod.clamp_int(cfg.get("max_display"), cfgmod.DEFAULT_MAX_DISPLAY,
                                            cfgmod.MIN_MAX_DISPLAY, cfgmod.MAX_MAX_DISPLAY)
        self.auto_repair = bool(cfg.get("auto_repair", True))
        self.close_to_tray = bool(cfg.get("close_to_tray", True))
        self.history: list[str] = [h for h in cfg.get("history", []) if isinstance(h, str)]

        f = cfg.get("filters", {}) if isinstance(cfg.get("filters"), dict) else {}

        def pick(key, table, default):
            v = f.get(key)
            return v if v in table else default

        self.v_text = tk.StringVar(value=initial_text)
        self.v_all_drives = tk.BooleanVar(value=bool(f.get("all_drives", True)))
        self.v_type = tk.StringVar(value=pick("type", TYPE_PRESETS, "Alles"))
        self.v_size = tk.StringVar(value=pick("size", SIZE_PRESETS, "Egal"))
        self.v_date = tk.StringVar(value=pick("date", DATE_PRESETS, "Egal"))
        self.v_sort = tk.StringVar(value=pick("sort", SORT_OPTIONS, DEFAULT_SORT))
        self.v_case = tk.BooleanVar(value=bool(f.get("case", False)))
        self.v_whole = tk.BooleanVar(value=bool(f.get("whole", False)))
        self.v_regex = tk.BooleanVar(value=bool(f.get("regex", False)))
        self.v_path = tk.BooleanVar(value=bool(f.get("path", False)))
        self.v_syntax = tk.StringVar()
        self.v_status = tk.StringVar(value="Initialisiere...")
        self._saved_drives = set(f.get("drives", []) or [])
        self.drive_vars: dict[str, tk.BooleanVar] = {}

        root.title(APP_TITLE)
        root.minsize(760, 420)
        self._restore_geometry()
        self._setup_style()
        self._build_menu()
        self._build_ui()
        self._bind_keys()
        self._update_syntax()

        self.v_text.trace_add("write", lambda *_: self._on_filter_changed())
        root.report_callback_exception = self._report_exception

        threading.Thread(target=self._search_worker, name="search", daemon=True).start()
        self._pump()
        self._init_sdk()
        threading.Thread(target=self._watchdog_loop, name="watchdog", daemon=True).start()
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

    # ------------------------------------------------------------------ style/UI
    def _setup_style(self):
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family="Segoe UI", size=10)
            except tk.TclError:
                pass
        base = tkfont.nametofont("TkDefaultFont")
        self.font_bold = base.copy()
        self.font_bold.configure(weight="bold")
        self.font_search = base.copy()
        self.font_search.configure(size=12)
        line = base.metrics("linespace")
        style.configure("Treeview", rowheight=int(line * 1.45))
        style.configure("Hint.TLabel", foreground="#6b6b6b")
        self.scale = self.root.winfo_fpixels("1i") / 96.0

    def _build_menu(self):
        m = tk.Menu(self.root)
        self.root.configure(menu=m)

        file_m = tk.Menu(m, tearoff=0)
        file_m.add_command(label="Ergebnisse als CSV exportieren...", accelerator="Strg+S",
                           command=self.export_csv)
        file_m.add_separator()
        file_m.add_command(label="In den Tray minimieren", accelerator="Esc",
                           command=self.hide_to_tray)
        file_m.add_command(label="Beenden", accelerator="Strg+Q", command=self.quit)
        m.add_cascade(label="Datei", menu=file_m)

        ev_m = tk.Menu(m, tearoff=0)
        ev_m.add_command(label="Everything starten", command=self.start_everything)
        ev_m.add_command(label="Aktuelle Suche in Everything öffnen",
                         command=self.open_in_everything)
        ev_m.add_command(label="Diagnose (indizierte Laufwerke)", command=self.run_diagnose)
        ev_m.add_separator()
        ev_m.add_command(label="Laufwerksliste aktualisieren", command=self._rebuild_drives)
        m.add_cascade(label="Everything", menu=ev_m)

        ex_m = tk.Menu(m, tearoff=0)
        ex_m.add_command(label="Einstellungen...", accelerator="Strg+,",
                         command=self.open_settings)
        ex_m.add_command(label="Suchverlauf löschen", command=self.clear_history)
        ex_m.add_command(label="Log-Datei öffnen", command=self._open_log)
        m.add_cascade(label="Extras", menu=ex_m)

        help_m = tk.Menu(m, tearoff=0)
        help_m.add_command(label="Tastenkürzel", accelerator="F1", command=self.show_shortcuts)
        help_m.add_command(label="Everything-Suchsyntax", command=self.show_syntax_help)
        help_m.add_separator()
        help_m.add_command(label="Über ALLES", command=self.show_about)
        m.add_cascade(label="Hilfe", menu=help_m)

    def _build_ui(self):
        root = self.root

        # --- search row
        top = ttk.Frame(root, padding=(10, 10, 10, 4))
        top.pack(fill=tk.X)
        ttk.Label(top, text="Suche:", font=self.font_bold).pack(side=tk.LEFT)
        self.search_entry = ttk.Combobox(top, textvariable=self.v_text, values=self.history,
                                         font=self.font_search)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.search_entry.bind("<<ComboboxSelected>>", lambda e: self.run_search())
        ttk.Button(top, text="Leeren", command=self.clear_search).pack(side=tk.LEFT)
        self.start_btn = ttk.Button(top, text="Everything starten",
                                    command=self.start_everything)

        # --- filter row
        fbar = ttk.Frame(root, padding=(10, 2, 10, 2))
        fbar.pack(fill=tk.X)
        for label, var, table, width in (("Typ:", self.v_type, TYPE_PRESETS, 12),
                                         ("Größe:", self.v_size, SIZE_PRESETS, 11),
                                         ("Geändert:", self.v_date, DATE_PRESETS, 12),
                                         ("Sortierung:", self.v_sort, SORT_OPTIONS, 16)):
            ttk.Label(fbar, text=label).pack(side=tk.LEFT)
            cb = ttk.Combobox(fbar, textvariable=var, values=list(table), state="readonly",
                              width=width)
            cb.pack(side=tk.LEFT, padx=(3, 10))
            cb.bind("<<ComboboxSelected>>", lambda e: self._on_filter_changed(now=True))
        obar = ttk.Frame(root, padding=(10, 2, 10, 2))
        obar.pack(fill=tk.X)
        ttk.Label(obar, text="Optionen:").pack(side=tk.LEFT, padx=(0, 6))
        for label, var in (("Groß/Klein beachten", self.v_case), ("Ganzes Wort", self.v_whole),
                           ("Regex", self.v_regex), ("Auch im Pfad suchen", self.v_path)):
            ttk.Checkbutton(obar, text=label, variable=var,
                            command=lambda: self._on_filter_changed(now=True)).pack(
                side=tk.LEFT, padx=(0, 8))

        # --- drive scope
        self.drive_frame = ttk.LabelFrame(root, text="Laufwerke (Suchbereich)", padding=(8, 3))
        self.drive_frame.pack(fill=tk.X, padx=10, pady=(4, 2))
        self._rebuild_drives()

        # --- generated syntax
        syn = ttk.Frame(root, padding=(10, 2, 10, 2))
        syn.pack(fill=tk.X)
        ttk.Label(syn, text="Everything-Syntax:", style="Hint.TLabel").pack(side=tk.LEFT)
        syn_entry = ttk.Entry(syn, textvariable=self.v_syntax, state="readonly")
        syn_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(syn, text="Kopieren", command=lambda: self._to_clipboard(
            self.v_syntax.get())).pack(side=tk.LEFT)

        # --- status bar (pack before the tree so it is never squeezed out)
        status = ttk.Frame(root, padding=(10, 3, 10, 6))
        status.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_dot = tk.Canvas(status, width=14, height=14, highlightthickness=0,
                                    bg=ttk.Style().lookup("TFrame", "background") or None)
        self.status_dot.create_oval(3, 3, 11, 11, fill=STATUS_COLORS["info"], outline="",
                                    tags="dot")
        self.status_dot.pack(side=tk.LEFT)
        self.status_label = ttk.Label(status, textvariable=self.v_status, anchor=tk.W)
        self.status_label.pack(side=tk.LEFT, padx=(6, 0), fill=tk.X, expand=True)
        self.more_btn = ttk.Button(status, text="Weitere laden",
                                   command=lambda: self.run_search(append=True))
        self.status_label.bind("<Enter>", self._show_status_tip)
        self.status_label.bind("<Leave>", self._hide_status_tip)

        # --- results
        tree_frame = ttk.Frame(root, padding=(10, 4, 10, 0))
        tree_frame.pack(fill=tk.BOTH, expand=True)
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(tree_frame, columns=[c[0] for c in COLUMNS],
                                 show="headings", selectmode="extended")
        widths = self.cfg.get("columns") if isinstance(self.cfg.get("columns"), dict) else {}
        for key, title, width, anchor in COLUMNS:
            self.tree.heading(key, text=title, command=lambda k=key: self.sort_by_column(k))
            w = cfgmod.clamp_int(widths.get(key), int(width * self.scale), 30, 3000)
            self.tree.column(key, width=w, anchor=anchor, stretch=key in ("name", "folder"))
        self.tree.tag_configure("dir", foreground="#1f5fbf")
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self._update_sort_headings()

        self.ctx = tk.Menu(root, tearoff=0)
        self.ctx.add_command(label="Öffnen", accelerator="Enter", command=self.open_selected)
        self.ctx.add_command(label="Im Explorer anzeigen", accelerator="Strg+Enter",
                             command=self.reveal_selected)
        self.ctx.add_command(label="Eigenschaften", accelerator="Alt+Enter",
                             command=self.properties_selected)
        self.ctx.add_separator()
        self.ctx.add_command(label="Pfad kopieren", accelerator="Strg+C",
                             command=self.copy_paths)
        self.ctx.add_command(label="Name kopieren", accelerator="Strg+Umschalt+C",
                             command=self.copy_names)
        self.ctx.add_command(label="Ordnerpfad kopieren", command=self.copy_folders)
        self.ctx.add_separator()
        self.ctx.add_command(label="In diesem Ordner suchen", command=self.search_in_folder)

    def _bind_keys(self):
        r, t, e = self.root, self.tree, self.search_entry
        for seq in ("<Control-f>", "<Control-l>", "<F3>"):
            r.bind_all(seq, lambda ev: self.focus_search())
        r.bind_all("<F5>", lambda ev: self.run_search())
        r.bind_all("<F1>", lambda ev: self.show_shortcuts())
        r.bind_all("<Control-s>", lambda ev: self.export_csv())
        r.bind_all("<Control-q>", lambda ev: self.quit())
        r.bind_all("<Control-comma>", lambda ev: self.open_settings())

        e.bind("<Return>", self._on_search_return)
        e.bind("<Down>", self._focus_results)
        e.bind("<Alt-Down>", lambda ev: self._post_history())
        e.bind("<Escape>", self._on_search_escape)

        t.bind("<Double-1>", lambda ev: self.open_selected())
        t.bind("<Return>", lambda ev: self.open_selected())
        t.bind("<Control-Return>", lambda ev: self.reveal_selected())
        t.bind("<Alt-Return>", lambda ev: (self.properties_selected(), "break")[1])
        t.bind("<Control-c>", lambda ev: self.copy_paths())
        t.bind("<Control-C>", lambda ev: self.copy_names())  # Ctrl+Shift+C
        t.bind("<Control-a>", lambda ev: (t.selection_set(t.get_children()), "break")[1])
        t.bind("<Escape>", lambda ev: self.focus_search())
        t.bind("<Up>", self._on_tree_up)
        t.bind("<Button-3>", self._on_right_click)
        t.bind("<<TreeviewSelect>>", lambda ev: self._update_selection_status())

    # ------------------------------------------------------------------ drives
    def _rebuild_drives(self):
        for w in self.drive_frame.winfo_children():
            w.destroy()
        previous = {d for d, v in self.drive_vars.items() if v.get()} or self._saved_drives
        self.drive_vars = {}
        ttk.Checkbutton(self.drive_frame, text="Alle Laufwerke", variable=self.v_all_drives,
                        command=self._on_all_drives_toggle).pack(side=tk.LEFT, padx=(0, 12))
        self.drive_checks = []
        for d in shell.logical_drives():
            label = shell.drive_label(d)
            text = d.rstrip("\\") + (f" {label}" if label else "")
            v = tk.BooleanVar(value=d in previous)
            self.drive_vars[d] = v
            cb = ttk.Checkbutton(self.drive_frame, text=text, variable=v,
                                 command=self._on_drive_toggle)
            cb.pack(side=tk.LEFT, padx=(0, 8))
            self.drive_checks.append(cb)
        self._sync_drive_state()

    def _sync_drive_state(self):
        # Keep the drive checkboxes usable; "all drives" simply wins when on.
        style = "disabled" if self.v_all_drives.get() else "!disabled"
        for cb in self.drive_checks:
            cb.state([style])

    def _on_all_drives_toggle(self):
        if not self.v_all_drives.get() and not any(v.get() for v in self.drive_vars.values()):
            # nothing selected -> pre-select the system drive so the scope isn't empty
            sysdrive = (os.environ.get("SYSTEMDRIVE", "C:") + "\\").upper()
            if sysdrive in self.drive_vars:
                self.drive_vars[sysdrive].set(True)
        self._sync_drive_state()
        self._on_filter_changed(now=True)

    def _on_drive_toggle(self):
        if any(v.get() for v in self.drive_vars.values()):
            self.v_all_drives.set(False)
        else:
            self.v_all_drives.set(True)
        self._sync_drive_state()
        self._on_filter_changed(now=True)

    # ------------------------------------------------------------------ SDK / connection
    def _init_sdk(self):
        try:
            self.sdk = es.EverythingSDK()
            self.sdk_error = None
        except (OSError, FileNotFoundError) as exc:
            self.sdk = None
            self.sdk_error = str(exc)
            log.error("SDK load failed: %s", exc)
            self.set_status(f"Everything-SDK nicht geladen: {exc}", "err")
            return
        self._check_connection()

    def _probe(self):
        """(alive, db_loaded, version) - safe to call from any thread."""
        if self.sdk is None:
            return (False, False, (0, 0, 0))
        with self._sdk_lock:
            ver = self.sdk.get_version()
            if ver[0] == 0:
                return (False, False, ver)
            return (True, self.sdk.is_db_loaded(), ver)

    def _check_connection(self):
        threading.Thread(target=lambda: self.dispatch(self._apply_connection, self._probe()),
                         daemon=True).start()

    def _apply_connection(self, state):
        alive, db, ver = state
        changed = (alive, db) != (self._conn_state[:2] if self._conn_state else None)
        self._conn_state = state
        if alive:
            self.start_btn.pack_forget()
        elif not self.start_btn.winfo_ismapped() and self.sdk is not None:
            self.start_btn.pack(side=tk.LEFT, padx=(6, 0))
        if not changed:
            return
        if self.sdk is None:
            return
        if not alive:
            self.set_status("Everything läuft nicht (oder nur als Dienst). "
                            "Bitte 'Everything starten' klicken.", "err")
        elif not db:
            self.set_status("Everything läuft, die Datenbank wird noch geladen...", "warn")
        else:
            self.set_status(f"Verbunden mit Everything {ver[0]}.{ver[1]}.{ver[2]}.", "ok")
            self.run_search()

    def _watchdog_loop(self):
        while not self._closing:
            time.sleep(WATCHDOG_INTERVAL)
            if self.sdk is None:
                continue
            try:
                state = self._probe()
            except Exception:  # noqa: BLE001
                log.exception("watchdog probe failed")
                continue
            self.dispatch(self._apply_connection, state)
            if (not state[0] and self.auto_repair
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
            # -startup: start in the background (tray) instead of opening a window
            subprocess.Popen([exe, "-startup"], close_fds=True)
        except OSError as exc:
            log.error("start Everything failed: %s", exc)
            if manual:
                messagebox.showerror("Fehler", f"Konnte Everything nicht starten:\n{exc}",
                                     parent=self.root)
            return
        self.set_status("Everything wird gestartet...", "warn")
        log.info("started %s", exe)
        self.start_btn.state(["disabled"])
        threading.Thread(target=self._wait_for_everything, daemon=True).start()

    def _wait_for_everything(self):
        deadline = time.time() + 30
        state = (False, False, (0, 0, 0))
        while time.time() < deadline and not self._closing:
            time.sleep(0.75)
            state = self._probe()
            if state[0] and state[1]:
                break
        self.dispatch(self._after_start_wait, state)

    def _after_start_wait(self, state):
        self.start_btn.state(["!disabled"])
        self._conn_state = None  # force a status refresh
        self._apply_connection(state)
        if not state[0]:
            self.set_status("Everything antwortet nicht (Zeitüberschreitung). Läuft evtl. nur "
                            "der Dienst - die Everything-Oberfläche einmal manuell starten.",
                            "err")

    def open_in_everything(self):
        exe = self.everything_exe()
        if not exe:
            messagebox.showinfo("ALLES", "Everything.exe wurde nicht gefunden. Pfad unter "
                                "Extras > Einstellungen festlegen.", parent=self.root)
            return
        q = build_query(self.options())
        args = [exe, "-search", q.search]
        args.append("-case" if q.match_case else "-nocase")
        args.append("-ww" if q.whole_word else "-noww")
        args.append("-matchpath" if q.match_path else "-nomatchpath")
        try:
            subprocess.Popen(args, close_fds=True)
        except OSError as exc:
            messagebox.showerror("Fehler", str(exc), parent=self.root)

    # ------------------------------------------------------------------ diagnose
    def run_diagnose(self):
        self.set_status("Diagnose läuft...", "info")
        threading.Thread(target=self._diagnose_worker, daemon=True).start()

    def _diagnose_worker(self):
        try:
            text = self._diagnose_text()
        except Exception as exc:  # noqa: BLE001
            log.exception("diagnose failed")
            text = f"Diagnose fehlgeschlagen: {exc}"
        self.dispatch(lambda: messagebox.showinfo("ALLES Diagnose", text, parent=self.root))
        self.dispatch(self._check_connection)

    def _diagnose_text(self) -> str:
        lines = [f"ALLES {__version__}  |  Python {sys.version.split()[0]}"]
        lines.append(f"Everything.exe: {self.everything_exe() or 'nicht gefunden'}")
        if self.sdk is None:
            lines.append(f"SDK: NICHT geladen ({self.sdk_error})")
            return "\n".join(lines)
        lines.append(f"SDK: {self.sdk.dll_path}")
        alive, db, ver = self._probe()
        if not alive:
            lines += ["", "Everything antwortet nicht (läuft evtl. nur der Dienst).",
                      "'Everything starten' klicken und erneut testen."]
            return "\n".join(lines)
        lines.append(f"Everything {ver[0]}.{ver[1]}.{ver[2]}, Datenbank "
                     f"{'geladen' if db else 'lädt noch'}")
        indexed, missing = [], []
        for d in shell.logical_drives():
            with self._sdk_lock:
                self.sdk.reset()
                self.sdk.set_search(f'parent:"{d}"')
                self.sdk.set_max(1)
                try:
                    n = self.sdk.query(wait=True)
                except es.EverythingError:
                    n = 0
            (indexed if n > 0 else missing).append(d.rstrip("\\"))
        lines += ["", "Indiziert: " + (", ".join(indexed) or "-")]
        if missing:
            lines += ["NICHT im Index: " + ", ".join(missing), "",
                      "Tipp: FAT/exFAT- und Netzlaufwerke brauchen in Everything unter",
                      "Extras > Optionen > Indizes > Ordner einen Ordner-Index."]
        return "\n".join(lines)

    # ------------------------------------------------------------------ search
    def options(self) -> SearchOptions:
        return SearchOptions(
            text=self.v_text.get(),
            all_drives=self.v_all_drives.get(),
            drives=[d for d, v in self.drive_vars.items() if v.get()],
            type=self.v_type.get(), size=self.v_size.get(), date=self.v_date.get(),
            sort=self.v_sort.get(), match_case=self.v_case.get(),
            whole_word=self.v_whole.get(), regex=self.v_regex.get(),
            match_path=self.v_path.get())

    def _on_filter_changed(self, now=False):
        if self._suspend_trace:
            return
        self._update_sort_headings()
        self._update_syntax()
        if self._search_timer:
            self.root.after_cancel(self._search_timer)
        self._search_timer = self.root.after(0 if now else 180, self.run_search)

    def _update_syntax(self):
        self.v_syntax.set(build_query(self.options()).search or "(alles)")

    def run_search(self, append=False):
        self._search_timer = None
        q = self._last_query if append and self._last_query else build_query(self.options())
        self.v_syntax.set(q.search or "(alles)")
        if self.sdk is None:
            return
        if self._conn_state and not self._conn_state[0]:
            return  # not connected - the status bar already explains why
        self._gen += 1
        offset = len(self._rows) if append else 0
        req = SearchRequest(self._gen, q, offset, self.max_display, append)
        with self._req_cond:
            self._pending = req
            self._req_cond.notify()
        if not append:
            self._last_query = q

    def _search_worker(self):
        while True:
            with self._req_cond:
                while self._pending is None:
                    self._req_cond.wait()
                req, self._pending = self._pending, None
            try:
                result = self._execute(req)
            except es.EverythingError as exc:
                result = exc
            except Exception as exc:  # noqa: BLE001
                log.exception("search failed")
                result = exc
            if result is not None:
                self.dispatch(self._on_search_done, req, result)

    def _execute(self, req: SearchRequest):
        q = req.query
        with self._sdk_lock:
            if req.gen != self._gen or self.sdk is None:
                return None  # superseded while waiting for the lock
            s = self.sdk
            s.reset()
            s.set_search(q.search)
            s.set_match_case(q.match_case)
            s.set_match_whole_word(q.whole_word)
            s.set_match_path(q.match_path)
            s.set_sort(q.sort)
            s.set_request_flags(REQUEST_FLAGS)
            s.set_max(req.limit)
            s.set_offset(req.offset)
            t0 = time.perf_counter()
            num = s.query(wait=True)
            total = s.get_total_results()
            rows = []
            for i in range(num):
                if i % 256 == 0 and req.gen != self._gen:
                    return None  # user typed on - drop stale results early
                path = s.get_result_full_path(i)
                if not path:
                    continue
                folder, name = os.path.split(path)
                rows.append(Row(path, name or path, folder, s.get_result_size(i),
                                s.get_result_date_modified(i), s.get_result_extension(i),
                                s.is_result_folder(i)))
            elapsed = (time.perf_counter() - t0) * 1000
        return rows, total, elapsed

    def _on_search_done(self, req: SearchRequest, result):
        if req.gen != self._gen:
            return
        if isinstance(result, Exception):
            kind = "Everything-Fehler" if isinstance(result, es.EverythingError) else "Fehler"
            self.set_status(f"{kind}: {result}", "err")
            if isinstance(result, es.EverythingError):
                self._check_connection()
            return
        rows, total, elapsed = result
        if not req.append:
            self.tree.delete(*self.tree.get_children())
            self._rows = []
            self.tree.yview_moveto(0)
        start = len(self._rows)
        for i, row in enumerate(rows, start):
            self.tree.insert("", tk.END, iid=str(i), values=row.display(),
                             tags=("dir",) if row.is_dir else ())
        self._rows.extend(rows)
        self._total = total
        shown = len(self._rows)
        more = total > shown
        if more:
            self.more_btn.pack(side=tk.RIGHT)
        else:
            self.more_btn.pack_forget()
        text = f"{fmt_count(total)} Treffer"
        if more:
            text += f" ({fmt_count(shown)} angezeigt)"
        self.set_status(f"{text}  ·  {elapsed:.0f} ms", "ok" if total else "info")

    # ------------------------------------------------------------------ sorting
    def sort_by_column(self, column):
        asc, desc = COLUMN_SORTS[column]
        self.v_sort.set(desc if self.v_sort.get() == asc else asc)
        self._on_filter_changed(now=True)

    def _update_sort_headings(self):
        current = self.v_sort.get()
        for key, title, *_ in COLUMNS:
            asc, desc = COLUMN_SORTS[key]
            arrow = " ▲" if current == asc else " ▼" if current == desc else ""
            self.tree.heading(key, text=title + arrow)

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

    def open_selected(self):
        rows = self.selected_rows()
        if not rows:
            return
        if len(rows) > CONFIRM_OPEN_MANY and not messagebox.askyesno(
                "ALLES", f"{len(rows)} Elemente öffnen?", parent=self.root):
            return
        self._remember_search()
        for row in rows:
            self._shell_action(shell.open_path, row.path)

    def reveal_selected(self):
        rows = self.selected_rows()
        if rows:
            self._remember_search()
            self._shell_action(shell.reveal_in_explorer, rows[0].path)

    def properties_selected(self):
        rows = self.selected_rows()
        if rows:
            self._shell_action(shell.show_properties, rows[0].path)

    def _shell_action(self, fn, path):
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
            self.set_status(f"{n} Eintrag kopiert." if n == 1 else f"{n} Einträge kopiert.",
                            "ok")

    def copy_paths(self):
        self._to_clipboard("\n".join(r.path for r in self.selected_rows()))
        return "break"

    def copy_names(self):
        self._to_clipboard("\n".join(r.name for r in self.selected_rows()))
        return "break"

    def copy_folders(self):
        folders = dict.fromkeys(r.path if r.is_dir else r.folder for r in self.selected_rows())
        self._to_clipboard("\n".join(folders))

    def search_in_folder(self):
        rows = self.selected_rows()
        if not rows:
            return
        folder = rows[0].path if rows[0].is_dir else rows[0].folder
        self.v_text.set(f'"{folder.rstrip(os.sep)}\\" ')
        self.focus_search(select=False)

    def _update_selection_status(self):
        n = len(self.tree.selection())
        if n > 1:
            self.set_status(f"{n} Elemente ausgewählt", "info")

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
                                "Ordner" if r.is_dir else r.ext, r.path])
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
            self.tree.focus(self.tree.selection()[0])
            self.tree.see(self.tree.selection()[0])
        return "break"

    def _on_tree_up(self, event=None):
        focus = self.tree.focus()
        children = self.tree.get_children()
        if children and focus == children[0]:
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
            return  # fully visible, no tooltip needed
        tip = tk.Toplevel(self.root)
        tip.wm_overrideredirect(True)
        tip.wm_attributes("-topmost", True)
        ttk.Label(tip, text=text, padding=(6, 3), relief=tk.SOLID, wraplength=700).pack()
        tip.update_idletasks()
        x = lbl.winfo_rootx()
        y = lbl.winfo_rooty() - tip.winfo_reqheight() - 4
        tip.wm_geometry(f"+{x}+{y}")
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
            self.root.geometry(f"{int(1150 * self._dpi())}x{int(720 * self._dpi())}")
        if self.cfg.get("maximized"):
            self.root.state("zoomed")

    def _dpi(self):
        return self.root.winfo_fpixels("1i") / 96.0

    @staticmethod
    def _geometry_on_screen(geo: str) -> bool:
        """Reject saved positions on a monitor that is no longer connected."""
        parsed = parse_geometry(geo)
        if not parsed:
            return False
        try:
            gsm = _user32.GetSystemMetrics
            virtual = (gsm(76), gsm(77), gsm(78), gsm(79))  # SM_[XY]VIRTUALSCREEN, SM_C[XY]...
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

    def _frame_hwnd(self):
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
        hwnd = self._frame_hwnd()
        if hwnd:
            _user32.SetForegroundWindow(hwnd)
        self.root.focus_force()
        self.focus_search()

    def hide_to_tray(self):
        if self.tray is None or self.tray.hwnd is None:
            self.root.iconify()  # no tray icon -> never make the window unreachable
            return
        self._remember_window()
        self.save_config()
        self._hide_status_tip()
        self.root.withdraw()

    def toggle_window(self):
        visible = self.root.state() not in ("withdrawn", "iconic")
        hwnd = self._frame_hwnd()
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

    def on_hotkey_changed(self, combo, is_preferred):
        if combo is None:
            self.set_status("Kein globaler Hotkey frei (alle Kombinationen belegt).", "warn")
        elif self.cfg.get("hotkey_vk") and not is_preferred:
            self.set_status(f"Gewünschter Hotkey belegt - verwende {vk_display(*combo)}.",
                            "warn")
        log.info("hotkey: %s", vk_display(*combo) if combo else None)

    def save_config(self):
        self.cfg.update({
            "max_display": self.max_display,
            "auto_repair": self.auto_repair,
            "close_to_tray": self.close_to_tray,
            "history": self.history,
            "columns": {k: self.tree.column(k, "width") for k, *_ in COLUMNS},
            "filters": {
                "type": self.v_type.get(), "size": self.v_size.get(),
                "date": self.v_date.get(), "sort": self.v_sort.get(),
                "case": self.v_case.get(), "whole": self.v_whole.get(),
                "regex": self.v_regex.get(), "path": self.v_path.get(),
                "all_drives": self.v_all_drives.get(),
                "drives": [d for d, v in self.drive_vars.items() if v.get()],
            },
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
        try:
            with self._sdk_lock:
                if self.sdk:
                    self.sdk.cleanup()
        except Exception:  # noqa: BLE001
            pass
        self.root.destroy()

    # ------------------------------------------------------------------ dialogs
    def open_settings(self):
        SettingsDialog(self)

    def _open_log(self):
        path = os.path.join(cfgmod.CONFIG_DIR, "alles.log")
        if os.path.exists(path):
            self._shell_action(shell.open_path, path)

    def show_shortcuts(self):
        hotkey = vk_display(*self.tray.hotkey_combo) if self.tray and \
            self.tray.hotkey_combo else "(keiner)"
        messagebox.showinfo("Tastenkürzel", "\n".join([
            f"{hotkey}\tFenster ein-/ausblenden (global)",
            "Strg+F / Strg+L\tSuchfeld fokussieren",
            "↓ / ↑\tZwischen Suchfeld und Ergebnissen wechseln",
            "Alt+↓\tSuchverlauf öffnen",
            "Enter\tÖffnen",
            "Strg+Enter\tIm Explorer anzeigen",
            "Alt+Enter\tEigenschaften",
            "Strg+C\tPfad(e) kopieren",
            "Strg+Umschalt+C\tName(n) kopieren",
            "Strg+A\tAlle Ergebnisse markieren",
            "F5\tSuche wiederholen",
            "Strg+S\tAls CSV exportieren",
            "Esc\tSuche leeren / in den Tray",
            "Strg+Q\tBeenden",
        ]), parent=self.root)

    def show_syntax_help(self):
        messagebox.showinfo("Everything-Suchsyntax", "\n".join([
            "Leerzeichen\tUND:  rechnung 2024",
            "|\tODER:  jpg | png",
            "!\tNICHT:  !temp",
            "< >\tGruppe:  <jpg | png> urlaub",
            '" "\tGenaue Phrase:  "mein ordner"',
            "* ?\tPlatzhalter:  *.pdf  bericht?.doc",
            "ext:\text:pdf;docx",
            "size:\tsize:>10mb",
            "dm:\tdm:today  dm:2024",
            "parent:\tparent:C:\\Users",
            "regex:\tregex:^IMG_\\d+",
            "",
            "Die Filter oben erzeugen diese Syntax automatisch.",
        ]), parent=self.root)

    def show_about(self):
        ver = self._conn_state[2] if self._conn_state and self._conn_state[0] else None
        messagebox.showinfo("Über ALLES", (
            f"ALLES {__version__}\n"
            "Ein freundliches Front-End für Everything von voidtools.\n\n"
            f"Everything: {'.'.join(map(str, ver)) if ver else 'nicht verbunden'}\n"
            f"Konfiguration: {cfgmod.CONFIG_FILE}\n\n"
            "ALLES ist kein offizielles voidtools-Produkt."), parent=self.root)


class SettingsDialog(tk.Toplevel):
    def __init__(self, app: AllesApp):
        super().__init__(app.root)
        self.app = app
        self.title("ALLES Einstellungen")
        self.resizable(False, False)
        self.transient(app.root)
        self.new_combo = None
        self._capturing = False
        icon = win_style.app_icon_path()
        if icon:
            try:
                self.iconbitmap(icon)
            except tk.TclError:
                pass

        frm = ttk.Frame(self, padding=14)
        frm.pack(fill=tk.BOTH, expand=True)
        frm.columnconfigure(0, weight=1)
        row = 0

        ttk.Label(frm, text="Globaler Hotkey (Fenster ein-/ausblenden):").grid(
            row=row, column=0, columnspan=2, sticky=tk.W)
        row += 1
        self.hotkey_var = tk.StringVar(value=self._combo_text())
        self.hk_entry = ttk.Entry(frm, textvariable=self.hotkey_var, width=30, state="readonly")
        self.hk_entry.grid(row=row, column=0, sticky=tk.EW, pady=(2, 10))
        self.hk_entry.bind("<KeyPress>", self._on_key)
        self.capture_btn = ttk.Button(frm, text="Aufzeichnen...", command=self._toggle_capture)
        self.capture_btn.grid(row=row, column=1, padx=(6, 0), pady=(2, 10))
        row += 1

        ttk.Label(frm, text="Treffer pro Seite:").grid(row=row, column=0, sticky=tk.W)
        row += 1
        self.max_var = tk.StringVar(value=str(app.max_display))
        ttk.Spinbox(frm, from_=cfgmod.MIN_MAX_DISPLAY, to=50_000, increment=500,
                    textvariable=self.max_var, width=10).grid(
            row=row, column=0, sticky=tk.W, pady=(2, 10))
        row += 1

        ttk.Label(frm, text="Everything.exe (leer = automatisch suchen):").grid(
            row=row, column=0, columnspan=2, sticky=tk.W)
        row += 1
        self.exe_var = tk.StringVar(value=app.cfg.get("everything_exe", ""))
        ttk.Entry(frm, textvariable=self.exe_var, width=46).grid(
            row=row, column=0, sticky=tk.EW, pady=(2, 10))
        ttk.Button(frm, text="Durchsuchen...", command=self._browse_exe).grid(
            row=row, column=1, padx=(6, 0), pady=(2, 10))
        row += 1

        self.auto_var = tk.BooleanVar(value=app.auto_repair)
        self.tray_var = tk.BooleanVar(value=app.close_to_tray)
        self.autostart_var = tk.BooleanVar(value=shell.get_autostart())
        for text, var in (("Everything bei Bedarf automatisch starten", self.auto_var),
                          ("Schließen-Knopf minimiert in den Tray", self.tray_var),
                          ("ALLES mit Windows starten (im Tray)", self.autostart_var)):
            ttk.Checkbutton(frm, text=text, variable=var).grid(
                row=row, column=0, columnspan=2, sticky=tk.W, pady=1)
            row += 1

        btns = ttk.Frame(frm)
        btns.grid(row=row, column=0, columnspan=2, sticky=tk.E, pady=(14, 0))
        ttk.Button(btns, text="Speichern", command=self._save).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side=tk.LEFT)
        self.bind("<Escape>", lambda e: self._escape())
        self.bind("<Return>", lambda e: None if self._capturing else self._save())

        self.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - self.winfo_reqwidth()) // 2
        y = app.root.winfo_rooty() + 80
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.focus_set()

    def _combo_text(self):
        combo = self.app.tray.hotkey_combo if self.app.tray else None
        return vk_display(*combo) if combo else "(keiner)"

    def _escape(self):
        if self._capturing:
            self._toggle_capture()
        else:
            self.destroy()

    def _toggle_capture(self):
        self._capturing = not self._capturing
        if self._capturing:
            self.hotkey_var.set("Tastenkombination drücken (z.B. Strg+Alt+Leertaste)...")
            self.capture_btn.configure(text="Abbrechen")
            self.hk_entry.focus_set()
        else:
            self.hotkey_var.set(vk_display(*self.new_combo) if self.new_combo
                                else self._combo_text())
            self.capture_btn.configure(text="Aufzeichnen...")

    def _on_key(self, event):
        if not self._capturing:
            return None
        vk = int(event.keycode)
        if vk in MODIFIER_VKS:
            return "break"
        if vk == 0x1B:  # Esc cancels
            self._toggle_capture()
            return "break"
        gks = _user32.GetAsyncKeyState
        down = lambda k: bool(gks(k) & 0x8000)  # noqa: E731
        mods = 0
        if down(0x11):
            mods |= MOD_CONTROL
        if down(0x12):
            mods |= MOD_ALT
        if down(0x10):
            mods |= MOD_SHIFT
        if down(0x5B) or down(0x5C):
            mods |= MOD_WIN
        if not is_valid_hotkey(mods, vk):
            self.hotkey_var.set("Bitte mit Strg, Alt oder Win kombinieren...")
            return "break"
        self.new_combo = (mods, vk)
        self._capturing = False
        self.hotkey_var.set(vk_display(*self.new_combo))
        self.capture_btn.configure(text="Aufzeichnen...")
        return "break"

    def _browse_exe(self):
        path = filedialog.askopenfilename(parent=self, title="Everything.exe auswählen",
                                          filetypes=[("Everything", "Everything*.exe"),
                                                     ("Programme", "*.exe")])
        if path:
            self.exe_var.set(os.path.normpath(path))

    def _save(self):
        app = self.app
        exe = self.exe_var.get().strip()
        if exe and not os.path.isfile(exe):
            messagebox.showerror("ALLES", f"Datei nicht gefunden:\n{exe}", parent=self)
            return
        app.max_display = cfgmod.clamp_int(self.max_var.get(), app.max_display,
                                           cfgmod.MIN_MAX_DISPLAY, cfgmod.MAX_MAX_DISPLAY)
        app.auto_repair = bool(self.auto_var.get())
        app.close_to_tray = bool(self.tray_var.get())
        if exe:
            app.cfg["everything_exe"] = exe
        else:
            app.cfg.pop("everything_exe", None)
        if self.new_combo:
            app.cfg["hotkey_mod"], app.cfg["hotkey_vk"] = self.new_combo
            if app.tray:
                app.tray.request_reregister(self.new_combo)
        if (self.autostart_var.get() != shell.get_autostart()
                and not shell.set_autostart(self.autostart_var.get())):
            messagebox.showwarning("ALLES", "Autostart konnte nicht geändert werden.",
                                   parent=self)
        app.save_config()
        app.set_status("Einstellungen gespeichert.", "ok")
        self.destroy()


# ---------------------------------------------------------------------- entry point
def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="alles", description=APP_TITLE)
    p.add_argument("--tray", action="store_true", help="versteckt im Tray starten")
    p.add_argument("--search", default="", help="mit diesem Suchbegriff starten")
    p.add_argument("--version", action="version", version=f"ALLES {__version__}")
    return p.parse_args(argv)


_mutex_handle = None  # keep the single-instance mutex alive for the process lifetime


def acquire_single_instance() -> bool:
    """True if we are the first instance. Otherwise the running one is activated."""
    global _mutex_handle
    from . import tray
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    _mutex_handle = k32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        for _ in range(20):  # the other instance may still be starting up
            if tray.signal_existing_instance():
                break
            time.sleep(0.1)
        return False
    return True


def main(argv=None):
    args = parse_args(argv)
    win_style.hide_own_console()
    if not acquire_single_instance():
        return 0
    log_path = setup_logging()
    log.info("ALLES %s starting (log: %s)", __version__, log_path)
    win_style.set_app_user_model_id()
    win_style.enable_dpi_awareness()

    from . import tray as tray_mod

    root = tk.Tk()
    icon = win_style.app_icon_path()
    if icon:
        try:
            root.iconbitmap(default=icon)
        except tk.TclError:
            pass

    cfg = cfgmod.load_config()
    app = AllesApp(root, cfg, start_hidden=args.tray, initial_text=args.search)

    preferred = None
    if "hotkey_mod" in cfg and "hotkey_vk" in cfg:
        try:
            preferred = (int(cfg["hotkey_mod"]), int(cfg["hotkey_vk"]))
        except (TypeError, ValueError):
            preferred = None
    tray = tray_mod.TrayHotkey(app.dispatch, app.toggle_window, app.show_window, app.quit,
                               on_hotkey_changed=app.on_hotkey_changed,
                               preferred_combo=preferred, icon_path=icon,
                               tooltip=f"ALLES {__version__} - Everything Front-End")
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
