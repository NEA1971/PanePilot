"""Duplikate suchen (v1.6, L-600 ff.).

Drei Arten (L-610): gleicher Inhalt (Größe, dann SHA-256), gleicher Name ohne Endung, gleicher Name und gleiche
Größe. Die Suche läuft in einem eigenen, frei verschiebbaren Fenster im Hintergrund; gefundene Dateien lassen sich
ankreuzen und in den Papierkorb verschieben (endgültiges Löschen gibt es hier bewusst nicht, L-644).
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import time
from dataclasses import asdict, dataclass, field, fields

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .filters import FilterSpec
from .i18n import t

MODE_CONTENT, MODE_NAME, MODE_NAMESIZE, MODE_ID, MODE_SIMILAR = "content", "name", "namesize", "id", "similar"
MODES = (MODE_CONTENT, MODE_NAME, MODE_NAMESIZE, MODE_ID, MODE_SIMILAR)
SIMILAR_MIN, SIMILAR_MAX, SIMILAR_DEFAULT = 70, 100, 85  # Regler in Prozent (v1.20, L-2010)
# Kennung im Dateinamen wie bei Jellyfin/Plex/Kodi, z. B. „Alien (1979) [imdbid-tt0078748].mkv“ (v1.6.2)
_ID_RX = re.compile(r"[\[{]\s*(imdbid|tmdbid|tvdbid|imdb|tmdb|tvdb)\s*[-=]\s*([A-Za-z0-9]+)\s*[\]}]", re.IGNORECASE)
DEPTH_ALL = 0  # wie bei der Verzeichnisliste: 0 = unbegrenzt, 1 = nur dieser Ordner, n = n Ebenen
CHUNK = 1024 * 1024
QUICK = 64 * 1024  # erst den Anfang vergleichen, dann ganz (spart Lesen bei verschiedenen Dateien)


@dataclass
class DupOptions:
    folder: str = ""
    mode: str = MODE_NAME  # Vorgabe beim ersten Aufruf (Abschnitt 8, Punkt 1)
    depth: int = DEPTH_ALL
    other: bool = False  # Ordner des anderen Fensters einbeziehen (L-622)
    pattern: str = ""  # z. B. „*.mp4;*.mkv“ (L-623)
    min_size_mb: int = 0
    similarity: int = SIMILAR_DEFAULT  # nur bei e) Ähnlicher Name

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("folder")
        return d

    @classmethod
    def from_dict(cls, data) -> DupOptions:
        opts = cls()
        if isinstance(data, dict):
            for f in fields(cls):
                if f.name == "folder":
                    continue
                value = data.get(f.name)
                default = getattr(opts, f.name)
                if isinstance(default, bool):
                    ok = isinstance(value, bool)
                elif isinstance(default, int):
                    ok = isinstance(value, int) and not isinstance(value, bool)
                else:
                    ok = isinstance(value, str)
                if ok:
                    setattr(opts, f.name, value)
        if opts.mode not in MODES:
            opts.mode = MODE_NAME
        opts.depth = max(0, min(opts.depth, 10))
        opts.min_size_mb = max(0, opts.min_size_mb)
        opts.similarity = max(SIMILAR_MIN, min(opts.similarity, SIMILAR_MAX))
        return opts


@dataclass
class FileInfo:
    path: str
    size: int
    mtime: float

    @property
    def name(self) -> str:
        return os.path.basename(self.path)


@dataclass
class Group:
    key: str
    files: list[FileInfo] = field(default_factory=list)

    @property
    def extra_size(self) -> int:
        """Platz, den die überzähligen Dateien belegen (alle bis auf die größte)."""
        sizes = sorted((f.size for f in self.files), reverse=True)
        return sum(sizes[1:])


# --- Suche (ohne Oberfläche, testbar) -------------------------------------------------------------------
def collect(folders: list[str], depth: int, hidden: bool, pattern: str = "", min_size: int = 0,
            stop=lambda: False, progress=lambda n: None) -> list[FileInfo]:
    """Alle passenden Dateien; Verknüpfungen werden nicht verfolgt (Abschnitt 8, Punkt 3)."""
    match = FilterSpec(pattern.strip()).matcher() if pattern.strip() else None
    seen_dirs: set[str] = set()
    seen_files: set[str] = set()
    out: list[FileInfo] = []
    for base in folders:
        queue = [(base, 1)]
        while queue and not stop():
            folder, level = queue.pop(0)
            real = os.path.realpath(folder)
            if real in seen_dirs:  # anderes Fenster im selben Baum: nicht doppelt zählen
                continue
            seen_dirs.add(real)
            try:
                with os.scandir(folder) as it:
                    entries = sorted(it, key=lambda d: d.name.casefold())
            except OSError:
                continue
            for de in entries:
                if stop():
                    break
                if de.name.startswith(".") and not hidden:
                    continue
                try:
                    if de.is_symlink():
                        continue
                    if de.is_dir(follow_symlinks=False):
                        if depth == DEPTH_ALL or level < depth:
                            queue.append((de.path, level + 1))
                        continue
                    st = de.stat(follow_symlinks=False)
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode) or st.st_size < min_size:
                    continue
                if match is not None and not match(de.name):
                    continue
                real_file = os.path.realpath(de.path)
                if real_file in seen_files:
                    continue
                seen_files.add(real_file)
                out.append(FileInfo(de.path, st.st_size, st.st_mtime))
                if len(out) % 200 == 0:
                    progress(len(out))
    progress(len(out))
    return out


def stem(name: str) -> str:
    return os.path.splitext(name)[0]


def file_id(name: str) -> str | None:
    """Kennung aus dem Dateinamen: IMDb vor TMDb vor TVDb, z. B. „imdbid-tt0078748“."""
    found = {}
    for m in _ID_RX.finditer(name):
        kind = m.group(1).lower()
        kind = kind if kind.endswith("id") else kind + "id"
        found.setdefault(kind, m.group(2).lower())
    for kind in ("imdbid", "tmdbid", "tvdbid"):
        if kind in found:
            return f"{kind}-{found[kind]}"
    return None


_SEPARATORS = re.compile(r"[\s._\-()\[\]{},;+&'\"!]+")
_NUMBERS = re.compile(r"\d+")


def similar_key(name: str) -> str:
    """L-2011: Name ohne Endung, Kennung, Groß-/Kleinschreibung und Satzzeichen."""
    base = _ID_RX.sub(" ", stem(name)).casefold()
    return _SEPARATORS.sub(" ", base).strip()


def _numbers(key: str) -> tuple:
    return tuple(int(n) for n in _NUMBERS.findall(key))


def similar_groups(files: list[FileInfo], percent: int, stop=lambda: False,
                   progress=lambda done, total: None) -> list[Group]:
    """L-2010/L-2012: Gruppen ähnlicher Namen; ähnlich zu ähnlich gehört in dieselbe Gruppe.

    Zahlen im Namen müssen übereinstimmen – sonst wären „IMG_0001“ und „IMG_0002“ oder „Folge 1“ und
    „Folge 2“ ähnlich."""
    from difflib import SequenceMatcher

    limit = max(SIMILAR_MIN, min(percent, SIMILAR_MAX)) / 100.0
    keys: dict[str, list[FileInfo]] = {}
    for f in files:
        k = similar_key(f.name)
        if k:
            keys.setdefault(k, []).append(f)
    uniq = sorted(keys, key=lambda k: (len(k), k))  # feste Reihenfolge (ratio ist nicht symmetrisch)
    parent = list(range(len(uniq)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    if limit < 1.0:
        _compare_all(uniq, limit, find, parent, stop, progress)
        if stop():
            return []
    clusters: dict[int, list[FileInfo]] = {}
    for i, k in enumerate(uniq):
        clusters.setdefault(find(i), []).extend(keys[k])
    groups = []
    for members in clusters.values():
        if len(members) > 1:
            members.sort(key=lambda f: f.path.casefold())
            groups.append(Group(_ID_RX.sub("", stem(members[0].name)).strip() or members[0].name, members))
    return _sorted(groups)


def _compare_all(uniq: list[str], limit: float, find, parent: list[int], stop, progress) -> None:
    """Paarweiser Vergleich, aber nur innerhalb gleicher Zahlen und passender Länge; Bigramme als Vorfilter."""
    import math
    from difflib import SequenceMatcher

    by_numbers: dict[tuple, list[int]] = {}
    for i, k in enumerate(uniq):  # uniq ist nach Länge sortiert, die Listen also auch
        by_numbers.setdefault(_numbers(k), []).append(i)
    total = len(uniq)
    done = 0
    grams = [{k[n:n + 2] for n in range(len(k) - 1)} for k in uniq]
    sm = SequenceMatcher(None, autojunk=False)
    for ids in by_numbers.values():
        for pos, i in enumerate(ids):
            if stop():
                return
            done += 1
            if done % 50 == 0:
                progress(done, total)
            a = uniq[i]
            la = len(a)
            ga = grams[i]
            dup_a = (la - 1) - len(ga)  # doppelte Bigramme in a
            max_len = la * (2 - limit) / limit  # längere Namen können nicht mehr ähnlich genug sein
            seq2_set = False
            for j in ids[pos + 1:]:
                b = uniq[j]
                lb = len(b)
                if lb > max_len:
                    break
                # gemeinsame Zeichen M ≥ limit·(la+lb)/2; Bigramme in gemeinsamen Stücken: ≥ 2M − la − 1
                need = 2 * math.ceil(limit * (la + lb) / 2) - la - 1 - dup_a
                if need > 0 and len(ga & grams[j]) < need:
                    continue
                if find(i) == find(j):
                    continue
                if not seq2_set:
                    sm.set_seq2(a)
                    seq2_set = True
                sm.set_seq1(b)
                if sm.quick_ratio() >= limit and sm.ratio() >= limit:
                    parent[find(j)] = find(i)
    progress(total, total)


def _groups_by(files: list[FileInfo], key) -> list[Group]:
    buckets: dict = {}
    for f in files:
        buckets.setdefault(key(f), []).append(f)
    return [Group(_label(k), sorted(v, key=lambda f: f.path.casefold())) for k, v in buckets.items() if len(v) > 1]


def _label(key) -> str:
    if isinstance(key, tuple):
        return str(key[0])
    return str(key)


def _hash(path: str, limit: int | None, stop, on_bytes) -> str | None:
    h = hashlib.sha256()
    done = 0
    try:
        with open(path, "rb") as fh:
            while not stop():
                want = CHUNK if limit is None else min(CHUNK, limit - done)
                if want <= 0:
                    break
                data = fh.read(want)
                if not data:
                    break
                h.update(data)
                done += len(data)
                on_bytes(len(data))
    except OSError:
        return None
    return None if stop() else h.hexdigest()


def find_groups(files: list[FileInfo], mode: str, stop=lambda: False, on_bytes=lambda n: None,
                set_total=lambda n: None, similarity: int = SIMILAR_DEFAULT,
                on_compare=lambda done, total: None) -> list[Group]:
    if mode == MODE_SIMILAR:
        return similar_groups(files, similarity, stop, on_compare)
    if mode == MODE_NAME:
        names = {}
        for f in files:  # Anzeige mit der Schreibweise der ersten Datei
            names.setdefault(stem(f.name).casefold(), stem(f.name))
        groups = _groups_by(files, lambda f: stem(f.name).casefold())
        for g in groups:
            g.key = names.get(g.key, g.key)
        return _sorted(groups)
    if mode == MODE_NAMESIZE:
        return _sorted(_groups_by(files, lambda f: (f.name.casefold(), f.size)))
    if mode == MODE_ID:  # gleiche Kennung im Namen; Dateien ohne Kennung zählen nicht
        with_id = [(file_id(f.name), f) for f in files]
        groups = _groups_by([f for i, f in with_id if i], lambda f: file_id(f.name))
        for g in groups:  # Anzeige: Name der ersten Datei ohne Endung und Kennung
            g.key = _ID_RX.sub("", stem(g.files[0].name)).strip() + f"  [{g.key}]"
        return _sorted(groups)
    # gleicher Inhalt: nur gleich große Dateien lesen (L-631); leere Dateien zählen nicht
    by_size = [g for g in _groups_by([f for f in files if f.size > 0], lambda f: f.size)]
    total = sum(min(f.size, QUICK) for g in by_size for f in g.files)
    total += sum(f.size for g in by_size for f in g.files if f.size > QUICK)
    set_total(total)
    groups: list[Group] = []
    for g in by_size:
        if stop():
            break
        quick: dict[str, list[FileInfo]] = {}
        for f in g.files:
            hq = _hash(f.path, QUICK, stop, on_bytes)
            if hq is not None:
                quick.setdefault(hq, []).append(f)
        for part in quick.values():
            if len(part) < 2:
                for f in part:  # nicht weiter lesen: Fortschritt trotzdem weiterzählen
                    if f.size > QUICK:
                        on_bytes(f.size - QUICK)
                continue
            if part[0].size <= QUICK:
                groups.append(Group(part[0].name, part))
                continue
            full: dict[str, list[FileInfo]] = {}
            for f in part:
                hf = _hash(f.path, None, stop, on_bytes)
                if hf is not None:
                    full.setdefault(hf, []).append(f)
            groups += [Group(p[0].name, p) for p in full.values() if len(p) > 1]
        for g2 in groups:
            g2.files.sort(key=lambda f: f.path.casefold())
    return [] if stop() else _sorted(groups)


def _sorted(groups: list[Group]) -> list[Group]:
    return sorted(groups, key=lambda g: g.key.casefold())


class DupThread(QThread):
    counted = Signal(int)  # gefundene Dateien
    bytes_progress = Signal(object, object)  # gelesen, gesamt (große Zahlen als Python-int)
    done = Signal(list, bool, int)  # Gruppen, vollständig (nicht abgebrochen), Anzahl geprüfter Dateien
    compare_progress = Signal(int, int)  # Namen verglichen, gesamt (e, L-2013)

    def __init__(self, opts: DupOptions, folders: list[str], hidden: bool, parent=None) -> None:
        super().__init__(parent)
        self.opts = opts
        self.folders = folders
        self.hidden = hidden
        self._stop = False
        self._read = 0
        self._total = 0
        self._last = 0.0

    def stop(self) -> None:
        self._stop = True

    def _on_bytes(self, n: int) -> None:
        self._read += n
        now = time.monotonic()
        if now - self._last > 0.2:
            self._last = now
            self.bytes_progress.emit(self._read, self._total)

    def _set_total(self, n: int) -> None:
        self._total = n
        self.bytes_progress.emit(0, n)

    def run(self) -> None:
        stop = lambda: self._stop  # noqa: E731
        files = collect(self.folders, self.opts.depth, self.hidden, self.opts.pattern,
                        self.opts.min_size_mb * 1000 * 1000, stop, self.counted.emit)
        groups = [] if self._stop else find_groups(files, self.opts.mode, stop, self._on_bytes, self._set_total,
                                                   self.opts.similarity, self.compare_progress.emit)
        self.done.emit(groups, not self._stop, len(files))


# --- Liste als Text ------------------------------------------------------------------------------------
def groups_text(groups: list[Group], opts: DupOptions, folders: list[str], checked: int | None = None) -> str:
    from .util import format_size

    lines = [t("dup.title"), "", t("dup.folders") + " " + "; ".join(folders),
             t("dup.mode") + " " + t(f"dup.mode_{opts.mode}"), "", summary_text(groups, checked), ""]
    for n, g in enumerate(groups, 1):
        lines.append(f"[{n}] {g.key}")
        for f in g.files:
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.mtime))
            lines.append(f"    {f.path}    {format_size(f.size)}    {when}")
        lines.append("")
    return "\n".join(lines)


def summary_text(groups: list[Group], checked: int | None = None) -> str:
    from .util import format_size

    if not groups:
        text = t("dup.none")
    else:
        files = sum(len(g.files) for g in groups)
        text = t("dup.summary", groups=len(groups), files=files, extra=files - len(groups),
                 size=format_size(sum(g.extra_size for g in groups)))
    if checked is not None:  # v1.6.2: zeigt, ob der Filter überhaupt etwas erfasst hat
        text += " " + t("dup.checked", n=checked)
    return text


# --- Fenster ---------------------------------------------------------------------------------------------
PICK_NEWEST, PICK_OLDEST, PICK_LARGEST, PICK_NONE = "newest", "oldest", "largest", "none"


class DuplicateWindow(QWidget):
    """Eigenes, frei verschiebbares Fenster (L-601)."""

    def __init__(self, window, folder: str, other: str | None) -> None:
        super().__init__(window, Qt.WindowType.Window)
        self.window = window
        self.other_folder = other
        self.thread: DupThread | None = None
        self.groups: list[Group] = []
        self.last_opts: DupOptions | None = None
        self.checked_count: int | None = None
        self.last_folders: list[str] = []
        self.setWindowTitle(t("dup.title"))
        opts = DupOptions.from_dict(window.settings.get("dup_last"))
        opts.folder = folder

        # Optionen
        self.folder_edit = QLineEdit(folder, self)
        browse = QToolButton(self)
        browse.setText("…")
        browse.setToolTip(t("dup.browse"))
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder_edit, 1)
        row.addWidget(browse)
        self.other_check = QCheckBox(t("dup.other", path=other or "–"), self)
        self.other_check.setEnabled(bool(other))
        self.other_check.setChecked(bool(other) and opts.other)
        self.mode_buttons: dict[str, QRadioButton] = {}
        group = QButtonGroup(self)
        modes = QVBoxLayout()
        for m in MODES:
            b = QRadioButton(t(f"dup.mode_{m}"), self)
            group.addButton(b)
            modes.addWidget(b)
            self.mode_buttons[m] = b
        self.mode_buttons[opts.mode].setChecked(True)
        # Regler für e) Ähnlicher Name (v1.20, L-2010)
        self.similar = QSlider(Qt.Orientation.Horizontal, self)
        self.similar.setRange(SIMILAR_MIN, SIMILAR_MAX)
        self.similar.setSingleStep(1)
        self.similar.setPageStep(5)
        self.similar.setValue(opts.similarity)
        self.similar_label = QLabel(self)
        self.similar.valueChanged.connect(self._similar_changed)
        srow = QHBoxLayout()
        srow.setContentsMargins(24, 0, 0, 0)
        srow.addWidget(QLabel(t("dup.similarity"), self))
        srow.addWidget(self.similar, 1)
        srow.addWidget(self.similar_label)
        modes.addLayout(srow)
        self.mode_buttons[MODE_SIMILAR].toggled.connect(lambda _on: self._similar_changed())
        self._similar_changed()
        hint = QLabel(t("dup.speed_hint"), self)  # L-611
        hint.setWordWrap(True)
        hint.setObjectName("hintLabel")
        modes.addWidget(hint)
        self.depth = QComboBox(self)
        self.depth.addItem(t("dirlist.depth_all"), DEPTH_ALL)
        self.depth.addItem(t("dup.depth_one"), 1)
        for n in range(2, 11):
            self.depth.addItem(str(n), n)
        self.depth.setCurrentIndex(max(self.depth.findData(opts.depth), 0))
        self.pattern = QLineEdit(opts.pattern, self)
        self.pattern.setPlaceholderText("*.mp4;*.mkv")
        self.min_size = QSpinBox(self)
        self.min_size.setRange(0, 1000000)
        self.min_size.setSuffix(" MB")
        self.min_size.setValue(opts.min_size_mb)
        form = QFormLayout()
        form.addRow(t("dup.folder"), row)
        form.addRow("", self.other_check)
        form.addRow(t("dup.mode"), modes)
        form.addRow(t("dirlist.depth"), self.depth)
        form.addRow(t("dup.pattern"), self.pattern)
        form.addRow(t("dup.min_size"), self.min_size)
        self.btn_start = QPushButton(t("dup.start"), self)
        self.btn_start.setDefault(True)
        self.btn_start.clicked.connect(self.start_or_stop)

        # Fortschritt und Ergebnis
        self.bar = QProgressBar(self)
        self.bar.setVisible(False)
        self.status = QLabel(self)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels([t("dup.col_name"), t("dup.col_folder"), t("dup.col_size"), t("dup.col_date")])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, w in enumerate((330, 380, 90)):
            hdr.resizeSection(col, w)
        self.tree.itemDoubleClicked.connect(lambda *_a: self.show_in_panel())
        self.tree.itemChanged.connect(lambda *_a: self._update_buttons())
        self.tree.currentItemChanged.connect(lambda *_a: self._update_buttons())

        self.btn_pick = QToolButton(self)
        self.btn_pick.setText(t("dup.pick"))
        self.btn_pick.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        pick = QMenu(self.btn_pick)
        for key in (PICK_NEWEST, PICK_OLDEST, PICK_LARGEST, PICK_NONE):
            pick.addAction(t(f"dup.pick_{key}")).triggered.connect(lambda _c=False, k=key: self.pick(k))
        self.btn_pick.setMenu(pick)
        self.btn_trash = QPushButton(t("dup.trash"), self)
        self.btn_trash.clicked.connect(self.move_to_trash)
        self.btn_show = QPushButton(t("dup.show"), self)
        self.btn_show.clicked.connect(self.show_in_panel)
        self.btn_save = QPushButton(t("dup.save"), self)
        self.btn_save.clicked.connect(self.save_list)
        self.btn_close = QPushButton(t("button.close"), self)
        self.btn_close.clicked.connect(self.close)
        buttons = QHBoxLayout()
        for b in (self.btn_pick, self.btn_trash, self.btn_show, self.btn_save):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_close)

        top = QHBoxLayout()
        top.addLayout(form, 1)
        start_col = QVBoxLayout()
        start_col.addStretch(1)
        start_col.addWidget(self.btn_start)
        top.addLayout(start_col)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.bar)
        lay.addWidget(self.status)
        lay.addWidget(self.summary)
        lay.addWidget(self.tree, 1)
        lay.addLayout(buttons)
        geo = window.settings.get("dup_geometry")
        if isinstance(geo, list) and len(geo) == 2:
            self.resize(int(geo[0]), int(geo[1]))
        else:
            self.resize(980, 680)
        self._update_buttons()

    # Optionen
    def options(self) -> DupOptions:
        mode = next((m for m, b in self.mode_buttons.items() if b.isChecked()), MODE_NAME)
        return DupOptions(folder=self.folder_edit.text().strip(), mode=mode, depth=int(self.depth.currentData()),
                          other=self.other_check.isChecked(), pattern=self.pattern.text().strip(),
                          min_size_mb=self.min_size.value(), similarity=self.similar.value())

    def _similar_changed(self, *_args) -> None:
        self.similar_label.setText(f"{self.similar.value()} %")
        on = self.mode_buttons[MODE_SIMILAR].isChecked() and self.mode_buttons[MODE_SIMILAR].isEnabled()
        self.similar.setEnabled(on)
        self.similar_label.setEnabled(on)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, t("dup.browse"), self.folder_edit.text())
        if path:
            self.folder_edit.setText(path)

    def _set_inputs_enabled(self, on: bool) -> None:
        for w in (self.folder_edit, self.other_check, self.depth, self.pattern, self.min_size,
                  *self.mode_buttons.values()):
            w.setEnabled(on if w is not self.other_check else on and bool(self.other_folder))
        self._similar_changed()

    # Suche
    def start_or_stop(self) -> None:
        if self.thread is not None:
            self.thread.stop()
            self.status.setText(t("dup.stopping"))
            return
        opts = self.options()
        if not os.path.isdir(opts.folder):
            from .dialogs import show_error

            show_error(self, t("dup.title"), t("dup.no_folder", path=opts.folder))
            return
        if opts.pattern:
            err = FilterSpec(opts.pattern).error()
            if err and err != "empty":
                from .dialogs import show_error

                show_error(self, t("dup.title"), t(err) if err.startswith("filter.") else err)
                return
        self.window.settings.set("dup_last", opts.to_dict())  # L-650
        folders = [opts.folder]
        if opts.other and self.other_folder and os.path.isdir(self.other_folder):
            folders.append(self.other_folder)
        self.last_opts, self.last_folders = opts, folders
        self.tree.clear()
        self.groups = []
        self.summary.setText("")
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.status.setText(t("dup.counting", n=0))
        self.btn_start.setText(t("dup.cancel"))
        self._set_inputs_enabled(False)
        self._update_buttons()
        th = DupThread(opts, folders, bool(self.window.settings.get("show_hidden")), self)
        th.counted.connect(lambda n: self.status.setText(t("dup.counting", n=n)))
        th.bytes_progress.connect(self._bytes)
        th.compare_progress.connect(self._compared)
        th.done.connect(self._done)
        self.thread = th
        th.start()

    def _bytes(self, done, total) -> None:
        from .util import format_size

        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(1000 * min(done, total) / total))
            self.status.setText(t("dup.reading", done=format_size(done), total=format_size(total)))

    def _compared(self, done: int, total: int) -> None:
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(1000 * min(done, total) / total))
            self.status.setText(t("dup.comparing", done=done, total=total))

    def _done(self, groups: list, complete: bool, checked: int = 0) -> None:
        th, self.thread = self.thread, None
        if th is not None:
            th.wait(2000)
            th.deleteLater()
        self.bar.setVisible(False)
        self.btn_start.setText(t("dup.start"))
        self._set_inputs_enabled(True)
        if not complete:
            self.status.setText(t("dup.cancelled"))
            self._update_buttons()
            return
        self.status.setText("")
        self.groups = groups
        self.checked_count = checked
        self._fill()

    def _fill(self) -> None:
        from .util import format_size

        self.tree.blockSignals(True)
        self.tree.clear()
        for g in self.groups:
            top = QTreeWidgetItem([t("dup.group", key=g.key, n=len(g.files)), "", "", ""])
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            top.setFirstColumnSpanned(True)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for f in g.files:
                when = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.mtime))
                child = QTreeWidgetItem([f.name, os.path.dirname(f.path), format_size(f.size), when])
                child.setData(0, Qt.ItemDataRole.UserRole, f)
                child.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                               Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Unchecked)
                child.setTextAlignment(2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                child.setToolTip(0, f.path)
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        self.tree.blockSignals(False)
        self.summary.setText(summary_text(self.groups, self.checked_count))  # L-641
        self._update_buttons()

    # Auswahl
    def file_items(self):
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for j in range(top.childCount()):
                yield top, top.child(j)

    def checked(self) -> list[FileInfo]:
        return [c.data(0, Qt.ItemDataRole.UserRole) for _t, c in self.file_items()
                if c.checkState(0) == Qt.CheckState.Checked]

    def pick(self, how: str) -> None:
        """Schnellwahl für alle Gruppen (L-642)."""
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            children = [top.child(j) for j in range(top.childCount())]
            infos = [c.data(0, Qt.ItemDataRole.UserRole) for c in children]
            keep = None
            if how == PICK_NEWEST:
                keep = max(range(len(infos)), key=lambda k: infos[k].mtime)
            elif how == PICK_OLDEST:
                keep = min(range(len(infos)), key=lambda k: infos[k].mtime)
            elif how == PICK_LARGEST:
                keep = max(range(len(infos)), key=lambda k: infos[k].size)
            for k, c in enumerate(children):
                on = how != PICK_NONE and k != keep
                c.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self._update_buttons()

    def _update_buttons(self) -> None:
        busy = self.thread is not None
        has = bool(self.groups) and not busy
        self.btn_pick.setEnabled(has)
        self.btn_save.setEnabled(has)
        self.btn_trash.setEnabled(has and bool(self.checked()))
        cur = self.tree.currentItem()
        self.btn_show.setEnabled(not busy and cur is not None and cur.data(0, Qt.ItemDataRole.UserRole) is not None)

    # Aktionen (L-643)
    def move_to_trash(self) -> None:
        from .dialogs import confirm, show_error
        from .fileops import move_to_trash
        from .util import format_size

        chosen = self.checked()
        if not chosen:
            return
        total = sum(f.size for f in chosen)
        text = t("dup.trash_confirm", n=len(chosen), size=format_size(total))
        empty_groups = [top.text(0) for top, _c in self._groups_all_checked()]
        warning = bool(empty_groups)
        if warning:  # keine Datei der Gruppe bliebe übrig
            text = t("dup.trash_all_warning", n=len(empty_groups)) + "\n\n" + text
        if not confirm(self, t("dup.trash"), text, yes_key="dup.trash", default_yes=not warning, warning=warning):
            return
        failed = []
        done: set[str] = set()
        for f in chosen:
            try:
                move_to_trash(f.path)
                done.add(f.path)
            except OSError as exc:
                failed.append(f"{f.path}: {exc.strerror or exc}")
        for g in self.groups:
            g.files = [f for f in g.files if f.path not in done]
        self.groups = [g for g in self.groups if len(g.files) > 1]
        if self.checked_count is not None:
            self.checked_count = max(0, self.checked_count - len(done))
        self._fill()
        self._refresh_panels()
        if failed:
            show_error(self, t("dup.trash"), "\n".join(failed[:20]))

    def _groups_all_checked(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            kids = [top.child(j) for j in range(top.childCount())]
            if kids and all(c.checkState(0) == Qt.CheckState.Checked for c in kids):
                out.append((top, kids))
        return out

    def _refresh_panels(self) -> None:
        for s in getattr(self.window, "sides", {}).values():
            try:
                s.panel.refresh()
            except Exception:  # noqa: BLE001 – Anzeige ist Nebensache
                pass

    def show_in_panel(self) -> None:
        cur = self.tree.currentItem()
        info = cur.data(0, Qt.ItemDataRole.UserRole) if cur is not None else None
        if info is None:
            return
        panel = self.window.active
        panel.navigate(os.path.dirname(info.path), select_name=info.name)
        self.window.raise_()
        self.window.activateWindow()

    def save_list(self) -> None:
        from .dialogs import show_error

        start = os.path.join(self.last_folders[0] if self.last_folders else os.path.expanduser("~"),
                             t("dup.file_name") + ".txt")
        path, _f = QFileDialog.getSaveFileName(self, t("dup.save"), start, "*.txt")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(groups_text(self.groups, self.last_opts or self.options(), self.last_folders,
                                     self.checked_count))
        except OSError as exc:
            show_error(self, t("dup.save"), exc.strerror or str(exc))

    def closeEvent(self, event) -> None:
        if self.thread is not None:
            self.thread.stop()
            self.thread.wait(3000)
            self.thread = None
        self.window.settings.set("dup_geometry", [self.width(), self.height()])
        super().closeEvent(event)
