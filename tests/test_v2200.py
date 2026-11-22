"""Tests for 2.2: archive button, archives opened like folders (read-only)."""

import os
import tarfile
import zipfile

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from test_mainwindow import window  # noqa: F401


def _make_zip(path):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("readme.txt", "hallo")
        zf.writestr("Urlaub/bild1.jpg", b"\xff\xd8bild1")
        zf.writestr("Urlaub/Strand/bild2.jpg", b"\xff\xd8bild2")
        zf.writestr("leer/", "")
        zf.writestr("../boese.txt", "nein")  # zeigt nach außen → wird nicht angezeigt
    return path


def _make_tgz(path, src_dir):
    (src_dir / "doc").mkdir(parents=True)
    (src_dir / "doc" / "a.txt").write_text("A")
    (src_dir / "b.txt").write_text("BB")
    with tarfile.open(path, "w:gz") as tar:
        tar.add(src_dir / "doc", arcname="doc")
        tar.add(src_dir / "b.txt", arcname="b.txt")
    return path


# --- archivefs ---------------------------------------------------------------------------------------------
def test_index_and_paths(tmp_path):
    from panepilot import archivefs as af

    z = _make_zip(tmp_path / "Fotos.zip")
    idx = af.read_index(str(z))
    assert sorted(i.name for i in idx.listdir("")) == ["Urlaub", "leer", "readme.txt"]
    assert sorted((i.name, i.is_dir) for i in idx.listdir("Urlaub")) == [("Strand", True), ("bild1.jpg", False)]
    assert idx.listdir("gibtsnicht") is None
    assert idx.size_of(["Urlaub"]) == len(b"\xff\xd8bild1") + len(b"\xff\xd8bild2")
    assert af.split_path(str(z)) == (str(z), "")
    assert af.split_path(str(z / "Urlaub" / "Strand")) == (str(z), "Urlaub/Strand")
    assert af.split_path(str(tmp_path)) is None
    (tmp_path / "x.txt").write_text("x")
    assert af.split_path(str(tmp_path / "x.txt" / "y")) is None
    assert af.join(str(z), "Urlaub/") == str(z) + "/Urlaub"

    t = _make_tgz(tmp_path / "pak.tar.gz", tmp_path / "src")
    parts = []
    idx2 = af.read_index(str(t), progress=parts.append)
    assert sorted(i.name for i in idx2.listdir("")) == ["b.txt", "doc"]
    assert parts and parts[-1] == 1.0


def test_extract_items(tmp_path):
    from panepilot import archivefs as af
    from panepilot.archives import _Ctx

    ctx = _Ctx(progress=lambda n, name: None, is_cancelled=lambda: False, error=lambda p, r: None)
    idx = af.read_index(str(_make_zip(tmp_path / "F.zip")))
    out = tmp_path / "out"
    out.mkdir()
    af.extract_items(idx, ["Urlaub/Strand", "Urlaub/bild1.jpg"], "Urlaub", str(out), ctx)
    assert (out / "Strand" / "bild2.jpg").read_bytes() == b"\xff\xd8bild2"
    assert (out / "bild1.jpg").exists() and not (out / "Urlaub").exists()
    out2 = tmp_path / "out2"
    out2.mkdir()
    af.extract_items(idx, ["leer"], "", str(out2), ctx)
    assert (out2 / "leer").is_dir()
    idx2 = af.read_index(str(_make_tgz(tmp_path / "p.tgz", tmp_path / "s")))
    out3 = tmp_path / "out3"
    out3.mkdir()
    af.extract_items(idx2, ["doc"], "", str(out3), ctx)
    assert (out3 / "doc" / "a.txt").read_text() == "A" and not (out3 / "b.txt").exists()


def test_parse_tool_lists():
    from panepilot import archivefs as af

    seven = ("7-Zip 23.01\n\nListing archive: x.7z\n\n--\nPath = x.7z\nType = 7z\n\n----------\n"
             "Path = Ordner\nSize = 0\nModified = 2024-05-01 10:11:12\nAttributes = D....\n\n"
             "Path = Ordner/a.txt\nSize = 12\nModified = 2024-05-01 10:11:13.1234567\nAttributes = A....\n"
             "Encrypted = +\n\n")
    rows = af.parse_7z_list(seven)
    assert [r["Path"] for r in rows] == ["Ordner", "Ordner/a.txt"] and rows[1]["Encrypted"] == "+"
    rar = ("UNRAR 7.00\n\nArchive: x.rar\nDetails: RAR 5\n\n        Name: dir\n        Type: Directory\n"
           "       mtime: 2024-05-01 10:11:12,000000000\n\n        Name: dir/f.txt\n        Type: File\n"
           "        Size: 5\n       mtime: 2024-05-01 10:11:12,000000000\n       Flags: encrypted\n")
    rows = af.parse_unrar_list(rar)
    assert [(r["Name"], r["Type"]) for r in rows] == [("dir", "Directory"), ("dir/f.txt", "File")]
    assert af._parse_time("2024-05-01 10:11:12,000") > 0


