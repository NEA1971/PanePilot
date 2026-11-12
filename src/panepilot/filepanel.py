"""Ein Dateipanel: Pfadleiste, Dateiliste und Statuszeile."""

from __future__ import annotations

import os
import sys
import shutil

from PySide6.QtCore import (
    QDir,
    QItemSelectionModel,
    QModelIndex,
    QPoint,
    Qt,
    QTimer,
    QFileSystemWatcher,
    Signal,
)
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCompleter,
    QFileSystemModel,
    QFrame,
    QHeaderView,
    QLabel,
    QLineEdit,
    QStyledItemDelegate,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from .filemodel import (COL_CREATED, COL_DATE, COL_NAME, COL_NAME_STEM, COL_SIZE, COL_TYPE, COLUMN_COUNT, COLUMN_KEYS,
                        DEFAULT_HIDDEN, NAME_COLUMNS, REMOTE_MIME, Entry, FileListModel)
from .remotefs import is_remote_uri
from .trash import TRASH_URI, is_trash_uri
from .i18n import t
from .icons import IconProvider
from .util import format_size, nearest_existing_dir

HISTORY_LIMIT = 50


class RenameDelegate(QStyledItemDelegate):
    """Beim Umbenennen nur den Namensteil vor der Endung markieren."""

    def setEditorData(self, editor, index):
        super().setEditorData(editor, index)
        if isinstance(editor, QLineEdit):
            name = editor.text()
            entry = index.data(Qt.ItemDataRole.UserRole + 1)
            stem_len = len(name)
            if entry is not None and not entry.is_dir:
                dot = name.rfind(".")
                if dot > 0:
                    stem_len = dot
            QTimer.singleShot(0, lambda: editor.setSelection(0, stem_len))


class FileView(QTreeView):
    """Dateiliste mit Drag & Drop für Dateien."""

    drop_requested = Signal(list, str, object)  # Pfade, Zielordner, Qt.DropAction
    remote_drop_requested = Signal(object, str, object)  # {side, paths, dirs} aus einem Server-Fenster (v1.3)
    focus_entered = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setRootIsDecorated(False)
        self.setItemsExpandable(False)
        self.setUniformRowHeights(True)
        self.setAllColumnsShowFocus(True)
        self.setSortingEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setItemDelegate(RenameDelegate(self))

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focus_entered.emit()

    # --- Ziehen ---------------------------------------------------------------------
    def startDrag(self, supported_actions) -> None:
        model = self.model()
        rows = sorted({i.row() for i in self.selectionModel().selectedRows()})
        indexes = [model.index(r, model.icon_column) for r in rows]
        md = model.mimeData(indexes)
        if not md.urls():
            return
        drag = QDrag(self)
        drag.setMimeData(md)
        icon = indexes[0].data(Qt.ItemDataRole.DecorationRole) if indexes else None
        if icon is not None:
            drag.setPixmap(icon.pixmap(32, 32))
        # Standard: Kopieren; mit Umschalttaste: Verschieben (übernimmt Qt samt Mauszeiger).
        # Aus dem Papierkorb heraus nur Kopieren (F-409).
        actions = Qt.DropAction.CopyAction if model.trash_mode else Qt.DropAction.CopyAction | Qt.DropAction.MoveAction
        drag.exec(actions, Qt.DropAction.CopyAction)

    # --- Ablegen ---------------------------------------------------------------------
    def _target_dir(self, pos: QPoint, sources: list[str]) -> str | None:
        model: FileListModel = self.model()
        if model.trash_mode:
            return TRASH_URI  # Ablegen im Papierkorb = in den Papierkorb verschieben
        index = self.indexAt(pos)
        if index.isValid():
            entry = model.entry(index.row())
            if entry is not None and entry.is_dir and entry.path not in sources:
                return entry.path
        return model.directory or None

    @staticmethod
    def _local_paths(event) -> list[str]:
        md = event.mimeData()
        if not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile()]

    @staticmethod
    def _choose_action(event):
        possible = event.possibleActions()
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier and possible & Qt.DropAction.MoveAction:
            return Qt.DropAction.MoveAction
        if possible & Qt.DropAction.CopyAction:
            return Qt.DropAction.CopyAction
        if possible & Qt.DropAction.MoveAction:
            return Qt.DropAction.MoveAction
        return None

    @staticmethod
    def _remote_payload(event) -> dict | None:
        md = event.mimeData()
        if not md.hasFormat(REMOTE_MIME):
            return None
        import json

        try:
            data = json.loads(bytes(md.data(REMOTE_MIME)).decode("utf-8"))
        except ValueError:
            return None
        return data if isinstance(data, dict) and data.get("paths") else None

    def _remote_drag(self, event) -> bool:
        """Ziehen aus einem Server-Fenster: nur in das andere Fenster (v1.3)."""
        payload = self._remote_payload(event)
        if payload is None or event.source() is self:
            return False
        action = self._choose_action(event)
        target = self._target_dir(event.position().toPoint(), payload["paths"])
        if action is None or target is None or self.model().trash_mode:
            return False
        event.setDropAction(action)
        return True

    def dragEnterEvent(self, event) -> None:
        if self._remote_payload(event) is not None:
            if event.source() is not self:
                action = self._choose_action(event)
                if action is not None:
                    event.setDropAction(action)
                    event.accept()
                    return
            event.ignore()
            return
        if self._local_paths(event):
            action = self._choose_action(event)
            if action is not None:
                event.setDropAction(action)
                event.accept()
                return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._remote_payload(event) is not None:
            if self._remote_drag(event):
                event.accept()
            else:
                event.ignore()
            return
        paths = self._local_paths(event)
        action = self._choose_action(event) if paths else None
        if action is None:
            event.ignore()
            return
        target = self._target_dir(event.position().toPoint(), paths)
        # Ablegen auf den eigenen Ordner ohne Ziel-Unterordner ergibt nichts
        if target is None or (event.source() is self and target == self.model().directory):
            event.ignore()
            return
        event.setDropAction(action)
        event.accept()

    def dropEvent(self, event) -> None:
        payload = self._remote_payload(event)
        if payload is not None:
            if not self._remote_drag(event):
                event.ignore()
                return
            event.accept()
            self.remote_drop_requested.emit(payload, self._target_dir(event.position().toPoint(), payload["paths"]),
                                            event.dropAction())
            return
        paths = self._local_paths(event)
        action = self._choose_action(event) if paths else None
        target = self._target_dir(event.position().toPoint(), paths) if paths else None
        if not paths or action is None or target is None:
            event.ignore()
            return
        event.setDropAction(action)
        event.accept()
        self.drop_requested.emit(paths, target, action)


