"""Favoritensystem.

Es gibt genau EINEN Satz Favoriten (``FavoritesModel``). Beide Seitenleisten
zeigen dasselbe Modell in je einer eigenen Ansicht (``FavoritesView``). Dadurch
erscheint jede Änderung sofort auf beiden Seiten, während der
Auf-/Zuklappzustand je Ansicht getrennt bleibt.

Eintragsarten:
* ``group`` – Favoritenordner (nur zur Gliederung, beliebig verschachtelbar)
* ``link``  – Verknüpfung zu einem echten Ordner oder einer Datei
"""

from __future__ import annotations

import json
import os
import uuid

from PySide6.QtCore import QAbstractItemModel, QByteArray, QMimeData, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QPalette
from PySide6.QtWidgets import QAbstractItemView, QApplication, QTreeView

from .config import FAVORITES_FILE, load_json, save_json
from .i18n import t
from .icons import IconProvider

MIME_INTERNAL = "application/x-panepilot-favorites"
NodeRole = Qt.ItemDataRole.UserRole + 1

# Schriftfarben für Favoriten (F-220). None = Standard (folgt dem GNOME-Design).
FAV_COLORS: tuple[tuple[str, str], ...] = (
    ("white", "#FFFFFF"),
    ("gray", "#808080"),
    ("black", "#000000"),
    ("yellow", "#E6C200"),
    ("orange", "#F08000"),
    ("red", "#D00000"),
    ("green", "#008A00"),
    ("turquoise", "#00A0A0"),
    ("blue", "#0050D0"),
)
COLOR_HEX = dict(FAV_COLORS)
STYLE_FLAGS = ("bold", "italic", "underline", "strike")


class FavNode:
    __slots__ = ("id", "kind", "name", "path", "parent", "children", "style")

    def __init__(self, kind: str, name: str, path: str = "", node_id: str | None = None) -> None:
        self.id = node_id or uuid.uuid4().hex
        self.kind = kind
        self.name = name
        self.path = path
        self.parent: FavNode | None = None
        self.children: list[FavNode] = []
        self.style: dict = {}

    @property
    def is_group(self) -> bool:
        return self.kind == "group"

    def row(self) -> int:
        return self.parent.children.index(self) if self.parent else 0

    def is_ancestor_of(self, other: "FavNode") -> bool:
        node = other.parent
        while node is not None:
            if node is self:
                return True
            node = node.parent
        return False

    def to_dict(self) -> dict:
        d = {"id": self.id, "type": self.kind, "name": self.name}
        if self.style:
            d["style"] = dict(self.style)
        if self.is_group:
            d["children"] = [c.to_dict() for c in self.children]
        else:
            d["path"] = self.path
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FavNode | None":
        if not isinstance(d, dict):
            return None
        kind = d.get("type")
        if kind not in ("group", "link"):
            return None
        node = cls(kind, str(d.get("name") or ""), str(d.get("path") or ""), d.get("id") or None)
        if kind == "link" and not node.path:
            return None
        node.style = clean_style(d.get("style"))
        if kind == "group":
            for cd in d.get("children") or []:
                child = cls.from_dict(cd)
                if child is not None:
                    child.parent = node
                    node.children.append(child)
        return node


def clean_style(raw) -> dict:
    style = {}
    if isinstance(raw, dict):
        for flag in STYLE_FLAGS:
            if raw.get(flag) is True:
                style[flag] = True
        if raw.get("color") in COLOR_HEX:
            style["color"] = raw["color"]
    return style


