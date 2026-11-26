"""v3.2: Erscheinungsbild Hell/Dunkel, Schrift, Dateilisten, Favoriten sortieren."""

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def _restore_light():
    from panepilot import theme

    theme.apply("light")


def test_theme_light_and_dark(qapp):  # L-4200–L-4203
    from panepilot import theme

    try:
        theme.apply("dark")
        assert theme.is_dark() and QApplication.style().name().lower() == "fusion"
        pal = QApplication.palette()
        assert pal.color(QPalette.ColorRole.Window).lightness() < 70
        assert pal.color(QPalette.ColorRole.Text).lightness() > 200
        assert pal.color(QPalette.ColorRole.Highlight) == theme.accent()
        theme.apply("light")
        assert not theme.is_dark()
        assert QApplication.palette().color(QPalette.ColorRole.Window).lightness() > 200
        assert QApplication.palette().color(QPalette.ColorRole.Window) != QColor("#FFFFFF")  # nicht reinweiß
        assert QApplication.palette().color(QPalette.ColorRole.Highlight) == theme.accent()
    finally:
        _restore_light()


def test_readable_favorite_colors(qapp):  # L-4204
    from panepilot import theme

    try:
        theme.apply("dark")
        black = theme.readable(QColor("#000000"))
        assert black.lightness() > 150
        yellow = QColor("#F5C211")
        assert theme.readable(yellow) == yellow
        theme.apply("light")
        assert theme.readable(QColor("#000000")) == QColor("#000000")
    finally:
        _restore_light()


def test_font_default_and_custom(qapp):  # L-4210/L-4211
    from panepilot import theme

    fam, size = theme.default_font()
    theme.apply_font("", 0)
    assert QApplication.font().pointSizeF() == size
    theme.apply_font("", 14)
    assert QApplication.font().pointSizeF() == 14
    theme.apply_font("", 0)
    assert QApplication.font().pointSizeF() == size and fam


def test_settings_appearance(qapp, monkeypatch):  # L-4200/L-4210/L-4220/L-4221/L-4233
    from panepilot import theme
    from panepilot.filepanel import FileView
    from panepilot.mainwindow import MainWindow
    from panepilot.settingsdialog import SettingsDialog

    monkeypatch.setattr("panepilot.settingsdialog.confirm", lambda *a, **k: False)
    w = MainWindow()
    try:
        assert w.settings.get("theme") == "system" and w.settings.get("grid_lines") is True
        assert w.settings.get("alt_rows") is False and w.settings.get("fav_sort_order") == "folders_first"
        dlg = SettingsDialog(w)
        dlg.theme_choice["dark"].setChecked(True)
        dlg.font_size.setValue(13)
        dlg.alt_rows.setChecked(True)
        dlg.grid_lines.setChecked(False)
        dlg.fav_sort_choice["mixed"].setChecked(True)
        dlg.accept()
        assert w.settings.get("theme") == "dark" and theme.is_dark()
        assert w.settings.get("font_size") == 13 and QApplication.font().pointSizeF() == 13
        assert w.settings.get("fav_sort_order") == "mixed"
        assert FileView.alt_rows and not FileView.grid_lines
        assert w.sides["left"].panel.view.alternatingRowColors()
        dlg = SettingsDialog(w)
        dlg.font_family.setCurrentIndex(max(0, dlg.font_family.count() - 1))
        dlg.font_default.click()  # „Standard“
        dlg.theme_choice["light"].setChecked(True)
        dlg.accept()
        assert w.settings.get("font_size") == 0 and w.settings.get("font_family") == ""
        assert not theme.is_dark()
    finally:
        w.settings.set("alt_rows", False)
        w.settings.set("grid_lines", True)
        FileView.alt_rows, FileView.grid_lines = False, True
        _restore_light()
        theme.apply_font("", 0)
        w._skip_save_state = True
        w.close()


def test_grid_lines_paint(qapp, tmp_path):  # L-4221
    from panepilot.filepanel import FileView
    from panepilot.mainwindow import MainWindow

    (tmp_path / "a.txt").write_text("x")
    w = MainWindow()
    try:
        w.resize(1000, 600)
        w.show()
        panel = w.sides["left"].panel
        panel.navigate(str(tmp_path))
        qapp.processEvents()
        FileView.grid_lines = True
        img = panel.view.viewport().grab().toImage()
        header = panel.view.header()
        x = header.sectionViewportPosition(header.logicalIndex(0)) + header.sectionSize(header.logicalIndex(0)) - 1
        y = img.height() - 5  # unterhalb der Einträge: Linie geht durch die ganze Liste
        base = panel.view.palette().color(QPalette.ColorRole.Base)
        assert img.pixelColor(x, y) != base
        FileView.grid_lines = False
        img = panel.view.viewport().grab().toImage()
        assert img.pixelColor(x, y) == base
    finally:
        FileView.grid_lines = True
        w._skip_save_state = True
        w.close()


