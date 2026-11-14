"""Tags von Musikdateien lesen und schreiben (Meta-Wizard, F-900 ff.) – auf Basis von mutagen.

Einheitliche Sicht auf die verschiedenen Tag-Arten:
- bekannte Felder unter festen Namen (FIELDS), z. B. "title" oder "track"
- alle übrigen Text-Tags als Zusatzfelder mit dem Schlüssel "x:<Rohname>" (F-912)
- Bilder als Liste von Picture

Beim Speichern werden nur die geänderten Felder angefasst; alles andere in der Datei bleibt
unverändert (F-941).
"""

from __future__ import annotations

import base64
import os
import struct
from dataclasses import dataclass, field

# Bekannte Felder in der Reihenfolge der Spaltenauswahl
FIELDS = ("title", "artist", "album", "albumartist", "track", "disc", "year", "genre", "comment",
          "composer", "conductor", "bpm", "copyright", "publisher", "grouping", "isrc", "encodedby", "lyrics")
EXTRA = "x:"  # Präfix für Zusatzfelder
DATA = "d:"  # Präfix für Datenfelder ohne lesbaren Inhalt (z. B. PRIV) – nur löschbar (F-972)
# Standardfelder: im Feld-Editor weder löschbar noch umbenennbar (F-976)
STANDARD_FIELDS = ("title", "artist", "album", "year", "track", "genre", "comment", "albumartist", "disc")

AUDIO_EXTENSIONS = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".wma", ".m4a", ".wav"}

FRONT_COVER = 3


def is_audio(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS


@dataclass
class Picture:
    data: bytes
    mime: str = "image/jpeg"
    ptype: int = FRONT_COVER
    desc: str = ""

    def same(self, other: Picture) -> bool:
        return self.data == other.data and self.ptype == other.ptype


@dataclass
class TagRecord:
    path: str
    kind: str = ""  # id3, vorbis, mp4, asf
    codec: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)  # Zusatzfeld → Anzeigename
    sources: dict[str, str] = field(default_factory=dict)  # Feld → tatsächlicher Schlüssel in der Datei
    readonly: set[str] = field(default_factory=set)  # Zusatzfelder, die nur angezeigt werden
    fixed: set[str] = field(default_factory=set)  # Zusatzfelder mit festem Namen (nur löschbar)
    data: dict[str, str] = field(default_factory=dict)  # Datenfelder → Anzeigename (F-972)
    pictures: list[Picture] = field(default_factory=list)
    length: float = 0.0
    bitrate: int = 0
    sample_rate: int = 0
    size: int = 0
    mtime: float = 0.0
    error: str | None = None

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    def front_cover(self) -> Picture | None:
        for p in self.pictures:
            if p.ptype == FRONT_COVER:
                return p
        return self.pictures[0] if self.pictures else None


def label_of(key: str) -> str:
    """Anzeigename eines Zusatzfelds aus seinem Schlüssel."""
    raw = key[len(EXTRA):] if key.startswith(EXTRA) else key
    if raw.startswith("TXXX:"):
        return raw[5:]
    if raw.startswith("----:"):
        return raw.rsplit(":", 1)[-1]
    if len(raw) > 5 and raw[0] == "W" and raw[4] == ":" and raw[:4].isalnum():
        return raw[:4]  # Web-Adressen (z. B. WOAR:<url>) unter dem Feldnamen zeigen
    return raw


def _join(values) -> str:
    return "; ".join(str(v) for v in values if str(v) != "")


# ==== ID3 (MP3, WAV) ===========================================================================
_ID3 = {"title": "TIT2", "artist": "TPE1", "album": "TALB", "albumartist": "TPE2", "track": "TRCK",
        "disc": "TPOS", "year": "TDRC", "genre": "TCON", "composer": "TCOM", "conductor": "TPE3",
        "bpm": "TBPM", "copyright": "TCOP", "publisher": "TPUB", "grouping": "TIT1", "isrc": "TSRC",
        "encodedby": "TENC"}
_ID3_YEAR_V23 = ("TYER", "TDAT", "TIME", "TRDA")  # werden beim Lesen zu TDRC zusammengefasst


