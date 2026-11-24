"""Tests for 2.5: RAW metadata in XMP sidecars (Lightroom naming), sidecars follow file operations."""

import os

from test_mainwindow import window  # noqa: F401
from test_v140 import make_photo


def _raw(tmp_path, name="IMG_1234.dng"):
    return make_photo(tmp_path / name)


def test_sidecar_names(tmp_path):
    from panepilot import sidecar

    raw = str(tmp_path / "IMG_1.CR2")
    open(raw, "wb").write(b"x")
    assert sidecar.find(raw) == [] and sidecar.write_path(raw) == str(tmp_path / "IMG_1.xmp")  # Lightroom-Art
    (tmp_path / "IMG_1.CR2.xmp").write_text("x")
    assert sidecar.find(raw) == [str(tmp_path / "IMG_1.CR2.xmp")]  # darktable-Art wird weiterbenutzt
    assert sidecar.renamed(str(tmp_path / "IMG_1.CR2.xmp"), raw, str(tmp_path / "Neu.CR2")) == \
        str(tmp_path / "Neu.CR2.xmp")
    assert sidecar.renamed(str(tmp_path / "IMG_1.xmp"), raw, str(tmp_path / "b" / "Neu.CR2")) == \
        str(tmp_path / "b" / "Neu.xmp")
    jpg = tmp_path / "IMG_1.jpg"
    jpg.write_bytes(b"x")
    assert sidecar.find(str(jpg)) == []  # nur RAW-Dateien haben Begleitdateien


def test_raw_write_goes_to_sidecar(tmp_path):
    from panepilot import tags as tg

    raw = _raw(tmp_path)
    before = raw.read_bytes()
    rec = tg.read_file(str(raw))
    rec = tg.write_file(rec, {"title": "Strand", "keywords": "Urlaub; Meer", "rating": "4",
                              "datetaken": "2026-11-08 15:00:12"})
    assert raw.read_bytes() == before  # RAW unverändert
    side = tmp_path / "IMG_1234.xmp"
    assert side.exists() and "Strand" in side.read_text(encoding="utf-8")
    assert rec.fields["title"] == "Strand" and rec.fields["rating"] == "4"
    assert "Urlaub" in rec.fields["keywords"] and rec.fields["make"] == "Xiaomi"
    # Undo: Begleitdatei verschwindet wieder
    rec2 = tg.read_file(str(raw))
    snap = tg.snapshot(str(raw), False)
    tg.write_file(rec2, {"title": "Anders"})
    tg.restore(str(raw), snap)
    assert tg.read_file(str(raw)).fields["title"] == "Strand"
    side.unlink()
    snap = tg.snapshot(str(raw), False)
    tg.write_file(tg.read_file(str(raw)), {"title": "Neu"})
    assert side.exists()
    tg.restore(str(raw), snap)
    assert not side.exists() and "title" not in tg.read_file(str(raw)).fields


def test_existing_darktable_sidecar_wins(tmp_path):
    from panepilot import tags as tg

    raw = _raw(tmp_path, "IMG_2.dng")
    dt = tmp_path / "IMG_2.dng.xmp"
    from panepilot import sidecar

    dt.write_text(sidecar.EMPTY_PACKET, encoding="utf-8")
    tg.write_file(tg.read_file(str(raw)), {"title": "Berg"})
    assert "Berg" in dt.read_text(encoding="utf-8") and not (tmp_path / "IMG_2.xmp").exists()
    assert tg.read_file(str(raw)).fields["title"] == "Berg"


def test_meta_item_raw(tmp_path):
    from panepilot import tags as tg
    from panepilot.metawizard import MetaItem

    it = MetaItem(tg.read_file(str(_raw(tmp_path))))
    assert not it.readonly("title") and it.readonly("make") and it.readonly("gpslat")


def _run(kind, sources, target=""):
    from panepilot import fileops

    cls = next(v for k, v in vars(fileops).items() if isinstance(v, type) and hasattr(v, "_follow"))
    return cls(kind, sources, target).run()


