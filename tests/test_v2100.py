"""Tests for 2.1: tabs per panel and recently visited folders."""

import json
import os

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from test_mainwindow import press, window  # noqa: F401


def _names(panel):
    return [panel.tab_bar.tabText(i) for i in range(panel.tab_bar.count())]


def test_new_switch_close(window, tree, qtbot):  # noqa: F811
    w = window
    panel = w.active
    panel.navigate(str(tree / "a"))
    assert panel.tab_bar.count() == 1 and not panel.tab_bar.isVisible()  # nur ein Reiter: Leiste unsichtbar
    w.trigger("tab_new")
    QApplication.processEvents()
    assert panel.tab_bar.count() == 2 and panel.tab_bar.isVisible() and panel.tab_bar.currentIndex() == 1
    assert panel.current_path == str(tree / "a")
    panel.navigate(str(tree / "b"))
    assert _names(panel) == ["a", "b"]
    assert panel.tab_bar.tabToolTip(1) == str(tree / "b")
    # eigener Verlauf je Reiter
    assert panel.history_state()[0] == [str(tree / "a"), str(tree / "b")]
    w.trigger("tab_prev")
    assert panel.current_path == str(tree / "a") and panel.tab_bar.currentIndex() == 0
    w.trigger("tab_next")
    assert panel.current_path == str(tree / "b")
    w.trigger("tab_next")  # rundum
    assert panel.tab_bar.currentIndex() == 0
    # Sortierung und Ansicht gehören zum Reiter
    panel.set_sort_state(1, int(Qt.SortOrder.DescendingOrder.value))
    w.trigger("tab_next")
    assert panel.sort_state()[0] == 0
    w.trigger("tab_prev")
    assert panel.sort_state() == (1, int(Qt.SortOrder.DescendingOrder.value))
    # Strg+W schließt, der letzte bleibt
    w.trigger("tab_close")
    assert panel.tab_bar.count() == 1 and panel.current_path == str(tree / "b")
    w.trigger("tab_close")
    assert panel.tab_bar.count() == 1
    assert not panel.tab_bar.isVisible()
    # Tastenkürzel
    assert w.qactions["tab_new"].shortcut().toString() == "Ctrl+T"
    assert w.qactions["meta_wizard"].shortcut().toString() == "Ctrl+Shift+T"
    assert w.qactions["tab_close"].shortcut().toString() == "Ctrl+W"
    assert w.qactions["recent_dirs"].shortcut().toString() == "Alt+Down"


def test_locked_tab_opens_new_tab(window, tree):  # noqa: F811
    panel = window.active
    panel.navigate(str(tree / "a"))
    panel.toggle_tab_lock()
    assert _names(panel) == ["🔒 a"]
    panel.navigate(str(tree / "b"))  # gesperrt: neuer Reiter
    assert panel.tab_bar.count() == 2 and panel.tab_bar.currentIndex() == 1 and panel.current_path == str(tree / "b")
    assert panel.tab_bar.tabData(0).path == str(tree / "a")
    panel.tab_bar.setCurrentIndex(0)
    assert panel.current_path == str(tree / "a")
    panel.go_up()  # auch „nach oben“ öffnet einen neuen Reiter
    assert panel.tab_bar.count() == 3 and panel.tab_bar.tabData(0).path == str(tree / "a")
    panel.tab_bar.setCurrentIndex(0)
    panel.refresh()  # neu einlesen bleibt im Reiter
    assert panel.tab_bar.count() == 3
    panel.toggle_tab_lock(0)
    assert _names(panel)[0] == "a"


