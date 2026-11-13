"""Welche Dateien der Meta-Wizard gerade zeigt (v1.4): Musik oder Fotos.

Der Meta-Wizard zeigt immer eine Art von Dateien. Felder, Spalten, Seitenleiste und Konverter hängen
davon ab; die Einstellungen werden je Art getrennt gemerkt.
"""

from __future__ import annotations

from . import phototags as ph
from . import tags as tg

AUDIO, PHOTO = "audio", "photo"

_current = AUDIO


def current() -> str:
    return _current


def set_current(kind: str) -> None:
    global _current
    _current = PHOTO if kind == PHOTO else AUDIO


def is_photo_mode() -> bool:
    return _current == PHOTO


def fields() -> tuple[str, ...]:
    return ph.FIELDS if _current == PHOTO else tg.FIELDS


def standard_fields() -> tuple[str, ...]:
    return ph.STANDARD_FIELDS if _current == PHOTO else tg.STANDARD_FIELDS


AUDIO_INFO = ("i:length", "i:bitrate", "i:samplerate", "i:codec", "i:size", "i:mtime")
PHOTO_INFO = ("i:dims", "i:camera", "i:format", "i:size", "i:mtime")


def info_columns() -> tuple[str, ...]:
    return PHOTO_INFO if _current == PHOTO else AUDIO_INFO


AUDIO_COLUMNS = ["filename", "title", "artist", "album", "albumartist", "track", "disc", "year", "genre",
                 "comment", "path"]
PHOTO_COLUMNS = ["filename", "datetaken", "i:camera", "i:dims", "title", "rating", "keywords", "path"]


def default_columns() -> list[str]:
    return list(PHOTO_COLUMNS if _current == PHOTO else AUDIO_COLUMNS)


AUDIO_SIDEBAR = ["title", "artist", "album", "year", "track", "genre", "comment", "albumartist", "composer",
                 "disc", "cover"]
PHOTO_SIDEBAR = ["cover", "title", "description", "keywords", "rating", "datetaken", "author", "copyright",
                 "make", "model", "lens", "exposure", "aperture", "iso", "focal", "gpslat", "gpslon", "gpsalt"]


def default_sidebar() -> list[str]:
    return list(PHOTO_SIDEBAR if _current == PHOTO else AUDIO_SIDEBAR)


def accepts(path: str, kind: str | None = None) -> bool:
    kind = kind or _current
    return ph.is_photo(path) if kind == PHOTO else tg.is_audio(path)


def setting(name: str) -> str:
    """Einstellung je Art: „meta_layout“ bzw. „meta_photo_layout“."""
    return name.replace("meta_", "meta_photo_", 1) if _current == PHOTO else name


# Konverter, die es nur bei Musik gibt (L-441)
def tools() -> tuple[str, ...]:
    from . import convert as cv

    if _current == PHOTO:
        return tuple(k for k in cv.TOOLS if k not in cv.AUDIO_ONLY)
    return tuple(k for k in cv.TOOLS if k not in cv.PHOTO_ONLY)
