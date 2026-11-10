"""Baumansicht für die Seitenleiste (nur Ordner).

Oberste Einträge: Persönlicher Ordner, Dateisystem, Netzwerk, Laufwerke.
Unterordner werden erst beim Aufklappen eingelesen. Jede Seitenleiste hat ihr
eigenes Modell, damit links und rechts unabhängig aufgeklappt werden.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QStyle, QApplication, QTreeView

from .filepanel import FileView
from .i18n import t
from .icons import IconProvider
from .mounts import KIND_NETWORK, MountManager
from .trash import TRASH_URI, is_trash_uri

PathRole = Qt.ItemDataRole.UserRole + 10
KindRole = Qt.ItemDataRole.UserRole + 11
LoadedRole = Qt.ItemDataRole.UserRole + 12

DiskRole = Qt.ItemDataRole.UserRole + 13

K_HOME, K_ROOT, K_NETWORK, K_DRIVES, K_SERVER, K_DISK, K_MOUNT, K_DIR, K_PLACEHOLDER = (
    "home", "root", "network", "drives", "server", "disk", "mount", "dir", "placeholder",
)
K_TRASH = "trash"
SECTION_KINDS = (K_NETWORK, K_DRIVES, K_SERVER, K_DISK)


def _placeholder() -> QStandardItem:
    item = QStandardItem("…")
    item.setData(K_PLACEHOLDER, KindRole)
    item.setFlags(Qt.ItemFlag.NoItemFlags)
    return item


class FolderTreeModel(QStandardItemModel):
    def __init__(self, icons: IconProvider, mounts: MountManager | None, parent=None) -> None:
        super().__init__(parent)
        self._icons = icons
        self._mounts = mounts
        self.show_hidden = False
        self.home_item: QStandardItem | None = None
        self.root_item: QStandardItem | None = None
        self.network_item: QStandardItem | None = None
        self.drives_item: QStandardItem | None = None
        self.build()

    # --- Aufbau -------------------------------------------------------------------------
    def _dir_item(self, name: str, path: str, kind: str = K_DIR, icon: QIcon | None = None) -> QStandardItem:
        item = QStandardItem(icon or self._icons.dir_icon(path), name)
        item.setData(path, PathRole)
        item.setData(kind, KindRole)
        item.setData(False, LoadedRole)
        item.setEditable(False)
        item.setToolTip(path)
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDropEnabled
        item.setFlags(flags)
        item.appendRow(_placeholder())
        return item

    def _section(self, name: str, kind: str, icon: QIcon) -> QStandardItem:
        item = QStandardItem(icon, name)
        item.setData(kind, KindRole)
        item.setEditable(False)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        return item

    def build(self) -> None:
        self.clear()
        style = QApplication.style()
        home = str(Path.home())
        self.home_item = self._dir_item(
            t("tree.home"), home, K_HOME, QIcon.fromTheme("user-home", style.standardIcon(QStyle.StandardPixmap.SP_DirHomeIcon))
        )
        from .platform import IS_WINDOWS, windows_drives

        drive_icon = QIcon.fromTheme("drive-harddisk", style.standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))
        self.root_item = self._dir_item(t("tree.filesystem"), "/", K_ROOT, drive_icon)
        self.root_items = [self.root_item]
        if IS_WINDOWS:
            # Windows-Vorschau: je Laufwerksbuchstabe ein Eintrag statt „Dateisystem (/)“
            self.root_items = [self._dir_item(d.rstrip("\\"), d, K_ROOT, drive_icon) for d in windows_drives()]
        self.network_item = self._section(
            t("tree.network"), K_NETWORK, QIcon.fromTheme("network-workgroup", style.standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon))
        )
        self.drives_item = self._section(
            t("tree.drives"), K_DRIVES, QIcon.fromTheme("drive-multidisk", style.standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))
        )
        from .bars import trash_icons

        self.trash_item = QStandardItem(trash_icons()[0], t("trash.title"))
        self.trash_item.setData(TRASH_URI, PathRole)
        self.trash_item.setData(K_TRASH, KindRole)
        self.trash_item.setEditable(False)
        self.trash_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDropEnabled)
        if IS_WINDOWS:
            # Netzwerk, Laufwerke (nach Platten) und Papierkorb gibt es in der Vorschau noch nicht
            for item in [self.home_item] + self.root_items:
                self.appendRow(item)
            return
        for item in (self.home_item, self.root_item, self.network_item, self.drives_item, self.trash_item):
            self.appendRow(item)
        self.rebuild_mounts()

    def set_trash_full(self, full: bool) -> None:
        from .bars import trash_icons

        empty, full_icon = trash_icons()
        self.trash_item.setIcon(full_icon if full else empty)

    def rebuild_mounts(self) -> None:
        for section in (self.network_item, self.drives_item):
            section.removeRows(0, section.rowCount())
        if self._mounts is None:
            return
        servers: dict[str, QStandardItem] = {}
        server_icon = QIcon.fromTheme("network-server", self._icons.network_folder(True))
        for entry in self._mounts.entries():
            item = self._dir_item(entry.label, entry.mount_point, K_MOUNT, self._icons.mount_icon(entry))
            if not entry.mounted:
                # nicht eingebunden: (noch) nicht aufklappbar, Klick bindet ein
                item.removeRows(0, item.rowCount())
            if entry.kind == KIND_NETWORK:
                server = entry.server or "?"
                parent = servers.get(server)
                if parent is None:
                    parent = self._section(server, K_SERVER, server_icon)
                    servers[server] = parent
                    self.network_item.appendRow(parent)
                parent.appendRow(item)
        # Laufwerke: je physische Platte ein Eintrag, darunter die Partitionen (F-260 ff.)
        for disk in self._mounts.disks():
            enabled = bool(disk.entries) or disk.kind != "optical"
            disk_item = self._section(disk.label, K_DISK, self._icons.disk_icon(disk.kind, enabled))
            disk_item.setData(disk, DiskRole)
            if not enabled:
                disk_item.setToolTip(t("drives.no_medium") if not disk.has_medium else disk.device)
            for entry in disk.entries:
                item = self._dir_item(entry.label, entry.mount_point, K_MOUNT,
                                      self._icons.disk_icon(disk.kind, entry.mounted))
                item.setData(disk, DiskRole)
                if not entry.mounted:
                    item.removeRows(0, item.rowCount())
                disk_item.appendRow(item)
            self.drives_item.appendRow(disk_item)

    # --- Nachladen ------------------------------------------------------------------------
    def load_children(self, item: QStandardItem) -> None:
        path = item.data(PathRole)
        if not path or is_trash_uri(path):
            return
        item.removeRows(0, item.rowCount())
        item.setData(True, LoadedRole)
        try:
            with os.scandir(path) as it:
                names = []
                for de in it:
                    if de.name.startswith(".") and not self.show_hidden:
                        continue
                    try:
                        if de.is_dir(follow_symlinks=True):
                            names.append((de.name, de.path))
                    except OSError:
                        continue
        except OSError:
            return
        names.sort(key=lambda n: (n[0].casefold(), n[0]))
        for name, child_path in names:
            item.appendRow(self._dir_item(name, child_path))

    @staticmethod
    def find_child(item: QStandardItem, name: str) -> QStandardItem | None:
        for row in range(item.rowCount()):
            child = item.child(row)
            if child is not None and child.text() == name and child.data(KindRole) == K_DIR:
                return child
        return None

    def mount_item(self, mount_point: str) -> QStandardItem | None:
        stack = [self.network_item, self.drives_item]
        while stack:
            it = stack.pop()
            for row in range(it.rowCount()):
                child = it.child(row)
                kind = child.data(KindRole)
                if kind == K_MOUNT and child.data(PathRole) == mount_point:
                    return child
                if kind in (K_SERVER, K_DISK):
                    stack.append(child)
        return None


class FolderTreeView(QTreeView):
    open_path = Signal(str)
    disk_clicked = Signal(object)  # DiskInfo (z. B. leeres DVD-Laufwerk)
    focus_entered = Signal()
    drop_requested = Signal(list, str, object)

    def __init__(self, icons: IconProvider, mounts: MountManager | None, parent=None) -> None:
        super().__init__(parent)
        self.tree_model = FolderTreeModel(icons, mounts, self)
        self._mounts = mounts
        self.setModel(self.tree_model)
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.setAnimated(False)
        self.setExpandsOnDoubleClick(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.expanded.connect(self._on_expanded)
        self.collapsed.connect(self._on_collapsed)
        self._press_index = None
        self._expand_sections()
        if mounts is not None:
            mounts.changed.connect(self._on_mounts_changed)

    def _expand_sections(self) -> None:
        model = self.tree_model
        for section in (model.network_item, model.drives_item):
            self.expand(section.index())
        for row in range(model.drives_item.rowCount()):
            self.expand(model.drives_item.child(row).index())

    # --- Hilfen -----------------------------------------------------------------------------
    def item_at(self, index: QModelIndex) -> QStandardItem | None:
        return self.tree_model.itemFromIndex(index) if index.isValid() else None

    def path_of(self, index: QModelIndex) -> str | None:
        item = self.item_at(index)
        return item.data(PathRole) if item is not None else None

    def disk_of(self, index: QModelIndex):
        item = self.item_at(index)
        return item.data(DiskRole) if item is not None else None

    def current_path(self) -> str | None:
        return self.path_of(self.currentIndex())

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focus_entered.emit()

    def _on_expanded(self, index: QModelIndex) -> None:
        item = self.item_at(index)
        if item is not None and item.data(PathRole) and not item.data(LoadedRole):
            self.tree_model.load_children(item)

    def _on_collapsed(self, index: QModelIndex) -> None:
        item = self.item_at(index)
        if item is not None and item.data(PathRole):
            # Beim nächsten Aufklappen neu einlesen
            item.setData(False, LoadedRole)

    # --- Klick öffnet im Panel ------------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        idx = self.indexAt(event.position().toPoint())
        on_item = idx.isValid() and self.visualRect(idx).contains(event.position().toPoint())
        self._press_index = idx if on_item and event.button() == Qt.MouseButton.LeftButton else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        idx = self.indexAt(event.position().toPoint())
        if self._press_index is not None and idx == self._press_index and event.button() == Qt.MouseButton.LeftButton:
            self.activate(idx)
        self._press_index = None

    def activate(self, idx: QModelIndex) -> None:
        item = self.item_at(idx)
        if item is None:
            return
        path = item.data(PathRole)
        if path:
            self.open_path.emit(path)
        elif item.data(KindRole) == K_DISK and item.rowCount() == 0:
            self.disk_clicked.emit(item.data(DiskRole))
        else:
            self.setExpanded(idx, not self.isExpanded(idx))

    def activate_current(self) -> None:
        if self.currentIndex().isValid():
            self.activate(self.currentIndex())

    # --- Dem Panel folgen (F-233) -------------------------------------------------------------
    def select_path(self, path: str) -> None:
        if not path:
            return
        model = self.tree_model
        if is_trash_uri(path):
            if not model.trash_item.index().isValid():
                return
            idx = model.trash_item.index()
            self.selectionModel().setCurrentIndex(idx, self.selectionModel().SelectionFlag.ClearAndSelect)
            self.scrollTo(idx)
            return
        path = os.path.normpath(path)
        base_item = None
        base_path = ""
        entry = self._mounts.entry_containing(path) if self._mounts is not None else None
        if entry is not None:
            base_item = model.mount_item(entry.mount_point)
            base_path = entry.mount_point
        if base_item is None:
            home = os.path.normpath(str(Path.home()))
            if path == home or path.startswith(home + os.sep):
                base_item, base_path = model.home_item, home
            else:
                base_item, base_path = model.root_item, "/"
                drive = os.path.splitdrive(path)[0]
                if drive:  # Windows: passendes Laufwerk wählen
                    for it in model.root_items:
                        if os.path.splitdrive(it.data(PathRole))[0].upper() == drive.upper():
                            base_item, base_path = it, it.data(PathRole)
                            break
                    else:
                        return
        rel = os.path.relpath(path, base_path) if path != base_path else ""
        parts = [p for p in rel.split(os.sep) if p and p != "."]
        item = base_item
        for name in parts:
            if not item.data(LoadedRole):
                model.load_children(item)
            child = model.find_child(item, name)
            if child is None:
                break
            self.expand(item.index())
            item = child
        idx = item.index()
        self.selectionModel().setCurrentIndex(idx, self.selectionModel().SelectionFlag.ClearAndSelect)
        self.scrollTo(idx)

    # --- Neu einlesen -------------------------------------------------------------------------
    def _expanded_paths(self) -> list[tuple[str, str]]:
        result = []
        stack = [self.tree_model.invisibleRootItem()]
        while stack:
            it = stack.pop()
            for row in range(it.rowCount()):
                child = it.child(row)
                if child is None or not self.isExpanded(child.index()):
                    continue
                result.append((child.data(KindRole) or "", child.data(PathRole) or child.text()))
                stack.append(child)
        return result

    def _restore_expanded(self, expanded: list[tuple[str, str]]) -> None:
        wanted = set(expanded)
        stack = [self.tree_model.invisibleRootItem()]
        while stack:
            it = stack.pop()
            for row in range(it.rowCount()):
                child = it.child(row)
                if child is None:
                    continue
                key = (child.data(KindRole) or "", child.data(PathRole) or child.text())
                if key in wanted:
                    if child.data(PathRole) and not child.data(LoadedRole):
                        self.tree_model.load_children(child)
                    self.expand(child.index())
                    stack.append(child)

    def reload(self, show_hidden: bool | None = None) -> None:
        current = self.current_path()
        expanded = self._expanded_paths()
        if show_hidden is not None:
            self.tree_model.show_hidden = show_hidden
        self.tree_model.build()
        self._expand_sections()
        self._restore_expanded(expanded)
        if current:
            self.select_path(current)

    def _on_mounts_changed(self) -> None:
        current = self.current_path()
        expanded = self._expanded_paths()
        self.tree_model.rebuild_mounts()
        self._expand_sections()
        self._restore_expanded(expanded)
        if current:
            self.select_path(current)

    # --- Ablegen (F-234) ---------------------------------------------------------------------
    def _target(self, event) -> str | None:
        return self.path_of(self.indexAt(event.position().toPoint()))

    def dragEnterEvent(self, event) -> None:
        if FileView._local_paths(event) and FileView._choose_action(event) is not None:
            event.setDropAction(FileView._choose_action(event))
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        paths = FileView._local_paths(event)
        action = FileView._choose_action(event) if paths else None
        target = self._target(event)
        if action is None or not target or target in paths:
            event.ignore()
            return
        event.setDropAction(action)
        event.accept()

    def dropEvent(self, event) -> None:
        paths = FileView._local_paths(event)
        action = FileView._choose_action(event) if paths else None
        target = self._target(event)
        if not paths or action is None or not target:
            event.ignore()
            return
        event.setDropAction(action)
        event.accept()
        self.drop_requested.emit(paths, target, action)
