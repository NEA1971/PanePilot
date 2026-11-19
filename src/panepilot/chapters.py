"""Kapitel von Videos lesen, erzeugen, einlesen und speichern (v1.15, L-1500 ff.).

Lesen mit ffprobe (MKV und MP4), Schreiben bei MKV mit mkvpropedit direkt in der Datei,
bei MP4 über videoremux (neue Datei bzw. Original ersetzen).
"""

from __future__ import annotations

import json
import os
import random
import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .i18n import current_language, t

FILE_SUFFIXES = (".chapters.txt", ".chapters.xml", ".txt", ".xml")


@dataclass
class Chapter:
    start: float  # Sekunden
    name: str = ""


# --- Zeiten --------------------------------------------------------------------------------------------------
_TIME = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:[.,]\d+)?)\s*$")


def parse_time(text: str) -> float | None:
    """„01:02:03.5“, „1:02:03,500“, „12:30“ → Sekunden; None, wenn es keine Zeit ist."""
    m = _TIME.match(text or "")
    if not m:
        return None
    h, mnt, sec = m.groups()
    try:
        value = int(h or 0) * 3600 + int(mnt) * 60 + float(sec.replace(",", "."))
    except ValueError:
        return None
    if int(mnt) >= 60 and h is not None or float(sec.replace(",", ".")) >= 60:
        return None
    return value


def format_time(seconds: float, ms: bool = True) -> str:
    total = max(0, round(seconds * 1000))
    h, rest = divmod(total, 3600000)
    m, rest = divmod(rest, 60000)
    s, milli = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{milli:03d}" if ms else f"{h:02d}:{m:02d}:{s:02d}"


def short_time(seconds: float) -> str:
    """Für die Tabelle: Millisekunden nur, wenn nötig."""
    text = format_time(seconds)
    return text[:-4] if text.endswith(".000") else text


# --- Erzeugen ------------------------------------------------------------------------------------------------
def default_name(n: int) -> str:
    return t("chapters.default_name", n=f"{n:02d}")


def interval(duration: float, minutes: float) -> list[Chapter]:
    """Kapitel in festem Abstand, erstes bei 00:00 (L-1503)."""
    step = max(1.0, float(minutes)) * 60
    out, pos = [], 0.0
    while pos < max(duration, 1) - 1e-6 or not out:
        out.append(Chapter(pos, default_name(len(out) + 1)))
        pos += step
    return out


# --- Dateien einlesen (L-1505) -------------------------------------------------------------------------------
def _clean(name: str) -> str:
    name = (name or "").strip()
    if len(name) >= 2 and name[0] == name[-1] and name[0] in "\"'":
        name = name[1:-1].strip()
    for a, b in (("„", "“"), ("“", "”"), ("«", "»"), ("‚", "‘")):
        if name.startswith(a) and name.endswith(b):
            name = name[len(a):-len(b)].strip()
    return name


def parse_ogm(text: str) -> list[Chapter]:
    times: dict[str, float] = {}
    names: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"\s*CHAPTER(\d+)(NAME)?\s*=(.*)$", line, re.I)
        if not m:
            continue
        num, is_name, value = m.groups()
        if is_name:
            names[num.lstrip("0") or "0"] = _clean(value)
        else:
            sec = parse_time(value.strip())
            if sec is not None:
                times[num.lstrip("0") or "0"] = sec
    return [Chapter(times[k], names.get(k, "")) for k in sorted(times, key=int)]


def parse_list(text: str) -> list[Chapter]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        m = re.match(r"^(\S+)\s*[-–|;,\t ]?\s*(.*)$", line)
        if not m:
            continue
        sec = parse_time(m.group(1))
        if sec is not None:
            out.append(Chapter(sec, _clean(m.group(2))))
    return out


def _ns_time(text: str) -> float | None:
    """„00:12:30.500000000“ (Matroska) → Sekunden."""
    m = re.match(r"^\s*(\d+):(\d{2}):(\d{2})(?:\.(\d+))?\s*$", text or "")
    if not m:
        return parse_time(text or "")
    h, mnt, sec, frac = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + int(sec) + (float("0." + frac) if frac else 0.0)


def parse_xml(text: str) -> list[Chapter]:
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    edition = root.find(".//EditionEntry")
    atoms = (edition if edition is not None else root).findall("ChapterAtom")
    if not atoms:
        atoms = root.findall(".//ChapterAtom")
    out = []
    for atom in atoms:
        if (atom.findtext("ChapterFlagHidden") or "0").strip() == "1":
            continue
        sec = _ns_time(atom.findtext("ChapterTimeStart") or "")
        if sec is None:
            continue
        name = atom.findtext("ChapterDisplay/ChapterString") or ""
        out.append(Chapter(sec, _clean(name)))
    return out


def parse_text(text: str) -> list[Chapter]:
    text = text.lstrip("﻿")
    if text.lstrip().startswith("<"):
        return parse_xml(text)
    if re.search(r"^\s*CHAPTER\d+\s*=", text, re.I | re.M):
        return parse_ogm(text)
    return parse_list(text)


def read_file(path: str) -> list[Chapter]:
    with open(path, "rb") as fh:
        data = fh.read()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    try:
        return sorted(parse_text(text), key=lambda c: c.start)
    except ET.ParseError as exc:
        raise ValueError(str(exc)) from exc


