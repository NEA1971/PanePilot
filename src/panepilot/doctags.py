"""Metadaten von Dokumenten lesen und schreiben (v1.8, L-810 ff.).

- Microsoft Office (DOCX, XLSX, PPTX …): docProps/core.xml, app.xml, custom.xml im ZIP-Archiv
- OpenDocument (ODT, ODS, ODP, ODG): meta.xml im ZIP-Archiv
- PDF: Dokumentinformationen (und XMP, soweit vorhanden) über pypdf
- alte Office-Formate (DOC, XLS, PPT): nur lesen, über olefile

Beim Schreiben wird das ZIP-Archiv mit den geänderten Teilen neu geschrieben (in eine Hilfsdatei, dann
ausgetauscht); alle anderen Teile bleiben byte-genau erhalten.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile

OOXML_EXTENSIONS = {".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm"}
ODF_EXTENSIONS = {".odt", ".ods", ".odp", ".odg"}
PDF_EXTENSIONS = {".pdf"}
OLE_EXTENSIONS = {".doc", ".xls", ".ppt"}
ALL_EXTENSIONS = OOXML_EXTENSIONS | ODF_EXTENSIONS | PDF_EXTENSIONS | OLE_EXTENSIONS

EDITABLE = ("title", "subject", "author", "keywords", "description", "category", "language")
INFO = ("created", "modified", "lastmodifiedby", "application", "pages", "words", "pdfversion")
FIELDS = EDITABLE + INFO
STANDARD_FIELDS = FIELDS

KIND_OOXML, KIND_ODF, KIND_PDF, KIND_OLE = "doc-ooxml", "doc-odf", "doc-pdf", "doc"


def is_document(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in ALL_EXTENSIONS


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lower()


def format_name(path: str) -> str:
    return _ext(path).lstrip(".").upper()


# --- gemeinsame Hilfen ----------------------------------------------------------------------------------
def _local(when: dt.datetime | None) -> str:
    if when is None:
        return ""
    if when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    return when.strftime("%Y-%m-%d %H:%M:%S")


def parse_iso(text: str) -> dt.datetime | None:
    text = (text or "").strip()
    if not text:
        return None
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)(?:[T ](\d\d):(\d\d)(?::(\d\d))?(?:\.\d+)?)?\s*(Z|[+-]\d\d:?\d\d)?$", text)
    if not m:
        return None
    y, mo, d, h, mi, s, tz = m.groups()
    try:
        when = dt.datetime(int(y), int(mo), int(d), int(h or 0), int(mi or 0), int(s or 0))
    except ValueError:
        return None
    if tz == "Z":
        return when.replace(tzinfo=dt.timezone.utc)
    if tz:
        sign = -1 if tz[0] == "-" else 1
        digits = tz[1:].replace(":", "")
        return when.replace(tzinfo=dt.timezone(sign * dt.timedelta(hours=int(digits[:2]), minutes=int(digits[2:]))))
    return when


def _new_record(path: str):
    from . import tags as tg

    rec = tg.TagRecord(path)
    rec.codec = format_name(path)
    try:
        st = os.stat(path)
        rec.size, rec.mtime = st.st_size, st.st_mtime
    except OSError as exc:
        rec.error = exc.strerror or str(exc)
    return rec


def _set(rec, name: str, value, source: str = "") -> None:
    if value is None:
        return
    value = str(value).strip()
    if value:
        rec.fields[name] = value
        if source:
            rec.sources[name] = source


# --- Lesen ---------------------------------------------------------------------------------------------
def read_file(path: str):
    rec = _new_record(path)
    if rec.error:
        return rec
    ext = _ext(path)
    try:
        if ext in OOXML_EXTENSIONS:
            rec.kind = KIND_OOXML
            _read_ooxml(rec)
        elif ext in ODF_EXTENSIONS:
            rec.kind = KIND_ODF
            _read_odf(rec)
        elif ext in PDF_EXTENSIONS:
            rec.kind = KIND_PDF
            _read_pdf(rec)
        else:
            rec.kind = KIND_OLE
            _read_ole(rec)
    except Exception as exc:  # noqa: BLE001 – kaputte Datei als Fehler anzeigen
        rec.error = str(exc) or type(exc).__name__
        return rec
    rec.readonly |= set(INFO)
    if rec.kind == KIND_OLE or rec.note:
        extras = {k for k in rec.fields if k.startswith("x:")}
        rec.readonly |= set(EDITABLE) | extras | {"*"}
    elif rec.kind == KIND_PDF:
        rec.readonly |= {"description", "category"}  # gibt es in PDF-Dokumentinformationen nicht
    elif rec.kind == KIND_ODF:
        rec.readonly.add("category")  # gibt es in OpenDocument nicht
    return rec


# Office Open XML -------------------------------------------------------------------------------------------
NS = {
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcmitype": "http://purl.org/dc/dcmitype/",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "ep": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
    "cu": "http://schemas.openxmlformats.org/officeDocument/2006/custom-properties",
    "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}
_CORE = {"title": "dc:title", "subject": "dc:subject", "author": "dc:creator", "keywords": "cp:keywords",
         "description": "dc:description", "category": "cp:category", "language": "dc:language"}
_REL_CORE = "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
_REL_CUSTOM = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties"
_FMTID = "{D5CDD505-2E9C-101B-9397-08002B2CF9AE}"


def _q(tag: str) -> str:
    prefix, _sep, local = tag.partition(":")
    return f"{{{NS[prefix]}}}{local}"


def _part_names(zf: zipfile.ZipFile) -> dict[str, str]:
    """Teile über die Paket-Beziehungen finden (Standard: docProps/core.xml usw.)."""
    names = {"core": "docProps/core.xml", "app": "docProps/app.xml", "custom": "docProps/custom.xml"}
    try:
        rels = ET.fromstring(zf.read("_rels/.rels"))
    except (KeyError, ET.ParseError):
        return names
    for r in rels:
        typ = r.get("Type", "")
        target = r.get("Target", "").lstrip("/")
        if typ.endswith("/core-properties"):
            names["core"] = target
        elif typ.endswith("/extended-properties"):
            names["app"] = target
        elif typ.endswith("/custom-properties"):
            names["custom"] = target
        elif typ.endswith("/thumbnail"):
            names["thumb"] = target
    return names


def _read_ooxml(rec) -> None:
    from . import tags as tg

    with zipfile.ZipFile(rec.path) as zf:
        names = _part_names(zf)
        if names["core"] in zf.namelist():
            core = ET.fromstring(zf.read(names["core"]))
            for field, tag in _CORE.items():
                el = core.find(_q(tag))
                if el is not None:
                    _set(rec, field, el.text, tag)
            el = core.find(_q("cp:lastModifiedBy"))
            _set(rec, "lastmodifiedby", el.text if el is not None else None)
            for field, tag in (("created", "dcterms:created"), ("modified", "dcterms:modified")):
                el = core.find(_q(tag))
                if el is not None:
                    _set(rec, field, _local(parse_iso(el.text or "")))
        if names["app"] in zf.namelist():
            app = ET.fromstring(zf.read(names["app"]))
            name = app.findtext(_q("ep:Application")) or ""
            _set(rec, "application", name.split("$")[0].replace("/", " ").strip())
            pages = app.findtext(_q("ep:Pages")) or app.findtext(_q("ep:Slides"))
            _set(rec, "pages", pages if pages and pages != "0" else None)
            words = app.findtext(_q("ep:Words"))
            _set(rec, "words", words if words and words != "0" else None)
        if names["custom"] in zf.namelist():
            custom = ET.fromstring(zf.read(names["custom"]))
            for prop in custom.findall(_q("cu:property")):
                name = prop.get("name") or ""
                if not name or len(prop) == 0:
                    continue
                k = tg.EXTRA + name
                rec.fields[k] = (prop[0].text or "").strip()
                rec.labels[k] = name
                if prop[0].tag != _q("vt:lpwstr"):  # Zahlen, Datum, Ja/Nein: nur anzeigen
                    rec.readonly.add(k)
        thumb = names.get("thumb") or next((n for n in zf.namelist() if n.startswith("docProps/thumbnail")), None)
        if thumb and thumb in zf.namelist():
            data = zf.read(thumb)
            mime = "image/png" if thumb.lower().endswith(".png") else "image/jpeg"
            if not thumb.lower().endswith((".png", ".jpg", ".jpeg")):
                mime = ""  # z. B. WMF/EMF: kann Qt nicht zeigen
            if mime:
                rec.pictures.append(tg.Picture(data, mime, tg.FRONT_COVER, ""))


# OpenDocument ---------------------------------------------------------------------------------------------
ODF_NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "dc": "http://purl.org/dc/elements/1.1/",
    "manifest": "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0",
}
_ODF = {"title": "dc:title", "subject": "dc:subject", "author": "meta:initial-creator",
        "description": "dc:description", "language": "dc:language"}


def _oq(tag: str) -> str:
    prefix, _sep, local = tag.partition(":")
    return f"{{{ODF_NS[prefix]}}}{local}"


def _odf_meta(root: ET.Element) -> ET.Element | None:
    return root.find(_oq("office:meta"))


def _read_odf(rec) -> None:
    from . import tags as tg

    with zipfile.ZipFile(rec.path) as zf:
        if "meta.xml" in zf.namelist():
            meta = _odf_meta(ET.fromstring(zf.read("meta.xml")))
            if meta is not None:
                for field, tag in _ODF.items():
                    el = meta.find(_oq(tag))
                    if el is not None:
                        _set(rec, field, el.text, tag)
                keywords = [el.text.strip() for el in meta.findall(_oq("meta:keyword")) if el.text and el.text.strip()]
                if keywords:
                    rec.fields["keywords"] = "; ".join(keywords)
                _set(rec, "lastmodifiedby", meta.findtext(_oq("dc:creator")))
                _set(rec, "created", _local(parse_iso(meta.findtext(_oq("meta:creation-date")) or "")))
                _set(rec, "modified", _local(parse_iso(meta.findtext(_oq("dc:date")) or "")))
                gen = meta.findtext(_oq("meta:generator")) or ""
                _set(rec, "application", gen.split("$")[0].replace("/", " ").strip() if gen else "")
                stats = meta.find(_oq("meta:document-statistic"))
                if stats is not None:
                    pages = stats.get(_oq("meta:page-count"))
                    _set(rec, "pages", pages)
                    _set(rec, "words", stats.get(_oq("meta:word-count")))
                for ud in meta.findall(_oq("meta:user-defined")):
                    name = ud.get(_oq("meta:name")) or ""
                    if not name:
                        continue
                    k = tg.EXTRA + name
                    rec.fields[k] = (ud.text or "").strip()
                    rec.labels[k] = name
                    if (ud.get(_oq("meta:value-type")) or "string") != "string":
                        rec.readonly.add(k)
        if "Thumbnails/thumbnail.png" in zf.namelist():
            rec.pictures.append(tg.Picture(zf.read("Thumbnails/thumbnail.png"), "image/png", tg.FRONT_COVER, ""))


# PDF --------------------------------------------------------------------------------------------------------
_PDF_INFO = {"title": "/Title", "subject": "/Subject", "author": "/Author", "keywords": "/Keywords"}
_PDF_SKIP = {"/Title", "/Subject", "/Author", "/Keywords", "/Creator", "/Producer", "/CreationDate", "/ModDate",
             "/Trapped"}


def parse_pdf_date(text: str) -> dt.datetime | None:
    """„D:20261117100000+01'00'“ → datetime."""
    m = re.match(r"^D?:?(\d{4})(\d\d)?(\d\d)?(\d\d)?(\d\d)?(\d\d)?([Zz+\-])?(\d\d)?'?(\d\d)?'?", (text or "").strip())
    if not m:
        return None
    y, mo, d, h, mi, s, sign, oh, om = m.groups()
    try:
        when = dt.datetime(int(y), int(mo or 1), int(d or 1), int(h or 0), int(mi or 0), int(s or 0))
    except ValueError:
        return None
    if sign in ("Z", "z"):
        return when.replace(tzinfo=dt.timezone.utc)
    if sign in ("+", "-"):
        off = dt.timedelta(hours=int(oh or 0), minutes=int(om or 0))
        return when.replace(tzinfo=dt.timezone(off if sign == "+" else -off))
    return when


def is_signed(reader) -> bool:
    try:
        root = reader.trailer["/Root"]
        form = root.get("/AcroForm")
        if form is None:
            return False
        form = form.get_object()
        if int(form.get("/SigFlags", 0)) & 1:
            return True
        for f in form.get("/Fields", []) or []:
            f = f.get_object()
            if f.get("/FT") == "/Sig" and f.get("/V") is not None:
                return True
    except Exception:  # noqa: BLE001 – im Zweifel nicht signiert
        return False
    return False


def _read_pdf(rec) -> None:
    from pypdf import PdfReader

    from . import tags as tg

    reader = PdfReader(rec.path)
    if reader.is_encrypted:
        rec.note = "encrypted"
        try:
            if not reader.decrypt(""):
                _set(rec, "pdfversion", reader.pdf_header.replace("%PDF-", ""))
                return
        except Exception:  # noqa: BLE001 – Kennwort nötig: nur Version zeigen
            _set(rec, "pdfversion", reader.pdf_header.replace("%PDF-", ""))
            return
    elif is_signed(reader):
        rec.note = "signed"
    info = reader.metadata or {}
    for field, key in _PDF_INFO.items():
        if key in info:
            _set(rec, field, info.get(key), key)
    _xmp_fallback(rec, reader)
    creator = str(info.get("/Creator") or "").strip()
    producer = str(info.get("/Producer") or "").strip()
    _set(rec, "application", " / ".join(x for x in (creator, producer) if x))
    for field, key in (("created", "/CreationDate"), ("modified", "/ModDate")):
        if key in info:
            _set(rec, field, _local(parse_pdf_date(str(info.get(key)))))
    try:
        lang = reader.trailer["/Root"].get("/Lang")
        _set(rec, "language", lang)
    except Exception:  # noqa: BLE001
        pass
    try:
        _set(rec, "pages", len(reader.pages))
    except Exception:  # noqa: BLE001
        pass
    _set(rec, "pdfversion", reader.pdf_header.replace("%PDF-", ""))
    for key, value in info.items():
        if key in _PDF_SKIP or not isinstance(key, str):
            continue
        k = tg.EXTRA + key.lstrip("/")
        rec.fields[k] = str(value)
        rec.labels[k] = key.lstrip("/")


def _xmp_fallback(rec, reader) -> None:
    """Felder, die nur in den XMP-Metadaten stehen (manche Programme schreiben nur dorthin)."""
    try:
        x = reader.xmp_metadata
    except Exception:  # noqa: BLE001
        return
    if x is None:
        return
    try:
        if "title" not in rec.fields and x.dc_title:
            _set(rec, "title", x.dc_title.get("x-default") or next(iter(x.dc_title.values()), ""))
        if "author" not in rec.fields and x.dc_creator:
            _set(rec, "author", "; ".join(x.dc_creator))
        if "subject" not in rec.fields and x.dc_description:
            _set(rec, "subject", x.dc_description.get("x-default") or next(iter(x.dc_description.values()), ""))
        if "keywords" not in rec.fields and x.pdf_keywords:
            _set(rec, "keywords", x.pdf_keywords)
    except Exception:  # noqa: BLE001 – unlesbares XMP ignorieren
        return


# Alte Office-Formate ----------------------------------------------------------------------------------------
def _read_ole(rec) -> None:
    import olefile

    if not olefile.isOleFile(rec.path):
        raise OSError("not an OLE file")
    with olefile.OleFileIO(rec.path) as ole:
        m = ole.get_metadata()

    def text(v):
        if isinstance(v, bytes):
            for enc in ("utf-8", "cp1252", "latin-1"):
                try:
                    return v.decode(enc)
                except UnicodeDecodeError:
                    continue
        return v

    _set(rec, "title", text(m.title))
    _set(rec, "subject", text(m.subject))
    _set(rec, "author", text(m.author))
    _set(rec, "keywords", text(m.keywords))
    _set(rec, "description", text(m.comments))
    _set(rec, "category", text(getattr(m, "category", None)))
    _set(rec, "lastmodifiedby", text(m.last_saved_by))
    _set(rec, "application", text(m.creating_application))
    for field, when in (("created", m.create_time), ("modified", m.last_saved_time)):
        if isinstance(when, dt.datetime) and when.year > 1601:
            _set(rec, field, _local(when.replace(tzinfo=dt.timezone.utc)))
    _set(rec, "pages", m.num_pages or getattr(m, "slides", None) or None)
    _set(rec, "words", m.num_words or None)


# --- Schreiben -----------------------------------------------------------------------------------------
def writable(rec) -> bool:
    return rec.kind in (KIND_OOXML, KIND_ODF, KIND_PDF) and not rec.note


def write_file(rec, changes: dict, pictures=None):
    if not writable(rec):
        raise OSError("read-only")
    changes = {k: (v.strip() if isinstance(v, str) else v) for k, v in changes.items()}
    changes = {k: v for k, v in changes.items() if k not in INFO}
    if changes:
        if rec.kind == KIND_OOXML:
            _write_ooxml(rec, changes)
        elif rec.kind == KIND_ODF:
            _write_odf(rec, changes)
        else:
            _write_pdf(rec, changes)
    return read_file(rec.path)


def _replace_zip(path: str, parts: dict[str, bytes]) -> None:
    """ZIP neu schreiben: geänderte bzw. neue Teile ersetzen, alles andere unverändert übernehmen."""
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".panepilot-", suffix=os.path.splitext(path)[1], dir=folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(path) as src, zipfile.ZipFile(tmp, "w") as dst:
            done = set()
            for info in src.infolist():
                if info.filename in parts:
                    new = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                    new.compress_type = info.compress_type
                    new.external_attr = info.external_attr
                    dst.writestr(new, parts[info.filename])
                    done.add(info.filename)
                else:
                    dst.writestr(info, src.read(info.filename))
            for name, data in parts.items():
                if name not in done:
                    dst.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        try:
            shutil.copymode(path, tmp)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _xml(root: ET.Element) -> bytes:
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n' + ET.tostring(root, encoding="utf-8")


def _register(ns: dict) -> None:
    for prefix, uri in ns.items():
        if prefix not in ("ct", "rel", "cu", "ep"):
            ET.register_namespace(prefix, uri)


def _write_ooxml(rec, changes: dict) -> None:
    from . import tags as tg

    _register(NS)
    parts: dict[str, bytes] = {}
    with zipfile.ZipFile(rec.path) as zf:
        names = _part_names(zf)
        listing = zf.namelist()
        core_changes = {k: v for k, v in changes.items() if k in _CORE}
        custom_changes = {k[len(tg.EXTRA):]: v for k, v in changes.items() if k.startswith(tg.EXTRA)}
        need_rels = []
        if core_changes:
            if names["core"] in listing:
                core = ET.fromstring(zf.read(names["core"]))
            else:
                core = ET.Element(_q("cp:coreProperties"))
                need_rels.append((names["core"], _REL_CORE,
                                  "application/vnd.openxmlformats-package.core-properties+xml"))
            for field, value in core_changes.items():
                el = core.find(_q(_CORE[field]))
                if value is None:
                    if el is not None:
                        core.remove(el)
                    continue
                if el is None:
                    el = ET.SubElement(core, _q(_CORE[field]))
                el.text = value
            parts[names["core"]] = _xml(core)
        if custom_changes:
            if names["custom"] in listing:
                ET.register_namespace("", NS["cu"])
                ET.register_namespace("vt", NS["vt"])
                custom = ET.fromstring(zf.read(names["custom"]))
            else:
                custom = ET.Element(_q("cu:Properties"))
                need_rels.append((names["custom"], _REL_CUSTOM,
                                  "application/vnd.openxmlformats-officedocument.custom-properties+xml"))
            props = custom.findall(_q("cu:property"))
            pids = [int(p.get("pid", "1")) for p in props if (p.get("pid") or "").isdigit()]
            for name, value in custom_changes.items():
                found = next((p for p in props if (p.get("name") or "").casefold() == name.casefold()), None)
                if value is None:
                    if found is not None:
                        custom.remove(found)
                    continue
                if found is None:
                    found = ET.SubElement(custom, _q("cu:property"), {"fmtid": _FMTID,
                                                                     "pid": str(max(pids + [1]) + 1),
                                                                     "name": name})
                    pids.append(int(found.get("pid")))
                for child in list(found):
                    found.remove(child)
                ET.SubElement(found, _q("vt:lpwstr")).text = value
            ET.register_namespace("", NS["cu"])
            parts[names["custom"]] = _xml(custom)
        for part, rel_type, content_type in need_rels:
            rels = ET.fromstring(parts.get("_rels/.rels") or zf.read("_rels/.rels"))
            ids = {r.get("Id") for r in rels}
            n = 1
            while f"rId{n}" in ids or f"rIdPP{n}" in ids:
                n += 1
            ET.register_namespace("", NS["rel"])
            ET.SubElement(rels, _q("rel:Relationship"), {"Id": f"rIdPP{n}", "Type": rel_type, "Target": part})
            parts["_rels/.rels"] = _xml(rels)
            ct_name = "[Content_Types].xml"
            ET.register_namespace("", NS["ct"])
            ct = ET.fromstring(parts.get(ct_name) or zf.read(ct_name))
            ET.SubElement(ct, _q("ct:Override"), {"PartName": "/" + part, "ContentType": content_type})
            parts[ct_name] = _xml(ct)
    _replace_zip(rec.path, parts)


def _write_odf(rec, changes: dict) -> None:
    from . import tags as tg

    _register(ODF_NS)
    with zipfile.ZipFile(rec.path) as zf:
        if "meta.xml" not in zf.namelist():
            raise OSError("meta.xml missing")
        raw = zf.read("meta.xml")
    root = ET.fromstring(raw)
    meta = _odf_meta(root)
    if meta is None:
        meta = ET.SubElement(root, _oq("office:meta"))
    for field, value in changes.items():
        if field == "keywords":
            for el in meta.findall(_oq("meta:keyword")):
                meta.remove(el)
            for word in [w.strip() for w in re.split(r"[;,]", value or "") if w.strip()]:
                ET.SubElement(meta, _oq("meta:keyword")).text = word
            continue
        if field.startswith(tg.EXTRA):
            name = field[len(tg.EXTRA):]
            found = next((u for u in meta.findall(_oq("meta:user-defined"))
                          if (u.get(_oq("meta:name")) or "").casefold() == name.casefold()), None)
            if value is None:
                if found is not None:
                    meta.remove(found)
                continue
            if found is None:
                found = ET.SubElement(meta, _oq("meta:user-defined"), {_oq("meta:name"): name})
            found.set(_oq("meta:value-type"), "string")
            found.text = value
            continue
        tag = _ODF.get(field)
        if tag is None:
            continue
        el = meta.find(_oq(tag))
        if value is None:
            if el is not None:
                meta.remove(el)
            continue
        if el is None:
            el = ET.SubElement(meta, _oq(tag))
        el.text = value
    _replace_zip(rec.path, {"meta.xml": b'<?xml version="1.0" encoding="UTF-8"?>\n' +
                            ET.tostring(root, encoding="utf-8")})


def _write_pdf(rec, changes: dict) -> None:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, TextStringObject

    from . import tags as tg

    reader = PdfReader(rec.path)
    writer = PdfWriter(clone_from=reader)
    try:
        writer.pdf_header = reader.pdf_header.encode() if isinstance(writer.pdf_header, bytes) else reader.pdf_header
    except Exception:  # noqa: BLE001 – Version bleibt dann die von pypdf
        pass
    info = dict(reader.metadata or {})
    for field, value in changes.items():
        if field == "language":
            root = writer._root_object
            if value is None:
                root.pop(NameObject("/Lang"), None)
            else:
                root[NameObject("/Lang")] = TextStringObject(value)
            continue
        if field.startswith(tg.EXTRA):
            name = field[len(tg.EXTRA):]
            key = next((k for k in info if isinstance(k, str) and k.lstrip("/").casefold() == name.casefold()),
                       "/" + name)
        else:
            key = _PDF_INFO.get(field)
            if key is None:
                continue
        if value is None:
            info.pop(key, None)
        else:
            info[key] = value
    meta = writer._info.get_object() if writer._info is not None else None
    if meta is not None:
        for k in list(meta.keys()):
            if k not in info:
                del meta[k]
    writer.add_metadata({k: (v if not isinstance(v, str) else TextStringObject(v)) for k, v in info.items()})
    _update_xmp(writer, changes)
    folder = os.path.dirname(os.path.abspath(rec.path))
    fd, tmp = tempfile.mkstemp(prefix=".panepilot-", suffix=".pdf", dir=folder)
    os.close(fd)
    try:
        with open(tmp, "wb") as fh:
            writer.write(fh)
        try:
            shutil.copymode(rec.path, tmp)
        except OSError:
            pass
        os.replace(tmp, rec.path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


_XMP_NS = {"x": "adobe:ns:meta/", "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
           "dc": "http://purl.org/dc/elements/1.1/", "pdf": "http://ns.adobe.com/pdf/1.3/"}


def _update_xmp(writer, changes: dict) -> None:
    """Vorhandene XMP-Metadaten mitziehen, damit Programme, die XMP bevorzugen, dieselben Werte zeigen."""
    from pypdf.generic import NameObject, StreamObject

    try:
        root = writer._root_object
        if "/Metadata" not in root:
            return
        stream = root["/Metadata"].get_object()
        data = stream.get_data()
        for prefix, uri in _XMP_NS.items():
            ET.register_namespace(prefix, uri)
        start = data.find(b"<x:xmpmeta")
        end = data.find(b"</x:xmpmeta>")
        if start < 0 or end < 0:
            return
        tree = ET.fromstring(data[start:end + len(b"</x:xmpmeta>")])
        rdf = tree.find(f"{{{_XMP_NS['rdf']}}}RDF")
        if rdf is None:
            return
        desc = rdf.find(f"{{{_XMP_NS['rdf']}}}Description")
        if desc is None:
            desc = ET.SubElement(rdf, f"{{{_XMP_NS['rdf']}}}Description", {f"{{{_XMP_NS['rdf']}}}about": ""})
        R = _XMP_NS["rdf"]

        def set_list(tag: str, container: str, value) -> None:
            for d in rdf.findall(f"{{{R}}}Description"):
                for old in d.findall(tag):
                    d.remove(old)
            if value is None:
                return
            el = ET.SubElement(desc, tag)
            box = ET.SubElement(el, f"{{{R}}}{container}")
            li = ET.SubElement(box, f"{{{R}}}li")
            if container == "Alt":
                li.set("{http://www.w3.org/XML/1998/namespace}lang", "x-default")
            li.text = value

        mapping = {"title": (f"{{{_XMP_NS['dc']}}}title", "Alt"), "subject": (f"{{{_XMP_NS['dc']}}}description", "Alt"),
                   "author": (f"{{{_XMP_NS['dc']}}}creator", "Seq")}
        for field, (tag, container) in mapping.items():
            if field in changes:
                set_list(tag, container, changes[field])
        if "keywords" in changes:
            tag = f"{{{_XMP_NS['pdf']}}}Keywords"
            for d in rdf.findall(f"{{{R}}}Description"):
                for old in d.findall(tag):
                    d.remove(old)
                if d.get(tag) is not None:
                    del d.attrib[tag]
            if changes["keywords"] is not None:
                ET.SubElement(desc, tag).text = changes["keywords"]
        xml = ET.tostring(tree, encoding="utf-8")
        packet = (b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n' + xml +
                  b'\n<?xpacket end="w"?>')
        new = StreamObject()
        new[NameObject("/Type")] = NameObject("/Metadata")
        new[NameObject("/Subtype")] = NameObject("/XML")
        new.set_data(packet)
        root[NameObject("/Metadata")] = writer._add_object(new)
    except Exception:  # noqa: BLE001 – XMP ist Zugabe; die Dokumentinformationen sind geschrieben
        return


# --- Rückgängig ----------------------------------------------------------------------------------------
def snapshot(path: str) -> tuple:
    rec = read_file(path)
    keep = {k: v for k, v in rec.fields.items() if k in EDITABLE or k.startswith("x:")}
    return ("document", keep)


def restore(path: str, snap: tuple):
    _kind, old = snap
    rec = read_file(path)
    if not writable(rec):
        return rec
    changes = {}
    for k in set(EDITABLE) | {k for k in rec.fields if k.startswith("x:")} | {k for k in old if k.startswith("x:")}:
        if k in rec.readonly:
            continue
        if rec.fields.get(k) != old.get(k):
            changes[k] = old.get(k)
    return write_file(rec, changes) if changes else rec


# --- Vorschau ----------------------------------------------------------------------------------------------
def pdf_preview(path: str, size: int = 432) -> bytes | None:
    """Erste Seite einer PDF als PNG (L-841), gezeichnet mit pdfium."""
    try:
        import pypdfium2 as pdfium
    except Exception:  # noqa: BLE001 – ohne Bibliothek keine Vorschau
        return None
    try:
        pdf = pdfium.PdfDocument(path)
        try:
            page = pdf[0]
            w, h = page.get_size()
            scale = size / max(w, h, 1)
            image = page.render(scale=scale).to_pil()
            buf = io.BytesIO()
            image.save(buf, "PNG")
            return buf.getvalue()
        finally:
            pdf.close()
    except Exception:  # noqa: BLE001 – kaputte oder verschlüsselte PDF: keine Vorschau
        return None


def preview(rec, size: int = 432) -> bytes | None:
    if rec.kind == KIND_PDF and rec.note != "encrypted":
        return pdf_preview(rec.path, size)
    if rec.pictures:
        return rec.pictures[0].data
    return None