def _id3_read(rec: TagRecord, tags) -> None:
    from mutagen.id3 import TCON, TextFrame, UrlFrame

    if tags is None:
        return
    used = set()
    for name, fid in _ID3.items():
        frame = tags.get(fid)
        if frame is None:
            continue
        rec.fields[name] = _join(frame.genres) if isinstance(frame, TCON) else _join(frame.text)
        rec.sources[name] = fid
        used.add(fid)
    for name, fid in (("comment", "COMM"), ("lyrics", "USLT")):
        frames = sorted(tags.getall(fid), key=lambda f: (f.desc != "", f.desc.casefold()))
        if frames:
            main = next((f for f in frames if f.desc == ""), frames[0])
            rec.fields[name] = main.text if fid == "USLT" else _join(main.text)
            rec.sources[name] = main.HashKey
            used.add(main.HashKey)
    for key, frame in tags.items():
        if key in used or key.split(":")[0] in used or key.startswith(("APIC", "TDRC") + _ID3_YEAR_V23):
            continue
        fid = frame.FrameID
        if isinstance(frame, TextFrame) or fid == "COMM":
            k = EXTRA + (f"TXXX:{frame.desc}" if fid == "TXXX" else key)
            rec.fields[k] = _join(frame.text)
            rec.labels[k] = label_of(k)
        elif fid == "UFID":  # v1.2: z. B. MusicBrainz-Track-ID
            k = EXTRA + key
            rec.fields[k] = bytes(frame.data).decode("utf-8", "replace")
            rec.labels[k] = label_of(k)
        elif isinstance(frame, UrlFrame) or fid == "WXXX":
            k = EXTRA + key
            rec.fields[k] = frame.url
            rec.labels[k] = label_of(k)
            rec.readonly.add(k)
        else:
            rec.data[DATA + fid] = fid
    for f in tags.getall("APIC"):
        rec.pictures.append(Picture(bytes(f.data), f.mime or "image/jpeg", int(f.type), f.desc))


def _id3_set(tags, rec: TagRecord, key: str, value: str | None) -> None:
    from mutagen import id3

    if key.startswith(DATA):
        tags.delall(key[len(DATA):])
        return
    if value is None and key.startswith(EXTRA):
        raw = key[len(EXTRA):]
        if raw in tags:
            del tags[raw]
        else:
            tags.delall(raw)
        return

    if key in _ID3:
        fid = _ID3[key]
        tags.delall(fid)
        if fid == "TDRC":
            for old in _ID3_YEAR_V23:
                tags.delall(old)
        if value is not None:
            tags.add(getattr(id3, fid)(encoding=1, text=[value]))
        return
    if key in ("comment", "lyrics") or key.startswith(EXTRA + "COMM"):
        fid = "USLT" if key == "lyrics" else "COMM"
        hk = rec.sources.get(key) if not key.startswith(EXTRA) else key[len(EXTRA):]
        old = tags.get(hk) if hk else None
        if old is not None:
            del tags[hk]
        if value is not None:
            lang = getattr(old, "lang", "eng") or "eng"
            desc = getattr(old, "desc", "") if old is not None else ""
            if fid == "USLT":
                tags.add(id3.USLT(encoding=1, lang=lang, desc=desc, text=value))
            else:
                tags.add(id3.COMM(encoding=1, lang=lang, desc=desc, text=[value]))
        return
    raw = key[len(EXTRA):]
    if raw.startswith("TXXX:"):
        desc = raw[5:]
        tags.delall(f"TXXX:{desc}")
        if value is not None:
            tags.add(id3.TXXX(encoding=1, desc=desc, text=[value]))
        return
    if raw.startswith("UFID:"):
        tags.delall(raw)
        if value is not None:
            tags.add(id3.UFID(owner=raw[5:], data=value.encode("utf-8")))
        return
    fid = raw.split(":")[0]
    cls = getattr(id3, fid, None)
    if cls is None or not fid.startswith("T"):
        raise ValueError(f"{raw}: cannot be changed")
    tags.delall(fid)
    if value is not None:
        tags.add(cls(encoding=1, text=[value]))


