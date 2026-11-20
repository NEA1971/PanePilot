"""Tests for 1.21: shared sidebar for both panels (variant B)."""

import json
import os

from PySide6.QtWidgets import QApplication

from test_mainwindow import window  # noqa: F401


def _shown(w):
    return [n for n, s in w.sides.items() if s.sidebar.isVisible()]


def test_shared_sidebar_follows_active(window, tmp_path):  # noqa: F811
    from panepilot.sidebars import MODE_FAVORITES, MODE_TREE

    w = window
    w.set_sidebar_mode("left", MODE_TREE)
    w.set_sidebar_mode("right", MODE_FAVORITES)
    w.set_active_side("left")
    w.trigger("toggle_shared_sidebar")
    QApplication.processEvents()
    assert w.shared_sidebar and w.qactions["toggle_shared_sidebar"].isChecked()
    assert w.shared_box.isVisible() and _shown(w) == ["left"]
    assert w.sides["left"].sidebar.parent() is w.shared_box  # ganz links, nicht mehr im Fenster
    assert w.sides["right"].sidebar.mode == MODE_TREE  # gleiche Ansicht für beide (L-2102)
    # nur ein Menüeintrag „Seitenleiste“ (L-2105)
    assert w.sidebar_submenus["left"].title() == "Seitenleiste"
    assert not w.sidebar_submenus["right"].menuAction().isVisible()
    # Klick ins rechte Fenster: die Leiste gehört jetzt zum rechten
    right = w.sides["right"].panel
    right.navigate(str(tmp_path))
    right.focus_view()
    QApplication.processEvents()
    assert w.active_side == "right" and _shown(w) == ["right"]
    tree = w.tree_view("right")
    assert tree is not None and tree.isVisible()
    # Menü wählt für die gezeigte Leiste
    w.sidebar_menus["left"][MODE_FAVORITES].trigger()
    assert w.sides["right"].sidebar.mode == MODE_FAVORITES and w.shared_box.isVisible()
    w.set_active_side("left")
    assert w.sides["left"].sidebar.mode == MODE_FAVORITES and _shown(w) == ["left"]
    # Alt+F: aus und wieder an
    w.trigger("toggle_sidebar")
    QApplication.processEvents()
    assert not w.shared_box.isVisible()
    w.set_active_side("right")
    assert not w.shared_box.isVisible()  # „aus“ gilt auch für das andere Fenster
    w.trigger("toggle_sidebar")
    assert w.shared_box.isVisible()
    # aus: wieder zwei Leisten wie vorher (Variante A)
    w.trigger("toggle_shared_sidebar")
    QApplication.processEvents()
    assert not w.shared_sidebar and not w.shared_box.isVisible()
    assert w.sides["left"].sidebar.parent() is w.sides["left"].splitter
    assert w.sides["right"].sidebar.parent() is w.sides["right"].splitter
    assert w.sidebar_submenus["right"].menuAction().isVisible()
    assert w.sidebar_submenus["left"].title() == "Seitenleiste links"


def test_tool_stays_with_its_panel(window):  # noqa: F811
    from panepilot.mainwindow import MODE_SEARCH
    from panepilot.sidebars import MODE_TREE

    w = window
    w.set_sidebar_mode("left", MODE_TREE)
    w.set_shared_sidebar(True)
    w.set_active_side("left")
    w.trigger("search")
    QApplication.processEvents()
    assert w.sides["left"].sidebar.mode == MODE_SEARCH and _shown(w) == ["left"]
    assert w.main_split.sizes()[0] >= 360
    w.set_active_side("right")
    assert _shown(w) == ["left"]  # Suche bleibt beim linken Fenster (L-2103)
    w.close_tool("left")
    QApplication.processEvents()
    assert w.sides["left"].sidebar.mode == MODE_TREE
    w.set_active_side("right")
    assert _shown(w) == ["right"] and w.sides["right"].sidebar.mode == MODE_TREE


def test_shared_sidebar_stacked_and_restart(window, qtbot):  # noqa: F811
    from panepilot.mainwindow import MainWindow
    from panepilot.sidebars import MODE_TREE

    w = window
    w.set_sidebar_mode("left", MODE_TREE)
    w.set_shared_sidebar(True)
    w.main_split.setSizes([300, 980])
    QApplication.processEvents()
    side_by_side = w.main_split.sizes()
    w.set_stacked(True)
    QApplication.processEvents()
    assert w.shared_box.isVisible() and w.sidebar_submenus["left"].title() == "Seitenleiste"
    assert w.main_split.width() > 1000  # Fenster nutzen die volle Breite
    w.main_split.setSizes([250, 1030])
    QApplication.processEvents()
    stacked = w.main_split.sizes()
    w.set_stacked(False)
    QApplication.processEvents()
    assert w.main_split.sizes() == side_by_side  # Breite je Anordnung (L-2106)
    w.set_stacked(True)
    QApplication.processEvents()
    assert w.main_split.sizes() == stacked
    w.save_state()
    state = json.load(open(os.path.join(os.environ["PANEPILOT_CONFIG_DIR"], "Settings", "state.json")))
    assert state["shared_sidebar"] is True
    again = MainWindow()
    qtbot.addWidget(again)
    again.resize(1280, 780)
    again.show()
    QApplication.processEvents()
    assert again.shared_sidebar and again.stacked and again.shared_box.isVisible()
    assert again.qactions["toggle_shared_sidebar"].isChecked()


def test_shared_sidebar_single_mode(window):  # noqa: F811
    from panepilot.sidebars import MODE_TREE

    w = window
    w.set_sidebar_mode("left", MODE_TREE)
    w.set_shared_sidebar(True)
    w.trigger("toggle_single")
    QApplication.processEvents()
    assert w.shared_box.isVisible() and w.sidebar_submenus["left"].title() == "Seitenleiste"
    w.trigger("toggle_single")
    w.set_shared_sidebar(False)
    assert w.sides["left"].sidebar.isVisible()
