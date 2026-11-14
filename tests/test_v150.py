"""Tests for 1.5: video metadata in the meta wizard and the help chapter on additional programs."""

import os
import shutil
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from test_mainwindow import window  # noqa: F401
from test_v093 import _open

VIDEO = Path(__file__).parent / "data" / "video"
AUDIO = Path(__file__).parent / "data" / "audio"
PNG = Path(__file__).parent.parent / "docs" / "screenshots" / "ftp.png"

needs_ffprobe = pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffprobe missing")
needs_exiftool = pytest.mark.skipif(shutil.which("exiftool") is None, reason="exiftool missing")
needs_mkvtoolnix = pytest.mark.skipif(shutil.which("mkvpropedit") is None or shutil.which("mkvextract") is None,
                                      reason="mkvtoolnix missing")


@pytest.fixture(autouse=True)
def berlin(monkeypatch):
    """Ortszeit fest auf Mitteleuropa, damit die UTC-Zeiten aus den Videos vorhersehbar sind."""
    monkeypatch.setenv("TZ", "Europe/Berlin")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def copy(tmp_path, name: str, target: str | None = None) -> str:
    dst = tmp_path / (target or name)
    shutil.copy(VIDEO / name, dst)
    return str(dst)


def _pic():
    from panepilot import tags as tg

    return tg.Picture(PNG.read_bytes(), "image/png", tg.FRONT_COVER, "")


# --- Grundlagen -----------------------------------------------------------------------------------------------
def test_kinds_and_profile():
    from panepilot import convert as cv
    from panepilot import metaprofile as mp

    assert mp.kind_of("a.mp4") == mp.VIDEO and mp.kind_of("a.m4a") == mp.AUDIO  # L-513
    assert mp.kind_of("a.MKV") == mp.VIDEO and mp.kind_of("a.jpg") == mp.PHOTO and mp.kind_of("a.txt") is None
    try:
        mp.set_current(mp.VIDEO)
        assert mp.setting("meta_layout") == "meta_video_layout"
        assert mp.default_columns() == ["filename", "datetaken", "i:duration", "i:resolution", "title", "path"]
        assert cv.DATESHIFT in mp.tools() and cv.REPLAYGAIN not in mp.tools() and cv.MUSICBRAINZ not in mp.tools()
        assert "author" in mp.fields() and "gpslat" in mp.fields()
    finally:
        mp.set_current(mp.AUDIO)


def test_iso_parsing():
    from panepilot import videotags as vt

    assert vt.parse_iso6709("+48.1371+011.5753+520.000/") == (48.1371, 11.5753, 520.0)
    assert vt.parse_iso6709("-33.9-018.4/") == (-33.9, -18.4, None)
    assert vt.parse_iso("1904-01-01T00:00:00.000000Z") is None
    when = vt.parse_iso("2026-11-08T15:00:12+0100")
    assert when.utcoffset().total_seconds() == 3600
    assert vt._date_taken({"creation_time": "2026-07-01T08:00:00.000000Z"})[0] == "2026-07-01 10:00:00"
    # Apple: Ortszeit der Aufnahme gilt
    assert vt._date_taken({"creation_time": "2026-11-08T14:00:12Z",
                           "com.apple.quicktime.creationdate": "2026-11-08T21:00:12+0800"})[0] == "2026-11-08 21:00:12"
    assert vt.format_fps(29.97002997) == "29.97 fps" and vt.format_fps(25.0) == "25 fps"


# --- MP4 ------------------------------------------------------------------------------------------------------
@needs_ffprobe
def test_read_mp4(tmp_path):
    from panepilot import tags as tg

    rec = tg.read_file(copy(tmp_path, "clip.mp4"))
    assert rec.kind == "video-mp4" and rec.codec == "MP4" and not rec.error
    assert (rec.width, rec.height) == (64, 48) and rec.fps == 10 and rec.vcodec == "H.264" and rec.acodec == "AAC"
    assert 0.9 < rec.length < 1.2
    f = rec.fields
    assert f["title"] == "Strand" and f["datetaken"] == "2026-11-08 15:00:12"
    assert (f["gpslat"], f["gpslon"], f["gpsalt"]) == ("10.310000", "123.890000", "12.0 m")


