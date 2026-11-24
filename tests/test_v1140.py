"""Tests for 1.14: OpenSubtitles download, adding subtitle files, MTS → MKV, online search fallback and
manual search, new movie fields (Actors, Rating, Certification)."""

import json
import os
import shutil
import struct
import subprocess
import urllib.parse

import pytest
from PySide6.QtWidgets import QDialog

from test_mainwindow import window  # noqa: F401
from test_v093 import _open
from test_v1130 import VIDEO, _mp4_two_audio_sub, _srt, has_ffmpeg, has_mkv

needs_ffmpeg = pytest.mark.skipif(not has_ffmpeg, reason="ffmpeg fehlt")
needs_mkv = pytest.mark.skipif(not (has_ffmpeg and has_mkv), reason="mkvtoolnix fehlt")


# --- OpenSubtitles ------------------------------------------------------------------------------------------
def test_moviehash(tmp_path):
    from panepilot import opensubs as osb

    data = bytes(range(256)) * 1024  # 256 KB
    p = tmp_path / "v.bin"
    p.write_bytes(data)
    value = len(data)
    for chunk in (data[:65536], data[-65536:]):
        for (w,) in struct.iter_unpack("<Q", chunk):
            value = (value + w) & 0xFFFFFFFFFFFFFFFF
    assert osb.moviehash(str(p)) == f"{value:016x}"
    small = tmp_path / "s.bin"
    small.write_bytes(b"x" * 1000)
    assert osb.moviehash(str(small)) == "" and osb.moviehash(str(tmp_path / "fehlt")) == ""


def test_languages_and_names(tmp_path):
    from panepilot import opensubs as osb

    assert osb.to_mkv_lang("de") == "ger" and osb.to_mkv_lang("pt-BR") == "por" and osb.to_mkv_lang("eng") == "eng"
    assert osb.parse_languages("de, en;ger fr") == ["de", "en", "fr"]
    video = str(tmp_path / "Film (2001).mkv")
    taken = set()
    full = osb.Hit(1, "de", file_name="x.srt")
    assert osb.target_name(video, full, taken).endswith("Film (2001).ger.srt")
    assert osb.target_name(video, full, taken).endswith("Film (2001).ger.2.srt")  # gleicher Name (L-1405)
    forced = osb.Hit(2, "en", file_name="x.ass", forced=True)
    assert osb.target_name(video, forced, taken).endswith("Film (2001).eng.forced.ass")
    sdh = osb.Hit(3, "en", file_name="x.zip", sdh=True)
    assert osb.target_name(video, sdh, taken).endswith("Film (2001).eng.sdh.srt")
    hits = [osb.Hit(1, "de", downloads=900), osb.Hit(2, "de", downloads=10, hash_match=True),
            osb.Hit(3, "en", downloads=50, forced=True), osb.Hit(4, "en", downloads=40)]
    assert [h.file_id for h in osb.best_per_language(hits, ["de", "en", "fr"])] == [2, 4]  # L-1404


SEARCH = {"data": [
    {"attributes": {"language": "de", "release": "Film.2001.1080p", "download_count": 1234, "ratings": 8.5,
                    "moviehash_match": True, "hearing_impaired": False, "foreign_parts_only": False,
                    "feature_details": {"title": "Film", "year": 2001},
                    "files": [{"file_id": 111, "file_name": "Film.2001.1080p.srt"}]}},
    {"attributes": {"language": "en", "release": "Film.2001.WEB", "download_count": 50, "hearing_impaired": True,
                    "files": [{"file_id": 222, "file_name": "Film.en.srt"}]}},
    {"attributes": {"language": "en", "files": []}},
]}


class FakeOS:
    """Ersetzt opensubs.http."""

    def __init__(self, quota=False):
        self.calls = []
        self.quota = quota

    def __call__(self, method, url, headers, body=None):
        u = urllib.parse.urlparse(url)
        self.calls.append((method, u.netloc, u.path, urllib.parse.parse_qsl(u.query), headers,
                           json.loads(body) if body else None))
        if u.path.endswith("/login"):
            if json.loads(body)["password"] != "geheim":
                return 401, b'{"message":"invalid"}'
            return 200, json.dumps({"token": "TOK", "base_url": "vip-api.opensubtitles.com",
                                    "user": {"allowed_downloads": 20, "remaining_downloads": 19}}).encode()
        if u.path.endswith("/infos/user"):
            return 200, json.dumps({"data": {"allowed_downloads": 20, "remaining_downloads": 18}}).encode()
        if u.path.endswith("/infos/formats"):
            return 200, b'{"data":{}}'
        if u.path.endswith("/subtitles"):
            q = dict(urllib.parse.parse_qsl(u.query))
            if "moviehash" in q or q.get("query") == "film":
                return 200, json.dumps(SEARCH).encode()
            return 200, b'{"data":[]}'
        if u.path.endswith("/download"):
            if self.quota:
                return 406, b'{"message":"quota","reset_time":"5 hours"}'
            fid = json.loads(body)["file_id"]
            return 200, json.dumps({"link": f"https://dl.example.org/{fid}.srt", "remaining": 17}).encode()
        if u.netloc == "dl.example.org":
            return 200, b"1\n00:00:00,000 --> 00:00:00,800\nHallo\n\n"
        raise AssertionError(url)


