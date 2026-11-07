"""Settings and duplicate-finder dialogs."""
from __future__ import annotations

import ctypes
import os
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

from . import config as cfgmod
from . import shell, theme
from .backends import BACKEND_LABELS
from .dupes import MODE_CONTENT, MODE_NAME_SIZE, find_duplicates, wasted_bytes
from .theme import THEME_LABELS
from .util import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    MODIFIER_VKS,
    fmt_count,
    fmt_date,
    fmt_size,
    is_valid_hotkey,
    vk_display,
)

if TYPE_CHECKING:
    from .app import AllesApp

_user32 = ctypes.WinDLL("user32")
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short


def _center(win: tk.Toplevel, parent: tk.Misc, top: int = 70):
    win.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - win.winfo_reqwidth()) // 2
    y = parent.winfo_rooty() + top
    win.geometry(f"+{max(0, x)}+{max(0, y)}")


class SettingsDialog(tk.Toplevel):
    def __init__(self, app: AllesApp, tab: int = 0):
        super().__init__(app.root)
        self.app = app
        self.title("ALLES Einstellungen")
        self.transient(app.root)
        self.resizable(False, False)
        theme.style_toplevel(self, app.palette)
        self.new_combo = None
        self._capturing = False
        cfg = app.cfg

        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=12, pady=(12, 0))

        # ---------------------------------------------------------- general
        g = ttk.Frame(nb, padding=14)
        nb.add(g, text="Allgemein")
        g.columnconfigure(0, weight=1)
        ttk.Label(g, text="Globaler Hotkey (Fenster ein-/ausblenden):").grid(
            row=0, column=0, columnspan=2, sticky="w")
        self.hotkey_var = tk.StringVar(value=self._combo_text())
        self.hk_entry = ttk.Entry(g, textvariable=self.hotkey_var, width=34, state="readonly")
        self.hk_entry.grid(row=1, column=0, sticky="ew", pady=(2, 10))
        self.hk_entry.bind("<KeyPress>", self._on_key)
        self.capture_btn = ttk.Button(g, text="Aufzeichnen…", command=self._toggle_capture)
        self.capture_btn.grid(row=1, column=1, padx=(6, 0), pady=(2, 10))

        ttk.Label(g, text="Darstellung:").grid(row=2, column=0, sticky="w")
        self.theme_var = tk.StringVar(value=THEME_LABELS.get(cfg.get("theme", "system")))
        ttk.Combobox(g, textvariable=self.theme_var, values=list(THEME_LABELS.values()),
                     state="readonly", width=20).grid(row=3, column=0, sticky="w", pady=(2, 10))

        ttk.Label(g, text="Treffer pro Seite:").grid(row=4, column=0, sticky="w")
        self.max_var = tk.StringVar(value=str(app.max_display))
        ttk.Spinbox(g, from_=cfgmod.MIN_MAX_DISPLAY, to=50_000, increment=500,
                    textvariable=self.max_var, width=10).grid(row=5, column=0, sticky="w",
                                                              pady=(2, 10))
        self.tray_var = tk.BooleanVar(value=app.close_to_tray)
        self.autostart_var = tk.BooleanVar(value=shell.get_autostart())
        self.explorer_var = tk.BooleanVar(value=shell.get_explorer_integration())
        self.labels_var = tk.BooleanVar(value=cfg.get("show_drive_labels", True))
        self.update_var = tk.BooleanVar(value=app.auto_update)
        for i, (text, var) in enumerate((
                ("Schließen-Knopf minimiert in den Tray", self.tray_var),
                ("ALLES mit Windows starten (im Tray)", self.autostart_var),
                ("„Mit ALLES durchsuchen“ im Explorer-Kontextmenü", self.explorer_var),
                ("Laufwerksnamen anzeigen", self.labels_var),
                ("Automatisch nach Updates suchen (einmal täglich)", self.update_var))):
            ttk.Checkbutton(g, text=text, variable=var).grid(row=6 + i, column=0, columnspan=2,
                                                             sticky="w", pady=1)

        # ---------------------------------------------------------- search
        s = ttk.Frame(nb, padding=14)
        nb.add(s, text="Suche")
        s.columnconfigure(0, weight=1)
        ttk.Label(s, text="Suchmodus:").grid(row=0, column=0, sticky="w")
        self.backend_var = tk.StringVar(value=BACKEND_LABELS[cfg.get("backend", "auto")])
        ttk.Combobox(s, textvariable=self.backend_var, values=list(BACKEND_LABELS.values()),
                     state="readonly", width=44).grid(row=1, column=0, sticky="w", pady=(2, 12))
        ttk.Label(s, text="Ausgeschlossene Ordner (einer pro Zeile):").grid(
            row=2, column=0, sticky="w")
        ttk.Label(s, text="Ordnername (z. B. node_modules) oder vollständiger Pfad. "
                          "Gilt für beide Suchmodi.", style="Hint.TLabel",
                  wraplength=420).grid(row=3, column=0, sticky="w")
        self.excludes = tk.Text(s, width=50, height=8, relief="flat", highlightthickness=1,
                                bg=app.palette["field"], fg=app.palette["fg"],
                                insertbackground=app.palette["fg"],
                                highlightbackground=app.palette["border"])
        self.excludes.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        self.excludes.insert("1.0", "\n".join(app.excludes))

        # ---------------------------------------------------------- everything
        e = ttk.Frame(nb, padding=14)
        nb.add(e, text="Everything")
        e.columnconfigure(0, weight=1)
        ttk.Label(e, text="Everything.exe (leer = automatisch suchen):").grid(
            row=0, column=0, columnspan=2, sticky="w")
        self.exe_var = tk.StringVar(value=cfg.get("everything_exe", ""))
        ttk.Entry(e, textvariable=self.exe_var, width=46).grid(row=1, column=0, sticky="ew",
                                                              pady=(2, 10))
        ttk.Button(e, text="Durchsuchen…", command=self._browse_exe).grid(
            row=1, column=1, padx=(6, 0), pady=(2, 10))
        self.auto_var = tk.BooleanVar(value=app.auto_repair)
        ttk.Checkbutton(e, text="Everything bei Bedarf automatisch im Hintergrund starten",
                        variable=self.auto_var).grid(row=2, column=0, columnspan=2, sticky="w")
        found = app.everything_exe()
        ttk.Label(e, text=f"Gefunden: {found or '–'}", style="Hint.TLabel",
                  wraplength=420).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

        # ---------------------------------------------------------- index
        x = ttk.Frame(nb, padding=14)
        nb.add(x, text="Eigener Index")
        x.columnconfigure(0, weight=1)
        ttk.Label(x, text="Indizierte Laufwerke und Ordner:").grid(row=0, column=0, sticky="w")
        self.roots = tk.Listbox(x, height=6, relief="flat", highlightthickness=1,
                                bg=app.palette["field"], fg=app.palette["fg"],
                                selectbackground=app.palette["select"],
                                highlightbackground=app.palette["border"])
        self.roots.grid(row=1, column=0, rowspan=3, sticky="nsew", pady=(4, 0))
        for r in app.index_roots:
            self.roots.insert(tk.END, r)
        ttk.Button(x, text="Ordner hinzufügen…", command=self._add_root).grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=(4, 2))
        ttk.Button(x, text="Entfernen", command=self._remove_root).grid(
            row=2, column=1, sticky="ew", padx=(8, 0), pady=2)
        ttk.Button(x, text="Alle Festplatten", command=self._default_roots).grid(
            row=3, column=1, sticky="new", padx=(8, 0), pady=2)
        ttk.Label(x, text="Beim Start auffrischen, wenn älter als (Minuten, 0 = nie):").grid(
            row=4, column=0, sticky="w", pady=(12, 0))
        self.refresh_var = tk.StringVar(value=str(cfg.get("index_refresh_minutes", 60)))
        ttk.Spinbox(x, from_=0, to=10_080, increment=30, textvariable=self.refresh_var,
                    width=8).grid(row=5, column=0, sticky="w", pady=(2, 8))
        info = app.index_info_text()
        ttk.Label(x, text=info, style="Hint.TLabel", justify=tk.LEFT,
                  wraplength=420).grid(row=6, column=0, columnspan=2, sticky="w")
        ttk.Button(x, text="Index jetzt neu aufbauen",
                   command=lambda: (app.rebuild_index(), self.destroy())).grid(
            row=7, column=0, sticky="w", pady=(10, 0))

        nb.select(tab)
        btns = ttk.Frame(self, padding=(12, 10, 12, 12))
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Speichern", command=self._save).pack(side=tk.RIGHT, padx=6)
        self.bind("<Escape>", lambda ev: self._escape())
        _center(self, app.root)
        self.grab_set()
        self.focus_set()

    # -- hotkey capture
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
            self.hotkey_var.set("Tastenkombination drücken…")
            self.capture_btn.configure(text="Abbrechen")
            self.hk_entry.focus_set()
        else:
            self.hotkey_var.set(vk_display(*self.new_combo) if self.new_combo
                                else self._combo_text())
            self.capture_btn.configure(text="Aufzeichnen…")

    def _on_key(self, event):
        if not self._capturing:
            return None
        vk = int(event.keycode)
        if vk in MODIFIER_VKS:
            return "break"
        if vk == 0x1B:
            self._toggle_capture()
            return "break"

        def down(k):
            return bool(_user32.GetAsyncKeyState(k) & 0x8000)

        mods = ((MOD_CONTROL if down(0x11) else 0) | (MOD_ALT if down(0x12) else 0)
                | (MOD_SHIFT if down(0x10) else 0)
                | (MOD_WIN if down(0x5B) or down(0x5C) else 0))
        if not is_valid_hotkey(mods, vk):
            self.hotkey_var.set("Bitte mit Strg, Alt oder Win kombinieren…")
            return "break"
        self.new_combo = (mods, vk)
        self._capturing = False
        self.hotkey_var.set(vk_display(*self.new_combo))
        self.capture_btn.configure(text="Aufzeichnen…")
        return "break"

    # -- helpers
    def _browse_exe(self):
        path = filedialog.askopenfilename(parent=self, title="Everything.exe auswählen",
                                          filetypes=[("Everything", "Everything*.exe"),
                                                     ("Programme", "*.exe")])
        if path:
            self.exe_var.set(os.path.normpath(path))

    def _add_root(self):
        path = filedialog.askdirectory(parent=self, title="Ordner für den Index wählen")
        if path:
            path = os.path.normpath(path)
            if path not in self.roots.get(0, tk.END):
                self.roots.insert(tk.END, path)

    def _remove_root(self):
        for i in reversed(self.roots.curselection()):
            self.roots.delete(i)

    def _default_roots(self):
        self.roots.delete(0, tk.END)
        for d in shell.fixed_drives():
            self.roots.insert(tk.END, d)

    def _save(self):
        exe = self.exe_var.get().strip()
        if exe and not os.path.isfile(exe):
            messagebox.showerror("ALLES", f"Datei nicht gefunden:\n{exe}", parent=self)
            return
        roots = list(self.roots.get(0, tk.END))
        if not roots:
            messagebox.showerror("ALLES", "Bitte mindestens einen Ordner für den eigenen "
                                          "Index angeben.", parent=self)
            return
        theme = next(k for k, v in THEME_LABELS.items() if v == self.theme_var.get())
        backend = next(k for k, v in BACKEND_LABELS.items() if v == self.backend_var.get())
        excludes = [ln.strip() for ln in self.excludes.get("1.0", tk.END).splitlines()
                    if ln.strip()]
        for flag, getter, setter in (
                (self.autostart_var.get(), shell.get_autostart, shell.set_autostart),
                (self.explorer_var.get(), shell.get_explorer_integration,
                 lambda on: shell.set_explorer_integration(on, self.app.icon_path))):
            if flag != getter() and not setter(flag):
                messagebox.showwarning("ALLES", "Eine Windows-Integration konnte nicht "
                                                "geändert werden.", parent=self)
        self.app.apply_settings({
            "max_display": self.max_var.get(), "close_to_tray": self.tray_var.get(),
            "show_drive_labels": self.labels_var.get(), "theme": theme, "backend": backend,
            "excludes": excludes, "everything_exe": exe, "auto_repair": self.auto_var.get(),
            "index_roots": roots, "index_refresh_minutes": self.refresh_var.get(),
            "hotkey": self.new_combo, "auto_update": self.update_var.get(),
        })
        self.destroy()


