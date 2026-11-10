"""Inhalt eines Ordners als Tabelle (Name, Größe, Geändert, Typ)."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import (
    QAbstractTableModel,
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from .i18n import t
from .icons import IconProvider
from .util import format_size

# Die Nummern sind fest (gespeicherte Spaltenzustände bauen darauf auf);
# Reihenfolge und Sichtbarkeit regelt der Spaltenkopf der Ansicht.
(COL_NAME, COL_SIZE, COL_DATE, COL_TYPE, COL_EXT, COL_PERM_NUM, COL_PERM_STR, COL_OWNER, COL_GROUP, COL_NAME_STEM,
 COL_CREATED) = range(11)
COLUMN_KEYS = ("column.name", "column.size", "column.date", "column.type", "column.ext",
               "column.perm_num", "column.perm_str", "column.owner", "column.group", "column.name_stem",
               "column.created")
COLUMN_COUNT = len(COLUMN_KEYS)
DEFAULT_HIDDEN = (COL_EXT, COL_PERM_NUM, COL_PERM_STR, COL_OWNER, COL_GROUP, COL_NAME_STEM, COL_CREATED)
# Reihenfolge im Spaltenmenü (F-511, F-520)
MENU_ORDER = (COL_NAME, COL_NAME_STEM, COL_EXT, COL_SIZE, COL_CREATED, COL_DATE, COL_TYPE,
              COL_PERM_NUM, COL_PERM_STR, COL_OWNER, COL_GROUP)
NAME_COLUMNS = (COL_NAME, COL_NAME_STEM)
# Im Papierkorb zeigen zwei Spalten etwas anderes an
TRASH_HEADER_KEYS = {COL_DATE: "column.deleted", COL_TYPE: "column.origin"}

_owner_cache: dict[int, str] = {}
_group_cache: dict[int, str] = {}


def owner_name(uid: int) -> str:
    if uid not in _owner_cache:
        try:
            import pwd

            _owner_cache[uid] = pwd.getpwuid(uid).pw_name
        except (ImportError, KeyError):
            _owner_cache[uid] = str(uid)
    return _owner_cache[uid]


def group_name(gid: int) -> str:
    if gid not in _group_cache:
        try:
            import grp

            _group_cache[gid] = grp.getgrgid(gid).gr_name
        except (ImportError, KeyError):
            _group_cache[gid] = str(gid)
    return _group_cache[gid]


def stem_of(name: str, is_dir: bool) -> str:
    """Name ohne Endung; Ordner und Dateien wie '.bashrc' bleiben vollständig."""
    if is_dir:
        return name
    stem, ext = os.path.splitext(name)
    return stem if ext else name


def extension_of(name: str, is_dir: bool) -> str:
    if is_dir:
        return ""
    ext = os.path.splitext(name)[1]
    return ext.lower() if ext else ""


def perm_number(mode: int) -> str:
    return f"{stat.S_IMODE(mode):03o}"


def perm_string(mode: int) -> str:
    return stat.filemode(mode)

EntryRole = Qt.ItemDataRole.UserRole + 1


@dataclass
class Entry:
    name: str
    path: str
    is_dir: bool
    size: int = 0
    mtime: float = 0.0
    is_link: bool = False
    is_parent: bool = False
    hidden: bool = False
    type_text: str = ""
    mode: int = 0
    uid: int = -1
    gid: int = -1
    # nur im Papierkorb
    original_path: str = ""
    info_path: str = ""
    btime: float | None = None  # Erstellungszeit, wird erst bei Bedarf ermittelt (-1 = unbekannt)

    def birth_time(self) -> float:
        """Erstellungszeit in Sekunden oder -1, wenn das Dateisystem sie nicht liefert (F-513)."""
        if self.btime is None:
            self.btime = birth_time_of(self.path)
        return self.btime


def birth_time_of(path: str) -> float:
    try:
        st = os.stat(path)
        if hasattr(st, "st_birthtime"):
            return float(st.st_birthtime)
    except OSError:
        return -1.0
    from PySide6.QtCore import QFileInfo

    dt = QFileInfo(path).birthTime()  # Linux: statx()
    return dt.toSecsSinceEpoch() if dt.isValid() else -1.0


def scan_directory(path: str, show_hidden: bool, icons: IconProvider | None) -> list[Entry]:
    """Liest einen Ordner ein. Wirft OSError, wenn er nicht lesbar ist."""
    entries: list[Entry] = []
    with os.scandir(path) as it:
        for de in it:
            hidden = de.name.startswith(".")
            if hidden and not show_hidden:
                continue
            try:
                is_link = de.is_symlink()
                try:
                    st = de.stat(follow_symlinks=True)
                    is_dir = stat.S_ISDIR(st.st_mode)
                except OSError:
                    # Verwaister Link: Daten des Links selbst anzeigen
                    st = de.stat(follow_symlinks=False)
                    is_dir = False
            except OSError:
                continue
            entry = Entry(
                name=de.name,
                path=de.path,
                is_dir=is_dir,
                size=0 if is_dir else st.st_size,
                mtime=st.st_mtime,
                is_link=is_link,
                hidden=hidden,
                mode=st.st_mode,
                uid=st.st_uid,
                gid=st.st_gid,
            )
            if is_dir:
                entry.type_text = t("type.folder")
            elif icons is not None:
                entry.type_text = icons.type_text(de.path)
            entries.append(entry)
    return entries


def entry_from_path(path: str, icons: IconProvider | None) -> Entry | None:
    """Ein Eintrag für einen beliebigen Pfad (z. B. Suchtreffer)."""
    name = os.path.basename(path.rstrip(os.sep)) or path
    try:
        is_link = os.path.islink(path)
        try:
            st = os.stat(path)
            is_dir = stat.S_ISDIR(st.st_mode)
        except OSError:
            st = os.lstat(path)
            is_dir = False
    except OSError:
        return None
    entry = Entry(name=name, path=path, is_dir=is_dir, size=0 if is_dir else st.st_size, mtime=st.st_mtime,
                  is_link=is_link, hidden=name.startswith("."), mode=st.st_mode, uid=st.st_uid, gid=st.st_gid)
    if is_dir:
        entry.type_text = t("type.folder")
    elif icons is not None:
        entry.type_text = icons.type_text(path)
    return entry


class FileListModel(QAbstractTableModel):
    rename_failed = Signal(str)  # Fehlermeldung
    renamed = Signal(str)  # neuer Name

    def __init__(self, icons: IconProvider, parent=None) -> None:
        super().__init__(parent)
        self._icons = icons
        self._dir = ""
        self._entries: list[Entry] = []
        self._show_hidden = False
        self._dirs_first = True
        self._show_parent = True
        self.alignments: dict[int, str] = {}  # Spalte → left/center/right (F-843)
        self.accept = None  # Filter (F-600): Funktion (name, is_dir) → bool, None = alles zeigen
        self.total_count = 0  # Einträge ohne Filter (ohne „..“)
        self._sort_col = COL_NAME
        self._sort_order = Qt.SortOrder.AscendingOrder
        self.trash_mode = False
        self.search_base: str | None = None  # Suchergebnisse (F-817): Startordner der Suche
        self.icon_column = COL_NAME  # Spalte, in der das Symbol steht (erste sichtbare Namensspalte)

    # --- Laden ---------------------------------------------------------------
    @property
    def directory(self) -> str:
        return self._dir

    def set_options(self, show_hidden: bool, dirs_first: bool = True, show_parent: bool = True) -> None:
        self._show_hidden = show_hidden
        self._dirs_first = dirs_first
        self._show_parent = show_parent

    def load_trash(self, items, uri: str) -> None:
        """Inhalt des Papierkorbs anzeigen (F-405)."""
        entries = []
        for it in items:
            e = Entry(name=it.name, path=it.file_path, is_dir=it.is_dir, size=it.size, mtime=it.deleted,
                      mode=it.mode, uid=it.uid, gid=it.gid, original_path=it.original_path, info_path=it.info_path)
            e.type_text = it.original_dir
            entries.append(e)
        self.beginResetModel()
        self.search_base = None
        self.trash_mode = True
        self._dir = uri
        self._entries = entries
        self._sort_entries()
        self.endResetModel()
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, COLUMN_COUNT - 1)

    # --- Suchergebnisse (F-817) ---------------------------------------------------------
    def load_results(self, base: str, entries: list[Entry]) -> None:
        """Ergebnisliste statt Ordnerinhalt; Spalte „Typ“ zeigt den Ordner relativ zur Basis."""
        for e in entries:
            self._set_folder_text(base, e)
        self.beginResetModel()
        self.trash_mode = False
        self.search_base = base
        self._dir = base
        self._entries = list(entries)
        self.total_count = len(entries)
        self._sort_entries()
        self.endResetModel()
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, COLUMN_COUNT - 1)

    @staticmethod
    def _set_folder_text(base: str, e: Entry) -> None:
        rel = os.path.relpath(os.path.dirname(e.path), base)
        e.type_text = "." if rel == "." else rel

    def add_results(self, entries: list[Entry]) -> None:
        if not entries or self.search_base is None:
            return
        for e in entries:
            self._set_folder_text(self.search_base, e)
        first = len(self._entries)
        self.beginInsertRows(QModelIndex(), first, first + len(entries) - 1)
        self._entries.extend(entries)
        self.total_count = len(self._entries)
        self.endInsertRows()

    def resort(self) -> None:
        self.layoutAboutToBeChanged.emit()
        self._sort_entries()
        self.layoutChanged.emit()

    def refresh_results(self) -> None:
        """Nach Dateioperationen: verschwundene Treffer entfernen, übrige neu einlesen."""
        if self.search_base is None:
            return
        fresh = []
        for e in self._entries:
            n = entry_from_path(e.path, self._icons)
            if n is not None:
                fresh.append(n)
        self.load_results(self.search_base, fresh)

    def load(self, path: str) -> None:
        self.search_base = None
        entries = scan_directory(path, self._show_hidden, self._icons)
        self.total_count = len(entries)
        if self.accept is not None:
            entries = [e for e in entries if self.accept(e.name, e.is_dir)]
        was_trash = self.trash_mode
        self.beginResetModel()
        self.trash_mode = False
        self._dir = path
        self._entries = entries
        self._sort_entries()
        p = Path(path)
        if self._show_parent and p.parent != p:  # nicht an der Wurzel (/ bzw. C:\)
            self._entries.insert(0, Entry(name="..", path=str(p.parent), is_dir=True, is_parent=True))
        self.endResetModel()
        if was_trash:
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, COLUMN_COUNT - 1)

    # --- Sortierung ------------------------------------------------------------
    @property
    def sort_column(self) -> int:
        return self._sort_col

    @property
    def sort_order(self) -> Qt.SortOrder:
        return self._sort_order

    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        self._sort_col = column
        self._sort_order = order
        self.layoutAboutToBeChanged.emit()
        old = [QPersistentModelIndex(self.index(r, c)) for r in range(len(self._entries)) for c in range(COLUMN_COUNT)]
        old_entries = list(self._entries)
        parent_entry = [e for e in self._entries if e.is_parent]
        self._entries = [e for e in self._entries if not e.is_parent]
        self._sort_entries()
        self._entries = parent_entry + self._entries
        pos = {id(e): i for i, e in enumerate(self._entries)}
        new = [self.index(pos[id(old_entries[p.row()])], p.column()) for p in old]
        self.changePersistentIndexList([QModelIndex(p) for p in old], new)
        self.layoutChanged.emit()

    def _sort_entries(self) -> None:
        col = self._sort_col
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder

        def name_key(e: Entry):
            return (e.name.casefold(), e.name)

        if col == COL_SIZE:
            key = lambda e: (e.size, name_key(e))  # noqa: E731
        elif col == COL_DATE:
            key = lambda e: (e.mtime, name_key(e))  # noqa: E731
        elif col == COL_TYPE:
            key = lambda e: (e.type_text.casefold(), name_key(e))  # noqa: E731
        elif col == COL_CREATED:
            key = lambda e: (e.birth_time(), name_key(e))  # noqa: E731
        elif col == COL_EXT:
            key = lambda e: (extension_of(e.name, e.is_dir), name_key(e))  # noqa: E731
        elif col == COL_NAME_STEM:
            key = lambda e: (stem_of(e.name, e.is_dir).casefold(), name_key(e))  # noqa: E731
        elif col in (COL_PERM_NUM, COL_PERM_STR):
            key = lambda e: (stat.S_IMODE(e.mode), name_key(e))  # noqa: E731
        elif col == COL_OWNER:
            key = lambda e: (owner_name(e.uid).casefold(), name_key(e))  # noqa: E731
        elif col == COL_GROUP:
            key = lambda e: (group_name(e.gid).casefold(), name_key(e))  # noqa: E731
        else:
            key = name_key
        if self._dirs_first:
            dirs = sorted((e for e in self._entries if e.is_dir), key=key, reverse=reverse)
            files = sorted((e for e in self._entries if not e.is_dir), key=key, reverse=reverse)
            # Ordner nach Größe zu sortieren ergibt keinen Sinn: dann nach Name
            if col == COL_SIZE:
                dirs = sorted(dirs, key=name_key, reverse=reverse)
            self._entries = dirs + files
        else:
            self._entries.sort(key=key, reverse=reverse)

    # --- Zugriff -----------------------------------------------------------------
    def entry(self, row: int) -> Entry | None:
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def entries(self) -> list[Entry]:
        return list(self._entries)

    def row_of(self, name: str) -> int:
        for i, e in enumerate(self._entries):
            if e.name == name:
                return i
        return -1

    # --- Qt-Modell ---------------------------------------------------------------
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._entries)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else COLUMN_COUNT

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            if self.trash_mode and section in TRASH_HEADER_KEYS:
                return t(TRASH_HEADER_KEYS[section])
            if self.search_base is not None and section == COL_TYPE:
                return t("column.folder")
            return t(COLUMN_KEYS[section])
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.TextAlignmentRole:
            return self.alignment(section)
        return None

    def alignment(self, col: int) -> int:
        """Ausrichtung der Spalte für Kopf und Inhalt (F-843)."""
        mode = self.alignments.get(col, "right" if col == COL_SIZE else "left")
        h = {"left": Qt.AlignmentFlag.AlignLeft, "center": Qt.AlignmentFlag.AlignHCenter,
             "right": Qt.AlignmentFlag.AlignRight}[mode]
        return int(h | Qt.AlignmentFlag.AlignVCenter)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self._entries[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == COL_NAME:
                return e.name
            if e.is_parent:
                return e.name if col == COL_NAME_STEM else ""  # F-960: „..“ auch ohne Endung
            if col == COL_SIZE:
                return "" if e.is_dir else format_size(e.size)
            if col == COL_DATE:
                return datetime.fromtimestamp(e.mtime).strftime("%d.%m.%Y %H:%M")
            if col == COL_TYPE:
                return e.type_text
            if col == COL_EXT:
                return extension_of(e.name, e.is_dir)
            if col == COL_PERM_NUM:
                return perm_number(e.mode)
            if col == COL_PERM_STR:
                return perm_string(e.mode)
            if col == COL_OWNER:
                return owner_name(e.uid)
            if col == COL_GROUP:
                return group_name(e.gid)
            if col == COL_NAME_STEM:
                return stem_of(e.name, e.is_dir)
            if col == COL_CREATED:
                if self.trash_mode:
                    return ""
                bt = e.birth_time()
                return datetime.fromtimestamp(bt).strftime("%d.%m.%Y %H:%M") if bt >= 0 else ""
        elif role == Qt.ItemDataRole.EditRole and col == COL_NAME:
            return e.name
        elif role == Qt.ItemDataRole.EditRole and col == COL_NAME_STEM:
            return stem_of(e.name, e.is_dir)
        elif role == Qt.ItemDataRole.DecorationRole and col == self.icon_column:
            if e.is_parent:
                return self._icons.parent_entry()
            if e.is_dir:
                return self._icons.folder() if self.trash_mode else self._icons.dir_icon(e.path)
            return self._icons.for_file(e.name if self.trash_mode else e.path)
        elif role == Qt.ItemDataRole.FontRole and col in (COL_PERM_NUM, COL_PERM_STR):
            from PySide6.QtGui import QFontDatabase

            return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            return self.alignment(col)
        elif role == Qt.ItemDataRole.ForegroundRole and e.hidden:
            return QApplication.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        elif role == Qt.ItemDataRole.ToolTipRole and not e.is_parent:
            # F-430 ff.: die jeweils andere Darstellung als Infotext
            if col == COL_OWNER:
                return t("tooltip.uid", uid=e.uid)
            if col == COL_GROUP:
                return t("tooltip.gid", gid=e.gid)
            if col == COL_PERM_NUM:
                return perm_string(e.mode)
            if col == COL_PERM_STR:
                return perm_number(e.mode)
            if self.trash_mode and col in NAME_COLUMNS:
                return t("tooltip.trash_origin", path=e.original_path)
            if col in NAME_COLUMNS and e.is_link:
                try:
                    return t("tooltip.link_target", target=os.readlink(e.path))
                except OSError:
                    return None
        elif role == EntryRole:
            return e
        return None

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        e = self._entries[index.row()]
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if not e.is_parent:
            flags |= Qt.ItemFlag.ItemIsDragEnabled
            if index.column() in NAME_COLUMNS and not self.trash_mode:
                flags |= Qt.ItemFlag.ItemIsEditable
        if e.is_dir and not self.trash_mode:
            flags |= Qt.ItemFlag.ItemIsDropEnabled
        return flags

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or index.column() not in NAME_COLUMNS:
            return False
        if self.trash_mode:
            return False
        e = self._entries[index.row()]
        new_name = str(value).strip()
        if index.column() == COL_NAME_STEM and new_name:
            # Umbenennen in der Spalte „ohne Endung“: die Endung bleibt erhalten
            ext = os.path.splitext(e.name)[1] if not e.is_dir else ""
            new_name += ext
        if e.is_parent or not new_name or new_name == e.name:
            return False
        if "/" in new_name or new_name in (".", ".."):
            self.rename_failed.emit(t("error.invalid_name", name=new_name))
            return False
        new_path = os.path.join(os.path.dirname(e.path), new_name)
        if os.path.lexists(new_path) and os.path.normcase(new_name) != os.path.normcase(e.name):
            self.rename_failed.emit(t("error.name_exists", name=new_name))
            return False
        try:
            os.rename(e.path, new_path)
        except OSError as exc:
            self.rename_failed.emit(t("error.rename_failed", name=e.name, reason=exc.strerror or str(exc)))
            return False
        e.name = new_name
        e.path = new_path
        self.dataChanged.emit(index, index)
        self.renamed.emit(new_name)
        return True

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    def supportedDropActions(self):
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction | Qt.DropAction.LinkAction

    def mimeTypes(self) -> list[str]:
        return ["text/uri-list"]

    def mimeData(self, indexes) -> QMimeData:
        rows = sorted({i.row() for i in indexes})
        urls = [QUrl.fromLocalFile(self._entries[r].path) for r in rows if not self._entries[r].is_parent]
        md = QMimeData()
        md.setUrls(urls)
        return md
