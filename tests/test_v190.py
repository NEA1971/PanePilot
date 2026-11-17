"""Tests for 1.9: online movie data (TMDB with API key, Wikidata without) – network calls are faked."""

import json
import os
import shutil
import urllib.parse

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from test_mainwindow import window  # noqa: F401
from test_v093 import _open

VIDEO = os.path.join(os.path.dirname(__file__), "data", "video")


def _png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (20, 30), (200, 40, 40)).save(buf, "PNG")
    return buf.getvalue()


PNG = _png()

ALIEN = {"id": 348, "title": "Alien – Das unheimliche Wesen aus einer fremden Welt", "original_title": "Alien",
         "release_date": "1979-05-25", "overview": "Die Besatzung der Nostromo …",
         "genres": [{"id": 27, "name": "Horror"}, {"id": 878, "name": "Science Fiction"}],
         "imdb_id": "tt0078748", "poster_path": "/alien.jpg",
         "credits": {"crew": [{"job": "Director", "name": "Ridley Scott"}, {"job": "Writer", "name": "Dan O'Bannon"}]}}
HEAT_DE = {"id": 949, "title": "Heat", "original_title": "Heat", "release_date": "1995-12-15", "overview": "",
           "genres": [{"name": "Krimi"}], "imdb_id": "tt0113277", "poster_path": None, "credits": {"crew": []}}
HEAT_EN = {"id": 949, "title": "Heat", "overview": "Obsessive master thief …", "genres": [{"name": "Crime"}]}


class FakeNet:
    """Ersetzt moviedb.http_get; merkt sich die Anfragen."""

    def __init__(self, status=None):
        self.urls = []
        self.status = status

    def __call__(self, url, headers=None, service="tmdb"):
        from panepilot import moviedb as md

        self.urls.append(url)
        if self.status:
            raise md.FatalError(self.status)
        u = urllib.parse.urlparse(url)
        q = dict(urllib.parse.parse_qsl(u.query))
        if u.netloc == "image.tmdb.org":
            return PNG
        if u.path.endswith("/find/tt0078748"):
            return json.dumps({"movie_results": [{"id": 348}]}).encode()
        if u.path.endswith("/movie/348"):
            return json.dumps(ALIEN).encode()
        if u.path.endswith("/movie/949"):
            return json.dumps(HEAT_EN if q.get("language") == "en-US" else HEAT_DE).encode()
        if u.path.endswith("/movie/8196"):
            return json.dumps({"id": 8196, "title": "Ronin", "release_date": "1998-01-01", "genres": [],
                               "overview": "x", "imdb_id": "tt0122690", "credits": {"crew": []}}).encode()
        if u.path.endswith("/search/movie"):
            if q["query"] == "Heat":
                return json.dumps({"results": [{"id": 949, "title": "Heat", "release_date": "1995-12-15"},
                                               {"id": 950, "title": "Heat", "release_date": "1986-03-14"}]}).encode()
            if q["query"] == "Ronin":
                return json.dumps({"results": [{"id": 8195, "title": "Ronin", "release_date": "1998-09-12"},
                                               {"id": 8196, "title": "Ronin", "release_date": "1998-01-01",
                                                "poster_path": "/r.jpg"}]}).encode()
            return json.dumps({"results": []}).encode()
        if u.path.endswith("/configuration"):
            return b"{}"
        raise AssertionError(url)


@pytest.fixture
def net(monkeypatch):
    from panepilot import moviedb as md

    fake = FakeNet()
    monkeypatch.setattr(md, "http_get", fake)
    monkeypatch.setitem(md._session_key, "key", "k" * 32)
    return fake


def test_ids_titles_and_language():
    from panepilot import moviedb as md

    assert md.ids_from_name("Alien (1979) [imdbid-tt0078748].mkv") == ("tt0078748", "")
    assert md.ids_from_name("Heat (1995) {tmdb-949}.mp4") == ("", "949")
    assert md.title_year("Alien (1979) [imdbid-tt0078748].mkv") == ("Alien", "1979")
    assert md.title_year("Der.Pate.mp4") == ("Der Pate", "")
    assert md.clean_imdb("https://www.imdb.com/title/tt0078748/") == "tt0078748"
    assert md.clean_tmdb("348") == "348" and md.clean_tmdb("tt0078748") == ""
    assert md.language("frk") == "de-DE" and md.language("en") == "en-US" and md.language("ru") == "ru-RU"
    hits = [md.Hit("Heat", "1995"), md.Hit("Heat", "1986")]
    assert md.pick(hits, "1995").year == "1995" and md.pick(hits, "") is None


