"""Spuren von MP4-Dateien bearbeiten (v1.12, L-1200 ff.).

- Sprache: direkt in der Datei (Feld „language“ im mdhd-Kasten jeder Spur, feste Länge) – in Sekunden.
- Spurname und „Standard“: Neupacken mit ffmpeg ohne Neukodieren in eine Hilfsdatei; danach werden alle Tags
  und das Cover aus der alten Datei übernommen und die alte Datei erst nach erfolgreicher Prüfung ersetzt.
"""

from __future__ import annotations

import os
import struct
import subprocess
import threading

from . import mkvtracks as mt

# MP4 verlangt ISO 639-2/T (L-1202)
B_TO_T = {"ger": "deu", "fre": "fra", "dut": "nld", "cze": "ces", "chi": "zho", "gre": "ell", "ice": "isl",
          "per": "fas", "rum": "ron", "slo": "slk", "alb": "sqi", "arm": "hye", "baq": "eus", "bur": "mya",
          "geo": "kat", "mac": "mkd", "mao": "mri", "may": "msa", "tib": "bod", "wel": "cym"}


def to_t(code: str) -> str:
    code = (code or "und").strip().lower()
    return B_TO_T.get(code, code)


# --- Kästen (Boxen) der MP4-Datei ----------------------------------------------------------------------
def _boxes(fh, start: int, end: int):
    """(Typ, Anfang, Anfang der Nutzdaten, Ende) aller Kästen zwischen start und end."""
    pos = start
    while pos + 8 <= end:
        fh.seek(pos)
        head = fh.read(8)
        if len(head) < 8:
            return
        size, kind = struct.unpack(">I4s", head)
        body = pos + 8
        if size == 1:
            size = struct.unpack(">Q", fh.read(8))[0]
            body = pos + 16
        elif size == 0:
            size = end - pos
        if size < 8 or pos + size > end:
            return
        yield kind.decode("latin-1"), pos, body, pos + size
        pos += size


def _child(fh, start: int, end: int, kind: str):
    return next((b for b in _boxes(fh, start, end) if b[0] == kind), None)


_HANDLERS = {"vide": mt.VIDEO, "soun": mt.AUDIO, "sbtl": mt.SUBS, "text": mt.SUBS, "subt": mt.SUBS}


def language_fields(path: str) -> dict[int, tuple[int, str, str]]:
    """{Track-ID: (Dateiposition der Sprache, Code, Art)} für alle Spuren."""
    out: dict[int, tuple[int, str, str]] = {}
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        moov = _child(fh, 0, size, "moov")
        if moov is None:
            raise OSError("moov missing")
        for kind, _s, body, end in _boxes(fh, moov[2], moov[3]):
            if kind != "trak":
                continue
            tkhd = _child(fh, body, end, "tkhd")
            mdia = _child(fh, body, end, "mdia")
            if tkhd is None or mdia is None:
                continue
            mdhd = _child(fh, mdia[2], mdia[3], "mdhd")
            if mdhd is None:
                continue
            fh.seek(tkhd[2])
            version = fh.read(1)[0]
            fh.seek(tkhd[2] + (20 if version == 1 else 12))
            track_id = struct.unpack(">I", fh.read(4))[0]
            fh.seek(mdhd[2])
            version = fh.read(1)[0]
            lang_pos = mdhd[2] + (32 if version == 1 else 20)
            fh.seek(lang_pos)
            packed = struct.unpack(">H", fh.read(2))[0]
            code = "".join(chr(((packed >> s) & 0x1F) + 0x60) for s in (10, 5, 0))
            kind = ""
            hdlr = _child(fh, mdia[2], mdia[3], "hdlr")
            if hdlr is not None:
                fh.seek(hdlr[2] + 8)
                kind = _HANDLERS.get(fh.read(4).decode("latin-1"), "")
            out[track_id] = (lang_pos, code if code.isalpha() else "und", kind)
    return out