def _id3_set_pictures(tags, pictures: list[Picture]) -> None:
    from mutagen.id3 import APIC

    tags.delall("APIC")
    for i, p in enumerate(pictures):
        # Die Beschreibung muss je Bildtyp eindeutig sein, sonst überschreiben sich die Bilder
        tags.add(APIC(encoding=1, mime=p.mime, type=p.ptype, desc=p.desc or ("" if i == 0 else str(i)), data=p.data))


# ==== Vorbis-Kommentare (FLAC, Ogg Vorbis, Opus) =================================================
_VORBIS = {"title": ("TITLE",), "artist": ("ARTIST",), "album": ("ALBUM",),
           "albumartist": ("ALBUMARTIST", "ALBUM ARTIST"), "track": ("TRACKNUMBER",),
           "disc": ("DISCNUMBER",), "year": ("DATE", "YEAR"), "genre": ("GENRE",),
           "comment": ("COMMENT", "DESCRIPTION"), "composer": ("COMPOSER",), "conductor": ("CONDUCTOR",),
           "bpm": ("BPM",), "copyright": ("COPYRIGHT",), "publisher": ("ORGANIZATION", "LABEL", "PUBLISHER"),
           "grouping": ("GROUPING",), "isrc": ("ISRC",), "encodedby": ("ENCODEDBY",), "lyrics": ("LYRICS",)}
_VORBIS_PICTURE = "METADATA_BLOCK_PICTURE"


def _vorbis_read(rec: TagRecord, tags) -> None:
    if tags is None:
        return
    keys = {k.upper(): k for k in tags.keys()}
    used = {_VORBIS_PICTURE, "COVERART", "COVERARTMIME"}
    for name, aliases in _VORBIS.items():
        for alias in aliases:
            if alias in keys:
                rec.fields[name] = _join(tags[keys[alias]])
                rec.sources[name] = alias
                used.add(alias)
                break
    for upper, k in keys.items():
        if upper in used:
            continue
        key = EXTRA + upper
        rec.fields[key] = _join(tags[k])
        rec.labels[key] = upper


def _vorbis_set(tags, rec: TagRecord, key: str, value: str | None) -> None:
    target = key[len(EXTRA):] if key.startswith(EXTRA) else rec.sources.get(key, _VORBIS[key][0])
    for k in list(tags.keys()):
        if k.upper() == target:
            del tags[k]
    if value is not None:
        tags[target] = [value]


def _flac_picture(p: Picture):
    from mutagen.flac import Picture as FlacPicture

    fp = FlacPicture()
    fp.data, fp.mime, fp.type, fp.desc = p.data, p.mime, p.ptype, p.desc
    return fp


def _ogg_pictures(tags) -> list[Picture]:
    from mutagen.flac import Picture as FlacPicture

    result = []
    for k in list(tags.keys()):
        if k.upper() != _VORBIS_PICTURE:
            continue
        for b64 in tags[k]:
            try:
                fp = FlacPicture(base64.b64decode(b64))
            except Exception:  # noqa: BLE001 – kaputtes Bild überspringen
                continue
            result.append(Picture(bytes(fp.data), fp.mime or "image/jpeg", int(fp.type), fp.desc))
    return result


def _ogg_set_pictures(tags, pictures: list[Picture]) -> None:
    for k in list(tags.keys()):
        if k.upper() in (_VORBIS_PICTURE, "COVERART", "COVERARTMIME"):
            del tags[k]
    if pictures:
        tags[_VORBIS_PICTURE] = [base64.b64encode(_flac_picture(p).write()).decode("ascii") for p in pictures]


# ==== MP4 / M4A =====================================================================================
_FF = "----:com.apple.iTunes:"
_MP4 = {"title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb", "albumartist": "aART", "track": "trkn",
        "disc": "disk", "year": "\xa9day", "genre": "\xa9gen", "comment": "\xa9cmt", "composer": "\xa9wrt",
        "conductor": _FF + "CONDUCTOR", "bpm": "tmpo", "copyright": "cprt", "publisher": _FF + "LABEL",
        "grouping": "\xa9grp", "isrc": _FF + "ISRC", "encodedby": "\xa9too", "lyrics": "\xa9lyr"}


