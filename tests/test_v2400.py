"""Tests for 2.4: double-click editing in the meta wizard, episodes without S01E01, report of applied films."""

import os
import shutil

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit

from test_mainwindow import window  # noqa: F401
from test_v093 import _open
from test_v190 import VIDEO, _videos


# --- Doppelklick ------------------------------------------------------------------------------------------
def _cell(pane, name, col):
    view = pane.meta_view
    model = pane.meta_model
    row = next(i for i, it in enumerate(model.items) if it.record.name == name)
    src = model.index(row, model.columns.index(col))
    return view.proxy.mapFromSource(src), model.items[row]


def _dclick(view, index):
    rect = view.visualRect(index)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    QApplication.processEvents()


def _inline(view):
    edit = view._inline[0] if view._inline is not None else None
    assert edit is None or (isinstance(edit, QLineEdit) and edit.objectName() == "metaInline")
    return edit


def test_double_click_edit(window, tmp_path, qtbot, monkeypatch):  # noqa: F811
    from panepilot import dialogs

    errors = []
    monkeypatch.setattr(dialogs, "show_error", lambda *a: errors.append(a[2]))
    monkeypatch.setattr(dialogs, "confirm", lambda *a, **k: True)
    pane = _open(window, qtbot, _videos(tmp_path))
    view = pane.meta_view
    model = pane.meta_model
    if "title" not in model.columns:
        view.set_columns(model.columns + ["title"])
    index, item = _cell(pane, "Heat (1995).mp4", "title")
    _dclick(view, index)
    edit = _inline(view)
    assert edit is not None and edit.text() == item.value("title")
    edit.setText("Heat – Neu")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert item.pending.get("title") == "Heat – Neu" and _inline(view) is None
    others = [it for it in model.items if it is not item]
    assert not any(it.changed for it in others)  # nur die angeklickte Zeile
    # Esc bricht ab
    index, ronin = _cell(pane, "Ronin (1998).mp4", "title")
    _dclick(view, index)
    edit = _inline(view)
    edit.setText("weg")
    QTest.keyClick(edit, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert _inline(view) is None and not ronin.changed
    # Dateiname: umbenennen (nur vorgemerkt), Endung muss bleiben
    index, item = _cell(pane, "Unbekannt.mp4", "filename")
    _dclick(view, index)
    edit = _inline(view)
    assert edit.selectedText() == "Unbekannt"
    edit.setText("Bekannt.mkv")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert errors and ".mp4" in errors[-1] and item.pending_name is None
    _dclick(view, _cell(pane, "Unbekannt.mp4", "filename")[0])
    edit = _inline(view)
    edit.setText("Heat (1995).mp4")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert "gibt es" in errors[-1] and item.pending_name is None
    _dclick(view, _cell(pane, "Unbekannt.mp4", "filename")[0])
    edit = _inline(view)
    edit.setText("Bekannt.mp4")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert item.pending_name == "Bekannt.mp4" and os.path.exists(item.record.path)  # erst beim Speichern


def test_double_click_long_and_info(window, tmp_path, qtbot):  # noqa: F811
    pane = _open(window, qtbot, _videos(tmp_path))
    view = pane.meta_view
    model = pane.meta_model
    cols = [c for c in model.columns]
    extra = [c for c in ("description", "i:size") if c not in cols]
    if extra:
        view.set_columns(cols + extra)
    index, _item = _cell(pane, "Heat (1995).mp4", "i:size")
    _dclick(view, index)
    assert _inline(view) is None
    index, _item = _cell(pane, "Heat (1995).mp4", "description")
    if "description" in pane.boxes:
        _dclick(view, index)
        assert _inline(view) is None
        box = pane.boxes["description"]
        assert box.hasFocus() or (box.lineEdit() is not None and box.lineEdit().hasFocus()) or \
            QApplication.focusWidget() in (box, box.lineEdit())


# --- Folgen ohne S01E01 -----------------------------------------------------------------------------------
def test_loose_episode_ref(tmp_path):
    from panepilot import moviedb as md

    r = md.loose_episode_ref(str(tmp_path / "Auf Leben und Tod" / "3.mkv"))
    assert (r.series, r.season, r.episode) == ("Auf Leben und Tod", 1, 3)
    r = md.loose_episode_ref(str(tmp_path / "Dark (2017)" / "Staffel 2" / "Folge 04.mkv"))
    assert (r.series, r.year, r.season, r.episode) == ("Dark", "2017", 2, 4)
    r = md.loose_episode_ref(str(tmp_path / "Miniserie {tmdbid-64313}" / "Teil 2.mkv"))
    assert r.episode == 2 and r.tmdb == "64313"
    assert md.loose_episode_ref(str(tmp_path / "X" / "E05 Abschied.mkv")).episode == 5
    assert md.loose_episode_ref(str(tmp_path / "Filme" / "Heat (1995).mkv")) is None
    assert md.loose_episode_ref(str(tmp_path / "Filme" / "Rocky 2.mkv")) is None


def test_make_jobs_loose(tmp_path):
    from panepilot import moviedialogs as mdl

    class Rec:
        def __init__(self, path):
            self.path, self.name = path, os.path.basename(path)

    class Item:
        def __init__(self, path):
            self.record = Rec(path)
            self.display_name = self.record.name

        def value(self, key):
            return ""

    items = [Item(str(tmp_path / "Auf Leben und Tod" / f"{n}.mkv")) for n in (2, 1, 3)]
    items.append(Item(str(tmp_path / "Filme" / "Heat (1995).mkv")))
    asked = []

    def yes(folder, series, season, nums):
        asked.append((os.path.basename(folder), series, season, nums))
        return True
    jobs = mdl.make_jobs(items, yes)
    assert asked == [("Auf Leben und Tod", "Auf Leben und Tod", 1, [1, 2, 3])]
    eps = [j for j in jobs if j.ep is not None]
    assert len(eps) == 3 and len({id(j.group) for j in eps}) == 1 and eps[0].group.name == "Auf Leben und Tod"
    jobs = mdl.make_jobs(items, lambda *a: False)
    assert all(j.ep is None for j in jobs) and jobs[0].title == "2"
    assert all(j.ep is None for j in mdl.make_jobs(items))  # ohne Rückfrage wie bisher


def test_online_asks_for_loose_folder(window, tmp_path, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import dialogs
    from panepilot import moviedb as md
    from panepilot import moviedialogs as mdl

    folder = tmp_path / "Auf Leben und Tod"
    folder.mkdir()
    for n in (1, 2):
        shutil.copy(os.path.join(VIDEO, "clip.mp4"), folder / f"{n}.mp4")
    pane = _open(window, qtbot, folder)
    pane.meta_view.selectAll()
    questions = []
    monkeypatch.setattr(dialogs, "confirm", lambda p, title, text, **k: questions.append(text) or False)
    monkeypatch.setattr(dialogs, "_msgbox", lambda *a, **k: "button.discard")
    monkeypatch.setattr(md, "load_key", lambda: "")
    monkeypatch.setattr(mdl, "run_lookup", lambda *a: "stop")
    monkeypatch.setattr(mdl, "error_text", lambda e: e)
    monkeypatch.setattr(dialogs, "show_error", lambda *a: None)
    monkeypatch.setattr(dialogs, "show_info", lambda *a: None)
    window.meta_convert(cv.ONLINE)
    assert questions and "Folgen 1–2 von Staffel 1" in questions[0] and "„Auf Leben und Tod“" in questions[0]


# --- Abschlussmeldung -------------------------------------------------------------------------------------
def test_report_lists_applied():
    from panepilot import moviedb as md
    from panepilot import moviedialogs as mdl

    class Item:
        def __init__(self, name):
            self.display_name = name

    a, b, c = Item("Heat.mkv"), Item("Columbo S01E02.mkv"), Item("Unbekannt.mkv")
    jobs = [mdl.Job(a, title="Heat"), mdl.Job(b, title="Columbo"), mdl.Job(c, title="x")]
    jobs[0].movie = md.Movie(md.SOURCE_TMDB, title="Heat", year="1995")
    jobs[1].movie = md.Movie(md.SOURCE_TMDB, title="Tödliche Trennung", series="Columbo", season="01", episode="02")
    text = mdl.auto_report(jobs, [(a, {}, None), (b, {}, None)])
    assert "Übernommen:" in text
    assert "• Heat.mkv → Heat (1995)" in text
    assert "• Columbo S01E02.mkv → Columbo – S01E02 „Tödliche Trennung“" in text
    assert "Unbekannt.mkv:" in text


def test_show_report_long(window, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QDialog

    from panepilot import dialogs

    shown = []
    monkeypatch.setattr(dialogs, "show_info", lambda *a: shown.append("info"))
    monkeypatch.setattr(QDialog, "exec", lambda self: shown.append(self.windowTitle()) or 0)
    dialogs.show_report(window, "T", "kurz")
    dialogs.show_report(window, "Lang", "\n".join(str(i) for i in range(40)))
    assert shown == ["info", "Lang"]