class FavoritesModel(QAbstractItemModel):
    changed = Signal()

    def __init__(self, icons: IconProvider, autosave: bool = True, parent=None, file: str = FAVORITES_FILE) -> None:
        super().__init__(parent)
        self.file = file  # relativ zum Konfigurationsordner, z. B. "Favoriten/Standard.json"
        self._icons = icons
        self._root = FavNode("group", "", node_id="root")
        self._autosave = autosave
        for sig in (self.rowsInserted, self.rowsRemoved, self.rowsMoved, self.dataChanged):
            sig.connect(self._on_changed)

    # --- Laden/Speichern ---------------------------------------------------------------
    def load(self) -> None:
        data = load_json(self.file, {"version": 1, "items": []})
        self.load_dict(data)

    def load_dict(self, data: dict) -> None:
        self.beginResetModel()
        self._root = FavNode("group", "", node_id="root")
        items = data.get("items", []) if isinstance(data, dict) else []
        for d in items:
            node = FavNode.from_dict(d)
            if node is not None:
                node.parent = self._root
                self._root.children.append(node)
        self.endResetModel()

    def to_dict(self) -> dict:
        return {"version": 1, "items": [c.to_dict() for c in self._root.children]}

    def save(self) -> None:
        save_json(self.file, self.to_dict())

    def _on_changed(self, *_args) -> None:
        if self._autosave:
            self.save()
        self.changed.emit()

    # --- Knoten -----------------------------------------------------------------------
    @property
    def root(self) -> FavNode:
        return self._root

    def node(self, index: QModelIndex) -> FavNode:
        if index.isValid():
            return index.internalPointer()
        return self._root

    def index_for(self, node: FavNode) -> QModelIndex:
        if node is self._root or node.parent is None:
            return QModelIndex()
        return self.createIndex(node.row(), 0, node)

    def find(self, node_id: str) -> FavNode | None:
        stack = [self._root]
        while stack:
            n = stack.pop()
            if n.id == node_id:
                return n
            stack.extend(n.children)
        return None

    def all_groups(self) -> list[FavNode]:
        result, stack = [], list(self._root.children)
        while stack:
            n = stack.pop()
            if n.is_group:
                result.append(n)
                stack.extend(n.children)
        return result

    def insert_node(self, node: FavNode, parent: FavNode, row: int = -1) -> FavNode:
        if not parent.is_group:
            parent = parent.parent or self._root
        if row < 0 or row > len(parent.children):
            row = len(parent.children)
        self.beginInsertRows(self.index_for(parent), row, row)
        node.parent = parent
        parent.children.insert(row, node)
        self.endInsertRows()
        return node

    def add_link(self, path: str, parent: FavNode | None = None, row: int = -1, name: str | None = None) -> FavNode:
        path = os.path.abspath(path)
        label = name or os.path.basename(path.rstrip(os.sep)) or path
        return self.insert_node(FavNode("link", label, path), parent or self._root, row)

    def add_group(self, name: str, parent: FavNode | None = None, row: int = -1) -> FavNode:
        return self.insert_node(FavNode("group", name), parent or self._root, row)

    def remove_node(self, node: FavNode) -> None:
        if node is self._root or node.parent is None:
            return
        parent = node.parent
        row = node.row()
        self.beginRemoveRows(self.index_for(parent), row, row)
        parent.children.pop(row)
        node.parent = None
        self.endRemoveRows()

    def move_node(self, node: FavNode, new_parent: FavNode, row: int) -> bool:
        """Verschiebt einen Eintrag. row = Position im Zielordner VOR dem Verschieben."""
        if node is self._root or node.parent is None:
            return False
        if not new_parent.is_group:
            return False
        if node is new_parent or node.is_ancestor_of(new_parent):
            return False
        old_parent = node.parent
        old_row = node.row()
        if row < 0 or row > len(new_parent.children):
            row = len(new_parent.children)
        if old_parent is new_parent and row in (old_row, old_row + 1):
            return False
        if not self.beginMoveRows(self.index_for(old_parent), old_row, old_row, self.index_for(new_parent), row):
            return False
        old_parent.children.pop(old_row)
        if old_parent is new_parent and row > old_row:
            row -= 1
        node.parent = new_parent
        new_parent.children.insert(row, node)
        self.endMoveRows()
        return True

    def rename_node(self, node: FavNode, name: str) -> None:
        name = name.strip()
        if not name or node is self._root:
            return
        node.name = name
        idx = self.index_for(node)
        self.dataChanged.emit(idx, idx)

    def insertion_point(self, selected: FavNode | None) -> tuple[FavNode, int]:
        """Einfügestelle gemäß Anforderung F-90 (Strg+B).

        * Favoritenordner markiert → hinein (ans Ende)
        * einzelner Favorit markiert → direkt dahinter
        * nichts markiert → oberste Ebene (ans Ende)
        """
        if selected is None or selected is self._root:
            return self._root, len(self._root.children)
        if selected.is_group:
            return selected, len(selected.children)
        parent = selected.parent or self._root
        return parent, selected.row() + 1

    def link_state(self, node: FavNode) -> str:
        """'ok', 'unmounted' (liegt in nicht eingebundener Freigabe) oder 'broken'."""
        if node.is_group:
            return "ok"
        mounts = self._icons.mounts
        if mounts is not None:
            entry = mounts.needs_mount(node.path)
            if entry is not None:
                return "unmounted"
        return "ok" if os.path.exists(node.path) else "broken"

    def target_exists(self, node: FavNode) -> bool:
        return self.link_state(node) != "broken"

    def update_node(self, node: FavNode, name: str, path: str, style: dict) -> None:
        if node is self._root:
            return
        if name.strip():
            node.name = name.strip()
        if not node.is_group and path.strip():
            node.path = os.path.abspath(os.path.expanduser(path.strip()))
        node.style = clean_style(style)
        idx = self.index_for(node)
        self.dataChanged.emit(idx, idx)

    def refresh_states(self) -> None:
        """Symbole/Farben neu zeichnen (z. B. nachdem eine Freigabe eingebunden wurde)."""
        self.layoutChanged.emit()

    # --- Qt-Modell ----------------------------------------------------------------------
    def index(self, row: int, column: int, parent=QModelIndex()) -> QModelIndex:
        if column != 0:
            return QModelIndex()
        pnode = self.node(parent)
        if 0 <= row < len(pnode.children):
            return self.createIndex(row, 0, pnode.children[row])
        return QModelIndex()

    def parent(self, index: QModelIndex = QModelIndex()) -> QModelIndex:  # type: ignore[override]
        if not index.isValid():
            return QModelIndex()
        node: FavNode = index.internalPointer()
        if node.parent is None or node.parent is self._root:
            return QModelIndex()
        return self.index_for(node.parent)

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid() and parent.column() != 0:
            return 0
        return len(self.node(parent).children)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 1

    def hasChildren(self, parent=QModelIndex()) -> bool:
        node = self.node(parent)
        return node.is_group and bool(node.children)

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node: FavNode = index.internalPointer()
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return node.name
        if role == Qt.ItemDataRole.DecorationRole:
            if node.is_group:
                return self._icons.favorite_group()
            state = self.link_state(node)
            if state == "broken":
                return self._icons.no_entry()
            if state == "unmounted":
                entry = self._icons.mounts.needs_mount(node.path)
                return self._icons.mount_icon(entry)
            if os.path.isdir(node.path):
                return self._icons.dir_icon(node.path)
            return self._icons.for_file(node.path)
        if role == Qt.ItemDataRole.ToolTipRole and not node.is_group:
            state = self.link_state(node)
            if state == "broken":
                return t("favorites.missing_tooltip", path=node.path)
            if state == "unmounted":
                return t("favorites.unmounted_tooltip", path=node.path)
            return node.path
        if role == Qt.ItemDataRole.ForegroundRole:
            if not node.is_group and self.link_state(node) == "broken":
                # Defekter Link: grau – eine eigene Farbe tritt zurück (F-224)
                return QApplication.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
            color = node.style.get("color")
            if color in COLOR_HEX:
                return QColor(COLOR_HEX[color])
            return None
        if role == Qt.ItemDataRole.FontRole:
            if not node.style:
                return None
            font = QApplication.font()
            font.setBold(bool(node.style.get("bold")))
            font.setItalic(bool(node.style.get("italic")))
            font.setUnderline(bool(node.style.get("underline")))
            font.setStrikeOut(bool(node.style.get("strike")))
            return font
        if role == NodeRole:
            return node
        return None

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if role != Qt.ItemDataRole.EditRole or not index.isValid():
            return False
        name = str(value).strip()
        if not name:
            return False
        node: FavNode = index.internalPointer()
        node.name = name
        self.dataChanged.emit(index, index)
        return True

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.ItemIsDropEnabled
        node: FavNode = index.internalPointer()
        flags = (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                 | Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsEditable)
        if node.is_group:
            flags |= Qt.ItemFlag.ItemIsDropEnabled
        return flags

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction | Qt.DropAction.CopyAction | Qt.DropAction.LinkAction

    def supportedDragActions(self):
        return Qt.DropAction.MoveAction

    def mimeTypes(self) -> list[str]:
        return [MIME_INTERNAL, "text/uri-list"]

    def mimeData(self, indexes) -> QMimeData:
        ids = []
        for idx in indexes:
            if idx.isValid():
                node: FavNode = idx.internalPointer()
                if node.id not in ids:
                    ids.append(node.id)
        md = QMimeData()
        md.setData(MIME_INTERNAL, QByteArray(json.dumps(ids).encode("utf-8")))
        return md

    def canDropMimeData(self, data, action, row, column, parent) -> bool:
        if data.hasFormat(MIME_INTERNAL):
            target = self.node(parent)
            for nid in self._ids_from(data):
                node = self.find(nid)
                if node is None or node is target or node.is_ancestor_of(target):
                    return False
            return True
        return data.hasUrls() and any(u.isLocalFile() for u in data.urls())

    @staticmethod
    def _ids_from(data) -> list[str]:
        try:
            return list(json.loads(bytes(data.data(MIME_INTERNAL)).decode("utf-8")))
        except (ValueError, TypeError):
            return []

    def dropMimeData(self, data, action, row, column, parent) -> bool:
        target = self.node(parent)
        if not target.is_group:
            # Ablegen direkt AUF einen Favoriten → dahinter einfügen
            row = target.row() + 1
            target = target.parent or self._root
        if row < 0:
            row = len(target.children)
        if data.hasFormat(MIME_INTERNAL):
            moved = False
            for nid in self._ids_from(data):
                node = self.find(nid)
                if node is None:
                    continue
                old_parent, old_row = node.parent, node.row()
                if self.move_node(node, target, row):
                    moved = True
                    # Nächstes Element hinter dem eben verschobenen einsortieren
                    row = node.row() + 1
                elif old_parent is target and row in (old_row, old_row + 1):
                    row = old_row + 1
            return moved
        if data.hasUrls():
            added = False
            for url in data.urls():
                if url.isLocalFile():
                    self.add_link(url.toLocalFile(), target, row)
                    row += 1
                    added = True
            return added
        return False


