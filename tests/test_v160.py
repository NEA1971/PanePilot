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
    assert win.groups == [] and win.summary.text() == dup.summary_text([])
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
