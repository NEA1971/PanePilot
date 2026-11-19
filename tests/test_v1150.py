"""Tests for 1.15: chapters (read, interval, import, export, write MKV/MP4) and tick-all in the tracks dialog."""

import os
import shutil

import pytest
from PySide6.QtWidgets import QDialog

from test_mainwindow import window  # noqa: F401
from test_v093 import _open
from test_v1130 import VIDEO, has_ffmpeg, has_mkv

needs_ffmpeg = pytest.mark.skipif(not has_ffmpeg, reason="ffmpeg fehlt")
needs_mkv = pytest.mark.skipif(not (has_ffmpeg and has_mkv), reason="mkvtoolnix fehlt")

OGM = """CHAPTER01=00:00:00.000
CHAPTER01NAME="Opening"
CHAPTER02=00:05:00.000
CHAPTER02NAME="Chase"
CHAPTER03=01:00:00.000
CHAPTER03NAME=Night
CHAPTER04=01:48:20.000
CHAPTER04NAME=
"""

XML = """<?xml version="1.0" encoding="UTF-8"?>
<Chapters><EditionEntry>
<ChapterAtom><ChapterTimeStart>00:00:00.000000000</ChapterTimeStart>
  <ChapterDisplay><ChapterString>Anfang</ChapterString><ChapterLanguage>ger</ChapterLanguage></ChapterDisplay></ChapterAtom>
<ChapterAtom><ChapterTimeStart>00:12:30.500000000</ChapterTimeStart>
  <ChapterDisplay><ChapterString>Ankunft</ChapterString></ChapterDisplay></ChapterAtom>
<ChapterAtom><ChapterTimeStart>00:20:00.000000000</ChapterTimeStart><ChapterFlagHidden>1</ChapterFlagHidden>
  <ChapterDisplay><ChapterString>versteckt</ChapterString></ChapterDisplay></ChapterAtom>
</EditionEntry></Chapters>
"""


def test_times():
    from panepilot import chapters as chp

    assert chp.parse_time("01:02:03.5") == 3723.5 and chp.parse_time("1:02:03,500") == 3723.5
    assert chp.parse_time("12:30") == 750 and chp.parse_time("00:12:30") == 750
    assert chp.parse_time("abc") is None and chp.parse_time("00:61:00") is None and chp.parse_time("00:00:75") is None
    assert chp.format_time(3723.5) == "01:02:03.500" and chp.short_time(750) == "00:12:30"


def test_parse_and_fit(window):  # noqa: F811
    from panepilot import chapters as chp

    chs = chp.parse_text(OGM)
    assert [(c.start, c.name) for c in chs] == [(0, "Opening"), (300, "Chase"), (3600, "Night"), (6500, "")]
    fitted, warn = chp.fit(chs, 6497)  # leeres Schlusskapitel weg, Länge passt
    assert [c.name for c in fitted] == ["Opening", "Chase", "Night"] and warn == ""
    fitted, warn = chp.fit(chp.parse_text(OGM), 5000)  # andere Fassung: Kapitel hinter dem Ende fallen weg
    assert [c.name for c in fitted] == ["Opening", "Chase", "Night"] and warn
    fitted, warn = chp.fit(chp.parse_text(OGM), 3000)
    assert [c.name for c in fitted] == ["Opening", "Chase"] and "1" in warn
    x = chp.parse_text(XML)
    assert [(c.start, c.name) for c in x] == [(0, "Anfang"), (750.5, "Ankunft")]
    plain = chp.parse_text("# Liste\n00:00 Vorspann\n00:12:30 „Ankunft“\n1:05:00 - Finale\nkeine Zeit\n")
    assert [(c.start, c.name) for c in plain] == [(0, "Vorspann"), (750, "Ankunft"), (3900, "Finale")]
    assert [c.name for c in chp.fit([chp.Chapter(0, ""), chp.Chapter(60, "B")], 100)[0]] == ["Kapitel 01", "B"]


