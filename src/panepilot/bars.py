"""Knopfleiste zwischen den Panels und F-Tasten-Leiste unter den Panels."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QSizePolicy, QToolButton, QVBoxLayout, QHBoxLayout, QWidget

from .actions import FKEYS, GNOME_RESERVED

_ICON_SIZES = (24, 32, 48)


def _paint_icon(draw) -> QIcon:
    icon = QIcon()
    for size in _ICON_SIZES:
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(size / 24.0, size / 24.0)
        draw(p)
        p.end()
        icon.addPixmap(pm)
    return icon


def _mirror(icon: QIcon) -> QIcon:
    result = QIcon()
    for size in _ICON_SIZES:
        result.addPixmap(icon.pixmap(size, size).transformed(QTransform().scale(-1, 1)))
    return result


def _colors():
    pal = QApplication.palette()
    return pal.color(pal.ColorRole.Text), QColor("#2E75B6")


def _arrow(p: QPainter, x1: float, x2: float, y: float, color: QColor, width: float = 2.2) -> None:
    p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawLine(QPointF(x1, y), QPointF(x2 - 1, y))
    head = QPainterPath()
    d = 1 if x2 > x1 else -1
    head.moveTo(x2, y)
    head.lineTo(x2 - 4.5 * d, y - 4)
    head.lineTo(x2 - 4.5 * d, y + 4)
    head.closeSubpath()
    p.setBrush(color)
    p.drawPath(head)


def _page(p: QPainter, x: float, y: float, w: float, h: float, color: QColor, fill: QColor) -> None:
    p.setPen(QPen(color, 1.4))
    p.setBrush(fill)
    p.drawRoundedRect(QRectF(x, y, w, h), 1.5, 1.5)
    p.drawLine(QPointF(x + 2, y + 3.5), QPointF(x + w - 2, y + 3.5))
    p.drawLine(QPointF(x + 2, y + 6.5), QPointF(x + w - 2, y + 6.5))


def icon_same_path() -> QIcon:
    fg, accent = _colors()

    def draw(p):
        p.setPen(QPen(fg, 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(2, 4, 8, 16), 1.5, 1.5)
        p.drawRoundedRect(QRectF(14, 4, 8, 16), 1.5, 1.5)
        p.setPen(QPen(accent, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for y in (10, 14):
            p.drawLine(QPointF(4, y), QPointF(8, y))
            p.drawLine(QPointF(16, y), QPointF(20, y))
    return _paint_icon(draw)


def icon_swap() -> QIcon:
    fg, accent = _colors()

    def draw(p):
        _arrow(p, 3, 21, 8.5, accent)
        _arrow(p, 21, 3, 15.5, fg)
    return _paint_icon(draw)


def icon_copy() -> QIcon:
    fg, accent = _colors()
    pal = QApplication.palette()
    base = pal.color(pal.ColorRole.Base)

    def draw(p):
        _page(p, 1.5, 3, 9, 11, fg, base)
        _page(p, 4, 6, 9, 11, fg, base)
        _arrow(p, 13, 23, 18, accent)
    return _paint_icon(draw)


def icon_move() -> QIcon:
    fg, accent = _colors()
    faded = QColor(fg)
    faded.setAlpha(90)

    def draw(p):
        _page(p, 2, 4, 9, 11, faded, Qt.GlobalColor.transparent)
        _arrow(p, 7, 23, 18, accent, 2.6)
    return _paint_icon(draw)


def trash_icons() -> tuple[QIcon, QIcon]:
    """(leer, voll) – aus dem Symbolthema, sonst selbst gezeichnet."""
    from PySide6.QtWidgets import QStyle

    style = QApplication.style()
    empty = QIcon.fromTheme("user-trash", style.standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
    full = QIcon.fromTheme("user-trash-full")
    if full.isNull() or full.name() == empty.name():
        base = empty
        full = QIcon()
        for size in _ICON_SIZES:
            pm = base.pixmap(size, size)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setBrush(QColor("#E6A23C"))
            p.setPen(QPen(QColor("#8A5A00"), max(1.0, size / 24)))
            r = size * 0.22
            p.drawEllipse(QRectF(size - 2 * r - 1, 1, 2 * r, 2 * r))
            p.end()
            full.addPixmap(pm)
    return empty, full


class TrashButton(QToolButton):
    """Papierkorb-Knopf: Klick öffnet, Dateien darauf ziehen = löschen (F-400 ff.)."""

    files_dropped = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    @staticmethod
    def _paths(event) -> list[str]:
        md = event.mimeData()
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile()] if md.hasUrls() else []

    def dragEnterEvent(self, event) -> None:
        if self._paths(event) and event.possibleActions() & Qt.DropAction.MoveAction:
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        paths = self._paths(event)
        if not paths:
            event.ignore()
            return
        # Für die Quelle als "kopiert" melden – gelöscht wird über unseren eigenen Ablauf
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.files_dropped.emit(paths)


class ButtonBar(QWidget):
    """Senkrechte Leiste zwischen den Panels (F-320 ff.)."""

    triggered = Signal(str)  # Aktions-ID
    trash_clicked = Signal()
    trash_dropped = Signal(list)
    trash_menu = Signal(object)  # globale Position

    BUTTONS = ("same_path", "swap_panels", "copy_direct", "move_direct")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("buttonBar")
        self.setFixedWidth(36)
        self._icons_ltr = {
            "same_path": icon_same_path(),
            "swap_panels": icon_swap(),
            "copy_direct": icon_copy(),
            "move_direct": icon_move(),
        }
        self._icons_rtl = {k: (_mirror(v) if k in ("copy_direct", "move_direct", "same_path") else v)
                           for k, v in self._icons_ltr.items()}
        self.buttons: dict[str, QToolButton] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.addStretch(1)
        for i, aid in enumerate(self.BUTTONS):
            btn = QToolButton(self)
            btn.setAutoRaise(True)
            btn.setIconSize(QSize(24, 24))
            btn.setFixedSize(32, 32)
            btn.setObjectName(f"bar_{aid}")
            btn.clicked.connect(lambda _c=False, a=aid: self.triggered.emit(a))
            self.buttons[aid] = btn
            layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
            if i < len(self.BUTTONS) - 1:
                layout.addSpacing(14)
        layout.addStretch(1)
        # Papierkorb ganz unten (F-400)
        self._trash_empty, self._trash_full = trash_icons()
        self.trash_button = TrashButton(self)
        self.trash_button.setObjectName("bar_trash")
        self.trash_button.setAutoRaise(True)
        self.trash_button.setIconSize(QSize(24, 24))
        self.trash_button.setFixedSize(32, 32)
        self.trash_button.clicked.connect(self.trash_clicked)
        self.trash_button.files_dropped.connect(self.trash_dropped)
        self.trash_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.trash_button.customContextMenuRequested.connect(
            lambda pos: self.trash_menu.emit(self.trash_button.mapToGlobal(pos))
        )
        layout.addWidget(self.trash_button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.set_trash_full(False)
        self.set_direction(True)

    def set_trash_full(self, full: bool) -> None:
        self.trash_full = full
        self.trash_button.setIcon(self._trash_full if full else self._trash_empty)

    def set_direction(self, left_to_right: bool) -> None:
        icons = self._icons_ltr if left_to_right else self._icons_rtl
        for aid, btn in self.buttons.items():
            btn.setIcon(icons[aid])

    def set_tooltips(self, texts: dict[str, str]) -> None:
        for aid, btn in self.buttons.items():
            btn.setToolTip(texts.get(aid, ""))


LAYER_LABELS = {"": "", "Shift+": "SHIFT+", "Ctrl+": "STRG+", "Alt+": "ALT+"}


def layer_from_modifiers(mods) -> str:
    """Genau eine Zusatztaste gedrückt → deren Schicht, sonst die normale (F-641)."""
    mods = Qt.KeyboardModifier(mods) & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier
                                        | Qt.KeyboardModifier.AltModifier)
    return {Qt.KeyboardModifier.ShiftModifier: "Shift+", Qt.KeyboardModifier.ControlModifier: "Ctrl+",
            Qt.KeyboardModifier.AltModifier: "Alt+"}.get(mods, "")


class FKeyBar(QWidget):
    """F1–F12 unter den Panels; Belegung per Rechtsklick (F-330 ff.), vier Schichten (F-640 ff.)."""

    triggered = Signal(str)  # "F5", "Shift+F5" …
    assign_requested = Signal(str, object)  # "Shift+F5", globale Position

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("fkeyBar")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self.buttons: dict[str, QToolButton] = {}
        for key in FKEYS:
            btn = QToolButton(self)
            btn.setObjectName(f"fkey_{key}")
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            btn.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)  # alle gleich breit
            btn.setMinimumWidth(40)
            btn.setFixedHeight(38)
            # Schicht aus den beim Klick gedrückten Zusatztasten (F-642/F-643)
            btn.clicked.connect(lambda _c=False, k=key: self.triggered.emit(self._current_layer() + k))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, k=key, b=btn: self.assign_requested.emit(self._current_layer() + k, b.mapToGlobal(pos))
            )
            self.buttons[key] = btn
            layout.addWidget(btn)
        self.layer = ""
        self._labels: dict[str, str | None] = {}
        self._tooltips: dict[str, str] = {}
        self._disabled: set[str] = set()

    def set_disabled(self, keys: set[str]) -> None:
        self._disabled = set(keys)
        self._show()

    @staticmethod
    def _current_layer() -> str:
        return layer_from_modifiers(QApplication.keyboardModifiers())

    def set_layer(self, layer: str) -> None:
        if layer != self.layer:
            self.layer = layer
            self._show()

    def set_labels(self, labels: dict[str, str | None], tooltips: dict[str, str] | None = None) -> None:
        """labels/tooltips für alle Schichten, Schlüssel z. B. 'F5' oder 'Alt+F5'."""
        self._labels = dict(labels)
        self._tooltips = dict(tooltips or {})
        self._show()

    def _show(self) -> None:
        for base, btn in self.buttons.items():
            key = self.layer + base
            text = self._labels.get(key)
            shown_key = LAYER_LABELS[self.layer] + base
            if not text and key in GNOME_RESERVED:
                btn.setText(f"{shown_key}\n(GNOME)")
            else:
                btn.setText(f"{shown_key}\n{text}" if text else shown_key)
            btn.setToolTip(self._tooltips.get(key, ""))
            btn.setEnabled(key not in self._disabled)
            # Freie Tasten ausgegraut (über die Palette, damit belegte Tasten sicher wieder normal aussehen)
            pal = QApplication.palette()
            if not text:
                pal.setColor(pal.ColorRole.ButtonText, pal.color(pal.ColorGroup.Disabled, pal.ColorRole.ButtonText))
            btn.setPalette(pal)
            btn.setStyleSheet("")
