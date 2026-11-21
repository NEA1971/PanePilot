"""Menüzeile mit Punkt vor dem Bildchen (Knopf „Ansicht“, v1.23, L-2301)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QWidget, QWidgetAction


class ViewMenuRow(QWidget):
    def __init__(self, action: QWidgetAction, icon: QIcon, text: str, current: bool, parent=None) -> None:
        super().__init__(parent)
        self._action = action
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAutoFillBackground(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 4, 16, 4)
        lay.setSpacing(8)
        self.dot = QLabel("●" if current else "", self)
        self.dot.setFixedWidth(12)
        self.dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f = self.dot.font()
        f.setPointSizeF(max(6.0, f.pointSizeF() * 0.6))
        self.dot.setFont(f)
        size = self.style().pixelMetric(self.style().PixelMetric.PM_SmallIconSize)
        self.icon = QLabel(self)
        self.icon.setPixmap(icon.pixmap(QSize(size, size)))
        self.text = QLabel(text, self)
        lay.addWidget(self.dot)
        lay.addWidget(self.icon)
        lay.addWidget(self.text, 1)
        self.current = current
        self._hover(False)

    @classmethod
    def action(cls, menu: QMenu, icon: QIcon, text: str, current: bool) -> QWidgetAction:
        act = QWidgetAction(menu)
        act.setText(text)
        act.setIcon(icon)
        act.setCheckable(True)
        act.setChecked(current)
        row = cls(act, icon, text, current, menu)
        act.setDefaultWidget(row)
        menu.hovered.connect(lambda a, r=row, me=act: r._hover(a is me))  # auch mit den Pfeiltasten
        return act

    def _hover(self, on: bool) -> None:
        pal = self.palette()
        role = pal.ColorRole
        bg = pal.color(role.Highlight) if on else self.parentWidget().palette().color(role.Window) \
            if self.parentWidget() is not None else pal.color(role.Window)
        fg = pal.color(role.HighlightedText) if on else pal.color(role.WindowText)
        pal.setColor(self.backgroundRole(), bg)
        for w in (self.dot, self.text):
            p2 = w.palette()
            p2.setColor(w.foregroundRole(), fg)
            w.setPalette(p2)
        self.setPalette(pal)

    def enterEvent(self, event) -> None:
        self._hover(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            menu = self.parentWidget()
            self._action.trigger()
            if isinstance(menu, QMenu):
                menu.close()
            event.accept()
            return
        super().mouseReleaseEvent(event)