class DuplicatesDialog(tk.Toplevel):
    """Finds duplicates among the current search (all pages, files only)."""

    SCAN_LIMIT = 200_000

    def __init__(self, app: AllesApp):
        super().__init__(app.root)
        self.app = app
        self.title("Duplikate finden")
        self.transient(app.root)
        self.geometry(f"{int(900 * app.scale)}x{int(560 * app.scale)}")
        theme.style_toplevel(self, app.palette)
        self._stop = threading.Event()
        self._rows = {}

        top = ttk.Frame(self, padding=(12, 12, 12, 6))
        top.pack(fill=tk.X)
        ttk.Label(top, text="Durchsucht wird die aktuelle Suche inkl. aller Filter.",
                  style="Hint.TLabel").pack(side=tk.LEFT)
        opts = ttk.Frame(self, padding=(12, 0, 12, 6))
        opts.pack(fill=tk.X)
        self.mode = tk.StringVar(value=MODE_CONTENT)
        ttk.Radiobutton(opts, text="Gleicher Inhalt (sicher, liest die Dateien)",
                        value=MODE_CONTENT, variable=self.mode).pack(side=tk.LEFT)
        ttk.Radiobutton(opts, text="Gleicher Name + Größe (schnell)", value=MODE_NAME_SIZE,
                        variable=self.mode).pack(side=tk.LEFT, padx=12)
        ttk.Label(opts, text="Mindestgröße (MB):").pack(side=tk.LEFT, padx=(12, 4))
        self.min_mb = tk.StringVar(value="1")
        ttk.Spinbox(opts, from_=0, to=100_000, textvariable=self.min_mb, width=7).pack(
            side=tk.LEFT)
        self.start_btn = ttk.Button(opts, text="Suchen", command=self.start)
        self.start_btn.pack(side=tk.RIGHT)

        frame = ttk.Frame(self, padding=(12, 0, 12, 0))
        frame.pack(fill=tk.BOTH, expand=True)
        self.tree = ttk.Treeview(frame, columns=("size", "modified"), selectmode="extended")
        self.tree.heading("#0", text="Datei")
        self.tree.heading("size", text="Größe")
        self.tree.heading("modified", text="Geändert")
        self.tree.column("#0", width=int(560 * app.scale))
        self.tree.column("size", width=int(100 * app.scale), anchor=tk.E)
        self.tree.column("modified", width=int(130 * app.scale))
        self.tree.tag_configure("group", background=app.palette["group"])
        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Double-1>", lambda ev: self._open())
        self.tree.bind("<Delete>", lambda ev: self._recycle())

        bottom = ttk.Frame(self, padding=12)
        bottom.pack(fill=tk.X)
        self.status = tk.StringVar(value="Bereit.")
        ttk.Label(bottom, textvariable=self.status).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(bottom, text="In den Papierkorb", command=self._recycle).pack(side=tk.RIGHT)
        ttk.Button(bottom, text="Im Explorer zeigen", command=self._reveal).pack(
            side=tk.RIGHT, padx=6)
        ttk.Button(bottom, text="Ältere Kopien markieren", command=self._mark_older).pack(
            side=tk.RIGHT)
        self.protocol("WM_DELETE_WINDOW", self._close)
        _center(self, app.root, 40)

    def _close(self):
        self._stop.set()
        self.destroy()

    def start(self):
        self._stop.clear()
        self.start_btn.state(["disabled"])
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        mode = self.mode.get()
        try:
            min_size = int(float(self.min_mb.get().replace(",", ".")) * 1024 * 1024)
        except ValueError:
            min_size = 1
        query = self.app.current_query(files_only=True)
        backend = self.app.backend
        self.status.set("Lade Dateiliste…")

        def work():
            t0 = time.time()
            try:
                res = backend.search(query, 0, self.SCAN_LIMIT, self._stop.is_set)
                rows = res.rows if res else []
                groups = find_duplicates(rows, mode, max(1, min_size),
                                         lambda m: self.app.dispatch(self.status.set, m),
                                         self._stop.is_set)
                self.app.dispatch(self._show, groups, len(rows), time.time() - t0)
            except Exception as exc:  # noqa: BLE001
                self.app.dispatch(self.status.set, f"Fehler: {exc}")
                self.app.dispatch(self.start_btn.state, ["!disabled"])

        threading.Thread(target=work, daemon=True).start()

    def _show(self, groups, scanned, seconds):
        if not self.winfo_exists():
            return
        self.start_btn.state(["!disabled"])
        for gi, group in enumerate(groups[:2000]):
            head = self.tree.insert("", tk.END, iid=f"g{gi}", open=True, tags=("group",),
                                    text=f"{group[0].name}  –  {len(group)}× ",
                                    values=(fmt_size(group[0].size), ""))
            for ri, row in enumerate(group):
                iid = f"g{gi}r{ri}"
                self._rows[iid] = row
                self.tree.insert(head, tk.END, iid=iid, text=row.path,
                                 values=(fmt_size(row.size), fmt_date(row.modified)))
        self.status.set(
            f"{fmt_count(len(groups))} {'Gruppe' if len(groups) == 1 else 'Gruppen'} · "
            f"{fmt_size(wasted_bytes(groups))} belegt "
            f"durch Kopien · {fmt_count(scanned)} Dateien geprüft in {seconds:.1f} s")

    def _selected(self):
        return [self._rows[i] for i in self.tree.selection() if i in self._rows]

    def _open(self):
        for row in self._selected()[:5]:
            self.app.shell_action(shell.open_path, row.path)

    def _reveal(self):
        rows = self._selected()
        if rows:
            self.app.shell_action(shell.reveal_in_explorer, rows[0].path)

    def _mark_older(self):
        """Select every copy except the newest one in each group."""
        sel = []
        for head in self.tree.get_children():
            kids = [k for k in self.tree.get_children(head) if k in self._rows]
            kids.sort(key=lambda k: (self._rows[k].modified.timestamp()
                                     if self._rows[k].modified else 0.0), reverse=True)
            sel += kids[1:]
        self.tree.selection_set(sel)

    def _recycle(self):
        rows = self._selected()
        if not rows:
            return
        heads = {self.tree.parent(i) for i in self.tree.selection() if i in self._rows}
        for h in heads:
            kids = [k for k in self.tree.get_children(h) if k in self._rows]
            if all(k in self.tree.selection() for k in kids):
                messagebox.showwarning("ALLES", "In mindestens einer Gruppe sind alle Kopien "
                                                "markiert. Eine Datei muss übrig bleiben.",
                                       parent=self)
                return
        if not messagebox.askyesno("In den Papierkorb",
                                   f"{len(rows)} Datei(en) in den Papierkorb verschieben?",
                                   parent=self):
            return
        if shell.recycle([r.path for r in rows], self.app.frame_hwnd()):
            for iid in list(self.tree.selection()):
                if iid in self._rows:
                    self.tree.delete(iid)
                    del self._rows[iid]
            for head in heads:  # a single remaining file is no duplicate any more
                if len(self.tree.get_children(head)) < 2:
                    self.tree.delete(head)
            self.status.set(f"{len(rows)} Datei(en) in den Papierkorb verschoben.")
        else:
            messagebox.showerror("ALLES", "Nicht alle Dateien konnten verschoben werden.",
                                 parent=self)