def test_write_mp4_tags_poster_and_undo(tmp_path):
    from mutagen.mp4 import MP4

    from panepilot import tags as tg

    path = copy(tmp_path, "clip.mp4")
    rec = tg.read_file(path)
    snap = tg.snapshot(path, with_pictures=True)
    key = tg.custom_key(rec.kind, "Ort")
    assert key == "x:----:com.apple.iTunes:Ort"
    rec = tg.write_file(rec, {"title": "Abend", "description": "Am Meer", "author": "Alice", "copyright": "(c) Alice",
                              "genre": "Urlaub", "year": "2026", key: "Moalboal"}, [_pic()])
    f = rec.fields
    assert (f["title"], f["description"], f["author"], f["genre"], f["year"]) == ("Abend", "Am Meer", "Alice", "Urlaub",
                                                                                  "2026")
    assert f[key] == "Moalboal" and rec.labels[key] == "Ort" and len(rec.pictures) == 1
    tags = MP4(path).tags
    assert tags["desc"] == ["Am Meer"] and tags["\xa9cmt"] == ["Am Meer"]  # an beide üblichen Stellen (L-534)
    rec = tg.write_file(rec, {"description": None})
    assert "description" not in rec.fields and "\xa9cmt" not in MP4(path).tags
    rec = tg.restore(path, snap)
    assert rec.fields["title"] == "Strand" and key not in rec.fields and rec.pictures == []


def test_mp4_access_without_exiftool(tmp_path, monkeypatch):
    from panepilot import tags as tg
    from panepilot import videotags as vt

    monkeypatch.setattr(vt, "exiftool", lambda: None)
    rec = tg.read_file(copy(tmp_path, "clip.mp4"))
    assert {"datetaken", "gpslat"} <= rec.readonly and "title" not in rec.readonly and not rec.removable


@needs_exiftool
@needs_ffprobe
def test_mp4_date_and_gps_with_exiftool(tmp_path):
    from panepilot import tags as tg

    path = copy(tmp_path, "clip.mp4")
    rec = tg.read_file(path)
    assert rec.removable == {"gpslat", "gpslon", "gpsalt"} and "datetaken" not in rec.readonly
    snap = tg.snapshot(path, with_pictures=False)
    rec = tg.write_file(rec, {"datetaken": "2026-07-01 10:00:00", "gpslat": None, "gpslon": None, "gpsalt": None})
    assert rec.fields["datetaken"] == "2026-07-01 10:00:00" and "gpslat" not in rec.fields
    rec = tg.restore(path, snap)
    assert rec.fields["datetaken"] == "2026-11-08 15:00:12" and rec.fields["gpslat"] == "10.310000"


# --- WMV, MKV, AVI ----------------------------------------------------------------------------------------------
def test_wmv(tmp_path):
    from panepilot import tags as tg

    path = copy(tmp_path, "clip.wmv")
    rec = tg.read_file(path)
    assert rec.kind == "video-asf" and rec.fields["title"] == "Strand" and "datetaken" in rec.readonly
    snap = tg.snapshot(path, with_pictures=True)
    rec = tg.write_file(rec, {"author": "Alice", tg.custom_key(rec.kind, "Ort"): "Rom"}, [_pic()])
    assert rec.fields["author"] == "Alice" and rec.fields["x:Ort"] == "Rom" and len(rec.pictures) == 1
    rec = tg.restore(path, snap)
    assert "author" not in rec.fields and "x:Ort" not in rec.fields and rec.pictures == []


@needs_ffprobe
def test_mkv_read_only_without_mkvtoolnix(tmp_path, monkeypatch):
    from panepilot import metawizard as mw
    from panepilot import tags as tg
    from panepilot import videotags as vt

    monkeypatch.setattr(vt, "mkvpropedit", lambda: None)
    rec = tg.read_file(copy(tmp_path, "clip.mkv"))
    assert rec.kind == "video-mkv" and rec.fields["title"] == "Strand" and rec.fields["author"] == "Alice"
    assert rec.fields["datetaken"] == "2026-11-08 15:00:12" and rec.acodec == "Opus"
    assert "*" in rec.readonly and "x:ENCODER" not in rec.fields
    assert "mkvtoolnix" in mw.video_hint([rec])
    with pytest.raises(OSError):
        tg.write_file(rec, {"title": "x"})