def test_client(monkeypatch):
    from panepilot import opensubs as osb

    fake = FakeOS()
    monkeypatch.setattr(osb, "http", fake)
    c = osb.Client("KEY", "alice", "geheim")
    assert c.check() == 18
    assert c.token == "TOK" and c.base == "https://vip-api.opensubtitles.com/api/v1"  # base_url aus der Anmeldung
    hits = c.search(["en", "de"], "abc123", imdb="tt0078748")
    _m, host, path, query, headers, _b = fake.calls[-1]
    assert host == "vip-api.opensubtitles.com" and path.endswith("/subtitles")
    assert query == [("imdb_id", "78748"), ("languages", "de,en"), ("moviehash", "abc123")]  # sortiert
    assert headers["Api-Key"] == "KEY" and headers["Authorization"] == "Bearer TOK"
    assert headers["User-Agent"].startswith("PanePilot v")
    assert [(h.file_id, h.lang, h.hash_match, h.sdh) for h in hits] == [(111, "de", True, False),
                                                                        (222, "en", False, True)]
    c.search(["de"], query="Film", year="2001", season=1, episode=2, tmdb="")
    assert dict(fake.calls[-1][3]) == {"languages": "de", "query": "film", "season_number": "1",
                                       "episode_number": "2"}
    c.search(["de"], tmdb="1399", season=1, episode=2)
    assert dict(fake.calls[-1][3])["parent_tmdb_id"] == "1399"
    assert b"Hallo" in c.download(hits[0]) and c.remaining == 17
    monkeypatch.setattr(osb, "http", FakeOS(quota=True))
    with pytest.raises(osb.QuotaError):
        c.download(hits[0])
    monkeypatch.setattr(osb, "http", FakeOS())
    with pytest.raises(osb.FatalError):
        osb.Client("KEY", "alice", "falsch").check()
    assert osb.Client("KEY").check() is None  # ohne Anmeldung: nur der Schlüssel


def test_settings_section(window, monkeypatch):  # noqa: F811
    from panepilot import opensubs as osb
    from panepilot.settingsdialog import SettingsDialog

    stored = {}
    monkeypatch.setattr(osb, "_session", {})
    monkeypatch.setattr(osb, "store_secret", lambda kind, value: stored.__setitem__(kind, value) or True)
    dlg = SettingsDialog(window)
    assert dlg.os_langs.text() == "de,en"
    dlg.os_key.setText("KEY")
    dlg.os_user.setText("alice")
    dlg.os_password.setText("pw")
    dlg.os_langs.setText("en de")
    dlg.accept()
    assert stored == {"apikey": "KEY", "password": "pw"}
    assert window.settings.get("opensubs_user") == "alice" and window.settings.get("opensubs_languages") == "en, de"
    assert osb.languages(window.settings) == ["en", "de"]


@needs_ffmpeg
def test_meta_subtitles_flow(window, tmp_path, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import mp4tracks as m4
    from panepilot import opensubs as osb
    from panepilot.subsdialog import SubtitleSearchDialog

    folder = tmp_path / "F"
    folder.mkdir()
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), folder / "Film (2001).mp4")
    pane = _open(window, qtbot, folder)
    assert pane.convert_buttons[cv.SUBTITLES].isVisibleTo(pane)
    monkeypatch.setattr(osb, "http", FakeOS())
    monkeypatch.setattr(osb, "_clients", {})
    monkeypatch.setattr(osb, "_session", {"apikey": "KEY", "password": ""})
    seen = {}

    def accept(self):
        seen["rows"] = [(item.text(0), item.checkState(0).name) for _p, item, _h in self.rows]
        self.chk_direct.setChecked(True)
        self.chk_replace.setChecked(False)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SubtitleSearchDialog, "exec", accept)
    window.meta_convert(cv.SUBTITLES)
    assert [s for _t, s in seen["rows"]] == ["Checked", "Checked"]  # je Sprache der beste
    names = sorted(os.listdir(folder))
    assert names == sorted(["Film (2001).mp4", "Film (2001).ger.srt", "Film (2001).eng.sdh.srt",
                            "Film (2001)-Kopie.mp4"])
    subs = [tr for tr in m4.read(str(folder / "Film (2001)-Kopie.mp4")).tracks if tr.kind == "subtitles"]
    assert sorted(tr.lang for tr in subs) == ["deu", "eng"]
    assert "2 Untertitel gespeichert" in pane.summary.text()
    window.meta_close()


