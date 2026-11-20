"""Tests for 1.20: content search in documents, similar names, online data without overview."""

import os
import re
import zipfile

import pytest
from PySide6.QtWidgets import QApplication

from test_mainwindow import window  # noqa: F401

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
TXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
OFF = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"


def _zip(path, parts):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in parts.items():
            zf.writestr(name, data)
    return str(path)


def make_docx(path, text):
    return _zip(path, {"word/document.xml": f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>Einleitung</w:t></w:r>'
                                             f'</w:p><w:p><w:r><w:t>{text}</w:t></w:r><w:r><w:t> Ende</w:t></w:r>'
                                             f'</w:p></w:body></w:document>'})


def make_xlsx(path, text):
    return _zip(path, {"xl/sharedStrings.xml": f'<sst xmlns="{S}"><si><t>Kopf</t></si><si><t>{text}</t></si></sst>',
                       "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{S}"><sheetData><row><c><v>4711</v></c>'
                                                   f'</row></sheetData></worksheet>'})


def make_pptx(path, text):
    return _zip(path, {"ppt/slides/slide1.xml": f'<p:sld xmlns:p="p" xmlns:a="{A}"><a:p><a:r><a:t>{text}</a:t>'
                                                f'</a:r></a:p></p:sld>'})


def make_odf(path, text):
    return _zip(path, {"content.xml": f'<office:document-content xmlns:office="{OFF}" xmlns:text="{TXT}"><office:body>'
                                      f'<text:p>Vorher <text:span>{text}</text:span> nachher</text:p>'
                                      f'</office:body></office:document-content>'})


def make_pdf(path, pages):
    from PySide6.QtGui import QPageSize, QPainter, QPdfWriter

    writer = QPdfWriter(str(path))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    p = QPainter(writer)
    for i, text in enumerate(pages):
        if i:
            writer.newPage()
        p.drawText(200, 400, text)
    p.end()
    return str(path)


def test_doctext_formats(window, tmp_path):  # noqa: F811
    from panepilot import doctext as dt

    rx = re.compile("Zauberwort", re.IGNORECASE)
    for maker, name in ((make_docx, "a.docx"), (make_xlsx, "b.xlsx"), (make_pptx, "c.pptx"), (make_odf, "d.odt"),
                        (make_odf, "e.ods")):
        path = maker(tmp_path / name, "Das Zauberwort heißt Bitte")
        hit = dt.find(path, rx)
        assert hit is not None, name
        assert "»Zauberwort«" in hit[1] and hit[0] == "", (name, hit)
    assert "Vorher Das »Zauberwort« heißt Bitte nachher" in dt.find(str(tmp_path / "d.odt"), rx)[1]
    assert "4711" in "".join(t for _l, t in dt.pages(str(tmp_path / "b.xlsx")))  # Zahlen in Zellen
    assert dt.find(make_docx(tmp_path / "f.docx", "nichts"), rx) is None
    (tmp_path / "kaputt.docx").write_bytes(b"PK\x03\x04kaputt")
    assert dt.pages(str(tmp_path / "kaputt.docx")) == []
    pdf = make_pdf(tmp_path / "g.pdf", ["Erste Seite", "Hier steht das Zauberwort drin"])
    try:
        import pypdf  # noqa: F401
    except ImportError:
        pytest.skip("pypdf fehlt")
    label, text = dt.find(pdf, rx)
    assert label == "2" and "Zauberwort" in text
    assert dt.is_document("x.PDF") and not dt.is_document("x.doc")


def test_snippet():
    from panepilot.doctext import snippet

    text = "A" * 200 + " Mitte  des\n Textes " + "B" * 200
    m = re.search("des", text)
    s = snippet(text, m)
    assert s.startswith("…") and s.endswith("…") and "Mitte »des« Textes" in s and len(s) < 120