def _mp4_value(key: str, values) -> str:
    out = []
    for v in values:
        if key in ("trkn", "disk"):
            n, total = (tuple(v) + (0, 0))[:2]
            out.append(f"{n}/{total}" if total else str(n))
        elif isinstance(v, bytes):
            out.append(v.decode("utf-8", "replace"))
        else:
            out.append(str(v))
    return _join(out)


def _mp4_read(rec: TagRecord, tags) -> None:
    from mutagen.mp4 import MP4Cover

    if tags is None:
        return
    used = {"covr"}
    for name, key in _MP4.items():
        if key in tags:
            rec.fields[name] = _mp4_value(key, tags[key])
            rec.sources[name] = key
            used.add(key)
    if "genre" not in rec.fields and "gnre" in tags:
        from mutagen.id3 import TCON

        rec.fields["genre"] = _join(TCON(text=[f"({n})" for n in tags["gnre"]]).genres)
        used.add("gnre")
    for key, values in tags.items():
        if key in used:
            continue
        k = EXTRA + key
        rec.fields[k] = _mp4_value(key, values)
        rec.labels[k] = label_of(k)
        if not key.startswith(("----:", "\xa9", "so")):  # so..: Sortierfelder (v1.2)
            rec.readonly.add(k)
            rec.fixed.add(k)
    for c in tags.get("covr", []):
        mime = "image/png" if c.imageformat == MP4Cover.FORMAT_PNG else "image/jpeg"
        rec.pictures.append(Picture(bytes(c), mime, FRONT_COVER, ""))


def _parse_pair(value: str) -> tuple[int, int]:
    a, _sep, b = value.partition("/")
    return int(a.strip() or 0), int(b.strip() or 0)


def _mp4_set(tags, rec: TagRecord, key: str, value: str | None) -> None:
    from mutagen.mp4 import MP4FreeForm

    if key.startswith(DATA):
        key = EXTRA + key[len(DATA):]
    mkey = key[len(EXTRA):] if key.startswith(EXTRA) else _MP4[key]
    if key == "genre" and "gnre" in tags:
        del tags["gnre"]
    if mkey in tags:
        del tags[mkey]
    if value is None:
        return
    if mkey in ("trkn", "disk"):
        tags[mkey] = [_parse_pair(value)]
    elif mkey == "tmpo":
        tags[mkey] = [int(value)]
    elif mkey.startswith("----:"):
        tags[mkey] = [MP4FreeForm(value.encode("utf-8"))]
    else:
        tags[mkey] = [value]


def _mp4_set_pictures(tags, pictures: list[Picture]) -> None:
    from mutagen.mp4 import MP4Cover

    if "covr" in tags:
        del tags["covr"]
    covers = [MP4Cover(p.data, MP4Cover.FORMAT_PNG if p.mime == "image/png" else MP4Cover.FORMAT_JPEG)
              for p in pictures]
    if covers:
        tags["covr"] = covers


# ==== ASF / WMA ======================================================================================
_ASF = {"title": "Title", "artist": "Author", "album": "WM/AlbumTitle", "albumartist": "WM/AlbumArtist",
        "track": "WM/TrackNumber", "disc": "WM/PartOfSet", "year": "WM/Year", "genre": "WM/Genre",
        "comment": "Description", "composer": "WM/Composer", "conductor": "WM/Conductor",
        "bpm": "WM/BeatsPerMinute", "copyright": "Copyright", "publisher": "WM/Publisher",
        "grouping": "WM/ContentGroupDescription", "isrc": "WM/ISRC", "encodedby": "WM/EncodedBy",
        "lyrics": "WM/Lyrics"}


def _asf_read(rec: TagRecord, tags) -> None:
    from mutagen.asf import ASFByteArrayAttribute

    if tags is None:
        return
    used = {"WM/Picture"}
    for name, key in _ASF.items():
        if key in tags:
            rec.fields[name] = _join(v.value for v in tags[key])
            rec.sources[name] = key
            used.add(key)
    for key in tags.keys():
        if key in used:
            continue
        values = tags[key]
        if any(isinstance(v, ASFByteArrayAttribute) for v in values):
            rec.data[DATA + key] = key
            continue
        k = EXTRA + key
        rec.fields[k] = _join(v.value for v in values)
        rec.labels[k] = key
    for v in tags.get("WM/Picture", []):
        pic = _asf_parse_picture(bytes(v.value))
        if pic is not None:
            rec.pictures.append(pic)


