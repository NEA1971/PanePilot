"""Tests for 1.11: editing MKV tracks; online data for TV series (network faked)."""

import json
import os
import shutil
import urllib.parse

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from test_mainwindow import window  # noqa: F401
from test_v093 import _open
from test_v190 import PNG

VIDEO = os.path.join(os.path.dirname(__file__), "data", "video")

IDENTIFY = {"tracks": [
    {"codec": "AVC/H.264/MPEG-4p10", "id": 0, "type": "video", "properties": {"number": 1, "language": "und"}},
    {"codec": "AC-3", "id": 1, "type": "audio",
     "properties": {"number": 2, "language": "und", "audio_channels": 6, "default_track": True}},
    {"codec": "AAC", "id": 2, "type": "audio",
     "properties": {"number": 3, "language": "eng", "track_name": "English", "audio_channels": 2}},
    {"codec": "SubRip/SRT", "id": 3, "type": "subtitles", "properties": {"number": 4, "language": "ger"}},
]}


# --- Spuren --------------------------------------------------------------------------------------------
def test_parse_identify_and_args():
    from panepilot import mkvtracks as mt

    tracks = mt.parse_identify(IDENTIFY)
    assert [(tr.kind, tr.index, tr.number) for tr in tracks] == [("video", 1, 1), ("audio", 1, 2), ("audio", 2, 3),
                                                                  ("subtitles", 1, 4)]
    a1 = tracks[1]
    assert a1.lang == "und" and a1.channels == 6 and a1.default and not a1.forced
    ch = mt.TrackChange(lang="ger", name="Deutsch AC3 5.1", forced=False)
    assert mt.edit_args(a1, ch) == ["--edit", "track:@2", "--set", "language=ger", "--set", "name=Deutsch AC3 5.1"]
    assert mt.edit_args(tracks[2], mt.TrackChange(name="")) == ["--edit", "track:@3", "--delete", "name"]
    assert mt.edit_args(tracks[0], mt.TrackChange(lang="ger", name="Film")) == ["--edit", "track:@1", "--set",
                                                                                "name=Film"]
    assert mt.edit_args(tracks[3], mt.TrackChange(forced=True)) == ["--edit", "track:@4", "--set", "flag-forced=1"]
    assert mt.suggest_name("audio", "ger", "AC-3", 6) == "Deutsch AC3 5.1"
    assert mt.suggest_name("audio", "eng", "AAC", 2) == "Englisch AAC Stereo"
    assert mt.suggest_name("subtitles", "ger", "SubRip/SRT", forced=True) == "Deutsch SRT (forced)"


def _files(tmp_path, n=1):
    from panepilot import mkvtracks as mt

    out = []
    for i in range(n):
        data = json.loads(json.dumps(IDENTIFY))
        if i == 1:
            data["tracks"] = data["tracks"][:2]  # zweiter Film: nur eine Tonspur
        out.append(mt.FileTracks(str(tmp_path / f"film{i}.mkv"), mt.parse_identify(data)))
    return out


def test_track_dialog_single_and_many(window, tmp_path):  # noqa: F811
    from panepilot.trackdialog import TrackDialog, parse_lang

    assert parse_lang("Deutsch (ger)") == "ger" and parse_lang("eng") == "eng" and parse_lang("Deutsch") == "ger"
    dlg = TrackDialog(window, _files(tmp_path))
    assert dlg.table.rowCount() == 4
    w = dlg.widgets[1]  # Tonspur 1
    w["lang"].setCurrentIndex(w["lang"].findData("ger"))
    dlg.table.selectRow(1)
    dlg.suggest_names()
    assert w["name"].text() == "Deutsch AC3 5.1"
    dlg.widgets[3]["forced"].setChecked(True)
    edits, missing = dlg.edits()
    path = str(tmp_path / "film0.mkv")
    assert list(edits) == [path] and not missing
    changes = {tr.number: ch for tr, ch in edits[path]}
    assert changes[2].lang == "ger" and changes[2].name == "Deutsch AC3 5.1" and changes[4].forced is True
    # mehrere Dateien: Tonspur 2 fehlt im zweiten Film (L-1105)
    many = TrackDialog(window, _files(tmp_path, 2))
    labels = [many.table.item(r, 0).text() for r in range(many.table.rowCount())]
    assert labels[2].startswith("Tonspur 2") and "(in 1 von 2)" in labels[2]
    many.widgets[1]["lang"].setCurrentIndex(many.widgets[1]["lang"].findData("ger"))
    many.widgets[2]["lang"].setCurrentIndex(many.widgets[2]["lang"].findData("ger"))
    edits, missing = many.edits()
    assert len(edits) == 2 and missing == ["film1.mkv – Tonspur 2"]


