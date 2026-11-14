"""Metadaten von Videos lesen und schreiben (v1.5).

- MP4, MOV, M4V, 3GP: Tags über mutagen (wie M4A-Musik). Aufnahmedatum und GPS stehen an anderen Stellen der
  Datei; sie werden mit ffprobe gelesen und nur mit exiftool geändert bzw. entfernt (L-533).
- WMV: Tags über mutagen (ASF).
- MKV, WebM: gelesen mit ffprobe, geschrieben nur mit mkvpropedit/mkvextract (Paket mkvtoolnix, L-511).
- AVI, MTS, M2TS: nur lesen (L-512).

Technische Angaben (Dauer, Auflösung, Bildrate, Codecs, Bitrate) liefert ffprobe (L-532). Ein Standbild als
Vorschau liefert ffmpeg (L-522). Fehlen die Programme, fehlen nur diese Angaben bzw. die Felder sind grau.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

MP4_EXTENSIONS = {".mp4", ".mov", ".m4v", ".3gp", ".3g2"}
ASF_EXTENSIONS = {".wmv", ".asf"}
MKV_EXTENSIONS = {".mkv", ".webm"}
READONLY_EXTENSIONS = {".avi", ".mts", ".m2ts", ".m2t"}
ALL_EXTENSIONS = MP4_EXTENSIONS | ASF_EXTENSIONS | MKV_EXTENSIONS | READONLY_EXTENSIONS

EDITABLE = ("title", "description", "author", "copyright", "genre", "year", "datetaken")
REMOVE_ONLY = ("gpslat", "gpslon", "gpsalt")
FIELDS = EDITABLE + REMOVE_ONLY
STANDARD_FIELDS = FIELDS
GPS = REMOVE_ONLY

KIND_MP4, KIND_ASF, KIND_MKV, KIND_RO = "video-mp4", "video-asf", "video-mkv", "video"

# Tags je Format: Lesen in dieser Reihenfolge, geschrieben wird an alle Stellen (L-534)
_MP4 = {"title": ("\xa9nam",), "description": ("desc", "\xa9cmt", "ldes"), "author": ("\xa9ART",),
        "copyright": ("cprt",), "genre": ("\xa9gen",), "year": ("\xa9day",)}
_MP4_WRITE = {"description": ("desc", "\xa9cmt")}
_ASF = {"title": ("Title",), "description": ("Description",), "author": ("Author",), "copyright": ("Copyright",),
        "genre": ("WM/Genre",), "year": ("WM/Year",)}
_MKV = {"title": ("TITLE",), "description": ("DESCRIPTION", "COMMENT", "SUMMARY", "SYNOPSIS"),
        "author": ("ARTIST", "AUTHOR", "DIRECTOR"), "copyright": ("COPYRIGHT",), "genre": ("GENRE",),
        "year": ("DATE_RELEASED", "DATE", "YEAR")}
# Angaben, die ffprobe für MKV als Tag meldet, die aber keine Tags im eigentlichen Sinn sind
_MKV_SKIP = {"TITLE", "ENCODER", "CREATION_TIME", "DURATION", "MAJOR_BRAND", "MINOR_VERSION", "COMPATIBLE_BRANDS"}

_CODECS = {"h264": "H.264", "hevc": "H.265 (HEVC)", "vp8": "VP8", "vp9": "VP9", "av1": "AV1", "mpeg4": "MPEG-4",
           "mpeg2video": "MPEG-2", "mpeg1video": "MPEG-1", "mjpeg": "MJPEG", "prores": "ProRes", "wmv1": "WMV 7",
           "wmv2": "WMV 8", "wmv3": "WMV 9", "vc1": "VC-1", "msmpeg4v3": "DivX 3", "theora": "Theora",
           "dvvideo": "DV", "aac": "AAC", "mp3": "MP3", "mp2": "MP2", "ac3": "AC-3", "eac3": "E-AC-3",
           "dts": "DTS", "truehd": "TrueHD", "opus": "Opus", "vorbis": "Vorbis", "flac": "FLAC", "alac": "ALAC",
           "wmav1": "WMA", "wmav2": "WMA", "wmapro": "WMA Pro", "amr_nb": "AMR", "amr_wb": "AMR-WB"}


def is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in ALL_EXTENSIONS


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def is_mkv(path: str) -> bool:
    return _ext(path) in MKV_EXTENSIONS


def is_mp4(path: str) -> bool:
    return _ext(path) in MP4_EXTENSIONS


def is_readonly_format(path: str) -> bool:
    return _ext(path) in READONLY_EXTENSIONS


# --- Zusatzprogramme ----------------------------------------------------------------------------------
def ffprobe() -> str | None:
    return shutil.which("ffprobe")


def ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def exiftool() -> str | None:
    return shutil.which("exiftool")


def mkvpropedit() -> str | None:
    return shutil.which("mkvpropedit")


def mkvextract() -> str | None:
    return shutil.which("mkvextract")


def mkvtoolnix() -> bool:
    return mkvpropedit() is not None and mkvextract() is not None


def _env() -> dict | None:
    try:
        from .util import child_environment

        pe = child_environment()
        return {k: pe.value(k) for k in pe.keys()} or None
    except Exception:  # noqa: BLE001 – ohne Qt die normale Umgebung
        return None


def _run(args: list[str], timeout: int = 60, binary: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=not binary, env=_env(), timeout=timeout, check=False)


def _fail(proc, name: str) -> OSError:
    err = proc.stderr if isinstance(proc.stderr, str) else (proc.stderr or b"").decode("utf-8", "replace")
    out = proc.stdout if isinstance(proc.stdout, str) else ""
    lines = [ln for ln in (err or out or name).strip().splitlines() if ln.strip()]
    return OSError(lines[-1] if lines else name)


def format_name(path: str) -> str:
    ext = _ext(path).lstrip(".")
    return {"webm": "WebM", "m2ts": "M2TS", "m2t": "M2TS"}.get(ext, ext.upper())


def codec_name(name: str) -> str:
    if not name:
        return ""
    if name.startswith("pcm_"):
        return "PCM"
    return _CODECS.get(name, name.upper())


# --- ffprobe ----------------------------------------------------------------------------------------------
def probe(path: str) -> dict | None:
    tool = ffprobe()
    if tool is None:
        return None
    try:
        proc = _run([tool, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                    timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout or "{}")
    except ValueError:
        return None


def _rate(text: str) -> float:
    try:
        a, _s, b = str(text).partition("/")
        return float(a) / float(b) if b else float(a)
    except (ValueError, ZeroDivisionError):
        return 0.0


def _apply_probe(rec, info: dict) -> None:
    fmt = info.get("format") or {}
    try:
        rec.length = float(fmt.get("duration") or rec.length or 0)
    except ValueError:
        pass
    try:
        rec.bitrate = int(fmt.get("bit_rate") or 0) or rec.bitrate
    except ValueError:
        pass
    video = audio = None
    for s in info.get("streams") or []:
        if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic") \
                and video is None:
            video = s
        elif s.get("codec_type") == "audio" and audio is None:
            audio = s
    if video is not None:
        w, h = int(video.get("width") or 0), int(video.get("height") or 0)
        rot = 0
        try:
            rot = int(float((video.get("tags") or {}).get("rotate", 0)))
        except ValueError:
            pass
        for sd in video.get("side_data_list") or []:
            if "rotation" in sd:
                try:
                    rot = int(float(sd["rotation"]))
                except ValueError:
                    pass
        if abs(rot) % 180 == 90:
            w, h = h, w
        rec.width, rec.height = w, h
        rec.fps = _rate(video.get("avg_frame_rate") or "") or _rate(video.get("r_frame_rate") or "")
        rec.vcodec = codec_name(video.get("codec_name") or "")
    if audio is not None:
        rec.acodec = codec_name(audio.get("codec_name") or "")
        rec.sample_rate = int(audio.get("sample_rate") or 0)


def _tags(info: dict | None) -> dict:
    return dict(((info or {}).get("format") or {}).get("tags") or {})


def _local(when: dt.datetime) -> str:
    if when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    return when.strftime("%Y-%m-%d %H:%M:%S")


def parse_iso(text: str) -> dt.datetime | None:
    """„2026-11-08T14:00:12.000000Z“ bzw. „2026-11-08T15:00:12+0100“ → datetime (mit Zeitzone)."""
    text = (text or "").strip()
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d)(?::(\d\d))?(?:\.\d+)?\s*(Z|[+-]\d\d:?\d\d)?$", text)
    if not m:
        return None
    y, mo, d, h, mi, s, tz = m.groups()
    try:
        when = dt.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0))
    except ValueError:
        return None
    if when.year < 1971:  # „kein Datum“ (0 bzw. 1904 in QuickTime)
        return None
    if tz == "Z":
        return when.replace(tzinfo=dt.timezone.utc)
    if tz:
        sign = -1 if tz[0] == "-" else 1
        digits = tz[1:].replace(":", "")
        return when.replace(tzinfo=dt.timezone(sign * dt.timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))))
    return when


def _date_taken(tags: dict) -> tuple[str, str]:
    """Aufnahmedatum in Ortszeit und woher es stammt."""
    for key in ("com.apple.quicktime.creationdate", "creation_time", "date_recorded", "DATE_RECORDED"):
        when = parse_iso(tags.get(key, ""))
        if when is not None:
            if key == "com.apple.quicktime.creationdate" and when.tzinfo is not None:
                return when.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"), key  # Ortszeit der Aufnahme
            return _local(when), key
    return "", ""


def parse_iso6709(text: str) -> tuple[float, float, float | None] | None:
    """„+48.1371+011.5753+520.000/“ → (Breite, Länge, Höhe)."""
    m = re.match(r"^([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)?", (text or "").strip())
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    alt = float(m.group(3)) if m.group(3) else None
    return lat, lon, alt


def _gps(tags: dict) -> tuple[dict, str]:
    for key in ("com.apple.quicktime.location.ISO6709", "location", "LOCATION", "location-eng"):
        pos = parse_iso6709(tags.get(key, ""))
        if pos is not None:
            out = {"gpslat": f"{pos[0]:.6f}", "gpslon": f"{pos[1]:.6f}"}
            if pos[2] is not None:
                out["gpsalt"] = f"{pos[2]:.1f} m"
            return out, tags.get(key, "")
    return {}, ""


# --- Lesen ---------------------------------------------------------------------------------------------
def read_file(path: str):
    from . import tags as tg

    rec = tg.TagRecord(path)
    rec.codec = format_name(path)
    try:
        st = os.stat(path)
        rec.size, rec.mtime = st.st_size, st.st_mtime
    except OSError as exc:
        rec.error = exc.strerror or str(exc)
        return rec
    info = probe(path)
    tags = _tags(info)
    if info is not None:
        _apply_probe(rec, info)
    try:
        if is_mp4(path):
            rec.kind = KIND_MP4
            _read_mp4(rec)
        elif _ext(path) in ASF_EXTENSIONS:
            rec.kind = KIND_ASF
            _read_asf(rec)
        elif is_mkv(path):
            rec.kind = KIND_MKV
            _read_mkv(rec, tags, info)
        else:
            rec.kind = KIND_RO
            _read_generic(rec, tags)
    except Exception as exc:  # noqa: BLE001 – kaputte Datei als Fehler anzeigen
        rec.error = str(exc) or type(exc).__name__
        return rec
    if info is None and rec.kind in (KIND_MKV, KIND_RO) and not rec.fields:
        rec.error = None  # ohne ffprobe einfach leer (Hinweis in der Seitenleiste)
    taken, src = _date_taken(tags)
    if taken:
        rec.fields["datetaken"] = taken
        rec.sources["datetaken"] = src
    gps, raw = _gps(tags)
    if gps:
        rec.fields.update(gps)
        rec.sources["gpslat"] = raw
    _set_access(rec)
    return rec


def _set_access(rec) -> None:
    from . import tags as tg

    extras = {k for k in rec.fields if k.startswith(tg.EXTRA)}
    if rec.kind == KIND_RO or (rec.kind == KIND_MKV and not mkvtoolnix()):
        rec.readonly = set(FIELDS) | extras | {"*"}
        return
    if rec.kind == KIND_MP4:
        if exiftool() is None:
            rec.readonly |= {"datetaken", *GPS}
        else:
            rec.removable = set(GPS)
    elif rec.kind == KIND_ASF:
        rec.readonly |= {"datetaken", *GPS}
    elif rec.kind == KIND_MKV:
        rec.readonly |= set(GPS)


def _read_mp4(rec) -> None:
    from mutagen.mp4 import MP4, MP4Cover

    from . import tags as tg

    audio = MP4(rec.path)
    if not rec.length:
        rec.length = float(getattr(audio.info, "length", 0) or 0)
    tags = audio.tags
    if tags is None:
        return
    used = {"covr", "\xa9too"}
    for name, keys in _MP4.items():
        for key in keys:
            if key in tags:
                rec.fields.setdefault(name, tg._mp4_value(key, tags[key]))
                rec.sources.setdefault(name, key)
                used.add(key)
    for key, values in tags.items():
        if key in used:
            continue
        k = tg.EXTRA + key
        rec.fields[k] = tg._mp4_value(key, values)
        rec.labels[k] = tg.label_of(k)
        if not key.startswith(("----:", "\xa9")):
            rec.readonly.add(k)
            rec.fixed.add(k)
    for c in tags.get("covr", []):
        mime = "image/png" if c.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
        rec.pictures.append(tg.Picture(bytes(c), mime, tg.FRONT_COVER, ""))


def _read_asf(rec) -> None:
    from mutagen.asf import ASF, ASFByteArrayAttribute

    from . import tags as tg

    audio = ASF(rec.path)
    if not rec.length:
        rec.length = float(getattr(audio.info, "length", 0) or 0)
    tags = audio.tags
    if tags is None:
        return
    used = {"WM/Picture"}
    for name, keys in _ASF.items():
        for key in keys:
            if key in tags:
                rec.fields[name] = tg._join(v.value for v in tags[key])
                rec.sources[name] = key
                used.add(key)
                break
    for key in tags.keys():
        if key in used:
            continue
        values = tags[key]
        if any(isinstance(v, ASFByteArrayAttribute) for v in values):
            rec.data[tg.DATA + key] = key
            continue
        k = tg.EXTRA + key
        rec.fields[k] = tg._join(v.value for v in values)
        rec.labels[k] = key
    for v in tags.get("WM/Picture", []):
        pic = tg._asf_parse_picture(bytes(v.value))
        if pic is not None:
            rec.pictures.append(pic)


def _read_mkv(rec, tags: dict, info: dict | None) -> None:
    from . import tags as tg

    upper = {k.upper(): (k, v) for k, v in tags.items()}
    used = set()
    title = tags.get("title") or upper.get("TITLE", ("", ""))[1]
    if title:
        rec.fields["title"] = title
        rec.sources["title"] = "title"
    used.add("TITLE")
    for name, keys in _MKV.items():
        if name == "title":
            continue
        for key in keys:
            if key in upper:
                rec.fields[name] = upper[key][1]
                rec.sources[name] = key
                used.add(key)
                break
    for key, (orig, value) in upper.items():
        if key in used or key in _MKV_SKIP or orig.startswith("com.") or "/" in orig or "-" in orig \
                or orig != orig.upper():
            continue
        k = tg.EXTRA + key
        rec.fields[k] = value
        rec.labels[k] = key
    rec.pictures = _attached_pictures(rec.path, info)


def _read_generic(rec, tags: dict) -> None:
    from . import tags as tg

    low = {k.lower(): v for k, v in tags.items()}
    for name, key in (("title", "title"), ("description", "comment"), ("author", "artist"),
                      ("copyright", "copyright"), ("genre", "genre"), ("year", "date")):
        if low.get(key):
            rec.fields[name] = low[key]
            rec.sources[name] = key
    for key in ("encoder", "creation_time", "title", "comment", "artist", "copyright", "genre", "date"):
        low.pop(key, None)
    for key, value in low.items():
        if key.startswith(("com.", "major_brand", "minor_version", "compatible")) or not value:
            continue
        k = tg.EXTRA + key.upper()
        rec.fields[k] = value
        rec.labels[k] = key.upper()


def _attached_pictures(path: str, info: dict | None) -> list:
    """Eingebettete Bilder eines MKV (Anhänge „cover.jpg“ usw., von ffmpeg als Bildspur gemeldet)."""
    from . import tags as tg

    out = []
    tool = ffmpeg()
    if tool is None or info is None:
        return out
    for s in info.get("streams") or []:
        disp = s.get("disposition") or {}
        tags = s.get("tags") or {}
        if not (disp.get("attached_pic") or s.get("codec_type") == "attachment"):
            continue
        mime = tags.get("mimetype") or ("image/png" if s.get("codec_name") == "png" else "image/jpeg")
        if not mime.startswith("image/"):
            continue
        try:
            proc = _run([tool, "-v", "error", "-i", path, "-map", f"0:{s.get('index')}", "-c", "copy", "-f",
                         "image2pipe", "-"], timeout=30, binary=True)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode == 0 and proc.stdout:
            pic = tg.Picture(bytes(proc.stdout), mime, tg.FRONT_COVER, tags.get("filename", ""))
            out.append(pic)
    return out


# --- Schreiben -----------------------------------------------------------------------------------------
def writable(rec) -> bool:
    return rec.kind in (KIND_MP4, KIND_ASF) or (rec.kind == KIND_MKV and mkvtoolnix())


def write_file(rec, changes: dict, pictures=None):
    """Schreibt die Änderungen und liefert den neu gelesenen Stand. OSError/ValueError bei Fehlern."""
    if not writable(rec):
        raise OSError("read-only format")
    changes = {k: (v.strip() if isinstance(v, str) else v) for k, v in changes.items()}
    special = {k: v for k, v in changes.items() if k == "datetaken" or k in GPS}
    normal = {k: v for k, v in changes.items() if k not in special}
    if rec.kind == KIND_MP4:
        if normal or pictures is not None:
            _write_mp4(rec, normal, pictures)
        if special:
            _write_exiftool(rec, special)
    elif rec.kind == KIND_ASF:
        if normal or pictures is not None:
            _write_asf(rec, normal, pictures)
    elif rec.kind == KIND_MKV:
        _write_mkv(rec, normal, special.get("datetaken", ...), pictures)
    return read_file(rec.path)


def _save(audio) -> None:
    import mutagen

    try:
        audio.save()
    except mutagen.MutagenError as exc:
        cause = exc.__cause__ or exc.__context__
        if isinstance(cause, OSError):
            raise cause from exc
        raise OSError(str(exc)) from exc


def _write_mp4(rec, changes: dict, pictures) -> None:
    from mutagen.mp4 import MP4, MP4FreeForm

    from . import tags as tg

    audio = MP4(rec.path)
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    for field, value in changes.items():
        if field.startswith(tg.DATA):
            field = tg.EXTRA + field[len(tg.DATA):]
        if field.startswith(tg.EXTRA):
            keys = (field[len(tg.EXTRA):],)
        else:
            keys = _MP4_WRITE.get(field, _MP4.get(field, ())[:1])
            if value is None:
                keys = _MP4.get(field, ())
        for key in keys:
            if key in tags:
                del tags[key]
            if value is None:
                continue
            if key.startswith("----:"):
                tags[key] = [MP4FreeForm(value.encode("utf-8"))]
            else:
                tags[key] = [value]
    if pictures is not None:
        tg._mp4_set_pictures(tags, pictures)
    _save(audio)


def _write_asf(rec, changes: dict, pictures) -> None:
    from mutagen.asf import ASF

    from . import tags as tg

    audio = ASF(rec.path)
    tags = audio.tags
    for field, value in changes.items():
        if field.startswith(tg.DATA):
            field = tg.EXTRA + field[len(tg.DATA):]
        key = field[len(tg.EXTRA):] if field.startswith(tg.EXTRA) else _ASF[field][0]
        if key in tags:
            del tags[key]
        if value is not None:
            tags[key] = [value]
    if pictures is not None:
        tg._asf_set_pictures(tags, pictures)
    _save(audio)


def _date_value(value: str) -> dt.datetime:
    from .phototags import parse_date

    when = parse_date(value)
    if when is None:
        raise ValueError(f"{value}: date?")
    return when


def _offset(when: dt.datetime) -> str:
    """Zeitzonenabstand der Ortszeit zu diesem Zeitpunkt, z. B. „+01:00“."""
    off = when.astimezone().utcoffset() or dt.timedelta(0)
    minutes = int(off.total_seconds() // 60)
    sign = "-" if minutes < 0 else "+"
    minutes = abs(minutes)
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def _write_exiftool(rec, special: dict) -> None:
    tool = exiftool()
    if tool is None:
        raise OSError("exiftool")
    args = [tool, "-overwrite_original", "-q", "-m", "-api", "QuickTimeUTC=1", "-charset", "filename=utf8",
            "-charset", "utf8"]
    if "datetaken" in special:
        value = special["datetaken"]
        if value is None:
            args += ["-QuickTime:CreateDate=", "-Keys:CreationDate="]
        else:
            when = _date_value(value)
            stamp = when.strftime("%Y:%m:%d %H:%M:%S")
            args += [f"-QuickTime:CreateDate={stamp}", f"-QuickTime:TrackCreateDate={stamp}",
                     f"-QuickTime:MediaCreateDate={stamp}"]
            if rec.sources.get("datetaken") == "com.apple.quicktime.creationdate":
                args.append(f"-Keys:CreationDate={stamp}{_offset(when)}")
    if any(k in special for k in GPS):
        if all(special.get(k, None) is None for k in GPS if k in special):
            args += ["-UserData:GPSCoordinates=", "-Keys:GPSCoordinates=", "-ItemList:GPSCoordinates=",
                     "-UserData:LocationInformation=", "-XMP:GPSLatitude=", "-XMP:GPSLongitude=",
                     "-XMP:GPSAltitude="]
    args.append(rec.path)
    proc = _run(args)
    if proc.returncode != 0:
        raise _fail(proc, "exiftool")


# --- MKV über mkvtoolnix ------------------------------------------------------------------------------------
def _mkv_read_xml(path: str) -> ET.Element:
    tool = mkvextract()
    if tool is None:
        raise OSError("mkvextract")
    with tempfile.TemporaryDirectory(prefix="panepilot-") as tmp:
        out = os.path.join(tmp, "tags.xml")
        proc = _run([tool, path, "tags", out])
        if proc.returncode not in (0, 1):  # 1 = Warnungen
            raise _fail(proc, "mkvextract")
        if not os.path.exists(out) or os.path.getsize(out) == 0:
            return ET.Element("Tags")
        try:
            return ET.parse(out).getroot()
        except ET.ParseError:
            return ET.Element("Tags")


def _is_global(tag: ET.Element) -> bool:
    targets = tag.find("Targets")
    if targets is None:
        return True
    if any(targets.find(uid) is not None for uid in ("TrackUID", "EditionUID", "ChapterUID", "AttachmentUID")):
        return False
    tv = targets.findtext("TargetTypeValue")
    return tv in (None, "", "50")


def _global_tag(root: ET.Element, create: bool) -> ET.Element | None:
    for tag in root.findall("Tag"):
        if _is_global(tag):
            return tag
    if not create:
        return None
    tag = ET.SubElement(root, "Tag")
    targets = ET.SubElement(tag, "Targets")
    ET.SubElement(targets, "TargetTypeValue").text = "50"
    return tag


def mkv_set_simple(root: ET.Element, name: str, value: str | None) -> None:
    """Einfachen Tag im globalen Bereich setzen bzw. löschen (Groß-/Kleinschreibung egal)."""
    tag = _global_tag(root, create=value is not None)
    if tag is None:
        return
    for simple in tag.findall("Simple"):
        if (simple.findtext("Name") or "").upper() == name.upper():
            tag.remove(simple)
    if value is not None:
        simple = ET.SubElement(tag, "Simple")
        ET.SubElement(simple, "Name").text = name
        ET.SubElement(simple, "String").text = value
    if not tag.findall("Simple"):
        root.remove(tag)


def _mkv_date_args(datetaken) -> list[str]:
    if datetaken is None or datetaken == "":
        return ["--delete", "date"]
    when = _date_value(datetaken).astimezone(dt.timezone.utc)
    return ["--set", "date=" + when.strftime("%Y-%m-%dT%H:%M:%SZ")]


def _mkv_tags_args(root: ET.Element, tmp: str) -> list[str]:
    if not root.findall("Tag"):
        return ["--tags", "all:"]
    out = os.path.join(tmp, "tags.xml")
    ET.ElementTree(root).write(out, encoding="utf-8", xml_declaration=True)
    return ["--tags", f"all:{out}"]


def _mkv_picture_args(old: list, new: list, tmp: str) -> list[str]:
    args = []
    for p in old:
        if p.desc:
            args += ["--delete-attachment", f"name:{p.desc}"]
    for i, p in enumerate(new):
        ext = ".png" if p.mime == "image/png" else ".jpg"
        name = ("cover" if i == 0 else f"cover_{i}") + ext
        src = os.path.join(tmp, f"{i}_{name}")
        with open(src, "wb") as fh:
            fh.write(p.data)
        args += ["--attachment-name", name, "--attachment-mime-type", p.mime, "--add-attachment", src]
    return args


def _mkv_run(path: str, groups: list[list[str]]) -> None:
    """Jede Art von Änderung in einem eigenen Aufruf: mkvpropedit verrechnet sich sonst manchmal beim
    Verschieben mehrerer Bereiche und verweigert dann das Schreiben („data … corrupted“)."""
    tool = mkvpropedit()
    if tool is None:
        raise OSError("mkvpropedit")
    for group in groups:
        if not group:
            continue
        proc = _run([tool, path, *group], timeout=120)
        if proc.returncode not in (0, 1):  # 1 = nur Warnungen
            raise _fail(proc, "mkvpropedit")


def _write_mkv(rec, changes: dict, datetaken, pictures) -> None:
    from . import tags as tg

    info: list[str] = []
    tag_changes: dict = {}
    for field, value in changes.items():
        if field == "title":
            info += ["--set", f"title={value}"] if value is not None else ["--delete", "title"]
            if "TITLE" in {k.upper() for k in _mkv_simple_names(rec)}:
                tag_changes["TITLE"] = value
            continue
        if field.startswith(tg.EXTRA):
            tag_changes[field[len(tg.EXTRA):]] = value
            continue
        keys = _MKV.get(field)
        if not keys:
            continue
        if value is None:
            for k in keys:
                tag_changes[k] = None
        else:
            tag_changes[rec.sources.get(field) or keys[0]] = value
    if datetaken is not ...:
        info += _mkv_date_args(datetaken)
    with tempfile.TemporaryDirectory(prefix="panepilot-") as tmp:
        tags: list[str] = []
        if tag_changes:
            root = _mkv_read_xml(rec.path)
            for name, value in tag_changes.items():
                mkv_set_simple(root, name, value)
            tags = _mkv_tags_args(root, tmp)
        pics = _mkv_picture_args(rec.pictures, pictures, tmp) if pictures is not None else []
        _mkv_run(rec.path, [["--edit", "info", *info] if info else [], tags, pics])


def _mkv_simple_names(rec) -> list[str]:
    return [k for k in rec.sources.values()] + [k[2:] for k in rec.fields if k.startswith("x:")]


# --- Rückgängig ----------------------------------------------------------------------------------------
def snapshot(path: str, with_pictures: bool) -> tuple:
    from . import tags as tg

    rec = read_file(path)
    special = {k: rec.fields.get(k) for k in ("datetaken", *GPS)}
    special["_gps_raw"] = rec.sources.get("gpslat", "")
    special["_date_src"] = rec.sources.get("datetaken", "")
    if rec.kind in (KIND_MP4, KIND_ASF):
        inner = tg.mutagen_snapshot(path, with_pictures)
    elif rec.kind == KIND_MKV and mkvtoolnix():
        inner = ("mkv", ET.tostring(_mkv_read_xml(path), encoding="unicode"), rec.fields.get("title"),
                 [tg.Picture(p.data, p.mime, p.ptype, p.desc) for p in rec.pictures] if with_pictures else None)
    else:
        inner = None
    return ("video", rec.kind, inner, special)


def restore(path: str, snap: tuple):
    from . import tags as tg

    _v, kind, inner, special = snap
    rec = read_file(path)
    if kind in (KIND_MP4, KIND_ASF) and inner is not None:
        tg.mutagen_restore(path, inner)
    elif kind == KIND_MKV and inner is not None:
        _mkv_restore(rec, inner, special.get("datetaken"))
        rec = read_file(path)
    if kind == KIND_MP4 and exiftool() is not None:
        rec = read_file(path)
        _restore_special(rec, special)
    return read_file(path)


def _mkv_restore(rec, inner, datetaken) -> None:
    _k, xml, title, pictures = inner
    with tempfile.TemporaryDirectory(prefix="panepilot-") as tmp:
        info = ["--edit", "info"] + (["--set", f"title={title}"] if title else ["--delete", "title"])
        info += _mkv_date_args(datetaken)
        tags = _mkv_tags_args(ET.fromstring(xml), tmp)
        pics = _mkv_picture_args(rec.pictures, pictures, tmp) if pictures is not None else []
        _mkv_run(rec.path, [info, tags, pics])


def _restore_special(rec, special: dict) -> None:
    tool = exiftool()
    args = [tool, "-overwrite_original", "-q", "-m", "-api", "QuickTimeUTC=1"]
    old_date = special.get("datetaken")
    if old_date and old_date != rec.fields.get("datetaken"):
        when = _date_value(old_date)
        stamp = when.strftime("%Y:%m:%d %H:%M:%S")
        args += [f"-QuickTime:CreateDate={stamp}", f"-QuickTime:TrackCreateDate={stamp}",
                 f"-QuickTime:MediaCreateDate={stamp}"]
        if special.get("_date_src") == "com.apple.quicktime.creationdate":
            args.append(f"-Keys:CreationDate={stamp}{_offset(when)}")
    raw = special.get("_gps_raw") or ""
    if raw and "gpslat" not in rec.fields:
        pos = parse_iso6709(raw)
        if pos is not None:
            coords = f"{pos[0]}, {pos[1]}" + (f", {pos[2]}" if pos[2] is not None else "")
            args.append(f"-UserData:GPSCoordinates={coords}")
    if len(args) > 6:
        args.append(rec.path)
        proc = _run(args)
        if proc.returncode != 0:
            raise _fail(proc, "exiftool")


# --- Standbild ---------------------------------------------------------------------------------------------
def frame_args(path: str, length: float, size: int = 432) -> list[str] | None:
    """Befehl für ein Standbild bei etwa 10 % der Laufzeit (PNG auf die Standardausgabe), L-522."""
    tool = ffmpeg()
    if tool is None:
        return None
    pos = max(0.0, (length or 0) * 0.1)
    return [tool, "-v", "error", "-ss", f"{pos:.2f}", "-i", path, "-frames:v", "1", "-vf",
            f"scale='min({size},iw)':-2", "-f", "image2pipe", "-vcodec", "png", "-"]


def grab_frame(path: str, length: float, size: int = 432) -> bytes | None:
    args = frame_args(path, length, size)
    if args is None:
        return None
    try:
        proc = _run(args, timeout=30, binary=True)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return bytes(proc.stdout) if proc.returncode == 0 and proc.stdout else None


def format_fps(fps: float) -> str:
    if not fps:
        return ""
    text = f"{fps:.3f}".rstrip("0").rstrip(".")
    return f"{text} fps"