def fit(chapters: list[Chapter], duration: float) -> tuple[list[Chapter], str]:
    """Leeres Schlusskapitel weg, Kapitel hinter dem Filmende weg; Warnung bei unpassender Länge (L-1505)."""
    chs = sorted(chapters, key=lambda c: c.start)
    end_mark = None
    if len(chs) > 1 and not chs[-1].name:
        end_mark = chs.pop().start
    warn = ""
    if duration > 0:
        beyond = [c for c in chs if c.start >= duration]
        chs = [c for c in chs if c.start < duration]
        if beyond:
            warn = t("chapters.warn_beyond", n=len(beyond), length=short_time(duration).split(".")[0])
        elif end_mark is not None and abs(end_mark - duration) > max(30.0, duration * 0.02):
            warn = t("chapters.warn_length", file=short_time(end_mark).split(".")[0],
                     length=short_time(duration).split(".")[0])
    for i, c in enumerate(chs, 1):
        if not c.name:
            c.name = default_name(i)
    return chs, warn


def candidates(video: str) -> list[str]:
    """Kapiteldateien mit gleichem Namen neben dem Video (L-1506)."""
    stem = os.path.splitext(video)[0]
    return [stem + s for s in FILE_SUFFIXES if os.path.isfile(stem + s)]


# --- Dateien schreiben (L-1507) ------------------------------------------------------------------------------
def to_ogm(chapters: list[Chapter]) -> str:
    lines = []
    for i, c in enumerate(chapters, 1):
        lines.append(f"CHAPTER{i:02d}={format_time(c.start)}")
        lines.append(f"CHAPTER{i:02d}NAME={c.name}")
    return "\n".join(lines) + "\n"


def to_xml(chapters: list[Chapter], lang: str = "und") -> str:
    root = ET.Element("Chapters")
    edition = ET.SubElement(root, "EditionEntry")
    rng = random.SystemRandom()
    for c in chapters:
        atom = ET.SubElement(edition, "ChapterAtom")
        ET.SubElement(atom, "ChapterUID").text = str(rng.randrange(1, 2 ** 63))
        ET.SubElement(atom, "ChapterTimeStart").text = format_time(c.start) + "000000"
        disp = ET.SubElement(atom, "ChapterDisplay")
        ET.SubElement(disp, "ChapterString").text = c.name
        ET.SubElement(disp, "ChapterLanguage").text = lang or "und"
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE Chapters SYSTEM "matroskachapters.dtd">\n' + \
        ET.tostring(root, encoding="unicode") + "\n"


def save_file(path: str, chapters: list[Chapter], lang: str = "und") -> None:
    text = to_xml(chapters, lang) if path.lower().endswith(".xml") else to_ogm(chapters)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def to_ffmetadata(chapters: list[Chapter], duration: float) -> str:
    def esc(s: str) -> str:
        return re.sub(r"([=;#\\\n])", r"\\\1", s)

    lines = [";FFMETADATA1"]
    chs = sorted(chapters, key=lambda c: c.start)
    for i, c in enumerate(chs):
        end = chs[i + 1].start if i + 1 < len(chs) else max(duration, c.start + 1)
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={round(c.start * 1000)}", f"END={round(end * 1000)}",
                  f"title={esc(c.name)}"]
    return "\n".join(lines) + "\n"


def chapter_language() -> str:
    """Sprache der Programmoberfläche als Matroska-Kürzel (L-1509)."""
    from . import opensubs

    code = (current_language() or "en").lower()
    code = {"frk": "de", "sxu": "de"}.get(code, code)
    return opensubs.to_mkv_lang(code.split("-")[0].split("_")[0])


# --- Videos --------------------------------------------------------------------------------------------------
@dataclass
class VideoChapters:
    path: str
    fmt: str  # "mkv" oder "mp4"
    duration: float
    chapters: list
    error: str = ""


def _ffprobe() -> str:
    from .videotags import ffprobe

    tool = ffprobe()
    if tool is None:
        raise OSError("ffprobe")
    return tool


def read(path: str) -> VideoChapters:
    from .videotags import _run

    fmt = "mkv" if path.lower().endswith((".mkv", ".webm")) else "mp4"
    try:
        proc = _run([_ffprobe(), "-v", "error", "-show_chapters", "-show_entries", "format=duration",
                     "-of", "json", path])
        if proc.returncode != 0:
            return VideoChapters(path, fmt, 0.0, [], (proc.stderr or "ffprobe").strip()[-300:])
        data = json.loads(proc.stdout or "{}")
    except (OSError, ValueError) as exc:
        return VideoChapters(path, fmt, 0.0, [], str(exc))
    try:
        duration = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    chs = []
    for c in data.get("chapters") or []:
        try:
            start = float(c.get("start_time") or 0)
        except (TypeError, ValueError):
            continue
        chs.append(Chapter(start, str((c.get("tags") or {}).get("title") or "")))
    return VideoChapters(path, fmt, duration, sorted(chs, key=lambda c: c.start))


def write_mkv(path: str, chapters: list[Chapter], lang: str | None = None) -> None:
    """Direkt in der Datei (L-1508); leere Liste löscht alle Kapitel."""
    from .videotags import _fail, _run, mkvpropedit

    tool = mkvpropedit()
    if tool is None:
        raise OSError("mkvpropedit")
    with tempfile.TemporaryDirectory(prefix="panepilot-") as tmp:
        if chapters:
            xml = os.path.join(tmp, "chapters.xml")
            with open(xml, "w", encoding="utf-8") as fh:
                fh.write(to_xml(sorted(chapters, key=lambda c: c.start), lang or chapter_language()))
            arg = xml
        else:
            arg = ""
        proc = _run([tool, path, "--chapters", arg], timeout=120)
        if proc.returncode not in (0, 1):
            raise _fail(proc, "mkvpropedit")
