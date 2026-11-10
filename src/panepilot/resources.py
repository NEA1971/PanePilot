"""Zugriff auf mitgelieferte Dateien (Sprachdateien, Symbole) – auch im AppImage."""

from __future__ import annotations

import sys
from pathlib import Path


def package_dir() -> Path:
    frozen_base = getattr(sys, "_MEIPASS", None)
    if frozen_base:
        return Path(frozen_base) / "panepilot"
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    return package_dir().joinpath(*parts)
