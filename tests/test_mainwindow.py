import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from panepilot.app import create_app


@pytest.fixture
def window(qtbot, tree, monkeypatch):
    create_app([])
    from panepilot.mainwindow import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.show()
    qtbot.waitExposed(w)
    w.sides["left"].panel.navigate(str(tree / "a"))
    w.sides["right"].panel.navigate(str(tree / "b"))
    w.sides["left"].panel.view.setFocus()
    w.activateWindow()
    QApplication.processEvents()
    return w


def press(qtbot, w, key, mods=Qt.KeyboardModifier.NoModifier):
    widget = QApplication.focusWidget() or w
    qtbot.keyClick(widget, key, mods)
    QApplication.processEvents()


def test_parent_entry_and_dirs_first(window, tree):
    names = [e.name for e in window.sides["left"].panel.model.entries()]
    assert names == ["..", "sub", "eins.txt"]  # versteckte Datei ausgeblendet


def test_tab_switches_panel(window, qtbot):
    assert window.active_side == "left"
    press(qtbot, window, Qt.Key.Key_Tab)
    assert window.active_side == "right"
    press(qtbot, window, Qt.Key.Key_Tab)
    assert window.active_side == "left"


def test_same_path_and_swap(window, qtbot, tree):
    press(qtbot, window, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert window.sides["right"].panel.current_path == str(tree / "a")
    window.sides["right"].panel.navigate(str(tree / "b"))
    press(qtbot, window, Qt.Key.Key_U, Qt.KeyboardModifier.ControlModifier)
    assert window.sides["left"].panel.current_path == str(tree / "b")
    assert window.sides["right"].panel.current_path == str(tree / "a")


def test_toggle_hidden(window, qtbot):
    press(qtbot, window, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
    assert ".versteckt" in [e.name for e in window.sides["left"].panel.model.entries()]
    press(qtbot, window, Qt.Key.Key_H, Qt.KeyboardModifier.ControlModifier)
    assert ".versteckt" not in [e.name for e in window.sides["left"].panel.model.entries()]


def test_backspace_goes_up_and_selects_origin(window, qtbot, tree):
    press(qtbot, window, Qt.Key.Key_Backspace)
    panel = window.sides["left"].panel
    assert panel.current_path == str(tree)
    assert panel.current_entry().name == "a"


def test_f5_copies_to_other_panel(window, qtbot, tree, monkeypatch):
    import panepilot.mainwindow as mw

    monkeypatch.setattr(mw.CopyMoveDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    panel = window.sides["left"].panel
    panel.select_names(["eins.txt"], current="eins.txt")
    with qtbot.waitSignal(window.ops.finished, timeout=5000):
        press(qtbot, window, Qt.Key.Key_F5)
    assert (tree / "b" / "eins.txt").read_text() == "eins"
    assert (tree / "a" / "eins.txt").exists()


def test_delete_moves_to_trash_without_question(window, qtbot, tree, tmp_path):
    panel = window.sides["left"].panel
    panel.select_names(["eins.txt"], current="eins.txt")
    with qtbot.waitSignal(window.ops.finished, timeout=5000):
        press(qtbot, window, Qt.Key.Key_Delete)
    assert not (tree / "a" / "eins.txt").exists()
    trash = tmp_path / "data" / "Trash" / "files"
    assert any(p.name.startswith("eins") for p in trash.iterdir())


def test_ctrl_b_adds_selection_or_current_folder(window, qtbot, tree):
    panel = window.sides["left"].panel
    press(qtbot, window, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    assert [c.path for c in window.fav_model.root.children] == [str(tree / "a")]
    panel.select_names(["sub"], current="sub")
    press(qtbot, window, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    # neuer Favorit landet direkt hinter dem markierten (zuletzt eingefügten)
    assert [c.name for c in window.fav_model.root.children] == ["a", "sub"]


def test_favorite_click_opens_in_its_panel(window, qtbot, tree):
    node = window.fav_model.add_link(str(tree / "b"))
    window._open_favorite("left", node)
    assert window.sides["left"].panel.current_path == str(tree / "b")
    assert window.active_side == "left"


def test_state_is_restored(window, qtbot, tree):
    g = window.fav_model.add_group("G")
    window.fav_model.add_link(str(tree / "a"), g)
    window.favorites_view("left").restore_expanded([g.id])
    window.set_sidebar_mode("right", "off")
    window.close()
    from panepilot.mainwindow import MainWindow

    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.sides["left"].panel.current_path == str(tree / "a")
    assert w2.sides["right"].panel.current_path == str(tree / "b")
    assert w2.sides["right"].sidebar.mode == "off"
    assert w2.favorites_view("left").expanded_ids() == [g.id]
    assert [c.name for c in w2.fav_model.root.children] == ["G"]


def test_missing_folder_falls_back_to_parent(window, qtbot, tree, monkeypatch):
    import panepilot.mainwindow as mw

    monkeypatch.setattr(mw, "show_error", lambda *a: None)
    panel = window.sides["left"].panel
    panel.navigate(str(tree / "gibtsnicht" / "tiefer"))
    assert panel.current_path == str(tree)


def test_alt_f_toggles_sidebar_and_restores_last_view(window, qtbot):
    window.set_sidebar_mode("left", "tree")
    assert window.tree_view("left") is not None
    press(qtbot, window, Qt.Key.Key_F, Qt.KeyboardModifier.AltModifier)
    assert window.sides["left"].sidebar.mode == "off"
    press(qtbot, window, Qt.Key.Key_F, Qt.KeyboardModifier.AltModifier)
    assert window.sides["left"].sidebar.mode == "tree"


def test_tree_follows_panel(window, qtbot, tree):
    window.set_sidebar_mode("left", "tree")
    window.sides["left"].panel.navigate(str(tree / "a" / "sub"))
    assert window.tree_view("left").current_path() == str(tree / "a" / "sub")


def test_mouse_back_and_forward_buttons(window, qtbot, tree):
    panel = window.sides["left"].panel
    panel.navigate(str(tree / "a" / "sub"))
    qtbot.mouseClick(panel.view.viewport(), Qt.MouseButton.BackButton)
    assert panel.current_path == str(tree / "a")
    qtbot.mouseClick(panel.view.viewport(), Qt.MouseButton.ForwardButton)
    assert panel.current_path == str(tree / "a" / "sub")


def test_column_resize_is_independent(window):
    hdr = window.sides["left"].panel.view.header()
    name_before = hdr.sectionSize(0)
    hdr.resizeSection(1, hdr.sectionSize(1) + 40)
    assert hdr.sectionSize(0) == name_before
    hdr.resizeSection(0, name_before + 50)
    assert hdr.sectionSize(0) == name_before + 50


def test_new_textfile_creates_unique_names(window, qtbot, tree):
    window.trigger("new_textfile")
    assert (tree / "a" / "Neue Textdatei.txt").exists()
    panel = window.sides["left"].panel
    assert panel.view.state() == panel.view.State.EditingState
    panel.view.setFocus()
    window.trigger("new_textfile")
    assert (tree / "a" / "Neue Textdatei (2).txt").exists()


def test_buttonbar_copies_without_question_in_arrow_direction(window, qtbot, tree):
    window.do_switch_panel()  # rechts aktiv → Pfeile zeigen nach links
    right = window.sides["right"].panel
    right.select_names(["zwei.txt"], current="zwei.txt")
    with qtbot.waitSignal(window.ops.finished, timeout=5000):
        window.button_bar.buttons["copy_direct"].click()
    assert (tree / "a" / "zwei.txt").exists()


def test_fkey_assignment_drives_keyboard_and_persists(window, qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "do_refresh", lambda: calls.append("refresh"))
    window.set_fkey("F3", "refresh")
    assert "F3\n" in window.fkey_bar.buttons["F3"].text()
    press(qtbot, window, Qt.Key.Key_F3)
    assert calls == ["refresh"]
    window.set_fkey("F5", None)
    from panepilot.config import Settings

    stored = Settings().get("fkeys")
    assert stored == {"F3": "refresh", "F5": None}


def test_f4_opens_default_text_editor(window, qtbot, monkeypatch):
    import panepilot.mainwindow as mw

    launched = []
    monkeypatch.setattr(mw.desktop_apps, "default_text_editor", lambda: "EDITOR")
    monkeypatch.setattr(mw.desktop_apps, "launch", lambda app, files: launched.append((app, files)) or True)
    panel = window.sides["left"].panel
    panel.select_names(["eins.txt"], current="eins.txt")
    press(qtbot, window, Qt.Key.Key_F4)
    assert launched == [("EDITOR", [panel.model.entries()[2].path])]


def test_columns_show_hide_and_persist(window, qtbot, tree):
    from panepilot.filemodel import COL_NAME, COL_PERM_STR

    panel = window.sides["left"].panel
    assert not panel.column_visible(COL_PERM_STR)
    panel.set_column_visible(COL_PERM_STR, True)
    panel.set_column_visible(COL_NAME, False)  # nicht erlaubt
    assert panel.column_visible(COL_NAME)
    row = panel.model.row_of("eins.txt")
    assert panel.model.index(row, COL_PERM_STR).data().startswith("-rw")
    window.close()
    from panepilot.mainwindow import MainWindow

    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.sides["left"].panel.column_visible(COL_PERM_STR)
    # beide Fenster nutzen das Spaltenprofil „Standard“ (F-842) → gleiche Spalten
    assert w2.sides["right"].panel.column_visible(COL_PERM_STR)


def test_fkey_right_click_opens_assign_menu(window, qtbot):
    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtGui import QContextMenuEvent

    seen = []

    def grab_menu():
        menu = QApplication.activePopupWidget()
        seen.append([a.text() for a in menu.actions()] if menu else None)
        if menu:
            menu.close()

    QTimer.singleShot(100, grab_menu)
    btn = window.fkey_bar.buttons["F3"]
    QApplication.sendEvent(btn, QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(5, 5), btn.mapToGlobal(QPoint(5, 5))))
    assert seen and seen[0] and "Keine Funktion" in seen[0]


def test_assigned_fkey_shows_label_in_normal_color(window):
    window.set_fkey("F12", "fav_new_group")
    btn = window.fkey_bar.buttons["F12"]
    assert btn.text() == "F12\nFav.-Ordner"
    normal = QApplication.palette().color(QApplication.palette().ColorRole.ButtonText)
    assert btn.palette().color(btn.palette().ColorRole.ButtonText) == normal


def test_name_without_extension_column(window, tree):
    from panepilot.filemodel import COL_NAME, COL_NAME_STEM

    panel = window.sides["left"].panel
    panel.set_column_visible(COL_NAME_STEM, True)
    panel.set_column_visible(COL_NAME, False)
    assert not panel.column_visible(COL_NAME)
    panel.set_column_visible(COL_NAME_STEM, False)  # letzte Namensspalte bleibt
    assert panel.column_visible(COL_NAME_STEM)
    row = panel.model.row_of("eins.txt")
    idx = panel.model.index(row, COL_NAME_STEM)
    assert idx.data() == "eins"
    assert panel.model.setData(idx, "zwei")
    assert (tree / "a" / "zwei.txt").exists()
    assert panel.model.icon_column == COL_NAME_STEM


def test_owner_and_permission_tooltips(window):
    from panepilot.filemodel import COL_GROUP, COL_OWNER, COL_PERM_NUM, COL_PERM_STR

    m = window.sides["left"].panel.model
    row = m.row_of("eins.txt")
    tip = lambda c: m.index(row, c).data(Qt.ItemDataRole.ToolTipRole)  # noqa: E731
    assert tip(COL_OWNER) == f"UID {os.getuid()}" and tip(COL_GROUP) == f"GID {os.getgid()}"
    assert tip(COL_PERM_NUM).startswith("-rw") and tip(COL_PERM_STR).isdigit()


def test_single_pane_mode_blocks_other_panel(window, qtbot, tree):
    window.set_single_mode(True)
    assert not window.sides["right"].splitter.isVisible()
    assert not window.button_bar.isVisible()
    press(qtbot, window, Qt.Key.Key_Tab)
    assert window.active_side == "left"
    panel = window.sides["left"].panel
    panel.select_names(["eins.txt"], current="eins.txt")
    press(qtbot, window, Qt.Key.Key_F5)  # gesperrt – kein Dialog, keine Kopie
    assert not (tree / "b" / "eins.txt").exists()
    assert not window.fkey_bar.buttons["F5"].isEnabled()
    window.close()
    from panepilot.mainwindow import MainWindow

    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.single_mode
    w2.set_single_mode(False)
    assert w2.fkey_bar.buttons["F5"].isEnabled()


def test_single_mode_menu_texts(window):
    act = window.qactions["toggle_single"]
    assert act.isCheckable() and not act.isChecked()
    window.set_single_mode(True)
    assert act.isChecked()
    left, right = window.sidebar_submenus["left"], window.sidebar_submenus["right"]
    assert left.title() == "Seitenleiste" and left.menuAction().isVisible()
    assert not right.menuAction().isVisible()
    assert window.qactions["toggle_sidebar"].text() == "Seitenleiste an/aus"
    window.set_single_mode(False)
    assert left.title() == "Seitenleiste links" and right.menuAction().isVisible()
    assert window.qactions["toggle_sidebar"].text().startswith("Seitenleiste an/aus (")


def test_header_menu_order_and_no_grey(window):
    from PySide6.QtCore import QPoint, QTimer

    seen = []

    def grab():
        menu = QApplication.activePopupWidget()
        seen.append([(a.text(), a.isEnabled()) for a in menu.actions()])
        menu.close()

    QTimer.singleShot(100, grab)
    window.sides["left"].panel._header_menu(QPoint(5, 5))
    texts = [x[0] for x in seen[0]]
    assert texts[:2] == ["Name (mit Endung)", "Name (ohne Endung)"]
    assert all(enabled for _t, enabled in seen[0])


def test_rename_editor_survives_folder_refresh(window, qtbot, tree):
    window.trigger("new_textfile")
    panel = window.sides["left"].panel
    assert panel.view.state() == panel.view.State.EditingState
    qtbot.wait(700)  # Ordnerüberwachung meldet die neue Datei – das Umbenennen muss offen bleiben
    panel.refresh()
    assert panel.view.state() == panel.view.State.EditingState


def test_name_columns_are_exclusive_and_menu_order(window):
    from PySide6.QtCore import QPoint, QTimer

    from panepilot.filemodel import COL_CREATED, COL_NAME, COL_NAME_STEM

    panel = window.sides["left"].panel
    assert not panel.column_visible(COL_CREATED)  # F-512
    panel.set_column_visible(COL_NAME_STEM, True)
    assert panel.column_visible(COL_NAME_STEM) and not panel.column_visible(COL_NAME)
    panel.set_column_visible(COL_NAME, True)
    assert panel.column_visible(COL_NAME) and not panel.column_visible(COL_NAME_STEM)
    panel.set_column_visible(COL_NAME, False)  # bleibt
    assert panel.column_visible(COL_NAME)
    seen = []

    def grab():
        menu = QApplication.activePopupWidget()
        seen.append([a.text() for a in menu.actions()])
        menu.close()

    QTimer.singleShot(100, grab)
    panel._header_menu(QPoint(5, 5))
    texts = seen[0]
    assert texts[:3] == ["Name (mit Endung)", "Name (ohne Endung)", "Dateiendung"]
    assert texts.index("Erstellt") + 1 == texts.index("Geändert")


def test_created_column_from_old_state(window, qtbot):
    from panepilot.filemodel import COL_CREATED, COL_DATE, COL_NAME, COL_NAME_STEM

    panel = window.sides["left"].panel
    # Zustand wie aus v0.4: beide Namensspalten sichtbar, 10 Spalten
    panel.view.header().setSectionHidden(COL_NAME_STEM, False)
    state = panel.header_state()
    panel.restore_header_state(state, 10)
    hdr = panel.view.header()
    assert not panel.column_visible(COL_CREATED)
    assert hdr.visualIndex(COL_CREATED) < hdr.visualIndex(COL_DATE)
    assert [panel.column_visible(c) for c in (COL_NAME, COL_NAME_STEM)].count(True) == 1
    panel.set_column_visible(COL_CREATED, True)
    row = panel.model.row_of("eins.txt")
    text = panel.model.index(row, COL_CREATED).data()
    assert text == "" or text.count(".") == 2  # Datum oder leer, wenn das Dateisystem es nicht liefert


def test_unmounted_share_is_not_mounted_on_start(window, qtbot, tree, monkeypatch):
    from pathlib import Path

    share = str(tree / "a")
    window.close()
    from panepilot.mounts import MountManager

    calls = []
    monkeypatch.setattr(MountManager, "needs_mount", lambda self, p: object() if p == share else None)
    monkeypatch.setattr(MountManager, "mount", lambda self, e, cb: calls.append(e))
    from panepilot.mainwindow import MainWindow

    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.sides["left"].panel.current_path == str(Path.home())
    assert not calls


def test_toolbar_history_and_customizing(window, qtbot, tree, monkeypatch):
    from PySide6.QtWidgets import QMenu

    panel = window.sides["left"].panel
    assert window.toolbar.items == ["back", "forward"]
    assert window.qactions["back"].isEnabled() is panel.can_go_back()
    panel.navigate(str(tree / "a" / "sub"))
    assert window.qactions["back"].isEnabled() and not window.qactions["forward"].isEnabled()
    menu = QMenu()
    window._fill_history_menu("back", menu)
    assert menu.actions()[0].text() == str(tree / "a")
    menu.actions()[0].trigger()
    assert panel.current_path == str(tree / "a")
    assert window.qactions["forward"].isEnabled()

    import panepilot.mainwindow as mw

    class FakeDialog:
        DialogCode = QDialog.DialogCode

        def __init__(self, parent, items):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def result_items(self):
            return ["back", "|", "refresh", "unbekannt", "|"]

    monkeypatch.setattr(mw, "ToolbarDialog", FakeDialog)
    window.customize_toolbar()
    assert window.toolbar.items == ["back", "|", "refresh"]
    window.set_toolbar_visible(False)
    window.close()
    w2 = mw.MainWindow()
    qtbot.addWidget(w2)
    assert w2.toolbar.items == ["back", "|", "refresh"]
    assert not w2.qactions["toggle_toolbar"].isChecked()


def test_toolbar_dialog_editing(window):
    from panepilot.toolbar import DEFAULT_ITEMS, ToolbarDialog

    dlg = ToolbarDialog(window, ["back", "forward"])
    dlg.chosen.setCurrentRow(0)
    dlg._add_separator()
    for i in range(dlg.available.count()):
        if dlg.available.item(i).data(Qt.ItemDataRole.UserRole) == "refresh":
            dlg.available.setCurrentRow(i)
    dlg._add()
    assert dlg.items() == ["back", "|", "refresh", "forward"]
    dlg._move(-1)
    assert dlg.items() == ["back", "refresh", "|", "forward"]
    dlg._remove()
    assert dlg.items() == ["back", "|", "forward"]
    assert "refresh" in [dlg.available.item(i).data(Qt.ItemDataRole.UserRole) for i in range(dlg.available.count())]
    dlg.btn_default.click()
    assert dlg.items() == DEFAULT_ITEMS


def test_compress_and_extract_via_window(window, qtbot, tree, monkeypatch):
    import panepilot.mainwindow as mw

    panel = window.sides["left"].panel
    panel.select_names(["eins.txt", "sub"], current="eins.txt")
    stems = []

    class FakeCompress:
        DialogCode = QDialog.DialogCode

        def __init__(self, parent, what, stem, folder):
            stems.append(stem)

        def exec(self):
            return QDialog.DialogCode.Accepted
        def stem(self):
            return "paket"
        def archive_format(self):
            return "tar.gz"

    monkeypatch.setattr(mw, "CompressDialog", FakeCompress)
    window.trigger("compress")
    qtbot.waitUntil(lambda: (tree / "a" / "paket.tar.gz").exists() and not window.ops.is_busy(), timeout=5000)
    assert stems == ["a"]  # mehrere Einträge: Name des Ordners
    assert panel.current_entry().name == "paket.tar.gz"  # neues Archiv ist markiert
    panel.select_names(["eins.txt", "sub"], current="eins.txt")
    window.trigger("compress")  # zweites Mal: automatisch nummeriert (F-534)
    qtbot.waitUntil(lambda: (tree / "a" / "paket (2).tar.gz").exists() and not window.ops.is_busy(), timeout=5000)
    panel.refresh()
    panel.select_names(["paket.tar.gz"], current="paket.tar.gz")
    window.trigger("extract_subfolder")
    qtbot.waitUntil(lambda: (tree / "a" / "paket" / "eins.txt").exists() and not window.ops.is_busy(), timeout=5000)
    assert (tree / "a" / "paket" / "sub").is_dir()


@pytest.mark.parametrize("side", ["left", "right"])
def test_cursor_after_delete_with_name_without_extension(window, qtbot, tree, side):
    """Fehler 0.5.0: Mit „Name (ohne Endung)“ stand der Cursor in der ausgeblendeten Spalte."""
    from panepilot.filemodel import COL_NAME_STEM

    d = tree / "c"
    d.mkdir()
    for n in "abcd":
        (d / f"{n}.txt").write_text(n)
    panel = window.sides[side].panel
    panel.navigate(str(d))
    panel.set_column_visible(COL_NAME_STEM, True)
    panel.view.setFocus()
    window.set_active_side(side)
    panel.select_names(["b.txt"], current="b.txt")
    with qtbot.waitSignal(window.ops.finished, timeout=5000):
        press(qtbot, window, Qt.Key.Key_Delete)
    assert panel.current_entry().name == "c.txt"
    assert panel.view.currentIndex().column() == COL_NAME_STEM
    press(qtbot, window, Qt.Key.Key_Down)
    assert [e.name for e in panel.selected_entries()] == ["d.txt"]
    press(qtbot, window, Qt.Key.Key_Up)
    assert [e.name for e in panel.selected_entries()] == ["c.txt"]


def test_switching_name_column_moves_cursor(window):
    from panepilot.filemodel import COL_NAME, COL_NAME_STEM

    panel = window.sides["left"].panel
    panel.select_names(["eins.txt"], current="eins.txt")
    assert panel.view.currentIndex().column() == COL_NAME
    panel.set_column_visible(COL_NAME_STEM, True)
    assert panel.view.currentIndex().column() == COL_NAME_STEM
    assert panel.current_entry().name == "eins.txt"


# --- v0.6 -------------------------------------------------------------------------------------
def test_filter_wildcards_regex_and_ui(window, tree, monkeypatch):
    from panepilot.filters import FilterSpec

    d = tree / "f"
    d.mkdir()
    for n in ("bericht.pdf", "brief.DOCX", "foto.jpg", "2026-plan.txt"):
        (d / n).write_text("x")
    (d / "ordner").mkdir()
    panel = window.active
    panel.navigate(str(d))
    window._apply_filter(FilterSpec("*.pdf;*.docx"), True)
    names = sorted(e.name for e in panel.model.entries() if not e.is_parent)
    assert names == ["bericht.pdf", "brief.DOCX", "ordner"]  # Ordner bleiben, Schreibweise egal
    assert panel.header.property("filtered") is True
    assert window.qactions["filter_toggle"].isChecked()
    assert panel.filter_counts() == (3, 5)
    panel.navigate(str(tree / "a"))  # bleibt beim Ordnerwechsel aktiv
    assert panel.filter_active
    panel.navigate(str(d))
    window.trigger("filter_toggle")  # aus
    assert not panel.filter_active and panel.header.property("filtered") is False
    assert len([e for e in panel.model.entries() if not e.is_parent]) == 5
    window.trigger("filter_toggle")  # wieder an mit dem letzten Filter
    assert panel.filter_active
    window._apply_filter(FilterSpec(r"^\d{4}-", regex=True), True)
    assert [e.name for e in panel.model.entries() if not e.is_parent] == ["ordner", "2026-plan.txt"] or \
        sorted(e.name for e in panel.model.entries() if not e.is_parent) == ["2026-plan.txt", "ordner"]
    window._apply_filter(FilterSpec("*.jpg", invert=True, dirs=True), True)
    assert sorted(e.name for e in panel.model.entries() if not e.is_parent) == \
        ["2026-plan.txt", "bericht.pdf", "brief.DOCX", "ordner"]
    window._apply_filter(FilterSpec("o", dirs=True), True)  # ohne Platzhalter: Teil des Namens
    assert sorted(e.name for e in panel.model.entries() if not e.is_parent) == ["brief.DOCX", "foto.jpg", "ordner"]
    other = window.sides[window.other_side].panel
    assert not other.filter_active  # je Panel eigener Filter
    recent = window._recent_filters()
    assert recent[0] == FilterSpec("o", dirs=True) and len(recent) == 4


def test_filter_spec_validation():
    from panepilot.filters import FilterSpec, add_recent

    assert FilterSpec("(", regex=True).error()
    assert FilterSpec("(").error() is None
    assert FilterSpec("  ").error() == "empty"
    rec = []
    for i in range(20):
        rec = add_recent(rec, FilterSpec(f"*.{i}"))
    assert len(rec) == 15 and rec[0]["pattern"] == "*.19"
    rec = add_recent(rec, FilterSpec("*.5"))
    assert rec[0]["pattern"] == "*.5" and [r["pattern"] for r in rec].count("*.5") == 1


def test_filter_dialog_blocks_invalid_regex(window):
    from PySide6.QtWidgets import QDialogButtonBox

    from panepilot.dialogs import FilterDialog

    dlg = FilterDialog(window, None, [])
    ok = next(b for b in dlg.buttons.buttons() if dlg.buttons.buttonRole(b) == QDialogButtonBox.ButtonRole.AcceptRole)
    assert not ok.isEnabled()
    dlg.regex.setChecked(True)
    dlg.pattern.setEditText("(abc")
    assert not ok.isEnabled() and dlg.error.text()
    dlg.pattern.setEditText("abc$")
    assert ok.isEnabled() and dlg.spec().regex


def test_favorite_sets(window, qtbot, tree, monkeypatch):
    import panepilot.mainwindow as mw
    from panepilot.config import config_dir

    window.set_sidebar_mode("left", "favorites")
    window.set_sidebar_mode("right", "favorites")
    assert window.fav_set == {"left": "Standard", "right": "Standard"}
    assert (config_dir() / "Favoriten" / "Standard.json").exists()
    answers = iter(["SMO MT"])
    monkeypatch.setattr(mw, "ask_text", lambda *a, **k: next(answers))
    window.new_fav_set("left")
    assert window.fav_set["left"] == "SMO MT" and window.fav_set["right"] == "Standard"
    pane = window._fav_pane("left")
    assert pane.title_button.text().startswith("SMO MT") and pane.title_button.menu() is not None
    window.set_active_side("left")
    window._add_favorite_paths([str(tree / "a")])
    assert [c.name for c in window.fav_sets.model("SMO MT").root.children] == ["a"]
    assert window.fav_sets.model("Standard").root.children == []
    # Umbenennen benennt die Datei mit um
    monkeypatch.setattr(mw, "ask_text", lambda *a, **k: "Privat")
    window.rename_fav_set("left")
    assert (config_dir() / "Favoriten" / "Privat.json").exists()
    assert not (config_dir() / "Favoriten" / "SMO MT.json").exists()
    assert window.fav_set["left"] == "Privat"
    # ungültige Namen
    assert window.fav_sets.name_error("a/b") == "favsets.error_chars"
    assert window.fav_sets.name_error("standard") == "favsets.error_exists"
    # Zustand bleibt nach Neustart erhalten
    window.close()
    w2 = mw.MainWindow()
    qtbot.addWidget(w2)
    assert w2.fav_set["left"] == "Privat" and w2.fav_set["right"] == "Standard"
    assert [c.name for c in w2.favorites_view("left").fav_model.root.children] == ["a"]
    # Löschen; der letzte Satz bleibt
    monkeypatch.setattr(mw, "confirm", lambda *a, **k: True)
    w2.delete_fav_set("left")
    assert w2.fav_sets.names() == ["Standard"] and w2.fav_set["left"] == "Standard"
    w2.delete_fav_set("left")
    assert w2.fav_sets.names() == ["Standard"]


def test_migration_of_old_favorites(qapp, monkeypatch):
    import json

    from panepilot.config import config_dir
    from panepilot.favsets import FavoriteSets
    from panepilot.icons import IconProvider

    (config_dir() / "favorites.json").write_text(json.dumps(
        {"version": 1, "items": [{"type": "link", "name": "X", "path": "/tmp"}]}))
    sets = FavoriteSets(IconProvider())
    assert sets.names() == ["Standard"]
    assert not (config_dir() / "favorites.json").exists()
    assert [c.name for c in sets.model("Standard").root.children] == ["X"]


def test_add_favorite_needs_open_sidebar_in_active_panel(window, tree, monkeypatch):
    import panepilot.mainwindow as mw

    errors = []
    monkeypatch.setattr(mw, "show_error", lambda parent, title, text: errors.append(text))
    window.set_sidebar_mode("left", "tree")
    window.set_sidebar_mode("right", "favorites")
    window.set_active_side("left")
    before = len(window.fav_sets.model("Standard").root.children)
    window._add_favorite_paths([str(tree / "a")])
    assert errors and len(window.fav_sets.model("Standard").root.children) == before
    assert window.tree_view("left") is not None  # Ordnerbaum steckt jetzt in einer Leiste mit Titel
    window._pane("left", window.tree_view("left"), "x")  # erzeugt keinen Fehler


def test_fkey_layers(window, qtbot, tree, monkeypatch):
    from panepilot.bars import layer_from_modifiers

    panel = window.active
    panel.view.setFocus()
    assert window.fkeys["Shift+F4"] == "new_textfile"
    assert layer_from_modifiers(Qt.KeyboardModifier.ShiftModifier) == "Shift+"
    assert layer_from_modifiers(Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier) == ""
    window.fkey_bar.set_layer("Ctrl+")
    assert window.fkey_bar.buttons["F5"].text().startswith("STRG+F5")
    window.fkey_bar.set_layer("Alt+")
    assert "(GNOME)" in window.fkey_bar.buttons["F4"].text()
    window.fkey_bar.set_layer("")
    assert window.fkey_bar.buttons["F5"].text().startswith("F5\n")
    window.set_fkey("Ctrl+F7", "refresh")
    called = []
    monkeypatch.setattr(window, "do_refresh", lambda: called.append(1))
    press(qtbot, window, Qt.Key.Key_F7, Qt.KeyboardModifier.ControlModifier)
    assert called == [1]
    window.close()
    import panepilot.mainwindow as mw

    w2 = mw.MainWindow()
    qtbot.addWidget(w2)
    assert w2.fkeys["Ctrl+F7"] == "refresh" and w2.fkeys["F7"] == "new_folder"


# --- v0.7 -------------------------------------------------------------------------------------
def _rename_dir(tree):
    d = tree / "fotos"
    d.mkdir()
    for i in range(1, 4):
        (d / f"IMG_000{i}.JPG").write_text(str(i))
    (d / "notiz.txt").write_text("n")
    return d


def test_multi_rename_mode_and_rename(window, qtbot, tree):
    from panepilot import multirename as mr

    d = _rename_dir(tree)
    panel = window.active
    panel.navigate(str(d))
    window.set_sidebar_mode(window.active_side, "tree")
    sizes = window.sides[window.active_side].splitter.sizes()
    press(qtbot, window, Qt.Key.Key_M, Qt.KeyboardModifier.ControlModifier)
    assert window.rename_mode is not None and window.single_mode
    assert panel.preview.isVisible() and not panel.view.isVisible()
    assert not window.qactions["copy"].isEnabled() and window.qactions["filter_toggle"].isEnabled()
    pane = window._rename_pane()
    pane.set_options(mr.RenameOptions(pattern="Bild_[C]", counter_digits=2, case_mode=mr.CASE_LOWER))
    res = pane.preview_model.results
    assert [r.new for r in res] == ["bild_01.JPG", "bild_02.JPG", "bild_03.JPG", "bild_04.txt"]
    assert pane.btn_rename.isEnabled()
    panel.navigate(str(tree))  # gesperrt
    assert panel.current_path == str(d)
    # Filter im Modus (F-703)
    from panepilot.filters import FilterSpec

    window._apply_filter(FilterSpec("*.jpg"), True)
    assert [r.old for r in pane.preview_model.results] == ["IMG_0001.JPG", "IMG_0002.JPG", "IMG_0003.JPG"]
    pane.rename_clicked.emit()
    assert window.rename_mode is None and not window.single_mode
    assert window.sides[window.active_side].sidebar.mode == "tree"
    assert window.sides[window.active_side].splitter.sizes()[0] == sizes[0]
    assert sorted(os.listdir(d)) == ["bild_01.JPG", "bild_02.JPG", "bild_03.JPG", "notiz.txt"]
    assert sorted(e.name for e in panel.selected_entries()) == ["bild_01.JPG", "bild_02.JPG", "bild_03.JPG"]
    assert window.qactions["copy"].isEnabled()
    # Rückgängig (F-733)
    window.trigger("rename_undo")
    assert sorted(os.listdir(d)) == ["IMG_0001.JPG", "IMG_0002.JPG", "IMG_0003.JPG", "notiz.txt"]
    assert not window.qactions["rename_undo"].isEnabled()
    # letzte Einstellungen bleiben (F-732)
    window.trigger("multi_rename")
    assert window._rename_pane().options().pattern == "Bild_[C]"
    press(qtbot, window, Qt.Key.Key_Escape)
    assert window.rename_mode is None


def test_multi_rename_conflicts_block(window, tree):
    from panepilot import multirename as mr

    d = _rename_dir(tree)
    window.active.navigate(str(d))
    window.trigger("multi_rename")
    pane = window._rename_pane()
    pane.set_options(mr.RenameOptions(pattern="gleich"))
    assert not pane.btn_rename.isEnabled()
    assert any(r.status == mr.CONFLICT for r in pane.preview_model.results)
    pane.set_options(mr.RenameOptions(search="(", search_mode=mr.SEARCH_REGEX))
    assert not pane.btn_rename.isEnabled() and pane.search_error.text()
    window.leave_rename_mode()


def test_multi_rename_profiles(window, tree, monkeypatch):
    import panepilot.mainwindow as mw
    from panepilot import multirename as mr
    from panepilot.renamepane import profile_names

    window.active.navigate(str(_rename_dir(tree)))
    window.trigger("multi_rename")
    pane = window._rename_pane()
    pane.set_options(mr.RenameOptions(pattern="P_[N]", counter_digits=5))
    monkeypatch.setattr(mw, "ask_text", lambda *a, **k: "Fotos")
    window._save_rename_profile()
    assert profile_names() == ["Fotos"]
    pane.set_options(mr.RenameOptions())
    pane.profile_box.setCurrentIndex(pane.profile_box.findData("Fotos"))
    pane._profile_chosen(pane.profile_box.currentIndex())
    assert pane.options().pattern == "P_[N]" and pane.options().counter_digits == 5
    monkeypatch.setattr(mw, "confirm", lambda *a, **k: True)
    window._delete_rename_profile()
    assert profile_names() == []
    window.leave_rename_mode()


def test_multi_rename_blocked_in_trash(window):
    from panepilot.trash import TRASH_URI

    window.active.navigate(TRASH_URI)
    window.trigger("multi_rename")
    assert window.rename_mode is None


def test_filter_hide_dirs_and_rename_colors(window, tree):
    from PySide6.QtCore import Qt as _Qt

    from panepilot import multirename as mr
    from panepilot.dialogs import FilterDialog
    from panepilot.filters import FilterSpec

    d = _rename_dir(tree)
    (d / "Unterordner").mkdir()
    panel = window.active
    panel.navigate(str(d))
    spec = FilterSpec("", hide_dirs=True)
    assert spec.error() is None and FilterSpec("").error() == "empty"
    window._apply_filter(spec, True)
    names = [e.name for e in panel.model.entries() if not e.is_parent]
    assert "Unterordner" not in names and len(names) == 4
    assert window._recent_filters()[0].label() == "(nur Ordner ausblenden)"
    window._apply_filter(FilterSpec("*.txt", hide_dirs=True), True)
    assert [e.name for e in panel.model.entries() if not e.is_parent] == ["notiz.txt"]
    dlg = FilterDialog(window, FilterSpec("", hide_dirs=True), [])
    assert not dlg.dirs.isEnabled() and dlg.spec().hide_dirs
    # Vorschau: geänderte Namen grün, normale Schrift
    window._apply_filter(spec, True)
    window.trigger("multi_rename")
    pane = window._rename_pane()
    pane.set_options(mr.RenameOptions(pattern="x_[C]"))
    m = pane.preview_model
    assert "Unterordner" not in [r.old for r in m.results]
    idx = m.index(0, 1)
    assert m.data(idx, _Qt.ItemDataRole.ForegroundRole).name().lower() == "#2e7d32"
    assert m.data(idx, _Qt.ItemDataRole.FontRole) is None
    window.leave_rename_mode()
