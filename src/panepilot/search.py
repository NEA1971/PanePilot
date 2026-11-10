"""Dateisuche (F-810 ff.): nach Namen und/oder enthaltenem Text, im Hintergrund."""

from __future__ import annotations

import os
import re
import stat
import time
from dataclasses import asdict, dataclass, fields

from PySide6.QtCore import QThread, Signal

from .filters import FilterSpec

MAX_TEXT_SIZE = 100 * 1000 * 1000  # A-3: größere Dateien werden bei der Textsuche übersprungen
DEPTH_UNLIMITED = -1
NAME_WILDCARD, NAME_REGEX = "wildcard", "regex"
TEXT_PLAIN, TEXT_REGEX = "text", "regex"


@dataclass
class SearchOptions:
    name: str = ""
    name_mode: str = NAME_WILDCARD
    name_case: bool = False
    text: str = ""
    text_mode: str = TEXT_PLAIN
    text_case: bool = False
    depth: int = DEPTH_UNLIMITED  # 0 = nur dieser Ordner, n = n Ebenen, -1 = alle
    hidden: bool = False
    dirs: bool = True  # Ordner als Treffer (nur Namenssuche)
    network: bool = False  # in eingehängte Netzfreigaben hinabsteigen (F-880)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> SearchOptions:
        opts = cls()
        if not isinstance(data, dict):
            return opts
        for f in fields(cls):
            default = getattr(opts, f.name)
            value = data.get(f.name)
            if isinstance(default, bool):
                ok = isinstance(value, bool)
            elif isinstance(default, int):
                ok = isinstance(value, int) and not isinstance(value, bool)
            else:
                ok = isinstance(value, str)
            if ok:
                setattr(opts, f.name, value)
        if opts.name_mode not in (NAME_WILDCARD, NAME_REGEX):
            opts.name_mode = NAME_WILDCARD
        if opts.text_mode not in (TEXT_PLAIN, TEXT_REGEX):
            opts.text_mode = TEXT_PLAIN
        opts.depth = max(DEPTH_UNLIMITED, min(opts.depth, 10))
        return opts

    # --- Prüfen ------------------------------------------------------------------------
    def error(self) -> str | None:
        """None oder i18n-Schlüssel/Fehlertext."""
        if not self.name.strip() and not self.text:
            return "search.err_empty"
        if self.name.strip():
            err = self.name_spec().error()
            if err and err != "empty":
                return err
        if self.text and self.text_mode == TEXT_REGEX:
            try:
                re.compile(self.text)
            except re.error as exc:
                return str(exc)
        return None

    def name_spec(self) -> FilterSpec:
        return FilterSpec(self.name.strip(), regex=self.name_mode == NAME_REGEX, case_sensitive=self.name_case)

    def text_regex(self) -> re.Pattern | None:
        if not self.text:
            return None
        flags = 0 if self.text_case else re.IGNORECASE
        pattern = self.text if self.text_mode == TEXT_REGEX else re.escape(self.text)
        return re.compile(pattern, flags | re.MULTILINE)


def looks_binary(chunk: bytes) -> bool:
    return b"\0" in chunk


def file_contains(path: str, rx: re.Pattern, stop=lambda: False) -> bool:
    """Textdatei durchsuchen; Binärdateien (Nullbytes) gelten als „kein Treffer“."""
    with open(path, "rb") as fh:
        head = fh.read(8192)
        if looks_binary(head):
            return False
        data = head + fh.read()
    if stop():
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return rx.search(text) is not None


class SearchThread(QThread):
    found = Signal(list)  # Liste von Pfaden (gebündelt)
    progress = Signal(str, int)  # aktueller Ordner, Zahl der geprüften Einträge
    finished_search = Signal(bool, list)  # vollständig (nicht abgebrochen), übersprungene große Dateien

    def __init__(self, base: str, opts: SearchOptions, parent=None, exclude: set[str] | None = None) -> None:
        super().__init__(parent)
        self.base = base
        self.opts = opts
        # Ordner, in die die Suche nicht hinabsteigt (Netzfreigaben); der Startordner selbst zählt nicht
        self.exclude = {os.path.normpath(p) for p in (exclude or set())}
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        opts = self.opts
        match = opts.name_spec().matcher() if opts.name.strip() else None
        rx = opts.text_regex()
        skipped: list[str] = []
        batch: list[str] = []
        last_emit = time.monotonic()
        checked = 0
        # Breitensuche mit Tiefe; Verknüpfungen auf Ordner werden nicht verfolgt
        queue: list[tuple[str, int]] = [(self.base, 0)]
        while queue and not self._stop:
            folder, level = queue.pop(0)
            self.progress.emit(folder, checked)
            try:
                with os.scandir(folder) as it:
                    items = sorted(it, key=lambda d: d.name.casefold())
            except OSError:
                continue
            for de in items:
                if self._stop:
                    break
                checked += 1
                if de.name.startswith(".") and not opts.hidden:
                    continue
                try:
                    is_dir = de.is_dir(follow_symlinks=False)
                    is_link = de.is_symlink()
                except OSError:
                    continue
                if is_dir and not is_link and (opts.depth == DEPTH_UNLIMITED or level < opts.depth):
                    if os.path.normpath(de.path) not in self.exclude:
                        queue.append((de.path, level + 1))
                name_hit = match(de.name) if match else True
                if is_dir:
                    if rx is None and match is not None and opts.dirs and name_hit:
                        batch.append(de.path)
                elif name_hit:
                    if rx is None:
                        batch.append(de.path)
                    else:
                        try:
                            st = de.stat(follow_symlinks=True)
                            if not stat.S_ISREG(st.st_mode):
                                continue
                            if st.st_size > MAX_TEXT_SIZE:
                                skipped.append(de.path)
                                continue
                            if file_contains(de.path, rx, lambda: self._stop):
                                batch.append(de.path)
                        except OSError:
                            continue
                now = time.monotonic()
                if batch and now - last_emit > 0.2:
                    self.found.emit(batch)
                    batch = []
                    last_emit = now
                    self.progress.emit(folder, checked)
        if batch:
            self.found.emit(batch)
        self.finished_search.emit(not self._stop, skipped)
