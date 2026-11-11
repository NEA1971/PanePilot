"""PanePilot ins Anwendungsmenü aufnehmen (v1.1).

Beim Start als AppImage kann PanePilot selbst einen Starter mit Programmsymbol anlegen:
``~/.local/share/applications/panepilot.desktop`` und das Symbol unter ``~/.local/share/icons``.
Der Starter zeigt auf die gerade laufende AppImage-Datei. Startet man später eine andere Datei
(z. B. eine neuere Version), wird der Starter beim Programmstart automatisch nachgeführt.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

DESKTOP_NAME = "panepilot.desktop"  # passt zu QApplication.setDesktopFileName("panepilot")
MARKER = "X-PanePilot-Integration=1"


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def desktop_path() -> Path:
    return _data_home() / "applications" / DESKTOP_NAME


def icon_path() -> Path:
    return _data_home() / "icons" / "hicolor" / "scalable" / "apps" / "panepilot.svg"


def appimage_path() -> str | None:
    """Pfad der laufenden AppImage-Datei (nur beim Start als AppImage)."""
    path = os.environ.get("APPIMAGE")
    return path if path and os.path.isfile(path) else None


def is_integrated() -> bool:
    try:
        return MARKER in desktop_path().read_text(encoding="utf-8")
    except OSError:
        return False


def _quote(path: str) -> str:
    # Desktop-Entry-Spezifikation: Argument in Anführungszeichen, \ " ` $ maskieren
    escaped = path.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return f'"{escaped}"'


def desktop_text(appimage: str) -> str:
    from . import __version__

    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=PanePilot",
        "GenericName=File Manager",
        "GenericName[de]=Dateimanager",
        "Comment=Two-panel file manager inspired by FreeCommander",
        "Comment[de]=Zwei-Fenster-Dateimanager nach dem Vorbild von FreeCommander",
        f"Exec={_quote(appimage)} %U",
        f"TryExec={appimage}",
        "Icon=panepilot",
        "Terminal=false",
        "Categories=System;FileTools;FileManager;",
        "Keywords=files;folders;file manager;commander;rename;tags;checksum;",
        "Keywords[de]=Dateien;Ordner;Dateimanager;Commander;Umbenennen;Tags;Prüfsumme;",
        "StartupWMClass=PanePilot",
        f"X-PanePilot-Version={__version__}",
        MARKER,
        "",
    ])


def other_launchers() -> list[Path]:
    """Andere Starter für PanePilot im eigenen Anwendungsordner (z. B. selbst angelegte)."""
    folder = _data_home() / "applications"
    found = []
    try:
        for p in sorted(folder.glob("*.desktop")):
            if p.name == DESKTOP_NAME:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "panepilot" in text.casefold():
                found.append(p)
    except OSError:
        pass
    return found


def integrate(appimage: str | None = None) -> Path:
    """Starter und Symbol anlegen bzw. erneuern. OSError bei Schreibfehlern."""
    from .resources import resource_path

    appimage = appimage or appimage_path()
    if not appimage:
        raise OSError("APPIMAGE")
    icon = icon_path()
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(resource_path("icons", "panepilot.svg"), icon)
    target = desktop_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(desktop_text(appimage), encoding="utf-8")
    target.chmod(0o755)
    _refresh_caches()
    return target


def remove() -> None:
    for p in (desktop_path(), icon_path()):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    _refresh_caches()


def update_if_moved() -> bool:
    """Beim Programmstart: Starter auf die laufende AppImage-Datei nachführen. True, wenn geändert."""
    current = appimage_path()
    if not current or not is_integrated():
        return False
    try:
        text = desktop_path().read_text(encoding="utf-8")
    except OSError:
        return False
    if desktop_text(current) == text:
        return False
    try:
        integrate(current)
    except OSError:
        return False
    return True


def _refresh_caches() -> None:
    """Menü und Symbole aktualisieren (die Programme sind optional)."""
    from .util import child_environment

    apps = str(_data_home() / "applications")
    for cmd in (["update-desktop-database", apps], ["gtk-update-icon-cache", "-q", "-t", "-f",
                                                       str(_data_home() / "icons" / "hicolor")]):
        if shutil.which(cmd[0]):
            from PySide6.QtCore import QProcess

            proc = QProcess()
            proc.setProcessEnvironment(child_environment())
            proc.start(cmd[0], cmd[1:])
            proc.waitForFinished(3000)
