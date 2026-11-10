import os
from pathlib import Path

from panepilot.foldertree import FolderTreeView, PathRole
from panepilot.icons import IconProvider


def test_tree_follows_path_and_lists_only_folders(qtbot, tree, monkeypatch):
    monkeypatch.setenv("HOME", str(tree.parent))
    view = FolderTreeView(IconProvider(), None)
    qtbot.addWidget(view)
    view.reload()
    view.select_path(str(tree / "a" / "sub"))
    cur = view.currentIndex()
    assert view.path_of(cur) == str(tree / "a" / "sub")
    a_item = view.tree_model.itemFromIndex(cur.parent())
    names = [a_item.child(r).text() for r in range(a_item.rowCount())]
    assert names == ["sub"]  # keine Dateien, keine versteckten Ordner


def test_tree_click_emits_open(qtbot, tree, monkeypatch):
    monkeypatch.setenv("HOME", str(tree.parent))
    view = FolderTreeView(IconProvider(), None)
    qtbot.addWidget(view)
    view.reload()
    view.select_path(str(tree / "b"))
    with qtbot.waitSignal(view.open_path) as sig:
        view.activate_current()
    assert sig.args == [str(tree / "b")]


def test_hidden_folders_follow_setting(qtbot, tree, monkeypatch):
    monkeypatch.setenv("HOME", str(tree.parent))
    (tree / ".geheim").mkdir()
    view = FolderTreeView(IconProvider(), None)
    qtbot.addWidget(view)
    view.reload(show_hidden=True)
    view.select_path(str(tree / ".geheim"))
    assert view.current_path() == str(tree / ".geheim")
