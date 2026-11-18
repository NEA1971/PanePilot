"""Neue Video-Dateien ohne Neukodieren (v1.13, L-1300 ff.).

- Spuren entfernen: MKV mit mkvmerge, MP4 mit ffmpeg → neue Datei „…-Kopie“
- Untertitel exportieren: .srt / .ass / .sup / .idx+.sub neben dem Video
- Formatwechsel: MP4/M4V/MOV/AVI → MKV (mkvmerge), MKV → MP4 (ffmpeg); Tags und Cover werden übertragen

Das Original bleibt immer unverändert (L-1300).
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
from dataclasses import dataclass

from . import mkvtracks as mt
from .i18n import t


class Cancelled(Exception):
    pass


# --- Namen (L-1301, L-1323) ------------------------------------------------------------------------
def copy_name(path: str, ext: str | None = None) -> str:
    """„Film.mkv“ → „Film-Kopie.mkv“ (bzw. mit neuer Endung erst „Film.mkv“), nie vorhanden."""
    folder, name = os.path.split(path)
    stem, old_ext = os.path.splitext(name)
    ext = ext or old_ext
    if ext.lower() != old_ext.lower():
        first = os.path.join(folder, stem + ext)
        if not os.path.lexists(first):
            return first
    word = t("file.duplicate_suffix")
    n = 1
    while True:
        cand = os.path.join(folder, f"{stem}-{word}{ext}" if n == 1 else f"{stem}-{word}-{n}{ext}")
        if not os.path.lexists(cand):
            return cand
        n += 1


def subtitle_kind(codec: str) -> str:
    """text, ass, pgs oder vobsub."""
    low = (codec or "").lower()
    if "pgs" in low or "hdmv" in low:
        return "pgs"
    if "vobsub" in low or "dvd_sub" in low or "dvdsub" in low:
        return "vobsub"
    if "ass" in low or "ssa" in low or "substation" in low:
        return "ass"
    return "text"


_EXT = {"text": ".srt", "ass": ".ass", "pgs": ".sup", "vobsub": ".idx"}


def subtitle_name(video: str, track: mt.MkvTrack, taken: set[str]) -> str:
    """„Film (2001).ger.forced.srt“, bei Gleichheit „Film (2001).ger.2.srt“ (L-1323)."""
    stem = os.path.splitext(video)[0]
    lang = (track.lang or "und").strip() or "und"
    tag = f".{lang}" + (".forced" if track.forced else "")
    ext = _EXT[subtitle_kind(track.codec)]
    n = 1
    while True:
        cand = f"{stem}{tag}{'' if n == 1 else f'.{n}'}{ext}"
        partner = cand[:-4] + ".sub" if ext == ".idx" else None
        if cand not in taken and not os.path.lexists(cand) and not (partner and os.path.lexists(partner)):
            taken.add(cand)
            return cand
        n += 1


# --- Hilfen -----------------------------------------------------------------------------------------
def _tool(name: str) -> str:
    import shutil

    from . import videotags as vt

    path = {"ffmpeg": vt.ffmpeg, "mkvmerge": mt.mkvmerge}.get(name, lambda: shutil.which(name))()
    if path is None:
        raise OSError(t("remux.missing_tool", tool=name))
    return path


def _run_progress(args: list[str], parse, progress=None, cancel: threading.Event | None = None) -> None:
    """Programm ausführen, Fortschritt (0…1) aus seiner Ausgabe lesen, bei Abbruch beenden."""
    from .videotags import _env

    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=_env(),
                            errors="replace")
    tail: list[str] = []
    try:
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise Cancelled()
            line = line.strip()
            frac = parse(line)
            if frac is None:
                if line:
                    tail = (tail + [re.sub(r"^#GUI#(error|warning)\s*", "", line)])[-8:]
            elif frac >= 0 and progress is not None:
                progress(min(frac, 1.0))
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if proc.returncode not in (0, 1) or (proc.returncode == 1 and args and "mkvmerge" not in
                                          os.path.basename(args[0])):
        raise OSError(tail[-1] if tail else os.path.basename(args[0]))


def _mkvmerge_progress(line: str):
    """Fortschritt 0…1, -1 = ohne Bedeutung, None = Meldung (für Fehlertexte)."""
    m = re.match(r"#GUI#progress\s+(\d+)%", line)
    if m:
        return int(m.group(1)) / 100
    if line.startswith(("#GUI#error", "#GUI#warning")) or not line.startswith("#GUI#"):
        return None
    return -1


def _ffmpeg_progress(total: float):
    def parse(line: str):
        key, _sep, value = line.partition("=")
        if key == "out_time_us" and value.strip().isdigit():
            return int(value) / 1e6 / max(total, 0.001)
        if _sep and re.fullmatch(r"[a-z_0-9]+", key):
            return -1  # übrige Zeilen von „-progress“
        return None
    return parse


def _tmp_for(final: str) -> str:
    folder, name = os.path.split(final)
    stem, ext = os.path.splitext(name)
    return os.path.join(folder, f".{stem}.panepilot-tmp{ext}")


def _finish(tmp: str, final: str, src: str) -> None:
    import shutil

    try:
        shutil.copymode(src, tmp)
    except OSError:
        pass
    os.replace(tmp, final)


def _discard(tmp: str) -> None:
    try:
        os.remove(tmp)
    except OSError:
        pass


def video_length(info: dict | None) -> float:
    """Länge der Videospur (nicht der ganzen Datei: eine längere Tonspur verlängert die Datei)."""
    if not info:
        return 0.0
    for st in info.get("streams") or []:
        if st.get("codec_type") != "video" or (st.get("disposition") or {}).get("attached_pic"):
            continue
        try:
            if st.get("duration"):
                return float(st["duration"])
        except ValueError:
            pass
        tags = {k.upper(): v for k, v in (st.get("tags") or {}).items()}
        m = re.match(r"^(\d+):(\d\d):(\d\d(?:\.\d+)?)$", str(tags.get("DURATION") or ""))
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        break
    try:
        return float((info.get("format") or {}).get("duration") or 0)
    except ValueError:
        return 0.0


def _check(path: str, expected_tracks: int, reference: float) -> None:
    """Neue Datei prüfen: Spuranzahl und Länge der Videospur (L-1303)."""
    from . import mp4tracks as m4
    from .videotags import probe

    info = probe(path)
    if info is None:
        return  # ohne ffprobe keine Prüfung möglich; das Programm hat ohne Fehler geendet
    tracks = m4.parse_probe(info)
    dur = video_length(info)
    tolerance = max(2.0, reference * 0.005)
    if len(tracks) != expected_tracks or (reference and dur and abs(dur - reference) > tolerance):
        raise OSError(t("remux.check_failed") + f" ({len(tracks)}/{expected_tracks}, {dur:.1f}s/{reference:.1f}s)")


def _reference(path: str) -> float:
    from .videotags import probe

    return video_length(probe(path))


def _duration(path: str) -> float:
    from .videotags import probe

    info = probe(path) or {}
    try:
        return float((info.get("format") or {}).get("duration") or 0)
    except ValueError:
        return 0.0


# --- Untertitel exportieren (L-1320 ff.) -------------------------------------------------------------
def export_subtitles(files: mt.FileTracks, tracks: list[mt.MkvTrack]) -> list[str]:
    """Speichert die Untertitel neben dem Video; liefert die angelegten Dateien."""
    from .videotags import _fail, _run

    out: list[str] = []
    taken: set[str] = set()
    extract: list[str] = []
    for tr in tracks:
        if tr.kind != mt.SUBS:
            continue
        kind = subtitle_kind(tr.codec)
        target = subtitle_name(files.path, tr, taken)
        if kind in ("pgs", "vobsub"):
            if files.fmt != "mkv":
                raise OSError(t("remux.image_subs_mp4"))
            extract.append(f"{tr.stream}:{target}")
        else:
            codec = "copy" if kind == "ass" else "srt"
            proc = _run([_tool("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", files.path,
                         "-map", f"0:{tr.stream}", "-c:s", codec, target], timeout=600)
            if proc.returncode != 0:
                _discard(target)
                raise _fail(proc, "ffmpeg")
        out.append(target)
    if extract:
        import shutil

        tool = shutil.which("mkvextract")
        if tool is None:
            raise OSError(t("remux.missing_tool", tool="mkvextract"))
        proc = _run([tool, files.path, "tracks", *extract], timeout=1800)
        if proc.returncode not in (0, 1):
            raise _fail(proc, "mkvextract")
    return out


# --- Spuren entfernen (L-1310 ff.) -------------------------------------------------------------------
def plan_removal(files: mt.FileTracks, remove: list[mt.MkvTrack],
                 edits: list[tuple[mt.MkvTrack, mt.TrackChange]]) -> tuple[list[mt.MkvTrack], dict]:
    """Behaltene Spuren und die gewünschten Werte je Spur (Sprache, Name, Standard, Erzwungen)."""
    gone = {id(tr) for tr in remove}
    keep = [tr for tr in files.tracks if id(tr) not in gone]
    by = {id(tr): ch for tr, ch in edits}
    values = {}
    for tr in keep:
        ch = by.get(id(tr)) or mt.TrackChange()
        values[id(tr)] = {
            "lang": ch.lang if ch.lang is not None else tr.lang,
            "name": ch.name if ch.name is not None else tr.name,
            "default": ch.default if ch.default is not None else tr.default,
            "forced": ch.forced if ch.forced is not None else tr.forced,
        }
    for kind in (mt.AUDIO, mt.SUBS):  # L-1312: Standard geht auf die nächste verbliebene Spur über
        removed_default = any(tr.kind == kind and tr.default for tr in remove)
        kept = [tr for tr in keep if tr.kind == kind]
        if removed_default and kept and not any(values[id(tr)]["default"] for tr in kept):
            values[id(kept[0])]["default"] = True
    return keep, values


# --- Untertiteldateien hinzufügen (v1.14, L-1410 ff.) ------------------------------------------------------------
SUB_EXTENSIONS = (".srt", ".ass", ".ssa", ".sup", ".idx", ".vtt")
_SUB_FLAGS = {"forced": "forced", "sdh": "sdh", "hi": "sdh", "cc": "sdh", "default": "default"}


@dataclass
class SubAdd:
    """Eine Untertiteldatei, die als neue Spur ins Video kommt."""
    path: str
    lang: str = "und"
    name: str = ""
    forced: bool = False
    default: bool = False


def is_image_sub(path: str) -> bool:
    return path.lower().endswith((".sup", ".idx"))


def parse_sub_name(video: str, sub: str) -> SubAdd:
    """„Film.ger.forced.srt“ zu „Film.mkv“ → Sprache ger, erzwungen (Jellyfin-Stil)."""
    stem = os.path.splitext(os.path.basename(video))[0]
    base = os.path.splitext(os.path.basename(sub))[0]
    rest = base[len(stem):] if base.startswith(stem) else ""
    parts = [x for x in rest.split(".") if x]
    add = SubAdd(sub)
    flags = set()
    for part in parts:
        low = part.lower()
        if low in _SUB_FLAGS:
            flags.add(_SUB_FLAGS[low])
        elif re.fullmatch(r"[a-z]{2,3}", low) and add.lang == "und":
            add.lang = _lang3(low)
    add.forced = "forced" in flags
    add.default = "default" in flags
    return add


def _lang3(code: str) -> str:
    """2-Buchstaben-Codes in die in MKV übliche Form (de → ger)."""
    from . import opensubs

    return opensubs.to_mkv_lang(code)


def subtitle_candidates(video: str) -> list[str]:
    """Untertiteldateien im selben Ordner, deren Name mit dem Videonamen beginnt (L-1410)."""
    folder = os.path.dirname(os.path.abspath(video))
    stem = os.path.splitext(os.path.basename(video))[0]
    out = []
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    for name in names:
        low = name.lower()
        if low.endswith(SUB_EXTENSIONS) and name.startswith(stem + "."):
            out.append(os.path.join(folder, name))
    return out


def _sub_charset(path: str) -> str:
    """utf-8, sonst cp1252 (ältere deutsche SRT-Dateien)."""
    if is_image_sub(path):
        return ""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError:
        return ""
    if data.startswith(b"\xef\xbb\xbf"):
        return "UTF-8"
    try:
        data.decode("utf-8")
        return "UTF-8"
    except UnicodeDecodeError:
        return "CP1252"


def add_problem(files: mt.FileTracks, adds: list[SubAdd]) -> str:
    if files.fmt != "mkv" and any(is_image_sub(a.path) for a in adds):
        return t("remux.image_subs_add")  # L-1412
    return ""


def remove_tracks(files: mt.FileTracks, remove: list[mt.MkvTrack], edits, progress=None, cancel=None,
                  replace: bool = False, add: list[SubAdd] | None = None) -> str:
    """Neue Datei ohne die Spuren (und mit neuen Untertiteln, v1.14); liefert ihren Pfad.

    Das Original bleibt (L-1300), außer bei replace."""
    add = list(add or [])
    problem = add_problem(files, add)
    if problem:
        raise OSError(problem)
    if any(tr.kind == mt.VIDEO for tr in remove):
        raise OSError(t("remux.no_video_removal"))
    keep, values = plan_removal(files, remove, edits)
    if not any(tr.kind == mt.AUDIO for tr in keep) and any(tr.kind == mt.AUDIO for tr in files.tracks):
        raise OSError(t("remux.last_audio"))  # L-1311
    final = files.path if replace else copy_name(files.path)  # v1.13.2: auf Wunsch Original ersetzen
    tmp = _tmp_for(final)
    duration = files.duration or _duration(files.path)
    try:
        if files.fmt == "mkv":
            _remove_mkv(files, keep, values, tmp, progress, cancel, add)
        else:
            _remove_mp4(files, keep, values, tmp, duration, progress, cancel, add)
        _check(tmp, len(keep) + len(add), _reference(files.path))
        _finish(tmp, final, files.path)
    except BaseException:
        _discard(tmp)
        raise
    return final


def _ids(tracks, kind) -> str:
    return ",".join(str(tr.stream) for tr in tracks if tr.kind == kind)


def _remove_mkv(files, keep, values, tmp, progress, cancel, add=()) -> None:
    args = [_tool("mkvmerge"), "--gui-mode", "-o", tmp]
    for kind, opt, none in ((mt.AUDIO, "--audio-tracks", "--no-audio"),
                            (mt.SUBS, "--subtitle-tracks", "--no-subtitles")):
        ids = _ids(keep, kind)
        if ids:
            args += [opt, ids]
        elif any(tr.kind == kind for tr in files.tracks):
            args.append(none)
    for tr in keep:
        v = values[id(tr)]
        if tr.kind != mt.VIDEO:
            args += ["--language", f"{tr.stream}:{v['lang'] or 'und'}",
                     "--default-track-flag", f"{tr.stream}:{1 if v['default'] else 0}",
                     "--forced-display-flag", f"{tr.stream}:{1 if v['forced'] else 0}"]
        args += ["--track-name", f"{tr.stream}:{v['name']}"]
    args.append(files.path)
    for a in add:
        args += ["--language", f"0:{a.lang or 'und'}", "--track-name", f"0:{a.name}",
                 "--default-track-flag", f"0:{1 if a.default else 0}",
                 "--forced-display-flag", f"0:{1 if a.forced else 0}"]
        charset = _sub_charset(a.path)
        if charset:
            args += ["--sub-charset", f"0:{charset}"]
        args.append(a.path)
    _run_progress(args, _mkvmerge_progress, progress, cancel)


def _remove_mp4(files, keep, values, tmp, duration, progress, cancel, add=()) -> None:
    from . import mp4tracks as m4
    from . import tags as tg

    snap = tg.mutagen_snapshot(files.path, True)
    args = [_tool("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", files.path]
    for a in add:
        charset = _sub_charset(a.path)
        if charset and charset != "UTF-8":
            args += ["-sub_charenc", charset]
        args += ["-i", a.path]
    for tr in keep:
        args += ["-map", f"0:{tr.stream}"]
    for n, _a in enumerate(add, 1):
        args += ["-map", f"{n}:0"]
    args += ["-c", "copy", "-map_metadata", "0", "-map_chapters", "0"]
    if add:
        args += ["-c:s", "mov_text"]  # L-1412: Text-Untertitel für MP4 umwandeln
    for k, a in enumerate(add):
        i = len(keep) + k
        args += [f"-metadata:s:{i}", f"title={a.name}", f"-metadata:s:{i}", f"handler_name={a.name}",
                 f"-metadata:s:{i}", f"language={m4.to_t(a.lang or 'und')}",
                 f"-disposition:{i}", "+".join(x for x in ("default" if a.default else "",
                                                          "forced" if a.forced else "") if x) or "0"]
    for i, tr in enumerate(keep):
        v = values[id(tr)]
        args += [f"-metadata:s:{i}", f"title={v['name']}", f"-metadata:s:{i}", f"handler_name={v['name']}"]
        if tr.kind != mt.VIDEO:
            args += [f"-metadata:s:{i}", f"language={m4.to_t(v['lang'])}",
                     f"-disposition:{i}", "default" if v["default"] else "0"]
    fmt = "mov" if files.path.lower().endswith(".mov") else "mp4"
    args += ["-f", fmt, "-progress", "pipe:1", "-nostats", tmp]
    _run_progress(args, _ffmpeg_progress(duration), progress, cancel)
    tg.mutagen_restore(tmp, snap)


# --- Formatwechsel (L-1330 ff.) ----------------------------------------------------------------------
MKV, MP4 = "mkv", "mp4"
_TS_SOURCES = (".mts", ".m2ts", ".m2t")  # v1.14, L-1420
_SOURCE_TO_MKV = (".mp4", ".m4v", ".mov", ".avi") + _TS_SOURCES
_BAD_MP4_AUDIO = ("dts", "truehd", "mlp", "pcm", "flac", "vorbis")


def convert_problem(path: str, target: str, files: mt.FileTracks | None = None) -> str:
    """Grund, warum eine Datei ausgelassen wird, sonst „“."""
    ext = os.path.splitext(path)[1].lower()
    if target == MKV:
        if ext in (".mkv", ".webm"):
            return t("convert.already")
        if ext not in _SOURCE_TO_MKV:
            return t("convert.unsupported")
        return ""
    if ext in (".mp4", ".m4v", ".mov"):
        return t("convert.already")
    if ext not in (".mkv", ".webm"):
        return t("convert.unsupported")
    if files is None:
        return ""
    for tr in files.tracks:
        low = (tr.codec or "").lower()
        if tr.kind == mt.SUBS and subtitle_kind(tr.codec) in ("pgs", "vobsub"):
            return t("convert.image_subs")  # L-1332
        if tr.kind == mt.AUDIO and any(b in low for b in _BAD_MP4_AUDIO):
            return t("convert.audio_codec", codec=tr.codec)
    return ""


def convert(path: str, target: str, files: mt.FileTracks | None, progress=None, cancel=None,
            replace: bool = False) -> str:
    """Neue Datei im Zielformat neben dem Original; Tags und Cover übertragen (L-1304).

    replace (v1.13.2): nach erfolgreicher Prüfung wird das Original gelöscht."""
    final = copy_name(path, ".mkv" if target == MKV else ".mp4")
    tmp = _tmp_for(final)
    duration = (files.duration if files else 0) or _duration(path)
    try:
        if target == MKV:
            _to_mkv(path, files, tmp, progress, cancel)
            expected = len(mt.read(tmp).tracks) if files is None else len(files.tracks)
        else:
            tracks = files.tracks if files else []
            args = [_tool("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", path]
            for tr in tracks:
                args += ["-map", f"0:{tr.stream}"]
            if not tracks:
                args += ["-map", "0:v?", "-map", "0:a?", "-map", "0:s?"]
            args += ["-c", "copy", "-c:s", "mov_text", "-map_metadata", "0", "-map_chapters", "0", "-f", "mp4",
                     "-progress", "pipe:1", "-nostats", tmp]
            _run_progress(args, _ffmpeg_progress(duration), progress, cancel)
            expected = len(tracks)
        if expected:
            _check(tmp, expected, _reference(path))
        transfer_tags(path, tmp)
        _finish(tmp, final, path)
        if replace and os.path.abspath(final) != os.path.abspath(path):
            os.remove(path)
    except BaseException:
        _discard(tmp)
        raise
    return final


def _to_mkv(path: str, files, tmp: str, progress, cancel) -> None:
    """mkvmerge; MP4-Text-Untertitel liest mkvmerge nicht überall – die kommen als .srt dazu."""
    import tempfile

    from .videotags import _fail, _run

    # Nur MP4-Text-Untertitel; Bild-Untertitel aus MPEG-TS (PGS) liest mkvmerge selbst (v1.14)
    mp4 = path.lower().endswith((".mp4", ".m4v", ".mov"))
    subs = [tr for tr in (files.tracks if files else []) if tr.kind == mt.SUBS] if mp4 else []
    args = [_tool("mkvmerge"), "--gui-mode", "-o", tmp]
    work = tempfile.mkdtemp(prefix=".panepilot-subs-", dir=os.path.dirname(os.path.abspath(tmp)))
    try:
        extra: list[str] = []
        if subs:
            args.append("--no-subtitles")
            for n, tr in enumerate(subs):
                srt = os.path.join(work, f"{n}.srt")
                proc = _run([_tool("ffmpeg"), "-nostdin", "-v", "error", "-y", "-i", path,
                             "-map", f"0:{tr.stream}", "-c:s", "srt", srt], timeout=600)
                if proc.returncode != 0:
                    raise _fail(proc, "ffmpeg")
                extra += ["--language", f"0:{tr.lang or 'und'}", "--track-name", f"0:{tr.name}",
                          "--default-track-flag", f"0:{1 if tr.default else 0}",
                          "--forced-display-flag", f"0:{1 if tr.forced else 0}", srt]
        _run_progress(args + [path] + extra, _mkvmerge_progress, progress, cancel)
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)


def transfer_tags(src: str, dst: str) -> None:
    """Titel, Jahr, Genre … eigene Felder und Cover von src nach dst (L-1304)."""
    from . import tags as tg
    from . import videotags as vt

    s = tg.read_file(src)
    d = tg.read_file(dst)
    if s.error or d.error or d.kind not in ("video-mp4", "video-mkv"):
        return
    changes = {}
    for k in vt.FIELDS:
        v = s.fields.get(k)
        if v and k not in d.readonly and d.fields.get(k) != v:
            changes[k] = v
    for k, v in s.fields.items():
        if not k.startswith(tg.EXTRA) or not v or k in s.readonly and not s.labels.get(k):
            continue
        name = s.labels.get(k) or tg.label_of(k)
        target = tg.custom_key(d.kind, name)
        existing = tg.resolve_key(d, target)
        if d.fields.get(existing) != v:
            changes[existing] = v
    pictures = list(s.pictures) if s.pictures else None
    if changes or pictures:
        vt.write_file(d, changes, pictures)