# --- Untertiteldateien hinzufügen --------------------------------------------------------------------------
def test_sub_names_and_candidates(tmp_path):
    from panepilot import videoremux as vr

    video = tmp_path / "Film (2001).mkv"
    video.write_text("x")
    for name in ("Film (2001).ger.srt", "Film (2001).eng.forced.srt", "Film (2001).en.sdh.ass",
                 "Film (2001)-Kopie.ger.srt", "Anderer.ger.srt", "Film (2001).txt"):
        (tmp_path / name).write_text("1\n")
    found = [os.path.basename(p) for p in vr.subtitle_candidates(str(video))]
    assert found == ["Film (2001).en.sdh.ass", "Film (2001).eng.forced.srt", "Film (2001).ger.srt"]
    a = vr.parse_sub_name(str(video), str(tmp_path / "Film (2001).eng.forced.srt"))
    assert (a.lang, a.forced) == ("eng", True)
    assert vr.parse_sub_name(str(video), str(tmp_path / "Film (2001).en.sdh.ass")).lang == "eng"
    assert vr.parse_sub_name(str(video), str(tmp_path / "x.srt")).lang == "und"
    (tmp_path / "w.srt").write_bytes("Größe\n".encode("cp1252"))
    (tmp_path / "u.srt").write_bytes("Größe\n".encode("utf-8"))
    assert vr._sub_charset(str(tmp_path / "w.srt")) == "CP1252" and vr._sub_charset(str(tmp_path / "u.srt")) == "UTF-8"
    mp4 = vr.mt.FileTracks("x.mp4", [], fmt="mp4")
    assert vr.add_problem(mp4, [vr.SubAdd("a.sup")]) and not vr.add_problem(mp4, [vr.SubAdd("a.srt")])


def test_add_dialog(window, tmp_path):  # noqa: F811
    from panepilot import mkvtracks as mt
    from panepilot.subsdialog import AddSubtitlesDialog
    from panepilot.trackdialog import TrackDialog

    video = tmp_path / "Film.mkv"
    video.write_text("x")
    (tmp_path / "Film.ger.srt").write_text("1\n")
    (tmp_path / "Film.eng.forced.srt").write_text("1\n")
    one = mt.FileTracks(str(video), [mt.MkvTrack(1, "video", 1), mt.MkvTrack(2, "audio", 1)])
    dlg = AddSubtitlesDialog(window, one)
    adds = dlg.additions()
    assert [(os.path.basename(a.path), a.lang, a.forced) for a in adds] == [("Film.eng.forced.srt", "eng", True),
                                                                           ("Film.ger.srt", "ger", False)]
    assert adds[1].name == "Deutsch SRT"
    dlg.widgets[0]["use"].setChecked(False)
    assert len(dlg.additions()) == 1
    td = TrackDialog(window, [one])
    assert td.btn_add.isEnabled() and td.additions() == {}
    td.adds = dlg.additions()
    assert list(td.additions()) == [str(video)]
    two = mt.FileTracks(str(tmp_path / "b.mkv"), [mt.MkvTrack(1, "video", 1)])
    assert not TrackDialog(window, [one, two]).btn_add.isEnabled()  # nur bei einem Video (L-1410)
    mp4 = mt.FileTracks(str(tmp_path / "Film.mp4"), [mt.MkvTrack(1, "video", 1)], fmt="mp4")
    (tmp_path / "Film.ger.sup").write_bytes(b"PG")
    d4 = AddSubtitlesDialog(window, mp4)
    sup = [w for w in d4.widgets if w["path"].endswith(".sup")][0]
    assert not sup["use"].isEnabled()  # Bild-Untertitel nur in MKV (L-1412)


