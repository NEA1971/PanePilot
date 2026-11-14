"""Welche Dateien der Meta-Wizard gerade zeigt (v1.4): Musik, Fotos oder Videos (v1.5).

Der Meta-Wizard zeigt immer eine Art von Dateien. Felder, Spalten, Seitenleiste und Konverter hängen
davon ab; die Einstellungen werden je Art getrennt gemerkt.
"""

from __future__ import annotations

from . import phototags as ph
from . import tags as tg
from . import videotags as vt

AUDIO, PHOTO, VIDEO = "audio", "photo", "video"
KINDS = (AUDIO, PHOTO, VIDEO)

_current = AUDIO


def current() -> str:
    return _current


def set_current(kind: str) -> None:
    global _current
    _current = kind if kind in KINDS else AUDIO


def is_photo_mode() -> bool:
    return _current == PHOTO


def is_video_mode() -> bool:
    return _current == VIDEO


def is_audio_mode() -> bool:
    return _current == AUDIO


def _pick(audio, photo, video):
    return {PHOTO: photo, VIDEO: video}.get(_current, audio)


def fields() -> tuple[str, ...]:
    return _pick(tg.FIELDS, ph.FIELDS, vt.FIELDS)


def standard_fields() -> tuple[str, ...]:
    return _pick(tg.STANDARD_FIELDS, ph.STANDARD_FIELDS, vt.STANDARD_FIELDS)


AUDIO_INFO = ("i:length", "i:bitrate", "i:samplerate", "i:codec", "i:size", "i:mtime")
PHOTO_INFO = ("i:dims", "i:camera", "i:format", "i:size", "i:mtime")
VIDEO_INFO = ("i:duration", "i:resolution", "i:fps", "i:vcodec", "i:acodec", "i:bitrate", "i:format", "i:size",
              "i:mtime")


def info_columns() -> tuple[str, ...]:
    return _pick(AUDIO_INFO, PHOTO_INFO, VIDEO_INFO)


AUDIO_COLUMNS = ["filename", "title", "artist", "album", "albumartist", "track", "disc", "year", "genre",
                 "comment", "path"]
PHOTO_COLUMNS = ["filename", "datetaken", "i:camera", "i:dims", "title", "rating", "keywords", "path"]
VIDEO_COLUMNS = ["filename", "datetaken", "i:duration", "i:resolution", "title", "path"]


def default_columns() -> list[str]:
    return list(_pick(AUDIO_COLUMNS, PHOTO_COLUMNS, VIDEO_COLUMNS))


AUDIO_SIDEBAR = ["title", "artist", "album", "year", "track", "genre", "comment", "albumartist", "composer",
                 "disc", "cover"]
PHOTO_SIDEBAR = ["cover", "title", "description", "keywords", "rating", "datetaken", "author", "copyright",
                 "make", "model", "lens", "exposure", "aperture", "iso", "focal", "gpslat", "gpslon", "gpsalt"]
VIDEO_SIDEBAR = ["cover", "title", "description", "author", "genre", "year", "copyright", "datetaken", "gpslat",
                 "gpslon", "gpsalt"]


def default_sidebar() -> list[str]:
    return list(_pick(AUDIO_SIDEBAR, PHOTO_SIDEBAR, VIDEO_SIDEBAR))


def kind_of(path: str) -> str | None:
    if tg.is_audio(path):
        return AUDIO
    if ph.is_photo(path):
        return PHOTO
    if vt.is_video(path):
        return VIDEO
    return None


def accepts(path: str, kind: str | None = None) -> bool:
    return kind_of(path) == (kind or _current)


def setting(name: str) -> str:
    """Einstellung je Art: „meta_layout“, „meta_photo_layout“ bzw. „meta_video_layout“."""
    if _current == AUDIO:
        return name
    return name.replace("meta_", f"meta_{_current}_", 1)


# Konverter, die es nur bei Musik gibt (L-441)
def tools() -> tuple[str, ...]:
    from . import convert as cv

    if _current in (PHOTO, VIDEO):
        return tuple(k for k in cv.TOOLS if k not in cv.AUDIO_ONLY)
    return tuple(k for k in cv.TOOLS if k not in cv.PHOTO_ONLY)
