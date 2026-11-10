"""Spaltenprofile (F-842): sichtbare Spalten, Reihenfolge, Breite und Ausrichtung.

Ablage: Settings/Spalten/<Name>.json mit
``{"header": <QHeaderView-Zustand als Hex>, "columns": <Spaltenzahl>, "align": {"<spalte>": "left|center|right"}}``.
"""

from __future__ import annotations

import os

from .config import config_dir, load_json, save_json

SUBDIR = "Spalten"
DEFAULT_PROFILE = "Standard"
ALIGNMENTS = ("left", "center", "right")
_FORBIDDEN = set('/\\:*?"<>|')


def folder() -> str:
    path = os.path.join(str(config_dir()), SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def names() -> list[str]:
    try:
        files = os.listdir(folder())
    except OSError:
        return []
    return sorted((f[:-5] for f in files if f.endswith(".json") and not f.startswith(".")), key=str.casefold)


def load(name: str) -> dict:
    data = load_json(f"{SUBDIR}/{name}.json", {})
    if not isinstance(data, dict):
        return {}
    align = data.get("align") if isinstance(data.get("align"), dict) else {}
    data["align"] = {int(k): v for k, v in align.items() if str(k).isdigit() and v in ALIGNMENTS}
    return data


def save(name: str, data: dict) -> None:
    out = dict(data)
    out["align"] = {str(k): v for k, v in (data.get("align") or {}).items()}
    save_json(f"{SUBDIR}/{name}.json", out)


def delete(name: str) -> None:
    os.unlink(os.path.join(folder(), name + ".json"))


def rename(old: str, new: str) -> None:
    os.rename(os.path.join(folder(), old + ".json"), os.path.join(folder(), new + ".json"))


def name_error(name: str, ignore: str | None = None) -> str | None:
    name = name.strip()
    if not name or name in (".", ".."):
        return "favsets.error_empty"
    if any(c in _FORBIDDEN for c in name) or name.startswith("."):
        return "favsets.error_chars"
    if any(n.casefold() == name.casefold() for n in names() if n != ignore):
        return "colprof.error_exists"
    return None