def test_interval_and_files(window, tmp_path):  # noqa: F811
    from panepilot import chapters as chp

    chs = chp.interval(1500, 10)
    assert [(c.start, c.name) for c in chs] == [(0, "Kapitel 01"), (600, "Kapitel 02"), (1200, "Kapitel 03")]
    assert len(chp.interval(10, 10)) == 1
    txt, xml = tmp_path / "Film.chapters.txt", tmp_path / "Film.xml"
    chp.save_file(str(txt), chs, "ger")
    chp.save_file(str(xml), chs, "ger")
    assert txt.read_text().startswith("CHAPTER01=00:00:00.000\nCHAPTER01NAME=Kapitel 01\n")
    for p in (txt, xml):
        back = chp.read_file(str(p))
        assert [(c.start, c.name) for c in back] == [(c.start, c.name) for c in chs]
    assert "<ChapterLanguage>ger</ChapterLanguage>" in xml.read_text()
    (tmp_path / "Film.mkv").write_text("x")
    assert chp.candidates(str(tmp_path / "Film.mkv")) == [str(txt), str(xml)]
    cp = tmp_path / "w.txt"
    cp.write_bytes("00:00 Größe\n".encode("cp1252"))
    assert chp.read_file(str(cp))[0].name == "Größe"
    assert chp.chapter_language() == "ger"


def test_dialog_single(window, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import chapters as chp
    from panepilot.chaptersdialog import ChapterDialog

    video = tmp_path / "Film.mkv"
    video.write_text("x")
    (tmp_path / "Film.chapters.txt").write_text(OGM)
    v = chp.VideoChapters(str(video), "mkv", 6497.0, [chp.Chapter(0, "A"), chp.Chapter(60, "B")])
    dlg = ChapterDialog(window, [v])
    assert dlg.table.rowCount() == 2 and dlg.result_chapters() == {}  # unverändert
    assert not dlg.chk_replace.isVisibleTo(dlg)  # nur bei MP4
    dlg.table.item(1, 1).setText("Bravo")
    dlg.table.selectRow(0)
    dlg.add_row()  # zwischen 0 und 60
    assert dlg.table.item(1, 0).text() == "00:00:30"
    out = dlg.result_chapters()[str(video)]
    assert [(c.start, c.name) for c in out] == [(0, "A"), (30, "Kapitel 03"), (60, "Bravo")]
    dlg.import_file(dlg.found[0])  # L-1506: gleichnamige Datei
    assert [dlg.table.item(r, 1).text() for r in range(dlg.table.rowCount())] == ["Opening", "Chase", "Night"]
    dlg.spin.setValue(30)
    dlg.make_interval()
    assert dlg.table.rowCount() == 4 and window.settings.get("chapters_interval") == 30
    dlg.clear()
    assert dlg.result_chapters() == {str(video): []}
    dlg.set_chapters([chp.Chapter(0, "A")])
    dlg.table.item(0, 0).setText("kaputt")
    errors = []
    monkeypatch.setattr("panepilot.chaptersdialog.show_error", lambda *a: errors.append(a))
    dlg.accept()
    assert errors and dlg.result() != QDialog.DialogCode.Accepted
    dlg.table.item(0, 0).setText("02:00:00")  # hinter dem Ende
    dlg.accept()
    assert len(errors) == 2


def test_dialog_many(window, tmp_path):  # noqa: F811
    from panepilot import chapters as chp
    from panepilot.chaptersdialog import ChapterDialog

    vids = [chp.VideoChapters(str(tmp_path / "a.mkv"), "mkv", 1300.0, []),
            chp.VideoChapters(str(tmp_path / "b.mp4"), "mp4", 700.0, [chp.Chapter(0, "x")])]
    dlg = ChapterDialog(window, vids)
    assert dlg.result_chapters() == {} and dlg.chk_replace.isVisibleTo(dlg)
    dlg.spin.setValue(5)
    dlg.make_interval()
    res = dlg.result_chapters()
    assert [len(res[v.path]) for v in vids] == [5, 3]
    dlg.clear()
    assert dlg.result_chapters() == {v.path: [] for v in vids}


@needs_ffmpeg
def test_mp4_write(tmp_path):
    from mutagen.mp4 import MP4

    from panepilot import chapters as chp
    from panepilot import mp4tracks as m4
    from panepilot import videoremux as vr

    src = str(tmp_path / "Film.mp4")
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), src)
    tags = MP4(src)
    tags["\xa9nam"] = ["Testfilm"]
    tags.save()
    new = vr.remove_tracks(m4.read(src), [], [], chapters=[chp.Chapter(0, "Anfang"), chp.Chapter(0.5, "a = b; #c")])
    assert new.endswith("Film-Kopie.mp4")
    assert [(c.start, c.name) for c in chp.read(new).chapters] == [(0, "Anfang"), (0.5, "a = b; #c")]
    assert MP4(new)["\xa9nam"] == ["Testfilm"]
    assert vr.remove_tracks(m4.read(new), [], [], chapters=[], replace=True) == new
    assert chp.read(new).chapters == []