def test_search_thread_documents(window, tmp_path):  # noqa: F811
    from panepilot import search as srch

    make_docx(tmp_path / "brief.docx", "Kündigung zum Monatsende")
    make_odf(tmp_path / "notiz.odt", "Kündigung bestätigt")
    (tmp_path / "text.txt").write_text("Hier: Kündigung\n", encoding="utf-8")
    (tmp_path / "anders.txt").write_text("nichts", encoding="utf-8")

    def run(opts):
        th = srch.SearchThread(str(tmp_path), opts)
        found = []
        th.found.connect(found.extend)
        th.run()
        QApplication.processEvents()
        return sorted(os.path.basename(p) for p in found), th.hits

    names, hits = run(srch.SearchOptions(text="kündigung"))
    assert names == ["brief.docx", "notiz.odt", "text.txt"]
    assert "»Kündigung«" in hits[str(tmp_path / "brief.docx")] and "»Kündigung«" in hits[str(tmp_path / "text.txt")]
    names, _h = run(srch.SearchOptions(text="kündigung", documents=False))
    assert names == ["text.txt"]
    names, _h = run(srch.SearchOptions(text="KÜNDIGUNG", text_case=True))
    assert names == []
    names, _h = run(srch.SearchOptions(text=r"Monats\w+", text_mode=srch.TEXT_REGEX))
    assert names == ["brief.docx"]
    # alte Profile ohne „documents“ → eingeschaltet
    assert srch.SearchOptions.from_dict({"text": "x"}).documents is True


def test_search_tooltip_in_window(window, tmp_path, qtbot):  # noqa: F811
    from PySide6.QtCore import Qt

    from panepilot.mainwindow import MODE_SEARCH

    make_docx(tmp_path / "brief.docx", "Kündigung zum Monatsende")
    panel = window.active
    panel.navigate(str(tmp_path))
    window.set_sidebar_mode(window.active_side, MODE_SEARCH)
    pane = window.sides[window.active_side].sidebar.widget_for(MODE_SEARCH)
    assert pane.documents.isChecked()
    pane.text.setText("Monatsende")
    window.start_search(window.active_side)
    qtbot.waitUntil(lambda: window._search_thread is None, timeout=10000)
    row = panel.model.row_of("brief.docx")
    assert row >= 0
    tip = panel.model.index(row, panel.model.icon_column).data(Qt.ItemDataRole.ToolTipRole)
    assert "»Monatsende«" in tip
    from PySide6.QtWidgets import QLabel

    assert any("100 MB" in lab.text() for lab in pane.findChildren(QLabel))  # Hinweis (L-2003)


# --- Ähnliche Namen (L-2010 ff.) ------------------------------------------------------------------------------
def _f(name):
    from panepilot.duplicates import FileInfo

    return FileInfo("/x/" + name, 1, 0)


def test_similar_names():
    from panepilot import duplicates as d

    files = [_f(n) for n in ("Der.Pate_1972.mkv", "Der Pate (1972).mp4", "Der Pade (1972).avi", "IMG_0001.jpg",
                             "IMG_0002.jpg", "Herr der Ringe.mkv", "Herr der Rinke.avi", "Herr der Rinker.avi",
                             "Alien [imdbid-tt0078748].mkv", "alien.mp4", "Ganz anders.txt")]
    groups = {g.key: sorted(f.name for f in g.files) for g in d.similar_groups(files, 85)}
    assert groups["Der Pade (1972)"] == ["Der Pade (1972).avi", "Der Pate (1972).mp4", "Der.Pate_1972.mkv"]
    assert groups["Herr der Ringe"] == ["Herr der Ringe.mkv", "Herr der Rinke.avi", "Herr der Rinker.avi"]  # A~B~C
    assert groups["Alien"] == ["Alien [imdbid-tt0078748].mkv", "alien.mp4"]
    assert not any("IMG" in k for k in groups)  # Zahlen müssen übereinstimmen
    strict = {g.key: [f.name for f in g.files] for g in d.similar_groups(files, 100)}
    assert len(strict["Der Pate (1972)"]) == 2 and "Herr der Ringe" not in strict  # nur gleich nach dem Bereinigen
    assert d.similar_key("Der.Pate_1972 [imdbid-tt1].mkv") == "der pate 1972"
    stopped = d.similar_groups(files, 85, stop=lambda: True)
    assert stopped == []
    seen = []
    d.similar_groups(files, 85, progress=lambda a, b: seen.append((a, b)))
    assert seen and seen[-1][0] == seen[-1][1]


