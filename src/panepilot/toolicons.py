"""Symbole für die Symbolleiste (F-551, F-555).

Zuerst wird das Symbolthema des Systems gefragt (auch die „-symbolic“-Variante,
die neuere GNOME-Versionen nur noch mitbringen). Fehlt dort etwas, zeichnet
PanePilot ein eigenes, einfaches Symbol.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen

from .bars import _arrow, _colors, _mirror, _page, _paint_icon, icon_copy, icon_move, icon_same_path, icon_swap, trash_icons

# Aktion → Namen im Symbolthema (der erste vorhandene gewinnt)
THEME_NAMES: dict[str, tuple[str, ...]] = {
    "go_up": ("go-up",),
    "refresh": ("view-refresh",),
    "new_folder": ("folder-new",),
    "new_textfile": ("document-new",),
    "clip_copy": ("edit-copy",),
    "clip_cut": ("edit-cut",),
    "clip_paste": ("edit-paste",),
    "delete_permanent": ("edit-delete",),
    "select_all": ("edit-select-all",),
    "edit_text": ("accessories-text-editor", "document-edit", "text-editor"),
    "open_with_other": ("document-open",),
    "rename": ("edit-rename", "document-edit"),
    "add_favorite": ("bookmark-new", "starred"),
    "fav_edit": ("document-properties",),
    "fav_new_group": ("folder-new",),
    "trash_restore": ("edit-undo",),
    "trash_purge": ("edit-delete",),
    "trash_empty": ("edit-clear-all", "edit-clear"),
    "about": ("help-about",),
    "quit": ("application-exit", "system-log-out"),
    "edit_path": ("document-edit", "edit-find"),
    "meta_wizard": ("audio-x-generic", "multimedia-audio-player", "audio-x-mpeg"),
    # v0.9.10
    "search": ("system-search", "edit-find"),
    "settings_dialog": ("preferences-system", "emblem-system", "applications-system"),
    # v1.1
    "open_terminal": ("utilities-terminal", "terminal", "org.gnome.Terminal"),
    "dir_list": ("view-list-text", "text-x-generic", "x-office-document"),
    # v1.6
    "find_duplicates": ("edit-copy", "edit-find-replace", "edit-find"),
}

_cache: dict[str, QIcon] = {}


def _theme(names: tuple[str, ...]) -> QIcon | None:
    for name in names:
        for candidate in (name, name + "-symbolic"):
            if QIcon.hasThemeIcon(candidate):
                return QIcon.fromTheme(candidate)
    return None


def action_icon(action_id: str, text: str = "") -> QIcon:
    icon = _cache.get(action_id)
    if icon is None:
        icon = _make(action_id, text)
        _cache[action_id] = icon
    return icon


def _make(action_id: str, text: str) -> QIcon:
    painted = _PAINTED.get(action_id)
    if painted is not None:
        return painted()
    if action_id in ("delete", "open_trash"):
        return trash_icons()[0]
    themed = _theme(THEME_NAMES.get(action_id, ()))
    if themed is not None:
        return themed
    fallback = _FALLBACK.get(action_id)
    if fallback is not None:
        return fallback()
    return _badge(text or action_id)


# --- Selbst gezeichnete Symbole ------------------------------------------------------------
def _pen(color: QColor, width: float = 2.0) -> QPen:
    return QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


def icon_back() -> QIcon:
    """Geschwungener Pfeil nach links."""
    _fg, accent = _colors()

    def draw(p: QPainter) -> None:
        path = QPainterPath(QPointF(20, 18))
        path.cubicTo(QPointF(20, 9), QPointF(14, 7.5), QPointF(8, 8))
        p.setPen(_pen(accent, 2.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        head = QPainterPath(QPointF(3, 8))
        head.lineTo(QPointF(9, 3.2))
        head.lineTo(QPointF(9, 12.8))
        head.closeSubpath()
        p.setPen(_pen(accent, 1.0))
        p.setBrush(accent)
        p.drawPath(head)
    return _paint_icon(draw)


def icon_forward() -> QIcon:
    return _mirror(icon_back())


def _panes(p: QPainter, fg: QColor, two: bool) -> None:
    p.setPen(_pen(fg, 1.4))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRoundedRect(QRectF(2.5, 4, 19, 16), 2, 2)
    p.drawLine(QPointF(2.5, 7.5), QPointF(21.5, 7.5))
    if two:
        p.drawLine(QPointF(12, 7.5), QPointF(12, 20))


def icon_single() -> QIcon:
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        _panes(p, fg, False)
        p.setPen(_pen(accent, 1.8))
        for y in (11, 14, 17):
            p.drawLine(QPointF(6, y), QPointF(18, y))
    return _paint_icon(draw)


def icon_sidebar() -> QIcon:
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        _panes(p, fg, False)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawRect(QRectF(3.2, 8.2, 5.5, 11.1))
    return _paint_icon(draw)


def icon_buttonbar() -> QIcon:
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        _panes(p, fg, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        for y in (10, 13.5, 17):
            p.drawEllipse(QRectF(10.6, y - 1.4, 2.8, 2.8))
    return _paint_icon(draw)


def icon_fkeybar() -> QIcon:
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        _panes(p, fg, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        for x in (4, 9.6, 15.2):
            p.drawRoundedRect(QRectF(x, 16, 4.8, 2.8), 0.8, 0.8)
    return _paint_icon(draw)


def icon_toolbar() -> QIcon:
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        _panes(p, fg, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        for x in (4, 8, 12, 16):
            p.drawRoundedRect(QRectF(x, 4.6, 2.6, 2.4), 0.6, 0.6)
    return _paint_icon(draw)


def icon_hidden() -> QIcon:
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        eye = QPainterPath(QPointF(2.5, 12))
        eye.quadTo(QPointF(12, 2.5), QPointF(21.5, 12))
        eye.quadTo(QPointF(12, 21.5), QPointF(2.5, 12))
        p.setPen(_pen(fg, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(eye)
        p.setBrush(accent)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(9, 9, 6, 6))
    return _paint_icon(draw)


def _box(p: QPainter, fg: QColor) -> None:
    """Archiv-Karton."""
    p.setPen(_pen(fg, 1.4))
    p.setBrush(QColor("#D9B26F"))
    p.drawRect(QRectF(3, 9, 18, 12))
    p.drawLine(QPointF(3, 9), QPointF(5.5, 5))
    p.drawLine(QPointF(21, 9), QPointF(18.5, 5))
    p.drawLine(QPointF(5.5, 5), QPointF(18.5, 5))
    p.setPen(_pen(QColor("#7A5A20"), 1.2))
    for y in (11.5, 14, 16.5, 19):
        p.drawLine(QPointF(11, y), QPointF(13, y))


def icon_compress() -> QIcon:
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        _box(p, fg)
        head = QPainterPath(QPointF(12, 8.5))
        head.lineTo(QPointF(8, 3.5))
        head.lineTo(QPointF(16, 3.5))
        head.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawPath(head)
    return _paint_icon(draw)


def icon_extract() -> QIcon:
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        _box(p, fg)
        head = QPainterPath(QPointF(12, 0.5))
        head.lineTo(QPointF(8, 5.5))
        head.lineTo(QPointF(16, 5.5))
        head.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(accent)
        p.drawPath(head)
    return _paint_icon(draw)


def icon_switch_panel() -> QIcon:
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        _panes(p, fg, True)
        _arrow(p, 6, 18, 14, accent, 2.0)
    return _paint_icon(draw)


def icon_star() -> QIcon:
    _fg, _accent = _colors()

    def draw(p: QPainter) -> None:
        import math

        path = QPainterPath()
        for i in range(10):
            r = 9.5 if i % 2 == 0 else 4.2
            a = -math.pi / 2 + i * math.pi / 5
            pt = QPointF(12 + r * math.cos(a), 12.5 + r * math.sin(a))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        path.closeSubpath()
        p.setPen(_pen(QColor("#B8860B"), 1.2))
        p.setBrush(QColor("#F5C211"))
        p.drawPath(path)
    return _paint_icon(draw)


def icon_up() -> QIcon:
    _fg, accent = _colors()

    def draw(p: QPainter) -> None:
        p.save()
        p.translate(12, 12)
        p.rotate(-90)
        p.translate(-12, -12)
        _arrow(p, 3, 21, 12, accent, 2.4)
        p.restore()
    return _paint_icon(draw)


def icon_new_textfile() -> QIcon:
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        _page(p, 4, 2.5, 13, 18, fg, QColor("white"))
        p.setPen(_pen(accent, 2.2))
        p.drawLine(QPointF(19, 14), QPointF(19, 22))
        p.drawLine(QPointF(15, 18), QPointF(23, 18))
    return _paint_icon(draw)


def icon_refresh() -> QIcon:
    _fg, accent = _colors()

    def draw(p: QPainter) -> None:
        p.setPen(_pen(accent, 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(4, 4, 16, 16), 60 * 16, 280 * 16)
        head = QPainterPath(QPointF(20.5, 3))
        head.lineTo(QPointF(20.5, 10))
        head.lineTo(QPointF(13.5, 8))
        head.closeSubpath()
        p.setPen(_pen(accent, 1.0))
        p.setBrush(accent)
        p.drawPath(head)
    return _paint_icon(draw)


def icon_quit() -> QIcon:
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        p.setPen(_pen(fg, 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(3, 3, 11, 18), 1.5, 1.5)
        _arrow(p, 9, 22, 12, accent, 2.2)
    return _paint_icon(draw)


def icon_filter(active: bool = False) -> QIcon:
    """Trichter: dunkelgrau = Filter aus, rot = Filter aktiv (F-606)."""
    color = QColor("#D32F2F") if active else QColor("#4A4A4A")

    def draw(p: QPainter) -> None:
        path = QPainterPath(QPointF(3, 4))
        path.lineTo(QPointF(21, 4))
        path.lineTo(QPointF(14, 12.5))
        path.lineTo(QPointF(14, 19.5))
        path.lineTo(QPointF(10, 21.5))
        path.lineTo(QPointF(10, 12.5))
        path.closeSubpath()
        p.setPen(_pen(color.darker(130), 1.2))
        p.setBrush(color)
        p.drawPath(path)
    return _paint_icon(draw)


def icon_filter_define() -> QIcon:
    fg, accent = _colors()
    funnel = icon_filter(False)

    def draw(p: QPainter) -> None:
        p.drawPixmap(0, 0, funnel.pixmap(20, 20))
        p.setPen(_pen(accent, 2.2))
        p.drawLine(QPointF(15, 22), QPointF(22, 15))
    return _paint_icon(draw)


def _badge(text: str) -> QIcon:
    """Notlösung: abgerundetes Kästchen mit den ersten beiden Buchstaben."""
    fg, accent = _colors()
    letters = "".join(ch for ch in text if ch.isalnum())[:2] or "?"

    def draw(p: QPainter) -> None:
        p.setPen(_pen(accent, 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(2, 3, 20, 18), 4, 4)
        font = QFont()
        font.setPixelSize(10)
        font.setBold(True)
        p.setFont(font)
        p.setPen(fg)
        p.drawText(QRectF(2, 3, 20, 18), Qt.AlignmentFlag.AlignCenter, letters)
    return _paint_icon(draw)


# --- v0.9.10: Prüfsumme, Mehrfach-Umbenennen, Rückgängig, Lupe/Zahnrad als Ersatz ---------------
def icon_hash() -> QIcon:
    """Hash-Zeichen „#“ für die Prüfsummen."""
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        p.setPen(_pen(accent, 2.3))
        p.drawLine(QPointF(9.5, 3.5), QPointF(7.5, 20.5))
        p.drawLine(QPointF(16.5, 3.5), QPointF(14.5, 20.5))
        p.setPen(_pen(fg, 2.3))
        p.drawLine(QPointF(4, 8.5), QPointF(20.5, 8.5))
        p.drawLine(QPointF(3.5, 15.5), QPointF(20, 15.5))
    return _paint_icon(draw)