def test_meta_tracks_flow(window, tmp_path, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import metacontrol
    from panepilot import mkvtracks as mt
    from panepilot.trackdialog import TrackDialog

    folder = tmp_path / "F"
    folder.mkdir()
    shutil.copy(os.path.join(VIDEO, "clip.mkv"), folder / "a.mkv")
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), folder / "b.mp4")
    pane = _open(window, qtbot, folder)
    assert pane.convert_buttons[cv.TRACKS].isVisibleTo(pane)
    written = []
    monkeypatch.setattr(mt, "available", lambda: True)
    monkeypatch.setattr(mt, "read", lambda p: mt.FileTracks(p, mt.parse_identify(IDENTIFY)))
    monkeypatch.setattr(mt, "write", lambda p, edits: written.append((p, edits)))
    asked = []
    monkeypatch.setattr("panepilot.dialogs.confirm", lambda parent, title, text, **k: asked.append(text) or True)

    def run(self):
        self.widgets[1]["lang"].setCurrentIndex(self.widgets[1]["lang"].findData("ger"))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TrackDialog, "exec", run)
    window.meta_convert(cv.TRACKS)
    assert len(written) == 1 and written[0][0].endswith("a.mkv")
    assert "1 Spuren in 1 Dateien" in asked[0] and "keine MKV" in asked[0]
    # nur MP4 markiert: Hinweis statt Dialog (L-1101)
    infos = []
    monkeypatch.setattr("panepilot.dialogs.show_info", lambda parent, title, text: infos.append(text))
    mp4 = [it for it in pane.meta_model.items if it.record.name == "b.mp4"]
    pane.meta_view.select_items(mp4)
    window.meta_convert(cv.TRACKS)
    assert infos and "MKV" in infos[0]
    errors = []
    monkeypatch.setattr(metacontrol, "show_error", lambda *a: errors.append(a))
    window.meta_close()


@pytest.mark.skipif(shutil.which("mkvpropedit") is None or shutil.which("mkvmerge") is None,
                    reason="mkvtoolnix fehlt")
def test_mkv_tracks_real(tmp_path):
    from panepilot import mkvtracks as mt
    from panepilot import tags as tg

    path = str(tmp_path / "film.mkv")
    shutil.copy(os.path.join(VIDEO, "clip.mkv"), path)
    files = mt.read(path)
    assert not files.error and files.tracks
    audio = files.find("audio", 1)
    assert audio is not None
    mt.write(path, [(audio, mt.TrackChange(lang="ger", name="Deutsch Test", default=True))])
    again = mt.read(path).find("audio", 1)
    assert again.lang in ("ger", "deu") and again.name == "Deutsch Test" and again.default
    rec = tg.read_file(path)
    assert rec.audio_tracks and rec.audio_tracks[0].lang in ("ger", "deu", "de")
    assert rec.audio_tracks[0].title == "Deutsch Test"


# --- Serien --------------------------------------------------------------------------------------------
def test_episode_ref():
    from panepilot import moviedb as md

    r = md.episode_ref("/m/Breaking Bad/Staffel 1/Breaking Bad - S01E02 - Cat's in the Bag.mkv")
    assert (r.series, r.season, r.episode) == ("Breaking Bad", 1, 2)
    r = md.episode_ref("/m/Breaking Bad (2008) [tmdbid-1396]/S02E10.mkv")
    assert (r.series, r.year, r.tmdb, r.season, r.episode) == ("Breaking Bad", "2008", "1396", 2, 10)
    r = md.episode_ref("/m/Serien/Dark.s1e3.mkv")
    assert (r.series, r.season, r.episode) == ("Dark", 1, 3)
    r = md.episode_ref("/m/x/Lost 1x05.mp4")
    assert (r.series, r.season, r.episode) == ("Lost", 1, 5)
    assert md.episode_ref("/m/Filme/Alien (1979).mkv") is None
    assert md.episode_ref("/m/Filme/Mission S1000.mkv") is None


SHOW = {"id": 1396, "name": "Breaking Bad", "genres": [{"name": "Drama"}, {"name": "Krimi"}], "poster_path": "/bb.jpg"}
SEASON_DE = {"poster_path": "/s1.jpg", "episodes": [
    {"episode_number": 1, "name": "Der Einstieg", "overview": "Walter White …", "air_date": "2008-01-20"},
    {"episode_number": 2, "name": "Episode 2", "overview": "", "air_date": "2008-01-27"}]}
SEASON_EN = {"episodes": [{"episode_number": 2, "name": "Cat's in the Bag...", "overview": "Walt and Jesse …"}]}