def test_sidecar_follows_copy_move_delete(tmp_path):
    from panepilot import fileops as fo

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    raw = a / "IMG_5.CR2"
    raw.write_bytes(b"raw")
    (a / "IMG_5.xmp").write_text("side")
    _run(fo.COPY, [str(raw)], str(b))
    assert (b / "IMG_5.CR2").exists() and (b / "IMG_5.xmp").read_text() == "side" and (a / "IMG_5.xmp").exists()
    _run(fo.DELETE, [str(b / "IMG_5.CR2")])
    assert not (b / "IMG_5.xmp").exists()
    _run(fo.MOVE, [str(raw)], str(b))
    assert (b / "IMG_5.xmp").exists() and not (a / "IMG_5.xmp").exists()
    # beide markiert: Begleitdatei nicht doppelt
    _run(fo.MOVE, [str(b / "IMG_5.CR2"), str(b / "IMG_5.xmp")], str(a))
    assert (a / "IMG_5.CR2").exists() and (a / "IMG_5.xmp").exists()
    r = _run(fo.DUPLICATE, [str(a / "IMG_5.CR2")])
    names = sorted(os.listdir(a))
    assert len(names) == 4 and not r.errors, names


def test_sidecar_follows_rename(tmp_path):
    from panepilot import multirename as mr

    raw = tmp_path / "IMG_6.CR2"
    raw.write_bytes(b"raw")
    (tmp_path / "IMG_6.CR2.xmp").write_text("dt")
    done, errors = mr.perform(str(tmp_path), [("IMG_6.CR2", "Urlaub_1.CR2")])
    assert done and not errors
    assert (tmp_path / "Urlaub_1.CR2.xmp").read_text() == "dt" and not (tmp_path / "IMG_6.CR2.xmp").exists()


def test_sidecar_follows_f2_rename(window, tmp_path):  # noqa: F811
    raw = tmp_path / "IMG_7.CR2"
    raw.write_bytes(b"raw")
    (tmp_path / "IMG_7.xmp").write_text("lr")
    panel = window.sides["left"].panel
    panel.navigate(str(tmp_path))
    m = panel.model
    m.setData(m.index(m.row_of("IMG_7.CR2"), 0), "Strand.CR2")
    assert (tmp_path / "Strand.xmp").read_text() == "lr" and not (tmp_path / "IMG_7.xmp").exists()


# --- MKV nie fertig geschrieben ---------------------------------------------------------------------------
def _broken_mkv(tmp_path):
    import shutil
    import subprocess

    import pytest

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg fehlt")
    good = tmp_path / "gut.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=10", "-t", "2",
                    "-c:v", "mpeg4", str(good)], check=True)
    from panepilot import videotags as vt

    data = bytearray(good.read_bytes())
    _id, pos = vt._ebml_vint(data, 0, True)
    size, pos = vt._ebml_vint(data, pos)
    pos += size
    _seg, pos = vt._ebml_vint(data, pos, True)
    first, mask, n = data[pos], 0x80, 1
    while not first & mask:
        mask >>= 1
        n += 1
    data[pos:pos + n] = bytes([mask]) + bytes(n - 1)  # Segment-Größe 0 wie bei einer abgebrochenen Datei
    bad = tmp_path / "Folge S01E01.mkv"
    bad.write_bytes(bytes(data))
    return good, bad


def test_mkv_unfinished_and_repair(tmp_path):
    from panepilot import videotags as vt

    good, bad = _broken_mkv(tmp_path)
    assert not vt.mkv_unfinished(str(good)) and vt.mkv_unfinished(str(bad))
    assert vt.is_unfinished_error(str(bad)) and not vt.is_unfinished_error(str(good))
    parts = []
    new = vt.repair_mkv(str(bad), parts.append)
    assert os.path.basename(new).startswith(".panepilot-repariert-") and not vt.mkv_unfinished(new)
    assert parts[-1] == 1.0 and bad.exists()