class FilePanel(QWidget):
    focus_entered = Signal()
    path_changed = Signal(str)
    context_menu_requested = Signal(QPoint)
    drop_requested = Signal(list, str, object)
    remote_drop_requested = Signal(object, str, object)
    open_file_requested = Signal(str)
    remote_open_requested = Signal(object)  # Entry auf dem Server (v1.3)
    remote_closed = Signal(object)  # Sitzung wurde getrennt
    message = Signal(str, str)  # Titel, Text
    columns_changed = Signal()  # Spalten verschoben/Breite/ein-/ausgeblendet/Ausrichtung
    profile_chosen = Signal(str)  # Spaltenprofil im Kopf-Kontextmenü gewählt
    new_profile_requested = Signal()
    filter_changed = Signal()

    def __init__(self, side: str, icons: IconProvider, parent=None) -> None:
        super().__init__(parent)
        self.side = side
        self._history: list[str] = []
        self._history_pos = -1
        self._active = False
        self._free_text = ""
        self.mounts = None  # MountManager, vom Hauptfenster gesetzt
        self.trash = None  # Trash, vom Hauptfenster gesetzt
        self._columns_set = False
        self.filter_spec = None  # zuletzt definierter Filter (FilterSpec)
        self.remote = None  # Server-Sitzung (v1.3), siehe remotecontrol.RemoteSession
        self._filter_on = False

        self.header = QFrame(self)
        self.header.setObjectName("panelHeader")
        self.header.setProperty("active", False)
        self.path_edit = QLineEdit(self.header)
        self.path_edit.setObjectName("pathEdit")
        self.path_edit.returnPressed.connect(self._on_path_entered)
        self.path_edit.installEventFilter(self)
        completer_model = QFileSystemModel(self)
        completer_model.setFilter(QDir.Filter.Dirs | QDir.Filter.NoDotAndDotDot | QDir.Filter.Hidden)
        # Keine Überwachung: sonst blockiert die Pfad-Vervollständigung das Aushängen von Freigaben
        completer_model.setOption(QFileSystemModel.Option.DontWatchForChanges, True)
        completer_model.setRootPath("" if sys.platform.startswith("win") else "/")
        completer = QCompleter(completer_model, self)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.path_edit.setCompleter(completer)
        hl = QVBoxLayout(self.header)
        hl.setContentsMargins(3, 3, 3, 3)
        hl.addWidget(self.path_edit)

        self.model = FileListModel(icons, self)
        self.model.rename_failed.connect(lambda msg: self.message.emit(t("title.rename"), msg))
        self.model.renamed.connect(self._select_name_later)
        self.view = FileView(self)
        self.view.setModel(self.model)
        self.view.focus_entered.connect(self.focus_entered)
        self.view.doubleClicked.connect(self._on_double_click)
        self.view.customContextMenuRequested.connect(
            lambda pos: self.context_menu_requested.emit(self.view.viewport().mapToGlobal(pos))
        )
        self.view.drop_requested.connect(self.drop_requested)
        self.view.remote_drop_requested.connect(self.remote_drop_requested)
        self.model.remote_side = side
        hdr = self.view.header()
        # Spalten per Drag & Drop verschiebbar (F-340), per Rechtsklick ein-/ausblendbar (F-341)
        hdr.setSectionsMovable(True)
        hdr.setFirstSectionMovable(True)
        defaults = {COL_NAME: 260, COL_SIZE: 90, COL_DATE: 125, COL_TYPE: 120, COL_CREATED: 125}
        for col in range(COLUMN_COUNT):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            hdr.resizeSection(col, defaults.get(col, 90))
            hdr.setSectionHidden(col, col in DEFAULT_HIDDEN)
        _place_before(hdr, COL_CREATED, COL_DATE)  # „Erstellt“ vor „Geändert“
        hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        hdr.sectionMoved.connect(lambda *_a: self._update_icon_column())
        hdr.customContextMenuRequested.connect(self._header_menu)
        # Spaltenänderungen ins aktive Spaltenprofil übernehmen (F-842), gebündelt
        self.column_profile = ""
        self._applying_profile = False
        self._columns_timer = QTimer(self)
        self._columns_timer.setSingleShot(True)
        self._columns_timer.setInterval(400)
        self._columns_timer.timeout.connect(self.columns_changed)
        hdr.sectionMoved.connect(self._columns_touched)
        hdr.sectionResized.connect(self._columns_touched)
        hdr.setStretchLastSection(True)
        hdr.setMinimumSectionSize(40)
        hdr.setSortIndicator(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.view.selectionModel().selectionChanged.connect(self._update_status)

        self.status = QLabel(self)
        self.status.setObjectName("panelStatus")
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.header)
        layout.addWidget(self.view, 1)
        # Vorschau für „Mehrfach umbenennen“ (F-702) – ersetzt die Liste, solange der Modus läuft
        self.preview = QTreeView(self)
        self.preview.setObjectName("renamePreview")
        self.preview.setRootIsDecorated(False)
        self.preview.setUniformRowHeights(True)
        self.preview.setAlternatingRowColors(True)
        self.preview.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.header().setSectionsClickable(True)
        self.preview.header().setSortIndicatorShown(True)
        self.preview.header().sectionClicked.connect(self._preview_sort)
        self.preview.hide()
        layout.addWidget(self.preview, 1)
        layout.addWidget(self.status)
        self.locked = False  # während „Mehrfach umbenennen“: kein Ordnerwechsel (F-706)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(lambda _p: self._refresh_timer.start())
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self.refresh)

    # --- Eigenschaften --------------------------------------------------------------
    @property
    def current_path(self) -> str:
        return self.model.directory

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self.header.setProperty("active", active)
        self.header.style().unpolish(self.header)
        self.header.style().polish(self.header)

    def is_active(self) -> bool:
        return self._active

    def set_options(self, show_hidden: bool, dirs_first: bool, show_parent: bool) -> None:
        self.model.set_options(show_hidden, dirs_first, show_parent)

    # --- Navigation -------------------------------------------------------------------
    def with_mount(self, path: str, action) -> bool:
        """Führt action() aus – bindet vorher die Freigabe ein, falls path darin liegt und sie fehlt.

        Gibt True zurück, wenn erst eingebunden werden muss (action läuft dann später).
        """
        entry = self.mounts.needs_mount(path) if self.mounts is not None else None
        if entry is None:
            action()
            return False
        self.status.setText(t("mount.mounting", name=entry.label))

        def done(ok: bool, output: str) -> None:
            real = self.mounts.mounted_at(entry.source) if ok and not entry.in_fstab else None
            if real and real != entry.mount_point:
                # udisks hat einen anderen Ordner gewählt als erwartet (z. B. bei gleichem Namen)
                rest = os.path.relpath(path, entry.mount_point)
                self.navigate(real if rest == "." else os.path.join(real, rest))
            elif ok and self.mounts.needs_mount(path) is None:
                action()
            else:
                self._update_status()
                self.message.emit(t("title.mount"), t("mount.failed", name=entry.label,
                                                      reason=output or t("mount.unknown_error")))
                if not self.current_path:
                    self.navigate(os.path.expanduser("~"))

        self.mounts.mount(entry, done)
        return True

    @property
    def in_trash(self) -> bool:
        return self.model.trash_mode

    def _show_trash(self, add_history: bool) -> bool:
        items = self.trash.items() if self.trash is not None else []
        self.model.load_trash(items, TRASH_URI)
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        dirs = self.trash.files_dirs() if self.trash is not None else []
        if dirs:
            self._watcher.addPaths(dirs)
        self._add_history(TRASH_URI, add_history)
        self.path_edit.setText(t("trash.title"))
        self._update_filter_style()
        self._free_text = ""
        self._select_after_load(None)
        self._update_status()
        self.path_changed.emit(TRASH_URI)
        return True

    def _add_history(self, path: str, add_history: bool) -> None:
        if add_history:
            self._history = self._history[: self._history_pos + 1]
            if not self._history or self._history[-1] != path:
                self._history.append(path)
            self._history = self._history[-HISTORY_LIMIT:]
            self._history_pos = len(self._history) - 1

    # --- Server (v1.3) ----------------------------------------------------------------------
    @property
    def in_remote(self) -> bool:
        return self.model.remote_mode

    def _navigate_remote(self, uri: str, select_name: str | None, add_history: bool) -> bool:
        session = self.remote
        if session is None or not (uri == session.base or uri.startswith(session.base + "/")):
            self.message.emit(t("srv.title"), t("srv.not_connected", uri=uri))
            return False
        path = uri[len(session.base):] or "/"
        items = session.listdir(path)
        if items is None:
            return False
        self.model.load_remote(session.base, path, items)
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        uri = session.base + path
        self._add_history(uri, add_history)
        self.path_edit.setText(uri)
        self._update_filter_style()
        self._free_text = ""
        self._select_after_load(select_name)
        self._update_status()
        self.path_changed.emit(uri)
        return True

    def attach_remote(self, session, path: str) -> bool:
        """Mit einer Sitzung verbinden und deren Startordner zeigen."""
        if self.remote is not None and self.remote is not session:
            self.close_remote()
        self.remote = session
        self.model.remote_rename = session.rename_entry
        self.set_remote_color(session.cfg.color)
        if not self.navigate(session.base + path):
            if not self.navigate(session.base + "/"):
                self.close_remote()
                return False
        return True

    def close_remote(self, navigate_to: str | None = None, navigate_away: bool = True) -> None:
        session = self.remote
        if session is None:
            return
        self.remote = None
        self.model.remote_rename = None
        self.set_remote_color("")
        base = session.base
        keep = [h for h in self._history if not (h == base or h.startswith(base + "/"))]
        pos = self._history_pos
        if keep != self._history:
            # Position auf den letzten lokalen Eintrag vor dem Server setzen
            before = [h for h in self._history[: max(pos, 0) + 1] if not (h == base or h.startswith(base + "/"))]
            self._history = keep
            self._history_pos = len(before) - 1
        self.remote_closed.emit(session)
        if navigate_to is not None:
            self.navigate(navigate_to)
        elif navigate_away and self.in_remote:
            target = self._history[self._history_pos] if 0 <= self._history_pos < len(self._history) else ""
            self.navigate(target or os.path.expanduser("~"), add_history=not target)

    def set_remote_color(self, color: str) -> None:
        self.view.setStyleSheet(f"QTreeView {{ background-color: {color}; }}" if color else "")

    def navigate(self, path: str, select_name: str | None = None, add_history: bool = True) -> bool:
        if self.locked:
            return False
        self._end_search_view()
        if is_remote_uri(path):
            return self._navigate_remote(path, select_name, add_history)
        if self.remote is not None:
            self.close_remote(navigate_away=False)  # Verbindung endet beim Wechsel ins Lokale (L-346)
        if is_trash_uri(path):
            return self._show_trash(add_history)
        path = os.path.abspath(os.path.expanduser(path))
        if self.mounts is not None and self.mounts.needs_mount(path) is not None:
            self.with_mount(path, lambda: self.navigate(path, select_name, add_history))
            return True
        try:
            self.model.load(path)
        except OSError as exc:
            reason = exc.strerror or str(exc)
            fallback = nearest_existing_dir(os.path.dirname(path))
            self.message.emit(t("title.folder_error"), t("error.cannot_open_folder", path=path, reason=reason))
            if fallback == path:
                return False
            try:
                self.model.load(fallback)
            except OSError:
                return False
            path = fallback
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        self._watcher.addPath(path)
        self._add_history(path, add_history)
        self.path_edit.setText(path)
        self._update_filter_style()
        self._update_free_space()
        self._select_after_load(select_name)
        self._update_status()
        self.path_changed.emit(path)
        return True

    def _select_after_load(self, select_name: str | None) -> None:
        row = self.model.row_of(select_name) if select_name else -1
        if row < 0:
            row = 0
        if self.model.rowCount() == 0:
            return
        index = self.model.index(row, self.model.icon_column)
        sel = self.view.selectionModel()
        sel.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
        if not select_name:
            sel.clearSelection()
        self.view.scrollTo(index)

    def _select_name_later(self, name: str) -> None:
        QTimer.singleShot(0, lambda: self.select_names([name], current=name))

    def select_names(self, names: list[str], current: str | None = None) -> None:
        sel = self.view.selectionModel()
        sel.clearSelection()
        for name in names:
            row = self.model.row_of(name)
            if row >= 0:
                sel.select(
                    self.model.index(row, self.model.icon_column),
                    QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
                )
        if current:
            row = self.model.row_of(current)
            if row >= 0:
                idx = self.model.index(row, self.model.icon_column)
                sel.setCurrentIndex(idx, QItemSelectionModel.SelectionFlag.NoUpdate)
                self.view.scrollTo(idx)

    def refresh(self) -> None:
        if not self.current_path:
            return
        if self.view.state() == QAbstractItemView.State.EditingState:
            # Während des Umbenennens nicht neu einlesen – das würde die Eingabe beenden.
            self._refresh_timer.start()
            return
        selected = [e.name for e in self.selected_entries()]
        cur = self.current_entry()
        cur_name = cur.name if cur else None
        scroll = self.view.verticalScrollBar().value()
        if self.search_mode:
            self.model.refresh_results()
            self.select_names(selected, current=cur_name)
            self.view.verticalScrollBar().setValue(scroll)
            self._update_status()
            return
        if self.in_trash:
            items = self.trash.items() if self.trash is not None else []
            self.model.load_trash(items, TRASH_URI)
            self.select_names(selected, current=cur_name)
            self.view.verticalScrollBar().setValue(scroll)
            self._update_status()
            return
        if self.in_remote:
            if self.remote is None:
                return
            path = self.current_path[len(self.remote.base):] or "/"
            items = self.remote.listdir(path)
            if items is None:
                return
            self.model.load_remote(self.remote.base, path, items)
            self.select_names(selected, current=cur_name)
            self.view.verticalScrollBar().setValue(scroll)
            self._update_status()
            return
        if not os.path.isdir(self.current_path):
            self.navigate(nearest_existing_dir(self.current_path))
            return
        try:
            self.model.load(self.current_path)
        except OSError:
            self.navigate(nearest_existing_dir(os.path.dirname(self.current_path)))
            return
        self.select_names(selected, current=cur_name)
        if cur_name and self.model.row_of(cur_name) < 0 and self.model.rowCount():
            self.view.selectionModel().setCurrentIndex(
                self.model.index(0, self.model.icon_column), QItemSelectionModel.SelectionFlag.NoUpdate
            )
        self.view.verticalScrollBar().setValue(scroll)
        self._update_free_space()
        self._update_status()

    def go_up(self) -> None:
        if self.in_trash:
            return
        if self.in_remote and self.remote is not None:
            import posixpath

            path = self.current_path[len(self.remote.base):] or "/"
            if path != "/":
                parent = posixpath.dirname(path.rstrip("/")) or "/"
                self.navigate(self.remote.base + parent, select_name=posixpath.basename(path.rstrip("/")))
            return
        if self.search_mode:
            self.navigate(self.current_path)
            return
        from pathlib import Path

        p = Path(self.current_path)
        if p.parent != p:
            self.navigate(str(p.parent), select_name=p.name)

    def can_go_back(self) -> bool:
        return self._history_pos > 0

    def can_go_forward(self) -> bool:
        return self._history_pos < len(self._history) - 1

    def back(self) -> None:
        if self.can_go_back():
            came_from = self.current_path
            self._history_pos -= 1
            self.navigate(self._history[self._history_pos], add_history=False,
                          select_name=_child_name(self._history[self._history_pos], came_from))

    def forward(self) -> None:
        if self.can_go_forward():
            self._history_pos += 1
            self.navigate(self._history[self._history_pos], add_history=False)

    def history_entries(self, forward: bool) -> list[tuple[int, str]]:
        """Verlaufsliste für Zurück (neueste zuerst) bzw. Vorwärts (F-552)."""
        if forward:
            return [(i, self._history[i]) for i in range(self._history_pos + 1, len(self._history))]
        return [(i, self._history[i]) for i in range(self._history_pos - 1, -1, -1)]

    def go_history(self, index: int) -> None:
        if 0 <= index < len(self._history) and index != self._history_pos:
            came_from = self.current_path
            self._history_pos = index
            self.navigate(self._history[index], add_history=False,
                          select_name=_child_name(self._history[index], came_from))

    def history_state(self) -> tuple[list[str], int]:
        return list(self._history), self._history_pos

    def set_history_state(self, history: list[str], pos: int) -> None:
        self._history = list(history)
        self._history_pos = min(max(pos, -1), len(self._history) - 1)

    def open_entry(self, entry: Entry) -> None:
        if self.in_trash:
            if not entry.is_dir:
                self.open_file_requested.emit(entry.path)  # nur ansehen; Ordner im Papierkorb nicht öffnen
            return
        if entry.is_parent:
            self.go_up()
        elif entry.is_dir:
            self.navigate(entry.path)
        elif entry.remote:
            self.remote_open_requested.emit(entry)
        else:
            self.open_file_requested.emit(entry.path)

    def open_current(self) -> None:
        entry = self.current_entry()
        if entry is not None:
            self.open_entry(entry)

    def _on_double_click(self, index: QModelIndex) -> None:
        entry = self.model.entry(index.row())
        if entry is not None:
            self.open_entry(entry)

    def _on_path_entered(self) -> None:
        text = self.path_edit.text().strip()
        if not text:
            self.path_edit.setText(self.current_path)
            return
        if is_trash_uri(text) or text.casefold() == t("trash.title").casefold():
            self.navigate(TRASH_URI)
            self.view.setFocus()
            return
        if is_remote_uri(text):
            if not self.navigate(text.rstrip("/") if text.count("/") > 3 else text):
                self.path_edit.setText(self.current_path)
                return
            self.view.setFocus()
            return
        target = os.path.abspath(os.path.expanduser(text))
        if os.path.isfile(target):
            self.navigate(os.path.dirname(target), select_name=os.path.basename(target))
        elif os.path.isdir(target):
            self.navigate(target)
        else:
            self.message.emit(t("title.folder_error"), t("error.path_not_found", path=target))
            self.path_edit.setText(self.current_path)
            return
        self.view.setFocus()

    def edit_path(self) -> None:
        self.path_edit.setFocus()
        self.path_edit.selectAll()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.path_edit and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.path_edit.setText(self.current_path)
                self.view.setFocus()
                return True
        if obj is self.path_edit and event.type() == event.Type.FocusIn:
            self.focus_entered.emit()
        return super().eventFilter(obj, event)

    # --- Markierung -----------------------------------------------------------------
    def current_entry(self) -> Entry | None:
        idx = self.view.currentIndex()
        return self.model.entry(idx.row()) if idx.isValid() else None

    def selected_entries(self) -> list[Entry]:
        rows = sorted({i.row() for i in self.view.selectionModel().selectedRows(COL_NAME)})
        result = []
        for r in rows:
            e = self.model.entry(r)
            if e is not None and not e.is_parent:
                result.append(e)
        return result

    def target_entries(self) -> list[Entry]:
        """Markierte Einträge – oder, wenn nichts markiert ist, der Eintrag unter dem Cursor."""
        sel = self.selected_entries()
        if sel:
            return sel
        cur = self.current_entry()
        return [cur] if cur is not None and not cur.is_parent else []

    def select_all(self) -> None:
        self.view.selectAll()
        if self.model.rowCount() and self.model.entry(0).is_parent:
            self.view.selectionModel().select(
                self.model.index(0, self.model.icon_column),
                QItemSelectionModel.SelectionFlag.Deselect | QItemSelectionModel.SelectionFlag.Rows,
            )

    def start_rename(self) -> None:
        entry = self.current_entry()
        if entry is None or entry.is_parent or self.in_trash:
            return
        col = COL_NAME if self.column_visible(COL_NAME) else COL_NAME_STEM
        idx = self.model.index(self.view.currentIndex().row(), col)
        self.view.edit(idx)

    def column_widths(self) -> list[int]:
        hdr = self.view.header()
        return [hdr.sectionSize(c) for c in range(hdr.count())]

    def header_state(self) -> str:
        return bytes(self.view.header().saveState().toHex()).decode()

    def restore_header_state(self, hex_state: str, saved_columns: int = 10) -> None:
        from PySide6.QtCore import QByteArray

        hdr = self.view.header()
        if hdr.restoreState(QByteArray.fromHex(hex_state.encode())):
            # Spalten, die es beim Speichern noch nicht gab: Grundeinstellung
            for col in range(max(saved_columns, 0), COLUMN_COUNT):
                hdr.setSectionHidden(col, col in DEFAULT_HIDDEN)
                if col == COL_CREATED:
                    hdr.resizeSection(col, 125)
                    _place_before(hdr, col, COL_DATE)
            self._columns_set = True
            visible = [c for c in NAME_COLUMNS if not hdr.isSectionHidden(c)]
            if not visible:
                hdr.setSectionHidden(COL_NAME, False)
            elif len(visible) > 1:  # aus v0.4: beide sichtbar – nur die vordere bleibt
                keep = min(visible, key=hdr.visualIndex)
                for c in visible:
                    hdr.setSectionHidden(c, c != keep)
            hdr.setSectionsMovable(True)
            self._update_icon_column()

    def column_visible(self, col: int) -> bool:
        return not self.view.header().isSectionHidden(col)

    def set_column_visible(self, col: int, visible: bool) -> None:
        hdr = self.view.header()
        if col in NAME_COLUMNS:
            # Genau eine Namensspalte ist sichtbar (F-521): Einschalten tauscht, Ausschalten geht nicht
            if not visible:
                return
            other = next(c for c in NAME_COLUMNS if c != col)
            if not hdr.isSectionHidden(other):
                width = hdr.sectionSize(other)
                hdr.setSectionHidden(col, False)
                if hdr.visualIndex(col) != hdr.visualIndex(other):
                    hdr.moveSection(hdr.visualIndex(col), hdr.visualIndex(other))
                hdr.resizeSection(col, max(width, 40))
                hdr.setSectionHidden(other, True)
                self._update_icon_column()
                return
        hdr.setSectionHidden(col, not visible)
        if visible and hdr.sectionSize(col) < 40:
            hdr.resizeSection(col, 150 if col in NAME_COLUMNS else 90)
        self._update_icon_column()

    def _update_icon_column(self) -> None:
        """Das Symbol steht in der ersten sichtbaren Namensspalte."""
        hdr = self.view.header()
        visible = [c for c in NAME_COLUMNS if not hdr.isSectionHidden(c)]
        col = min(visible, key=hdr.visualIndex) if visible else COL_NAME
        if col != self.model.icon_column:
            self.model.icon_column = col
            self.view.viewport().update()
        # Der Cursor muss in einer sichtbaren Spalte stehen – sonst folgt die Markierung
        # den Pfeiltasten nicht (Cursor in ausgeblendeter Spalte „Name (mit Endung)“).
        cur = self.view.currentIndex()
        if cur.isValid() and hdr.isSectionHidden(cur.column()):
            self.view.selectionModel().setCurrentIndex(
                self.model.index(cur.row(), col), QItemSelectionModel.SelectionFlag.NoUpdate)

    # --- Spaltenprofile (F-842, F-843) ----------------------------------------------------
    def _columns_touched(self, *_args) -> None:
        if not self._applying_profile:
            self._columns_timer.start()

    def profile_data(self) -> dict:
        return {"header": self.header_state(), "columns": COLUMN_COUNT, "align": dict(self.model.alignments)}

    def apply_profile(self, name: str, data: dict) -> None:
        self._applying_profile = True
        sort_col, sort_order = self.model.sort_column, self.model.sort_order
        try:
            self.column_profile = name
            if data.get("header"):
                cols = data.get("columns", 10)
                self.restore_header_state(data["header"], cols if isinstance(cols, int) else 10)
            # Sortierung gehört zum Fenster, nicht zum Profil
            self.view.header().setSortIndicator(sort_col, sort_order)
            self.model.alignments = dict(data.get("align") or {})
            self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, COLUMN_COUNT - 1)
            self.view.viewport().update()
        finally:
            self._applying_profile = False
        self._columns_timer.stop()

    def column_signature(self) -> tuple:
        """Sichtbare Spalten in ihrer Reihenfolge (für den Vergleich zweier Fenster)."""
        hdr = self.view.header()
        return tuple(hdr.logicalIndex(v) for v in range(hdr.count()) if not hdr.isSectionHidden(hdr.logicalIndex(v)))

    def set_alignment(self, col: int, mode: str) -> None:
        if mode == ("right" if col == COL_SIZE else "left"):
            self.model.alignments.pop(col, None)
        else:
            self.model.alignments[col] = mode
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, COLUMN_COUNT - 1)
        self.view.viewport().update()
        self._columns_touched()

    def _header_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        from .filemodel import COL_GROUP, COL_OWNER, COL_PERM_NUM, COL_PERM_STR
        from .platform import IS_WINDOWS

        menu = QMenu(self)
        # Beide Namensspalten zuerst; nichts ausgrauen – den Zustand zeigt das Häkchen.
        # Ausnahme Windows-Vorschau: Linux-Rechte-Spalten sind dort ohne Aussage.
        from .filemodel import MENU_ORDER

        for col in MENU_ORDER:
            act = menu.addAction(t(COLUMN_KEYS[col]))
            act.setCheckable(True)
            act.setChecked(self.column_visible(col))
            if IS_WINDOWS and col in (COL_PERM_NUM, COL_PERM_STR, COL_OWNER, COL_GROUP):
                act.setEnabled(False)
            act.toggled.connect(lambda on, c=col: (self.set_column_visible(c, on), self._columns_touched()))
        # Ausrichtung der Spalte unter dem Mauszeiger (F-843)
        col = self.view.header().logicalIndexAt(pos)
        if col >= 0:
            current = self.model.alignments.get(col, "right" if col == COL_SIZE else "left")
            sub = menu.addMenu(t("colprof.align_of", name=t(COLUMN_KEYS[col])))
            for mode in ("left", "center", "right"):
                a = sub.addAction(t(f"colprof.align_{mode}"))
                a.setCheckable(True)
                a.setChecked(mode == current)
                a.triggered.connect(lambda _c=False, c=col, m=mode: self.set_alignment(c, m))
        from . import colprofiles

        prof = menu.addMenu(t("colprof.menu"))
        for name in colprofiles.names():
            a = prof.addAction(name)
            a.setCheckable(True)
            a.setChecked(name == self.column_profile)
            a.triggered.connect(lambda _c=False, n=name: self.profile_chosen.emit(n))
        prof.addSeparator()
        prof.addAction(t("colprof.new")).triggered.connect(self.new_profile_requested)
        menu.exec(self.view.header().mapToGlobal(pos))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._columns_set:
            self._columns_set = True
            QTimer.singleShot(0, self._fit_name_column)

    def _fit_name_column(self) -> None:
        """Erster Start: „Name“ bekommt den Platz, den die übrigen Spalten übrig lassen."""
        hdr = self.view.header()
        others = sum(hdr.sectionSize(c) for c in range(COLUMN_COUNT)
                     if c != COL_NAME and not hdr.isSectionHidden(c) and hdr.visualIndex(c) != hdr.count() - 1) + 120
        hdr.resizeSection(COL_NAME, max(150, self.view.viewport().width() - others))

    def set_column_widths(self, widths: list[int]) -> None:
        self._columns_set = True
        hdr = self.view.header()
        for col, w in enumerate(widths[: hdr.count() - 1]):  # letzte Spalte füllt automatisch
            if isinstance(w, int) and w >= 40:
                hdr.resizeSection(col, w)

    def sort_state(self) -> tuple[int, int]:
        return self.model.sort_column, int(self.model.sort_order.value)

    def set_sort_state(self, column: int, order: int) -> None:
        o = Qt.SortOrder(order)
        self.view.header().setSortIndicator(column, o)
        self.view.sortByColumn(column, o)

    # --- Statuszeile ------------------------------------------------------------------
    def _update_free_space(self) -> None:
        try:
            usage = shutil.disk_usage(self.current_path)
            self._free_text = t("status.free", size=format_size(usage.free))
        except OSError:
            self._free_text = ""

    # --- Suchergebnisse (F-817) -------------------------------------------------------------
    @property
    def search_mode(self) -> bool:
        return self.model.search_base is not None

    def show_search_results(self, base: str) -> None:
        """Liste leeren und für Treffer vorbereiten; die Spalte „Ordner“ wird sichtbar."""
        hdr = self.view.header()
        if not hasattr(self, "_type_hidden_before") or self._type_hidden_before is None:
            self._type_hidden_before = hdr.isSectionHidden(COL_TYPE)
        if hdr.isSectionHidden(COL_TYPE):
            self._applying_profile = True
            hdr.setSectionHidden(COL_TYPE, False)
            self._applying_profile = False
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        self.model.load_results(base, [])
        self.path_edit.setText(t("search.path_label", path=base))
        self._update_filter_style()
        self._update_status()
        self.path_changed.emit(base)

    def add_search_results(self, entries: list) -> None:
        had_current = self.view.currentIndex().isValid()
        self.model.add_results(entries)
        if not had_current and self.model.rowCount():
            self.view.selectionModel().setCurrentIndex(
                self.model.index(0, self.model.icon_column), QItemSelectionModel.SelectionFlag.NoUpdate)
        self._update_status()

    def finish_search(self) -> None:
        cur = self.current_entry()
        self.model.resort()
        if cur is not None:
            row = next((i for i, e in enumerate(self.model.entries()) if e.path == cur.path), 0)
            self.view.selectionModel().setCurrentIndex(
                self.model.index(row, self.model.icon_column), QItemSelectionModel.SelectionFlag.NoUpdate)
        self._update_status()

    def _end_search_view(self) -> None:
        before = getattr(self, "_type_hidden_before", None)
        if before is not None:
            self._type_hidden_before = None
            if before:
                self._applying_profile = True
                self.view.header().setSectionHidden(COL_TYPE, True)
                self._applying_profile = False

    # --- Vorschau „Mehrfach umbenennen“ ---------------------------------------------------
    def set_preview_mode(self, on: bool, model=None) -> None:
        self.locked = on
        self.path_edit.setReadOnly(on)
        if on:
            self.preview.setModel(model)
            hdr = self.preview.header()
            for col, width in enumerate((260, 260, 90, 125, 125)):
                hdr.resizeSection(col, width)
            self._sync_preview_sort_indicator()
            self.view.hide()
            self.preview.show()
            self.preview.setFocus()
        else:
            self.preview.hide()
            self.preview.setModel(None)
            self.view.show()
            self.view.setFocus()

    # --- Eigene Ansicht statt der Dateiliste (Meta-Wizard, F-903) --------------------------
    def set_custom_view(self, widget: QWidget | None) -> None:
        layout = self.layout()
        old = getattr(self, "_custom_view", None)
        if old is not None:
            layout.removeWidget(old)
            old.hide()
            old.setParent(None)
            self._custom_view = None
        self.locked = widget is not None
        self.path_edit.setReadOnly(widget is not None)
        self.status.setVisible(widget is None)  # Ordnerstatus passt nicht zur Titelliste
        if widget is None:
            self.view.show()
            self.view.setFocus()
            return
        self._custom_view = widget
        layout.insertWidget(layout.indexOf(self.view) + 1, widget, 1)
        self.view.hide()
        widget.show()
        widget.setFocus()

    _PREVIEW_SORT = {0: COL_NAME, 2: COL_SIZE, 3: COL_DATE, 4: COL_CREATED}

    def _preview_sort(self, section: int) -> None:
        col = self._PREVIEW_SORT.get(section)
        if col is None:
            self._sync_preview_sort_indicator()
            return
        order = Qt.SortOrder.AscendingOrder
        if self.model.sort_column == col and self.model.sort_order == Qt.SortOrder.AscendingOrder:
            order = Qt.SortOrder.DescendingOrder
        self.view.header().setSortIndicator(col, order)  # sortiert das Modell mit
        if self.model.sort_column != col or self.model.sort_order != order:
            self.model.sort(col, order)
        self._sync_preview_sort_indicator()

    def _sync_preview_sort_indicator(self) -> None:
        reverse = {v: k for k, v in self._PREVIEW_SORT.items()}
        sec = reverse.get(self.model.sort_column, 0)
        self.preview.header().setSortIndicator(sec, self.model.sort_order)

    # --- Filter (F-600 ff.) --------------------------------------------------------------
    @property
    def filter_active(self) -> bool:
        return self._filter_on and self.filter_spec is not None

    def set_filter(self, spec, active: bool = True) -> None:
        """Filter setzen bzw. an/aus schalten; liest den Ordner neu ein."""
        if spec is not None:
            self.filter_spec = spec
        self._filter_on = bool(active and self.filter_spec is not None)
        self.model.accept = self.filter_spec.accepts() if self.filter_active else None
        self._update_filter_style()
        if not self.in_trash:
            self.refresh()
        self.filter_changed.emit()

    def _update_filter_style(self) -> None:
        """Pfad rot und fett, solange ein Filter wirkt (F-608) – nicht im Papierkorb."""
        on = self.filter_active and not self.in_trash
        if self.header.property("filtered") == on:
            return
        self.header.setProperty("filtered", on)
        for w in (self.header, self.path_edit):
            w.style().unpolish(w)
            w.style().polish(w)

    def filter_counts(self) -> tuple[int, int]:
        """(sichtbare Einträge, Einträge ohne Filter) – ohne „..“."""
        shown = sum(1 for e in self.model.entries() if not e.is_parent)
        return shown, (self.model.total_count if not self.in_trash else shown)

    def _update_status(self, *_args) -> None:
        entries = [e for e in self.model.entries() if not e.is_parent]
        dirs = sum(1 for e in entries if e.is_dir)
        files = len(entries) - dirs
        parts = [t("status.counts", dirs=dirs, files=files)]
        if self.filter_active and not self.in_trash:
            shown, total = self.filter_counts()
            parts.append(t("status.filtered", shown=shown, total=total))
        sel = self.selected_entries()
        if sel:
            size = sum(e.size for e in sel if not e.is_dir)
            parts.append(t("status.selected", n=len(sel), size=format_size(size)))
        if self._free_text:
            parts.append(self._free_text)
        self.status.setText("  ·  ".join(parts))


def _place_before(hdr, col: int, before: int) -> None:
    """Spalte col (sichtbar) direkt vor die Spalte before setzen, falls sie dahinter steht."""
    if hdr.visualIndex(col) > hdr.visualIndex(before):
        hdr.moveSection(hdr.visualIndex(col), hdr.visualIndex(before))


def _child_name(parent: str, child: str) -> str | None:
    """Wenn child direkt in parent liegt: dessen Name (zum Wieder-Markieren)."""
    if os.path.dirname(child.rstrip(os.sep)) == parent.rstrip(os.sep) or (
        parent == os.sep and os.path.dirname(child) == os.sep
    ):
        return os.path.basename(child.rstrip(os.sep))
    return None
