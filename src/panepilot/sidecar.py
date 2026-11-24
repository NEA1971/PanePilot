"""XMP-Begleitdateien für RAW-Fotos (v2.5, L-3500 ff.).

RAW-Dateien selbst werden nie verändert. Titel, Schlagwörter, Bewertung … stehen in einer .xmp-Datei daneben:
- Lightroom: ``IMG_1234.xmp`` (neue Dateien legt PanePilot so an, Wunsch vom 22.11.2026)
- darktable/digiKam: ``IMG_1234.CR2.xmp`` (wird gelesen und weiterbenutzt, wenn es sie schon gibt)

Die Begleitdatei wandert beim Kopieren, Verschieben, Umbenennen und Löschen mit.
"""

from __future__ import annotations

import os

EMPTY_PACKET = ('<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
                '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
                ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
                ' </rdf:RDF>\n'
                '</x:xmpmeta>\n'
                '<?xpacket end="w"?>\n')


def _is_raw(path: str) -> bool:
    from .phototags import is_raw

    return is_raw(path)


def candidates(path: str) -> list[str]:
    """Mögliche Namen – Lightroom-Art zuerst."""
    stem = os.path.splitext(path)[0]
    return [stem + ".xmp", stem + ".XMP", path + ".xmp", path + ".XMP"]


def find(path: str) -> list[str]:
    """Vorhandene Begleitdateien einer RAW-Datei (leer für alle anderen Dateien)."""
    if not path or not _is_raw(path):
        return []
    out, seen = [], set()
    for c in candidates(path):
        if os.path.isfile(c):
            key = os.path.normcase(os.path.realpath(c))
            if key not in seen:  # auf Dateisystemen ohne Groß/klein ist .xmp = .XMP
                seen.add(key)
                out.append(c)
    return out


def write_path(path: str) -> str:
    """Hierhin wird geschrieben: in die vorhandene Datei, sonst neu nach Lightroom-Art."""
    found = find(path)
    return found[0] if found else os.path.splitext(path)[0] + ".xmp"


def renamed(sidecar: str, old_raw: str, new_raw: str) -> str:
    """Neuer Name der Begleitdatei, wenn ``old_raw`` zu ``new_raw`` wird (gleiche Art wie bisher)."""
    base = os.path.basename(sidecar)
    ext = base[-4:]  # „.xmp“ bzw. „.XMP“
    folder = os.path.dirname(new_raw)
    if base[:-4].casefold() == os.path.basename(old_raw).casefold():  # darktable-Art: IMG_1234.CR2.xmp
        return os.path.join(folder, os.path.basename(new_raw) + ext)
    return os.path.join(folder, os.path.splitext(os.path.basename(new_raw))[0] + ext)


def ensure(path: str) -> str:
    """Begleitdatei zum Schreiben (legt eine leere an, wenn es noch keine gibt)."""
    target = write_path(path)
    if not os.path.exists(target):
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(EMPTY_PACKET)
    return target


def follow_rename(old_raw: str, new_raw: str, skip: set | None = None) -> list[tuple[str, str]]:
    """Begleitdateien mit umbenennen (F2, Mehrfach umbenennen, Meta-Wizard). Liefert (alt, neu).

    ``skip``: Dateinamen, die selbst gerade umbenannt werden (dann nicht noch einmal anfassen)."""
    done = []
    for sc in find(old_raw):
        if skip and os.path.basename(sc) in skip:
            continue
        target = renamed(sc, old_raw, new_raw)
        if os.path.normcase(target) == os.path.normcase(sc) or os.path.lexists(target):
            continue
        try:
            os.rename(sc, target)
            done.append((sc, target))
        except OSError:
            pass
    return done
