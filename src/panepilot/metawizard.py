"""Meta-Wizard für Musikdateien (F-900 ff.): Titelliste, Seitenleiste mit Feldern, Cover, Einlesen/Speichern
im Hintergrund.

Ablauf wie beim Mehrfachen Umbenennen: Ein-Fenster-Ansicht, links die Seitenleiste (MetaPane), rechts statt
der Dateiliste die Titelliste (MetaView). Änderungen werden gesammelt (MetaItem.pending) und erst mit
„Tag speichern“ geschrieben (F-924, F-925).
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

from PySide6.QtCore import (
    QAbstractTableModel,
    QBuffer,
    QByteArray,
    QIODevice,
    QModelIndex,
    QSortFilterProxyModel,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtGui import QBrush, QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from . import metaprofile as mp
from . import tags as tg
from .i18n import t
from .toolpanes import ToolPane
from .util import format_size

REMOVE = None  # Wert „Feld entfernen“

# --- Spalten und Felder ---------------------------------------------------------------------------
COL_FILENAME, COL_PATH = "filename", "path"
INFO_COLUMNS = mp.AUDIO_INFO  # Musik; im Foto-Modus mp.info_columns()
DEFAULT_COLUMNS = mp.AUDIO_COLUMNS  # F-910
DEFAULT_SIDEBAR = mp.AUDIO_SIDEBAR  # F-920
COVER = "cover"
MAX_VALUES = 50  # F-921
CHANGED_COLOR = QColor("#2E7D32")
ERROR_COLOR = QColor("#D32F2F")


def column_title(col: str) -> str:
    if col in (COL_FILENAME, COL_PATH):
        return t(f"meta.col.{col}")
    if col.startswith(tg.EXTRA):
        return tg.label_of(col)
    if col.startswith("i:"):
        return t(f"meta.info.{col[2:]}")
    if col == COVER:
        if mp.is_video_mode():
            return t("video.poster")
        return t("photo.preview") if mp.is_photo_mode() else t("meta.field.cover")
    return t(f"meta.field.{col}")


def camera_name(item) -> str:
    """Hersteller und Modell, ohne doppelten Herstellernamen (z. B. „Canon EOS R6“)."""
    make, model = item.value("make").strip(), item.value("model").strip()
    if make and model.casefold().startswith(make.split()[0].casefold()):
        return model
    return f"{make} {model}".strip()


def _natural(text: str) -> str:
    return re.sub(r"\d+", lambda m: m.group().zfill(12), text.casefold())


@dataclass
class MetaItem:
    record: tg.TagRecord
    base: str = ""  # Startordner (für die Spalte „Pfad“)
    pending: dict[str, str | None] = field(default_factory=dict)
    pending_pictures: list[tg.Picture] | None = None
    pending_name: str | None = None  # neuer Dateiname aus Tag → Dateiname (F-992)
    mark: str = ""  # Konverter-Fehler: Zeile rot, Grund als Tooltip (F-995, F-996)

    @property
    def changed(self) -> bool:
        return bool(self.pending) or self.pending_pictures is not None or self.pending_name is not None

    @property
    def display_name(self) -> str:
        return self.pending_name or self.record.name

    def value(self, key: str) -> str:
        key = tg.resolve_key(self.record, key)
        if key in self.pending:
            v = self.pending[key]
            return "" if v is None else v
        return self.record.fields.get(key, "")

    def pictures(self) -> list[tg.Picture]:
        return self.pending_pictures if self.pending_pictures is not None else self.record.pictures

    def set(self, key: str, value: str | None) -> None:
        key = tg.resolve_key(self.record, key)
        exists = key in self.record.fields or key in self.record.data
        old = self.record.fields.get(key)
        if value is None or value == "":
            if exists:
                self.pending[key] = None
            else:
                self.pending.pop(key, None)
        elif exists and value == old:
            self.pending.pop(key, None)  # zurück auf den gespeicherten Stand
        else:
            self.pending[key] = value

    def readonly(self, key: str) -> bool:
        ro = self.record.readonly
        if "*" in ro:  # ganze Datei nur lesbar (z. B. RAW-Fotos, v1.4)
            return True
        key = tg.resolve_key(self.record, key)
        return key in ro or ("x:*" in ro and key.startswith(tg.EXTRA))

    def remove_only(self, key: str) -> bool:
        """Feld lässt sich nur entfernen, nicht ändern (Kamera, GPS … bei Fotos)."""
        return key in self.record.removable

    def set_pictures(self, pictures: list[tg.Picture]) -> None:
        old = self.record.pictures
        if len(old) == len(pictures) and all(a.same(b) for a, b in zip(old, pictures)):
            self.pending_pictures = None
        else:
            self.pending_pictures = pictures

    def folder(self) -> str:
        d = os.path.dirname(self.record.path)
        rel = os.path.relpath(d, self.base) if self.base else d
        return "" if rel == "." else rel


# --- Modell der Titelliste ---------------------------------------------------------------------------
class MetaModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.items: list[MetaItem] = []
        self.columns: list[str] = mp.default_columns()
        self.align: dict[str, str] = {}
        self.custom_fields: list[str] = []

    # Grunddaten
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.items)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < len(self.columns):
            return None
        col = self.columns[section]
        if role == Qt.ItemDataRole.DisplayRole:
            return column_title(col)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self._alignment(col)
        return None

    def _alignment(self, col: str):
        mode = self.align.get(col, "right" if col in ("i:bitrate", "i:samplerate", "i:size", "i:length", "i:duration",
                                                        "i:fps", "rating", "iso")
                              else "left")
        h = {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
             "right": Qt.AlignmentFlag.AlignRight}.get(mode, Qt.AlignmentFlag.AlignLeft)
        return int(h | Qt.AlignmentFlag.AlignVCenter)

    def text(self, item: MetaItem, col: str) -> str:
        rec = item.record
        if col == COL_FILENAME:
            return ("✎ " if item.changed else "") + item.display_name
        if col == COL_PATH:
            return item.folder()
        if col.startswith("i:"):
            what = col[2:]
            if what in ("length", "duration"):
                return tg.format_length(rec.length) if rec.length else ""
            if what == "resolution":
                return f"{rec.width} × {rec.height}" if rec.width else ""
            if what == "fps":
                from .videotags import format_fps

                return format_fps(rec.fps)
            if what == "vcodec":
                return rec.vcodec
            if what == "acodec":
                return rec.acodec
            if what == "bitrate":
                return f"{round(rec.bitrate / 1000)} kbit/s" if rec.bitrate else ""
            if what == "samplerate":
                return f"{rec.sample_rate} Hz" if rec.sample_rate else ""
            if what in ("codec", "format"):
                return rec.codec
            if what == "dims":
                return f"{rec.width} × {rec.height}" if rec.width else ""
            if what == "camera":
                return camera_name(item)
            if what == "size":
                return format_size(rec.size)
            if what == "mtime":
                return time.strftime("%d.%m.%Y %H:%M", time.localtime(rec.mtime)) if rec.mtime else ""
        return item.value(col).replace("\n", " ⏎ ")

    def sort_key(self, item: MetaItem, col: str):
        rec = item.record
        if col in ("i:length", "i:duration"):
            return float(rec.length)
        if col == "i:fps":
            return float(rec.fps)
        if col == "i:resolution":
            return float(rec.width * rec.height)
        if col == "i:bitrate":
            return float(rec.bitrate)
        if col == "i:samplerate":
            return float(rec.sample_rate)
        if col == "i:size":
            return float(rec.size)
        if col == "i:mtime":
            return float(rec.mtime)
        if col == "i:dims":
            return float(rec.width * rec.height)
        if col == "i:camera":
            return _natural(camera_name(item))
        if col in ("rating", "iso"):
            try:
                return float(item.value(col).split()[0])
            except (ValueError, IndexError):
                return -1.0
        if col == COL_FILENAME:
            return _natural(rec.name)
        if col == COL_PATH:
            return _natural(item.folder() + "/" + rec.name)
        return _natural(item.value(col))

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self.items[index.row()]
        col = self.columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self.text(item, col)
        if role == Qt.ItemDataRole.UserRole:
            return self.sort_key(item, col)
        if role == Qt.ItemDataRole.ForegroundRole:
            if item.record.error or item.mark:
                return QBrush(ERROR_COLOR)
            if item.changed:
                return QBrush(CHANGED_COLOR)  # F-915
            return None
        if role == Qt.ItemDataRole.ToolTipRole:
            if item.record.error:
                return t("meta.read_error", reason=item.record.error)
            if item.mark:
                return item.mark
            if col == COL_FILENAME and item.pending_name:
                return t("conv.old_name", name=item.record.name)
            if col == COL_PATH:
                return os.path.dirname(item.record.path)
            if col == COL_FILENAME:
                return item.record.path
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return self._alignment(col)
        return None

    # Änderungen
    def add_items(self, items: list[MetaItem]) -> None:
        if not items:
            return
        first = len(self.items)
        self.beginInsertRows(QModelIndex(), first, first + len(items) - 1)
        self.items.extend(items)
        self.endInsertRows()

    def set_columns(self, columns: list[str]) -> None:
        self.beginResetModel()
        self.columns = list(columns)
        self.endResetModel()

    def rows_changed(self, rows: list[int] | None = None) -> None:
        if not self.items:
            return
        if rows is None:
            rows = [0, len(self.items) - 1]
        top, bottom = min(rows), max(rows)
        self.dataChanged.emit(self.index(top, 0), self.index(bottom, len(self.columns) - 1))

    def extra_keys(self) -> dict[str, str]:
        """Alle Zusatzfelder der eingelesenen Dateien und eigene Felder, je Name einmal (F-912)."""
        found: dict[str, str] = {}
        seen: set[str] = set()
        for it in self.items:
            for k, label in it.record.labels.items():
                if label.casefold() not in seen:
                    seen.add(label.casefold())
                    found[k] = label
        for name in self.custom_fields:
            if name.casefold() not in seen:
                seen.add(name.casefold())
                found[tg.EXTRA + name] = name
        return dict(sorted(found.items(), key=lambda kv: kv[1].casefold()))

    def changed_items(self) -> list[MetaItem]:
        return [it for it in self.items if it.changed]


class MetaProxy(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSortRole(Qt.ItemDataRole.UserRole)
        self.setDynamicSortFilter(False)

    def lessThan(self, left, right) -> bool:
        a, b = left.data(self.sortRole()), right.data(self.sortRole())
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


# --- Titelliste ---------------------------------------------------------------------------------------
class MetaView(QTreeView):
    layout_changed = Signal()  # Spalten/Breiten geändert → speichern (F-913)
    escape_pressed = Signal()
    field_editor_requested = Signal()  # F-970
    row_menu_requested = Signal(object)  # globale Position (F-990)

    def __init__(self, model: MetaModel, parent=None) -> None:
        super().__init__(parent)
        self.source = model
        self.proxy = MetaProxy(self)
        self.proxy.setSourceModel(model)
        self.setModel(self.proxy)
        self.setObjectName("metaList")
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)  # F-914
        self.setSortingEnabled(True)
        self.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
        self.widths: dict[str, int] = {}
        hdr = self.header()
        hdr.setSectionsMovable(True)
        hdr.setStretchLastSection(False)
        hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hdr.customContextMenuRequested.connect(self._header_menu)
        hdr.sectionMoved.connect(self._section_moved)
        hdr.sectionResized.connect(self._section_resized)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self.row_menu_requested.emit(
            self.viewport().mapToGlobal(pos)))
        self._resetting = False
        model.modelReset.connect(self._apply_widths)

    # Darstellung
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
            return
        super().keyPressEvent(event)

    def _apply_widths(self) -> None:
        self._resetting = True
        for i, col in enumerate(self.source.columns):
            self.header().resizeSection(i, self.widths.get(col, 220 if col in (COL_FILENAME, "title") else 140))
        self._resetting = False

    def _section_resized(self, logical: int, _old: int, new: int) -> None:
        if self._resetting or not 0 <= logical < len(self.source.columns):
            return
        self.widths[self.source.columns[logical]] = new
        self.layout_changed.emit()

    def _section_moved(self, _logical: int, _old: int, _new: int) -> None:
        # Neue Reihenfolge übernehmen und die Kopfzeile wieder geradeziehen
        hdr = self.header()
        order = [self.source.columns[hdr.logicalIndex(v)] for v in range(hdr.count())]
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, lambda o=order: self.set_columns(o))

    def set_columns(self, columns: list[str]) -> None:
        selected = self.selected_items()
        hdr = self.header()
        hdr.blockSignals(True)
        for v in range(hdr.count()):  # Kopfzeile in Grundstellung
            li = hdr.logicalIndex(v)
            if li != v:
                hdr.moveSection(hdr.visualIndex(v), v)
        hdr.blockSignals(False)
        self.source.set_columns(columns)
        self.select_items(selected)
        self.layout_changed.emit()

    def _header_menu(self, pos) -> None:
        cols = self.source.columns
        menu = QMenu(self)
        logical = self.header().logicalIndexAt(pos)
        if 0 <= logical < len(cols):
            col = cols[logical]
            sub = menu.addMenu(t("colprof.align_of", name=column_title(col)))
            current = self.source.align.get(col, "")
            for mode in ("left", "center", "right"):
                act = sub.addAction(t(f"colprof.align_{mode}"))
                act.setCheckable(True)
                act.setChecked(current == mode)
                act.triggered.connect(lambda _c=False, c=col, m=mode: self._set_align(c, m))
            menu.addSeparator()

        def toggle(col: str, on: bool) -> None:
            new = [c for c in cols if c != col]
            if on:
                new.append(col)
            if new:
                self.set_columns(new)

        def add_toggle(target, col: str) -> None:
            act = target.addAction(column_title(col))
            act.setCheckable(True)
            act.setChecked(col in cols)
            act.setEnabled(not (col in cols and len(cols) == 1))
            act.toggled.connect(lambda on, c=col: toggle(c, on))

        for col in (COL_FILENAME, *mp.fields(), COL_PATH):
            add_toggle(menu, col)
        extra = menu.addMenu(t("meta.more_fields"))
        keys = self.source.extra_keys()
        extra.setEnabled(bool(keys))
        for k in keys:
            add_toggle(extra, k)
        info = menu.addMenu(t("meta.info_fields"))
        for col in mp.info_columns():
            add_toggle(info, col)
        menu.addSeparator()
        menu.addAction(t("fields.menu")).triggered.connect(self.field_editor_requested)
        menu.addAction(t("meta.columns_default")).triggered.connect(lambda: self.set_columns(mp.default_columns()))
        menu.exec(self.header().mapToGlobal(pos))

    def _set_align(self, col: str, mode: str) -> None:
        self.source.align[col] = mode
        self.source.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.source.columns) - 1)
        self.source.rows_changed()
        self.layout_changed.emit()

    # Auswahl
    def target_items(self) -> list[MetaItem]:
        """Markierte Titel, sonst alle angezeigten – jeweils in der Reihenfolge der Liste (v0.9.3)."""
        if self.selectionModel().hasSelection():
            rows = sorted({i.row() for i in self.selectionModel().selectedRows()})
        else:
            rows = range(self.proxy.rowCount())
        result = []
        for r in rows:
            src = self.proxy.mapToSource(self.proxy.index(r, 0)).row()
            if 0 <= src < len(self.source.items):
                result.append(self.source.items[src])
        return result

    def selected_items(self) -> list[MetaItem]:
        rows = sorted({self.proxy.mapToSource(i).row() for i in self.selectionModel().selectedRows()})
        return [self.source.items[r] for r in rows if 0 <= r < len(self.source.items)]

    def select_items(self, items: list[MetaItem]) -> None:
        from PySide6.QtCore import QItemSelection, QItemSelectionModel

        sel = QItemSelection()
        wanted = {id(i) for i in items}
        for r, it in enumerate(self.source.items):
            if id(it) in wanted:
                idx = self.proxy.mapFromSource(self.source.index(r, 0))
                sel.select(idx, idx)
        self.selectionModel().select(sel, QItemSelectionModel.SelectionFlag.ClearAndSelect
                                     | QItemSelectionModel.SelectionFlag.Rows)

    # Einstellungen
    def layout_state(self) -> dict:
        return {"columns": list(self.source.columns), "widths": dict(self.widths), "align": dict(self.source.align)}

    def restore_layout(self, state) -> None:
        if not isinstance(state, dict):
            state = {}
        known = set(mp.fields()) | set(mp.info_columns()) | {COL_FILENAME, COL_PATH}
        cols = [c for c in state.get("columns", []) if isinstance(c, str) and (c in known or c.startswith(tg.EXTRA))]
        cols = cols or mp.default_columns()
        self.widths = {k: int(v) for k, v in (state.get("widths") or {}).items() if isinstance(v, int)}
        self.source.align = {k: v for k, v in (state.get("align") or {}).items() if v in ("left", "center", "right")}
        self.set_columns(cols)


# --- Einlesen im Hintergrund (F-904) ------------------------------------------------------------------
class MetaScanThread(QThread):
    kind_chosen = Signal(str, int, int, int)  # Art, Anzahl Musik, Fotos, Videos (v1.4, v1.5)
    found = Signal(list)  # Liste von TagRecord
    progress = Signal(int, int)  # eingelesen, gesamt (gesamt = -1, solange noch gesucht wird)
    finished_scan = Signal(bool)  # vollständig

    def __init__(self, paths: list[str], hidden: bool, accept=None, exclude: set[str] | None = None,
                 parent=None, kind: str | None = None) -> None:
        super().__init__(parent)
        self.kind = kind  # None = die Art mit den meisten Dateien
        self.paths = paths
        self.hidden = hidden
        self.accept = accept
        self.exclude = {os.path.normpath(p) for p in (exclude or set())}
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def _collect(self) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {k: [] for k in mp.KINDS}
        queue: list[str] = []
        for p in self.paths:
            if os.path.isdir(p) and not os.path.islink(p):
                queue.append(p)
            elif mp.kind_of(p) and os.path.isfile(p):
                found[mp.kind_of(p)].append(p)
        last = time.monotonic()
        while queue and not self._stop:
            folder = queue.pop(0)
            try:
                with os.scandir(folder) as it:
                    entries = sorted(it, key=lambda d: d.name.casefold())
            except OSError:
                continue
            for de in entries:
                if de.name.startswith(".") and not self.hidden:
                    continue
                try:
                    is_dir = de.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if self.accept is not None and not self.accept(de.name, is_dir):
                    continue
                if is_dir:
                    if not de.is_symlink() and os.path.normpath(de.path) not in self.exclude:
                        queue.append(de.path)
                else:
                    kind = mp.kind_of(de.name)
                    if kind:
                        found[kind].append(de.path)
            if time.monotonic() - last > 0.3:
                self.progress.emit(sum(len(v) for v in found.values()), -1)
                last = time.monotonic()
        return found

    def run(self) -> None:
        found = self._collect()
        counts = {k: len(v) for k, v in found.items()}
        # die Art mit den meisten Dateien; bei Gleichstand Musik vor Fotos vor Videos
        kind = self.kind or max(mp.KINDS, key=lambda k: (counts[k], -mp.KINDS.index(k)))
        self.kind_chosen.emit(kind, counts[mp.AUDIO], counts[mp.PHOTO], counts[mp.VIDEO])
        files = found[kind]
        total = len(files)
        self.progress.emit(0, total)
        batch: list[tg.TagRecord] = []
        last = time.monotonic()
        done = 0
        for path in files:
            if self._stop:
                break
            batch.append(tg.read_file(path))
            done += 1
            if time.monotonic() - last > 0.2:
                self.found.emit(batch)
                self.progress.emit(done, total)
                batch = []
                last = time.monotonic()
        if batch:
            self.found.emit(batch)
        self.progress.emit(done, total)
        self.finished_scan.emit(not self._stop)


@dataclass
class SaveJob:
    record: tg.TagRecord
    changes: dict[str, str | None]
    pictures: list[tg.Picture] | None
    new_name: str | None = None  # Tag → Dateiname (F-992)


@dataclass
class UndoJob:
    """„Letztes Speichern rückgängig“ (F-943, F-977): Name zurück, kompletten alten Tag zurückschreiben."""

    path: str  # heutiger Pfad
    old_path: str
    snap: tuple


class ReplayGainThread(QThread):
    """Misst die Titel nacheinander mit ffmpeg (v0.9.6)."""

    measured = Signal(str, object)  # Pfad, Measurement
    failed = Signal(str, str)
    progress = Signal(int, int)

    def __init__(self, paths: list[str], parent=None) -> None:
        super().__init__(parent)
        self.paths = paths
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        from . import replaygain as rg

        for n, path in enumerate(self.paths, 1):
            if self._stop:
                break
            try:
                self.measured.emit(path, rg.measure(path, stop=lambda: self._stop))
            except InterruptedError:
                break
            except Exception as exc:  # noqa: BLE001 – Fehler je Datei sammeln
                self.failed.emit(path, getattr(exc, "strerror", None) or str(exc) or type(exc).__name__)
            self.progress.emit(n, len(self.paths))


class MetaSaveThread(QThread):
    """Schreibt Tags im Hintergrund; liefert je Datei den neuen Stand oder einen Fehler (F-944)."""

    saved = Signal(object, object, object)  # Pfad vorher, neuer TagRecord, UndoJob (oder None)
    failed = Signal(str, str)  # Pfad, Grund
    progress = Signal(int, int)

    def __init__(self, jobs: list, parent=None) -> None:
        super().__init__(parent)
        self.jobs = jobs

    def _save(self, job: SaveJob):
        path = job.record.path
        snap = tg.snapshot(path, with_pictures=job.pictures is not None)
        rec = job.record
        if job.changes or job.pictures is not None:
            rec = tg.write_file(job.record, job.changes, job.pictures)
        undo = UndoJob(path, path, snap)
        if job.new_name and job.new_name != os.path.basename(path):
            target = os.path.join(os.path.dirname(path), job.new_name)
            if os.path.exists(target):
                raise FileExistsError(t("rename.err_exists_now"))
            os.rename(path, target)
            undo = UndoJob(target, path, snap)
            rec = tg.read_file(target)
        return rec, undo

    def _undo(self, job: UndoJob):
        path = job.path
        if job.old_path != path:
            if os.path.exists(job.old_path):
                raise FileExistsError(t("rename.err_exists_now"))
            os.rename(path, job.old_path)
        return tg.restore(job.old_path, job.snap), None

    def run(self) -> None:
        for n, job in enumerate(self.jobs, 1):
            before = job.record.path if isinstance(job, SaveJob) else job.path
            try:
                rec, undo = self._save(job) if isinstance(job, SaveJob) else self._undo(job)
                self.saved.emit(before, rec, undo)
            except Exception as exc:  # noqa: BLE001 – jede Datei einzeln, Fehler sammeln
                reason = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
                self.failed.emit(before, reason)
            self.progress.emit(n, len(self.jobs))


# --- Seitenleiste ---------------------------------------------------------------------------------------
class FieldBox(QComboBox):
    """Auswahlfeld mit Freitext, < beibehalten > und < entfernen > (F-921)."""

    committed = Signal(str, object)  # Feld, Wert (None = entfernen)

    def __init__(self, key: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setMaxVisibleItems(20)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(8)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._shown = ""
        self.lineEdit().editingFinished.connect(self._edited)
        self.activated.connect(self._activated)

    def show_values(self, values: list[str], enabled: bool, remove_only: bool = False) -> None:
        keep, remove = t("meta.keep"), t("meta.remove")
        self.remove_only = remove_only
        distinct: list[str] = []
        for v in values:
            if v and v not in distinct:
                distinct.append(v)
        mixed = len(set(values)) > 1
        self.blockSignals(True)
        self.clear()
        self.addItem(keep)
        self.addItem(remove)
        shown_values = distinct[:MAX_VALUES]
        for v in shown_values:
            self.addItem(v.replace("\n", " ⏎ ") if self.key != "lyrics" else v[:80], v)
        if self.key == "genre" and mp.is_audio_mode():
            for g in tg.STANDARD_GENRES:
                if g not in shown_values:
                    self.addItem(g, g)
        if self.key == "rating" and mp.is_photo_mode():
            for g in ("0", "1", "2", "3", "4", "5"):
                if g not in shown_values:
                    self.addItem(f"{g} " + "★" * int(g), g)
        self.lineEdit().setReadOnly(remove_only)
        text = keep if mixed else (values[0] if values else "")
        self.setEditText(text)
        self._shown = text
        self.setEnabled(enabled)
        self.blockSignals(False)

    def _emit(self, text: str) -> None:
        if text == self._shown:
            return
        self._shown = text
        if text == t("meta.keep"):
            return
        if text == t("meta.remove") or not text.strip():
            self.committed.emit(self.key, REMOVE)
        elif getattr(self, "remove_only", False):
            return  # Kamera, GPS …: nur entfernen (L-431)
        else:
            self.committed.emit(self.key, text)

    def _edited(self) -> None:
        self._emit(self.currentText())

    def _activated(self, index: int) -> None:
        data = self.itemData(index)
        if getattr(self, "remove_only", False) and self.itemText(index) != t("meta.remove"):
            self.setEditText(self._shown)
            return
        self._emit(data if isinstance(data, str) else self.itemText(index))


def picture_info(p: tg.Picture) -> str:
    img = QImage.fromData(QByteArray(p.data))
    dims = f"{img.width()}×{img.height()}" if not img.isNull() else "?"
    return t("meta.cover_info", mime=p.mime, dims=dims, size=format_size(len(p.data)), kind=picture_type(p.ptype))


def picture_type(ptype: int) -> str:
    key = {0: "other", 3: "front", 4: "back", 5: "leaflet", 6: "media", 8: "artist"}.get(ptype)
    return t(f"meta.pic.{key}") if key else t("meta.pic.n", n=ptype)


class CoverBox(QWidget):
    """Cover-Anzeige mit Blättern, Rechtsklick-Menü und Drag & Drop von außen (F-930 ff.)."""

    replace_requested = Signal(object)  # tg.Picture
    remove_requested = Signal(int)  # Index des angezeigten Bilds (-1 = Front-Cover)
    save_requested = Signal(object)  # tg.Picture

    SIZE = 220

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.image = QLabel(self)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setFixedSize(self.SIZE, self.SIZE)
        self.image.setStyleSheet("border: 1px solid palette(mid); background: palette(base);")
        self.info = QLabel(self)
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color: gray;")
        self.btn_prev = QToolButton(self)
        self.btn_prev.setText("◀")
        self.btn_next = QToolButton(self)
        self.btn_next.setText("▶")
        self.counter = QLabel(self)
        self.btn_prev.clicked.connect(lambda: self._step(-1))
        self.btn_next.clicked.connect(lambda: self._step(1))
        nav = QHBoxLayout()
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.counter)
        nav.addWidget(self.btn_next)
        nav.addStretch(1)
        side = QVBoxLayout()
        side.addWidget(self.info)
        side.addLayout(nav)
        side.addStretch(1)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.image)
        row.addLayout(side, 1)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.pictures: list[tg.Picture] = []
        self.index = 0
        self.mixed = False
        self.enabled_for_selection = False
        self.frame_data: bytes | None = None  # Standbild eines Videos (v1.5, L-522)
        self._frame_proc = None
        self._frame_for: tuple | None = None
        self._frame_cache: dict[tuple, bytes] = {}
        self.show_pictures([], False, False)

    def show_pictures(self, pictures: list[tg.Picture], mixed: bool, enabled: bool) -> None:
        self._stop_frame()
        self.pictures = pictures
        self.mixed = mixed
        self.enabled_for_selection = enabled
        front = next((i for i, p in enumerate(pictures) if p.ptype == tg.FRONT_COVER), 0)
        self.index = front if pictures else 0
        self._render()

    def current(self) -> tg.Picture | None:
        return self.pictures[self.index] if 0 <= self.index < len(self.pictures) and not self.mixed else None

    def show_preview(self, path: str | None, count: int) -> None:
        """Foto-Modus (L-423): Vorschaubild statt Cover, ohne Menü und Ablegen."""
        from .phototags import preview

        self._stop_frame()
        self.pictures, self.mixed, self.enabled_for_selection = [], False, False
        for w in (self.btn_prev, self.btn_next, self.counter):
            w.setVisible(False)
        self.image.setPixmap(QPixmap())
        if not path:
            self.image.setText("")
            self.info.setText("")
            return
        img = preview(path, self.SIZE - 4)
        if img is None:
            self.image.setText(t("photo.no_preview"))
        else:
            self.image.setPixmap(QPixmap.fromImage(img))
        self.info.setText(t("photo.preview_of", name=os.path.basename(path)) if count > 1 else "")

    # Videos: Poster oder Standbild (v1.5, L-522, L-523)
    def show_video(self, items: list, enabled: bool) -> None:
        covers = [it.pictures() for it in items]
        fronts = [_front(p) for p in covers]
        mixed = len({f.data if f else None for f in fronts}) > 1
        self.show_pictures(covers[0] if covers and not mixed else [], mixed, enabled)
        if items and not mixed and not self.pictures:
            self._grab(items[-1].record, len(items))

    def _stop_frame(self) -> None:
        self.frame_data = None
        self._frame_for = None
        proc, self._frame_proc = self._frame_proc, None
        if proc is not None:
            try:
                proc.finished.disconnect()
            except (RuntimeError, TypeError):
                pass
            proc.kill()
            proc.waitForFinished(500)
            proc.deleteLater()

    def _grab(self, rec, count: int) -> None:
        from PySide6.QtCore import QProcess

        from . import videotags as vt
        from .util import child_environment

        key = (rec.path, rec.mtime)
        self._frame_for = key
        self._frame_count = count
        if key in self._frame_cache:
            self._show_frame(self._frame_cache[key])
            return
        args = vt.frame_args(rec.path, rec.length, (self.SIZE - 4) * 2)
        if args is None:
            return
        proc = QProcess(self)
        proc.setProcessEnvironment(child_environment())
        proc.finished.connect(lambda *_a, pr=proc, k=key: self._frame_done(pr, k))
        self._frame_proc = proc
        proc.start(args[0], args[1:])

    def _frame_done(self, proc, key) -> None:
        if proc is self._frame_proc:
            self._frame_proc = None
        data = bytes(proc.readAllStandardOutput().data())
        proc.deleteLater()
        if not data or key != self._frame_for:
            return
        if len(self._frame_cache) > 60:
            self._frame_cache.pop(next(iter(self._frame_cache)))
        self._frame_cache[key] = data
        self._show_frame(data)

    def _show_frame(self, data: bytes) -> None:
        pm = QPixmap()
        pm.loadFromData(QByteArray(data))
        if pm.isNull():
            return
        self.frame_data = data
        self.image.setPixmap(pm.scaled(self.SIZE - 4, self.SIZE - 4, Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation))
        name = os.path.basename(self._frame_for[0]) if self._frame_for else ""
        text = t("video.frame_info")
        if getattr(self, "_frame_count", 1) > 1:
            text += "\n" + t("photo.preview_of", name=name)
        self.info.setText(text)

    def frame_picture(self) -> tg.Picture | None:
        """Das angezeigte Standbild als JPEG-Poster."""
        if not self.frame_data:
            return None
        img = QImage.fromData(QByteArray(self.frame_data))
        if img.isNull():
            return None
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "JPEG", 90)
        return tg.Picture(bytes(buf.data()), "image/jpeg", tg.FRONT_COVER, "")

    def _step(self, delta: int) -> None:
        if self.pictures:
            self.index = (self.index + delta) % len(self.pictures)
            self._render()

    def _render(self) -> None:
        many = len(self.pictures) > 1 and not self.mixed
        for w in (self.btn_prev, self.btn_next, self.counter):
            w.setVisible(many)
        self.counter.setText(f"{self.index + 1}/{len(self.pictures)}")
        pic = self.current()
        if self.mixed:
            self.image.setPixmap(QPixmap())
            self.image.setText(t("meta.cover_mixed"))
            self.info.setText("")
        elif pic is None:
            self.image.setPixmap(QPixmap())
            self.image.setText(t("meta.cover_none") if self.enabled_for_selection else "")
            self.info.setText(t("meta.cover_hint") if self.enabled_for_selection else "")
        else:
            pm = QPixmap()
            pm.loadFromData(QByteArray(pic.data))
            if pm.isNull():
                self.image.setText("?")
            else:
                self.image.setPixmap(pm.scaled(self.SIZE - 4, self.SIZE - 4, Qt.AspectRatioMode.KeepAspectRatio,
                                               Qt.TransformationMode.SmoothTransformation))
            self.info.setText(picture_info(pic))

    def _menu(self, pos) -> None:
        if not self.enabled_for_selection:
            return
        menu = QMenu(self)
        menu.addAction(t("meta.cover_replace")).triggered.connect(self.choose_file)
        if self.frame_data and mp.is_video_mode():
            def use_frame():
                pic = self.frame_picture()
                if pic is not None:
                    self.replace_requested.emit(pic)

            menu.addAction(t("video.frame_as_poster")).triggered.connect(use_frame)
        act_remove = menu.addAction(t("meta.cover_remove"))
        act_remove.setEnabled(bool(self.pictures) or self.mixed)
        act_remove.triggered.connect(lambda: self.remove_requested.emit(-1 if self.mixed else self.index))
        act_save = menu.addAction(t("meta.cover_save"))
        act_save.setEnabled(self.current() is not None)
        act_save.triggered.connect(lambda: self.save_requested.emit(self.current()))
        menu.exec(self.mapToGlobal(pos))

    def choose_file(self) -> None:
        path, _f = QFileDialog.getOpenFileName(self, t("meta.cover_replace"), os.path.expanduser("~"),
                                               t("meta.cover_filter") + " (*.jpg *.jpeg *.png)")
        if path:
            pic = picture_from_file(path)
            if pic is not None:
                self.replace_requested.emit(pic)

    # Drag & Drop von außen (F-932)
    def _drop_picture(self, mime) -> tg.Picture | None:
        for url in mime.urls():
            if url.isLocalFile():
                pic = picture_from_file(url.toLocalFile())
                if pic is not None:
                    return pic
        if mime.hasImage():
            img = mime.imageData()
            if isinstance(img, QImage) and not img.isNull():
                buf = QBuffer()
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                img.save(buf, "JPEG", 92)
                return tg.Picture(bytes(buf.data()), "image/jpeg")
        return None

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        ok = self.enabled_for_selection and (mime.hasImage() or any(
            u.isLocalFile() and u.toLocalFile().lower().endswith((".jpg", ".jpeg", ".png")) for u in mime.urls()))
        event.acceptProposedAction() if ok else event.ignore()

    def dropEvent(self, event) -> None:
        pic = self._drop_picture(event.mimeData())
        if pic is not None:
            event.acceptProposedAction()
            self.replace_requested.emit(pic)


def picture_from_file(path: str) -> tg.Picture | None:
    """Bilddatei unverändert übernehmen (F-931)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif data[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    else:
        return None
    return tg.Picture(data, mime, tg.FRONT_COVER, "")


class KindSwitch(QWidget):
    """Umschalter „Musik | Fotos | Videos“, wenn ein Ordner mehrere Arten enthält (L-421, L-520)."""

    changed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QButtonGroup

        self.buttons = {k: QPushButton(self) for k in mp.KINDS}
        group = QButtonGroup(self)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(0)
        for kind, b in self.buttons.items():
            b.setCheckable(True)
            group.addButton(b)
            lay.addWidget(b, 1)
            b.clicked.connect(lambda _c=False, k=kind: self.changed.emit(k))
        group.setExclusive(True)
        self.btn_audio, self.btn_photo, self.btn_video = (self.buttons[k] for k in mp.KINDS)

    def select(self, kind: str) -> None:
        self.buttons.get(kind, self.btn_audio).setChecked(True)

    def set_counts(self, kind: str, audio: int, photos: int, videos: int = 0) -> None:
        counts = {mp.AUDIO: audio, mp.PHOTO: photos, mp.VIDEO: videos}
        keys = {mp.AUDIO: "photo.switch_audio", mp.PHOTO: "photo.switch_photo", mp.VIDEO: "video.switch_video"}
        for k, b in self.buttons.items():
            b.setText(t(keys[k], n=counts[k]))
            b.setVisible(counts[k] > 0 or k == kind)
        self.select(kind)
        self.setVisible(sum(1 for n in counts.values() if n > 0) > 1)


class MetaPane(ToolPane):
    """Seitenleiste des Meta-Wizards (F-920 ff.)."""

    save_clicked = Signal()
    discard_clicked = Signal()
    undo_clicked = Signal()
    stop_clicked = Signal()
    field_committed = Signal(str, object)
    cover_replace = Signal(object)
    cover_remove = Signal(int)
    cover_save = Signal(object)
    layout_changed = Signal()
    convert_requested = Signal(str)  # F-990
    long_text_requested = Signal(str)  # F-980

    def __init__(self, parent=None) -> None:
        super().__init__(t("meta.title"), parent)
        self.layout_keys: list[str] = mp.default_sidebar()
        self.boxes: dict[str, FieldBox] = {}
        self.rows: dict[str, QWidget] = {}
        self.wav_hint = QLabel(t("meta.wav_hint"), self)
        self.wav_hint.setWordWrap(True)
        self.wav_hint.setStyleSheet("color: gray;")
        self.wav_hint.hide()
        self.photo_hint = QLabel(self)  # HEIC ohne exiftool, RAW (v1.4)
        self.photo_hint.setWordWrap(True)
        self.photo_hint.setStyleSheet("color: gray;")
        self.photo_hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.photo_hint.setTextFormat(Qt.TextFormat.RichText)
        self.photo_hint.hide()
        self.kind_switch = KindSwitch(self)  # „Musik | Fotos“ (L-421)
        self.kind_switch.hide()
        self.cover = CoverBox(self)
        self.cover.replace_requested.connect(self.cover_replace)
        self.cover.remove_requested.connect(self.cover_remove)
        self.cover.save_requested.connect(self.cover_save)
        self.fields_host = QWidget(self.inner)
        self.fields_layout = QVBoxLayout(self.fields_host)
        self.fields_layout.setContentsMargins(0, 0, 0, 0)
        self.inner_layout.addWidget(self.kind_switch)
        self.inner_layout.addWidget(self.fields_host)
        self.inner_layout.addWidget(self.wav_hint)
        self.inner_layout.addWidget(self.photo_hint)
        from PySide6.QtWidgets import QGroupBox

        from . import convert as cv

        conv = QGroupBox(t("conv.group"), self.inner)
        cl = QVBoxLayout(conv)
        self.convert_buttons = {}
        for kind in cv.TOOLS:
            b = QPushButton(t(f"conv.{kind}"), conv)
            b.clicked.connect(lambda _c=False, k=kind: self.convert_requested.emit(k))
            cl.addWidget(b)
            self.convert_buttons[kind] = b
        self.apply_profile_buttons()
        self.inner_layout.addWidget(conv)
        self.inner.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.inner.customContextMenuRequested.connect(self._layout_menu)

        self.btn_save = QPushButton(t("meta.save"), self)
        self.btn_save.setDefault(True)
        self.btn_discard = QPushButton(t("meta.discard"), self)
        self.btn_undo = QPushButton(t("meta.undo"), self)
        self.btn_stop = QPushButton(t("search.stop"), self)
        self.btn_save.clicked.connect(self.save_clicked)
        self.btn_discard.clicked.connect(self.discard_clicked)
        self.btn_undo.clicked.connect(self.undo_clicked)
        self.btn_stop.clicked.connect(self.stop_clicked)
        top = QHBoxLayout()
        top.addWidget(self.btn_save, 1)
        top.addWidget(self.btn_discard, 1)
        self.layout().insertLayout(self.layout().count() - 1, top)
        self.buttons.addWidget(self.btn_undo, 1)
        self.buttons.addWidget(self.btn_stop, 1)
        self.finish_layout()
        self.btn_stop.hide()
        self.btn_undo.setEnabled(False)
        self.set_layout(self.layout_keys)

    def apply_profile_buttons(self) -> None:
        """Konverter passend zur Art zeigen (L-440, L-441)."""
        shown = set(mp.tools())
        for kind, b in self.convert_buttons.items():
            b.setVisible(kind in shown)

    # Aufbau
    def set_layout(self, keys: list[str]) -> None:
        keys = [k for k in keys if k == COVER or k in mp.fields() or k.startswith(tg.EXTRA)]
        if not keys:
            keys = mp.default_sidebar()
        self.layout_keys = list(dict.fromkeys(keys))
        while self.fields_layout.count():
            w = self.fields_layout.takeAt(0).widget()
            if w is not None and w is not self.cover:
                w.hide()  # sofort weg, nicht erst beim Löschen
                w.setParent(None)
                w.deleteLater()
        self.cover.setParent(None)
        self.boxes, self.rows = {}, {}
        self.map_link = None
        for key in self.layout_keys:
            if key == COVER:
                self.cover.setParent(self.fields_host)
                self.fields_layout.addWidget(self.cover)
                self.cover.show()
                self.rows[COVER] = self.cover
                continue
            row = QWidget(self.fields_host)
            lay = QVBoxLayout(row)
            lay.setContentsMargins(0, 2, 0, 2)
            lay.setSpacing(1)
            if key == "gpslat":  # Link zur Karte (L-433)
                head = QHBoxLayout()
                head.addWidget(QLabel(column_title(key), row))
                head.addStretch(1)
                self.map_link = QLabel(row)
                self.map_link.setOpenExternalLinks(True)
                head.addWidget(self.map_link)
                lay.addLayout(head)
            else:
                lay.addWidget(QLabel(column_title(key), row))
            box = FieldBox(key, row)
            box.committed.connect(self.field_committed)
            if key in ("lyrics", "comment", "description"):  # F-980: langer Text
                line = QHBoxLayout()
                line.addWidget(box, 1)
                more = QToolButton(row)
                more.setText("…")
                more.setToolTip(t("meta.long_text"))
                more.clicked.connect(lambda _c=False, k=key: self.long_text_requested.emit(k))
                line.addWidget(more)
                lay.addLayout(line)
            else:
                lay.addWidget(box)
            row.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            row.customContextMenuRequested.connect(lambda pos, k=key, r=row: self._layout_menu(pos, k, r))
            self.fields_layout.addWidget(row)
            self.boxes[key] = box
            self.rows[key] = row

    def _layout_menu(self, pos, key: str | None = None, widget=None) -> None:
        """Seitenleiste anpassen (F-926)."""
        menu = QMenu(self)
        if key is not None:
            i = self.layout_keys.index(key)
            up = menu.addAction(t("meta.field_up"))
            up.setEnabled(i > 0)
            up.triggered.connect(lambda: self._move(key, -1))
            down = menu.addAction(t("meta.field_down"))
            down.setEnabled(i < len(self.layout_keys) - 1)
            down.triggered.connect(lambda: self._move(key, 1))
            menu.addAction(t("meta.field_remove", name=column_title(key))).triggered.connect(lambda: self._remove(key))
            menu.addSeparator()
        add = menu.addMenu(t("meta.field_add"))
        for k in (*mp.fields(), COVER):
            if k not in self.layout_keys:
                add.addAction(column_title(k)).triggered.connect(lambda _c=False, kk=k: self._add(kk))
        extra = getattr(self, "extra_keys", {})
        if extra:
            more = add.addMenu(t("meta.more_fields"))
            for k, label in extra.items():
                if k not in self.layout_keys:
                    more.addAction(label).triggered.connect(lambda _c=False, kk=k: self._add(kk))
        menu.addSeparator()
        menu.addAction(t("meta.field_default")).triggered.connect(lambda: self._apply(mp.default_sidebar()))
        src = widget if widget is not None else self.inner
        menu.exec(src.mapToGlobal(pos))

    def _apply(self, keys: list[str]) -> None:
        self.set_layout(keys)
        self.layout_changed.emit()

    def _move(self, key: str, delta: int) -> None:
        keys = list(self.layout_keys)
        i = keys.index(key)
        j = max(0, min(len(keys) - 1, i + delta))
        keys[i], keys[j] = keys[j], keys[i]
        self._apply(keys)

    def _remove(self, key: str) -> None:
        self._apply([k for k in self.layout_keys if k != key])

    def _add(self, key: str) -> None:
        self._apply(self.layout_keys + [key])

    # Anzeige der Auswahl
    def show_selection(self, items: list[MetaItem]) -> None:
        enabled = bool(items)
        for key, box in self.boxes.items():
            values = [it.value(key) for it in items]
            box.show_values(values, enabled and not all(it.readonly(key) for it in items),
                            remove_only=bool(items) and all(it.remove_only(key) for it in items))
        if COVER in self.rows:
            if mp.is_photo_mode():
                self.cover.show_preview(items[-1].record.path if items else None, len(items))
            elif mp.is_video_mode():
                self.cover.show_video(items, enabled and not all(it.readonly("title") for it in items))
            else:
                covers = [it.pictures() for it in items]
                fronts = [_front(p) for p in covers]
                mixed = len({f.data if f else None for f in fronts}) > 1
                self.cover.show_pictures(covers[0] if covers and not mixed else [], mixed, enabled)
        if getattr(self, "map_link", None) is not None and "gpslat" in self.boxes:
            from .phototags import map_url

            url = map_url(items[-1].record) if len(items) == 1 else None
            self.map_link.setText(f'<a href="{url}">{t("photo.show_map")}</a>' if url else "")
        self.wav_hint.setVisible(any(it.record.codec == "WAV" for it in items))
        hint = ""
        if mp.is_photo_mode() and items:
            from . import phototags as ph

            if any(ph.is_heif(it.record.path) for it in items) and not ph.exiftool():
                hint = t("photo.heic_hint")
            elif any(ph.is_raw(it.record.path) for it in items):
                hint = t("photo.raw_hint")
        if mp.is_video_mode() and items:
            hint = video_hint([it.record for it in items])
        if hint:
            import html

            text = html.escape(hint)
            if hint not in (t("photo.raw_hint"), t("video.readonly_hint")):  # fehlendes Programm (L-552)
                text += f' <a href="tools">{html.escape(t("help.tools_link"))}</a>'
            hint = text
        self.photo_hint.setText(hint)
        self.photo_hint.setVisible(bool(hint))

    def update_state(self, scanning: bool, saving: bool, has_changes: bool, can_undo: bool) -> None:
        """Knöpfe passend zum Zustand (F-925): Stopp nur beim Einlesen, Speichern nur mit Änderungen."""
        self.btn_stop.setVisible(scanning)
        self.btn_close.setVisible(not scanning)
        busy = scanning or saving
        self.btn_save.setEnabled(has_changes and not busy)
        self.btn_discard.setEnabled(has_changes and not busy)
        self.btn_undo.setEnabled(can_undo and not busy)
        self.fields_host.setEnabled(not saving)


def video_hint(records) -> str:
    """Hinweis, welches Zusatzprogramm fehlt bzw. warum Felder grau sind (L-511, L-532, L-533, L-552)."""
    from . import videotags as vt

    wrong = [r for r in records if r.wrong_ext]
    if wrong:  # Endung passt nicht zum Inhalt (v1.5.2)
        r = wrong[0]
        text = (t("video.wrong_ext", name=r.name, real=r.wrong_ext) if len(wrong) == 1
                else t("video.wrong_ext_many", n=len(wrong)))
        more = video_hint([r for r in records if not r.wrong_ext] + [_copy_ok(r) for r in wrong])
        return text + (" " + more if more else "")
    if not vt.ffprobe():
        return t("video.ffmpeg_hint")
    if any(r.kind == vt.KIND_MKV for r in records) and not vt.mkvtoolnix():
        return t("video.mkv_hint")
    if any(r.kind == vt.KIND_RO for r in records):
        return t("video.readonly_hint")
    if any(r.kind == vt.KIND_MP4 for r in records) and not vt.exiftool():
        return t("video.exiftool_hint")
    if any(r.kind == vt.KIND_ASF for r in records):
        return t("video.wmv_hint")
    return ""


def _copy_ok(rec):
    import copy

    r = copy.copy(rec)
    r.wrong_ext = ""
    return r


def _front(pictures: list[tg.Picture]) -> tg.Picture | None:
    for p in pictures:
        if p.ptype == tg.FRONT_COVER:
            return p
    return pictures[0] if pictures else None


def replace_front(pictures: list[tg.Picture], new: tg.Picture, index: int | None = None) -> list[tg.Picture]:
    """Ersetzt das angezeigte Bild bzw. das Front-Cover; andere Bilder bleiben (F-930)."""
    pics = list(pictures)
    if index is not None and 0 <= index < len(pics):
        old = pics[index]
        pics[index] = tg.Picture(new.data, new.mime, old.ptype, old.desc)
        return pics
    for i, p in enumerate(pics):
        if p.ptype == tg.FRONT_COVER:
            pics[i] = tg.Picture(new.data, new.mime, tg.FRONT_COVER, p.desc)
            return pics
    return [tg.Picture(new.data, new.mime, tg.FRONT_COVER, "")] + pics


def remove_shown(pictures: list[tg.Picture], index: int | None = None) -> list[tg.Picture]:
    pics = list(pictures)
    if index is not None and 0 <= index < len(pics):
        del pics[index]
        return pics
    front = _front(pics)
    return [p for p in pics if p is not front]
