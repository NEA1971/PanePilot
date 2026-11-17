"""Tests for 1.7: audio tracks and subtitles of videos."""

import os
import shutil
import subprocess

import pytest
from PySide6.QtCore import Qt

from test_mainwindow import window  # noqa: F401
from test_v093 import _open

VIDEO = os.path.join(os.path.dirname(__file__), "data", "video")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                  reason="ffmpeg missing")


def make_multitrack(folder) -> str:
    """MKV mit zwei Tonspuren (deu 5.1 Standard, eng Stereo „Kommentar“) und zwei Untertiteln."""
    srt = os.path.join(folder, "u.srt")
    with open(srt, "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:00,000 --> 00:00:00,800\nHallo\n")
    out = os.path.join(folder, "Film (2001).mkv")
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10", "-f", "lavfi", "-i",
        "sine=frequency=440:sample_rate=8000", "-i", srt, "-i", srt, "-t", "1",
        "-map", "0:v", "-map", "1:a", "-map", "1:a", "-map", "2:s", "-map", "3:s",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a:0", "ac3", "-ac:a:0", "6", "-c:a:1", "aac", "-ac:a:1", "2",
        "-c:s", "srt",
        "-metadata:s:a:0", "language=ger", "-disposition:a:0", "default",
        "-metadata:s:a:1", "language=eng", "-metadata:s:a:1", "title=Kommentar", "-disposition:a:1", "0",
        "-metadata:s:s:0", "language=eng", "-disposition:s:0", "forced",
        "-metadata:s:s:1", "language=und", "-disposition:s:1", "0",
        out], check=True)
    return out


@needs_ffmpeg
def test_tracks_read(tmp_path):
    from panepilot import tags as tg
    from panepilot.tracks import lang_list, tooltip

    rec = tg.read_file(make_multitrack(str(tmp_path)))
    assert [t.code for t in rec.audio_tracks] == ["ger", "eng"]  # so, wie es in der Datei steht
    assert lang_list(rec.audio_tracks) == "ger, eng"
    assert lang_list(rec.sub_tracks) == "eng (forced), ?"
    lines = tooltip(rec.audio_tracks).splitlines()
    assert lines[0] == "ger (Deutsch) – AC-3 5.1 – Standard"
    assert lines[1] == "eng (Englisch) – AAC Stereo – „Kommentar“"
    sub = tooltip(rec.sub_tracks).splitlines()
    # ältere ffmpeg-Versionen markieren den ersten Untertitel zusätzlich als Standard
    assert sub[0] in ("eng (Englisch) – SRT – erzwungen", "eng (Englisch) – SRT – Standard, erzwungen")
    assert sub[1] == "Sprache unbekannt – SRT"


def test_language_names():
    from panepilot.tracks import Track, language_name, lang_list

    assert language_name("deu") == language_name("ger") == "Deutsch"
    assert language_name("und") == "Sprache unbekannt" and language_name("qqq") == ""
    assert lang_list([Track("audio", "")]) == "?"


@needs_ffmpeg
def test_columns_tooltip_placeholders_and_properties(window, tmp_path, qtbot):  # noqa: F811
    from PySide6.QtWidgets import QLabel

    from panepilot import metaprofile as mp
    from panepilot.propdialog import PropertiesDialog

    folder = tmp_path / "Filme"
    folder.mkdir()
    path = make_multitrack(str(folder))
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), folder / "ohne (2000).mp4")
    pane = _open(window, qtbot, folder)
    assert mp.is_video_mode() and "i:audio" in mp.info_columns() and "i:subs" in mp.info_columns()
    model = pane.meta_model
    items = {it.record.name: it for it in model.items}
    film = items["Film (2001).mkv"]
    assert model.text(film, "i:audio") == "ger, eng" and model.text(film, "i:subs") == "eng (forced), ?"
    assert model.text(items["ohne (2000).mp4"], "i:subs") == ""
    pane.meta_view.set_columns(["filename", "i:audio", "i:subs"])
    row = model.items.index(film)
    idx = model.index(row, model.columns.index("i:audio"))
    assert "AC-3 5.1" in model.data(idx, Qt.ItemDataRole.ToolTipRole)
    res = window._meta_compute("tag2file", "%audiolang% - %sublang%", "", [film])
    assert res[0][1] == "ger, eng - eng (forced), -.mkv"  # „?“ ist im Dateinamen nicht erlaubt
    window.meta_close()
    dlg = PropertiesDialog(window, [path])
    labels = dlg.meta_texts()
    assert any("ger (Deutsch) – AC-3 5.1 – Standard" in x for x in labels)
    assert any("eng (Englisch) – SRT –" in x and "erzwungen" in x for x in labels)


# --- 1.7.1: „Season“ und „SEASON“ sind dasselbe Feld -------------------------------------------------------------
def test_custom_field_case_merged(window, tmp_path, qtbot, monkeypatch):  # noqa: F811
    from panepilot import tags as tg
    from panepilot import videotags as vt

    folder = tmp_path / "Serie"
    folder.mkdir()
    shutil.copy(os.path.join(VIDEO, "clip.mkv"), folder / "S01E01.mkv")
    real = vt.read_file

    def fake(path):  # MKV-Datei mit eigenem Feld in Großbuchstaben (wie mkvpropedit es schreibt)
        rec = real(path)
        rec.fields["x:SEASON"] = "S01"
        rec.labels["x:SEASON"] = "SEASON"
        return rec
    monkeypatch.setattr(vt, "read_file", fake)
    window.settings.set("meta_video_custom_fields", ["Season"])
    window.settings.set("meta_video_layout", {"columns": ["filename", "x:Season", "x:SEASON", "title"]})
    window.settings.set("meta_video_sidebar", ["title", "x:Season"])
    pane = _open(window, qtbot, folder)
    model = pane.meta_model
    assert list(model.extra_keys()) == ["x:SEASON"]
    assert model.columns.count("x:SEASON") == 1 and "x:Season" not in model.columns
    assert pane.layout_keys == ["title", "x:SEASON"]
    assert model.text(model.items[0], "x:SEASON") == "S01"
    assert tg.custom_key("video-mkv", "Season") == "x:SEASON"
    window.meta_close()


