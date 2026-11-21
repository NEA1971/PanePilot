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
    QSize,
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
    QListView,
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


class _FileListMixin:
    """Gemeinsames Ziehen und Ablegen von Liste und Symbolansicht (v1.19)."""

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid():
                self.tab_open_requested.emit(index.row())
                event.accept()
                return
        super().mouseReleaseEvent(event)

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

    def _into_archive(self) -> bool:
        model = self.model() if callable(getattr(self, "model", None)) else None
        return bool(getattr(model, "archive_mode", False))

    def dragEnterEvent(self, event) -> None:
        if self._into_archive():  # v2.2: Archiv ist nur lesbar (L-3209)
            event.ignore()
            return
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
        if self._into_archive():  # v2.2: Archiv ist nur lesbar (L-3209)
            event.ignore()
            return
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
        if self._into_archive():  # v2.2: Archiv ist nur lesbar (L-3209)
            event.ignore()
            return
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


class FileView(_FileListMixin, QTreeView):
    """Dateiliste mit Drag & Drop für Dateien."""

    drop_requested = Signal(list, str, object)  # Pfade, Zielordner, Qt.DropAction
    remote_drop_requested = Signal(object, str, object)  # {side, paths, dirs} aus einem Server-Fenster (v1.3)
    focus_entered = Signal()
    tab_open_requested = Signal(int)  # Zeile – mittlere Maustaste auf einen Ordner (v2.1, L-3104)

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


# --- Symbolansicht (v1.19, L-1910 ff.) ------------------------------------------------------------------------
ICON_SIZES = (64, 128, 256)  # klein, mittel, groß (L-1911)
NAME_LINES = 2  # Name unter dem Bild, höchstens zwei Zeilen (L-1913)


class IconDelegate(RenameDelegate):
    """Zeichnet Vorschaubild bzw. Dateisymbol mit dem Namen darunter."""

    PAD = 4

    def __init__(self, view: "IconView") -> None:
        super().__init__(view)
        self.view = view

    def _metrics(self, option):
        from PySide6.QtGui import QFontMetrics

        return QFontMetrics(option.font)

    def cell_size(self, option=None):
        from PySide6.QtCore import QSize

        fm = self.view.fontMetrics()
        s = self.view.icon_px
        width = max(s + 2 * self.PAD, fm.averageCharWidth() * 14)
        return QSize(width + 2 * self.PAD, s + 3 * self.PAD + NAME_LINES * fm.height() + self.PAD)

    def sizeHint(self, option, index):
        return self.cell_size(option)

    def _rects(self, rect):
        from PySide6.QtCore import QRect

        s = self.view.icon_px
        icon = QRect(rect.x() + (rect.width() - s) // 2, rect.y() + self.PAD, s, s)
        text = QRect(rect.x() + self.PAD, icon.bottom() + 1 + self.PAD, rect.width() - 2 * self.PAD,
                     rect.bottom() - icon.bottom() - 2 * self.PAD)
        return icon, text

    def _lines(self, text: str, fm, width: int) -> list[str]:
        from PySide6.QtGui import QTextLayout, QTextOption

        layout = QTextLayout(text, self.view.font())
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(opt)
        layout.beginLayout()
        lines = []
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            lines.append((line.textStart(), line.textLength()))
        layout.endLayout()
        out = []
        for i, (start, length) in enumerate(lines[:NAME_LINES]):
            if i == NAME_LINES - 1 and len(lines) > NAME_LINES:
                out.append(fm.elidedText(text[start:], Qt.TextElideMode.ElideMiddle, width))
            else:
                out.append(text[start:start + length].strip())
        return out

    def paint(self, painter, option, index):
        from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = self.view.style()
        painter.save()
        # Hintergrund samt Markierung wie in der Liste
        opt_bg = QStyleOptionViewItem(opt)
        opt_bg.text = ""
        opt_bg.icon = type(opt.icon)()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, opt_bg, painter, self.view)
        icon_rect, text_rect = self._rects(opt.rect)
        pix = self.view.thumbnail_for(index)
        if pix is not None and not pix.isNull():
            dpr = pix.devicePixelRatio() or 1
            w, h = pix.width() / dpr, pix.height() / dpr
            scale = min(icon_rect.width() / max(w, 1), icon_rect.height() / max(h, 1), 1.0)
            tw, th = int(w * scale), int(h * scale)
            from PySide6.QtCore import QRect

            target = QRect(icon_rect.x() + (icon_rect.width() - tw) // 2,
                           icon_rect.y() + (icon_rect.height() - th) // 2, tw, th)
            painter.setRenderHint(painter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(target, pix)
            if opt.state & QStyle.StateFlag.State_Selected:  # markierte Vorschaubilder gut erkennbar umrahmen
                from PySide6.QtGui import QPen

                painter.setPen(QPen(opt.palette.color(opt.palette.ColorRole.Highlight), 3))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(target.adjusted(-1, -1, 1, 1))
        else:
            icon = index.data(Qt.ItemDataRole.DecorationRole)
            if icon is not None:
                icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter)
        fm = self._metrics(opt)
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        role = opt.palette.ColorRole.HighlightedText if selected else opt.palette.ColorRole.Text
        color = opt.palette.color(role)
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        if fg is not None and not selected:
            color = fg.color() if hasattr(fg, "color") else fg
        painter.setPen(color)
        painter.setFont(opt.font)
        y = text_rect.y()
        for line in self._lines(str(index.data(Qt.ItemDataRole.DisplayRole) or ""), fm, text_rect.width()):
            painter.drawText(text_rect.x(), y, text_rect.width(), fm.height(),
                             int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop), line)
            y += fm.height()
        painter.restore()

    def updateEditorGeometry(self, editor, option, index):
        _icon, text = self._rects(option.rect)
        h = editor.sizeHint().height()
        editor.setGeometry(option.rect.x(), text.y(), max(option.rect.width(), 160), h)