def _asf_parse_picture(data: bytes) -> Picture | None:
    """WM/Picture: Typ (1 Byte), Länge (4 Byte LE), MIME und Beschreibung als UTF-16 mit Nullende, Daten."""
    try:
        ptype = data[0]
        (size,) = struct.unpack_from("<I", data, 1)
        pos = 5

        def utf16z(pos):
            end = pos
            while data[end:end + 2] != b"\0\0":
                end += 2
            return data[pos:end].decode("utf-16-le"), end + 2

        mime, pos = utf16z(pos)
        desc, pos = utf16z(pos)
        return Picture(data[pos:pos + size], mime or "image/jpeg", ptype, desc)
    except (IndexError, struct.error, UnicodeDecodeError):
        return None


def _asf_build_picture(p: Picture) -> bytes:
    return (bytes([p.ptype]) + struct.pack("<I", len(p.data)) + p.mime.encode("utf-16-le") + b"\0\0"
            + p.desc.encode("utf-16-le") + b"\0\0" + p.data)


def _asf_set(tags, rec: TagRecord, key: str, value: str | None) -> None:
    if key.startswith(DATA):
        key = EXTRA + key[len(DATA):]
    akey = key[len(EXTRA):] if key.startswith(EXTRA) else _ASF[key]
    if akey in tags:
        del tags[akey]
    if value is not None:
        tags[akey] = [value]


def _asf_set_pictures(tags, pictures: list[Picture]) -> None:
    from mutagen.asf import ASFByteArrayAttribute

    if "WM/Picture" in tags:
        del tags["WM/Picture"]
    if pictures:
        tags["WM/Picture"] = [ASFByteArrayAttribute(_asf_build_picture(p)) for p in pictures]


# ==== Öffnen, Lesen, Schreiben ======================================================================
def _open(path: str):
    import mutagen
    from mutagen.asf import ASF
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4
    from mutagen.oggopus import OggOpus
    from mutagen.oggvorbis import OggVorbis
    from mutagen.wave import WAVE

    ext = os.path.splitext(path)[1].lower()
    cls = {".mp3": MP3, ".flac": FLAC, ".ogg": OggVorbis, ".oga": OggVorbis, ".opus": OggOpus,
           ".m4a": MP4, ".wma": ASF, ".wav": WAVE}.get(ext)
    try:
        audio = cls(path) if cls else None
    except mutagen.MutagenError:
        audio = None
    if audio is None:  # falsche Endung, z. B. Opus in .ogg
        audio = mutagen.File(path)
    if audio is None:
        raise ValueError("unknown format")
    return audio


def _kind(audio) -> tuple[str, str]:
    name = type(audio).__name__
    return {"MP3": ("id3", "MP3"), "WAVE": ("id3", "WAV"), "FLAC": ("vorbis", "FLAC"),
            "OggVorbis": ("vorbis", "Ogg Vorbis"), "OggOpus": ("vorbis", "Opus"), "OggFLAC": ("vorbis", "Ogg FLAC"),
            "MP4": ("mp4", "AAC (M4A)"), "ASF": ("asf", "WMA")}.get(name, ("", name))


def read_file(path: str) -> TagRecord:
    rec = TagRecord(path)
    try:
        st = os.stat(path)
        rec.size, rec.mtime = st.st_size, st.st_mtime
        audio = _open(path)
    except Exception as exc:  # noqa: BLE001 – jede kaputte Datei als Fehler anzeigen, nicht abstürzen
        rec.error = str(exc) or type(exc).__name__
        return rec
    rec.kind, rec.codec = _kind(audio)
    info = getattr(audio, "info", None)
    rec.length = float(getattr(info, "length", 0) or 0)
    rec.bitrate = int(getattr(info, "bitrate", 0) or 0)
    rec.sample_rate = int(getattr(info, "sample_rate", 0) or 0)
    if rec.kind == "mp4" and getattr(info, "codec", ""):
        rec.codec = "ALAC (M4A)" if info.codec == "alac" else rec.codec
    try:
        if rec.kind == "id3":
            _id3_read(rec, audio.tags)
        elif rec.kind == "vorbis":
            _vorbis_read(rec, audio.tags)
            if type(audio).__name__ == "FLAC":
                rec.pictures = [Picture(bytes(p.data), p.mime or "image/jpeg", int(p.type), p.desc)
                                for p in audio.pictures]
            elif audio.tags is not None:
                rec.pictures = _ogg_pictures(audio.tags)
        elif rec.kind == "mp4":
            _mp4_read(rec, audio.tags)
        elif rec.kind == "asf":
            _asf_read(rec, audio.tags)
    except Exception as exc:  # noqa: BLE001
        rec.error = str(exc) or type(exc).__name__
    return rec


