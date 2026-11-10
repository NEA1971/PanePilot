"""Kleine Hilfsfunktionen: Formatierung, Pfade, Öffnen mit Standardprogramm."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QUrl
from PySide6.QtGui import QDesktopServices

from .i18n import t


SIZE_UNITS = ("auto", "B", "KB", "MB", "GB", "KiB", "MiB", "GiB")
_size_unit = "auto"  # F-844, wird beim Start aus den Einstellungen gesetzt
_FIXED = {"KB": (1000, "size.kb"), "MB": (1000 ** 2, "size.mb"), "GB": (1000 ** 3, "size.gb"),
          "KiB": (1024, "size.kib"), "MiB": (1024 ** 2, "size.mib"), "GiB": (1024 ** 3, "size.gib")}


def set_size_unit(unit: str) -> None:
    global _size_unit
    _size_unit = unit if unit in SIZE_UNITS else "auto"


def _num(value: float, decimals: int) -> str:
    text = f"{value:,.{decimals}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return text


def format_size(size: int, unit: str | None = None) -> str:
    """Größe für die Anzeige. „auto“ = lesbar in 1000er-Schritten wie GNOME (F-844)."""
    unit = unit or _size_unit
    if unit == "B":
        return t("size.bytes", n=_num(size, 0))
    if unit in _FIXED:
        div, key = _FIXED[unit]
        value = size / div
        return t(key, n=_num(value, 0 if value >= 100 or value == 0 else 1 if value >= 10 else 2))
    if size < 1000:
        return t("size.bytes", n=size)
    value = float(size)
    for key in ("size.kb", "size.mb", "size.gb", "size.tb"):
        value /= 1000.0
        if value < 1000.0 or key == "size.tb":
            text = f"{value:.1f}" if value < 100 else f"{value:.0f}"
            return t(key, n=text.replace(".", ","))
    return str(size)


def nearest_existing_dir(path: str) -> str:
    """Nächster vorhandener und lesbarer Ordner (der Pfad selbst oder ein Elternordner)."""
    p = Path(path)
    while True:
        if p.is_dir() and os.access(p, os.R_OK | os.X_OK):
            return str(p)
        if p.parent == p:
            return str(Path.home())
        p = p.parent


def is_inside(child: str, parent: str) -> bool:
    """True, wenn child gleich parent ist oder darin liegt (nach Auflösen von Links)."""
    try:
        c = os.path.realpath(child)
        p = os.path.realpath(parent)
    except OSError:
        return False
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def unique_name(directory: str, name: str) -> str:
    """'bericht.txt' → 'bericht (2).txt', falls schon vorhanden."""
    stem, ext = os.path.splitext(name)
    if name.startswith(".") and stem == name:
        ext = ""
    candidate = name
    n = 2
    while os.path.lexists(os.path.join(directory, candidate)):
        candidate = f"{stem} ({n}){ext}"
        n += 1
    return candidate


def child_environment() -> QProcessEnvironment:
    """Umgebung für gestartete Programme ohne die Bibliothekspfade des AppImage.

    Sonst könnten Programme, die PanePilot öffnet, versehentlich die mitgelieferten
    Qt-Bibliotheken laden und abstürzen.
    """
    env = QProcessEnvironment.systemEnvironment()
    for var in ("LD_LIBRARY_PATH", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
        orig = env.value(var + "_ORIG")
        if orig:
            env.insert(var, orig)
        else:
            env.remove(var)
        env.remove(var + "_ORIG")
    for var in ("PYTHONHOME", "PYTHONPATH", "_MEIPASS2", "_PYI_APPLICATION_HOME_DIR", "_PYI_ARCHIVE_FILE", "_PYI_PARENT_PROCESS_LEVEL"):
        env.remove(var)
    # Angaben der AppImage-Laufzeit (v0.9.9): Ein gestartetes AppImage mit eigenem Updater
    # hielte sonst die PanePilot-Datei für seine eigene und schriebe sein Update darüber.
    for var in APPIMAGE_VARS:
        env.remove(var)
    return env


APPIMAGE_VARS = ("APPIMAGE", "APPDIR", "ARGV0", "OWD", "APPIMAGE_EXTRACT_AND_RUN", "APPIMAGE_UUID")


def _start_detached(program: str, args: list[str], workdir: str) -> bool:
    proc = QProcess()
    proc.setProgram(program)
    proc.setArguments(args)
    proc.setWorkingDirectory(workdir)
    proc.setProcessEnvironment(child_environment())
    return detached_ok(proc.startDetached())


def detached_ok(result) -> bool:
    """QProcess.startDetached() liefert je nach PySide-Version bool oder (bool, pid)."""
    return bool(result[0] if isinstance(result, tuple) else result)


def open_with_default_app(path: str) -> bool:
    """Öffnet eine Datei mit dem Standardprogramm des Systems.

    Ausführbare Programme (z. B. AppImages, Binärdateien) werden direkt gestartet.
    """
    workdir = os.path.dirname(path) or str(Path.home())
    if sys.platform.startswith("linux"):
        if _is_executable_program(path):
            return _start_detached(path, [], workdir)
        # „gio open“ öffnet wie Nautilus und übergibt korrekt kodierte Adressen (v0.9.8);
        # xdg-open nur, wenn gio fehlt
        import shutil

        if shutil.which("gio"):
            return _start_detached("gio", ["open", path], workdir)
        return _start_detached("xdg-open", [path], workdir)
    return QDesktopServices.openUrl(QUrl.fromLocalFile(path))


def open_url(url: str) -> bool:
    """Öffnet eine Internetadresse im Standard-Browser (v0.9.11)."""
    if sys.platform.startswith("linux"):
        import shutil

        if shutil.which("gio"):
            return _start_detached("gio", ["open", url], str(Path.home()))
        if shutil.which("xdg-open"):
            return _start_detached("xdg-open", [url], str(Path.home()))
    return QDesktopServices.openUrl(QUrl(url))


def _is_executable_program(path: str) -> bool:
    if os.path.isdir(path) or not os.access(path, os.X_OK):
        return False
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
    except OSError:
        return False
    return head == b"\x7fELF"
