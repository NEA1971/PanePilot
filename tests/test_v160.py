"""Tests for 1.6: find duplicates."""

import os
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from test_mainwindow import window  # noqa: F401


def _write(path, data: bytes, mtime: float | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _tree(tmp_path):
    root = tmp_path / "Filme"
    big = os.urandom(300 * 1024)  # größer als der Schnellvergleich
    _write(root / "Alien (1979).mkv", big, 1_000_000)
    _write(root / "Alien (1979).mp4", b"anders", 2_000_000)
    _write(root / "Alien (1979).eng.srt", b"untertitel")
    _write(root / "Sicherung" / "Alien Kopie.mkv", big, 3_000_000)
    _write(root / "Sicherung" / "tief" / "Alien Kopie2.mkv", big, 4_000_000)
    same_size = bytearray(big)
    same_size[-1] ^= 0xFF  # gleich groß, aber anderer Inhalt (erst am Ende verschieden)
    _write(root / "fast gleich.mkv", bytes(same_size))
    _write(root / "a" / "notiz.txt", b"hallo")
    _write(root / "b" / "notiz.txt", b"hallo")
    _write(root / "c" / "notiz.txt", b"welt!")  # gleicher Name, gleiche Größe, anderer Inhalt
    _write(root / "leer1.txt", b"")
    _write(root / "leer2.txt", b"")
    _write(root / ".versteckt" / "Alien (1979).avi", b"x")
    os.symlink(root / "Alien (1979).mkv", root / "link.mkv")
    return root


def _keys(groups):
    return {g.key: sorted(os.path.relpath(f.path) for f in g.files) for g in groups}


def test_content_mode(tmp_path, monkeypatch):
    from panepilot import duplicates as dup

    root = _tree(tmp_path)
    monkeypatch.chdir(root)
    files = dup.collect([str(root)], dup.DEPTH_ALL, hidden=False)
    assert not any(f.name == "link.mkv" for f in files)  # Verknüpfungen nicht verfolgen
    assert not any(".versteckt" in f.path for f in files)
    read = []
    groups = dup.find_groups(files, dup.MODE_CONTENT, on_bytes=read.append)
    keys = _keys(groups)
    assert keys == {"Alien (1979).mkv": ["Alien (1979).mkv", "Sicherung/Alien Kopie.mkv",
                                         "Sicherung/tief/Alien Kopie2.mkv"],
                    "notiz.txt": ["a/notiz.txt", "b/notiz.txt"]}  # leere Dateien zählen nicht
    assert "fast gleich.mkv" not in str(keys)
    assert dup.summary_text(groups).startswith("2 ")


def test_name_and_namesize_modes(tmp_path, monkeypatch):
    from panepilot import duplicates as dup

    root = _tree(tmp_path)
    monkeypatch.chdir(root)
    files = dup.collect([str(root)], dup.DEPTH_ALL, hidden=False)
    keys = _keys(dup.find_groups(files, dup.MODE_NAME))
    assert keys["Alien (1979)"] == ["Alien (1979).mkv", "Alien (1979).mp4"]  # .eng.srt zählt nicht (Punkt 4)
    assert keys["notiz"] == ["a/notiz.txt", "b/notiz.txt", "c/notiz.txt"]
    keys = _keys(dup.find_groups(files, dup.MODE_NAMESIZE))
    assert keys == {"notiz.txt": ["a/notiz.txt", "b/notiz.txt", "c/notiz.txt"]}
    hidden = dup.collect([str(root)], dup.DEPTH_ALL, hidden=True)
    assert len(_keys(dup.find_groups(hidden, dup.MODE_NAME))["Alien (1979)"]) == 3


def test_depth_filter_min_size_and_other_folder(tmp_path, monkeypatch):
    from panepilot import duplicates as dup

    root = _tree(tmp_path)
    monkeypatch.chdir(root)
    one = dup.collect([str(root)], 1, hidden=False)
    assert all(os.path.dirname(f.path) == str(root) for f in one)
    two = dup.collect([str(root)], 2, hidden=False)
    assert any("Sicherung/Alien Kopie.mkv" in f.path for f in two) and not any("tief" in f.path for f in two)
    only = dup.collect([str(root)], dup.DEPTH_ALL, hidden=False, pattern="*.mkv;*.mp4", min_size=1000)
    assert {f.name for f in only} == {"Alien (1979).mkv", "Alien Kopie.mkv", "Alien Kopie2.mkv", "fast gleich.mkv"}
    both = dup.collect([str(root), str(root / "Sicherung")], dup.DEPTH_ALL, hidden=False)  # nichts doppelt
    assert len(both) == len({f.path for f in both}) == len(dup.collect([str(root)], dup.DEPTH_ALL, False))


def test_cancel(tmp_path):
    from panepilot import duplicates as dup

    root = _tree(tmp_path)
    files = dup.collect([str(root)], dup.DEPTH_ALL, hidden=False)
    assert dup.find_groups(files, dup.MODE_CONTENT, stop=lambda: True) == []


def test_options_roundtrip():
    from panepilot import duplicates as dup

    o = dup.DupOptions.from_dict({"mode": "content", "depth": 3, "pattern": "*.mkv", "min_size_mb": 5,
                                  "other": True, "folder": "/x"})
    assert (o.mode, o.depth, o.pattern, o.min_size_mb, o.other, o.folder) == ("content", 3, "*.mkv", 5, True, "")
    assert dup.DupOptions.from_dict({"mode": "quatsch", "depth": 99}).mode == "name"
    assert dup.DupOptions.from_dict(None).mode == "name"  # Vorgabe b)


def test_window_flow(window, tmp_path, qtbot, monkeypatch):  # noqa: F811
    from panepilot import duplicates as dup

    root = _tree(tmp_path)
    window.sides["left"].panel.navigate(str(root))
    window.set_active_side("left")
    window.trigger("find_duplicates")
    QApplication.processEvents()
    win = next(w for w in QApplication.topLevelWidgets() if isinstance(w, dup.DuplicateWindow) and w.isVisible())
    assert win.folder_edit.text() == str(root) and win.mode_buttons["name"].isChecked()
    assert win.other_check.isEnabled()  # rechtes Fenster zeigt einen anderen Ordner
    win.mode_buttons["content"].setChecked(True)
    win.start_or_stop()
    qtbot.waitUntil(lambda: win.thread is None, timeout=10000)
    assert len(win.groups) == 2 and "2 " in win.summary.text()
    assert window.settings.get("dup_last")["mode"] == "content"
    win.pick(dup.PICK_NEWEST)
    chosen = sorted(f.name for f in win.checked())
    assert chosen == ["Alien (1979).mkv", "Alien Kopie.mkv", "notiz.txt"]  # je Gruppe bleibt die neueste
    # Papierkorb: Rückfrage, dann verschoben
    asked, moved = [], []
    monkeypatch.setattr("panepilot.dialogs.confirm", lambda *a, **k: asked.append((a[2], k)) or True)
    monkeypatch.setattr("panepilot.fileops.move_to_trash", lambda p: (moved.append(p), os.remove(p)))
    win.move_to_trash()
    assert len(moved) == 3 and not asked[0][1].get("warning")
    assert win.groups == [] and win.summary.text().startswith(dup.summary_text([]))
    # alle einer Gruppe angekreuzt: deutliche Warnung
    win.start_or_stop()
    qtbot.waitUntil(lambda: win.thread is None, timeout=10000)
    win.mode_buttons["name"].setChecked(True)
    win.start_or_stop()
    qtbot.waitUntil(lambda: win.thread is None, timeout=10000)
    for _top, child in win.file_items():
        child.setCheckState(0, Qt.CheckState.Checked)
    asked.clear()
    monkeypatch.setattr("panepilot.dialogs.confirm", lambda *a, **k: asked.append((a[2], k)) or False)
    win.move_to_trash()
    assert asked and asked[0][1]["warning"] and "Achtung" in asked[0][0]
    # Im Dateifenster zeigen
    top = win.tree.topLevelItem(0)
    win.tree.setCurrentItem(top.child(0))
    info = top.child(0).data(0, Qt.ItemDataRole.UserRole)
    win.show_in_panel()
    assert window.active.current_path == os.path.dirname(info.path)
    assert window.active.current_entry().name == info.name
    # Liste speichern
    out = tmp_path / "liste.txt"
    monkeypatch.setattr(dup.QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    win.save_list()
    text = out.read_text(encoding="utf-8")
    assert "[1]" in text and info.path in text
    win.close()
    assert window.settings.get("dup_geometry")


# --- 1.6.1: MKV-Anhänge selbst lesen (statt ffmpeg, das das ganze Video gelesen hat) ---------------------------
def test_mkv_attachments_read_directly(tmp_path, monkeypatch):
    import shutil
    import subprocess

    import pytest

    from panepilot import tags as tg
    from panepilot import videotags as vt

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg missing")
    src = os.path.join(os.path.dirname(__file__), "data", "video", "clip.mkv")
    png = os.path.join(os.path.dirname(__file__), "..", "docs", "screenshots", "ftp.png")
    out = tmp_path / "Film.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-attach", png, "-metadata:s:t:0", "mimetype=image/png",
                    "-metadata:s:t:0", "filename=cover.png", "-c", "copy", str(out)], check=True)
    att = vt.mkv_attachments(str(out))
    assert [(n, m) for n, m, _d in att] == [("cover.png", "image/png")]
    assert att[0][2] == open(png, "rb").read()
    assert vt.mkv_attachments(src) == [] and vt.mkv_attachments(str(tmp_path / "fehlt.mkv")) == []
    # das Einlesen startet dafür kein ffmpeg mehr
    calls = []
    real = vt._run
    monkeypatch.setattr(vt, "_run", lambda args, *a, **k: calls.append(args[0]) or real(args, *a, **k))
    rec = tg.read_file(str(out))
    assert len(rec.pictures) == 1 and rec.pictures[0].desc == "cover.png"
    assert not any(os.path.basename(c) == "ffmpeg" for c in calls)