def write_file(rec: TagRecord, changes: dict[str, str | None], pictures: list[Picture] | None = None) -> TagRecord:
    """Schreibt die Änderungen (Wert None = Feld entfernen) und liefert den neu gelesenen Stand.

    pictures=None lässt die Bilder unverändert, sonst ersetzt die Liste alle Bilder der Datei.
    Wirft OSError/ValueError bei Fehlern.
    """
    import mutagen

    audio = _open(rec.path)
    kind, _codec = _kind(audio)
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    setter = {"id3": _id3_set, "vorbis": _vorbis_set, "mp4": _mp4_set, "asf": _asf_set}.get(kind)
    if setter is None:
        raise ValueError("unsupported format")
    for key, value in changes.items():
        if value is not None:
            value = value.strip()
        setter(tags, rec, key, value)
    if pictures is not None:
        if kind == "id3":
            _id3_set_pictures(tags, pictures)
        elif kind == "vorbis" and type(audio).__name__ == "FLAC":
            audio.clear_pictures()
            for p in pictures:
                audio.add_picture(_flac_picture(p))
        elif kind == "vorbis":
            _ogg_set_pictures(tags, pictures)
        elif kind == "mp4":
            _mp4_set_pictures(tags, pictures)
        elif kind == "asf":
            _asf_set_pictures(tags, pictures)
    try:
        if kind == "id3":
            audio.save(v2_version=3)  # F-940: ID3v2.3, vorhandenes ID3v1 wird mit aktualisiert
        else:
            audio.save()
    except mutagen.MutagenError as exc:
        cause = exc.__cause__ or exc.__context__
        if isinstance(cause, OSError):
            raise cause from exc
        raise OSError(str(exc)) from exc
    return read_file(rec.path)


# ==== Eigene Felder und Feldnamen (F-970 ff.) ===================================================
def custom_key(kind: str, name: str) -> str:
    """Schlüssel eines eigenen Felds im jeweiligen Tag-Format."""
    if kind == "id3":
        return f"{EXTRA}TXXX:{name}"
    if kind == "vorbis":
        return EXTRA + name.upper()
    if kind == "mp4":
        return f"{EXTRA}{_FF}{name}"
    return EXTRA + name


def find_key(rec: TagRecord, key: str) -> str | None:
    """Zusatzfeld in einer Datei über den Anzeigenamen finden (unabhängig vom Format)."""
    if not key.startswith(EXTRA) or key in rec.fields:
        return key if key in rec.fields else None
    want = label_of(key).casefold()
    for k in rec.fields:
        if k.startswith(EXTRA) and rec.labels.get(k, label_of(k)).casefold() == want:
            return k
    return None


def resolve_key(rec: TagRecord, key: str) -> str:
    """Schlüssel, unter dem ein Feld in dieser Datei steht bzw. gespeichert würde."""
    if not key.startswith(EXTRA):
        return key
    return find_key(rec, key) or (key if _native_key(rec.kind, key[len(EXTRA):]) else
                                  custom_key(rec.kind, label_of(key)))


_MP4_SORT = ("soar", "soaa", "soal", "sonm", "soco")


def _native_key(kind: str, raw: str) -> bool:
    """Schlüssel, die schon im Format der Datei angegeben sind (v1.2, z. B. für MusicBrainz)."""
    if kind == "id3":
        if raw.startswith("UFID:"):
            return True
        if len(raw) == 4 and raw.startswith("T") and raw != "TXXX":
            from mutagen import id3

            return hasattr(id3, raw)
        return False
    if kind == "mp4":
        return raw in _MP4_SORT
    return False