def _rename_icon(undo: bool) -> QIcon:
    """„ABC“ oben, „DEF“ unten, geschwungener Pfeil von oben nach unten (Rückgängig: von unten nach oben)."""
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        font = QFont()
        font.setBold(True)
        font.setPixelSize(8)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.3)
        p.setFont(font)
        p.setPen(fg)
        p.drawText(QRectF(0, 1, 17, 9), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "ABC")
        p.drawText(QRectF(0, 14, 17, 9), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "DEF")
        start, end = (QPointF(16.8, 18.5), QPointF(18.5, 5.5)) if undo else (QPointF(16.8, 5.5), QPointF(18.5, 18.5))
        path = QPainterPath(start)
        path.cubicTo(QPointF(24.0, start.y()), QPointF(24.0, end.y()), end)
        p.setPen(_pen(accent, 1.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        # Pfeilspitze am Ende, nach links zeigend
        head = QPainterPath(QPointF(end.x() - 3.2, end.y()))
        head.lineTo(QPointF(end.x() + 1.2, end.y() - 3.2))
        head.lineTo(QPointF(end.x() + 1.2, end.y() + 3.2))
        head.closeSubpath()
        p.setPen(_pen(accent, 0.8))
        p.setBrush(accent)
        p.drawPath(head)
    return _paint_icon(draw)


def icon_multi_rename() -> QIcon:
    return _rename_icon(False)


def icon_rename_undo() -> QIcon:
    return _rename_icon(True)


def icon_search() -> QIcon:
    """Lupe (nur wenn das Symbolthema keine hat)."""
    fg, accent = _colors()

    def draw(p: QPainter) -> None:
        p.setPen(_pen(fg, 2.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(10, 10), 6, 6)
        p.setPen(_pen(accent, 3.0))
        p.drawLine(QPointF(14.5, 14.5), QPointF(20.5, 20.5))
    return _paint_icon(draw)


def icon_gear() -> QIcon:
    """Zahnrad (nur wenn das Symbolthema keins hat)."""
    import math

    fg, _accent = _colors()

    def draw(p: QPainter) -> None:
        path = QPainterPath()
        teeth, r_out, r_in = 8, 10.0, 7.6
        points = []
        for i in range(teeth * 4):
            angle = math.pi * 2 * i / (teeth * 4)
            r = r_out if i % 4 in (1, 2) else r_in
            points.append(QPointF(12 + r * math.cos(angle), 12 + r * math.sin(angle)))
        path.moveTo(points[0])
        for pt in points[1:]:
            path.lineTo(pt)
        path.closeSubpath()
        path.addEllipse(QPointF(12, 12), 3.2, 3.2)
        path.setFillRule(Qt.FillRule.OddEvenFill)
        p.setPen(_pen(fg, 1.0))
        p.setBrush(fg)
        p.drawPath(path)
    return _paint_icon(draw)


_PAINTED = {
    "back": icon_back,
    "forward": icon_forward,
    "toggle_single": icon_single,
    "toggle_sidebar": icon_sidebar,
    "toggle_buttonbar": icon_buttonbar,
    "toggle_fkeybar": icon_fkeybar,
    "toggle_toolbar": icon_toolbar,
    "toggle_hidden": icon_hidden,
    "compress": icon_compress,
    "extract_here": icon_extract,
    "extract_subfolder": icon_extract,
    "extract_to": icon_extract,
    "switch_panel": icon_switch_panel,
    "filter_toggle": icon_filter,
    "filter_define": icon_filter_define,
    "same_path": icon_same_path,
    "swap_panels": icon_swap,
    "copy": icon_copy,
    "copy_direct": icon_copy,
    "move": icon_move,
    "move_direct": icon_move,
    "checksums": icon_hash,
    "multi_rename": icon_multi_rename,
    "rename_undo": icon_rename_undo,
}

# Nur wenn das Symbolthema nichts liefert
_FALLBACK = {
    "go_up": icon_up,
    "add_favorite": icon_star,
    "new_textfile": icon_new_textfile,
    "refresh": icon_refresh,
    "quit": icon_quit,
    "search": icon_search,
    "settings_dialog": icon_gear,
}
