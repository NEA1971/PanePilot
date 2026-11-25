"""Dokumente gegliedert lesen (v2.7): LibreOffice (.odt/.ods/.odp), Microsoft (.docx/.xlsx/.pptx) und PDF.

Für die Schnellansicht (L-3704) und den Dateivergleich (L-3732): Text, Tabellen je Blatt, Folien/Seiten.
Nur Lesen, keine Formatierung, keine Bilder. (Die flache Variante für die Inhaltssuche steht in doctext.py.)
"""

from __future__ import annotations

import os
import re
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

ROW_LIMIT = 500
COL_LIMIT = 200
ZIP_MEMBER_LIMIT = 50 * 1000 * 1000  # entpackte XML-Größe, gegen Zip-Bomben

WRITER = (".odt", ".ott", ".docx", ".docm", ".dotx")
CALC = (".ods", ".ots", ".xlsx", ".xlsm", ".xltx")
IMPRESS = (".odp", ".otp", ".pptx", ".pptm", ".potx")
PDF = (".pdf",)
SUPPORTED = WRITER + CALC + IMPRESS + PDF

_NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def _q(prefix: str, name: str) -> str:
    return f"{{{_NS[prefix]}}}{name}"


@dataclass
class Document:
    kind: str  # "text", "sheets", "slides" (auch PDF-Seiten)
    text: str = ""
    sheets: list[tuple[str, list[list[str]]]] = field(default_factory=list)
    slides: list[str] = field(default_factory=list)
    truncated: bool = False


def supported(path: str) -> bool:
    return path.lower().endswith(SUPPORTED)


def _xml(z: zipfile.ZipFile, name: str):
    if z.getinfo(name).file_size > ZIP_MEMBER_LIMIT:
        raise ValueError("too large")
    return ET.fromstring(z.read(name))