VALID_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-äöüÄÖÜß")


def valid_field_name(name: str) -> bool:
    return bool(name.strip()) and all(c in VALID_NAME_CHARS for c in name)


# ==== Schnappschuss für „Rückgängig“ (F-977) =====================================================
def snapshot(path: str, with_pictures: bool) -> tuple:
    """Kompletter Tag einer Datei (ohne Bilder, wenn sie nicht geändert werden), zum Wiederherstellen."""
    import copy

    audio = _open(path)
    kind, _codec = _kind(audio)
    tags = audio.tags
    if tags is None:
        return (kind, None, None)
    if kind == "id3":
        frames = [copy.deepcopy(f) for k, f in tags.items() if with_pictures or not k.startswith("APIC")]
        return (kind, frames, None)
    if kind == "vorbis":
        pairs = [(k, v) for k, v in tags if with_pictures or k.upper() != _VORBIS_PICTURE]
        pics = None
        if type(audio).__name__ == "FLAC" and with_pictures:
            pics = [copy.deepcopy(p) for p in audio.pictures]
        return (kind, pairs, pics)
    if kind == "mp4":
        return (kind, {k: copy.deepcopy(v) for k, v in tags.items() if with_pictures or k != "covr"}, None)
    if kind == "asf":
        return (kind, [(k, copy.deepcopy(v)) for k, v in tags.items()
                       if with_pictures or k != "WM/Picture"], None)
    return (kind, None, None)


def restore(path: str, snap: tuple) -> TagRecord:
    """Schreibt einen Schnappschuss zurück; Bilder bleiben unangetastet, wenn sie nicht darin sind."""
    kind, content, pics = snap
    audio = _open(path)
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    if kind == "id3":
        keep_pics = not any(f.FrameID == "APIC" for f in content or [])
        for k in list(tags.keys()):
            if not (keep_pics and k.startswith("APIC")):
                del tags[k]
        for f in content or []:
            tags.add(f)
        audio.save(v2_version=3)
    elif kind == "vorbis":
        has_pics = any(k.upper() == _VORBIS_PICTURE for k, _v in content or [])
        keep = [(k, v) for k, v in tags if k.upper() == _VORBIS_PICTURE and not has_pics]
        tags.clear()
        for k, v in keep + list(content or []):
            tags.append((k, v))
        if pics is not None:
            audio.clear_pictures()
            for p in pics:
                audio.add_picture(p)
        audio.save()
    elif kind == "mp4":
        covr = tags.get("covr") if "covr" not in (content or {}) else None
        tags.clear()
        tags.update(content or {})
        if covr:
            tags["covr"] = covr
        audio.save()
    elif kind == "asf":
        has_pics = any(k == "WM/Picture" for k, _v in content or [])
        keep = tags.get("WM/Picture") if not has_pics and "WM/Picture" in tags else None
        tags.clear()
        for k, v in content or []:
            tags[k] = v
        if keep:
            tags["WM/Picture"] = keep
        audio.save()
    return read_file(path)


def format_length(seconds: float) -> str:
    s = int(round(seconds))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


# Übliche Genres (ID3v1-Liste, Auszug) für die Auswahlliste (F-922)
STANDARD_GENRES = sorted({
    "Alternative", "Alt. Rock", "Ambient", "Blues", "Classic Rock", "Classical", "Country", "Dance", "Disco",
    "Electronic", "Folk", "Funk", "Gospel", "Grunge", "Hard Rock", "Heavy Metal", "Hip-Hop", "House", "Indie",
    "Instrumental", "Jazz", "Latin", "Metal", "New Age", "Oldies", "Opera", "Pop", "Punk", "R&B", "Rap",
    "Reggae", "Rock", "Rock & Roll", "Schlager", "Soul", "Soundtrack", "Techno", "Trance", "Volksmusik", "World",
    "Audiobook", "Speech", "Podcast", "Children's", "Christmas", "Comedy", "Chanson", "Swing", "Musical",
}, key=str.casefold)
