"""v3.3: Favoriten-Menü per Tastenkürzel (Alt+↑, Diskussion #3)."""

from PySide6.QtGui import QKeySequence


def test_fav_popup_action_and_key(qapp):  # L-4300
    from panepilot.mainwindow import MainWindow

    w = MainWindow()
    try:
        act = w.qactions["fav_popup"]
        assert QKeySequence("Alt+Up") in act.shortcuts()
        menus = [a for m in w.menuBar().actions() for a in m.menu().actions()]
        assert act in menus
    finally:
        w._skip_save_state = True
        w.close()


def test_fav_popup_menu_structure(qapp, tmp_path, monkeypatch):  # L-4300
    from panepilot.favorites import SEPARATOR, FavNode
    from panepilot.mainwindow import MainWindow

    (tmp_path / "ordner").mkdir()
    (tmp_path / "datei.txt").write_text("x")
    w = MainWindow()
    try:
        m = w.fav_model
        m.load_dict({"version": 1, "items": []})
        g = m.add_group("Gruppe & Co")
        m.add_link(str(tmp_path / "ordner"), g, name="Ordner")
        m.add_group("leer")
        sep = FavNode(SEPARATOR, "")
        sep.parent = m.root
        m.root.children.append(sep)
        m.add_link(str(tmp_path / "datei.txt"), name="Datei")
        shown = []
        monkeypatch.setattr(w, "_exec_menu", lambda menu, pos: shown.append(menu))
        w.do_fav_popup()
        menu = shown[0]
        acts = menu.actions()
        assert [a.text() for a in acts] == ["Gruppe && Co", "leer", "", "Datei"]
        assert acts[2].isSeparator()
        sub = acts[0].menu()
        assert [a.text() for a in sub.actions()] == ["Ordner"]
        opened = []
        monkeypatch.setattr(w, "_open_file", lambda p: opened.append(p))
        sub.actions()[0].trigger()
        assert w.sides[w.active_side].panel.current_path == str(tmp_path / "ordner")
        acts[3].trigger()
        assert opened == [str(tmp_path / "datei.txt")]
        assert not acts[1].menu().actions()[0].isEnabled()  # leerer Ordner
    finally:
        w._skip_save_state = True
        w.close()


def test_fav_popup_empty_set(qapp, monkeypatch):
    from panepilot.mainwindow import MainWindow

    w = MainWindow()
    try:
        w.fav_model.load_dict({"version": 1, "items": []})
        shown = []
        monkeypatch.setattr(w, "_exec_menu", lambda menu, pos: shown.append(menu))
        w.do_fav_popup()
        acts = shown[0].actions()
        assert len(acts) == 1 and not acts[0].isEnabled()
    finally:
        w._skip_save_state = True
        w.close()