# --- 1.6.2 ----------------------------------------------------------------------------------------------------
def test_comma_separates_patterns():
    from panepilot.filters import FilterSpec

    m = FilterSpec("*.mkv, *.mp4").matcher()
    assert m("Alien (1979).mkv") and m("a.MP4") and not m("a.avi")
    assert FilterSpec("*.mkv;*.mp4").matcher()("x.mp4")


def test_id_mode_and_checked_count(tmp_path):
    from panepilot import duplicates as dup

    assert dup.file_id("Alien (1979) [imdbid-tt0078748].mkv") == "imdbid-tt0078748"
    assert dup.file_id("Alien (1979) [tmdbid-348] [imdbid-TT0078748].mp4") == "imdbid-tt0078748"
    assert dup.file_id("Alien {tmdb-348}.mkv") == "tmdbid-348" and dup.file_id("Alien (1979).mkv") is None
    root = tmp_path / "Movie"
    for name in ("Minions and Monsters (2026) [imdbid-tt32890033].mkv",
                 "Minions Monsters (2026) [imdbid-tt32890033].mp4",
                 "Minions Monsters (2026) [imdbid-tt32890033].eng.srt",
                 "Alien (1979) [imdbid-tt0078748].mp4", "Ohne Kennung (2000).mp4"):
        _write(root / name, name.encode())
    files = dup.collect([str(root)], dup.DEPTH_ALL, hidden=False, pattern="*.mkv,*.mp4")
    assert len(files) == 4
    groups = dup.find_groups(files, dup.MODE_ID)
    assert len(groups) == 1 and len(groups[0].files) == 2
    assert groups[0].key == "Minions and Monsters (2026)  [imdbid-tt32890033]"
    assert dup.summary_text(groups, 4).endswith("(4 Dateien geprüft)")
    assert dup.summary_text([], 0) == "Keine Duplikate gefunden. (0 Dateien geprüft)"


