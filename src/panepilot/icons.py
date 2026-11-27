"""Symbole für Dateien und Ordner aus dem Symbolthema des Systems (GNOME)."""

from __future__ import annotations

import os

from PySide6.QtCore import QMimeDatabase, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QStyle

from .resources import resource_path


class IconProvider:
    def __init__(self) -> None:
        self._db = QMimeDatabase()
        self._cache: dict[str, QIcon] = {}
        style = QApplication.style()
        self._dir_fallback = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self._file_fallback = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        self._link_fallback = style.standardIcon(QStyle.StandardPixmap.SP_FileLinkIcon)
        self._up = QIcon.fromTheme("go-up", style.standardIcon(QStyle.StandardPixmap.SP_FileDialogToParent))
        self._folder = QIcon.fromTheme("folder", self._dir_fallback)
        from .platform import IS_WINDOWS

        if IS_WINDOWS:  # v3.2 (L-4205): gefüllte blaue Ordner wie unter Linux statt der dünnen Windows-11-Umrisse
            self._folder = QIcon(str(resource_path("icons", "folder.svg")))
            self._dir_fallback = self._folder
        self._group = QIcon.fromTheme("user-bookmarks", QIcon.fromTheme("bookmark-new", self._folder))
        self._network = _network_folder_icon(self._folder)
        self._network_off = _disabled_icon(self._network)
        self._drive = QIcon.fromTheme("drive-harddisk", style.standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))
        self._removable = QIcon.fromTheme("drive-removable-media",
                                          style.standardIcon(QStyle.StandardPixmap.SP_DriveFDIcon))
        self._no_entry = QIcon(str(resource_path("icons", "no-entry.svg")))
        self.mounts = None  # wird vom Hauptfenster gesetzt (MountManager)

    def mime_for(self, path: str):
        return self._db.mimeTypeForFile(path, QMimeDatabase.MatchMode.MatchExtension)

    def folder(self) -> QIcon:
        return self._folder

    def network_folder(self, mounted: bool = True) -> QIcon:
        return self._network if mounted else self._network_off

    def drive(self, removable: bool = False, mounted: bool = True) -> QIcon:
        icon = self._removable if removable else self._drive
        return icon if mounted else _disabled_icon(icon)

    def no_entry(self) -> QIcon:
        return self._no_entry

    def mount_icon(self, entry) -> QIcon:
        from .mounts import KIND_NETWORK, KIND_REMOVABLE

        if entry.kind == KIND_NETWORK:
            return self.network_folder(entry.mounted)
        return self.drive(entry.kind == KIND_REMOVABLE, entry.mounted)

    def disk_icon(self, kind: str, enabled: bool = True) -> QIcon:
        style = QApplication.style()
        if kind == "usb":
            icon = self._removable
        elif kind == "optical":
            icon = QIcon.fromTheme("drive-optical", style.standardIcon(QStyle.StandardPixmap.SP_DriveCDIcon))
        elif kind == "image":
            icon = QIcon.fromTheme("media-optical", style.standardIcon(QStyle.StandardPixmap.SP_DriveCDIcon))
        else:
            icon = self._drive
        return icon if enabled else _disabled_icon(icon)

    def dir_icon(self, path: str) -> QIcon:
        """Ordnersymbol – bei Einhängepunkten Netzwerk-/Laufwerkssymbol."""
        if self.mounts is not None:
            entry = self.mounts.entry_for_mount_point(path)
            if entry is not None:
                return self.mount_icon(entry)
        return self._folder

    def parent_entry(self) -> QIcon:
        return self._up

    def favorite_group(self) -> QIcon:
        return self._group

    def missing(self) -> QIcon:
        return QIcon.fromTheme("dialog-question", self._file_fallback)

    def for_file(self, path: str) -> QIcon:
        from .platform import IS_WINDOWS

        if IS_WINDOWS:
            # Windows: Symbole des Systems (es gibt dort kein freedesktop-Symbolthema)
            from PySide6.QtCore import QFileInfo
            from PySide6.QtWidgets import QFileIconProvider

            ext = os.path.splitext(path)[1].lower()
            icon = self._cache.get("win:" + ext)
            if icon is None:
                if not hasattr(self, "_win_provider"):
                    self._win_provider = QFileIconProvider()
                if path.startswith(("\\\\", "//")):  # v3.2.1: Netzpfad – Symbol nur nach Endung
                    return self.for_extension(path)
                icon = self._win_provider.icon(QFileInfo(path)) if os.path.exists(path) else self._file_fallback
                if ext not in (".exe", ".lnk", ".ico", ".url"):  # diese haben je Datei eigene Symbole
                    self._cache["win:" + ext] = icon
            return icon
        mime = self.mime_for(path)
        name = mime.name()
        icon = self._cache.get(name)
        if icon is None:
            icon = QIcon.fromTheme(mime.iconName())
            if icon.isNull():
                icon = QIcon.fromTheme(mime.genericIconName(), self._file_fallback)
            self._cache[name] = icon
        return icon

    def for_extension(self, path: str) -> QIcon:
        """Symbol nur nach Dateiendung – fragt nicht beim (evtl. langsamen) Speicherort nach (v3.2.1)."""
        from .platform import IS_WINDOWS

        ext = os.path.splitext(path)[1].lower()
        if IS_WINDOWS:
            icon = self._cache.get("win:" + ext)
            if icon is None:
                import tempfile

                from PySide6.QtCore import QFileInfo
                from PySide6.QtWidgets import QFileIconProvider

                if not hasattr(self, "_win_provider"):
                    self._win_provider = QFileIconProvider()
                probe = os.path.join(tempfile.gettempdir(), "panepilot-icon" + ext)
                try:
                    if not os.path.exists(probe):
                        open(probe, "wb").close()
                    icon = self._win_provider.icon(QFileInfo(probe))
                except OSError:
                    icon = self._file_fallback
                if ext not in (".exe", ".lnk", ".ico", ".url"):
                    self._cache["win:" + ext] = icon
            return icon
        return self.for_file(path)

    def type_text(self, path: str) -> str:
        return self.mime_for(path).comment()


_SIZES = (16, 22, 24, 32, 48, 64)


def _network_folder_icon(folder: QIcon) -> QIcon:
    """Ordnersymbol mit „Netzwerkanschluss“ darunter (wie in Nautilus)."""
    icon = QIcon()
    for size in _SIZES:
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        fs = round(size * 0.78)
        p.drawPixmap(round((size - fs) / 2), 0, folder.pixmap(fs, fs))
        # Anschluss: senkrechter Strich und waagerechte Leiste mit drei Knoten
        dark = QColor("#2E3436")
        pen = QPen(dark, max(1.0, size / 16))
        p.setPen(pen)
        cx = size / 2
        top = fs * 0.92
        bar_y = size - max(2.0, size * 0.09)
        p.drawLine(QPointF(cx, top), QPointF(cx, bar_y))
        p.drawLine(QPointF(size * 0.18, bar_y), QPointF(size * 0.82, bar_y))
        r = max(1.2, size / 14)
        p.setBrush(dark)
        for x in (size * 0.18, cx, size * 0.82):
            p.drawEllipse(QRectF(x - r, bar_y - r, 2 * r, 2 * r))
        p.end()
        icon.addPixmap(pm)
    return icon


def _disabled_icon(icon: QIcon) -> QIcon:
    result = QIcon()
    for size in _SIZES:
        result.addPixmap(icon.pixmap(size, size, QIcon.Mode.Disabled))
    return result


def app_icon() -> QIcon:
    return QIcon(str(resource_path("icons", "panepilot.svg")))
