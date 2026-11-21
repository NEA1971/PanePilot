"""Reiter (Tabs) je Fenster (v2.1, L-3100 ff.).

Ein Fenster (FilePanel) hat weiterhin genau eine Dateiliste. Ein Reiter merkt sich nur seinen Zustand –
Ordner, Verlauf, Sortierung, Filter, Ansicht und ob er gesperrt ist. Beim Wechsel speichert das Fenster den
Zustand des alten Reiters und stellt den des neuen wieder her.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTabBar

from .filters import FilterSpec


@dataclass
class TabState:
    path: str
    history: list[str] = field(default_factory=list)
    pos: int = -1
    sort: tuple[int, int] = (0, 0)
    filter_spec: FilterSpec | None = None
    filter_on: bool = False
    icon_mode: bool = False
    icon_size: int = 128
    locked: bool = False

    def copy_for(self, path: str) -> "TabState":
        """Neuer Reiter: gleiche Sortierung, Filter und Ansicht, eigener Verlauf (L-3104)."""
        return TabState(path, [path], 0, self.sort, self.filter_spec, self.filter_on, self.icon_mode,
                        self.icon_size, False)

    def to_dict(self) -> dict:
        d = {"path": self.path, "history": self.history[-20:], "pos": max(-1, self.pos - max(0, len(self.history) - 20)),
             "sort": list(self.sort), "icon_view": self.icon_mode, "icon_size": self.icon_size,
             "locked": self.locked, "filter_on": self.filter_on}
        if self.filter_spec is not None:
            d["filter"] = self.filter_spec.to_dict()
        return d

    @classmethod
    def from_dict(cls, d) -> "TabState | None":
        if not isinstance(d, dict) or not isinstance(d.get("path"), str) or not d["path"]:
            return None
        history = [h for h in d.get("history") or [] if isinstance(h, str)]
        pos = d.get("pos") if isinstance(d.get("pos"), int) else len(history) - 1
        sort = d.get("sort")
        sort = (int(sort[0]), int(sort[1])) if isinstance(sort, list) and len(sort) == 2 else (0, 0)
        size = d.get("icon_size") if isinstance(d.get("icon_size"), int) else 128
        spec = FilterSpec.from_dict(d.get("filter")) if d.get("filter") else None
        return cls(d["path"], history, min(max(pos, -1), len(history) - 1), sort, spec,
                   bool(d.get("filter_on")) and spec is not None, d.get("icon_view") is True, size,
                   d.get("locked") is True)


def tab_title(path: str) -> str:
    """Ordnername; bei „/“ und Server-Adressen etwas Sinnvolles."""
    if "://" in path:
        rest = path.split("://", 1)[1].rstrip("/")
        return rest.rsplit("/", 1)[-1] or rest or path
    name = os.path.basename(path.rstrip(os.sep))
    return name or path


class PanelTabBar(QTabBar):
    """Reiterleiste: mittlere Maustaste schließt, Doppelklick auf freie Fläche öffnet einen neuen Reiter."""

    new_requested = Signal()
    close_requested = Signal(int)
    menu_requested = Signal(int, object)  # Index, globale Position

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMovable(True)
        self.setExpanding(False)
        self.setDocumentMode(True)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideMiddle)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self.menu_requested.emit(self.tabAt(pos),
                                                                                    self.mapToGlobal(pos)))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self.isEnabled():
            i = self.tabAt(event.position().toPoint())
            if i >= 0:
                self.close_requested.emit(i)
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if self.tabAt(event.position().toPoint()) < 0 and self.isEnabled():
            self.new_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