class IconView(_FileListMixin, QListView):
    """Symbolansicht: gleiches Modell und gleiche Markierung wie die Liste (L-1913)."""

    drop_requested = Signal(list, str, object)
    remote_drop_requested = Signal(object, str, object)
    focus_entered = Signal()
    tab_open_requested = Signal(int)  # Zeile – mittlere Maustaste auf einen Ordner (v2.1, L-3104)
    zoom_requested = Signal(int)  # +1 größer, -1 kleiner (Strg+Mausrad, L-1911)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.icon_px = 128
        self.thumbs = None  # ThumbnailLoader, beim ersten Zeichnen
        self.parent_bar = None  # Zeile „..“ über den Symbolen (v1.19.1)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(200)
        self.setUniformItemSizes(True)
        self.setWrapping(True)
        self.setWordWrap(True)
        self.setSpacing(2)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionRectVisible(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.delegate = IconDelegate(self)
        self.setItemDelegate(self.delegate)
        self.set_icon_px(128)

    def set_icon_px(self, px: int) -> None:
        self.icon_px = px
        self.setIconSize(QSize(px, px))
        self.setGridSize(self.delegate.cell_size())
        self.scheduleDelayedItemsLayout()
        self.viewport().update()

    def thumbnail_for(self, index):
        """Vorschaubild aus dem Speicher – fehlt es, wird es im Hintergrund erzeugt (L-1912)."""
        model = self.model()
        entry = model.entry(index.row()) if model is not None else None
        if entry is None or entry.is_dir or entry.remote or model.trash_mode:
            return None
        from . import thumbnails

        if self.thumbs is None:
            self.thumbs = thumbnails.loader()
            self.thumbs.ready.connect(self._thumb_ready)
            model.modelReset.connect(self.thumbs.drop_pending)
        if not self.thumbs.wanted(entry.path):
            return None
        return self.thumbs.get(entry.path, entry.mtime, self.icon_px)

    def _thumb_ready(self, _path: str) -> None:
        if self.isVisible():
            self._repaint_timer().start()

    def _repaint_timer(self) -> QTimer:
        timer = getattr(self, "_rt", None)
        if timer is None:
            timer = self._rt = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(60)
            timer.timeout.connect(self.viewport().update)
        return timer

    def keyPressEvent(self, event) -> None:
        # Pfeil nach oben in der ersten Reihe: in die Zeile „..“ darüber (v1.19.1)
        if (event.key() == Qt.Key.Key_Up and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                and self.parent_bar is not None and self.parent_bar.isVisible()):
            cur = self.currentIndex()
            nxt = self.moveCursor(QAbstractItemView.CursorAction.MoveUp, event.modifiers())
            if not cur.isValid() or not nxt.isValid() or nxt.row() == cur.row():
                self.parent_bar.take_cursor()
                return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_requested.emit(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)


class ParentBar(_FileListMixin, QListView):
    """Die Zeile „..“ bleibt in der Symbolansicht klein oben wie in der Liste (v1.19.1)."""

    drop_requested = Signal(list, str, object)
    remote_drop_requested = Signal(object, str, object)
    focus_entered = Signal()
    tab_open_requested = Signal(int)  # Zeile – mittlere Maustaste auf einen Ordner (v2.1, L-3104)

    def __init__(self, icons_view: IconView, parent=None) -> None:
        super().__init__(parent)
        self.icons_view = icons_view
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def startDrag(self, supported_actions) -> None:  # „..“ lässt sich nicht ziehen
        return

    def update_rows(self) -> bool:
        """Nur die Zeile „..“ zeigen; liefert, ob es sie gibt."""
        model = self.model()
        n = model.rowCount() if model is not None else 0
        has_parent = n > 0 and model.entry(0) is not None and model.entry(0).is_parent
        for row in range(n):
            self.setRowHidden(row, not (row == 0 and has_parent))
        if has_parent:
            h = self.sizeHintForRow(0)
            self.setFixedHeight(max(h, self.fontMetrics().height() + 4) + 2)
        return has_parent

    def take_cursor(self) -> None:
        model = self.model()
        self.setFocus()
        self.selectionModel().setCurrentIndex(
            model.index(0, self.modelColumn()),
            QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Right, Qt.Key.Key_PageDown, Qt.Key.Key_End):
            view = self.icons_view
            model = view.model()
            row = next((r for r in range(model.rowCount()) if not view.isRowHidden(r)), -1)
            if row >= 0:
                view.setFocus()
                view.selectionModel().setCurrentIndex(
                    model.index(row, view.modelColumn()),
                    QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
                view.scrollTo(view.currentIndex())
            return
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Left, Qt.Key.Key_PageUp, Qt.Key.Key_Home):
            return
        super().keyPressEvent(event)


class FilePanel(QWidget):
    focus_entered = Signal()
    tab_open_requested = Signal(int)  # Zeile – mittlere Maustaste auf einen Ordner (v2.1, L-3104)
    path_changed = Signal(str)
    context_menu_requested = Signal(QPoint)
    drop_requested = Signal(list, str, object)
    remote_drop_requested = Signal(object, str, object)
    open_file_requested = Signal(str)
    remote_open_requested = Signal(object)  # Entry auf dem Server (v1.3)
    archive_open_requested = Signal(object)  # Datei in einem Archiv öffnen (v2.2)
    remote_closed = Signal(object)  # Sitzung wurde getrennt
    message = Signal(str, str)  # Titel, Text
    columns_changed = Signal()  # Spalten verschoben/Breite/ein-/ausgeblendet/Ausrichtung
    profile_chosen = Signal(str)  # Spaltenprofil im Kopf-Kontextmenü gewählt
    new_profile_requested = Signal()
    filter_changed = Signal()
    icon_size_changed = Signal(int)  # v1.19
    tabs_changed = Signal()  # v2.1: Reiter geöffnet/geschlossen/gewechselt/gesperrt
    tab_menu_requested = Signal(int, object)  # Index, globale Position

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
        self.archive = None  # geöffnetes Archiv (v2.2), siehe archivefs.ArchiveIndex
        self.archive_loader = None  # vom Hauptfenster: Pfad → ArchiveIndex | None (mit Passwort/Fortschritt)
        self.open_archives_inside = True  # L-3206: Doppelklick öffnet Archive in PanePilot
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
        self.view.tab_open_requested.connect(self._open_row_in_tab)
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
        # Symbolansicht (v1.19): gleiches Modell, gleiche Markierung und gleicher Cursor wie die Liste
        self.icon_mode = False
        self.icon_view = IconView(self)
        self.icon_view.setModel(self.model)
        own = self.icon_view.selectionModel()
        self.icon_view.setSelectionModel(self.view.selectionModel())
        own.deleteLater()
        self.icon_view.setModelColumn(self.model.icon_column)
        self.icon_view.focus_entered.connect(self.focus_entered)
        self.icon_view.doubleClicked.connect(self._on_double_click)
        self.icon_view.customContextMenuRequested.connect(
            lambda pos: self.context_menu_requested.emit(self.icon_view.viewport().mapToGlobal(pos))
        )
        self.icon_view.drop_requested.connect(self.drop_requested)
        self.icon_view.tab_open_requested.connect(self._open_row_in_tab)
        self.icon_view.remote_drop_requested.connect(self.remote_drop_requested)
        self.icon_view.zoom_requested.connect(self.zoom_icons)
        self.icon_view.setFrameShape(QFrame.Shape.NoFrame)
        self.parent_bar = ParentBar(self.icon_view)
        self.parent_bar.setModel(self.model)
        own = self.parent_bar.selectionModel()
        self.parent_bar.setSelectionModel(self.view.selectionModel())
        own.deleteLater()
        self.parent_bar.setModelColumn(self.model.icon_column)
        self.parent_bar.focus_entered.connect(self.focus_entered)
        self.parent_bar.doubleClicked.connect(self._on_double_click)
        self.parent_bar.customContextMenuRequested.connect(
            lambda pos: self.context_menu_requested.emit(self.parent_bar.viewport().mapToGlobal(pos))
        )
        self.parent_bar.drop_requested.connect(self.drop_requested)
        self.parent_bar.tab_open_requested.connect(self._open_row_in_tab)
        self.parent_bar.remote_drop_requested.connect(self.remote_drop_requested)
        self.icon_view.parent_bar = self.parent_bar
        # Rahmen um beide wie bei der Liste
        self.icon_box = QFrame(self)
        self.icon_box.setFrameShape(QFrame.Shape.StyledPanel)
        box = QVBoxLayout(self.icon_box)
        box.setContentsMargins(1, 1, 1, 1)
        box.setSpacing(0)
        box.addWidget(self.parent_bar)
        box.addWidget(self.icon_view, 1)
        self.icon_box.setAutoFillBackground(True)
        self.icon_box.setBackgroundRole(self.icon_view.viewport().backgroundRole())
        self.icon_box.hide()
        for sig in (self.model.modelReset, self.model.layoutChanged, self.model.rowsInserted,
                    self.model.rowsRemoved):
            sig.connect(self._update_parent_row)
        self.view.selectionModel().currentChanged.connect(self._sync_icon_focus)

        self.status = QLabel(self)
        self.status.setObjectName("panelStatus")
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        # Reiter (v2.1, L-3100 ff.)
        from .paneltabs import PanelTabBar

        self.tab_bar = PanelTabBar(self)
        self.tab_bar.currentChanged.connect(self._tab_switched)
        self.tab_bar.tabMoved.connect(lambda *_a: self.tabs_changed.emit())
        self.tab_bar.new_requested.connect(lambda: self.new_tab())
        self.tab_bar.close_requested.connect(self.close_tab)
        self.tab_bar.menu_requested.connect(self.tab_menu_requested)
        self.tabs_always = False  # Einstellung „Reiterleiste immer anzeigen“
        self._tab_index = -1  # Reiter, dessen Zustand gerade angezeigt wird
        self._applying_tab = False
        self.tab_bar.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.tab_bar)
        layout.addWidget(self.header)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.icon_box, 1)
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
        self._locked = False  # während „Mehrfach umbenennen“: kein Ordnerwechsel (F-706)

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(lambda _p: self._refresh_timer.start())
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self.refresh)
        self.path_changed.connect(self._update_tab_title)

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

    # --- Archive (v2.2, L-3205 ff.) ------------------------------------------------------------
    @property
    def in_archive(self) -> bool:
        return self.model.archive_mode

    def _load_index(self, archive: str):
        from . import archivefs

        idx = archivefs.cached(archive)
        if idx is not None:
            return idx
        if self.archive_loader is not None:
            return self.archive_loader(archive)
        try:
            idx = archivefs.read_index(archive)
        except Exception as exc:  # noqa: BLE001
            self.message.emit(t("archive.title"), str(exc))
            return None
        archivefs.remember(idx)
        return idx

    def _navigate_archive(self, archive: str, inner: str, select_name: str | None, add_history: bool) -> bool:
        from . import archivefs

        idx = self._load_index(archive)
        if idx is None:
            return False
        items = idx.listdir(inner)
        while items is None and inner:  # Ordner gibt es (nicht mehr): nächsthöheren nehmen
            inner = inner.rpartition("/")[0]
            items = idx.listdir(inner)
        if items is None:
            return False
        self.archive = idx
        self.model.load_archive(archive, inner, items)
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        path = archivefs.join(archive, inner)
        self._add_history(path, add_history)
        self.path_edit.setText(path)
        self._update_filter_style()
        self._free_text = ""
        self._select_after_load(select_name)
        self._update_status()
        self.path_changed.emit(path)
        return True

    def archive_inner(self, path: str | None = None) -> str:
        """Innerer Pfad eines Eintrags bzw. des aktuellen Ordners im geöffneten Archiv."""
        path = self.current_path if path is None else path
        if self.archive is None:
            return ""
        a = self.archive.archive
        return path[len(a) + 1:] if path.startswith(a + "/") else ""

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
        self._update_tab_bar()
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
        self._update_tab_bar()
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

    # --- Reiter (v2.1, L-3100 ff.) ---------------------------------------------------------------------
    def _tabs_blocked(self) -> bool:
        """Werkzeug läuft (Suche, Umbenennen, Meta-Wizard, Synchronisieren) oder Server verbunden (L-3106)."""
        return bool(self._locked or self.search_mode or self.preview.isVisible()
                    or getattr(self, "_custom_view", None) is not None or self.remote is not None)

    def _update_tab_bar(self) -> None:
        bar = self.tab_bar
        bar.setVisible(bar.count() > 1 or (self.tabs_always and bar.count() > 0))
        bar.setEnabled(not self._tabs_blocked())

    def _tab_state(self, index: int):
        return self.tab_bar.tabData(index) if 0 <= index < self.tab_bar.count() else None

    def _tab_is_locked(self) -> bool:
        st = self._tab_state(self.tab_bar.currentIndex())
        return bool(st is not None and st.locked)

    def capture_tab_state(self):
        from .paneltabs import TabState

        history, pos = self.history_state()
        col, order = self.sort_state()
        old = self._tab_state(self._tab_index)
        return TabState(self.current_path, history, pos, (col, order), self.filter_spec, self._filter_on,
                        self.icon_mode, self.icon_size, bool(old is not None and old.locked))

    def _store_current_tab(self) -> None:
        if 0 <= self._tab_index < self.tab_bar.count() and self.current_path and not self.search_mode:
            self.tab_bar.setTabData(self._tab_index, self.capture_tab_state())

    def apply_tab_state(self, st, select_name: str | None = None) -> None:
        self._applying_tab = True
        try:
            self.set_sort_state(*st.sort)
            self.filter_spec = st.filter_spec
            self._filter_on = bool(st.filter_on and st.filter_spec is not None)
            self.model.accept = self.filter_spec.accepts() if self.filter_active else None
            self.set_icon_size(st.icon_size)
            self.set_icon_mode(st.icon_mode)
            path = st.path
            if getattr(self, "_restoring_tabs", False) and self.mounts is not None and \
                    self.mounts.needs_mount(path) is not None:
                path = os.path.expanduser("~")  # beim Start keine Freigabe von selbst einhängen (F-500)
            if getattr(self, "_restoring_tabs", False) and not os.path.isdir(path):
                from . import archivefs

                inside = archivefs.split_path(path)
                if inside is not None:  # v2.2: beim Start nicht ins Archiv (evtl. Passwort), nur daneben
                    select_name, path = os.path.basename(inside[0]), os.path.dirname(inside[0])
            if not self.navigate(path, select_name=select_name, add_history=False):
                self.navigate(nearest_existing_dir(path) if not is_remote_uri(path) else os.path.expanduser("~"),
                              add_history=False)
            hist = st.history or [self.current_path]
            self.set_history_state(hist, st.pos if st.history else 0)
            self.filter_changed.emit()
        finally:
            self._applying_tab = False

    def ensure_first_tab(self) -> None:
        """Der erste Reiter entsteht mit dem ersten Ordner."""
        if self.tab_bar.count() == 0:
            self.tab_bar.blockSignals(True)
            i = self.tab_bar.addTab("")
            self.tab_bar.blockSignals(False)
            self._tab_index = i
            self._store_current_tab()
            self._update_tab_title(self.current_path)
            self._update_tab_bar()

    def new_tab(self, path: str | None = None, activate: bool = True, select_name: str | None = None,
                at: int | None = None) -> int:
        """Strg+T: neuer Reiter neben dem aktuellen, mit dem aktuellen bzw. dem angegebenen Ordner (L-3104)."""
        if self._tabs_blocked():
            return -1
        self.ensure_first_tab()
        self._store_current_tab()
        base = self._tab_state(self._tab_index) or self.capture_tab_state()
        st = base.copy_for(path or self.current_path)
        from .paneltabs import tab_title

        self.tab_bar.blockSignals(True)
        i = self.tab_bar.insertTab(self.tab_bar.currentIndex() + 1 if at is None else at, tab_title(st.path))
        self.tab_bar.setTabData(i, st)
        self.tab_bar.setTabToolTip(i, st.path)
        self.tab_bar.blockSignals(False)
        if activate:
            self.tab_bar.setCurrentIndex(i)  # → _tab_switched
            if select_name:
                self._select_name_later(select_name)
        self._update_tab_bar()
        self.tabs_changed.emit()
        return i

    def close_tab(self, index: int | None = None) -> bool:
        """Strg+W; der letzte Reiter bleibt."""
        bar = self.tab_bar
        index = bar.currentIndex() if index is None else index
        if bar.count() <= 1 or not 0 <= index < bar.count() or self._tabs_blocked():
            return False
        current = index == bar.currentIndex()
        if current:
            self._tab_index = -1  # Zustand nicht mehr speichern
        else:
            self._store_current_tab()
        bar.removeTab(index)  # wählt bei Bedarf den Nachbarn → _tab_switched
        if not current:
            self._tab_index = bar.currentIndex()
        self._update_tab_bar()
        self.tabs_changed.emit()
        return True

    def close_other_tabs(self, keep: int) -> None:
        bar = self.tab_bar
        if self._tabs_blocked() or not 0 <= keep < bar.count():
            return
        if keep != bar.currentIndex():
            bar.setCurrentIndex(keep)
        for i in range(bar.count() - 1, -1, -1):
            if i != bar.currentIndex():
                bar.removeTab(i)
        self._tab_index = bar.currentIndex()
        self._update_tab_bar()
        self.tabs_changed.emit()

    def toggle_tab_lock(self, index: int | None = None) -> None:
        index = self.tab_bar.currentIndex() if index is None else index
        self._store_current_tab()
        st = self._tab_state(index)
        if st is None:
            self.ensure_first_tab()
            st = self._tab_state(0)
            index = 0
        st.locked = not st.locked
        self._update_tab_title(st.path if index != self.tab_bar.currentIndex() else self.current_path, index)
        self.tabs_changed.emit()

    def switch_tab(self, step: int) -> None:
        bar = self.tab_bar
        if bar.count() > 1 and not self._tabs_blocked():
            bar.setCurrentIndex((bar.currentIndex() + step) % bar.count())

    def _tab_switched(self, index: int) -> None:
        if index < 0:
            return
        if self._tabs_blocked() and self._tab_index >= 0:
            self.tab_bar.blockSignals(True)
            self.tab_bar.setCurrentIndex(self._tab_index)
            self.tab_bar.blockSignals(False)
            return
        if index == self._tab_index:
            return
        self._store_current_tab()
        self._tab_index = index
        st = self._tab_state(index)
        if st is not None:
            self.apply_tab_state(st)
            self._update_tab_title(self.current_path, index)
        self.tabs_changed.emit()

    def _update_tab_title(self, path: str, index: int | None = None) -> None:
        from .paneltabs import tab_title

        bar = self.tab_bar
        if bar.count() == 0 and path and not self._applying_tab:
            self.ensure_first_tab()
            return
        index = bar.currentIndex() if index is None else index
        if not 0 <= index < bar.count() or not path:
            return
        st = self._tab_state(index)
        if index == bar.currentIndex() and st is not None and not self.search_mode:
            st.path = path
        title = tab_title(path)
        bar.setTabText(index, ("🔒 " if st is not None and st.locked else "") + title)
        bar.setTabToolTip(index, path)

    def tabs_state(self) -> dict:
        """Zum Merken beim Beenden (L-3107): Server-Ordner und Papierkorb werden zum Heimordner."""
        self.ensure_first_tab()
        self._store_current_tab()
        tabs = []
        for i in range(self.tab_bar.count()):
            st = self._tab_state(i)
            if st is None:
                continue
            d = st.to_dict()
            if is_remote_uri(d["path"]) or is_trash_uri(d["path"]):
                d["path"] = os.path.expanduser("~")
            d["history"] = [h for h in d["history"] if not is_remote_uri(h)]
            d["pos"] = min(d["pos"], len(d["history"]) - 1)
            tabs.append(d)
        return {"tabs": tabs, "current": self.tab_bar.currentIndex()}

    def restore_tabs(self, data) -> None:
        """Gemerkte Reiter wiederherstellen; der aktuelle zeigt seinen Ordner sofort."""
        from .paneltabs import TabState, tab_title

        if not isinstance(data, dict) or not isinstance(data.get("tabs"), list):
            return
        states = [st for st in (TabState.from_dict(d) for d in data["tabs"]) if st is not None]
        if len(states) < 1:
            return
        current = data.get("current") if isinstance(data.get("current"), int) else 0
        current = min(max(current, 0), len(states) - 1)
        bar = self.tab_bar
        bar.blockSignals(True)
        while bar.count():
            bar.removeTab(0)
        for st in states:
            i = bar.addTab(tab_title(st.path))
            bar.setTabData(i, st)
            bar.setTabToolTip(i, st.path)
            if st.locked:
                bar.setTabText(i, "🔒 " + tab_title(st.path))
        bar.setCurrentIndex(current)
        bar.blockSignals(False)
        self._tab_index = current
        self._restoring_tabs = True
        try:
            self.apply_tab_state(states[current])
        finally:
            self._restoring_tabs = False
        self._update_tab_title(self.current_path, current)
        self._update_tab_bar()

    def set_tabs_always(self, on: bool) -> None:
        self.tabs_always = bool(on)
        self.ensure_first_tab()
        self._update_tab_bar()

    def set_remote_color(self, color: str) -> None:
        self.view.setStyleSheet(f"QTreeView {{ background-color: {color}; }}" if color else "")
        self.icon_view.setStyleSheet(f"QListView {{ background-color: {color}; }}" if color else "")
        self.parent_bar.setStyleSheet(f"QListView {{ background-color: {color}; }}" if color else "")

    def _update_parent_row(self, *_args) -> None:
        """Symbolansicht: „..“ nicht als großes Symbol, sondern als Zeile darüber (v1.19.1)."""
        has_parent = self.parent_bar.update_rows()
        self.parent_bar.setVisible(has_parent)
        self.icon_view.setRowHidden(0, has_parent)
        for row in range(1, self.model.rowCount()):
            if self.icon_view.isRowHidden(row):
                self.icon_view.setRowHidden(row, False)

    # --- Liste oder Symbolansicht (v1.19) -------------------------------------------------------------------
    def list_widget(self) -> QAbstractItemView:
        """Die gerade gezeigte Dateiansicht (Liste oder Symbolansicht)."""
        return self.icon_view if self.icon_mode else self.view

    def _show_list_widget(self) -> None:
        (self.icon_box if self.icon_mode else self.view).show()

    def focus_view(self) -> None:
        if self.icon_mode and self.parent_bar.isVisible() and self.view.currentIndex().row() == 0:
            self.parent_bar.setFocus()  # Cursor steht auf „..“
            return
        self.list_widget().setFocus()

    def _sync_icon_focus(self, current, _previous=None) -> None:
        """Der Cursor wechselt zwischen „..“ und den Symbolen – der Fokus folgt ihm (v1.19.1)."""
        if not self.icon_mode or not self.parent_bar.isVisible() or not current.isValid():
            return
        on_parent = current.row() == 0
        if on_parent and self.icon_view.hasFocus():
            self.parent_bar.setFocus()
        elif not on_parent and self.parent_bar.hasFocus():
            self.icon_view.setFocus()

    def set_icon_mode(self, on: bool) -> None:
        """L-1910: zwischen Liste und Symbolansicht umschalten."""
        on = bool(on)
        if on == self.icon_mode:
            return
        had_focus = self.list_widget().hasFocus() or self.parent_bar.hasFocus()
        busy = self.preview.isVisible() or getattr(self, "_custom_view", None) is not None
        self.icon_mode = on
        if not busy:
            self.view.setVisible(not on)
            self.icon_box.setVisible(on)
        if on:
            self._update_parent_row()
        cur = self.view.currentIndex()
        if cur.isValid():
            self.list_widget().scrollTo(cur)
        if had_focus and not busy:
            self.focus_view()

    @property
    def icon_size(self) -> int:
        return self.icon_view.icon_px

    def set_icon_size(self, px: int) -> None:
        """L-1911: klein, mittel, groß."""
        px = min(ICON_SIZES, key=lambda s: abs(s - int(px)))
        if px != self.icon_view.icon_px:
            self.icon_view.set_icon_px(px)
            cur = self.view.currentIndex()
            if cur.isValid() and self.icon_mode:
                QTimer.singleShot(0, lambda: self.icon_view.scrollTo(self.view.currentIndex()))
        self.icon_size_changed.emit(px)

    def zoom_icons(self, step: int) -> None:
        i = ICON_SIZES.index(self.icon_view.icon_px) + step
        if 0 <= i < len(ICON_SIZES):
            self.set_icon_size(ICON_SIZES[i])

    @property
    def locked(self) -> bool:
        return self._locked

    @locked.setter
    def locked(self, value: bool) -> None:
        self._locked = bool(value)
        self._update_tab_bar()

    def navigate(self, path: str, select_name: str | None = None, add_history: bool = True) -> bool:
        if self.locked:
            return False
        if self._tab_is_locked() and not self._applying_tab and self.current_path and \
                os.path.normpath(path) != os.path.normpath(self.current_path):
            # Gesperrter Reiter bleibt stehen – der neue Ordner öffnet sich in einem neuen Reiter (L-3103)
            self.new_tab(path, select_name=select_name)
            return True
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
        if not os.path.isdir(path):
            from . import archivefs

            inside = archivefs.split_path(path)
            if inside is not None:
                return self._navigate_archive(inside[0], inside[1], select_name, add_history)
        self.archive = None
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
        self.list_widget().scrollTo(index)

    def _select_name_later(self, name: str) -> None:
        QTimer.singleShot(0, lambda: self.select_names([name], current=name))

    def select_names(self, names: list[str], current: str | None = None) -> None:
        """Markiert die genannten Einträge in einem Schritt (v1.6.3: vorher je Name einzeln, bei vielen
        markierten Dateien dauerte das z. B. beim Schließen des Meta-Wizards sehr lange)."""
        from PySide6.QtCore import QItemSelection

        sel = self.view.selectionModel()
        rows_of = self.model.rows_by_name()
        rows = sorted({rows_of[n] for n in names if n in rows_of})
        selection = QItemSelection()
        col = self.model.icon_column
        start = prev = None
        for row in rows + [None]:  # zusammenhängende Zeilen als ein Bereich
            if row is not None and prev is not None and row == prev + 1:
                prev = row
                continue
            if start is not None:
                selection.select(self.model.index(start, col), self.model.index(prev, col))
            start = prev = row
        sel.select(selection, QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows)
        if current:
            row = self.model.row_of(current)
            if row >= 0:
                idx = self.model.index(row, self.model.icon_column)
                sel.setCurrentIndex(idx, QItemSelectionModel.SelectionFlag.NoUpdate)
                self.list_widget().scrollTo(idx)

    def refresh(self) -> None:
        if not self.current_path:
            return
        if QAbstractItemView.State.EditingState in (self.view.state(), self.icon_view.state()):
            # Während des Umbenennens nicht neu einlesen – das würde die Eingabe beenden.
            self._refresh_timer.start()
            return
        selected = [e.name for e in self.selected_entries()]
        cur = self.current_entry()
        cur_name = cur.name if cur else None
        scroll = self.list_widget().verticalScrollBar().value()
        if self.search_mode:
            self.model.refresh_results()
            self.select_names(selected, current=cur_name)
            self.list_widget().verticalScrollBar().setValue(scroll)
            self._update_status()
            return
        if self.in_trash:
            items = self.trash.items() if self.trash is not None else []
            self.model.load_trash(items, TRASH_URI)
            self.select_names(selected, current=cur_name)
            self.list_widget().verticalScrollBar().setValue(scroll)
            self._update_status()
            return
        if self.in_archive:
            from . import archivefs

            inside = archivefs.split_path(self.current_path)
            if inside is None:
                self.navigate(nearest_existing_dir(os.path.dirname(self.current_path)))
                return
            if not self._navigate_archive(inside[0], inside[1], cur_name, add_history=False):
                self.navigate(os.path.dirname(inside[0]))
                return
            self.select_names(selected, current=cur_name)
            self.list_widget().verticalScrollBar().setValue(scroll)
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
            self.list_widget().verticalScrollBar().setValue(scroll)
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
        self.list_widget().verticalScrollBar().setValue(scroll)
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
        if self.can_go_back() and self._tab_is_locked():  # gesperrter Reiter: Ziel in neuem Reiter
            self.new_tab(self._history[self._history_pos - 1])
            return
        if self.can_go_back():
            came_from = self.current_path
            self._history_pos -= 1
            self.navigate(self._history[self._history_pos], add_history=False,
                          select_name=_child_name(self._history[self._history_pos], came_from))

    def forward(self) -> None:
        if self.can_go_forward() and self._tab_is_locked():
            self.new_tab(self._history[self._history_pos + 1])
            return
        if self.can_go_forward():
            self._history_pos += 1
            self.navigate(self._history[self._history_pos], add_history=False)

    def history_entries(self, forward: bool) -> list[tuple[int, str]]:
        """Verlaufsliste für Zurück (neueste zuerst) bzw. Vorwärts (F-552)."""
        if forward:
            return [(i, self._history[i]) for i in range(self._history_pos + 1, len(self._history))]
        return [(i, self._history[i]) for i in range(self._history_pos - 1, -1, -1)]

    def go_history(self, index: int) -> None:
        if 0 <= index < len(self._history) and index != self._history_pos and self._tab_is_locked():
            self.new_tab(self._history[index])
            return
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
        elif self.in_archive:
            self.archive_open_requested.emit(entry)
        elif entry.remote:
            self.remote_open_requested.emit(entry)
        elif self.open_archives_inside and self.can_open_archive(entry):
            self.navigate(entry.path)  # L-3206: Archiv wie einen Ordner öffnen
        else:
            self.open_file_requested.emit(entry.path)

    def can_open_archive(self, entry) -> bool:
        from . import archivefs

        return (entry is not None and not entry.is_dir and not entry.remote and not self.in_trash
                and archivefs.is_archive_file(entry.name) and archivefs.can_browse(entry.name))

    def open_current(self) -> None:
        entry = self.current_entry()
        if entry is not None:
            self.open_entry(entry)

    def _on_double_click(self, index: QModelIndex) -> None:
        entry = self.model.entry(index.row())
        if entry is not None:
            from PySide6.QtWidgets import QApplication

            if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier and self._open_row_in_tab(
                    index.row()):
                return  # Strg+Doppelklick auf einen Ordner: neuer Reiter (L-3104)
            self.open_entry(entry)

    def _open_row_in_tab(self, row: int) -> bool:
        entry = self.model.entry(row)
        if entry is None or not entry.is_dir or self.in_trash:
            return False
        target = os.path.dirname(self.current_path.rstrip("/")) if entry.is_parent else entry.path
        if self.in_remote or self.remote is not None:
            return False
        return self.new_tab(target) >= 0

    def _on_path_entered(self) -> None:
        text = self.path_edit.text().strip()
        if not text:
            self.path_edit.setText(self.current_path)
            return
        if is_trash_uri(text) or text.casefold() == t("trash.title").casefold():
            self.navigate(TRASH_URI)
            self.focus_view()
            return
        if is_remote_uri(text):
            if not self.navigate(text.rstrip("/") if text.count("/") > 3 else text):
                self.path_edit.setText(self.current_path)
                return
            self.focus_view()
            return
        target = os.path.abspath(os.path.expanduser(text))
        from . import archivefs

        if not os.path.exists(target) and archivefs.split_path(target) is not None:
            if not self.navigate(target):
                self.path_edit.setText(self.current_path)
                return
            self.focus_view()
            return
        if os.path.isfile(target):
            self.navigate(os.path.dirname(target), select_name=os.path.basename(target))
        elif os.path.isdir(target):
            self.navigate(target)
        else:
            self.message.emit(t("title.folder_error"), t("error.path_not_found", path=target))
            self.path_edit.setText(self.current_path)
            return
        self.focus_view()

    def edit_path(self) -> None:
        self.path_edit.setFocus()
        self.path_edit.selectAll()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.path_edit and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.path_edit.setText(self.current_path)
                self.focus_view()
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
        if self.icon_mode:
            col = self.icon_view.modelColumn()
        idx = self.model.index(self.view.currentIndex().row(), col)
        self.list_widget().edit(idx)

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
            if hasattr(self, "icon_view"):
                self.icon_view.setModelColumn(col)
                self.parent_bar.setModelColumn(col)
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
        QTimer.singleShot(0, self._update_tab_bar)
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
        self.model.hit_texts = {}
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
        QTimer.singleShot(0, self._update_tab_bar)
        before = getattr(self, "_type_hidden_before", None)
        if before is not None:
            self._type_hidden_before = None
            if before:
                self._applying_profile = True
                self.view.header().setSectionHidden(COL_TYPE, True)
                self._applying_profile = False

    # --- Vorschau „Mehrfach umbenennen“ ---------------------------------------------------
    def set_preview_mode(self, on: bool, model=None) -> None:
        QTimer.singleShot(0, self._update_tab_bar)
        self.locked = on
        self.path_edit.setReadOnly(on)
        if on:
            self.preview.setModel(model)
            hdr = self.preview.header()
            for col, width in enumerate((260, 260, 90, 125, 125)):
                hdr.resizeSection(col, width)
            self._sync_preview_sort_indicator()
            self.view.hide()
            self.icon_box.hide()
            self.preview.show()
            self.preview.setFocus()
        else:
            self.preview.hide()
            self.preview.setModel(None)
            self._show_list_widget()
            self.focus_view()

    # --- Eigene Ansicht statt der Dateiliste (Meta-Wizard, F-903) --------------------------
    def set_custom_view(self, widget: QWidget | None) -> None:
        QTimer.singleShot(0, self._update_tab_bar)
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
            self._show_list_widget()
            self.focus_view()
            return
        self._custom_view = widget
        layout.insertWidget(layout.indexOf(self.icon_box) + 1, widget, 1)
        self.view.hide()
        self.icon_box.hide()
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