@needs_ffmpeg
def test_add_subtitles_mp4(tmp_path):
    from mutagen.mp4 import MP4

    from panepilot import mp4tracks as m4
    from panepilot import videoremux as vr

    src = _mp4_two_audio_sub(tmp_path)
    tags = MP4(src)
    tags["\xa9nam"] = ["Testfilm"]
    tags.save()
    srt = tmp_path / "Film (2001).eng.forced.srt"
    srt.write_bytes("1\n00:00:00,000 --> 00:00:00,800\nGrüße\n\n".encode("cp1252"))
    f = m4.read(src)
    new = vr.remove_tracks(f, [], [], add=[vr.SubAdd(str(srt), "eng", "Englisch (forced)", forced=True)])
    assert os.path.basename(new) == "Film (2001)-Kopie.mp4" and srt.exists()  # Datei bleibt (L-1411)
    subs = [tr for tr in m4.read(new).tracks if tr.kind == "subtitles"]
    assert [(tr.lang, tr.name) for tr in subs] == [("deu", ""), ("eng", "Englisch (forced)")]
    assert MP4(new)["\xa9nam"] == ["Testfilm"]
    out = tmp_path / "check.srt"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", new, "-map", "0:s:1", str(out)], check=True)
    assert "Grüße" in out.read_text(encoding="utf-8")  # Windows-Zeichensatz erkannt
    with pytest.raises(OSError):
        vr.remove_tracks(f, [], [], add=[vr.SubAdd(str(tmp_path / "x.sup"))])
    # Original ersetzen
    again = vr.remove_tracks(m4.read(src), [], [], add=[vr.SubAdd(str(srt), "eng")], replace=True)
    assert again == src and len([tr for tr in m4.read(src).tracks if tr.kind == "subtitles"]) == 2


@needs_mkv
def test_add_subtitles_mkv_and_track_dialog(window, tmp_path, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import mkvtracks as mt
    from panepilot import videoremux as vr
    from panepilot.trackdialog import TrackDialog

    folder = tmp_path / "F"
    folder.mkdir()
    mp4 = _mp4_two_audio_sub(tmp_path, "Quelle.mp4")
    vr.convert(mp4, vr.MKV, None)
    shutil.move(str(tmp_path / "Quelle.mkv"), folder / "Film.mkv")
    _srt(folder / "Film.ger.forced.srt")
    pane = _open(window, qtbot, folder)
    monkeypatch.setattr("panepilot.dialogs.confirm", lambda parent, title, text, **k: True)

    def add(self):
        from panepilot.subsdialog import AddSubtitlesDialog

        self.adds = AddSubtitlesDialog(self, self.files[0]).additions()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TrackDialog, "exec", add)
    asked = []  # v2.6, L-3612: danach wird gefragt, was mit den Untertiteldateien geschieht
    monkeypatch.setattr(type(window), "_ask_subs_dispose", lambda self, paths, title: asked.append(paths) or "keep")
    pane.meta_view.select_items([it for it in pane.meta_model.items if it.record.name == "Film.mkv"])
    window.meta_convert(cv.TRACKS)
    new = folder / "Film-Kopie.mkv"
    assert new.exists()
    subs = [tr for tr in mt.read(str(new)).tracks if tr.kind == "subtitles"]
    assert [(tr.lang, tr.forced) for tr in subs][-1] == ("ger", True)
    assert asked and (folder / "Film.ger.forced.srt").exists()
    window.meta_close()


# --- MTS → MKV ---------------------------------------------------------------------------------------------
def test_mts_problem():
    from panepilot import videoremux as vr

    assert vr.convert_problem("a.mts", vr.MKV) == "" and vr.convert_problem("a.M2TS", vr.MKV) == ""
    assert vr.convert_problem("a.mts", vr.MP4) != ""


@needs_mkv
def test_mts_to_mkv(tmp_path):
    from panepilot import mkvtracks as mt
    from panepilot import mp4tracks as m4
    from panepilot import videoremux as vr

    src = str(tmp_path / "Urlaub.m2ts")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(VIDEO, "clip.mp4"), "-c:v", "copy",
                    "-c:a", "ac3", "-f", "mpegts", src], check=True)  # wie beim Camcorder: AC3-Ton
    new = vr.convert(src, vr.MKV, m4.read(src))
    assert new.endswith("Urlaub.mkv") and os.path.exists(src)
    kinds = [tr.kind for tr in mt.read(new).tracks]
    assert kinds == [tr.kind for tr in m4.read(src).tracks], kinds  # keine Spur verloren