def test_tmdb_movie_with_fallback_to_english(net):
    from panepilot import moviedb as md

    db = md.Tmdb("k" * 32, "de-DE")
    m = db.load(imdb="tt0078748")
    assert m.title.startswith("Alien") and m.original_title == "Alien" and m.year == "1979"
    assert m.genres == ["Horror", "Science Fiction"] and m.directors == ["Ridley Scott"]
    assert m.imdb == "tt0078748" and m.tmdb == "348" and m.poster == PNG
    assert "w500/alien.jpg" in m.poster_url and "api_key=" in net.urls[0]
    heat = db.load(tmdb="949")
    assert heat.overview == "Obsessive master thief …"  # L-930: Englisch, wenn Deutsch fehlt
    assert heat.genres == ["Krimi"]
    long = md.Tmdb("eyJ" + "x" * 100, "de-DE")  # Lesezugriffstoken
    calls = []
    md.http_get = lambda url, headers=None, service="tmdb": calls.append(headers) or b"{}"
    long.check()
    assert calls[0]["Authorization"].startswith("Bearer ")


def test_wikidata_parsing(monkeypatch):
    from panepilot import moviedb as md

    rows = [{"item": {"value": "http://www.wikidata.org/entity/Q103569"}, "itemLabel": {"value": "Alien"},
             "orig": {"value": "Alien"}, "date": {"value": "1979-10-25T00:00:00Z"},
             "genreLabel": {"value": "Science-Fiction-Film"}, "links": {"value": "80"}, "dirLabel": {"value": "Ridley Scott"},
             "imdb": {"value": "tt0078748"}, "tmdb": {"value": "348"}},
            {"item": {"value": "http://www.wikidata.org/entity/Q103569"}, "itemLabel": {"value": "Alien"},
             "date": {"value": "1979-05-25T00:00:00Z"}, "genreLabel": {"value": "Horrorfilm"}, "links": {"value": "90"}}]
    seen = []

    def fake(url, headers=None, service="tmdb"):
        seen.append((url, service))
        if "list=search" in url:
            assert "haswbstatement" in urllib.parse.unquote_plus(url)
            return json.dumps({"query": {"search": [{"title": "Q103569"}, {"title": "Q42"}]}}).encode()
        return json.dumps({"results": {"bindings": rows}}).encode()

    monkeypatch.setattr(md, "http_get", fake)
    wd = md.Wikidata("de-DE")
    m = wd.load(imdb="tt0078748")
    assert m.title == "Alien" and m.year == "1979" and m.genres == ["Horrorfilm", "Science-Fiction-Film"]
    assert m.directors == ["Ridley Scott"] and m.tmdb == "348" and m.poster is None and not m.overview
    assert "P345" in urllib.parse.unquote(seen[0][0]) and seen[0][1] == "wikidata"
    hits = wd.search("Alien", "1979")
    assert len(hits) == 1 and hits[0].qid == "Q103569" and hits[0].year == "1979"
    assert md.service("") .source == md.SOURCE_WIKIDATA and md.service("x").source == md.SOURCE_TMDB


def _videos(tmp_path):
    folder = tmp_path / "Filme"
    folder.mkdir()
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), folder / "Alien (1979) [imdbid-tt0078748].mp4")
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), folder / "Heat (1995).mp4")
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), folder / "Ronin (1998).mp4")
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), folder / "Unbekannt.mp4")
    shutil.copy(os.path.join(VIDEO, "clip.avi"), folder / "Alt (1979) [imdbid-tt0078748].avi")
    return folder