def _pack(code: str) -> bytes:
    code = to_t(code)
    if len(code) != 3 or not code.isascii() or not code.isalpha():
        raise ValueError(f"language code: {code}")
    value = 0
    for ch in code.lower():
        value = (value << 5) | (ord(ch) - 0x60)
    return struct.pack(">H", value)


def set_languages(path: str, langs: dict[int, str]) -> None:
    """{Track-ID: Code} direkt in die Datei schreiben (L-1201)."""
    fields = language_fields(path)
    with open(path, "r+b") as fh:
        for track_id, code in langs.items():
            if track_id not in fields:
                raise OSError(f"track {track_id} missing")
            fh.seek(fields[track_id][0])
            fh.write(_pack(code))


# --- Lesen -------------------------------------------------------------------------------------------------
def parse_probe(info: dict) -> list[mt.MkvTrack]:
    """Spuren aus ffprobe; number = Track-ID der MP4-Datei (Cover-Bilder zählen nicht)."""
    tracks: list[mt.MkvTrack] = []
    counts = {k: 0 for k in mt.KINDS}
    for s in info.get("streams") or []:
        kind = {"video": mt.VIDEO, "audio": mt.AUDIO, "subtitle": mt.SUBS}.get(s.get("codec_type"))
        disp = s.get("disposition") or {}
        if kind is None or disp.get("attached_pic"):
            continue
        tags = {k.lower(): v for k, v in (s.get("tags") or {}).items()}
        try:
            track_id = int(str(s.get("id") or "0"), 0) or int(s.get("index", 0)) + 1
        except ValueError:
            track_id = int(s.get("index", 0)) + 1
        counts[kind] += 1
        name = (tags.get("title") or "").strip()
        handler = (tags.get("handler_name") or "").strip()
        if not name and handler and not _generic_handler(handler):
            name = handler
        tracks.append(mt.MkvTrack(track_id, kind, counts[kind], mt_codec(s),
                                  (tags.get("language") or "und").strip(), name, bool(disp.get("default")),
                                  bool(disp.get("forced")), int(s.get("channels") or 0), int(s.get("index", 0))))
    return tracks


_GENERIC = ("soundhandler", "videohandler", "subtitlehandler", "core media", "iso media", "apple", "mainconcept",
            "l-smash", "gpac", "bento4", "dataHandler".lower())


def _generic_handler(name: str) -> bool:
    low = name.casefold()
    return any(g in low for g in _GENERIC) or low in ("sound", "video", "text", "subtitle")


def mt_codec(stream: dict) -> str:
    from .videotags import codec_name

    return codec_name(stream.get("codec_name") or "")


def read(path: str) -> mt.FileTracks:
    from .videotags import probe

    info = probe(path)
    if info is None:
        # ohne ffmpeg: nur Sprachen aus der Datei (L-1207)
        try:
            fields = language_fields(path)
        except (OSError, ValueError, struct.error) as exc:
            return mt.FileTracks(path, error=str(exc), fmt="mp4")
        tracks = []
        counts = {k: 0 for k in mt.KINDS}
        for n, (tid, (_pos, code, kind)) in enumerate(sorted(fields.items())):
            if not kind:
                continue
            counts[kind] += 1
            tracks.append(mt.MkvTrack(tid, kind, counts[kind], "", code, stream=n))
        return mt.FileTracks(path, tracks, fmt="mp4")
    tracks = parse_probe(info)
    try:
        dur = float((info.get("format") or {}).get("duration") or 0)
    except ValueError:
        dur = 0.0
    return mt.FileTracks(path, tracks, fmt="mp4", duration=dur)


# --- Planen ------------------------------------------------------------------------------------------------
def needs_remux(track: mt.MkvTrack, change: mt.TrackChange) -> bool:
    return ((change.name is not None and change.name != track.name) or
            (change.default is not None and track.kind != mt.VIDEO and change.default != track.default))


def plan(edits: list[tuple[mt.MkvTrack, mt.TrackChange]]) -> tuple[dict[int, str], bool]:
    """(Sprachen je Track-ID, Neupacken nötig?)"""
    langs = {tr.number: to_t(ch.lang) for tr, ch in edits
             if ch.lang is not None and tr.kind != mt.VIDEO and to_t(ch.lang) != to_t(tr.lang)}
    return langs, any(needs_remux(tr, ch) for tr, ch in edits)


