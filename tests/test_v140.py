"""Tests for 1.4: photo metadata in the meta wizard (EXIF/IPTC/XMP via exiv2)."""

import os
import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from test_mainwindow import window  # noqa: F401
from test_v093 import _open

pyexiv2 = pytest.importorskip("pyexiv2")
Image = pytest.importorskip("PIL.Image")

DATA = Path(__file__).parent / "data" / "audio"


def make_photo(path: Path, date="2026:11:08 15:00:12", make="Xiaomi", model="Xiaomi 23113RKC6G", gps=True,
               size=(64, 48)) -> Path:
    """Kleines Foto mit typischen EXIF-Angaben eines Handys."""
    img = Image.new("RGB", size, (30, 120, 200))
    fmt = {".jpg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".tif": "TIFF", ".dng": "TIFF"}[path.suffix.lower()]
    img.save(path, fmt)
    exif = {"Exif.Image.Make": make, "Exif.Image.Model": model, "Exif.Photo.ExposureTime": "1/250",
            "Exif.Photo.FNumber": "18/10", "Exif.Photo.ISOSpeedRatings": "100", "Exif.Photo.FocalLength": "55/10",
            "Exif.Photo.Flash": "16", "Exif.Image.Orientation": "1"}
    if date:
        exif["Exif.Photo.DateTimeOriginal"] = date
    if gps:
        exif.update({"Exif.GPSInfo.GPSLatitude": "10/1 18/1 3600/100", "Exif.GPSInfo.GPSLatitudeRef": "N",
                     "Exif.GPSInfo.GPSLongitude": "123/1 53/1 2400/100", "Exif.GPSInfo.GPSLongitudeRef": "E",
                     "Exif.GPSInfo.GPSAltitude": "120/10", "Exif.GPSInfo.GPSAltitudeRef": "0"})
    if path.suffix.lower() in (".jpg", ".tif", ".dng"):
        from panepilot import phototags as ph

        ph._pyexiv2()
        im = pyexiv2.Image(str(path))
        im.modify_exif(exif)
        im.close()
    return path


# --- Lesen und Schreiben ------------------------------------------------------------------------------------
def test_read_jpeg(tmp_path):
    from panepilot import tags as tg

    rec = tg.read_file(str(make_photo(tmp_path / "IMG_1.jpg")))
    assert rec.kind == "photo" and rec.codec == "JPEG" and (rec.width, rec.height) == (64, 48)
    f = rec.fields
    assert f["datetaken"] == "2026-11-08 15:00:12" and f["make"] == "Xiaomi"
    assert f["exposure"] == "1/250 s" and f["aperture"] == "f/1.8" and f["focal"] == "5.5 mm" and f["iso"] == "100"
    assert f["flash"] == "nicht ausgelöst"
    assert f["gpslat"] == "10.310000" and f["gpslon"] == "123.890000" and f["gpsalt"] == "12.0 m"
    assert "make" in rec.removable and "title" not in rec.removable and not rec.readonly


def test_write_roundtrip_and_conventions(tmp_path):
    from panepilot import phototags as ph
    from panepilot import tags as tg

    path = make_photo(tmp_path / "IMG_2.jpg")
    rec = tg.read_file(str(path))
    rec = tg.write_file(rec, {"title": "Strand", "description": "Abends am Meer", "keywords": "Urlaub; Cebu",
                              "rating": "4", "author": "Alice", "copyright": "(c) Alice",
                              "datetaken": "09.11.2026 10:30", "x:Xmp.panepilot.Ort": "Moalboal",
                              "make": "Fake"})  # nur Entfernen erlaubt → ignoriert
    f = rec.fields
    assert (f["title"], f["description"], f["keywords"], f["rating"]) == ("Strand", "Abends am Meer", "Urlaub; Cebu", "4")
    assert f["datetaken"] == "2026-11-09 10:30:00" and f["make"] == "Xiaomi"
    assert rec.labels["x:Xmp.panepilot.Ort"] == "Ort" and f["x:Xmp.panepilot.Ort"] == "Moalboal"
    img = pyexiv2.Image(str(path))
    exif, iptc, xmp = img.read_exif(), img.read_iptc(), img.read_xmp()
    img.close()
    # an alle üblichen Stellen geschrieben (wie digiKam)
    assert xmp["Xmp.dc.title"] == {ph.X_DEFAULT: "Strand"} and iptc["Iptc.Application2.ObjectName"] == "Strand"
    assert xmp["Xmp.dc.subject"] == ["Urlaub", "Cebu"] and iptc["Iptc.Application2.Keywords"] == ["Urlaub", "Cebu"]
    assert exif["Exif.Image.Rating"] == "4" and exif["Exif.Image.Artist"] == "Alice"
    assert exif["Exif.Photo.DateTimeOriginal"] == "2026:11:09 10:30:00"
    # GPS und Kamera entfernen
    rec = tg.write_file(rec, {"gpslat": None, "gpslon": None, "gpsalt": None, "make": None, "keywords": None})
    assert "gpslat" not in rec.fields and "make" not in rec.fields and "keywords" not in rec.fields
    assert ph.map_url(rec) is None


@pytest.mark.parametrize("ext", [".png", ".webp", ".tif"])
def test_other_formats_writable(tmp_path, ext):
    from panepilot import tags as tg

    rec = tg.read_file(str(make_photo(tmp_path / f"bild{ext}")))
    assert not rec.readonly
    rec = tg.write_file(rec, {"title": "Titel", "rating": "5"})
    assert rec.fields["title"] == "Titel" and rec.fields["rating"] == "5"


def test_raw_and_heic_read_only(tmp_path, monkeypatch):
    from panepilot import phototags as ph
    from panepilot import tags as tg
    from panepilot.metawizard import MetaItem

    raw = make_photo(tmp_path / "IMG_3.dng")
    it = MetaItem(tg.read_file(str(raw)))
    assert it.record.codec == "RAW (DNG)" and it.readonly("title") and it.readonly("x:Xmp.panepilot.Ort")
    assert it.record.fields["make"] == "Xiaomi"
    heif = pytest.importorskip("pillow_heif")
    heif.register_heif_opener()
    path = tmp_path / "IMG_4.heic"
    Image.new("RGB", (32, 24), (200, 30, 30)).save(path)
    monkeypatch.setattr(ph, "exiftool", lambda: None)
    it = MetaItem(tg.read_file(str(path)))
    assert it.record.codec == "HEIC" and it.readonly("title")
    assert ph.preview(str(path), 100) is not None  # Vorschau über pillow-heif
    monkeypatch.setattr(ph, "exiftool", lambda: "/usr/bin/exiftool")
    it = MetaItem(tg.read_file(str(path)))
    assert not it.readonly("title") and it.readonly("x:Xmp.panepilot.Ort")  # eigene Felder nicht über exiftool


def test_exiftool_arguments(tmp_path, monkeypatch):
    from panepilot import phototags as ph

    calls = []

    class Done:
        returncode, stdout, stderr = 0, "", ""
    monkeypatch.setattr(ph, "exiftool", lambda: "/x/exiftool")
    monkeypatch.setattr(ph.subprocess, "run", lambda args, **k: calls.append(args) or Done())
    ph._write_exiftool(str(tmp_path / "a.heic"), {"Xmp.dc.title": {ph.X_DEFAULT: "T"}, "Xmp.dc.subject": ["a", "b"],
                                                  "Exif.GPSInfo.GPSLatitude": None})
    args = calls[0]
    assert args[0] == "/x/exiftool" and "-XMP-dc:Title=T" in args and "-XMP-dc:Subject+=b" in args
    assert "-EXIF:GPSLatitude=" in args and args[-1].endswith("a.heic")


def test_snapshot_restore(tmp_path):
    from panepilot import tags as tg

    path = str(make_photo(tmp_path / "IMG_5.jpg"))
    snap = tg.snapshot(path, with_pictures=False)
    rec = tg.write_file(tg.read_file(path), {"title": "Neu", "gpslat": None, "x:Xmp.panepilot.Ort": "X"})
    assert rec.fields["title"] == "Neu"
    rec = tg.restore(path, snap)
    assert "title" not in rec.fields and rec.fields["gpslat"] == "10.310000"
    assert "x:Xmp.panepilot.Ort" not in rec.fields


def test_date_function():
    from panepilot import convert as cv

    values = {"datetaken": "2026-11-08 15:00:12", "_mtime": "0"}
    assert cv.evaluate("$date(%datetaken%,JJJJ-MM-TT_hhmmss)", values.get) == "2026-11-08_150012"
    import datetime as dt

    ts = dt.datetime(2025, 1, 2, 3, 4, 5).timestamp()
    get = {"datetaken": "", "_mtime": str(ts)}.get
    assert cv.evaluate("$date(%datetaken%,TT.MM.JJJJ)", get) == "02.01.2025"  # Änderungsdatum als Ersatz
    assert cv.evaluate("$date(%year%,JJJJ)", {"year": "1999"}.get) == "1999"


def test_shift_date():
    from panepilot.metaextras import shift_date

    assert shift_date("2026-11-08 23:30:00", 3600) == "2026-11-09 00:30:00"
    assert shift_date("", 60) is None


# --- Meta-Wizard ------------------------------------------------------------------------------------------
@pytest.fixture
def photos(tmp_path):
    folder = tmp_path / "Urlaub"
    folder.mkdir()
    make_photo(folder / "IMG_20261108_150012.jpg")
    make_photo(folder / "IMG_20261108_160000.jpg", date="2026:11:08 16:00:00", gps=False)
    make_photo(folder / "Screenshot.png", date=None)
    return folder


def test_photo_mode(window, photos, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import metaprofile as mp

    pane = _open(window, qtbot, photos)
    assert mp.is_photo_mode() and len(pane.meta_model.items) == 3
    assert pane.meta_model.columns == mp.PHOTO_COLUMNS
    assert not pane.kind_switch.isVisible()
    assert not pane.convert_buttons[cv.MUSICBRAINZ].isVisibleTo(pane)
    assert pane.convert_buttons[cv.DATESHIFT].isVisibleTo(pane)
    items = sorted(pane.meta_model.items, key=lambda it: it.record.name)
    assert pane.meta_model.text(items[0], "i:dims") == "64 × 48"
    assert pane.meta_model.text(items[0], "i:camera") == "Xiaomi 23113RKC6G"
    pane.meta_view.select_items([items[0]])
    QApplication.processEvents()
    assert pane.cover.image.pixmap() is not None and not pane.cover.image.pixmap().isNull()
    assert "openstreetmap.org" in pane.map_link.text()
    box = pane.boxes["make"]
    assert box.lineEdit().isReadOnly()  # nur entfernen
    box.setEditText("Anders")
    box._edited()
    assert "make" not in items[0].pending
    box.setEditText("< entfernen >")
    box._edited()
    assert items[0].pending.get("make", "x") is None
    pane.boxes["title"].setEditText("Strand")
    pane.boxes["title"]._edited()
    window.meta_save()
    qtbot.waitUntil(lambda: window.meta_mode.get("save") is None, timeout=5000)
    assert items[0].record.fields["title"] == "Strand" and "make" not in items[0].record.fields
    window.meta_close()
    assert not mp.is_photo_mode() or window.meta_mode is None


def test_mixed_folder_switch(window, photos, qtbot, monkeypatch):  # noqa: F811
    from panepilot import metaprofile as mp

    shutil.copy(DATA / "leer.mp3", photos / "lied.mp3")
    pane = _open(window, qtbot, photos)
    assert mp.is_photo_mode()  # mehr Fotos als Musik
    assert pane.kind_switch.isVisibleTo(pane)
    assert pane.kind_switch.btn_audio.text() == "Musik (1)" and pane.kind_switch.btn_photo.text() == "Fotos (3)"
    pane.kind_switch.btn_audio.click()
    qtbot.waitUntil(lambda: window.meta_mode.get("scan") is None, timeout=5000)
    assert not mp.is_photo_mode() and [it.record.name for it in pane.meta_model.items] == ["lied.mp3"]
    assert "title" in pane.meta_model.columns and "artist" in pane.meta_model.columns
    # mit ungespeicherten Änderungen: Rückfrage
    pane.meta_model.items[0].set("title", "x")
    monkeypatch.setattr("panepilot.dialogs.confirm", lambda *a, **k: False)
    pane.kind_switch.btn_photo.click()
    assert not mp.is_photo_mode() and pane.kind_switch.btn_audio.isChecked()
    window.meta_discard()
    window.meta_close()


def test_dateshift_and_tag_to_filename(window, photos, qtbot, monkeypatch):  # noqa: F811
    from panepilot.metaextras import DateShiftDialog

    pane = _open(window, qtbot, photos)

    def shift_exec(dlg):
        dlg.spins["hours"].setValue(1)
        assert "kein Aufnahmedatum" in [dlg.tree.topLevelItem(i).text(1) for i in range(dlg.tree.topLevelItemCount())]
        assert "1 ohne Aufnahmedatum" in dlg.summary.text()
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(DateShiftDialog, "exec", shift_exec)
    window.meta_convert("dateshift")
    items = {it.record.name: it for it in pane.meta_model.items}
    assert items["IMG_20261108_150012.jpg"].value("datetaken") == "2026-11-08 16:00:12"
    assert "datetaken" not in items["Screenshot.png"].pending
    assert window.settings.get("meta_dateshift")["hours"] == 1
    # Tag → Dateiname mit der mitgelieferten Vorlage
    assert window._meta_presets("tag2file")[0]["format"] == "$date(%datetaken%,JJJJ-MM-TT_hhmmss)"
    res = window._meta_compute("tag2file", "$date(%datetaken%,JJJJ-MM-TT_hhmmss)", "", list(items.values()))
    names = {it.record.name: new for it, new, _err in res}
    assert names["IMG_20261108_150012.jpg"] == "2026-11-08_160012.jpg"
    assert names["Screenshot.png"].endswith(".png") and names["Screenshot.png"][:4].isdigit()
    window.meta_discard()
    window.meta_close()


def test_custom_photo_field(window, photos, qtbot):  # noqa: F811
    from panepilot import tags as tg

    pane = _open(window, qtbot, photos)
    it = pane.meta_model.items[0]
    it.set(tg.custom_key("photo", "Mein Ort"), "Cebu")
    assert "x:Xmp.panepilot.Mein_Ort" in it.pending
    window.meta_save()
    qtbot.waitUntil(lambda: window.meta_mode.get("save") is None, timeout=5000)
    assert it.record.fields["x:Xmp.panepilot.Mein_Ort"] == "Cebu"
    assert window.settings.get("meta_photo_layout") is not None
    window.meta_close()
    assert os.path.exists(it.record.path)


def test_layouts_kept_separately(window, photos, qtbot):  # noqa: F811
    from panepilot import metaprofile as mp

    pane = _open(window, qtbot, photos)
    pane.meta_view.set_columns(["filename", "rating"])
    window.meta_close()
    assert window.settings.get("meta_photo_layout")["columns"] == ["filename", "rating"]
    assert (window.settings.get("meta_layout") or {}).get("columns") != ["filename", "rating"]
    assert mp.current() == mp.AUDIO
