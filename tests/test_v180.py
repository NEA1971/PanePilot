"""Tests for 1.8: document metadata (Office, OpenDocument, PDF) and “Refresh” in the context menu."""

import os
import shutil
import zipfile

import pytest
from PySide6.QtWidgets import QApplication

from test_mainwindow import window  # noqa: F401
from test_v093 import _open

DOCS = os.path.join(os.path.dirname(__file__), "data", "docs")


@pytest.fixture
def docs(tmp_path):
    folder = tmp_path / "Dokumente"
    folder.mkdir()
    for name in os.listdir(DOCS):
        shutil.copy(os.path.join(DOCS, name), folder / name)
    return folder


def test_read_all_formats(docs):
    from panepilot import doctags as dc
    from panepilot import tags as tg

    recs = {n: tg.read_file(str(docs / n)) for n in os.listdir(docs)}
    for name, rec in recs.items():
        assert rec.error is None, name
    assert recs["brief.docx"].kind == dc.KIND_OOXML and recs["brief.odt"].kind == dc.KIND_ODF
    assert recs["brief.pdf"].kind == dc.KIND_PDF and recs["brief.doc"].kind == dc.KIND_OLE
    for name in ("brief.docx", "brief.odt", "brief.pdf", "brief.doc"):
        assert recs[name].fields["title"] == "Testbrief" and recs[name].fields["author"] == "Alice", name
    assert recs["brief.pdf"].fields["pages"] == "1" and recs["brief.pdf"].fields["pdfversion"] == "1.7"
    assert recs["brief.odt"].fields["keywords"] == "Test; Brief"
    assert recs["brief.odt"].pictures  # Vorschaubild aus Thumbnails/thumbnail.png
    # nur lesen: Infos immer, alte Formate komplett (L-821), Kategorie gibt es in PDF und ODF nicht
    assert "pages" in recs["brief.docx"].readonly and "title" not in recs["brief.docx"].readonly
    assert "*" in recs["brief.doc"].readonly
    assert "category" in recs["brief.pdf"].readonly and "category" in recs["brief.odt"].readonly
    assert tg.is_document("x.PPTX") and not tg.is_document("x.txt")


@pytest.mark.parametrize("name", ["brief.docx", "brief.odt", "brief.pdf", "tabelle.xlsx"])
def test_write_custom_and_undo(docs, name):
    from panepilot import tags as tg

    path = str(docs / name)
    before = tg.read_file(path)
    snap = tg.snapshot(path, False)
    rec = tg.write_file(before, {"title": "Neuer Titel äö", "author": "Bob", "keywords": "eins; zwei",
                                 "language": "de-DE", tg.custom_key(before.kind, "Projekt"): "P1"})
    assert rec.error is None
    assert rec.fields["title"] == "Neuer Titel äö" and rec.fields["author"] == "Bob"
    assert rec.fields["keywords"] == "eins; zwei" and rec.fields["language"] == "de-DE"
    assert rec.fields["x:Projekt"] == "P1" and rec.labels["x:Projekt"] == "Projekt"
    if before.fields.get("pdfversion"):
        assert rec.fields["pdfversion"] == before.fields["pdfversion"]  # Version bleibt
    rec = tg.write_file(rec, {"x:projekt": "P2", "subject": None})  # Groß-/Kleinschreibung egal
    assert rec.fields["x:Projekt"] == "P2" and "subject" not in rec.fields
    if not name.endswith(".pdf"):
        with zipfile.ZipFile(path) as zf:
            assert zf.testzip() is None
            if name.endswith(".odt"):
                first = zf.infolist()[0]
                assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    back = tg.restore(path, snap)
    for k in ("title", "author", "keywords", "subject", "language"):
        assert back.fields.get(k) == before.fields.get(k), k
    assert "x:Projekt" not in back.fields


def test_ooxml_without_custom_part(docs):
    """DOCX ohne docProps/custom.xml: Teil, Beziehung und Content-Type werden angelegt."""
    from panepilot import tags as tg

    path = str(docs / "brief.docx")
    with zipfile.ZipFile(path) as zf:
        assert "docProps/custom.xml" not in zf.namelist()
    rec = tg.write_file(tg.read_file(path), {"x:Projekt": "P1"})
    assert rec.fields["x:Projekt"] == "P1"
    with zipfile.ZipFile(path) as zf:
        assert b"custom-properties" in zf.read("_rels/.rels")
        assert b"/docProps/custom.xml" in zf.read("[Content_Types].xml")