@needs_ffprobe
@needs_mkvtoolnix
def test_mkv_write_with_mkvtoolnix(tmp_path):
    from panepilot import tags as tg

    path = copy(tmp_path, "clip.mkv")
    rec = tg.read_file(path)
    assert "*" not in rec.readonly and "datetaken" not in rec.readonly
    snap = tg.snapshot(path, with_pictures=True)
    key = tg.custom_key(rec.kind, "Ort")
    assert key == "x:ORT"
    rec = tg.write_file(rec, {"title": "Abend", "author": "Bob", "genre": "Urlaub", key: "Cebu",
                              "datetaken": "2026-07-01 10:00:00"}, [_pic()])
    f = rec.fields
    assert (f["title"], f["author"], f["genre"], f[key]) == ("Abend", "Bob", "Urlaub", "Cebu")
    assert f["datetaken"] == "2026-07-01 10:00:00" and len(rec.pictures) == 1
    rec = tg.write_file(rec, {"genre": None}, [])
    assert "genre" not in rec.fields and rec.pictures == []
    rec = tg.restore(path, snap)
    assert rec.fields["title"] == "Strand" and rec.fields["author"] == "Alice" and key not in rec.fields
    assert rec.fields["datetaken"] == "2026-11-08 15:00:12" and rec.pictures == []


def test_mkv_xml_helpers():
    import xml.etree.ElementTree as ET

    from panepilot import videotags as vt

    root = ET.fromstring("<Tags><Tag><Targets><TrackUID>1</TrackUID></Targets><Simple><Name>BPS</Name>"
                         "<String>1</String></Simple></Tag></Tags>")
    vt.mkv_set_simple(root, "ARTIST", "Alice")
    tags = root.findall("Tag")
    assert len(tags) == 2 and tags[1].find("Targets/TargetTypeValue").text == "50"  # Spur-Tags bleiben
    vt.mkv_set_simple(root, "artist", None)
    assert len(root.findall("Tag")) == 1


@needs_ffprobe
def test_avi_read_only(tmp_path):
    from panepilot import metawizard as mw
    from panepilot import tags as tg

    rec = tg.read_file(copy(tmp_path, "clip.avi"))
    assert rec.kind == "video" and rec.fields["title"] == "Strand" and "*" in rec.readonly
    assert rec.vcodec == "MPEG-4" and rec.acodec == "MP3"
    assert mw.video_hint([rec]) == mw.t("video.readonly_hint")


def test_without_ffprobe(tmp_path, monkeypatch):
    from panepilot import metawizard as mw
    from panepilot import tags as tg
    from panepilot import videotags as vt

    monkeypatch.setattr(vt, "ffprobe", lambda: None)
    rec = tg.read_file(copy(tmp_path, "clip.mp4"))
    assert not rec.error and rec.fields["title"] == "Strand" and rec.width == 0 and rec.length > 0
    rec = tg.read_file(copy(tmp_path, "clip.mkv"))
    assert not rec.error and rec.fields == {}
    assert "ffmpeg" in mw.video_hint([rec])


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")
def test_grab_frame(tmp_path):
    from panepilot import videotags as vt

    data = vt.grab_frame(copy(tmp_path, "clip.mp4"), 1.0, 100)
    assert data and data[:8] == b"\x89PNG\r\n\x1a\n"


# --- Meta-Wizard ----------------------------------------------------------------------------------------------
@pytest.fixture
def videos(tmp_path):
    folder = tmp_path / "Urlaub"
    folder.mkdir()
    copy(folder, "clip.mp4", "VID_20261108_150012.mp4")
    copy(folder, "clip.wmv", "alt.wmv")
    copy(folder, "clip.avi", "camcorder.avi")
    return folder


