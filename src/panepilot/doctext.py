"""Text aus Dokumenten für die Inhaltssuche (v1.20, L-2000).

PDF (pypdf, je Seite), Word/Excel/PowerPoint (DOCX, XLSX, PPTX) und LibreOffice (ODT, ODS, ODP).
Die alten Formate DOC, XLS und PPT werden nicht gelesen; eingescannte PDFs ohne Textebene liefern keinen Text.
pypdf statt pdfium, weil pdfium nicht threadsicher ist und gleichzeitig die Vorschaubilder zeichnet.
"""

from __future__ import annotations

import os
import re
import zipfile
import xml.etree.ElementTree as ET

PDF_EXT = {".pdf"}
OOXML_EXT = {".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm"}
ODF_EXT = {".odt", ".ods", ".odp", ".ott", ".ots", ".otp"}
DOC_EXT = PDF_EXT | OOXML_EXT | ODF_EXT
MAX_PART = 50 * 1000 * 1000  # entpackte Teile größer als das werden nicht gelesen (Zip-Bomben)
SNIPPET = 45  # Zeichen vor und nach der Fundstelle


def is_document(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in DOC_EXT


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_text(data: bytes, para: set[str], text: set[str], tab: set[str] = frozenset(),
              space: set[str] = frozenset()) -> str:
    """Text eines XML-Teils: Absätze werden zu Zeilen."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return ""
    out: list[str] = []
    count = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}c"

    def walk(el, in_text: bool) -> None:
        name = _local(el.tag)
        here = name in text
        if name in tab:
            out.append("\t")
        elif name in space:
            try:
                out.append(" " * max(1, int(el.get(count, "1"))))
            except ValueError:
                out.append(" ")
        elif here and el.text:
            out.append(el.text)
        for child in el:
            walk(child, here)
        if name in para:
            out.append("\n")
        if in_text and el.tail:
            out.append(el.tail)

    walk(root, False)
    return "".join(out)


def _zip_parts(path: str, pattern: str) -> list[tuple[str, bytes]]:
    rx = re.compile(pattern)
    out = []
    with zipfile.ZipFile(path) as zf:
        names = sorted((n for n in zf.namelist() if rx.fullmatch(n)), key=_natural)
        for n in names:
            info = zf.getinfo(n)
            if info.file_size > MAX_PART:
                continue
            out.append((n, zf.read(n)))
    return out


def _natural(name: str):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", name)]


def _ooxml(path: str) -> list[tuple[str, str]]:
    ext = os.path.splitext(path)[1].lower()
    if ext in (".docx", ".docm"):
        parts = _zip_parts(path, r"word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml")
        return [("", _xml_text(d, {"p"}, {"t"}, {"tab"})) for _n, d in parts]
    if ext in (".xlsx", ".xlsm"):
        # gemeinsame Texte + Inline-Texte + Zahlen der Zellen
        parts = _zip_parts(path, r"xl/sharedStrings\.xml|xl/worksheets/sheet\d+\.xml")
        out = []
        for name, data in parts:
            if name.endswith("sharedStrings.xml"):
                out.append(("", _xml_text(data, {"si"}, {"t"})))
            else:
                out.append(("", _xml_text(data, {"c"}, {"t", "v"})))
        return out
    parts = _zip_parts(path, r"ppt/slides/slide\d+\.xml|ppt/notesSlides/notesSlide\d+\.xml")
    return [("", _xml_text(d, {"p"}, {"t"})) for _n, d in parts]


def _odf_text(data: bytes) -> str:
    return _xml_text(data, {"p", "h"}, {"p", "h", "span", "a"}, {"tab"}, {"s"})


def _pdf(path: str, stop) -> list[tuple[str, str]]:
    try:
        from pypdf import PdfReader
    except Exception:  # noqa: BLE001 – ohne Bibliothek keine PDF-Suche
        return []
    import logging

    logging.getLogger("pypdf").setLevel(logging.ERROR)
    reader = PdfReader(path)
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                return []
        except Exception:  # noqa: BLE001
            return []
    out = []
    for i, page in enumerate(reader.pages, 1):
        if stop():
            break
        try:
            out.append((str(i), page.extract_text() or ""))
        except Exception:  # noqa: BLE001 – kaputte Seite überspringen
            continue
    return out


def pages(path: str, stop=lambda: False) -> list[tuple[str, str]]:
    """[(Seitenangabe oder "", Text)] – leer, wenn sich nichts lesen lässt."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in PDF_EXT:
            return _pdf(path, stop)
        if ext in OOXML_EXT:
            return _ooxml(path)
        if ext in ODF_EXT:
            return [("", _odf_text(d)) for _n, d in _zip_parts(path, r"content\.xml|styles\.xml")]
    except Exception:  # noqa: BLE001 – kaputte oder fremde Datei: kein Treffer
        return []
    return []


def snippet(text: str, m: re.Match) -> str:
    """Fundstelle mit etwas Text davor und danach, Leerraum zusammengefasst."""
    start, end = m.start(), m.end()
    before = text[max(0, start - SNIPPET * 2):start]
    after = text[end:end + SNIPPET * 2]
    before = re.sub(r"\s+", " ", before)[-SNIPPET:]
    after = re.sub(r"\s+", " ", after)[:SNIPPET]
    hit = re.sub(r"\s+", " ", text[start:end])
    lead = "…" if start > 0 and before else ""
    tail = "…" if end < len(text) and after else ""
    return f"{lead}{before}»{hit}«{after}{tail}".strip()


def find(path: str, rx: re.Pattern, stop=lambda: False) -> tuple[str, str] | None:
    """Erste Fundstelle im Dokument: (Seitenangabe oder "", Ausschnitt) oder None."""
    for label, text in pages(path, stop):
        if stop():
            return None
        m = rx.search(text)
        if m is not None:
            return label, snippet(text, m)
    return None
