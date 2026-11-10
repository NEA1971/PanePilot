import os

from PySide6.QtCore import QFile, Qt
from PySide6.QtWidgets import QApplication

from panepilot.fileops import PURGE, RESTORE, ConflictDecision, OperationEngine
from panepilot.trash import Trash, home_trash


def trash_file(path):
    res = QFile.moveToTrash(str(path))
    assert res if isinstance(res, bool) else res[0]


def test_items_restore_and_purge(qapp, tree):
    trash_file(tree / "a" / "eins.txt")
    trash_file(tree / "b")
    items = {i.name: i for i in Trash().items()}
    assert set(items) == {"eins.txt", "b"}
    assert items["eins.txt"].original_path == str(tree / "a" / "eins.txt")
    assert items["b"].is_dir and items["eins.txt"].deleted > 0
    it = items["eins.txt"]
    res = OperationEngine(RESTORE, [it.file_path], trash_info={it.file_path: (it.original_path, it.info_path)}).run()
    assert not res.errors and (tree / "a" / "eins.txt").read_text() == "eins"
    assert not os.path.exists(it.info_path)
    b = items["b"]
    OperationEngine(PURGE, [b.file_path], trash_info={b.file_path: (b.original_path, b.info_path)}).run()
    assert Trash().is_empty()


def test_restore_conflict_asks(qapp, tree):
    trash_file(tree / "a" / "eins.txt")
    (tree / "a" / "eins.txt").write_text("neu")
    it = Trash().items()[0]
    asked = []
    eng = OperationEngine(RESTORE, [it.file_path], trash_info={it.file_path: (it.original_path, it.info_path)},
                          ask_conflict=lambda *a: asked.append(a) or ConflictDecision("rename", "eins_alt.txt"))
    eng.run()
    assert asked and (tree / "a" / "eins_alt.txt").read_text() == "eins"


def test_topdir_trash_found(qapp, tmp_path):
    top = tmp_path / "usb"
    td = top / f".Trash-{os.getuid()}"
    (td / "files").mkdir(parents=True)
    (td / "info").mkdir()
    (td / "files" / "foto.jpg").write_text("x")
    (td / "info" / "foto.jpg.trashinfo").write_text("[Trash Info]\nPath=Bilder/foto.jpg\nDeletionDate=2026-11-04T10:00:00\n")
    items = Trash(lambda: [str(top)]).items()
    assert [i.original_path for i in items] == [str(top / "Bilder" / "foto.jpg")]


def test_trash_panel_view_and_actions(qtbot, tree, monkeypatch):
    from panepilot.app import create_app

    create_app([])
    from panepilot.mainwindow import MainWindow
    import panepilot.mainwindow as mw

    trash_file(tree / "a" / "eins.txt")
    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    panel = w.sides["left"].panel
    w.set_active_side("left")
    w.do_open_trash()
    assert panel.in_trash and panel.path_edit.text() == "Papierkorb"
    names = [e.name for e in panel.model.entries()]
    assert names == ["eins.txt"]
    assert panel.model.headerData(3, Qt.Orientation.Horizontal) == "Ursprünglicher Ort"
    # gesperrt im Papierkorb
    w.trigger("new_folder")
    assert not os.path.exists(os.path.join(home_trash(), "files", "Neuer Ordner"))
    panel.select_names(["eins.txt"], current="eins.txt")
    with qtbot.waitSignal(w.ops.finished, timeout=5000):
        w.trigger("trash_restore")
    assert (tree / "a" / "eins.txt").exists()
    assert panel.model.entries() == []
    # Leeren mit Rückfrage
    trash_file(tree / "b")
    monkeypatch.setattr(mw, "confirm", lambda *a, **k: True)
    with qtbot.waitSignal(w.ops.finished, timeout=5000):
        w.trigger("trash_empty")
    assert Trash().is_empty()
    w.update_trash_state()
    assert w.button_bar.trash_full is False


def test_purge_question_mentions_restore_not_trash(qtbot, tree, monkeypatch):
    from panepilot.app import create_app

    create_app([])
    import panepilot.mainwindow as mw

    trash_file(tree / "a" / "eins.txt")
    w = mw.MainWindow()
    qtbot.addWidget(w)
    texts = []
    monkeypatch.setattr(mw, "confirm", lambda parent, title, text, **k: texts.append(text) or False)
    w.set_active_side("left")
    w.do_open_trash()
    w.sides["left"].panel.select_names(["eins.txt"], current="eins.txt")
    w.trigger("trash_purge")
    assert "Der Eintrag wird" in texts[0] and "nicht mehr wiederhergestellt" in texts[0]
    assert "NICHT im Papierkorb" not in texts[0]


def test_network_share_trash_is_listed_only_on_demand(qapp, tmp_path):
    """Fehler 0.5.1: Papierkorb auf einer Netzfreigabe (.Trash-<uid>) wurde nicht angezeigt."""
    share = tmp_path / "nas" / "Dokumente"
    trash_dir = share / f".Trash-{os.getuid()}"
    (trash_dir / "files").mkdir(parents=True)
    (trash_dir / "info").mkdir()
    (trash_dir / "files" / "alt.zip").write_text("x")
    (trash_dir / "info" / "alt.zip.trashinfo").write_text(
        "[Trash Info]\nPath=TEMP/alt.zip\nDeletionDate=2026-11-05T08:50:03\n")
    trash = Trash(lambda: [], lambda: [str(share)])
    assert trash.is_empty(network=False)  # regelmäßige Abfrage ohne Netz
    assert not trash.is_empty(network=True, local=False)
    items = trash.items()
    assert [i.name for i in items] == ["alt.zip"]
    assert items[0].original_path == str(share / "TEMP" / "alt.zip")
    res = OperationEngine(RESTORE, [items[0].file_path],
                          trash_info={items[0].file_path: (items[0].original_path, items[0].info_path)}).run()
    assert not res.errors and (share / "TEMP" / "alt.zip").exists()
    assert trash.is_empty()
