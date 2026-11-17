"""Tests for 1.10: panels one above the other; “Duplicate” in the context menu."""

import json
import os

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication

from test_mainwindow import window  # noqa: F401


# --- Fenster übereinander ---------------------------------------------------------------------
def test_stacked_layout_toggle_and_sizes(window):  # noqa: F811
    w = window
    assert not w.stacked and w.outer.orientation() == Qt.Orientation.Horizontal
    w.outer.setSizes([500, 36, 700])
    side_sizes = w.outer.sizes()
    w.trigger("toggle_stacked")
    QApplication.processEvents()
    assert w.stacked and w.outer.orientation() == Qt.Orientation.Vertical
    assert w.qactions["toggle_stacked"].isChecked()
    assert w.button_bar.stacked and w.button_bar.height() == 36  # waagerechte Knopfleiste (L-1002)
    # Seitenleisten bleiben links neben jedem Fenster (Variante A, L-1001)
    assert all(s.splitter.orientation() == Qt.Orientation.Horizontal for s in w.sides.values())
    assert w.sidebar_submenus["left"].title() == "Seitenleiste oben"
    assert w.sidebar_submenus["right"].title() == "Seitenleiste unten"
    top, _bar, bottom = w.outer.sizes()
    assert abs(top - bottom) <= 2  # Standard: gleich hoch
    w.outer.setSizes([top - 60, 36, bottom + 60])
    stacked_sizes = w.outer.sizes()
    w.trigger("toggle_stacked")
    QApplication.processEvents()
    assert not w.stacked and w.sidebar_submenus["left"].title() == "Seitenleiste links"
    assert w.outer.sizes() == side_sizes  # je Anordnung getrennt gemerkt (L-1004)
    w.trigger("toggle_stacked")
    QApplication.processEvents()
    assert w.outer.sizes() == stacked_sizes


def test_stacked_buttonbar_copies_to_other_panel(window, tree):  # noqa: F811
    w = window
    w.set_stacked(True)
    left = w.sides["left"].panel
    left.select_names(["eins.txt"], current="eins.txt")
    w.button_bar.buttons["copy_direct"].click()
    qt_wait = QApplication.processEvents
    for _ in range(200):
        qt_wait()
        if (tree / "b" / "eins.txt").exists() and not w.ops.is_busy():
            break
    assert (tree / "b" / "eins.txt").exists()


def test_stacked_single_mode_and_restart(window, monkeypatch, qtbot):  # noqa: F811
    from panepilot.mainwindow import MainWindow

    w = window
    w.set_stacked(True)
    w.trigger("toggle_single")
    assert w.single_mode and w.sidebar_submenus["left"].title() == "Seitenleiste"
    w.trigger("toggle_single")
    assert w.sidebar_submenus["left"].title() == "Seitenleiste oben"
    w.save_state()
    state = json.load(open(os.path.join(os.environ["PANEPILOT_CONFIG_DIR"], "Settings", "state.json")))
    assert state["stacked"] is True and "side_by_side" in state["layouts"]
    again = MainWindow()
    qtbot.addWidget(again)
    assert again.stacked and again.outer.orientation() == Qt.Orientation.Vertical  # gemerkt (L-1000)
    assert again.qactions["toggle_stacked"].isChecked()
    again.set_stacked(False)
    assert again.outer.orientation() == Qt.Orientation.Horizontal


def test_stacked_shortcut_default():
    from panepilot.actions import ACTION_DEFS

    defs = {d.id: d for d in ACTION_DEFS}
    assert defs["toggle_stacked"].keys == ("Ctrl+Shift+H",)
    assert defs["duplicate"].keys == ("Ctrl+D",)


# --- Duplizieren ------------------------------------------------------------------------------------
def test_duplicate_names(tmp_path):
    from panepilot.fileops import duplicate_name

    (tmp_path / "Bericht.docx").write_text("x")
    assert duplicate_name(str(tmp_path / "Bericht.docx")) == str(tmp_path / "Bericht-Kopie.docx")
    (tmp_path / "Bericht-Kopie.docx").write_text("x")
    assert duplicate_name(str(tmp_path / "Bericht.docx")) == str(tmp_path / "Bericht-Kopie-2.docx")
    (tmp_path / "Fotos").mkdir()
    assert duplicate_name(str(tmp_path / "Fotos")) == str(tmp_path / "Fotos-Kopie")
    (tmp_path / "paket.tar.gz").write_text("x")
    assert duplicate_name(str(tmp_path / "paket.tar.gz")) == str(tmp_path / "paket-Kopie.tar.gz")
    (tmp_path / ".bashrc").write_text("x")
    assert duplicate_name(str(tmp_path / ".bashrc")) == str(tmp_path / ".bashrc-Kopie")


def _wait(w, qtbot, cond):
    qtbot.waitUntil(lambda: cond() and not w.ops.is_busy(), timeout=5000)
    QApplication.processEvents()


def test_duplicate_files_and_folder(window, tree, qtbot):  # noqa: F811
    w = window
    panel = w.sides["left"].panel
    a = tree / "a"
    panel.select_names(["eins.txt", "sub"], current="eins.txt")
    w.trigger("duplicate")
    _wait(w, qtbot, lambda: (a / "eins-Kopie.txt").exists() and (a / "sub-Kopie").is_dir())
    assert (a / "eins-Kopie.txt").read_bytes() == (a / "eins.txt").read_bytes()
    assert sorted(os.listdir(a / "sub-Kopie")) == sorted(os.listdir(a / "sub"))
    assert {e.name for e in panel.selected_entries()} == {"eins-Kopie.txt", "sub-Kopie"}  # Kopien markiert (L-1012)
    panel.select_names(["eins.txt"], current="eins.txt")
    w.trigger("duplicate")
    _wait(w, qtbot, lambda: (a / "eins-Kopie-2.txt").exists())


def test_duplicate_in_context_menu(window, tree):  # noqa: F811
    w = window
    panel = w.sides["left"].panel
    panel.select_names(["eins.txt"], current="eins.txt")
    seen = []

    def grab():
        menu = QApplication.activePopupWidget()
        if menu is not None:
            seen.append([x.text().replace("&", "") for x in menu.actions()])
            menu.close()

    QTimer.singleShot(200, grab)
    w._file_context_menu("left", QPoint(0, 0))
    assert seen and "Duplizieren" in seen[0]
    texts = seen[0]
    assert texts.index("Duplizieren") == texts.index("Umbenennen") + 1


def test_duplicate_blocked_on_server():
    from panepilot.remotecontrol import REMOTE_BLOCKED

    assert "duplicate" in REMOTE_BLOCKED
