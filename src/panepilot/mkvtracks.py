"""Ton-, Untertitel- und Videospuren von MKV-Dateien bearbeiten (v1.11, L-1100 ff.).

Gelesen wird mit „mkvmerge -J“ (liefert die Spurnummern, die mkvpropedit braucht), geschrieben mit
„mkvpropedit … --edit track:@N --set …“ direkt in der Datei.
"""

from __future__ import annotations

from . import tools as _tools
import json
from dataclasses import dataclass, field

from .i18n import t

VIDEO, AUDIO, SUBS = "video", "audio", "subtitles"
KINDS = (VIDEO, AUDIO, SUBS)

# Auswahlliste der Sprachen (L-1102): dreibuchstabige Codes wie in den meisten MKV-Dateien
LANGUAGES = ("ger", "eng", "fre", "spa", "ita", "dut", "por", "pol", "rus", "tur", "dan", "swe", "nor", "fin",
             "cze", "hun", "gre", "jpn", "chi", "kor", "ceb", "tgl", "und")


@dataclass
class MkvTrack:
    number: int  # Spurnummer in der Datei (für „track:@N“)
    kind: str  # video, audio, subtitles
    index: int  # Nummer innerhalb der Art, ab 1 („Tonspur 1“)
    codec: str = ""
    lang: str = "und"
    name: str = ""
    default: bool = False
    forced: bool = False
    channels: int = 0
    stream: int = 0  # Stream-Nummer für ffmpeg (MP4, v1.12)


@dataclass
class TrackChange:
    """Gewünschte Änderung einer Spur; None = unverändert."""
    lang: str | None = None
    name: str | None = None
    default: bool | None = None
    forced: bool | None = None

    def empty(self) -> bool:
        return self.lang is None and self.name is None and self.default is None and self.forced is None


@dataclass
class FileTracks:
    path: str
    tracks: list[MkvTrack] = field(default_factory=list)
    error: str = ""
    fmt: str = "mkv"  # „mkv“ oder „mp4“ (v1.12)
    duration: float = 0.0

    def has_effect(self, track: MkvTrack, change: "TrackChange") -> bool:
        if self.fmt == "mp4":
            from .mp4tracks import has_effect

            return has_effect(track, change)
        return bool(edit_args(track, change))

    def find(self, kind: str, index: int) -> MkvTrack | None:
        return next((tr for tr in self.tracks if tr.kind == kind and tr.index == index), None)


def mkvmerge() -> str | None:
    return _tools.find("mkvmerge")


def available() -> bool:
    from .videotags import mkvpropedit

    return mkvmerge() is not None and mkvpropedit() is not None


def parse_identify(data: dict) -> list[MkvTrack]:
    tracks: list[MkvTrack] = []
    counts = {k: 0 for k in KINDS}
    for tr in data.get("tracks") or []:
        kind = tr.get("type")
        if kind not in KINDS:
            continue
        p = tr.get("properties") or {}
        counts[kind] += 1
        number = p.get("number") or (int(tr.get("id", 0)) + 1)
        try:
            channels = int(p.get("audio_channels") or 0)
        except (TypeError, ValueError):
            channels = 0
        tracks.append(MkvTrack(int(number), kind, counts[kind], tr.get("codec") or "",
                               (p.get("language") or "und").strip() or "und", (p.get("track_name") or "").strip(),
                               bool(p.get("default_track")), bool(p.get("forced_track")), channels,
                               int(tr.get("id", int(number) - 1))))
    return tracks


def read(path: str) -> FileTracks:
    from .videotags import _fail, _run

    tool = mkvmerge()
    if tool is None:
        return FileTracks(path, error="mkvmerge")
    try:
        proc = _run([tool, "-J", path], timeout=120)
    except (OSError, ValueError) as exc:
        return FileTracks(path, error=str(exc))
    if proc.returncode not in (0, 1):
        return FileTracks(path, error=str(_fail(proc, "mkvmerge")))
    try:
        data = json.loads(proc.stdout or "{}")
    except ValueError as exc:
        return FileTracks(path, error=str(exc))
    return FileTracks(path, parse_identify(data))


def edit_args(track: MkvTrack, change: TrackChange) -> list[str]:
    args: list[str] = []
    if change.lang is not None and track.kind != VIDEO and change.lang != track.lang:
        args += ["--set", f"language={change.lang or 'und'}"]
    if change.name is not None and change.name != track.name:
        args += ["--set", f"name={change.name}"] if change.name else ["--delete", "name"]
    if change.default is not None and track.kind != VIDEO and change.default != track.default:
        args += ["--set", f"flag-default={1 if change.default else 0}"]
    if change.forced is not None and track.kind != VIDEO and change.forced != track.forced:
        args += ["--set", f"flag-forced={1 if change.forced else 0}"]
    return ["--edit", f"track:@{track.number}", *args] if args else []


def write(path: str, edits: list[tuple[MkvTrack, TrackChange]]) -> None:
    """Alle Änderungen einer Datei in einem Aufruf (Spureigenschaften verschieben nichts)."""
    from .videotags import _fail, _run, mkvpropedit

    args: list[str] = []
    for track, change in edits:
        args += edit_args(track, change)
    if not args:
        return
    tool = mkvpropedit()
    if tool is None:
        raise OSError("mkvpropedit")
    proc = _run([tool, path, *args], timeout=300)
    if proc.returncode not in (0, 1):
        raise _fail(proc, "mkvpropedit")


# --- Namen vorschlagen (L-1103) ----------------------------------------------------------------
_CODEC_SHORT = (("E-AC-3", "EAC3"), ("AC-3", "AC3"), ("DTS-HD", "DTS-HD"), ("DTS", "DTS"), ("TrueHD", "TrueHD"),
                ("AAC", "AAC"), ("FLAC", "FLAC"), ("Opus", "Opus"), ("Vorbis", "Vorbis"), ("MP3", "MP3"),
                ("MPEG-1 Layer 3", "MP3"), ("MP2", "MP2"), ("PCM", "PCM"), ("SubRip", "SRT"), ("SRT", "SRT"),
                ("PGS", "PGS"), ("HDMV", "PGS"), ("VobSub", "VobSub"), ("SubStationAlpha", "ASS"), ("ASS", "ASS"),
                ("SSA", "SSA"), ("WebVTT", "WebVTT"))


def short_codec(codec: str) -> str:
    for needle, short in _CODEC_SHORT:
        if needle.lower() in (codec or "").lower():
            return short
    return (codec or "").split("/")[0].strip()


def _channels(n: int) -> str:
    return {1: t("track.mono"), 2: t("track.stereo"), 3: "2.1", 6: "5.1", 7: "6.1", 8: "7.1"}.get(n, "")


def suggest_name(kind: str, lang: str, codec: str, channels: int = 0, forced: bool = False) -> str:
    """„Deutsch AC3 5.1“, „Englisch SRT (forced)“."""
    from .tracks import language_name

    parts = []
    lang_name = language_name(lang) if lang and lang != "und" else ""
    if lang_name:
        parts.append(lang_name)
    if kind != VIDEO:
        short = short_codec(codec)
        if short:
            parts.append(short)
    if kind == AUDIO and channels:
        ch = _channels(channels)
        if ch:
            parts.append(ch)
    name = " ".join(parts)
    if kind == SUBS and forced:
        name = f"{name} (forced)".strip()
    return name


def kind_label(kind: str, index: int) -> str:
    return t({VIDEO: "tracks.video_n", AUDIO: "tracks.audio_n", SUBS: "tracks.subs_n"}[kind], n=index)
