"""Metadaten von Fotos lesen und schreiben (v1.4) – EXIF, IPTC und XMP über exiv2 (pyexiv2).

Einheitliche Sicht wie bei der Musik (tags.TagRecord): feste Feldnamen (FIELDS) und eigene Felder als
„x:Xmp.panepilot.<Name>“. Geschrieben wird jedes Feld an alle üblichen Stellen (wie digiKam/exiftool),
damit andere Programme es finden. Kamera- und Belichtungsdaten sowie GPS lassen sich nur entfernen.

HEIC/HEIF kann exiv2 nicht schreiben; ist exiftool installiert, schreibt PanePilot HEIC damit.
RAW-Dateien werden nur gelesen.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
from fractions import Fraction

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".jpe", ".png", ".tif", ".tiff", ".webp", ".heic", ".heif"}
RAW_EXTENSIONS = {".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".dng", ".orf", ".rw2", ".raf",
                  ".pef", ".srw", ".3fr", ".erf", ".kdc", ".mrw", ".x3f"}
HEIF_EXTENSIONS = {".heic", ".heif"}
ALL_EXTENSIONS = PHOTO_EXTENSIONS | RAW_EXTENSIONS

EDITABLE = ("title", "description", "keywords", "rating", "author", "copyright", "datetaken")
REMOVE_ONLY = ("make", "model", "lens", "exposure", "aperture", "iso", "focal", "flash", "orientation",
               "gpslat", "gpslon", "gpsalt")
FIELDS = EDITABLE + REMOVE_ONLY
STANDARD_FIELDS = FIELDS  # im Feld-Editor weder löschbar noch umbenennbar

NS_URI = "http://ns.panepilot.app/1.0/"
NS_PREFIX = "panepilot"
CUSTOM_PREFIX = f"Xmp.{NS_PREFIX}."
X_DEFAULT = 'lang="x-default"'

# Wohin ein Feld geschrieben wird – die erste Quelle mit Wert gilt beim Lesen
WRITE_KEYS = {
    "title": ("Xmp.dc.title", "Iptc.Application2.ObjectName"),
    "description": ("Xmp.dc.description", "Exif.Image.ImageDescription", "Iptc.Application2.Caption"),
    "keywords": ("Xmp.dc.subject", "Iptc.Application2.Keywords"),
    "rating": ("Xmp.xmp.Rating", "Exif.Image.Rating"),
    "author": ("Xmp.dc.creator", "Exif.Image.Artist", "Iptc.Application2.Byline"),
    "copyright": ("Xmp.dc.rights", "Exif.Image.Copyright", "Iptc.Application2.Copyright"),
    "datetaken": ("Exif.Photo.DateTimeOriginal", "Xmp.exif.DateTimeOriginal", "Xmp.photoshop.DateCreated"),
    "make": ("Exif.Image.Make", "Xmp.tiff.Make"),
    "model": ("Exif.Image.Model", "Xmp.tiff.Model"),
    "lens": ("Exif.Photo.LensModel", "Xmp.aux.Lens", "Xmp.exifEX.LensModel"),
    "exposure": ("Exif.Photo.ExposureTime", "Xmp.exif.ExposureTime"),
    "aperture": ("Exif.Photo.FNumber", "Xmp.exif.FNumber"),
    "iso": ("Exif.Photo.ISOSpeedRatings", "Xmp.exif.ISOSpeedRatings"),
    "focal": ("Exif.Photo.FocalLength", "Xmp.exif.FocalLength"),
    "flash": ("Exif.Photo.Flash",),
    "orientation": ("Exif.Image.Orientation", "Xmp.tiff.Orientation"),
    "gpslat": ("Exif.GPSInfo.GPSLatitude", "Exif.GPSInfo.GPSLatitudeRef", "Xmp.exif.GPSLatitude"),
    "gpslon": ("Exif.GPSInfo.GPSLongitude", "Exif.GPSInfo.GPSLongitudeRef", "Xmp.exif.GPSLongitude"),
    "gpsalt": ("Exif.GPSInfo.GPSAltitude", "Exif.GPSInfo.GPSAltitudeRef", "Xmp.exif.GPSAltitude"),
}
# Nur diese Quellen werden beim Lesen ausgewertet (die übrigen sind Mitläufer beim Schreiben/Löschen)
READ_KEYS = {
    "title": ("Xmp.dc.title", "Iptc.Application2.ObjectName", "Exif.Image.XPTitle"),
    "description": ("Xmp.dc.description", "Exif.Image.ImageDescription", "Iptc.Application2.Caption"),
    "keywords": ("Xmp.dc.subject", "Iptc.Application2.Keywords", "Exif.Image.XPKeywords"),
    "rating": ("Xmp.xmp.Rating", "Exif.Image.Rating"),
    "author": ("Xmp.dc.creator", "Exif.Image.Artist", "Iptc.Application2.Byline"),
    "copyright": ("Xmp.dc.rights", "Exif.Image.Copyright", "Iptc.Application2.Copyright"),
    "datetaken": ("Exif.Photo.DateTimeOriginal", "Exif.Image.DateTimeOriginal", "Xmp.exif.DateTimeOriginal",
                  "Xmp.photoshop.DateCreated", "Exif.Image.DateTime"),
    "make": ("Exif.Image.Make", "Xmp.tiff.Make"),
    "model": ("Exif.Image.Model", "Xmp.tiff.Model"),
    "lens": ("Exif.Photo.LensModel", "Xmp.aux.Lens", "Xmp.exifEX.LensModel"),
    "exposure": ("Exif.Photo.ExposureTime", "Xmp.exif.ExposureTime"),
    "aperture": ("Exif.Photo.FNumber", "Xmp.exif.FNumber"),
    "iso": ("Exif.Photo.ISOSpeedRatings", "Exif.Photo.PhotographicSensitivity", "Xmp.exif.ISOSpeedRatings"),
    "focal": ("Exif.Photo.FocalLength", "Xmp.exif.FocalLength"),
    "flash": ("Exif.Photo.Flash",),
    "orientation": ("Exif.Image.Orientation", "Xmp.tiff.Orientation"),
    "gpslat": ("Exif.GPSInfo.GPSLatitude",),
    "gpslon": ("Exif.GPSInfo.GPSLongitude",),
    "gpsalt": ("Exif.GPSInfo.GPSAltitude",),
}
# Beim Entfernen zusätzlich löschen (gleichbedeutende Felder anderer Programme)
EXTRA_REMOVE = {
    "datetaken": ("Exif.Image.DateTimeOriginal",),
    "title": ("Exif.Image.XPTitle",),
    "keywords": ("Exif.Image.XPKeywords",),
    "iso": ("Exif.Photo.PhotographicSensitivity",),
}
MANAGED = sorted({k for keys in list(WRITE_KEYS.values()) + list(EXTRA_REMOVE.values()) for k in keys}
                 | {"Exif.Image.DateTimeOriginal", "Exif.Image.XPTitle", "Exif.Image.XPKeywords",
                    "Exif.Photo.PhotographicSensitivity"})


def is_photo(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in ALL_EXTENSIONS


def is_raw(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in RAW_EXTENSIONS


def is_heif(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in HEIF_EXTENSIONS


def exiftool() -> str | None:
    return shutil.which("exiftool")


def writable(path: str) -> bool:
    if is_raw(path):
        return False
    if is_heif(path):
        return exiftool() is not None
    return True


def format_name(path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if f".{ext}" in RAW_EXTENSIONS:
        return f"RAW ({ext.upper()})"
    return {"jpg": "JPEG", "jpeg": "JPEG", "jpe": "JPEG", "tif": "TIFF", "tiff": "TIFF", "webp": "WebP",
            "heic": "HEIC", "heif": "HEIF", "png": "PNG"}.get(ext, ext.upper())


_ns_done = False


def _pyexiv2():
    global _ns_done
    import pyexiv2

    if not _ns_done:
        try:
            pyexiv2.registerNs(NS_URI, NS_PREFIX)
        except Exception:  # noqa: BLE001 – schon registriert
            pass
        try:
            pyexiv2.set_log_level(4)  # keine Warnungen auf der Konsole
        except Exception:  # noqa: BLE001
            pass
        _ns_done = True
    return pyexiv2


# --- Werte umwandeln ----------------------------------------------------------------------------------
def _text(value) -> str:
    """Rohwert von exiv2 als Text (Sprachvarianten, Listen)."""
    if value is None:
        return ""
    if isinstance(value, dict):
        if X_DEFAULT in value:
            return str(value[X_DEFAULT]).strip()
        return str(next(iter(value.values()), "")).strip()
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v).strip() for v in value if str(v).strip())
    text = str(value).strip()
    m = re.match(r'^lang="[^"]*"\s+(.*)$', text, re.S)
    return m.group(1).strip() if m else text


def _ratio(text: str) -> float | None:
    try:
        return float(Fraction(str(text).strip().split()[0]))
    except (ValueError, ZeroDivisionError, IndexError):
        try:
            return float(text)
        except (TypeError, ValueError):
            return None


def _dms(text: str) -> float | None:
    """„10/1 18/1 3000/100“ (Grad Minuten Sekunden) bzw. XMP „10,18.5N“ → Dezimalgrad."""
    text = str(text).strip()
    m = re.match(r"^(\d+),([\d.]+)([NSEW])$", text)
    if m:
        deg = int(m.group(1)) + float(m.group(2)) / 60
        return -deg if m.group(3) in "SW" else deg
    parts = text.split()
    if not parts:
        return None
    vals = [_ratio(p) for p in parts]
    if any(v is None for v in vals):
        return None
    deg = vals[0] + (vals[1] / 60 if len(vals) > 1 else 0) + (vals[2] / 3600 if len(vals) > 2 else 0)
    return deg


def exif_date(text: str) -> str:
    """„2026:11:08 15:00:12“ bzw. XMP „2026-11-08T15:00:12+01:00“ → „2026-11-08 15:00:12“."""
    text = str(text).strip()
    m = re.match(r"^(\d{4})[:-](\d{2})[:-](\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?", text)
    if not m:
        return text
    y, mo, d, h, mi, s = m.groups()
    if h is None:
        return f"{y}-{mo}-{d}"
    return f"{y}-{mo}-{d} {h}:{mi}:{s or '00'}"


def parse_date(text: str) -> dt.datetime | None:
    """Aufnahmedatum aus der Anzeige (oder deutschen Schreibweise) lesen."""
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
                "%d.%m.%Y", "%Y:%m:%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _display(field: str, raw: str, exif: dict) -> str:
    if raw == "":
        return ""
    if field == "datetaken":
        return exif_date(raw)
    if field == "exposure":
        v = _ratio(raw)
        if v is None or v <= 0:
            return raw
        return f"1/{round(1 / v)} s" if v < 1 else f"{v:g} s"
    if field == "aperture":
        v = _ratio(raw)
        return f"f/{v:.1f}".replace(".0", "") if v else raw
    if field == "focal":
        v = _ratio(raw)
        return f"{v:g} mm" if v else raw
    if field == "flash":
        try:
            n = int(str(raw).split()[0])
        except ValueError:
            return raw
        from .i18n import t

        return t("photo.flash_on") if n & 1 else t("photo.flash_off")
    if field in ("gpslat", "gpslon"):
        v = _dms(raw)
        if v is None:
            return raw
        ref = exif.get("Exif.GPSInfo.GPSLatitudeRef" if field == "gpslat" else "Exif.GPSInfo.GPSLongitudeRef", "")
        if str(ref).strip() in ("S", "W"):
            v = -v
        return f"{v:.6f}"
    if field == "gpsalt":
        v = _ratio(raw)
        if v is None:
            return raw
        if str(exif.get("Exif.GPSInfo.GPSAltitudeRef", "0")).strip() == "1":
            v = -v
        return f"{v:.1f} m"
    return raw


# --- Lesen ---------------------------------------------------------------------------------------------
def read_file(path: str):
    from . import tags as tg

    rec = tg.TagRecord(path)
    rec.kind = "photo"
    rec.codec = format_name(path)
    try:
        st = os.stat(path)
        rec.size, rec.mtime = st.st_size, st.st_mtime
        exif, iptc, xmp, (w, h) = _read_raw(path)
    except Exception as exc:  # noqa: BLE001 – kaputte Datei als Fehler anzeigen
        rec.error = str(exc) or type(exc).__name__
        return rec
    rec.width, rec.height = w, h
    merged = {**exif, **iptc, **xmp}
    for name, keys in READ_KEYS.items():
        for key in keys:
            value = _text(merged.get(key))
            if value:
                rec.fields[name] = _display(name, value, exif)
                rec.sources[name] = key
                break
    for key, value in xmp.items():
        if key.startswith(CUSTOM_PREFIX):
            k = tg.EXTRA + key
            rec.fields[k] = _text(value)
            rec.labels[k] = key[len(CUSTOM_PREFIX):]
    if not writable(path):
        rec.readonly = set(FIELDS) | {k for k in rec.fields if k.startswith(tg.EXTRA)} | {"*"}
    else:
        rec.removable = set(REMOVE_ONLY)
        if is_heif(path):  # exiftool kennt den eigenen XMP-Bereich nicht
            rec.readonly = {k for k in rec.fields if k.startswith(tg.EXTRA)} | {"x:*"}
    return rec


def _read_raw(path: str):
    pyexiv2 = _pyexiv2()
    img = pyexiv2.Image(path)
    try:
        exif = _safe(img.read_exif)
        iptc = _safe(img.read_iptc)
        xmp = _safe(img.read_xmp)
        try:
            size = (int(img.get_pixel_width()), int(img.get_pixel_height()))
        except Exception:  # noqa: BLE001
            size = (0, 0)
    finally:
        img.close()
    if size == (0, 0) or size[0] <= 0:
        size = _qt_size(path)
    return exif, iptc, xmp, size


def _safe(fn) -> dict:
    try:
        return fn() or {}
    except Exception:  # noqa: BLE001 – einzelne Bereiche dürfen fehlen oder kaputt sein
        return {}


def _qt_size(path: str) -> tuple[int, int]:
    from PySide6.QtGui import QImageReader

    reader = QImageReader(path)
    s = reader.size()
    return (s.width(), s.height()) if s.isValid() else (0, 0)


# --- Schreiben -----------------------------------------------------------------------------------------
def _raw_changes(rec, changes: dict) -> dict:
    """Felder → Rohschlüssel von exiv2 (Wert None = löschen)."""
    from . import tags as tg

    out: dict = {}
    jpeg_tiff = os.path.splitext(rec.path)[1].lower() in (".jpg", ".jpeg", ".jpe", ".tif", ".tiff")
    for field, value in changes.items():
        if field.startswith(tg.EXTRA):
            out[field[len(tg.EXTRA):]] = value
            continue
        keys = WRITE_KEYS.get(field)
        if not keys:
            continue
        if value is None or value == "":
            for k in keys + EXTRA_REMOVE.get(field, ()):
                out[k] = None
            continue
        if field in REMOVE_ONLY:
            continue  # nur entfernen erlaubt
        for k in keys:
            if k.startswith("Iptc.") and not jpeg_tiff:
                continue
            out[k] = _raw_value(field, k, value)
            if out[k] is _SKIP:
                del out[k]
    return out


_SKIP = object()


def _raw_value(field: str, key: str, value: str):
    if field == "keywords":
        words = [w.strip() for w in re.split(r"[;,]", value) if w.strip()]
        return words
    if field == "author":
        return [value] if key == "Xmp.dc.creator" else (value if not key.startswith("Iptc.") else [value])
    if field in ("title", "description", "copyright") and key.startswith("Xmp."):
        return {X_DEFAULT: value}
    if field == "rating":
        try:
            n = max(0, min(5, int(round(float(value.replace(",", "."))))))
        except ValueError:
            return _SKIP
        return str(n)
    if field == "datetaken":
        when = parse_date(value)
        if when is None:
            raise ValueError(f"{value}: date?")
        if key.startswith("Exif."):
            return when.strftime("%Y:%m:%d %H:%M:%S")
        return when.strftime("%Y-%m-%dT%H:%M:%S")
    return value


def write_file(rec, changes: dict):
    """Schreibt die Änderungen und liefert den neu gelesenen Stand. OSError/ValueError bei Fehlern."""
    if not writable(rec.path):
        raise OSError("read-only format")
    raw = _raw_changes(rec, changes)
    if raw:
        write_raw(rec.path, raw)
    return read_file(rec.path)


def write_raw(path: str, raw: dict) -> None:
    if is_heif(path):
        _write_exiftool(path, raw)
        return
    pyexiv2 = _pyexiv2()
    exif = {k: v for k, v in raw.items() if k.startswith("Exif.")}
    iptc = {k: v for k, v in raw.items() if k.startswith("Iptc.")}
    xmp = {k: v for k, v in raw.items() if k.startswith("Xmp.")}
    img = pyexiv2.Image(path)
    try:
        current = {**_safe(img.read_exif), **_safe(img.read_iptc), **_safe(img.read_xmp)}
        # nur löschen, was es gibt (exiv2 mag kein Löschen fehlender Schlüssel nicht bei allen Formaten)
        exif = {k: v for k, v in exif.items() if v is not None or k in current}
        iptc = {k: v for k, v in iptc.items() if v is not None or k in current}
        xmp = {k: v for k, v in xmp.items() if v is not None or k in current}
        if exif:
            img.modify_exif(exif)
        if iptc:
            img.modify_iptc(iptc)
        if xmp:
            img.modify_xmp(xmp)
    except Exception as exc:  # noqa: BLE001
        raise OSError(str(exc) or type(exc).__name__) from exc
    finally:
        img.close()


# exiv2-Schlüssel → exiftool-Name (für HEIC)
_EXIFTOOL = {
    "Xmp.dc.title": "XMP-dc:Title", "Xmp.dc.description": "XMP-dc:Description", "Xmp.dc.subject": "XMP-dc:Subject",
    "Xmp.xmp.Rating": "XMP-xmp:Rating", "Xmp.dc.creator": "XMP-dc:Creator", "Xmp.dc.rights": "XMP-dc:Rights",
    "Exif.Image.ImageDescription": "EXIF:ImageDescription", "Exif.Image.Rating": "EXIF:Rating",
    "Exif.Image.Artist": "EXIF:Artist", "Exif.Image.Copyright": "EXIF:Copyright",
    "Exif.Photo.DateTimeOriginal": "EXIF:DateTimeOriginal", "Xmp.exif.DateTimeOriginal": "XMP-exif:DateTimeOriginal",
    "Xmp.photoshop.DateCreated": "XMP-photoshop:DateCreated", "Exif.Image.Make": "EXIF:Make",
    "Exif.Image.Model": "EXIF:Model", "Xmp.tiff.Make": "XMP-tiff:Make", "Xmp.tiff.Model": "XMP-tiff:Model",
    "Exif.Photo.LensModel": "EXIF:LensModel", "Xmp.aux.Lens": "XMP-aux:Lens", "Xmp.exifEX.LensModel": "XMP-exifEX:LensModel",
    "Exif.Photo.ExposureTime": "EXIF:ExposureTime", "Xmp.exif.ExposureTime": "XMP-exif:ExposureTime",
    "Exif.Photo.FNumber": "EXIF:FNumber", "Xmp.exif.FNumber": "XMP-exif:FNumber",
    "Exif.Photo.ISOSpeedRatings": "EXIF:ISO", "Xmp.exif.ISOSpeedRatings": "XMP-exif:ISO",
    "Exif.Photo.PhotographicSensitivity": "EXIF:ISO",
    "Exif.Photo.FocalLength": "EXIF:FocalLength", "Xmp.exif.FocalLength": "XMP-exif:FocalLength",
    "Exif.Photo.Flash": "EXIF:Flash", "Exif.Image.Orientation": "EXIF:Orientation",
    "Xmp.tiff.Orientation": "XMP-tiff:Orientation",
    "Exif.GPSInfo.GPSLatitude": "EXIF:GPSLatitude", "Exif.GPSInfo.GPSLatitudeRef": "EXIF:GPSLatitudeRef",
    "Exif.GPSInfo.GPSLongitude": "EXIF:GPSLongitude", "Exif.GPSInfo.GPSLongitudeRef": "EXIF:GPSLongitudeRef",
    "Exif.GPSInfo.GPSAltitude": "EXIF:GPSAltitude", "Exif.GPSInfo.GPSAltitudeRef": "EXIF:GPSAltitudeRef",
    "Xmp.exif.GPSLatitude": "XMP-exif:GPSLatitude", "Xmp.exif.GPSLongitude": "XMP-exif:GPSLongitude",
    "Xmp.exif.GPSAltitude": "XMP-exif:GPSAltitude", "Exif.Image.DateTimeOriginal": "IFD0:DateTimeOriginal",
    "Exif.Image.XPTitle": "EXIF:XPTitle", "Exif.Image.XPKeywords": "EXIF:XPKeywords",
}


def _write_exiftool(path: str, raw: dict) -> None:
    tool = exiftool()
    if tool is None:
        raise OSError("exiftool")
    args = [tool, "-overwrite_original", "-n", "-charset", "filename=utf8", "-charset", "utf8"]
    for key, value in raw.items():
        name = _EXIFTOOL.get(key)
        if name is None:
            continue
        if value is None:
            args.append(f"-{name}=")
        elif isinstance(value, list):
            args.append(f"-{name}=")
            args += [f"-{name}+={v}" for v in value]
        else:
            text = _text(value) if isinstance(value, dict) else str(value)
            if key.startswith("Exif.") and re.match(r"^\d{4}:\d\d:\d\d \d\d:\d\d:\d\d$", text):
                pass
            elif key.startswith("Exif.GPSInfo.GPSL") and not key.endswith("Ref"):
                v = _dms(text)
                text = f"{v}" if v is not None else text
            elif key in ("Exif.Photo.ExposureTime", "Exif.Photo.FNumber", "Exif.Photo.FocalLength",
                         "Exif.GPSInfo.GPSAltitude"):
                v = _ratio(text)
                text = f"{v}" if v is not None else text
            args.append(f"-{name}={text}")
    args.append(path)
    from .util import child_environment

    pe = child_environment()
    env = {k: pe.value(k) for k in pe.keys()}
    proc = subprocess.run(args, capture_output=True, text=True, env=env or None, timeout=60, check=False)
    if proc.returncode != 0:
        raise OSError((proc.stderr or proc.stdout or "exiftool").strip().splitlines()[-1])


# --- Rückgängig ------------------------------------------------------------------------------------------
def snapshot(path: str) -> tuple:
    """Alle von PanePilot verwalteten Rohwerte (klein, ohne Bilddaten)."""
    exif, iptc, xmp, _size = _read_raw(path)
    merged = {**exif, **iptc, **xmp}
    keep = {k: merged[k] for k in MANAGED if k in merged}
    keep.update({k: v for k, v in xmp.items() if k.startswith(CUSTOM_PREFIX)})
    if "Exif.GPSInfo.GPSLatitudeRef" in exif:
        keep["Exif.GPSInfo.GPSLatitudeRef"] = exif["Exif.GPSInfo.GPSLatitudeRef"]
    return ("photo", keep, None)


def restore(path: str, snap: tuple):
    _kind, keep, _p = snap
    exif, iptc, xmp, _size = _read_raw(path)
    now = {**exif, **iptc, **xmp}
    raw: dict = {}
    managed = set(MANAGED) | {k for k in now if k.startswith(CUSTOM_PREFIX)} | set(keep)
    for k in managed:
        if k in keep:
            if now.get(k) != keep[k]:
                raw[k] = keep[k]
        elif k in now:
            raw[k] = None
    if raw:
        write_raw(path, raw)
    return read_file(path)


# --- Vorschaubild ----------------------------------------------------------------------------------------
def preview(path: str, size: int = 216):
    """Verkleinertes Bild (QImage) – richtig gedreht; None, wenn es keins gibt."""
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QImage, QImageReader

    img = None
    if not is_heif(path) and not is_raw(path):
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        s = reader.size()
        if s.isValid() and s.width() > 0:
            reader.setScaledSize(s.scaled(QSize(size * 2, size * 2), Qt.AspectRatioMode.KeepAspectRatio))
        img = reader.read()
        if img.isNull():
            img = None
    elif is_heif(path):
        img = _heif_preview(path, size * 2)
    if img is None:
        img = _exif_thumbnail(path)
    if img is None or img.isNull():
        return None
    return img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation) \
        if max(img.width(), img.height()) > size else QImage(img)


def _heif_preview(path: str, size: int):
    try:
        import pillow_heif
        from PIL import Image, ImageOps

        pillow_heif.register_heif_opener()
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((size, size))
            return _pil_to_qimage(im)
    except Exception:  # noqa: BLE001
        return None


def _exif_thumbnail(path: str):
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QImage

    try:
        pyexiv2 = _pyexiv2()
        img = pyexiv2.Image(path)
        try:
            data = img.read_thumbnail()
        finally:
            img.close()
    except Exception:  # noqa: BLE001
        return None
    if not data:
        return None
    q = QImage.fromData(QByteArray(bytes(data)))
    return None if q.isNull() else q


def _pil_to_qimage(im):
    from PySide6.QtGui import QImage

    im = im.convert("RGBA")
    data = im.tobytes("raw", "RGBA")
    q = QImage(data, im.width, im.height, im.width * 4, QImage.Format.Format_RGBA8888)
    return q.copy()


def map_url(rec) -> str | None:
    """Link zu OpenStreetMap, wenn das Foto eine Position hat."""
    try:
        lat = float(rec.fields.get("gpslat", ""))
        lon = float(rec.fields.get("gpslon", ""))
    except ValueError:
        return None
    return f"https://www.openstreetmap.org/?mlat={lat:.6f}&mlon={lon:.6f}#map=16/{lat:.6f}/{lon:.6f}"