def has_effect(track: mt.MkvTrack, change: mt.TrackChange) -> bool:
    langs, remux = plan([(track, change)])
    return bool(langs) or remux


# --- Neupacken (L-1203) ---------------------------------------------------------------------------------
class Cancelled(Exception):
    pass


def remux_args(ffmpeg: str, src: str, dst: str, files: mt.FileTracks,
               edits: list[tuple[mt.MkvTrack, mt.TrackChange]]) -> list[str]:
    by_number = {tr.number: ch for tr, ch in edits}
    args = [ffmpeg, "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", src]
    for tr in files.tracks:
        args += ["-map", f"0:{tr.stream}"]
    args += ["-c", "copy", "-map_metadata", "0", "-map_chapters", "0"]
    for out_index, tr in enumerate(files.tracks):
        ch = by_number.get(tr.number) or mt.TrackChange()
        lang = to_t(ch.lang) if ch.lang is not None and tr.kind != mt.VIDEO else to_t(tr.lang)
        args += [f"-metadata:s:{out_index}", f"language={lang}"]
        name = ch.name if ch.name is not None else tr.name
        args += [f"-metadata:s:{out_index}", f"title={name}", f"-metadata:s:{out_index}", f"handler_name={name}"]
        if tr.kind != mt.VIDEO:
            default = ch.default if ch.default is not None else tr.default
            args += [f"-disposition:{out_index}", "default" if default else "0"]
    fmt = "mov" if src.lower().endswith(".mov") else "mp4"
    args += ["-f", fmt, "-progress", "pipe:1", "-nostats", dst]
    return args


def remux(files: mt.FileTracks, edits, progress=None, cancel: threading.Event | None = None) -> None:
    """Neu packen, prüfen, Tags und Cover übernehmen, dann ersetzen."""
    from . import tags as tg
    from .videotags import _env, ffmpeg, probe

    tool = ffmpeg()
    if tool is None:
        raise OSError("ffmpeg")
    path = files.path
    folder = os.path.dirname(os.path.abspath(path))
    base, ext = os.path.splitext(os.path.basename(path))
    tmp = os.path.join(folder, f".{base}.panepilot-tmp{ext}")
    snap = tg.mutagen_snapshot(path, True)  # vor dem Neupacken: Tags, eigene Felder, Cover
    proc = subprocess.Popen(remux_args(tool, path, tmp, files, edits), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=_env())
    try:
        total = max(files.duration, 0.001)
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise Cancelled()
            key, _sep, value = line.strip().partition("=")
            if key == "out_time_us" and progress is not None and value.isdigit():
                progress(min(int(value) / 1e6 / total, 1.0))
        proc.wait()
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        if proc.returncode != 0:
            err = (proc.stderr.read() or "ffmpeg").strip().splitlines()
            raise OSError(err[-1] if err else "ffmpeg")
        new = probe(tmp)
        old_n = len(files.tracks)
        if new is not None:  # Prüfung: gleiche Spuranzahl und Länge (L-1203)
            tracks = parse_probe(new)
            dur = float((new.get("format") or {}).get("duration") or 0)
            if len(tracks) != old_n or (files.duration and abs(dur - files.duration) > 2.0):
                raise OSError("check failed")
        tg.mutagen_restore(tmp, snap)
        try:
            import shutil

            shutil.copymode(path, tmp)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        if proc.poll() is None:
            proc.kill()
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    finally:
        for stream in (proc.stdout, proc.stderr):
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass


def write(files: mt.FileTracks, edits, progress=None, cancel=None) -> None:
    """Sprache allein direkt in der Datei; Name/„Standard“ über Neupacken (mit den Sprachen zusammen)."""
    langs, needs = plan(edits)
    if needs:
        remux(files, edits, progress, cancel)
    elif langs:
        set_languages(files.path, langs)