# --- Online-Daten ------------------------------------------------------------------------------------------
def test_title_variants_and_fallback():
    from panepilot import moviedb as md

    assert md.title_variants("Die Olsenbande faehrt nach Juetland") == ["Die Olsenbande faehrt nach Juetland",
                                                                       "Die Olsenbande fährt nach Jütland"]
    assert md.title_variants("Strasse") == ["Strasse", "Straße"]
    calls = []

    def search(title, year):
        calls.append((title, year))
        return ["hit"] if (title, year) == ("Die Olsenbande fährt nach Jütland", "") else []

    assert md.search_fallback(search, "Die Olsenbande faehrt nach Juetland", "1971") == ["hit"]
    assert calls == [("Die Olsenbande faehrt nach Juetland", "1971"), ("Die Olsenbande fährt nach Jütland", "1971"),
                     ("Die Olsenbande faehrt nach Juetland", ""), ("Die Olsenbande fährt nach Jütland", "")]
    assert md.search_fallback(lambda t, y: [], "Nix") == []


def test_new_fields(monkeypatch):
    from panepilot import moviedb as md
    from panepilot import moviedialogs as mdl

    data = {"id": 1, "title": "Film", "release_date": "2001-01-01", "genres": [], "imdb_id": "tt1",
            "vote_average": 7.84, "vote_count": 1200,
            "credits": {"crew": [], "cast": [{"name": f"P{i}", "order": i} for i in range(7, 0, -1)]},
            "release_dates": {"results": [{"iso_3166_1": "US", "release_dates": [{"certification": "R"}]},
                                          {"iso_3166_1": "DE", "release_dates": [
                                              {"certification": "", "type": 1},
                                              {"certification": "12", "type": 3}]}]}}
    monkeypatch.setattr(md, "http_get", lambda url, headers=None, service="tmdb": json.dumps(data).encode())
    m = md.Tmdb("k" * 32, "de-DE").movie("1", with_poster=False)
    assert m.actors == ["P1", "P2", "P3", "P4", "P5"] and m.rating == "7.8" and m.certification == "FSK 12"
    assert md.Tmdb("k" * 32, "en-US").movie("1", with_poster=False).certification == "R"
    assert md._rating({"vote_average": 5, "vote_count": 0}) == ""

    class Item:
        record = type("R", (), {"kind": "video-mkv"})()
        display_name = "Film.mkv"

        def readonly(self, key):
            return False

        def value(self, key):
            return ""

    from panepilot import tags as tg

    props = {k: new for k, _old, new, _v in mdl.proposals(mdl.Job(Item(), movie=m))}
    assert props[tg.EXTRA + "Actors"] == "P1; P2; P3; P4; P5" and props[tg.EXTRA + "Rating"] == "7.8"
    assert props[tg.EXTRA + "Certification"] == "FSK 12"


def test_manual_search(window, monkeypatch):  # noqa: F811
    from panepilot import moviedb as md
    from panepilot import moviedialogs as mdl
    from panepilot import netutil

    class Item:
        record = type("R", (), {"kind": "video-mkv", "path": "/x/Olsenbande.mkv"})()
        display_name = "Olsenbande.mkv"

        def readonly(self, key):
            return False

        def value(self, key):
            return ""

    class Service:
        source = md.SOURCE_TMDB

        def search(self, title, year=""):
            return [md.Hit("Die Olsenbande fährt nach Jütland", "1971", tmdb="11")] if "Jütland" in title else []

        def load(self, imdb="", tmdb="", qid=""):
            return md.Movie(md.SOURCE_TMDB, title="Die Olsenbande fährt nach Jütland", year="1971", tmdb=tmdb)

    job = mdl.Job(Item(), title="Olsenbande", year="", reason="nicht gefunden")
    dlg = mdl.ReviewDialog(window, [job], md.SOURCE_TMDB, Service())
    assert not dlg.rows and not dlg.btn_ok.isEnabled()
    holder = dlg.tree.topLevelItem(0).child(0)
    assert dlg.tree.itemWidget(holder, 0).text() == "Manuell suchen …"
    monkeypatch.setattr(netutil, "run_blocking", lambda parent, fn, text, title: (fn(), None))
    monkeypatch.setattr(mdl.ManualSearchDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(mdl.ManualSearchDialog, "values", lambda self: ("Olsenbande faehrt nach Juetland", "", ""))
    monkeypatch.setattr(mdl.ChoiceDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    monkeypatch.setattr(mdl.ChoiceDialog, "selected",
                        lambda self: md.Hit("Die Olsenbande fährt nach Jütland", "1971", tmdb="11"))
    dlg.manual(job)
    assert job.movie is not None and job.tmdb == "11"
    assert dlg.rows and dlg.btn_ok.isEnabled()
    assert any(key == "title" and value == "Die Olsenbande fährt nach Jütland" for _j, _c, key, value in dlg.rows)
