"""Plattform-Weichen. Linux ist die Hauptplattform; Windows ist derzeit eine Vorschau.

Funktionen, die (noch) nur unter Linux umgesetzt sind, werden unter Windows
ausgegraut statt versteckt, damit sichtbar bleibt, was später kommt.
"""

from __future__ import annotations

import os
import string
import sys

IS_LINUX = sys.platform.startswith("linux")
IS_WINDOWS = sys.platform.startswith("win")

# Aktionen, die unter Windows (Vorschau) noch nicht umgesetzt sind
WINDOWS_DISABLED_ACTIONS = {"open_with_other", "open_trash", "trash_restore", "trash_purge", "trash_empty"}


def windows_drives() -> list[str]:
    """Vorhandene Laufwerke, z. B. ['C:\\\\', 'D:\\\\']."""
    if hasattr(os, "listdrives"):
        try:
            return list(os.listdrives())
        except OSError:
            pass
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