class FavoritesView(QTreeView):
    """Eine Ansicht auf das gemeinsame Favoritenmodell (eine je Seitenleiste)."""

    open_link = Signal(object)  # FavNode
    focus_entered = Signal()

    def __init__(self, model: FavoritesModel, parent=None) -> None:
        super().__init__(parent)
        self.setModel(model)
        self.setHeaderHidden(True)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setExpandsOnDoubleClick(False)
        self.setAnimated(False)
        self._press_index = None
        self._dragging = False

    @property
    def fav_model(self) -> FavoritesModel:
        return self.model()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focus_entered.emit()

    # --- Auswahl ----------------------------------------------------------------------
    def selected_node(self) -> FavNode | None:
        rows = self.selectionModel().selectedRows()
        if not rows:
            return None
        return self.fav_model.node(rows[0])

    def select_node(self, node: FavNode) -> None:
        idx = self.fav_model.index_for(node)
        if idx.isValid():
            parent = idx.parent()
            while parent.isValid():
                self.expand(parent)
                parent = parent.parent()
            self.setCurrentIndex(idx)
            self.scrollTo(idx)

    # --- Auf-/Zuklappzustand (je Ansicht getrennt) ---------------------------------------
    def expanded_ids(self) -> list[str]:
        model = self.fav_model
        return [g.id for g in model.all_groups() if self.isExpanded(model.index_for(g))]

    def restore_expanded(self, ids: list[str]) -> None:
        model = self.fav_model
        wanted = set(ids or [])
        for g in model.all_groups():
            if g.id in wanted:
                self.setExpanded(model.index_for(g), True)

    # --- Öffnen per einfachem Klick (wie Firefox-Lesezeichen) -------------------------------
    def mousePressEvent(self, event) -> None:
        self._dragging = False
        idx = self.indexAt(event.position().toPoint())
        on_item = idx.isValid() and self.visualRect(idx).contains(event.position().toPoint())
        self._press_index = idx if on_item and event.button() == Qt.MouseButton.LeftButton else None
        if not idx.isValid():
            self.clearSelection()
            self.setCurrentIndex(QModelIndex())
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        idx = self.indexAt(event.position().toPoint())
        if (
            self._press_index is not None
            and not self._dragging
            and idx.isValid()
            and idx == self._press_index
            and event.button() == Qt.MouseButton.LeftButton
            and not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier))
        ):
            self.activate(idx)
        self._press_index = None

    def activate(self, idx: QModelIndex) -> None:
        node = self.fav_model.node(idx)
        if node.is_group:
            self.setExpanded(idx, not self.isExpanded(idx))
        else:
            self.open_link.emit(node)

    def activate_current(self) -> None:
        idx = self.currentIndex()
        if idx.isValid():
            self.activate(idx)

    # --- Ziehen / Ablegen ---------------------------------------------------------------
    def startDrag(self, supported_actions) -> None:
        self._dragging = True
        indexes = self.selectedIndexes()
        if not indexes:
            return
        # Nur interne Daten: ein Favorit, der versehentlich über einem Panel losgelassen
        # wird, soll dort nichts kopieren.
        md = self.fav_model.mimeData(indexes)
        drag = QDrag(self)
        drag.setMimeData(md)
        icon = indexes[0].data(Qt.ItemDataRole.DecorationRole)
        if icon is not None:
            drag.setPixmap(icon.pixmap(24, 24))
        # Bewusst kein Entfernen nach dem Ziehen: das Modell verschiebt selbst.
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction | Qt.DropAction.LinkAction,
                  Qt.DropAction.MoveAction)

    def _external_action(self, event):
        possible = event.possibleActions()
        if possible & Qt.DropAction.LinkAction:
            return Qt.DropAction.LinkAction
        if possible & Qt.DropAction.CopyAction:
            return Qt.DropAction.CopyAction
        return None

    def dragEnterEvent(self, event) -> None:
        md = event.mimeData()
        if md.hasFormat(MIME_INTERNAL) or md.hasUrls():
            super().dragEnterEvent(event)
            self._fix_action(event)
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        super().dragMoveEvent(event)
        self._fix_action(event)

    def _fix_action(self, event) -> None:
        md = event.mimeData()
        if not event.isAccepted():
            return
        if md.hasFormat(MIME_INTERNAL):
            event.setDropAction(Qt.DropAction.MoveAction)
        else:
            # Von außen wird immer nur eine Verknüpfung angelegt – das Original bleibt unberührt.
            action = self._external_action(event)
            if action is None:
                event.ignore()
            else:
                event.setDropAction(action)

    def dropEvent(self, event) -> None:
        md = event.mimeData()
        internal = md.hasFormat(MIME_INTERNAL)
        if not internal:
            action = self._external_action(event)
            if action is None:
                event.ignore()
                return
            event.setDropAction(action)
        super().dropEvent(event)
        # Qt darf die Quelle nach einem "Move" nicht löschen – das Modell hat bereits verschoben.
        if internal:
            event.setDropAction(Qt.DropAction.CopyAction)
