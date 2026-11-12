"""Tests for 1.2: update check, Upper Saxon language, disc assistant, MusicBrainz (no network: mocked data)."""

import datetime as dt
import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from test_mainwindow import window  # noqa: F401

DATA = Path(__file__).parent / "data" / "audio"


# --- Update-Suche -------------------------------------------------------------------------------------
GH_RELEASE = {
    "tag_name": "v9.1.0", "html_url": "https://github.com/NEA1971/PanePilot/releases/tag/v9.1.0",
    "body": "English notes\n\n---\n\nDeutsche Notizen",
    "assets": [{"name": "PanePilot-9.1.0-x86_64.AppImage.zsync", "browser_download_url": "z", "size": 1},
               {"name": "PanePilot-9.1.0-x86_64.AppImage", "browser_download_url": "https://x/a", "size": 1234}],
}


def test_version_compare_and_parse():
    from panepilot import updatecheck as uc

    assert uc.is_newer("1.2.1", "1.2.0") and uc.is_newer("1.10.0", "1.9.9")
    assert not uc.is_newer("1.2.0", "1.2.0") and not uc.is_newer("v1.1.9", "1.2.0")
    rel = uc.parse_release(GH_RELEASE)
    assert rel.version == "9.1.0" and rel.asset_name == "PanePilot-9.1.0-x86_64.AppImage"
    assert rel.asset_url == "https://x/a" and rel.asset_size == 1234
    assert uc._short_notes(rel.notes).startswith("Deutsche Notizen")  # Testsprache ist Deutsch


def test_due_today(window):  # noqa: F811
    from panepilot import updatecheck as uc

    s = window.settings
    assert s.get("update_check") is False  # Vorgabe: aus
    assert not uc.due_today(s)
    s.set("update_check", True)
    assert uc.due_today(s, dt.date(2026, 11, 12))
    s.set("update_last_check", "2026-11-12")
    assert not uc.due_today(s, dt.date(2026, 11, 12)) and uc.due_today(s, dt.date(2026, 11, 13))


def test_target_path(tmp_path, monkeypatch):
    from panepilot import updatecheck as uc

    rel = uc.parse_release(GH_RELEASE)
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert uc.target_path(rel) is None
    monkeypatch.setenv("APPIMAGE", str(tmp_path / "PanePilot_2026-11-11a.AppImage"))
    assert uc.target_path(rel) == str(tmp_path / "PanePilot-9.1.0-x86_64.AppImage")