class UpdateDialog(tk.Toplevel):
    """Shows release notes and installs the update (download + verify + swap/setup)."""

    def __init__(self, app: AllesApp, release):
        from . import __version__, update
        super().__init__(app.root)
        self.app = app
        self.release = release
        self._upd = update
        self.kind = update.install_kind()
        self._stop = threading.Event()
        self.title("Update verfügbar")
        self.transient(app.root)
        self.resizable(False, False)
        theme.style_toplevel(self, app.palette)

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text=f"ALLES {release.version} ist verfügbar",
                  font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(frm, text=f"Installiert: {__version__}", style="Hint.TLabel").pack(
            anchor="w", pady=(2, 10))
        notes = tk.Text(frm, width=70, height=14, wrap="word", relief="flat",
                        highlightthickness=1, bg=app.palette["field"], fg=app.palette["fg"],
                        highlightbackground=app.palette["border"], padx=8, pady=6)
        notes.insert("1.0", release.notes[:6000] or "Keine Versionshinweise.")
        notes.configure(state="disabled")
        notes.pack(fill=tk.BOTH, expand=True)
        self.progress = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.status = tk.StringVar(value=self._kind_text())
        ttk.Label(frm, textvariable=self.status, style="Hint.TLabel", wraplength=520).pack(
            anchor="w", pady=(10, 0))
        btns = ttk.Frame(frm)
        btns.pack(fill=tk.X, pady=(12, 0))
        self.later_btn = ttk.Button(btns, text="Später", command=self._close)
        self.later_btn.pack(side=tk.RIGHT)
        ttk.Button(btns, text="Diese Version überspringen", command=self._skip).pack(
            side=tk.RIGHT, padx=6)
        label = "Zur Download-Seite" if self.kind == update.KIND_SOURCE else "Jetzt aktualisieren"
        self.go_btn = ttk.Button(btns, text=label, command=self._go)
        self.go_btn.pack(side=tk.LEFT)
        self.protocol("WM_DELETE_WINDOW", self._close)
        _center(self, app.root, 60)
        self.grab_set()

    def _kind_text(self):
        u = self._upd
        return {u.KIND_INSTALLER: "Der neue Installer wird geladen, geprüft und still "
                                  "ausgeführt. ALLES startet danach automatisch neu.",
                u.KIND_PORTABLE: "Die neue Version wird geladen, geprüft und ersetzt die "
                                 "portable EXE. Deine Daten bleiben erhalten.",
                u.KIND_EXE: "Die neue Version wird geladen, geprüft und ersetzt diese EXE.",
                u.KIND_SOURCE: "Du nutzt ALLES aus dem Quellcode – aktualisiere mit "
                               "„git pull“ oder lade die neue Version herunter.",
                }[self.kind]

    def _close(self):
        self._stop.set()
        self.destroy()

    def _skip(self):
        self.app.cfg["update_skip"] = self.release.version
        self.app.save_config()
        self.app.update_btn.pack_forget()
        self.destroy()

    def _go(self):
        u = self._upd
        if self.kind == u.KIND_SOURCE:
            os.startfile(self.release.page)
            self.destroy()
            return
        asset = u.pick_asset(self.release, self.kind)
        if not asset:
            messagebox.showerror("Update", "Im Release fehlt die passende Datei.", parent=self)
            return
        self.go_btn.state(["disabled"])
        self.progress.pack(fill=tk.X, pady=(10, 0))
        self.status.set(f"Lade {asset} …")

        def progress(done, total):
            if total:
                self.app.dispatch(self.progress.configure, {"value": done * 100 / total})

        def work():
            try:
                path = u.download(self.release, asset, progress, self._stop.is_set)
                self.app.dispatch(self._install, path)
            except u.UpdateError as exc:
                self.app.dispatch(self._failed, str(exc))
            except OSError as exc:
                self.app.dispatch(self._failed, f"Download fehlgeschlagen: {exc}")

        threading.Thread(target=work, name="update-download", daemon=True).start()

    def _failed(self, message):
        if self.winfo_exists():
            self.status.set(message)
            self.go_btn.state(["!disabled"])

    def _install(self, path):
        u = self._upd
        self.status.set("Installiere Update …")
        try:
            if self.kind == u.KIND_INSTALLER:
                u.apply_installer(path, os.getpid())
            else:
                u.apply_exe(path, restart_args=["--wait-pid", str(os.getpid())])
        except OSError as exc:
            self._failed(f"Update konnte nicht installiert werden: {exc}")
            return
        self.app.quit()