# --- OpenDocument -------------------------------------------------------------------------------------------
def _odf_text(el) -> str:
    """Text eines Absatzes mit Leerzeichen (text:s), Tabulatoren und Zeilenumbrüchen."""
    parts = [el.text or ""]
    for child in el:
        tag = child.tag
        if tag == _q("text", "s"):
            try:
                parts.append(" " * int(child.get(_q("text", "c"), "1") or 1))
            except ValueError:
                parts.append(" ")
        elif tag == _q("text", "tab"):
            parts.append("\t")
        elif tag == _q("text", "line-break"):
            parts.append("\n")
        elif tag in (_q("text", "note"), _q("office", "annotation")):
            pass
        else:
            parts.append(_odf_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _odf_paragraphs(root) -> list[str]:
    out = []
    for el in root.iter():
        if el.tag in (_q("text", "p"), _q("text", "h")):
            out.append(_odf_text(el))
    return out


def _int(value, default: int = 1) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def _odt(z) -> Document:
    body = _xml(z, "content.xml").find(_q("office", "body"))
    return Document("text", "\n".join(_odf_paragraphs(body)) if body is not None else "")


def _ods(z) -> Document:
    doc = Document("sheets")
    root = _xml(z, "content.xml")
    for table in root.iter(_q("table", "table")):
        rows: list[list[str]] = []
        for row in table.iter(_q("table", "table-row")):
            cells: list[str] = []
            for cell in row:
                if cell.tag not in (_q("table", "table-cell"), _q("table", "covered-table-cell")):
                    continue
                value = "\n".join(_odf_text(p) for p in cell.findall(_q("text", "p")))
                repeat = _int(cell.get(_q("table", "number-columns-repeated"), "1"))
                cells.extend([value] * min(repeat, COL_LIMIT - len(cells)))
                if len(cells) >= COL_LIMIT:
                    break
            while cells and not cells[-1]:
                cells.pop()
            repeat = _int(row.get(_q("table", "number-rows-repeated"), "1"))
            for _ in range(min(repeat, ROW_LIMIT + 1 - len(rows))):
                rows.append(list(cells))
            if len(rows) > ROW_LIMIT:
                rows = rows[:ROW_LIMIT]
                if any(any(c for c in r) for r in rows[-5:]):
                    doc.truncated = True
                break
        while rows and not any(rows[-1]):
            rows.pop()
        doc.sheets.append((table.get(_q("table", "name"), "") or str(len(doc.sheets) + 1), rows))
    return doc


def _odp(z) -> Document:
    doc = Document("slides")
    for page in _xml(z, "content.xml").iter(_q("draw", "page")):
        doc.slides.append("\n".join(p for p in _odf_paragraphs(page) if p.strip()))
    return doc


# --- Office Open XML ----------------------------------------------------------------------------------------
def _docx(z) -> Document:
    root = _xml(z, "word/document.xml")
    paras = []
    for p in root.iter(_q("w", "p")):
        parts = []
        for el in p.iter():
            if el.tag == _q("w", "t"):
                parts.append(el.text or "")
            elif el.tag == _q("w", "tab"):
                parts.append("\t")
            elif el.tag in (_q("w", "br"), _q("w", "cr")):
                parts.append("\n")
        paras.append("".join(parts))
    return Document("text", "\n".join(paras))


def _rels(z, name: str) -> dict[str, str]:
    try:
        root = _xml(z, name)
    except KeyError:
        return {}
    return {r.get("Id"): r.get("Target", "") for r in root.iter(_q("rel", "Relationship"))}


def _col_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if not ch.isalpha():
            break
        n = n * 26 + (ord(ch.upper()) - 64)
    return max(n - 1, 0)


def _xlsx(z) -> Document:
    doc = Document("sheets")
    shared: list[str] = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in _xml(z, "xl/sharedStrings.xml").iter(_q("s", "si")):
            shared.append("".join(x.text or "" for x in si.iter(_q("s", "t"))))
    rels = _rels(z, "xl/_rels/workbook.xml.rels")
    for sheet in _xml(z, "xl/workbook.xml").iter(_q("s", "sheet")):
        target = rels.get(sheet.get(_q("r", "id")), "").lstrip("/")
        path = target if target.startswith("xl/") else "xl/" + target
        rows: list[list[str]] = []
        try:
            root = _xml(z, path)
        except KeyError:
            doc.sheets.append((sheet.get("name", ""), rows))
            continue
        for row in root.iter(_q("s", "row")):
            r = _int(row.get("r"), len(rows) + 1) - 1
            if r >= ROW_LIMIT:
                doc.truncated = True
                break
            while len(rows) < r:
                rows.append([])
            cells: list[str] = []
            for c in row.iter(_q("s", "c")):
                col = _col_index(c.get("r", "")) if c.get("r") else len(cells)
                if col >= COL_LIMIT:
                    break
                kind = c.get("t", "")
                v = c.find(_q("s", "v"))
                if kind == "inlineStr":
                    value = "".join(x.text or "" for x in c.iter(_q("s", "t")))
                elif kind == "s" and v is not None:
                    try:
                        value = shared[int(v.text or "0")]
                    except (ValueError, IndexError):
                        value = ""
                elif kind == "b" and v is not None:
                    value = "TRUE" if (v.text or "") == "1" else "FALSE"
                else:
                    value = v.text if v is not None and v.text else ""
                while len(cells) < col:
                    cells.append("")
                cells.append(value)
            while cells and not cells[-1]:
                cells.pop()
            rows.append(cells)
        while rows and not any(rows[-1]):
            rows.pop()
        doc.sheets.append((sheet.get("name", ""), rows))
    return doc


def _pptx(z) -> Document:
    doc = Document("slides")
    names = set(n for n in z.namelist() if re.match(r"^ppt/slides/slide\d+\.xml$", n))
    order = []
    rels = _rels(z, "ppt/_rels/presentation.xml.rels")
    try:
        for sid in _xml(z, "ppt/presentation.xml").iter(_q("p", "sldId")):
            name = "ppt/" + rels.get(sid.get(_q("r", "id")), "").lstrip("/").removeprefix("ppt/")
            if name in names:
                order.append(name)
    except KeyError:
        pass
    if not order:
        order = sorted(names, key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    for name in order:
        paras = []
        for p in _xml(z, name).iter(_q("a", "p")):
            text = "".join(x.text or "" for x in p.iter(_q("a", "t")))
            if text.strip():
                paras.append(text)
        doc.slides.append("\n".join(paras))
    return doc


def _pdf(path: str) -> Document:
    from .doctext import _pdf as pdf_pages

    return Document("slides", slides=[text for _n, text in pdf_pages(path, lambda: False)])


def extract(path: str) -> Document:
    """Liest das Dokument; wirft bei kaputten oder fremden Dateien eine Ausnahme."""
    low = path.lower()
    if low.endswith(PDF):
        return _pdf(path)
    with zipfile.ZipFile(path) as z:
        if low.endswith((".odt", ".ott")):
            return _odt(z)
        if low.endswith((".ods", ".ots")):
            return _ods(z)
        if low.endswith((".odp", ".otp")):
            return _odp(z)
        if low.endswith(WRITER):
            return _docx(z)
        if low.endswith(CALC):
            return _xlsx(z)
        if low.endswith(IMPRESS):
            return _pptx(z)
    raise ValueError(os.path.basename(path))


def as_text(doc: Document, page_label: str = "—") -> str:
    """Für den Vergleich (L-3732): Tabellen Zeile für Zeile (Tabulator), Folien/Seiten mit Überschrift."""
    if doc.kind == "text":
        return doc.text
    if doc.kind == "sheets":
        lines = []
        for name, rows in doc.sheets:
            lines.append(f"[{name}]")
            lines.extend("\t".join(r) for r in rows)
        return "\n".join(lines)
    out = []
    for i, text in enumerate(doc.slides, 1):
        out.append(f"— {page_label} {i} —")
        out.append(text)
    return "\n".join(out)
