"""Tests for 1.22: similar images and videos by picture content."""

import random
import shutil
import subprocess

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from test_mainwindow import window  # noqa: F401


def _photo(seed, size=(800, 600)):
    from PIL import Image, ImageDraw

    rnd = random.Random(seed)
    im = Image.new("RGB", size, (rnd.randint(0, 255),) * 3)
    d = ImageDraw.Draw(im)
    for _ in range(30):
        x = sorted(rnd.randint(0, size[0]) for _ in range(2))
        y = sorted(rnd.randint(0, size[1]) for _ in range(2))
        d.ellipse([x[0], y[0], x[1], y[1]], fill=tuple(rnd.randint(0, 255) for _ in range(3)))
    return im


def _info(path):
    import os

    from panepilot.duplicates import FileInfo

    st = os.stat(path)
    return FileInfo(str(path), st.st_size, st.st_mtime)


def test_image_fingerprints(tmp_path):
    from PIL import Image, ImageEnhance

    from panepilot import fingerprint as fp

    a = _photo(1)
    a.save(tmp_path / "a.jpg", quality=90)
    a.resize((200, 150)).save(tmp_path / "a_klein.png")
    ImageEnhance.Brightness(a).enhance(1.1).save(tmp_path / "a_hell.webp", quality=60)
    _photo(2).save(tmp_path / "b.jpg")
    pa = fp.image_print(str(tmp_path / "a.jpg"))
    assert (pa.width, pa.height) == (800, 600)
    for name in ("a_klein.png", "a_hell.webp"):
        assert fp.print_similarity(pa, fp.image_print(str(tmp_path / name))) >= 0.95, name
    assert fp.print_similarity(pa, fp.image_print(str(tmp_path / "b.jpg"))) < 0.8
    (tmp_path / "kaputt.jpg").write_bytes(b"\xff\xd8kaputt")
    assert fp.image_print(str(tmp_path / "kaputt.jpg")) is None
    assert fp.kind_of("x.HEIC") == fp.KIND_IMAGE and fp.kind_of("x.mkv") == fp.KIND_VIDEO
    assert fp.kind_of("x.cr2") is None and fp.kind_of("x.txt") is None
    # Hochkant gespeichert (EXIF-Ausrichtung 6): Auflösung wie angezeigt
    exif = Image.Exif()
    exif[0x0112] = 6
    a.save(tmp_path / "hoch.jpg", exif=exif)
    ph = fp.image_print(str(tmp_path / "hoch.jpg"))
    assert (ph.width, ph.height) == (600, 800)


def test_visual_groups_and_cache(tmp_path, monkeypatch):
    from panepilot import duplicates as d
    from panepilot import fingerprint as fp

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    a = _photo(1)
    a.save(tmp_path / "Urlaub.jpg", quality=90)
    a.resize((400, 300)).save(tmp_path / "Urlaub klein.png")
    _photo(2).save(tmp_path / "Anders.jpg")
    (tmp_path / "notiz.txt").write_text("x")
    files = [_info(p) for p in sorted(tmp_path.iterdir()) if p.is_file()]
    groups = d.visual_groups(files, 90)
    assert len(groups) == 1
    g = groups[0]
    assert [f.name for f in g.files] == ["Urlaub.jpg", "Urlaub klein.png"]  # höchste Auflösung zuerst
    assert d.resolution_text(g.files[0]) == "800 × 600"
    # Zwischenspeicher: zweiter Lauf erstellt keine neuen Fingerabdrücke
    calls = []
    real = fp.make_print
    monkeypatch.setattr(fp, "make_print", lambda path, stop=lambda: False: calls.append(path) or real(path, stop))
    files = [_info(p) for p in sorted(tmp_path.iterdir()) if p.is_file()]
    assert len(d.visual_groups(files, 90)) == 1 and calls == []
    assb = tmp_path / "Anders.jpg"
    _photo(3).save(assb)  # geändert → neu
    files = [_info(p) for p in sorted(tmp_path.iterdir()) if p.is_file()]
    d.visual_groups(files, 90)
    assert calls == [str(assb)]
    assert d.visual_groups(files, 90, stop=lambda: True) == []
    assert (tmp_path / "cache" / "PanePilot" / "fingerprints.sqlite").is_file()


def test_resolution_text():
    from panepilot.duplicates import FileInfo, resolution_text

    assert resolution_text(FileInfo("/a", 1, 0)) == ""
    assert resolution_text(FileInfo("/a", 1, 0, 1920, 1080, 5432.4)) == "1920 × 1080  (1:30:32)"
    assert resolution_text(FileInfo("/a", 1, 0, 640, 360, 75)) == "640 × 360  (1:15)"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")
def test_video_fingerprints(tmp_path, monkeypatch):
    from panepilot import duplicates as d
    from panepilot import fingerprint as fp

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))

    def make(name, size, src="testsrc", dur=4):
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"{src}=s={size}:d={dur}:r=10", "-pix_fmt",
                        "yuv420p", str(tmp_path / name)], check=True, timeout=120)

    make("Film.mp4", "640x360")
    make("Film klein.mkv", "320x180")
    make("Anderer Film.mp4", "640x360", "smptebars")
    make("Kurz.mp4", "640x360", dur=2)
    pa = fp.video_print(str(tmp_path / "Film.mp4"))
    assert pa is not None and len(pa.hashes) == 5 and (pa.width, pa.height) == (640, 360)
    assert abs(pa.duration - 4) < 0.2
    files = [_info(p) for p in sorted(tmp_path.iterdir()) if p.is_file()]
    groups = d.visual_groups(files, 90)
    assert [[f.name for f in g.files] for g in groups] == [["Film.mp4", "Film klein.mkv"]]
    assert "(0:04)" in d.resolution_text(groups[0].files[0])


def test_window_visual_mode(window, qtbot, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import duplicates as d

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    folder = tmp_path / "bilder"
    folder.mkdir()
    a = _photo(1)
    a.save(folder / "gross.jpg", quality=90)
    a.resize((300, 225)).save(folder / "klein.jpg", quality=50)
    win = d.DuplicateWindow(window, str(folder), None)
    qtbot.addWidget(win)
    assert not win.visual.isEnabled() and win.visual.value() == 90
    win.mode_buttons[d.MODE_VISUAL].setChecked(True)
    assert win.visual.isEnabled() and win.visual_label.text() == "90 %" and not win.similar.isEnabled()
    win.start_or_stop()
    qtbot.waitUntil(lambda: win.thread is None, timeout=20000)
    assert len(win.groups) == 1 and not win.tree.isColumnHidden(4)
    items = [c for _t, c in win.file_items()]
    assert [c.text(0) for c in items] == ["gross.jpg", "klein.jpg"] and items[0].text(4) == "800 × 600"
    assert win.pick_actions[d.PICK_RESOLUTION].isVisible()
    win.pick(d.PICK_RESOLUTION)
    assert [c.checkState(0) == Qt.CheckState.Checked for c in items] == [False, True]
    from panepilot import thumbnails

    thumbnails.loader().wait_idle()
    QApplication.processEvents()
    qtbot.waitUntil(lambda: not items[0].icon(0).isNull(), timeout=5000)
    assert d.DupOptions.from_dict(window.settings.get("dup_last")).mode == d.MODE_VISUAL
    # andere Art: Spalte wieder weg
    win.mode_buttons[d.MODE_NAME].setChecked(True)
    win.start_or_stop()
    qtbot.waitUntil(lambda: win.thread is None, timeout=10000)
    assert win.tree.isColumnHidden(4) and not win.pick_actions[d.PICK_RESOLUTION].isVisible()
    win.close()