def test_meta_scan_parallel_keeps_order(tmp_path, monkeypatch):
    import threading

    from panepilot import metaprofile as mp
    from panepilot import tags as tg
    from panepilot.metawizard import MetaScanThread

    seen_threads = set()
    real = tg.read_file

    def slow(path):
        seen_threads.add(threading.get_ident())
        time.sleep(0.1)
        return real(path)
    monkeypatch.setattr(tg, "read_file", slow)
    src = os.path.join(os.path.dirname(__file__), "data", "video", "clip.mp4")
    files = []
    for i in range(30):
        p = tmp_path / f"v{i:02d}.mp4"
        p.write_bytes(open(src, "rb").read())
        files.append(str(p))
    th = MetaScanThread([str(tmp_path)], False)
    t0 = time.monotonic()
    recs = list(th._read_all(files, mp.VIDEO))
    assert [r.path for r in recs] == files and len(seen_threads) > 1
    assert time.monotonic() - t0 < 30 * 0.1 / 2  # deutlich schneller als nacheinander (3 s)
    th._stop = True
    assert list(th._read_all(files, mp.VIDEO)) == []
    seen_threads.clear()
    th._stop = False
    list(th._read_all(files[:3], mp.PHOTO))  # Fotos nacheinander
    assert len(seen_threads) == 1