# --- Fenster -----------------------------------------------------------------------------------------------
@pytest.fixture
def zipped(window, tree):  # noqa: F811
    return _make_zip(tree / "a" / "Fotos.zip")


def test_browse_archive_like_folder(window, tree, zipped):  # noqa: F811
    panel = window.sides["left"].panel
    panel.refresh()
    panel.select_names(["Fotos.zip"], current="Fotos.zip")
    panel.open_current()  # Doppelklick/Enter → im Archiv (L-3206)
    assert panel.in_archive and panel.current_path == str(zipped)
    names = [e.name for e in panel.model.entries()]
    assert names[0] == ".." and sorted(names[1:]) == ["Urlaub", "leer", "readme.txt"]
    panel.select_names(["Urlaub"], current="Urlaub")
    panel.open_current()
    assert panel.current_path == str(zipped) + "/Urlaub" and panel.path_edit.text() == panel.current_path
    panel.go_up()
    assert panel.current_path == str(zipped) and panel.current_entry().name == "Urlaub"
    panel.go_up()
    assert not panel.in_archive and panel.current_path == str(tree / "a")
    assert panel.current_entry().name == "Fotos.zip"
    panel.back()
    assert panel.in_archive
    # Pfadzeile: direkt in einen Ordner im Archiv
    panel.path_edit.setText(str(zipped) + "/Urlaub/Strand")
    panel._on_path_entered()
    assert panel.current_path == str(zipped) + "/Urlaub/Strand"
    assert str(zipped) + "/Urlaub" not in window.recent_dirs


def test_open_with_app_setting(window, tree, zipped, monkeypatch):  # noqa: F811
    opened = []
    panel = window.sides["left"].panel
    monkeypatch.setattr(window, "_open_file", lambda p: opened.append(p))
    panel.open_file_requested.disconnect()
    panel.open_file_requested.connect(window._open_file)
    window.settings.set("archive_open", "app")
    from panepilot.settingsdialog import SettingsDialog

    dlg = SettingsDialog(window)
    assert dlg.archive_app.isChecked()
    dlg.accept()
    assert panel.open_archives_inside is False
    panel.refresh()
    panel.select_names(["Fotos.zip"], current="Fotos.zip")
    panel.open_current()
    assert opened == [str(zipped)] and not panel.in_archive


def test_read_only_and_copy_out(window, tree, zipped, qtbot, monkeypatch):  # noqa: F811
    import panepilot.archivecontrol as ac

    infos = []
    monkeypatch.setattr(ac, "show_info", lambda *a: infos.append(a[2]))
    monkeypatch.setattr("panepilot.mainwindow.show_info", lambda *a: infos.append(a[2]))
    window.settings.set("confirm_copy_move", False)
    panel = window.sides["left"].panel
    panel.navigate(str(zipped / "Urlaub"))
    assert panel.in_archive
    panel.select_names(["bild1.jpg", "Strand"], current="bild1.jpg")
    for aid in ("delete", "rename", "new_folder", "move"):
        window.trigger(aid)
    from PySide6.QtCore import Qt

    assert len(infos) == 4
    assert all(not panel.model.flags(panel.model.index(r, 0)) & Qt.ItemFlag.ItemIsEditable
               for r in range(panel.model.rowCount()))  # nur lesbar (L-3209)
    window.trigger("copy")  # F5 → entpacken ins andere Fenster (L-3208)
    qtbot.waitUntil(lambda: (tree / "b" / "Strand" / "bild2.jpg").exists() and not window.ops.is_busy(), timeout=5000)
    assert (tree / "b" / "bild1.jpg").read_bytes() == b"\xff\xd8bild1"
    assert not [n for n in os.listdir(tree / "b") if n.startswith(".panepilot")]
    # ins Archiv kopieren geht nicht
    window.set_active_side("right")
    window.sides["right"].panel.navigate(str(zipped))
    window.sides["right"].panel.select_names(["readme.txt"], current="readme.txt")
    window.set_active_side("left")
    panel.navigate(str(tree / "b"))
    panel.select_names(["bild1.jpg"], current="bild1.jpg")
    infos.clear()
    window.trigger("copy")
    assert infos and "Archiv" in infos[-1]


def test_open_file_in_archive(window, tree, zipped, monkeypatch):  # noqa: F811
    import panepilot.util as util

    opened = []
    monkeypatch.setattr(util, "open_with_default_app", lambda p: opened.append(p) or True)
    panel = window.sides["left"].panel
    panel.navigate(str(zipped))
    panel.select_names(["readme.txt"], current="readme.txt")
    panel.open_current()
    assert len(opened) == 1 and open(opened[0]).read() == "hallo" and opened[0].endswith("/readme.txt")