@needs_mkv
def test_mkv_write_and_controller(window, tmp_path, monkeypatch, qtbot):  # noqa: F811
    from panepilot import chapters as chp
    from panepilot import convert as cv
    from panepilot.chaptersdialog import ChapterDialog

    folder = tmp_path / "F"
    folder.mkdir()
    import subprocess

    mkv = folder / "Film.mkv"
    subprocess.run(["mkvmerge", "-q", "-o", str(mkv), os.path.join(VIDEO, "clip.mp4")], check=True)
    chp.write_mkv(str(mkv), [chp.Chapter(0, "Eins"), chp.Chapter(0.5, "Zwei")], "ger")
    assert [(c.start, c.name) for c in chp.read(str(mkv)).chapters] == [(0, "Eins"), (0.5, "Zwei")]
    pane = _open(window, qtbot, folder)
    assert pane.convert_buttons[cv.CHAPTERS].isVisibleTo(pane)

    def run(self):
        assert self.table.rowCount() == 2
        self.clear()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ChapterDialog, "exec", run)
    window.meta_convert(cv.CHAPTERS)
    assert chp.read(str(mkv)).chapters == [] and sorted(os.listdir(folder)) == ["Film.mkv"]  # ohne Kopie
    assert "1" in pane.summary.text()
    window.meta_close()


# --- Spuren: alle anhaken (L-1510/L-1511) --------------------------------------------------------------------
def test_tracks_toggle_all(window):  # noqa: F811
    from panepilot import mkvtracks as mt
    from panepilot.trackdialog import COL_DEFAULT, COL_FORCED, COL_REMOVE, TrackDialog

    f = mt.FileTracks("/x/Film.mkv", [mt.MkvTrack(1, mt.VIDEO, 1), mt.MkvTrack(2, mt.AUDIO, 1),
                                      mt.MkvTrack(3, mt.AUDIO, 2), mt.MkvTrack(4, mt.SUBS, 1),
                                      mt.MkvTrack(5, mt.SUBS, 2, forced=True)])
    dlg = TrackDialog(window, [f])
    boxes = [w["remove"] for w in dlg.widgets if "remove" in w]
    assert len(boxes) == 4  # Videospur hat keinen Haken
    dlg.table.horizontalHeader().sectionClicked.emit(COL_REMOVE)
    assert all(b.isChecked() for b in boxes)
    gone, notes = dlg.removals()
    assert [tr.number for tr in gone[f.path]] == [3, 4, 5] and notes  # erste Tonspur bleibt (mit Hinweis)
    dlg.table.horizontalHeader().sectionClicked.emit(COL_REMOVE)
    assert not any(b.isChecked() for b in boxes)
    dlg.toggle_column(COL_FORCED)
    assert all(w["forced"].isChecked() for w in dlg.widgets if "forced" in w)
    before = [w["default"].isChecked() for w in dlg.widgets if "default" in w]
    dlg.toggle_column(COL_DEFAULT)  # „Standard“ reagiert nicht
    assert [w["default"].isChecked() for w in dlg.widgets if "default" in w] == before