class FakeTv:
    def __init__(self):
        self.urls = []

    def __call__(self, url, headers=None, service="tmdb"):
        self.urls.append(url)
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.netloc == "image.tmdb.org":
            return PNG
        if u.path.endswith("/search/tv"):
            return json.dumps({"results": [
                {"id": 1396, "name": "Breaking Bad", "first_air_date": "2008-01-20"},
                {"id": 99999, "name": "Breaking Bad (Doku)", "first_air_date": "2015-03-01"}]}).encode()
        if u.path.endswith("/tv/1396"):
            return json.dumps(SHOW).encode()
        if u.path.endswith("/tv/1396/season/1"):
            return json.dumps(SEASON_EN if q.get("language") == "en-US" else SEASON_DE).encode()
        raise AssertionError(url)


def test_tmdb_episode(monkeypatch):
    from panepilot import moviedb as md

    fake = FakeTv()
    monkeypatch.setattr(md, "http_get", fake)
    db = md.Tmdb("k" * 32, "de-DE")
    m = db.episode("1396", 1, 1)
    assert (m.series, m.season, m.episode, m.title, m.year) == ("Breaking Bad", "01", "01", "Der Einstieg", "2008")
    assert m.genres == ["Drama", "Krimi"] and "w500/s1.jpg" in m.poster_url and m.poster == PNG
    m2 = db.episode("1396", 1, 2)  # „Episode 2“ und leere Beschreibung → Englisch (L-930)
    assert m2.title == "Cat's in the Bag..." and m2.overview == "Walt and Jesse …"
    assert sum("/tv/1396/season/1" in u for u in fake.urls) == 2  # je Sprache nur einmal geladen
    assert db.episode("1396", 1, 9) is None


def test_series_flow_in_meta_wizard(window, tmp_path, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import moviedb as md
    from panepilot import tags as tg
    from panepilot.moviedialogs import ChoiceDialog, ReviewDialog

    season = tmp_path / "Breaking Bad" / "Staffel 1"
    season.mkdir(parents=True)
    for n in (1, 2):
        shutil.copy(os.path.join(VIDEO, "clip.mp4"), season / f"Breaking Bad - S01E0{n}.mp4")
    monkeypatch.setattr(md, "http_get", FakeTv())
    monkeypatch.setitem(md._session_key, "key", "k" * 32)
    pane = _open(window, qtbot, season)
    asked = []

    def choose(self):  # zwei Treffer ohne Jahr → einmal für die Serie fragen (L-1111)
        asked.append(self.windowTitle())
        return QDialog.DialogCode.Accepted

    seen = {}

    def review(self):
        seen["texts"] = [self.tree.topLevelItem(i).text(0) for i in range(self.tree.topLevelItemCount())]
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ChoiceDialog, "exec", choose)
    monkeypatch.setattr(ReviewDialog, "exec", review)
    window.meta_convert(cv.ONLINE)
    assert len(asked) == 1
    assert any("Breaking Bad – S01E01 – Der Einstieg" in x for x in seen["texts"])
    items = {it.record.name: it for it in pane.meta_model.items}
    ep1 = items["Breaking Bad - S01E01.mp4"]
    assert ep1.value(tg.EXTRA + "Series") == "Breaking Bad"
    assert ep1.value(tg.EXTRA + "Season") == "01" and ep1.value(tg.EXTRA + "Episode") == "01"
    assert ep1.value(tg.EXTRA + "themoviedb") == "1396" and ep1.value("genre") == "Drama; Krimi"
    assert any("S01E02 – Cat's in the Bag..." in x for x in seen["texts"])  # Titel vorhanden: nicht vorgehakt
    assert items["Breaking Bad - S01E02.mp4"].value("description") == "Walt and Jesse …"
    window.meta_save()
    qtbot.waitUntil(lambda: window.meta_mode.get("save") is None, timeout=10000)
    from mutagen.mp4 import MP4

    tags = MP4(ep1.record.path).tags
    assert tags["tvsh"] == ["Breaking Bad"] and tags["tvsn"] == [1] and tags["tves"] == [1]  # L-1114
    rec = tg.read_file(ep1.record.path)
    assert not any(k.endswith(("tvsh", "tvsn", "tves")) for k in rec.fields)  # nicht als eigene Spalten
    window.meta_close()


def test_series_without_key(window, tmp_path, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import moviedb as md
    from panepilot.moviedialogs import ReviewDialog

    folder = tmp_path / "Dark"
    folder.mkdir()
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), folder / "Dark - S01E01.mp4")
    monkeypatch.setitem(md._session_key, "key", "")
    monkeypatch.setattr(md, "http_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("kein Netz")))
    pane = _open(window, qtbot, folder)
    seen = {}
    monkeypatch.setattr(ReviewDialog, "exec",
                        lambda self: seen.setdefault("t", self.tree.topLevelItem(0).text(0)) and 0)
    window.meta_convert(cv.ONLINE)
    assert "TMDb-Schlüssel" in seen["t"]
    assert not any(it.changed for it in pane.meta_model.items)
    window.meta_close()