def test_text_import_left_buttons_and_comma_csv(tmp_path):
    from PySide6.QtWidgets import QPushButton

    from panepilot.metaextras import ImportDialog, TextData, read_text_file

    class It:
        def __init__(self, n):
            self.display_name = n

        def folder(self):
            return ""

    items = [It(f"f{i}.mkv") for i in range(3)]
    dlg = ImportDialog(None, items, TextData(None, [["Kopf"], ["a"], ["b"], ["c"]]), [], "%title%", lambda *a: None)
    left_insert = [b for b in dlg.findChildren(QPushButton) if b.text() == "Platzhalter einfügen"][0]
    dlg.list_left.setCurrentRow(0)
    left_insert.click()  # wirkt jetzt links: Kopfzeile steht einem Platzhalter gegenüber
    assert dlg.left[0] is None and dlg.right[:2] == [0, 1]
    csv = tmp_path / "liste.csv"
    csv.write_text("Dateiname,Titel,SEASON,EPISODE\nf1.mkv,\"Tigh Me Up, Tigh Me Down\",S01,E09\n", encoding="utf-8")
    data = read_text_file(str(csv), [])
    assert data.header == ["filename", "title", "x:SEASON", "x:EPISODE"]
    assert data.rows[0][1] == "Tigh Me Up, Tigh Me Down"


# --- 1.7.2: Feld nur im Layout (keine Datei im Ordner hat es) -------------------------------------------------------
def test_layout_only_fields_merged_and_editable(window, tmp_path, qtbot, monkeypatch):  # noqa: F811
    from panepilot import metadialogs

    folder = tmp_path / "Serie1980"
    folder.mkdir()
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), folder / "S01E01.mp4")
    window.settings.set("meta_video_custom_fields", [])
    window.settings.set("meta_video_layout", {"columns": ["filename", "x:SEASON", "x:Season", "x:Episode"]})
    pane = _open(window, qtbot, folder)
    model = pane.meta_model
    assert model.columns == ["filename", "x:SEASON", "x:Episode"]  # eine Spalte je Name
    assert set(model.extra_keys().values()) == {"SEASON", "Episode"}  # im Spaltenmenü abwählbar
    seen = {}

    class FakeEditor:
        DialogCode = metadialogs.FieldEditorDialog.DialogCode

        def __init__(self, parent, rows, n):
            seen["labels"] = {r.label for r in rows}
            self.rows = rows

        def exec(self):
            return self.DialogCode.Accepted

        def deletions(self):
            return [r for r in self.rows if r.label == "Episode"]

        def renames(self):
            return []

        def new_fields(self):
            return []
    monkeypatch.setattr(metadialogs, "FieldEditorDialog", FakeEditor)
    window.meta_field_editor()
    assert {"SEASON", "Episode"} <= seen["labels"]  # im Feld-Editor sichtbar
    assert model.columns == ["filename", "x:SEASON"]  # gelöschtes Feld: Spalte weg
    window.meta_close()


# --- 1.7.3: %Season% füllt das vorhandene Feld „Season“ -----------------------------------------------------------
def test_file_to_tag_custom_field_keeps_case(window, tmp_path, qtbot):  # noqa: F811
    from panepilot import convert as cv

    assert cv.parse_filename("BSG 1980 S01E06 Spaceball", "%dummy% S%Season%E%Episode% %title%") == \
        {"Season": "01", "Episode": "06", "title": "Spaceball"}
    assert cv.parse_filename("01 - x", "%Track% - %Title%") == {"track": "01", "title": "x"}
    folder = tmp_path / "BSG"
    folder.mkdir()
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), folder / "BSG 1980 S01E06 Spaceball.mp4")
    window.settings.set("meta_video_custom_fields", ["Season", "Episode"])
    window.settings.set("meta_video_layout", {"columns": ["filename", "title", "x:Season", "x:Episode"]})
    pane = _open(window, qtbot, folder)
    it = pane.meta_model.items[0]
    res = window._meta_compute("file2tag", "%dummy% S%Season%E%Episode% %title%", "", [it])
    assert window._meta_target("Season") == "x:Season" and window._meta_target("season") == "x:Season"
    for name, v in res[0][1].items():
        it.set(window._meta_target(name), v)
    model = pane.meta_model
    assert model.text(it, "x:Season") == "01" and model.text(it, "x:Episode") == "06"
    it.set("x:season", "02")  # andere Schreibweise: dasselbe vorgemerkte Feld
    assert model.text(it, "x:Season") == "02" and len([k for k in it.pending if "eason" in k]) == 1
    window.meta_save()
    qtbot.waitUntil(lambda: window.meta_mode.get("save") is None, timeout=10000)
    assert it.record.fields.get("x:----:com.apple.iTunes:Season") == "02"
    window.meta_close()