@needs_ffprobe
def test_video_mode(window, videos, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import metaprofile as mp

    pane = _open(window, qtbot, videos)
    assert mp.is_video_mode() and len(pane.meta_model.items) == 3
    assert pane.meta_model.columns == mp.VIDEO_COLUMNS and not pane.kind_switch.isVisible()
    assert pane.convert_buttons[cv.DATESHIFT].isVisibleTo(pane)
    assert not pane.convert_buttons[cv.REPLAYGAIN].isVisibleTo(pane)
    items = {it.record.name: it for it in pane.meta_model.items}
    mp4 = items["VID_20261108_150012.mp4"]
    assert pane.meta_model.text(mp4, "i:resolution") == "64 × 48"
    assert pane.meta_model.text(mp4, "i:duration") == "0:01" and pane.meta_model.text(mp4, "i:fps") == "10 fps"
    pane.meta_view.select_items([mp4])
    QApplication.processEvents()
    assert "openstreetmap.org" in pane.map_link.text()
    qtbot.waitUntil(lambda: pane.cover.frame_data is not None, timeout=10000)  # Standbild (L-522)
    pic = pane.cover.frame_picture()
    assert pic.mime == "image/jpeg"
    window._meta_cover_replace(pic)  # „Standbild als Vorschaubild übernehmen“ (L-523)
    pane.boxes["title"].setEditText("Abend")
    pane.boxes["title"]._edited()
    window.meta_save()
    qtbot.waitUntil(lambda: window.meta_mode.get("save") is None, timeout=10000)
    assert mp4.record.fields["title"] == "Abend" and len(mp4.record.pictures) == 1
    # AVI: nur lesen
    pane.meta_view.select_items([items["camcorder.avi"]])
    QApplication.processEvents()
    assert not pane.boxes["title"].isEnabled()
    window.meta_close()
    assert mp.current() == mp.AUDIO


@needs_ffprobe
def test_three_kinds_switch(window, videos, qtbot):  # noqa: F811
    from panepilot import metaprofile as mp

    shutil.copy(AUDIO / "leer.mp3", videos / "lied.mp3")
    pane = _open(window, qtbot, videos)
    sw = pane.kind_switch
    assert mp.is_video_mode() and sw.isVisibleTo(pane)
    assert sw.btn_video.text() == "Videos (3)" and sw.btn_audio.text() == "Musik (1)"
    assert not sw.btn_photo.isVisibleTo(pane)  # keine Fotos im Ordner
    sw.btn_audio.click()
    qtbot.waitUntil(lambda: window.meta_mode.get("scan") is None, timeout=5000)
    assert mp.current() == mp.AUDIO and [it.record.name for it in pane.meta_model.items] == ["lied.mp3"]
    sw.btn_video.click()
    qtbot.waitUntil(lambda: window.meta_mode.get("scan") is None, timeout=5000)
    assert mp.is_video_mode() and len(pane.meta_model.items) == 3
    window.meta_close()


@needs_ffprobe
def test_video_dateshift_and_rename(window, videos, qtbot, monkeypatch):  # noqa: F811
    from panepilot import videotags as vt
    from panepilot.metaextras import DateShiftDialog

    monkeypatch.setattr(vt, "exiftool", lambda: None)
    pane = _open(window, qtbot, videos)

    def shift_exec(dlg):
        dlg.spins["hours"].setValue(1)
        texts = [dlg.tree.topLevelItem(i).text(2) for i in range(dlg.tree.topLevelItemCount())]
        assert "nicht änderbar" in texts  # MP4 ohne exiftool
        assert "1 lassen sich nicht ändern" in dlg.summary.text()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(DateShiftDialog, "exec", shift_exec)
    window.meta_convert("dateshift")
    items = {it.record.name: it for it in pane.meta_model.items}
    assert not items["VID_20261108_150012.mp4"].pending
    assert window._meta_presets("tag2file")[0]["format"] == "$date(%datetaken%,JJJJ-MM-TT_hhmmss)"
    res = window._meta_compute("tag2file", "$date(%datetaken%,JJJJ-MM-TT_hhmmss) %resolution%", "",
                               [items["VID_20261108_150012.mp4"]])
    assert res[0][1] == "2026-11-08_150012 64x48.mp4"
    window.meta_close()


@needs_ffprobe
def test_custom_video_field_and_layout(window, videos, qtbot):  # noqa: F811
    from panepilot import tags as tg

    pane = _open(window, qtbot, videos)
    it = next(i for i in pane.meta_model.items if i.record.name.endswith(".mp4"))
    it.set(tg.custom_key(it.record.kind, "Ort"), "Cebu")
    window.meta_save()
    qtbot.waitUntil(lambda: window.meta_mode.get("save") is None, timeout=5000)
    assert it.record.fields["x:----:com.apple.iTunes:Ort"] == "Cebu"
    pane.meta_view.set_columns(["filename", "i:vcodec"])
    window.meta_close()
    assert window.settings.get("meta_video_layout")["columns"] == ["filename", "i:vcodec"]
    assert os.path.exists(it.record.path)


def test_help_chapter_tools():
    from panepilot.helpdialog import TOPICS, topic_markdown

    assert "tools" in TOPICS
    for lang in ("de", "en"):
        text = topic_markdown("tools", lang)
        for prog in ("ffmpeg", "exiftool", "mkvtoolnix", "7zip", "unrar"):
            assert prog in text, (lang, prog)
    assert topic_markdown("tools", "de").startswith("# Zusatzprogramme")


# --- Eigenschaften: Reiter „Metadaten“ auch für Fotos und Videos (1.5.1) --------------------------------------
@needs_ffprobe
def test_properties_metadata_tab_video_and_photo(window, tmp_path):  # noqa: F811
    from PySide6.QtWidgets import QLabel

    from panepilot.propdialog import PropertiesDialog
    from test_v140 import make_photo

    dlg = PropertiesDialog(window, [copy(tmp_path, "clip.mp4")])
    assert dlg.tabs.isTabEnabled(2)
    labels = [w.text() for w in dlg.tabs.widget(2).findChildren(QLabel)]
    assert "Strand" in labels and "64 × 48" in labels and "H.264" in labels and "2026-11-08 15:00:12" in labels
    assert any("openstreetmap.org" in x for x in labels)
    assert any(w.pixmap() is not None and not w.pixmap().isNull() for w in dlg.tabs.widget(2).findChildren(QLabel))
    photo = PropertiesDialog(window, [str(make_photo(tmp_path / "IMG_1.jpg"))])
    assert photo.tabs.isTabEnabled(2)
    labels = [w.text() for w in photo.tabs.widget(2).findChildren(QLabel)]
    assert "Xiaomi" in labels and "64 × 48" in labels and "JPEG" in labels
    many = PropertiesDialog(window, [copy(tmp_path, "clip.mp4", "a.mp4"), copy(tmp_path, "clip.mp4", "b.mp4")])
    assert not many.tabs.isTabEnabled(2)


# --- 1.5.2: Endung passt nicht zum Inhalt ----------------------------------------------------------------------
def test_sniff_container(tmp_path):
    from panepilot import videotags as vt

    assert vt.sniff(copy(tmp_path, "clip.mkv")) == "mkv" and vt.sniff(copy(tmp_path, "clip.mp4")) == "mp4"
    assert vt.sniff(copy(tmp_path, "clip.wmv")) == "asf" and vt.sniff(copy(tmp_path, "clip.avi")) == "avi"
    assert vt.wrong_extension(copy(tmp_path, "clip.mkv", "film.mp4")) == "MKV"
    assert vt.wrong_extension(copy(tmp_path, "clip.mkv", "film.webm")) == ""  # WebM ist Matroska
    assert vt.wrong_extension(copy(tmp_path, "clip.mp4", "film.mov")) == ""
    empty = tmp_path / "leer.mp4"
    empty.write_bytes(b"")
    assert vt.sniff(str(empty)) is None and vt.container(str(empty)) == "mp4"


@needs_ffprobe
def test_mkv_named_mp4(tmp_path, monkeypatch):
    from panepilot import metawizard as mw
    from panepilot import tags as tg
    from panepilot import videotags as vt

    monkeypatch.setattr(vt, "mkvpropedit", lambda: None)
    rec = tg.read_file(copy(tmp_path, "clip.mkv", "James Bond (1962).mp4"))
    assert not rec.error and rec.kind == "video-mkv" and rec.fields["title"] == "Strand"
    assert rec.wrong_ext == "MKV" and rec.codec == "MKV (.mp4)"
    hint = mw.video_hint([rec])
    assert "James Bond (1962).mp4" in hint and "MKV" in hint and "mkvtoolnix" in hint
    other = tg.read_file(copy(tmp_path, "clip.mkv", "zwei.mp4"))
    assert "2" in mw.video_hint([rec, other])


def test_mp4_named_mkv(tmp_path):
    from panepilot import tags as tg

    path = copy(tmp_path, "clip.mp4", "film.mkv")
    rec = tg.read_file(path)
    assert not rec.error and rec.kind == "video-mp4" and rec.wrong_ext == "MP4" and rec.fields["title"] == "Strand"
    snap = tg.snapshot(path, with_pictures=True)
    rec = tg.write_file(rec, {"title": "Neu"})
    assert rec.fields["title"] == "Neu"
    assert tg.restore(path, snap).fields["title"] == "Strand"
