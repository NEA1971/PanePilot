"""Erscheinungsbild (v3.2, L-4200 ff.): Hell/Dunkel auf Linux und Windows gleich, Schrift für die ganze Oberfläche.

„Hell“ ist der Fusion-Stil mit hellgrauem Fensterhintergrund – so sah PanePilot unter Linux schon immer aus. Unter
Windows ersetzt er die grelle Windows-11-Darstellung. „Dunkel“ ist derselbe Stil in Dunkelgrau. Die Markierung nimmt
die Akzentfarbe des Systems.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

IS_WINDOWS = sys.platform.startswith("win")
SYSTEM, LIGHT, DARK = "system", "light", "dark"
MODES = (SYSTEM, LIGHT, DARK)
WINDOWS_FONT = ("Segoe UI", 10)

_state: dict = {"accent": None, "font": None, "dark": False, "mode": SYSTEM, "watching": False}


def _remember_system() -> None:
    """Akzentfarbe und Systemschrift einmal merken, bevor PanePilot sie ändert."""
    app = QApplication.instance()
    if app is None or _state["accent"] is not None:
        return
    pal = app.palette()
    role = getattr(QPalette.ColorRole, "Accent", QPalette.ColorRole.Highlight)
    accent = QColor(pal.color(role))
    if not accent.isValid() or accent.saturation() < 40:  # graue „Akzentfarbe“ → kräftiges Blau
        accent = QColor("#3584E4")
    _state["accent"] = accent
    _state["font"] = QFont(app.font())


def accent() -> QColor:
    _remember_system()
    return QColor(_state["accent"] or QColor("#3584E4"))


def default_font() -> tuple[str, float]:
    """Ausgangsschrift: Windows Segoe UI 10 pt, sonst die Systemschrift."""
    _remember_system()
    if IS_WINDOWS:
        return WINDOWS_FONT
    f = _state["font"] or QFont()
    size = f.pointSizeF() if f.pointSizeF() > 0 else 10.0
    return f.family(), size


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # ältere Qt-Version
        return False


def is_dark() -> bool:
    return bool(_state["dark"])


def light_palette(acc: QColor) -> QPalette:
    pal = QStyleFactory.create("Fusion").standardPalette()
    _set_accent(pal, acc, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#E9EDF2"))  # v3.2.1: deutlich sichtbar
    return pal


def dark_palette(acc: QColor) -> QPalette:
    pal = QPalette()
    c = {
        QPalette.ColorRole.Window: "#2D2D2D", QPalette.ColorRole.WindowText: "#E6E6E6",
        QPalette.ColorRole.Base: "#242424", QPalette.ColorRole.AlternateBase: "#323438",
        QPalette.ColorRole.Text: "#E6E6E6", QPalette.ColorRole.Button: "#383838",
        QPalette.ColorRole.ButtonText: "#E6E6E6", QPalette.ColorRole.BrightText: "#FFFFFF",
        QPalette.ColorRole.ToolTipBase: "#3A3A3A", QPalette.ColorRole.ToolTipText: "#F0F0F0",
        QPalette.ColorRole.PlaceholderText: "#8C8C8C", QPalette.ColorRole.Light: "#4A4A4A",
        QPalette.ColorRole.Midlight: "#404040", QPalette.ColorRole.Mid: "#5A5A5A",
        QPalette.ColorRole.Dark: "#1E1E1E", QPalette.ColorRole.Shadow: "#141414",
        QPalette.ColorRole.Link: "#7DB3FF", QPalette.ColorRole.LinkVisited: "#C59BFF",
    }
    for role, value in c.items():
        pal.setColor(role, QColor(value))
    for role, value in ((QPalette.ColorRole.Text, "#7A7A7A"), (QPalette.ColorRole.WindowText, "#7A7A7A"),
                        (QPalette.ColorRole.ButtonText, "#7A7A7A"), (QPalette.ColorRole.Base, "#2A2A2A")):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(value))
    _set_accent(pal, acc, QColor("#FFFFFF"))
    return pal


def _set_accent(pal: QPalette, acc: QColor, text: QColor) -> None:
    if acc.lightness() > 170:  # sehr helle Akzentfarbe: weiße Schrift wäre unlesbar
        text = QColor("#000000")
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        pal.setColor(group, QPalette.ColorRole.Highlight, acc)
        pal.setColor(group, QPalette.ColorRole.HighlightedText, text)
        if hasattr(QPalette.ColorRole, "Accent"):
            pal.setColor(group, QPalette.ColorRole.Accent, acc)
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, acc.darker(140))


def resolve(mode: str) -> bool:
    """True = dunkel."""
    if mode == DARK:
        return True
    if mode == LIGHT:
        return False
    return system_is_dark()


def apply(mode: str = SYSTEM, font_family: str = "", font_size: float = 0) -> None:
    """Stil, Farben und Schrift setzen; bei „Wie das System“ auch späteren Wechseln folgen."""
    app = QApplication.instance()
    if app is None:
        return
    _remember_system()
    mode = mode if mode in MODES else SYSTEM
    _state["mode"] = mode
    try:  # Qt ≥ 6.8: auch die Titelleiste unter Windows hell/dunkel
        scheme = {LIGHT: Qt.ColorScheme.Light, DARK: Qt.ColorScheme.Dark}.get(mode, Qt.ColorScheme.Unknown)
        QGuiApplication.styleHints().setColorScheme(scheme)
    except AttributeError:
        pass
    dark = resolve(mode)
    _state["dark"] = dark
    if app.style().name().lower() != "fusion":
        app.setStyle("Fusion")
    app.setPalette(dark_palette(accent()) if dark else light_palette(accent()))
    apply_font(font_family, font_size)
    _watch()


def apply_font(family: str = "", size: float = 0) -> None:
    app = QApplication.instance()
    if app is None:
        return
    dfam, dsize = default_font()
    font = QFont(_state["font"]) if _state["font"] is not None and not IS_WINDOWS else QFont()
    font.setFamily(family or dfam)
    font.setPointSizeF(float(size) if size and size > 0 else float(dsize))
    app.setFont(font)


class _Watcher(QObject):
    def changed(self, *_args) -> None:
        if _state["mode"] == SYSTEM:
            app = QApplication.instance()
            font = app.font() if app else None
            dark = system_is_dark()
            if dark != _state["dark"]:
                _state["dark"] = dark
                app.setPalette(dark_palette(accent()) if dark else light_palette(accent()))
                if font is not None:
                    app.setFont(font)
                for cb in list(_listeners):
                    try:
                        cb()
                    except Exception:  # noqa: BLE001
                        pass


_watcher: _Watcher | None = None
_listeners: list = []  # werden nach einem Hell/Dunkel-Wechsel des Systems aufgerufen


def on_system_change(callback) -> None:
    if callback not in _listeners:
        _listeners.append(callback)


def _watch() -> None:
    global _watcher
    if _state["watching"]:
        return
    try:
        hints = QGuiApplication.styleHints()
        _watcher = _Watcher()
        hints.colorSchemeChanged.connect(_watcher.changed)
        _state["watching"] = True
    except AttributeError:
        pass


def readable(color: QColor, background: QColor | None = None) -> QColor:
    """L-4204: zu dunkle Schriftfarbe auf dunklem Grund aufhellen (gespeicherte Farbe bleibt)."""
    if not _state["dark"]:
        return color
    bg = background or QApplication.palette().color(QPalette.ColorRole.Base)
    c = QColor(color)
    if c.lightness() - bg.lightness() >= 90:
        return c
    h, s, l, a = c.getHsl()
    target = max(l, bg.lightness() + 130)
    c.setHsl(max(h, 0), min(s, 230), min(target, 235), a)
    return c