def test_hang_log(tmp_path, monkeypatch):
    import faulthandler

    from panepilot.app import create_app, start_hang_log

    create_app([])
    path = start_hang_log(0.2)
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    try:
        time.sleep(0.6)  # Oberfläche „hängt“
    finally:
        timer = QApplication.instance().findChild(QTimer, "panepilotHangLog")
        timer.stop()
        timer.deleteLater()
        faulthandler.cancel_dump_traceback_later()
    text = open(path, encoding="utf-8").read()
    assert "PanePilot gestartet" in text and "test_hang_log" in text


# --- 1.6.3 ----------------------------------------------------------------------------------------------------
def test_refresh_with_many_selected_is_fast(window, tmp_path):  # noqa: F811
    root = tmp_path / "viele"
    root.mkdir()
    for i in range(1500):
        (root / f"datei {i:04d}.mp4").write_bytes(b"")
    panel = window.sides["left"].panel
    panel.navigate(str(root))
    panel.view.selectAll()
    assert len(panel.selected_entries()) == 1500
    t0 = time.monotonic()
    panel.refresh()
    assert time.monotonic() - t0 < 3
    assert len(panel.selected_entries()) == 1500
    panel.select_names(["datei 0003.mp4", "datei 0004.mp4", "datei 0010.mp4", "fehlt"], current="datei 0010.mp4")
    assert [e.name for e in panel.selected_entries()] == ["datei 0003.mp4", "datei 0004.mp4", "datei 0010.mp4"]
    assert panel.current_entry().name == "datei 0010.mp4"
    panel.select_names([])
    assert panel.selected_entries() == []


def test_meta_found_text_and_icon(window, tmp_path, qtbot):  # noqa: F811
    from panepilot.metawizard import found_text
    from panepilot.toolicons import action_icon

    assert found_text(432, 3246, 0) == "432 Musikdateien und 3246 Bilder"
    assert found_text(0, 1, 0) == "1 Bild" and found_text(0, 0, 0) == ""
    assert found_text(1, 2, 3) == "1 Musikdatei, 2 Bilder und 3 Videos"
    seen = []
    folder = tmp_path / "gemischt"
    folder.mkdir()
    import shutil
    shutil.copy(os.path.join(os.path.dirname(__file__), "data", "video", "clip.mp4"), folder / "a.mp4")
    window.sides["left"].panel.navigate(str(folder))
    window.set_active_side("left")
    window.trigger("meta_wizard")
    pane = window._meta_pane()
    seen.append(pane.summary.text())
    qtbot.waitUntil(lambda: window.meta_mode.get("scan") is None, timeout=10000)
    assert seen[0] in ("Dateien werden gesucht …", "Dateien werden gesucht … 1 Video gefunden")
    assert pane.summary.text().startswith("1 Dateien eingelesen") or "eingelesen" in pane.summary.text()
    window.meta_close()
    assert not action_icon("meta_wizard").isNull()