def test_middle_click_and_ctrl_double_click(window, tree, qtbot):  # noqa: F811
    panel = window.active
    panel.navigate(str(tree))
    row = panel.model.row_of("a")
    rect = panel.view.visualRect(panel.model.index(row, panel.model.icon_column))
    qtbot.mouseClick(panel.view.viewport(), Qt.MouseButton.MiddleButton, pos=rect.center())
    assert panel.tab_bar.count() == 2 and panel.current_path == str(tree / "a")
    panel.tab_bar.setCurrentIndex(0)
    row = panel.model.row_of("b")
    rect = panel.view.visualRect(panel.model.index(row, panel.model.icon_column))
    qtbot.mouseClick(panel.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                     pos=rect.center())
    qtbot.mouseDClick(panel.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                      pos=rect.center())
    assert panel.tab_bar.count() == 3 and panel.current_path == str(tree / "b")
    # Doppelklick auf die freie Reiterleiste: neuer Reiter
    bar = panel.tab_bar
    free = QPoint(bar.width() - 5, bar.height() // 2)
    assert bar.tabAt(free) < 0
    qtbot.mouseDClick(bar, Qt.MouseButton.LeftButton, pos=free)
    assert bar.count() == 4
    # mittlere Maustaste auf einen Reiter schließt ihn
    qtbot.mouseClick(bar, Qt.MouseButton.MiddleButton, pos=bar.tabRect(0).center())
    assert bar.count() == 3


def test_tab_menu_and_other_panel(window, tree, monkeypatch):  # noqa: F811
    w = window
    panel = w.sides["left"].panel
    w.set_active_side("left")
    panel.navigate(str(tree / "a"))
    panel.new_tab(str(tree / "b"))
    shown = []
    monkeypatch.setattr(w, "_exec_menu", lambda menu, pos: shown.append([x.text() for x in menu.actions()]))
    w._tab_menu("left", 1, QPoint(0, 0))
    assert shown[-1] == ["Neuer Reiter", "Reiter schließen", "Andere Reiter schließen", "", "Reiter sperren",
                         "Im anderen Fenster öffnen"]
    w.do_tab_to_other(1, "left")
    right = w.sides["right"].panel
    assert right.tab_bar.count() == 2 and right.current_path == str(tree / "b") and w.active_side == "right"
    panel.close_other_tabs(1)
    assert panel.tab_bar.count() == 1 and panel.current_path == str(tree / "b")


def test_tools_block_tabs(window, tree):  # noqa: F811
    w = window
    panel = w.active
    panel.navigate(str(tree))
    panel.new_tab()
    w.trigger("search")
    panel.show_search_results(str(tree))
    QApplication.processEvents()
    assert not panel.tab_bar.isEnabled()
    assert panel.new_tab() == -1 and not panel.close_tab()
    panel.tab_bar.setCurrentIndex(0)
    assert panel.tab_bar.currentIndex() == 1  # Wechsel wird zurückgenommen
    w.close_tool(w.active_side)
    panel.navigate(str(tree / "a"))
    QApplication.processEvents()
    assert panel.tab_bar.isEnabled()
    panel.locked = True  # Mehrfach umbenennen
    assert not panel.tab_bar.isEnabled()
    panel.locked = False


def test_tabs_always_and_restart(window, tree, qtbot):  # noqa: F811
    from panepilot.mainwindow import MainWindow

    w = window
    panel = w.sides["left"].panel
    w.set_active_side("left")
    panel.set_tabs_always(True)
    panel.navigate(str(tree / "a"))
    QApplication.processEvents()
    assert panel.tab_bar.isVisible() and panel.tab_bar.count() == 1
    panel.set_tabs_always(False)
    assert not panel.tab_bar.isVisible()
    panel.new_tab(str(tree / "b"))
    panel.set_icon_mode(True)
    panel.toggle_tab_lock()
    panel.tab_bar.setCurrentIndex(0)
    w.save_state()
    state = json.load(open(os.path.join(os.environ["PANEPILOT_CONFIG_DIR"], "Settings", "state.json")))
    tabs = state["sides"]["left"]["tabs"]
    assert [t["path"] for t in tabs["tabs"]] == [str(tree / "a"), str(tree / "b")] and tabs["current"] == 0
    assert tabs["tabs"][1]["locked"] is True and tabs["tabs"][1]["icon_view"] is True
    again = MainWindow()
    qtbot.addWidget(again)
    p2 = again.sides["left"].panel
    assert p2.tab_bar.count() == 2 and p2.current_path == str(tree / "a") and not p2.icon_mode
    p2.tab_bar.setCurrentIndex(1)
    assert p2.current_path == str(tree / "b") and p2.icon_mode and p2.tab_bar.tabText(1) == "🔒 b"


def test_tab_state_roundtrip():
    from panepilot.filters import FilterSpec
    from panepilot.paneltabs import TabState, tab_title

    st = TabState("/x/y", ["/x", "/x/y"], 1, (2, 1), FilterSpec("*.jpg"), True, True, 256, True)
    back = TabState.from_dict(st.to_dict())
    assert back == st
    assert TabState.from_dict({"path": ""}) is None and TabState.from_dict("x") is None
    assert tab_title("/") == "/" and tab_title("/home/alice/") == "alice"
    assert tab_title("sftp://nas/home/alice") == "alice"
    new = st.copy_for("/z")
    assert new.history == ["/z"] and not new.locked and new.filter_spec == st.filter_spec


# --- Verlauf (L-3108) -----------------------------------------------------------------------------------------
def test_recent_dirs(window, tree, monkeypatch, qtbot):  # noqa: F811
    from panepilot.mainwindow import MainWindow

    w = window
    panel = w.active
    for sub in ("a", "b", "a"):
        panel.navigate(str(tree / sub))
    assert w.recent_dirs[:2] == [str(tree / "a"), str(tree / "b")]  # neueste oben, ohne Doppelte
    for i in range(30):
        d = tree / f"x{i}"
        d.mkdir()
        w._remember_recent(str(d))
    assert len(w.recent_dirs) == 20
    w._remember_recent("sftp://nas/x")  # Server und Papierkorb nicht
    assert w.recent_dirs[0] == str(tree / "x29")
    shown = []
    monkeypatch.setattr(w, "_exec_menu", lambda menu, pos: shown.append(menu))
    panel.navigate(str(tree / "a"))
    w.trigger("recent_dirs")
    menu = shown[-1]
    texts = [a.text() for a in menu.actions()]
    assert str(tree / "a") not in texts and texts[0] == str(tree / "x29")
    menu.actions()[1].trigger()
    assert panel.current_path == str(tree / "x28")
    # Pfeil in der Pfadzeile
    arrows = [a for a in panel.path_edit.actions() if a.toolTip() == "Zuletzt besuchte Ordner …"]
    assert arrows
    w.save_state()
    again = MainWindow()
    qtbot.addWidget(again)
    assert again.recent_dirs[:2] == w.recent_dirs[:2]


def test_tab_keys(window, tree, qtbot):  # noqa: F811
    w = window
    panel = w.active
    panel.navigate(str(tree / "a"))
    panel.focus_view()
    press(qtbot, w, Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier)
    assert panel.tab_bar.count() == 2
    press(qtbot, w, Qt.Key.Key_Tab, Qt.KeyboardModifier.ControlModifier)
    assert panel.tab_bar.currentIndex() == 0 and w.active is panel  # Strg+Tab wechselt den Reiter, nicht das Fenster
    press(qtbot, w, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
    assert panel.tab_bar.count() == 1
