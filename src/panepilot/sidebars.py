"""Seitenleisten als austauschbare Module.

Jede Seitenleiste ist in ``SIDEBARS`` eingetragen. Neue Arten (z. B. eine
Baumansicht oder MP3-Metadaten) werden hier ergänzt, ohne den Rest des
Programms anzufassen. ``available=False`` zeigt die Art im Menü an, aber
ausgegraut (für angekündigte Funktionen).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtWidgets import QStackedWidget, QWidget

MODE_OFF = "off"
MODE_FAVORITES = "favorites"
MODE_TREE = "tree"
MODE_SERVERS = "servers"  # v1.3


@dataclass(frozen=True)
class SidebarDef:
    id: str
    text_key: str
    available: bool


SIDEBARS: tuple[SidebarDef, ...] = (
    SidebarDef(MODE_FAVORITES, "sidebar.favorites", True),
    SidebarDef(MODE_TREE, "sidebar.tree", True),
    SidebarDef(MODE_SERVERS, "sidebar.servers", True),
    SidebarDef(MODE_OFF, "sidebar.off", True),
)


class SidebarHost(QStackedWidget):
    """Platz für die Seitenleiste eines Panels; erzeugt Module bei Bedarf."""

    def __init__(self, factories: dict[str, Callable[[], QWidget]], parent=None) -> None:
        super().__init__(parent)
        self._factories = factories
        self._widgets: dict[str, QWidget] = {}
        self._mode = MODE_OFF
        self.setMinimumWidth(120)

    @property
    def mode(self) -> str:
        return self._mode

    def widget_for(self, mode: str) -> QWidget | None:
        if mode not in self._widgets and mode in self._factories:
            w = self._factories[mode]()
            self._widgets[mode] = w
            self.addWidget(w)
        return self._widgets.get(mode)

    def set_mode(self, mode: str) -> None:
        if mode != MODE_OFF and (mode not in self._factories):
            mode = MODE_OFF
        self._mode = mode
        if mode == MODE_OFF:
            self.setVisible(False)
            return
        w = self.widget_for(mode)
        if w is not None:
            self.setCurrentWidget(w)
        self.setVisible(True)

    def current_module(self) -> QWidget | None:
        return self._widgets.get(self._mode) if self._mode != MODE_OFF else None


class SidebarPane(QWidget):
    """Seitenleisten-Modul mit Titelleiste (F-623, F-626).

    Die Titelleiste zeigt einen Namen, optional eine Auswahlliste (Favoritensätze)
    und rechts ein „X“ zum Schließen der Seitenleiste.
    """

    def __init__(self, view: QWidget, title: str, parent=None) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton, QVBoxLayout

        super().__init__(parent)
        self.view = view
        self.title_bar = QFrame(self)
        self.title_bar.setObjectName("sidebarTitle")
        self.title_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.title_button = QToolButton(self.title_bar)
        self.title_button.setObjectName("sidebarTitleButton")
        self.title_button.setAutoRaise(True)
        self.title_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        from PySide6.QtWidgets import QSizePolicy

        self.title_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.title_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.close_button = QToolButton(self.title_bar)
        self.close_button.setObjectName("sidebarClose")
        self.close_button.setAutoRaise(True)
        self.close_button.setText("✕")
        hl = QHBoxLayout(self.title_bar)
        hl.setContentsMargins(4, 1, 1, 1)
        hl.setSpacing(2)
        hl.addWidget(self.title_button, 1)
        hl.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title_bar)
        layout.addWidget(view, 1)
        self.set_title(title)

    def set_title(self, title: str, menu=None) -> None:
        """menu=None: keine Auswahlliste; sonst QMenu, das beim Klick aufklappt."""
        from PySide6.QtWidgets import QToolButton

        self.title_button.setText(title + ("  ▾" if menu is not None else ""))
        self.title_button.setMenu(menu)
        self.title_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.title_button.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0; }")
