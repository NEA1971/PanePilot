"""Plattform-Weichen (Linux und – seit v3.0 – Windows).

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
WINDOWS_DISABLED_ACTIONS: set[str] = set()  # v3.0: Papierkorb und „Öffnen mit“ gibt es jetzt auch unter Windows


def windows_drives() -> list[str]:
    """Vorhandene Laufwerke, z. B. ['C:\\\\', 'D:\\\\']."""
    if hasattr(os, "listdrives"):
        try:
            return list(os.listdrives())
        except OSError:
            pass
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
