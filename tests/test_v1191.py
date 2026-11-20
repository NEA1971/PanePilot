"""Tests for 1.19.1: the “..” row stays a small row above the icons."""

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from test_mainwindow import press, window  # noqa: F401


def test_parent_row_above_icons(window, qtbot, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    panel = window.active
    window.trigger("toggle_icon_view")
    QApplication.processEvents()
    bar, icons = panel.parent_bar, panel.icon_view
    assert bar.isVisible() and icons.isRowHidden(0) and not icons.isRowHidden(1)
    assert [r for r in range(panel.model.rowCount()) if not bar.isRowHidden(r)] == [0]
    h = bar.height()
    for size in ("icons_large", "icons_small"):  # Zeile wird nicht mitskaliert
        window.trigger(size)
        QApplication.processEvents()
        assert bar.height() == h
    # Cursor auf „..“: Fokus in der Zeile; Pfeil runter → erstes Symbol, Pfeil hoch → zurück
    panel.select_names([], current="..")
    panel.focus_view()
    assert QApplication.focusWidget() is bar
    press(qtbot, window, Qt.Key.Key_Down)
    assert QApplication.focusWidget() is icons and panel.current_entry().name == "sub"
    press(qtbot, window, Qt.Key.Key_Up)
    assert QApplication.focusWidget() is bar and panel.current_entry().is_parent
    # Eingabetaste auf „..“ geht nach oben
    start = panel.current_path
    press(qtbot, window, Qt.Key.Key_Return)
    assert panel.current_path == os.path.dirname(start)
    # Doppelklick auf die Zeile ebenso
    panel.navigate(start)
    QApplication.processEvents()
    bar.doItemsLayout()
    rect = bar.visualRect(panel.model.index(0, bar.modelColumn()))
    assert rect.isValid(), rect
    qtbot.mouseClick(bar.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    qtbot.mouseDClick(bar.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
    assert panel.current_path == os.path.dirname(start)
    # ohne „..“ (Papierkorb, Suche, Wurzel) keine Zeile
    panel.navigate("/")
    QApplication.processEvents()
    assert not bar.isVisible() and not icons.isRowHidden(0)
    # zurück zur Liste: alles wie vorher
    window.trigger("toggle_icon_view")
    assert panel.view.isVisible() and not panel.icon_box.isVisible()