def test_archive_menu_and_button(window, tree, zipped, monkeypatch):  # noqa: F811
    from PySide6.QtWidgets import QMenu

    from panepilot import toolbar

    assert toolbar.clean_items(["back", "compress", "extract_here", "extract_to"]) == ["back", "archive"]
    avail = toolbar.available_actions()
    assert "archive" in avail and not {"compress", "extract_here", "extract_subfolder", "extract_to",
                                       "archive_open"} & set(avail)
    panel = window.sides["left"].panel
    panel.refresh()
    panel.select_names(["Fotos.zip"], current="Fotos.zip")
    menu = QMenu()
    window._fill_archive_menu(menu)
    texts = [(a.text(), a.isEnabled()) for a in menu.actions() if not a.isSeparator()]
    assert texts == [("Öffnen", True), ("Hier entpacken", True), ("Entpacken nach …", True),
                     ("Entpacken nach „Fotos“", True), ("Archiv erstellen …", True)]
    shown = []
    monkeypatch.setattr(window, "_exec_menu", lambda m, pos: shown.append(
        [(a.text(), [x.text() for x in a.menu().actions()] if a.menu() else None) for a in m.actions()]))
    window._file_context_menu("left", panel.view.viewport().mapToGlobal(QPoint(5, 5)))
    sub = dict((n, s) for n, s in shown[-1] if s)
    assert "Archiv" in sub and "Archiv erstellen …" in sub["Archiv"]
    assert "Komprimieren …" not in [n for n, _s in shown[-1]]
    window.trigger("archive")  # Klick auf den Knopf: markiertes Archiv öffnen (L-3201)
    assert panel.in_archive
    window._file_context_menu("left", panel.view.viewport().mapToGlobal(QPoint(5, 5)))
    names = [n for n, _s in shown[-1]]
    assert "Löschen" not in " ".join(names) and "Archiv" in names
    # ohne markiertes Archiv: „Archiv erstellen …“
    panel.navigate(str(tree / "a"))
    panel.select_names(["eins.txt"], current="eins.txt")
    called = []
    monkeypatch.setattr(window, "do_compress", lambda: called.append(1))
    window.trigger("archive")
    assert called == [1]


def test_drag_out_of_archive(window, tree, zipped, qtbot):  # noqa: F811
    from PySide6.QtCore import Qt

    panel = window.sides["left"].panel
    panel.navigate(str(zipped))
    md = panel.model.mimeData([panel.model.index(panel.model.row_of("readme.txt"), 0)])
    import json

    from panepilot.filemodel import REMOTE_MIME

    payload = json.loads(bytes(md.data(REMOTE_MIME)).decode())
    assert payload["archive"] and payload["side"] == "left"
    window.sides["right"].panel.remote_drop_requested.emit(payload, str(tree / "b"), Qt.DropAction.CopyAction)
    qtbot.waitUntil(lambda: (tree / "b" / "readme.txt").exists() and not window.ops.is_busy(), timeout=5000)
    assert panel.view._into_archive()


def test_tabs_restore_outside_archive(window, tree, zipped):  # noqa: F811
    panel = window.sides["left"].panel
    panel.navigate(str(zipped / "Urlaub"))
    state = panel.tabs_state()
    panel.navigate(str(tree))
    panel.restore_tabs(state)
    assert panel.current_path == str(tree / "a") and panel.current_entry().name == "Fotos.zip"
    QApplication.processEvents()


# --- Knopf „Reiter“ ---------------------------------------------------------------------------------------
def test_tabs_button(window, tree):  # noqa: F811
    from PySide6.QtWidgets import QMenu

    from panepilot import toolbar

    assert toolbar.clean_items(["tab_new", "tab_close", "back", "open_in_tab", "recent_dirs"]) == \
        ["tabs", "back", "recent_dirs"]
    assert "tabs" in toolbar.available_actions() and "tab_new" not in toolbar.available_actions()
    window.settings.set("tabs_always", False)
    panel = window.sides["left"].panel
    window.trigger("tabs")  # Klick: Reiterleiste immer anzeigen
    assert window.settings.get("tabs_always") and window.qactions["tabs"].isChecked()
    assert all(s.panel.tabs_always for s in window.sides.values()) and panel.tab_bar.isVisible()
    panel.select_names(["sub"], current="sub")
    menu = QMenu()
    window._fill_tabs_menu(menu)
    rows = [(a.text(), a.isEnabled(), a.isChecked()) for a in menu.actions() if not a.isSeparator()]
    assert [r[0] for r in rows] == ["In neuem Reiter öffnen", "Neuer Reiter", "Nächster Reiter",
                                    "Vorheriger Reiter", "Reiter schließen", "Reiter sperren"]
    assert rows[0][1] and not rows[2][1] and not rows[5][2]
    menu.actions()[0].trigger()
    assert panel.tab_bar.count() == 2 and panel.current_path == str(tree / "a" / "sub")
    window._fill_tabs_menu(menu)
    [a for a in menu.actions() if a.text() == "Reiter sperren"][0].trigger()
    window._fill_tabs_menu(menu)
    assert [a for a in menu.actions() if a.text() == "Reiter sperren"][0].isChecked()
    window.trigger("tabs")
    assert not window.settings.get("tabs_always") and not window.qactions["tabs"].isChecked()
    from panepilot.settingsdialog import SettingsDialog

    dlg = SettingsDialog(window)
    dlg.tabs_always.setChecked(True)
    dlg.accept()
    assert window.qactions["tabs"].isChecked()