def test_handle_release_choices(window, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import updatecheck as uc

    rel = uc.parse_release(GH_RELEASE)
    monkeypatch.setenv("APPIMAGE", str(tmp_path / "old.AppImage"))
    choice = {"value": uc.UpdateDialog.SKIP}
    shown = []

    def fake_exec(dlg):
        shown.append(dlg.btn_download.text())
        dlg.choice = choice["value"]
        return 1
    monkeypatch.setattr(uc.UpdateDialog, "exec", fake_exec)
    uc.handle_release(window, rel, manual=False)
    assert shown == ["Herunterladen"] and window.settings.get("update_skip") == "9.1.0"
    uc.handle_release(window, rel, manual=False)  # übersprungen → automatisch nicht mehr
    assert len(shown) == 1
    # Herunterladen → Datei landet neben der alten, ausführbar, dann Frage nach Neustart
    choice["value"] = uc.UpdateDialog.DOWNLOAD

    def fake_download(url, target, progress, cancel):
        Path(target).write_bytes(b"\x7fELF")
        progress(4, 4)
    monkeypatch.setattr(uc.netutil, "download", fake_download)
    asked, started = [], []
    monkeypatch.setattr("panepilot.dialogs.confirm", lambda *a, **k: asked.append(a[2]) or True)
    monkeypatch.setattr(uc, "restart_into", lambda w, p: started.append(p))
    uc.handle_release(window, rel, manual=True)
    new = tmp_path / "PanePilot-9.1.0-x86_64.AppImage"
    assert new.exists() and new.stat().st_mode & 0o111
    assert asked and "PanePilot-9.1.0-x86_64.AppImage" in asked[0] and started == [str(new)]
    # ohne AppImage: Release-Seite öffnen
    monkeypatch.delenv("APPIMAGE")
    opened = []
    monkeypatch.setattr("panepilot.util.open_url", lambda u: opened.append(u) or True)
    uc.handle_release(window, rel, manual=True)
    assert shown[-1] == "Release-Seite öffnen" and opened == [rel.page]


def test_manual_check_reports_latest(window, monkeypatch):  # noqa: F811
    from panepilot import __version__
    from panepilot import updatecheck as uc

    infos = []
    monkeypatch.setattr(uc, "fetch_latest", lambda: uc.parse_release(dict(GH_RELEASE, tag_name="v" + __version__)))
    monkeypatch.setattr("panepilot.dialogs.show_info", lambda *a, **k: infos.append(a[2]))
    window.trigger("check_updates")
    assert infos == [f"Du hast schon die neueste Version ({__version__})."]
    assert window.settings.get("update_last_check") == dt.date.today().isoformat()


def test_settings_update_checkbox(window):  # noqa: F811
    from panepilot.settingsdialog import SettingsDialog

    dlg = SettingsDialog(window)
    assert not dlg.update_check.isChecked()
    dlg.update_check.setChecked(True)
    dlg.accept()
    assert window.settings.get("update_check") is True


# --- Säggssch -----------------------------------------------------------------------------------------
def test_upper_saxon_bundled():
    from panepilot import i18n

    langs = i18n.languages()
    assert langs["sxu"].fallback == "de" and not langs["sxu"].user
    i18n.load_language("sxu")
    try:
        assert i18n.t("button.cancel") == "Abbrechn"
        assert i18n.t("conv.musicbrainz") == "MusicBrainz …"
    finally:
        i18n.load_language("de")


# --- Disc-Assistent -----------------------------------------------------------------------------------
def _item(path, **fields):
    from panepilot import tags as tg
    from panepilot.metawizard import MetaItem

    shutil.copy(DATA / ("leer" + Path(path).suffix), path)
    if fields:
        tg.write_file(tg.read_file(str(path)), fields)
    return MetaItem(record=tg.read_file(str(path)))


def test_disc_numbers(tmp_path):
    from panepilot import metaextras as mx

    (tmp_path / "CD1").mkdir()
    (tmp_path / "CD2").mkdir()
    items = [_item(tmp_path / "CD1" / "a.mp3", track="1"), _item(tmp_path / "CD1" / "b.mp3", track="2"),
             _item(tmp_path / "CD2" / "c.mp3", track="1"), _item(tmp_path / "CD2" / "d.mp3", track="2")]
    assert mx.default_disc_mode(items) == mx.DISC_FOLDER
    assert mx.disc_numbers(items, mx.DISC_FOLDER) == [1, 1, 2, 2]
    assert mx.disc_numbers(items, mx.DISC_RESTART) == [1, 1, 2, 2]
    assert mx.disc_numbers(items, mx.DISC_MANUAL, 3) == [3, 3, 3, 3]
    assert mx.disc_total_key("vorbis") == "x:DISCTOTAL" and mx.disc_total_key("id3") == "x:TXXX:DISCTOTAL"


@pytest.mark.parametrize("total", ["none", "pair", "field"])
def test_disc_dialog_changes(tmp_path, total, qtbot):
    from panepilot import metaextras as mx

    items = [_item(tmp_path / f"{i}.flac", track=str(n)) for i, n in enumerate((1, 2, 1))]
    dlg = mx.DiscDialog(None, items, {"total": total})
    assert dlg.mode() == mx.DISC_RESTART  # alles in einem Ordner
    changes = dlg.changes()
    discs = [v["disc"] for _it, v in changes]
    if total == "pair":
        assert discs == ["1/2", "1/2", "2/2"]
    else:
        assert discs == ["1", "1", "2"]
    assert all(("x:DISCTOTAL" in v) == (total == "field") for _it, v in changes)
    if total == "field":
        assert changes[0][1]["x:DISCTOTAL"] == "2"
    dlg.reject()


def test_disc_wizard_in_window(window, tmp_path, qtbot, monkeypatch):  # noqa: F811
    from panepilot.metaextras import DiscDialog

    from test_v093 import _open

    folder = tmp_path / "Album"
    folder.mkdir()
    for i, n in enumerate((1, 2, 1, 2)):
        _item(folder / f"{i}.mp3", track=str(n), title=f"T{i}")
    pane = _open(window, qtbot, folder)

    def fake_exec(dlg):
        dlg.total_buttons["pair"].setChecked(True)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(DiscDialog, "exec", fake_exec)
    window.meta_convert("disc")
    assert [it.value("disc") for it in pane.meta_view.target_items()] == ["1/2", "1/2", "2/2", "2/2"]
    assert window.settings.get("meta_disc")["total"] == "pair"
    window.meta_discard()
    window.meta_close()


# --- MusicBrainz --------------------------------------------------------------------------------------
SEARCH = {"releases": [
    {"id": "r1", "score": 100, "title": "Sample Album", "date": "1999-05-01", "country": "DE", "track-count": 2,
     "artist-credit": [{"name": "Sample Band", "artist": {"id": "a1", "name": "Sample Band"}}],
     "release-group": {"primary-type": "Album"},
     "label-info": [{"catalog-number": "CAT 1", "label": {"name": "Label A"}}],
     "media": [{"format": "CD", "track-count": 2}]},
    {"id": "r2", "score": 80, "title": "Sample Album (Deluxe)", "track-count": 3,
     "artist-credit": [{"name": "Sample Band", "joinphrase": " & "}, {"name": "Guest"}],
     "media": [{"format": "CD"}, {"format": "CD"}]},
]}

RELEASE = {
    "id": "r1", "title": "Sample Album", "date": "2001-01-01", "country": "DE", "barcode": "4006", "asin": "B000",
    "artist-credit": [{"name": "Sample Band", "artist": {"id": "a1", "name": "Sample Band", "sort-name": "Band, Sample"}}],
    "release-group": {"id": "rg1", "primary-type": "Album", "first-release-date": "1999-05-01",
                      "genres": [{"name": "rock", "count": 3}, {"name": "pop", "count": 1}]},
    "label-info": [{"catalog-number": "CAT 1", "label": {"name": "Label A"}}],
    "cover-art-archive": {"front": True},
    "media": [{"position": 1, "track-count": 2, "tracks": [
        {"position": 1, "number": "1", "title": "Morning Light", "length": 200000,
         "recording": {"id": "rec1", "isrcs": ["DEX001"]}},
        {"position": 2, "number": "2", "title": "Evening Rain", "length": 180000,
         "recording": {"id": "rec2", "artist-credit": [
             {"name": "Sample Band", "joinphrase": " feat. ", "artist": {"id": "a1", "sort-name": "Band, Sample"}},
             {"name": "Guest", "artist": {"id": "a2", "sort-name": "Guest"}}]}},
    ]}],
}


def test_search_url_and_parse():
    from urllib.parse import parse_qs, urlparse

    from panepilot import musicbrainz as mb

    q = parse_qs(urlparse(mb.search_url('AC/DC: "Live"', "Band")).query)
    assert q["query"] == ['release:"AC\\/DC\\: \\"Live\\"" AND artist:"Band"'] and q["limit"] == ["50"]
    hits = mb.parse_search(SEARCH)
    assert [h.id for h in hits] == ["r1", "r2"]
    h = hits[0]
    assert (h.type, h.artist, h.tracks, h.year, h.country, h.format, h.label, h.catno) == \
        ("Album", "Sample Band", 2, "1999-05-01", "DE", "CD", "Label A", "CAT 1")
    assert hits[1].artist == "Sample Band & Guest" and hits[1].format == "CD"


def test_parse_release_values():
    from panepilot import musicbrainz as mb

    rel = mb.parse_release(RELEASE)
    a = rel.album_values
    assert a["YEAR"] == "1999" and a["ORIGYEAR"] == "1999"  # Jahr der Erstveröffentlichung
    assert a["GENRE"] == "Rock" and a["PUBLISHER"] == "Label A" and a["ALBUMARTISTSORT"] == "Band, Sample"
    assert a["MUSICBRAINZ_RELEASEGROUPID"] == "rg1" and a["MUSICBRAINZ_ALBUMTYPE"] == "album"
    t1, t2 = rel.tracks
    assert t1.values["TRACK"] == "1/2" and t1.values["DISCNUMBER"] == "1/1" and t1.length == 200
    assert t1.values["ARTIST"] == "Sample Band" and t1.values["ISRC"] == "DEX001"
    assert t2.values["ARTIST"] == "Sample Band feat. Guest" and t2.values["MUSICBRAINZ_ARTISTID"] == "a1; a2"
    assert t2.values["MUSICBRAINZ_TRACKID"] == "rec2" and rel.has_cover


def test_throttle(monkeypatch):
    from panepilot import musicbrainz as mb

    sleeps = []
    clock = iter([100.0, 100.0, 100.2, 100.2])
    monkeypatch.setattr(mb.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(mb.time, "sleep", lambda s: sleeps.append(round(s, 2)))
    monkeypatch.setattr(mb, "_last_request", [0.0])
    mb._throttle()
    mb._throttle()
    assert sleeps == [0.9]  # höchstens eine Abfrage pro Sekunde


@pytest.mark.parametrize("ext", ["mp3", "flac", "m4a", "wma"])
def test_mb_fields_roundtrip(tmp_path, ext):
    from panepilot import musicbrainz as mb
    from panepilot import tags as tg

    it = _item(tmp_path / f"a.{ext}")
    kind = it.record.kind
    values = {"MUSICBRAINZ_TRACKID": "rec1", "ARTISTSORT": "Band, Sample", "ALBUMARTISTSORT": "Band, Sample",
              "MUSICBRAINZ_ALBUMID": "r1", "CATALOGNUMBER": "CAT 1", "ORIGYEAR": "1999", "TITLE": "Morning Light"}
    changes = {mb.FIELD_BY_ID[f].key(kind): v for f, v in values.items()}
    tg.write_file(it.record, changes)
    rec = tg.read_file(it.record.path)
    for f, v in values.items():
        key = mb.FIELD_BY_ID[f].key(kind)
        assert tg.resolve_key(rec, key) in rec.fields and rec.fields[tg.resolve_key(rec, key)] == v, (f, key)
    if kind == "id3":
        assert "x:UFID:http://musicbrainz.org" in rec.fields and "x:TSOP" in rec.fields
    if kind == "mp4":
        assert "x:soar" in rec.fields and "x:soar" not in rec.readonly


def test_initial_pairs(tmp_path):
    from panepilot import musicbrainz as mb

    rel = mb.parse_release(RELEASE)
    a = _item(tmp_path / "a.mp3", track="2")
    b = _item(tmp_path / "b.mp3", track="1")
    left, right = mb.initial_pairs(rel.tracks, [a, b])
    assert right == [b, a]  # nach Tracknummer
    c = _item(tmp_path / "c.mp3")
    left, right = mb.initial_pairs(rel.tracks, [a, c])
    assert right == [a, c]  # ohne Nummern: Reihenfolge
    assert mb.search_terms([a, b]) == ("", "")


def test_musicbrainz_in_window(window, tmp_path, qtbot, monkeypatch):  # noqa: F811
    from panepilot import mbdialogs as md
    from panepilot import musicbrainz as mb

    from test_v093 import _open

    folder = tmp_path / "Album"
    folder.mkdir()
    _item(folder / "01.mp3", track="1", album="Sample Album", artist="Sample Band", genre="Jazz")
    _item(folder / "02.flac", track="2", album="Sample Album", artist="Sample Band")
    pane = _open(window, qtbot, folder)
    monkeypatch.setattr(mb, "search", lambda album, artist: mb.parse_search(SEARCH))
    cover = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    monkeypatch.setattr(mb, "load_release", lambda rid: (mb.parse_release(RELEASE), cover))
    seen = {}

    def search_exec(dlg):
        seen["terms"] = dlg.terms()
        return QDialog.DialogCode.Accepted

    def results_exec(dlg):
        seen["rows"] = dlg.table.rowCount()
        seen["match"] = dlg.table.item(0, 0).background().color().name()
        return QDialog.DialogCode.Accepted

    def apply_exec(dlg):
        seen["pairs"] = [(tr.title, it.record.name) for tr, it in zip(dlg.left, dlg.right)]
        dlg.set_checked("GENRE", False)
        dlg.cover_check.setEnabled(True)  # Testbild ist kein echtes PNG
        dlg.cover_check.setChecked(True)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(md.SearchDialog, "exec", search_exec)
    monkeypatch.setattr(md.ResultsDialog, "exec", results_exec)
    monkeypatch.setattr(md.ApplyDialog, "exec", apply_exec)
    window.meta_convert("musicbrainz")
    assert seen["terms"] == ("Sample Album", "Sample Band")
    assert seen["rows"] == 2 and seen["match"] == md.MATCH.name()
    assert seen["pairs"] == [("Morning Light", "01.mp3"), ("Evening Rain", "02.flac")]
    mp3, flac = sorted(pane.meta_view.target_items(), key=lambda it: it.record.name)
    assert mp3.value("title") == "Morning Light" and mp3.value("track") == "1/2" and mp3.value("year") == "1999"
    assert mp3.value("genre") == "Jazz"  # Genre abgewählt → unverändert
    assert mp3.pending["x:UFID:http://musicbrainz.org"] == "rec1"
    assert flac.pending["x:MUSICBRAINZ_TRACKID"] == "rec2" and flac.value("artist") == "Sample Band feat. Guest"
    assert mp3.pending_pictures[0].mime == "image/png"
    assert "GENRE" not in window.settings.get("meta_musicbrainz")["fields"]
    window.meta_discard()
    window.meta_close()


def test_apply_dialog_length_marking(tmp_path, qtbot):
    from panepilot import mbdialogs as md
    from panepilot import musicbrainz as mb

    rel = mb.parse_release(RELEASE)
    it = _item(tmp_path / "a.mp3", track="1")
    dlg = md.ApplyDialog(None, rel, None, [it], {})
    assert not dlg.cover_check.isEnabled()
    assert md.ApplyDialog.length_differs(rel.tracks[0], it)  # Testdatei ist sehr kurz
    assert dlg.list_left.item(0).background().color() == md.YELLOW
    assert dlg.list_right.item(1).text() == "(übersprungen)" or dlg.list_right.count() == 2
    dlg.reject()
    QApplication.processEvents()
