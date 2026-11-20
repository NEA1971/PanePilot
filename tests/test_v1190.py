"""Tests for 1.19: last run of saved syncs, icon view with thumbnails, new icons."""

import json
import os
import shutil
import subprocess

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QWheelEvent
from PySide6.QtWidgets import QApplication

from test_mainwindow import window  # noqa: F401


# --- Letzter Lauf (L-1900/1901) -----------------------------------------------------------------------------
def test_last_run_record_and_keep(window, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import folderdiff as fd
    from panepilot import syncprofiles as sp

    monkeypatch.setattr(sp, "config_dir", lambda: tmp_path / "cfg")
    sp.put(sp.Profile("Fotos", "/a", "/b"))
    assert sp.load()[0].last is None
    res = fd.Result(copied=3, overwritten=1, deleted=2, errors=[(f"x{i}.jpg", "Zugriff verweigert") for i in range(7)])
    last = sp.record_run("fotos", res)
    assert last.result == sp.RESULT_ERRORS and last.failed == 7 and len(last.errors) == sp.LAST_ERRORS
    assert last.errors[0] == "x0.jpg: Zugriff verweigert"
    prof = sp.load()[0]
    assert (prof.last.copied, prof.last.overwritten, prof.last.deleted) == (3, 1, 2)
    # erneutes Speichern (z. B. andere Optionen) behält den letzten Lauf, Umbenennen ebenso
    sp.put(sp.Profile("Fotos", "/a", "/c"))
    assert sp.load()[0].last is not None and sp.load()[0].right == "/c"
    prof = sp.load()[0]
    prof.name = "Bilder"
    sp.put(prof, old_name="Fotos")
    assert [p.name for p in sp.load()] == ["Bilder"] and sp.load()[0].last.failed == 7
    assert sp.record_run("gibtsnicht", res) is None
    ok = sp.record_run("Bilder", fd.Result(copied=1))
    assert ok.ok and ok.errors == []
    assert sp.record_run("Bilder", fd.Result(cancelled=True)).result == sp.RESULT_CANCELLED
    # kaputte Daten werden ignoriert
    assert sp.LastRun.from_dict({"at": ""}) is None and sp.LastRun.from_dict("x") is None
    r = sp.LastRun.from_dict({"at": "2026-11-20T10:00:00", "result": "???", "copied": -1, "errors": [1, "a"]})
    assert r.result == sp.RESULT_OK and r.copied == 0 and r.errors == ["a"]


def test_last_run_display(window, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import folderdiff as fd
    from panepilot import syncmode as sm
    from panepilot import syncprofiles as sp

    monkeypatch.setattr(sp, "config_dir", lambda: tmp_path / "cfg")
    left, right = tmp_path / "L", tmp_path / "R"
    left.mkdir()
    right.mkdir()
    (left / "a.txt").write_text("a")
    sp.put(sp.Profile("Test", str(left), str(right)))
    pane = sm.SyncPane(window)
    pane.load_profile("Test")
    assert pane.last_row.isHidden()
    infos = []
    monkeypatch.setattr(sm, "show_info", lambda *x: infos.append(x[2]))
    monkeypatch.setattr(sm, "show_error", lambda *x: infos.append(x[2]))
    pane.finish(str(left), str(right), fd.Result(copied=1))
    assert not pane.last_row.isHidden() and "Letzter Lauf" in pane.last_text.text()
    assert "Fehlerfrei" in pane.last_row.toolTip() and "1 kopiert" in pane.last_row.toolTip()
    pane.finish(str(left), str(right), fd.Result(errors=[("b.txt", "Kein Platz")]))
    tip = pane.last_row.toolTip()
    assert "Mit Fehlern" in tip and "• b.txt: Kein Platz" in tip
    # Menü „Gespeicherte Abgleiche“: Symbol, Datum und Tooltip
    window._fill_sync_menu()
    acts = [a for a in window.sync_menu.actions() if a.text().startswith("Test")]
    assert acts and "\t" in acts[0].text() and not acts[0].icon().isNull() and "Kein Platz" in acts[0].toolTip()
    assert window.sync_menu.toolTipsVisible()
    # ohne gespeicherten Abgleich wird nichts gemerkt
    pane.load_profile(None)
    pane.finish(str(left), str(right), fd.Result(copied=5))
    assert sp.load()[0].last.failed == 1 and pane.last_row.isHidden()


def test_status_icons():
    from panepilot import syncprofiles as sp
    from panepilot.app import create_app

    create_app([])
    from panepilot import toolicons as ti

    assert ti.last_run_icon(None).isNull()
    ok = ti.last_run_icon(sp.LastRun("2026-11-20T10:00:00"))
    bad = ti.last_run_icon(sp.LastRun("2026-11-20T10:00:00", sp.RESULT_ERRORS))
    assert not ok.isNull() and not bad.isNull()
    img = ok.pixmap(24, 24).toImage()
    greens = sum(1 for x in range(24) for y in range(24)
                 if (c := img.pixelColor(x, y)).alpha() > 200 and c.green() > c.red() + 40)
    assert greens > 20  # grüner Haken


# --- Neue Symbole (L-1920 ff.) ------------------------------------------------------------------------------
def test_new_icons_registered(window):  # noqa: F811
    from panepilot import toolicons as ti

    for aid in ("toggle_stacked", "duplicate", "properties", "backup_now", "backup_restore", "server_manager",
                "help", "help_online", "check_updates", "donate", "toggle_icon_view", "meta_wizard"):
        assert aid in ti._PAINTED, aid
        img = ti._PAINTED[aid]().pixmap(24, 24).toImage()
        assert any(img.pixelColor(x, y).alpha() for x in range(24) for y in range(24)), aid
        assert ti.action_icon(aid) is not None and not ti.action_icon(aid).isNull(), aid


# --- Symbolansicht (L-1910 ff.) ------------------------------------------------------------------------------
def _png(path, color="red", w=400, h=300):
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(color))
    assert img.save(str(path))


def test_icon_view_toggle_and_selection(window, qtbot, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    panel = window.sides["left"].panel
    assert not panel.icon_mode and panel.list_widget() is panel.view
    window.trigger("toggle_icon_view")
    QApplication.processEvents()
    assert panel.icon_mode and panel.icon_view.isVisible() and not panel.view.isVisible()
    assert window.qactions["toggle_icon_view"].isChecked()
    assert QApplication.focusWidget() in (panel.icon_view, panel.parent_bar)  # Cursor auf „..“: Zeile darüber
    # gleiche Markierung wie die Liste
    assert panel.icon_view.selectionModel() is panel.view.selectionModel()
    panel.select_names(["eins.txt"], current="eins.txt")
    assert [e.name for e in panel.selected_entries()] == ["eins.txt"]
    panel.icon_view.clearSelection()
    panel.select_all()
    assert sorted(e.name for e in panel.selected_entries()) == ["eins.txt", "sub"]
    # Klick in der Symbolansicht markiert die ganze Zeile
    panel.icon_view.clearSelection()
    row = panel.model.row_of("sub")
    rect = panel.icon_view.visualRect(panel.model.index(row, panel.icon_view.modelColumn()))
    qtbot.mouseClick(panel.icon_view.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert [e.name for e in panel.selected_entries()] == ["sub"] and panel.current_entry().name == "sub"
    # Tastatur: Kürzel der Liste wirken auch hier (Strg+A)
    from test_mainwindow import press

    panel.icon_view.setFocus()
    press(qtbot, window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert len(panel.selected_entries()) == 2
    # Eingabetaste öffnet den Ordner
    panel.icon_view.clearSelection()
    panel.select_names([], current="sub")
    press(qtbot, window, Qt.Key.Key_Return)
    assert panel.current_path.endswith(os.sep + "sub")
    # anderes Fenster: eigene Ansicht
    window.set_active_side("right")
    assert not window.qactions["toggle_icon_view"].isChecked()
    window.set_active_side("left")
    assert window.qactions["toggle_icon_view"].isChecked()
    window.trigger("toggle_icon_view")
    assert not panel.icon_mode and panel.view.isVisible()


def test_icon_sizes_and_restart(window, qtbot, tmp_path, monkeypatch):  # noqa: F811
    from panepilot.filepanel import ICON_SIZES
    from panepilot.mainwindow import MainWindow

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    panel = window.sides["right"].panel
    window.set_active_side("right")
    window.trigger("icons_large")  # Größe wählen schaltet die Symbolansicht ein
    assert panel.icon_mode and panel.icon_size == 256 and window.qactions["icons_large"].isChecked()
    grid_large = panel.icon_view.gridSize()
    # Strg+Mausrad
    ev = QWheelEvent(QPoint(10, 10), panel.icon_view.mapToGlobal(QPoint(10, 10)), QPoint(), QPoint(0, -120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(panel.icon_view.viewport(), ev)
    assert panel.icon_size == 128 and window.qactions["icons_medium"].isChecked()
    assert panel.icon_view.gridSize().height() < grid_large.height()
    panel.zoom_icons(-1)
    panel.zoom_icons(-1)  # bleibt bei der kleinsten Größe
    assert panel.icon_size == ICON_SIZES[0]
    panel.set_icon_size(130)
    assert panel.icon_size == 128
    window.save_state()
    state = json.load(open(os.path.join(os.environ["PANEPILOT_CONFIG_DIR"], "Settings", "state.json")))
    assert state["sides"]["right"]["icon_view"] is True and state["sides"]["right"]["icon_size"] == 128
    assert state["sides"]["left"]["icon_view"] is False
    again = MainWindow()
    qtbot.addWidget(again)
    assert again.sides["right"].panel.icon_mode and again.sides["right"].panel.icon_size == 128
    assert not again.sides["left"].panel.icon_mode


def test_icon_view_sort_menu_and_rename(window, qtbot, monkeypatch, tmp_path):  # noqa: F811
    from panepilot.filemodel import COL_SIZE

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    panel = window.active
    panel.set_icon_mode(True)
    window._fill_sort_menu()
    acts = [a for a in window.sort_menu.actions() if a.text() == "Größe"]
    acts[0].trigger()
    assert panel.sort_state()[0] == COL_SIZE
    window._fill_sort_menu()
    desc = [a for a in window.sort_menu.actions() if a.text() == "Absteigend"][0]
    desc.trigger()
    assert panel.sort_state() == (COL_SIZE, int(Qt.SortOrder.DescendingOrder.value))
    panel.select_names([], current="eins.txt")
    panel.start_rename()
    QApplication.processEvents()
    assert panel.icon_view.state() == panel.icon_view.State.EditingState


def test_icon_view_context_menu_hit(window, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    panel = window.active
    panel.set_icon_mode(True)
    QApplication.processEvents()
    got = []
    monkeypatch.setattr(window, "_file_context_menu", lambda side, pos: got.append((side, pos)))
    panel.icon_view.customContextMenuRequested.emit(QPoint(5, 5))
    assert got == [("left", panel.icon_view.viewport().mapToGlobal(QPoint(5, 5)))]


# --- Vorschaubilder (L-1912) ----------------------------------------------------------------------------------
def test_thumbnail_cache_roundtrip(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication as _A  # noqa: F401

    from panepilot import thumbnails as th
    from panepilot.app import create_app

    create_app([])
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    img_path = tmp_path / "Foto mit Ä.png"
    _png(img_path)
    assert th.file_uri(str(img_path)).startswith("file://") and "%C3%84" in th.file_uri(str(img_path))
    assert th.file_uri("/a b/c(1)&.jpg") == "file:///a%20b/c(1)&.jpg"
    mtime = os.path.getmtime(img_path)
    assert th.read_cached(str(img_path), mtime, 128) is None
    img = th.thumbnail(str(img_path), mtime, 128)
    assert img is not None and max(img.width(), img.height()) == 128
    cached = th.cache_path(str(img_path), 128)
    assert cached.startswith(str(tmp_path / "cache" / "thumbnails" / "normal")) and os.path.isfile(cached)
    assert oct(os.stat(cached).st_mode & 0o777) == "0o600"
    again = th.read_cached(str(img_path), mtime, 100)
    assert again is not None and again.text("Thumb::MTime") == str(int(mtime))
    assert th.read_cached(str(img_path), mtime + 5, 128) is None  # Datei geändert → ungültig
    large = th.thumbnail(str(img_path), mtime, 256)
    assert max(large.width(), large.height()) == 256 and "/large/" in th.cache_path(str(img_path), 256)
    # kleine Bilder werden nicht vergrößert
    small = tmp_path / "klein.png"
    _png(small, "blue", 20, 10)
    assert th.generate(str(small), 128).width() == 20
    assert th.kind_of("x.txt") is None and th.kind_of("x.pdf") == "pdf" and th.kind_of("x.mp3") == "audio"
    assert th.kind_of("x.mkv") == "video" and th.kind_of("x.jpg") == "image"


def test_thumbnail_audio_cover_and_pdf(tmp_path, monkeypatch):
    from panepilot import thumbnails as th
    from panepilot.app import create_app

    create_app([])
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    from mutagen.id3 import APIC, ID3

    mp3 = tmp_path / "lied.mp3"
    mp3.write_bytes((b"\xff\xfb\x90\x64" + b"\x00" * 413) * 20)  # gültige MPEG-Rahmen
    cover = QImage(300, 300, QImage.Format.Format_RGB32)
    cover.fill(QColor("green"))
    tags = ID3()
    tags.add(APIC(encoding=3, mime="image/png", type=3, desc="", data=th.to_png(cover)))
    tags.save(str(mp3))
    img = th.generate(str(mp3), 128)
    assert img is not None and img.width() == 128 and img.pixelColor(64, 64).green() > 100
    try:
        import pypdfium2  # noqa: F401
    except Exception:  # noqa: BLE001
        pytest.skip("pypdfium2 fehlt")
    from PySide6.QtGui import QPageSize, QPainter, QPdfWriter

    pdf = tmp_path / "doc.pdf"
    writer = QPdfWriter(str(pdf))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    p = QPainter(writer)
    p.fillRect(0, 0, 2000, 2000, QColor("black"))
    p.end()
    img = th.generate(str(pdf), 256)
    assert img is not None and img.height() == 256 and img.width() < 256


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")
def test_thumbnail_video_frame_and_poster(tmp_path, monkeypatch):
    from panepilot import thumbnails as th
    from panepilot.app import create_app

    create_app([])
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    vid = tmp_path / "film.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=1", "-pix_fmt",
                    "yuv420p", str(vid)], check=True, timeout=60)
    img = th.generate(str(vid), 128)  # nur 1 s lang: erstes Bild
    assert img is not None and img.width() == 128 and img.pixelColor(64, 30).blue() > 150
    # MP4 mit Poster: das Poster gewinnt
    from mutagen.mp4 import MP4, MP4Cover

    poster = QImage(200, 300, QImage.Format.Format_RGB32)
    poster.fill(QColor("red"))
    m = MP4(str(vid))
    m["covr"] = [MP4Cover(th.to_png(poster), imageformat=MP4Cover.FORMAT_PNG)]
    m.save()
    img = th.generate(str(vid), 128)
    assert img is not None and img.height() == 128 and img.pixelColor(40, 64).red() > 150


def test_icon_view_paints_thumbnails(window, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import thumbnails as th

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    folder = tmp_path / "bilder"
    folder.mkdir()
    for i, color in enumerate(("red", "green", "blue")):
        _png(folder / f"bild{i}.png", color)
    (folder / "text.txt").write_text("x")
    panel = window.active
    panel.set_icon_mode(True)
    panel.navigate(str(folder))
    panel.icon_view.viewport().repaint()
    loader = th.loader()
    assert loader.wait_idle()
    panel.icon_view.viewport().repaint()
    e = next(e for e in panel.model.entries() if e.name == "bild1.png")
    pix = loader.get(e.path, e.mtime, 128)
    assert pix is not None and not pix.isNull()
    assert os.path.isfile(th.cache_path(e.path, 128))
    txt = next(e for e in panel.model.entries() if e.name == "text.txt")
    assert panel.icon_view.thumbnail_for(panel.model.index(panel.model.row_of(txt.name), 0)) is None
    grab = panel.icon_view.grab().toImage()
    assert any(grab.pixelColor(x, y).green() > 120 and grab.pixelColor(x, y).red() < 60
               for x in range(0, grab.width(), 3) for y in range(0, grab.height(), 3))
