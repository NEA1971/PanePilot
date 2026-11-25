"""Wie PanePilot installiert ist: AppImage, .deb, .rpm oder aus dem Quellcode (v2.0, L-3000 ff.)."""

from __future__ import annotations

import os
import sys

APPIMAGE, DEB, RPM, SOURCE, FROZEN = "appimage", "deb", "rpm", "source", "frozen"
WINSETUP, WINZIP = "winsetup", "winzip"  # v3.0 (L-4001/L-4002): Windows-Setup bzw. portables ZIP


def package_format() -> str | None:
    """„deb“/„rpm“ bzw. „winsetup“/„winzip“, wenn PanePilot aus einem Paket läuft (Datei PACKAGE neben dem
    Programm, z. B. /opt/panepilot/PACKAGE)."""
    if not getattr(sys, "frozen", False) or os.environ.get("APPIMAGE"):
        return None
    marker = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "PACKAGE")
    try:
        with open(marker, encoding="ascii") as fh:
            kind = fh.read().strip()
    except OSError:
        return None
    return kind if kind in (DEB, RPM, WINSETUP, WINZIP) else None


def kind() -> str:
    if os.environ.get("APPIMAGE"):
        return APPIMAGE
    fmt = package_format()
    if fmt:
        return fmt
    return FROZEN if getattr(sys, "frozen", False) else SOURCE


def install_command(path: str, fmt: str) -> str:
    """Befehl für das Terminal (Hinweis nach dem Herunterladen, L-3004)."""
    name = os.path.basename(path)
    folder = os.path.dirname(path)
    if fmt == DEB:
        return f"cd \"{folder}\" && sudo apt install ./\"{name}\""
    return f"cd \"{folder}\" && sudo dnf install ./\"{name}\"   (openSUSE: sudo zypper install ./\"{name}\")"