def _tree():
    from panepilot.favorites import FavNode, SEPARATOR

    root = FavNode("group", "", node_id="root")

    def add(parent, kind, name):
        n = FavNode(kind, name, path="/x/" + name if kind == "link" else "")
        n.parent = parent
        parent.children.append(n)
        return n

    add(root, "link", "zeta")
    g = add(root, "group", "Beta")
    add(g, "link", "item10")
    add(g, "link", "Item2")
    sub = add(g, "group", "unter")
    add(sub, "link", "b")
    add(sub, "link", "A")
    add(root, "link", "Alpha")
    add(root, SEPARATOR, "")
    add(root, "link", "y")
    add(root, "group", "X-Ordner")
    return root, g, sub


def test_sort_tree_sections_and_orders():  # L-4230–L-4233
    from panepilot.favorites import sort_tree

    root, g, sub = _tree()
    sort_tree(root, "folders_first")
    assert [n.name for n in root.children] == ["Beta", "Alpha", "zeta", "", "X-Ordner", "y"]
    assert [n.name for n in g.children] == ["unter", "Item2", "item10"]  # natürlich, ohne Groß/klein
    assert [n.name for n in sub.children] == ["A", "b"]
    root, g, sub = _tree()
    sort_tree(root, "links_first")
    assert [n.name for n in root.children] == ["Alpha", "zeta", "Beta", "", "y", "X-Ordner"]
    root, g, sub = _tree()
    sort_tree(root, "mixed")
    assert [n.name for n in root.children] == ["Alpha", "Beta", "zeta", "", "X-Ordner", "y"]
    root, g, sub = _tree()
    sort_tree(g, "folders_first")  # nur der Ordner: oberste Ebene bleibt
    assert [n.name for n in root.children][:3] == ["zeta", "Beta", "Alpha"]


def test_fav_sort_action(qapp):  # L-4230/L-4231
    from panepilot.mainwindow import MainWindow

    w = MainWindow()
    try:
        m = w.fav_model
        m.load_dict({"version": 1, "items": []})
        g = m.add_group("Gruppe")
        m.add_link("/tmp/zz", g, name="zz")
        m.add_link("/tmp/aa", g, name="aa")
        m.add_link("/tmp/q", name="q")
        m.add_link("/tmp/b", name="b")
        view = w.favorites_view(w.active_side)
        view.select_node(g)
        w.do_fav_sort()
        assert [n.name for n in g.children] == ["aa", "zz"]
        assert [n.name for n in m.root.children] == ["Gruppe", "q", "b"]  # nur der Ordner
        view.clearSelection()
        view.setCurrentIndex(view.model().index(-1, 0))
        w.do_fav_sort()
        assert [n.name for n in m.root.children] == ["Gruppe", "b", "q"]
        assert [i["name"] for i in m.to_dict()["items"]] == ["Gruppe", "b", "q"]
    finally:
        w._skip_save_state = True
        w.close()


def test_share_entries_no_date():  # L-4240
    from panepilot import filemodel

    e = filemodel.share_entries("\\\\nas", ["Daten"])[0]
    assert e.mtime < 0


def test_windows_folder_icon_file():  # L-4205
    from panepilot.resources import resource_path

    assert resource_path("icons", "folder.svg").exists()


def test_compare_one_file_each_side_by_click(qapp, tmp_path, monkeypatch):  # Finding Windows 3.1.1
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from panepilot import filecompare
    from panepilot.mainwindow import MainWindow

    a, b = tmp_path / "l", tmp_path / "r"
    a.mkdir()
    b.mkdir()
    (a / "x.txt").write_text("1")
    (b / "y.txt").write_text("2")
    calls = []
    monkeypatch.setattr(filecompare, "compare", lambda win, p1, p2: calls.append((p1, p2)))
    monkeypatch.setattr("panepilot.mainwindow.show_info", lambda *x, **k: calls.append("info"))
    w = MainWindow()
    try:
        w.resize(1200, 700)
        w.show()
        left, right = w.sides["left"].panel, w.sides["right"].panel
        left.navigate(str(a))
        right.navigate(str(b))
        qapp.processEvents()
        for panel, name in ((left, "x.txt"), (right, "y.txt")):
            row = next(i for i in range(panel.model.rowCount()) if panel.model.entry(i).name == name)
            rect = panel.view.visualRect(panel.model.index(row, 0))
            QTest.mouseClick(panel.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                             rect.center())
            qapp.processEvents()
        assert [e.name for e in left.selected_entries()] == ["x.txt"]
        assert [e.name for e in right.selected_entries()] == ["y.txt"]
        w.do_compare_files()
        assert calls == [(str(a / "x.txt"), str(b / "y.txt"))]
    finally:
        w._skip_save_state = True
        w.close()