def test_offer_repair_flow(window, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import dialogs, fileops
    from panepilot import videotags as vt

    _good, bad = _broken_mkv(tmp_path)
    trashed, saved, asked = [], [], []
    monkeypatch.setattr(dialogs, "confirm", lambda *a, **k: asked.append(a[2]) or True)
    monkeypatch.setattr(fileops, "move_to_trash", lambda p: trashed.append(p) or os.unlink(p))
    monkeypatch.setattr(window, "meta_save", lambda after=None: saved.append(1))
    monkeypatch.setattr(window, "_meta_pane", lambda: type("P", (), {
        "meta_model": type("M", (), {"items": [], "rows_changed": lambda self: None})()})())
    window._meta_offer_repair([str(bad)])
    assert asked and "Folge S01E01.mkv" in asked[0]
    assert trashed == [str(bad)] and bad.exists() and not vt.mkv_unfinished(str(bad)) and saved == [1]
    assert not [n for n in os.listdir(tmp_path) if n.startswith(".panepilot")]


def test_text_functions():
    from panepilot import convert as cv

    assert cv._call("mid", ["001 Act 1-1 Prelude", "5"]) == "Act 1-1 Prelude"
    assert cv._call("mid", ["abcdefghijklmnopqrst", "5", "12"]) == "efghijklmnop"  # Zeichen 5 bis 16
    assert cv._call("mid", ["abc", "0"]) == "abc" and cv._call("mid", ["abc", "2", "0"]) == ""
    assert cv._call("len", ["Prelude"]) == "7"
    assert "mid" in cv.FUNCTIONS and "len" in cv.FUNCTIONS


# --- Karte ------------------------------------------------------------------------------------------------
def test_map_math():
    from panepilot import mapview as mv

    x, y = mv.world_xy(0, 0, 1)
    assert (x, y) == (256, 256)
    la, lo = mv.latlon(*mv.world_xy(48.137, 11.575, 12), 12)
    assert abs(la - 48.137) < 1e-6 and abs(lo - 11.575) < 1e-6
    assert mv.fit([(48.1, 11.5)], 300, 200)[2] == 15
    lat, lon, z = mv.fit([(48.137, 11.575), (52.52, 13.405)], 300, 200)  # München–Berlin
    assert 3 <= z <= 8 and 48 < lat < 53 and 11 < lon < 14
    assert mv.fit([], 300, 200)[2] == mv.MIN_ZOOM


def test_map_view_tiles_and_points(window, tmp_path):  # noqa: F811
    from PySide6.QtGui import QColor, QImage

    from panepilot import mapview as mv

    view = mv.MapView(None, 200)
    view.resize(300, 200)
    view.set_points([(48.137, 11.575, "a.jpg"), (48.14, 11.58, "b.jpg")])
    z = view.zoom
    ox, oy = view._origin()
    tx, ty = int(ox // mv.TILE), int(oy // mv.TILE)
    path = mv.tile_path(z, tx, ty)
    os.makedirs(os.path.dirname(path))
    img = QImage(256, 256, QImage.Format.Format_RGB32)
    img.fill(QColor("#336699"))
    img.save(path)
    shot = view.grab().toImage()
    corner = shot.pixelColor(int(tx * mv.TILE - ox) + 5 if tx * mv.TILE - ox > 0 else 5,
                             int(ty * mv.TILE - oy) + 5 if ty * mv.TILE - oy > 0 else 5)
    assert corner.name() in ("#336699", "#e5e3df")
    pos = view.screen_pos(48.137, 11.575)
    assert 0 <= pos.x() <= 300 and 0 <= pos.y() <= 200


def test_map_wheel_zooms_not_page(window):  # noqa: F811
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication, QScrollArea, QVBoxLayout, QWidget

    from panepilot import mapview as mv

    area = QScrollArea()
    inner = QWidget()
    lay = QVBoxLayout(inner)
    view = mv.MapView(inner, 200)
    lay.addWidget(view)
    inner.setMinimumHeight(1200)
    area.setWidget(inner)
    area.setWidgetResizable(True)
    area.resize(300, 300)
    area.show()
    QApplication.processEvents()
    view.set_points([(48.137, 11.575, "a.jpg")])
    before = view.zoom
    pos = QPointF(view.rect().center())
    ev = QWheelEvent(pos, QPointF(view.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(view, ev)
    assert view.zoom == before + 1 and area.verticalScrollBar().value() == 0 and ev.isAccepted()
    area.close()


def test_map_in_sidebar(window, tmp_path, qtbot):  # noqa: F811
    from test_v093 import _open

    make_photo(tmp_path / "a.jpg")
    make_photo(tmp_path / "b.jpg", gps=False)
    pane = _open(window, qtbot, tmp_path)
    items = {it.record.name: it for it in pane.meta_model.items}
    pane.show_selection([items["a.jpg"]])
    assert pane.map_view is not None
    if True:
        assert not pane.map_view.isHidden() and len(pane.map_view.points) == 1
        pane.show_selection([items["b.jpg"]])
        assert pane.map_view.isHidden()