def test_pdf_signed_and_encrypted_read_only(docs, tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, NumberObject

    from panepilot import tags as tg
    from panepilot.metawizard import doc_hint

    w = PdfWriter(clone_from=str(docs / "brief.pdf"))
    w._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/SigFlags"): NumberObject(3)})
    signed = str(tmp_path / "signiert.pdf")
    w.write(signed)
    rec = tg.read_file(signed)
    assert rec.note == "signed" and "*" in rec.readonly and rec.fields["title"] == "Testbrief"
    assert "Signatur" in doc_hint([rec])
    with pytest.raises(OSError):
        tg.write_file(rec, {"title": "x"})
    w = PdfWriter(clone_from=str(docs / "brief.pdf"))
    w.encrypt("", "owner")
    enc = str(tmp_path / "geschuetzt.pdf")
    w.write(enc)
    rec = tg.read_file(enc)
    assert rec.note == "encrypted" and "*" in rec.readonly and rec.fields["title"] == "Testbrief"


def test_pdf_dates_and_preview(docs):
    from panepilot import doctags as dc
    from panepilot import tags as tg

    when = dc.parse_pdf_date("D:20261117100000+01'00'")
    assert when.isoformat() == "2026-11-17T10:00:00+01:00"
    assert dc.parse_iso("2026-11-17T09:00:00Z").hour == 9
    data = dc.preview(tg.read_file(str(docs / "brief.pdf")), 200)
    assert data and data.startswith(b"\x89PNG")


def test_doc_mode_in_meta_wizard(window, docs, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import metaprofile as mp

    shutil.copy(os.path.join(os.path.dirname(__file__), "data", "audio", "leer.mp3"), docs / "lied.mp3")
    pane = _open(window, qtbot, docs)
    assert mp.is_doc_mode() and len(pane.meta_model.items) == 5
    assert pane.meta_model.columns == mp.DOC_COLUMNS
    assert pane.kind_switch.isVisible() and pane.kind_switch.btn_doc.text() == "Dokumente (5)"
    assert not pane.convert_buttons[cv.DATESHIFT].isVisibleTo(pane)
    assert not pane.convert_buttons[cv.NUMBER].isVisibleTo(pane)
    assert pane.convert_buttons[cv.TAG_TO_FILE].isVisibleTo(pane)
    items = {it.record.name: it for it in pane.meta_model.items}
    pdf = items["brief.pdf"]
    assert pane.meta_model.text(pdf, "pages") == "1"
    pane.meta_view.select_items([pdf])
    QApplication.processEvents()
    assert pane.cover.image.pixmap() is not None and not pane.cover.image.pixmap().isNull()  # erste Seite
    # Tag → Dateiname mit Datum (L-852)
    res = window._meta_compute("tag2file", "$date(%created%,JJJJ-MM-TT) %title%", "", [pdf])
    assert res[0][1] == "2026-11-17 Testbrief.pdf"
    # alte DOC-Datei: grau, mit Hinweis
    pane.meta_view.select_items([items["brief.doc"]])
    QApplication.processEvents()
    assert not pane.boxes["title"].isEnabled() and "DOC" in pane.photo_hint.text()
    # bearbeiten und speichern
    pane.meta_view.select_items([items["brief.docx"]])
    QApplication.processEvents()
    assert pane.boxes["title"].isEnabled() and not pane.boxes["pages"].isEnabled()
    pane.boxes["title"].setEditText("Antwort")
    pane.boxes["title"]._edited()
    window.meta_save()
    qtbot.waitUntil(lambda: window.meta_mode.get("save") is None, timeout=10000)
    assert items["brief.docx"].record.fields["title"] == "Antwort"
    pane.kind_switch.btn_audio.click()
    qtbot.waitUntil(lambda: window.meta_mode.get("scan") is None, timeout=10000)
    assert mp.is_audio_mode() and len(pane.meta_model.items) == 1
    window.meta_close()
    assert mp.current() == mp.AUDIO


def test_properties_meta_tab_for_pdf(window, docs):  # noqa: F811
    from PySide6.QtWidgets import QLabel

    from panepilot.propdialog import PropertiesDialog

    dlg = PropertiesDialog(window, [str(docs / "brief.pdf")])
    assert dlg.tabs.isTabEnabled(2)
    labels = dlg.tabs.widget(2).findChildren(QLabel)
    texts = [w.text() for w in labels]
    assert "Testbrief" in texts and "Alice" in texts and "1.7" in texts
    assert any(w.pixmap() is not None and not w.pixmap().isNull() for w in labels)  # Vorschau (L-860)


def test_refresh_in_context_menu(window, tmp_path):  # noqa: F811
    from PySide6.QtCore import QPoint, QTimer

    (tmp_path / "a.txt").write_text("x")
    window.active.navigate(str(tmp_path))
    QApplication.processEvents()
    seen = []

    def grab():
        menu = QApplication.activePopupWidget()
        if menu is not None:
            seen.append([x for x in menu.actions() if not x.isSeparator()])
            menu.close()

    QTimer.singleShot(200, grab)
    window._file_context_menu("left", QPoint(0, 0))
    assert seen and seen[0][-1] is window.qactions["refresh"]
