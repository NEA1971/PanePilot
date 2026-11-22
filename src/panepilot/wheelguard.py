"""Mausrad überall in PanePilot zähmen (v2.3, Wunsch vom 21.11.2026).

1. Auswahllisten (Drop-downs) reagieren nur aufgeklappt aufs Mausrad – dann rollt die aufgeklappte Liste.
   Zugeklappt verstellt das Rad nichts mehr (vorher: nächster Eintrag, im Meta-Wizard auch „< entfernen >“),
   sondern rollt die umgebende Seite.
2. Regler und Zahlenfelder nehmen das Rad erst, wenn man sie angeklickt hat (wie in 2.1.2 in den Einstellungen).
3. Listen, Tabellen und Textfelder, die selbst in einer rollbaren Seite stecken, rollen nur sich selbst –
   am Ende geht das Rad nicht an die Seite weiter. Kann die innere Liste gar nicht rollen, rollt die Seite.

Ein einziger Ereignisfilter an der Anwendung, damit auch künftige Fenster das automatisch bekommen.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtWidgets import (QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QApplication, QComboBox,
                               QScrollBar, QWidget)


def _outer_area(w: QWidget | None) -> QAbstractScrollArea | None:
    """Nächste rollbare Fläche oberhalb von w (ohne w selbst)."""
    p = w.parentWidget() if w is not None else None
    while p is not None:
        if isinstance(p, QAbstractScrollArea):
            return p
        if p.isWindow():
            return None
        p = p.parentWidget()
    return None


def _owner(obj) -> QWidget | None:
    """Das Bedienelement, zu dem ein Unter-Widget gehört (z. B. Textfeld einer Auswahlliste)."""
    w = obj if isinstance(obj, QWidget) else None
    while w is not None and not w.isWindow():
        if isinstance(w, (QComboBox, QAbstractSpinBox)) or (isinstance(w, QAbstractSlider)
                                                             and not isinstance(w, QScrollBar)):
            return w
        if isinstance(w, QAbstractScrollArea):
            return None
        w = w.parentWidget()
    return None


def _bar_for(area: QAbstractScrollArea, event) -> QScrollBar:
    d = event.angleDelta()
    horizontal = abs(d.x()) > abs(d.y()) or bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
    return area.horizontalScrollBar() if horizontal else area.verticalScrollBar()


def _scroll(area: QAbstractScrollArea | None, event) -> None:
    if area is not None:
        QCoreApplication.sendEvent(_bar_for(area, event), event)


def _done(event) -> bool:
    """Ereignis erledigt: angenommen markieren, sonst reicht Qt ein echtes Mausrad-Ereignis an die
    übergeordneten Fenster weiter (so rollte am Ende einer Liste doch wieder die Seite – Meldung vom 22.11.2026)."""
    event.accept()
    return True


class WheelGuard(QObject):
    _busy = False

    def eventFilter(self, obj, event) -> bool:
        if self._busy:
            return False
        self._busy = True
        try:
            return self._filter(obj, event)
        finally:
            self._busy = False

    def _filter(self, obj, event) -> bool:
        et = event.type()
        if et == QEvent.Type.Polish and isinstance(obj, QWidget):
            if isinstance(obj, (QComboBox, QAbstractSpinBox)) or (isinstance(obj, QAbstractSlider)
                                                                  and not isinstance(obj, QScrollBar)):
                if obj.focusPolicy() == Qt.FocusPolicy.WheelFocus:
                    obj.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # das Rad soll keinen Fokus geben
            return False
        if et != QEvent.Type.Wheel or not isinstance(obj, QWidget):
            return False
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False  # Strg+Rad (z. B. Symbolgröße) unverändert
        if isinstance(obj, QScrollBar):  # direkt auf dem Rollbalken einer inneren Liste: auch dort nicht weiter
            inner = _outer_area(obj)
            if inner is not None and _outer_area(inner) is not None:
                QCoreApplication.sendEvent(obj, event)
                return _done(event)
            return False
        owner = _owner(obj)
        if owner is not None:
            if isinstance(owner, QComboBox) or not owner.hasFocus():
                _scroll(_outer_area(owner), event)  # zugeklappt bzw. nicht angeklickt: Seite rollen
                return _done(event)
            return False
        area = obj.parentWidget() if isinstance(obj.parentWidget(), QAbstractScrollArea) else None
        if area is None or obj is not area.viewport():
            return False
        outer = _outer_area(area)
        if outer is None:
            return False  # nicht verschachtelt: normales Verhalten
        bar = _bar_for(area, event)
        if bar.maximum() <= bar.minimum():
            _scroll(outer, event)  # innere Liste kann gar nicht rollen: Seite rollen
            return _done(event)
        QCoreApplication.sendEvent(bar, event)  # nur die innere Liste – am Ende nicht weiter (L-3300)
        return _done(event)


_guard: WheelGuard | None = None


def install() -> None:
    global _guard
    app = QApplication.instance()
    if app is None or _guard is not None:
        return
    _guard = WheelGuard(app)
    app.installEventFilter(_guard)
