"""Favoriten aus FreeCommander XE übernehmen (v3.1, L-4100 ff., nur Windows im Menü).

FreeCommander speichert seine Favoriten in ``%APPDATA%\\FreeCommander XE\\Settings\\FreeCommander.fav*.xml``
(UTF-16 oder UTF-8). Aufbau::

    <FreeCommanderXE_favorite_items>
      <category text="…" expanded="-1" font_color="…">            (beliebig tief)
        <folder_item text="…" folder_active="C:\\…" folder_inactive="" font_color="…" …/>
        <file_item text="…" file="C:\\…\\x.txt" font_color="…" …/>
      </category>
    </FreeCommanderXE_favorite_items>

Farben sind Delphi-TColor-Werte (BGR); 536870911 (clNone) und negative Werte (Systemfarben) heißen „keine Farbe“.
Übernommen werden Kategorien (auf-/zugeklappt), Ordner, Dateien und die Schriftfarbe (nächste PanePilot-Farbe).
"""

from __future__ import annotations

import glob
import os
import re
import uuid
import xml.etree.ElementTree as ET

from .favorites import FAV_COLORS

CL_NONE = 536870911
SET_NAME = "FreeCommander"


def settings_folder() -> str:
    return os.path.join(os.environ.get("APPDATA", ""), "FreeCommander XE", "Settings")


def newest_file(folder: str) -> str | None:
    """Die zuletzt geänderte FreeCommander.fav*.xml im Ordner."""
    files = [f for f in glob.glob(os.path.join(folder, "FreeCommander.fav*.xml")) if os.path.isfile(f)]
    return max(files, key=os.path.getmtime) if files else None


def decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    elif raw.startswith(b"\xef\xbb\xbf"):
        text = raw[3:].decode("utf-8")
    elif len(raw) > 1 and raw[1:2] == b"\x00":
        text = raw.decode("utf-16-le")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
    return re.sub(r"^\s*<\?xml[^>]*\?>", "", text)  # Kodierungsangabe passt nach dem Dekodieren nicht mehr


def color_key(value) -> str | None:
    """TColor (BGR) → nächste PanePilot-Farbe; None = Standard."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return None
    if v < 0 or v == CL_NONE or v > 0xFFFFFF:
        return None
    r, g, b = v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF
    best, dist = None, None
    for key, hexval in FAV_COLORS:
        cr, cg, cb = int(hexval[1:3], 16), int(hexval[3:5], 16), int(hexval[5:7], 16)
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dist is None or d < dist:
            best, dist = key, d
    return best


def _name(text: str, path: str) -> str:
    text = (text or "").strip()
    if text:
        return text
    tail = path.rstrip("\\/")
    return os.path.basename(tail.replace("\\", "/")) or path


def _convert(elem, expanded: list[str]) -> list[dict]:
    items: list[dict] = []
    for child in elem:
        tag = child.tag
        a = child.attrib
        color = color_key(a.get("font_color"))
        style = {"color": color} if color else {}
        if tag == "category":
            gid = uuid.uuid4().hex
            node = {"id": gid, "type": "group", "name": (a.get("text") or "").strip() or "?",
                    "children": _convert(child, expanded)}
            if a.get("expanded", "0") not in ("0", "", "false", "False"):
                expanded.append(gid)
        elif tag == "folder_item":
            path = (a.get("folder_active") or a.get("folder_inactive") or "").strip()
            if not path:
                continue
            node = {"id": uuid.uuid4().hex, "type": "link", "name": _name(a.get("text"), path), "path": path}
        elif tag == "file_item":
            path = (a.get("file") or "").strip()
            if not path:
                continue
            node = {"id": uuid.uuid4().hex, "type": "link", "name": _name(a.get("text"), path), "path": path}
        else:
            continue
        if style:
            node["style"] = style
        items.append(node)
    return items


def parse(raw: bytes) -> tuple[dict, list[str]]:
    """Datei-Inhalt → (Favoriten-Daten im PanePilot-Format, IDs der aufgeklappten Ordner). Wirft ValueError."""
    try:
        root = ET.fromstring(decode(raw))
    except ET.ParseError as exc:
        raise ValueError(str(exc)) from exc
    if root.tag != "FreeCommanderXE_favorite_items":
        raise ValueError("no FreeCommander favorites")
    expanded: list[str] = []
    return {"version": 1, "items": _convert(root, expanded)}, expanded


def count(items: list[dict]) -> int:
    return sum(count(i.get("children", [])) if i.get("type") == "group" else 1 for i in items)


def unique_set_name(existing: list[str], base: str = SET_NAME) -> str:
    folded = {n.casefold() for n in existing}
    if base.casefold() not in folded:
        return base
    n = 2
    while f"{base} {n}".casefold() in folded:
        n += 1
    return f"{base} {n}"