def test_online_flow_in_meta_wizard(window, tmp_path, net, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import metaprofile as mp
    from panepilot import tags as tg
    from panepilot.moviedialogs import ChoiceDialog, ReviewDialog

    pane = _open(window, qtbot, _videos(tmp_path))
    assert mp.is_video_mode() and pane.convert_buttons[cv.ONLINE].isVisibleTo(pane)
    items = {it.record.name: it for it in pane.meta_model.items}
    alien = items["Alien (1979) [imdbid-tt0078748].mp4"]
    old_title = alien.value("title")
    asked = []

    def choose(self):  # Ronin: zwei Treffer aus 1998 → Auswahl; den zweiten nehmen
        asked.append(self.list.count())
        self.list.setCurrentRow(1)
        return QDialog.DialogCode.Accepted

    seen = {}

    def review(self):
        seen["dlg"] = self
        texts = [self.tree.topLevelItem(i).text(0) for i in range(self.tree.topLevelItemCount())]
        seen["texts"] = texts
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ChoiceDialog, "exec", choose)
    monkeypatch.setattr(ReviewDialog, "exec", review)
    window.meta_convert(cv.ONLINE)
    assert asked == [2]
    texts = seen["texts"]
    assert any("Unbekannt.mp4" in x and "nicht gefunden" in x for x in texts)
    assert any(x.startswith("Alt (1979)") and "nur lesbar" in x for x in texts)  # AVI: L-945
    assert any(x.startswith("Ronin (1998).mp4 → Ronin") for x in texts)
    # Vorgabe: vorhandener Titel nicht angehakt, leere Felder angehakt (L-941)
    rows = {(job.item.record.name, key): child for job, child, key, _v in seen["dlg"].rows}
    title_row = rows[(alien.record.name, "title")]
    assert (title_row.checkState(0) == Qt.CheckState.Unchecked) == bool(old_title)
    assert rows[(alien.record.name, "description")].checkState(0) == Qt.CheckState.Checked
    assert (alien.record.name, "x:imdbid") in rows  # Kennung aus dem Dateinamen wird als Feld ergänzt
    # Ergebnis: grüne Vormerkung, noch nicht gespeichert
    assert alien.value("description") == "Die Besatzung der Nostromo …"
    assert alien.value("author") == "Ridley Scott" and alien.value("genre") == "Horror; Science Fiction"
    assert alien.value(tg.EXTRA + "themoviedb") == "348" and alien.value(tg.EXTRA + "originaltitle") == "Alien"
    assert alien.pending_pictures and alien.pending_pictures[0].data == PNG
    heat = items["Heat (1995).mp4"]
    assert heat.value(tg.EXTRA + "imdbid") == "tt0113277" and heat.value("year") == "1995"
    assert items["Ronin (1998).mp4"].value(tg.EXTRA + "themoviedb") == "8196"
    assert tg.read_file(alien.record.path).fields.get("description", "") != "Die Besatzung der Nostromo …"
    window.meta_save()
    qtbot.waitUntil(lambda: window.meta_mode.get("save") is None, timeout=10000)
    rec = tg.read_file(alien.record.path)
    assert rec.fields["description"] == "Die Besatzung der Nostromo …" and rec.pictures
    assert any(rec.labels.get(k, "").casefold() == "themoviedb" and v == "348" for k, v in rec.fields.items())
    window.meta_close()


def test_review_buttons_all_and_empty(window, tmp_path, net, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot.moviedialogs import ReviewDialog

    folder = tmp_path / "F"
    folder.mkdir()
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), folder / "Alien (1979) [imdbid-tt0078748].mp4")
    pane = _open(window, qtbot, folder)
    it = pane.meta_model.items[0]
    it.set("title", "Alter Titel")
    seen = {}

    def review(self):
        rows = {key: child for _j, child, key, _v in self.rows}
        seen["before"] = rows["title"].checkState(0)
        self.set_all(True)
        seen["all"] = rows["title"].checkState(0)
        self.set_all(False)
        seen["empty"] = rows["title"].checkState(0)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ReviewDialog, "exec", review)
    window.meta_convert(cv.ONLINE)
    assert seen == {"before": Qt.CheckState.Unchecked, "all": Qt.CheckState.Checked,
                    "empty": Qt.CheckState.Unchecked}
    assert it.value("title") == "Alter Titel"  # abgebrochen: nichts verändert
    window.meta_discard() if hasattr(window, "meta_discard") else None
    window.meta_close()


def test_bad_key_and_no_connection(window, tmp_path, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import metacontrol
    from panepilot import moviedb as md

    pane = _open(window, qtbot, _videos(tmp_path))
    errors = []
    monkeypatch.setattr(metacontrol, "show_error", lambda parent, title, text: errors.append(text))
    monkeypatch.setitem(md._session_key, "key", "falsch")
    monkeypatch.setattr(md, "http_get", FakeNet("401"))
    window.meta_convert(cv.ONLINE)
    monkeypatch.setattr(md, "http_get", FakeNet("Name or service not known"))
    window.meta_convert(cv.ONLINE)
    assert "abgelehnt" in errors[0] and "Keine Verbindung" in errors[1]
    assert not any(it.changed for it in pane.meta_model.items)
    window.meta_close()


def test_settings_online_section(window, monkeypatch):  # noqa: F811
    from panepilot import moviedb as md
    from panepilot.settingsdialog import SettingsDialog

    monkeypatch.setitem(md._session_key, "key", "")
    stored = []
    monkeypatch.setattr(md, "store_key", lambda key: stored.append(key) or True)
    dlg = SettingsDialog(window)
    assert dlg.tmdb_key.text() == ""
    texts = [w.text() for w in dlg.findChildren(type(dlg._hint("", dlg)))]
    assert any("Programmsprache" in x for x in texts) and any("TMDb-API" in x for x in texts)
    dlg.tmdb_key.setText("abc123")
    dlg.accept()
    assert stored == ["abc123"]