def test_similar_in_window(window, tmp_path, qtbot):  # noqa: F811
    from panepilot import duplicates as d

    folder = tmp_path / "filme"
    folder.mkdir()
    for n in ("Der.Pate_1972.mkv", "Der Pate (1972).mp4", "Urlaub.jpg"):
        (folder / n).write_bytes(b"x" * 10)
    win = d.DuplicateWindow(window, str(folder), None)
    qtbot.addWidget(win)
    assert not win.similar.isEnabled()
    win.mode_buttons[d.MODE_SIMILAR].setChecked(True)
    assert win.similar.isEnabled() and win.similar.value() == 85 and win.similar_label.text() == "85 %"
    win.similar.setValue(90)
    assert win.options().similarity == 90 and win.options().mode == d.MODE_SIMILAR
    win.start_or_stop()
    qtbot.waitUntil(lambda: win.thread is None, timeout=10000)
    assert len(win.groups) == 1 and len(win.groups[0].files) == 2
    assert d.DupOptions.from_dict(window.settings.get("dup_last")).similarity == 90
    assert d.DupOptions.from_dict({"similarity": 10}).similarity == d.SIMILAR_MIN
    win.close()


# --- Online-Daten ohne Übersicht (L-2020 ff.) -----------------------------------------------------------------
class _Item:
    def __init__(self, name, values, kind="video-mkv", ro=False):
        from types import SimpleNamespace

        self.display_name = name
        self._v = dict(values)
        self.record = SimpleNamespace(kind=kind, path="/x/" + name)
        self._ro = ro
        self._pics = []

    def value(self, k):
        return self._v.get(k, "")

    def readonly(self, k):
        return self._ro

    def pictures(self):
        return self._pics


def test_auto_changes_and_report(window):  # noqa: F811
    from panepilot import moviedb as md
    from panepilot import tags as tg
    from panepilot.moviedialogs import Job, auto_changes, auto_report
    from panepilot.i18n import t

    movie = md.Movie(md.SOURCE_TMDB, title="Der Pate", year="1972", genres=["Drama"], overview="Mafia", directors=["Coppola"],
                     imdb="tt0068646", tmdb="238", poster=b"\x89PNG")
    a = _Item("pate.mkv", {"title": "Pate (alt)", "year": ""})
    b = _Item("leer.mkv", {})
    jobs = [Job(a, movie=movie), Job(b, movie=movie), Job(_Item("weg.mkv", {}), reason=t("online.not_found")),
            Job(_Item("skip.mkv", {}), reason=t("online.skipped")), Job(_Item("ro.avi", {}, ro=True), movie=movie)]
    empty = auto_changes(jobs, overwrite=False)
    assert [it.display_name for it, _v, _p in empty] == ["pate.mkv", "leer.mkv"]
    va = empty[0][1]
    assert "title" not in va and va["year"] == "1972" and empty[0][2] == b"\x89PNG"  # Poster nur, wenn keins da
    assert va[tg.EXTRA + md.F_IMDB] == "tt0068646"
    a._pics = [tg.Picture(b"x", "image/jpeg", tg.FRONT_COVER, "")]
    empty = auto_changes(jobs, overwrite=False)
    assert empty[0][2] is None  # vorhandenes Cover bleibt
    full = auto_changes(jobs, overwrite=True)
    assert full[0][1]["title"] == "Der Pate" and full[0][2] == b"\x89PNG"
    text = auto_report(jobs, full)
    assert "2 Film(e) übernommen, 1 nicht gefunden, 1 übersprungen" in text
    assert "• weg.mkv" in text and "• skip.mkv" in text and "1 Film(e) gefunden, aber ohne neue Werte" in text


def test_online_setting(window, monkeypatch):  # noqa: F811
    from panepilot.settingsdialog import SettingsDialog

    assert window.settings.get("online_review") == "review"
    dlg = SettingsDialog(window)
    assert dlg.online_review["review"].isChecked()
    dlg.online_review["auto_all"].setChecked(True)
    dlg.accept()
    assert window.settings.get("online_review") == "auto_all"
