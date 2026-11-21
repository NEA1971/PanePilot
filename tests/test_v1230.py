"""Tests for 1.23: view button, paths to clipboard, shared-sidebar icon, launcher after update."""

import os

from PySide6.QtWidgets import QApplication, QMenu

from test_mainwindow import window  # noqa: F401


# --- Knopf „Ansicht“ (L-2300 ff.) ----------------------------------------------------------------------------
def test_view_button(window, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    w = window
    panel = w.active
    assert not panel.icon_mode
    w.trigger("view_mode")  # Details → zuletzt benutzte Symbolgröße (Vorgabe mittel)
    assert panel.icon_mode and panel.icon_size == 128
    w.trigger("view_mode")
    assert not panel.icon_mode
    menu = QMenu()
    w._fill_view_menu(menu)
    texts = [a.text() for a in menu.actions()]
    assert texts == ["Große Symbole", "Mittelgroße Symbole", "Kleine Symbole", "Details"]
    assert [a.isChecked() for a in menu.actions()] == [False, False, False, True]  # Punkt vor „Details“
    assert all(not a.icon().isNull() for a in menu.actions())
    menu.actions()[0].trigger()
    assert panel.icon_mode and panel.icon_size == 256
    w.trigger("view_mode")
    w.trigger("view_mode")
    assert panel.icon_mode and panel.icon_size == 256  # merkt sich die letzte Symbolgröße
    menu2 = QMenu()
    w._fill_view_menu(menu2)
    assert [a.isChecked() for a in menu2.actions()] == [True, False, False, False]


def test_view_button_in_toolbar(window):  # noqa: F811
    from panepilot import toolbar as tb

    # alte Ansicht-Knöpfe werden zu einem Knopf „Ansicht“ (L-2302)
    assert tb.clean_items(["back", "toggle_icon_view", "icons_large", "|", "icons_small"]) == ["back", "view_mode"]
    avail = tb.available_actions()
    assert "view_mode" in avail and "toggle_icon_view" not in avail and "icons_small" not in avail
    w = window
    w.toolbar.set_items(["view_mode", "clip_copy"])
    w.set_toolbar_visible(True)
    QApplication.processEvents()
    proxy = w.toolbar.proxies["view_mode"]
    assert "Details" in proxy.toolTip()
    w.active.set_icon_mode(True)
    w._update_view_actions()
    assert "Mittelgroße" in proxy.toolTip()
    # Menüpunkt bleibt, Tastenkürzel Strg+Umschalt+I auch
    assert w.qactions["toggle_icon_view"].shortcut().toString() == "Ctrl+Shift+I"


# --- Zwischenablage (L-2310 ff.) ------------------------------------------------------------------------------
def test_clipboard_texts(window, tree):  # noqa: F811
    w = window
    panel = w.active
    panel.navigate(str(tree / "a"))
    names = sorted(e.name for e in panel.model.entries() if not e.is_parent)
    files = [n for n in names if "." in n][:1] or names[:1]
    panel.select_names(files, current=files[0])
    cb = QApplication.clipboard()
    w.trigger("clip_path")
    assert cb.text() == str(tree / "a" / files[0])
    w.trigger("clip_name")
    assert cb.text() == files[0]
    w.trigger("clip_stem")
    assert cb.text() == os.path.splitext(files[0])[0]
    w.trigger("clip_folder")
    assert cb.text() == str(tree / "a")
    w.trigger("clip_url")
    assert cb.text().startswith("file:///") and cb.text().endswith(files[0].replace(" ", "%20"))
    w.trigger("clip_details")
    lines = cb.text().splitlines()
    assert lines[0].split("\t") == ["Name", "Größe", "Geändert", "Typ"] and lines[1].startswith(files[0] + "\t")
    # mehrere: eine Zeile je Datei
    panel.select_all()
    w.trigger("clip_name")
    assert sorted(cb.text().splitlines()) == names
    assert w.qactions["clip_path"].shortcut().toString() == "Alt+Ins"
    assert w.qactions["clip_name"].shortcut().toString() == "Alt+Shift+Ins"


def test_clipboard_menus(window):  # noqa: F811
    w = window
    menu = QMenu()
    w._fill_clip_menu(menu)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts[0] == "Dateipfad → Zwischenablage" and texts[-1] == "Details in die Zwischenablage kopieren"
    assert len(texts) == 6
    subs = [m for m in w.menuBar().findChildren(QMenu) if m.title() == "In die Zwischenablage"]
    assert subs and len([a for a in subs[0].actions() if not a.isSeparator()]) == 6


def test_shared_sidebar_icon():
    from panepilot import toolicons as ti
    from panepilot.app import create_app

    create_app([])
    assert ti._PAINTED["toggle_shared_sidebar"] is ti.icon_shared_sidebar_tinted
    for fn in ti.VIEW_ICONS.values():
        assert not fn().isNull()


# --- Update: Starter und alte Datei (L-2320 f.) ---------------------------------------------------------------
def test_update_points_launcher_and_offers_old_file(window, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import desktopint, dialogs, fileops, updatecheck

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    old = tmp_path / "PanePilot-1.22.0-x86_64.AppImage"
    new = tmp_path / "PanePilot-1.23.0-x86_64.AppImage"
    old.write_bytes(b"alt")
    new.write_bytes(b"neu")
    monkeypatch.setenv("APPIMAGE", str(old))
    desktopint.integrate(str(old))
    assert str(old) in desktopint.desktop_path().read_text()
    rel = updatecheck.Release("1.99.0", "notes", "https://example.invalid", new.name, "https://example.invalid/x", 3)
    asked = []
    monkeypatch.setattr(updatecheck, "UpdateDialog", type("D", (), {
        "DOWNLOAD": 1, "SKIP": 2, "LATER": 3,
        "__init__": lambda self, *a: setattr(self, "choice", 1), "exec": lambda self: 0}))
    monkeypatch.setattr(dialogs, "confirm", lambda *a, **k: asked.append(a[2]) or False)
    updatecheck.handle_release(window, rel, manual=True)  # „Später“
    text = desktopint.desktop_path().read_text()
    assert str(new) in text and str(old) not in text  # Starter zeigt schon auf die neue Datei
    assert "Taskleiste" in asked[-1]
    assert window.settings.get("update_old_file") == {"old": str(old), "new": str(new)}
    # alte Version noch einmal gestartet: keine Frage
    updatecheck.offer_old_file_removal(window)
    assert len(asked) == 1 and window.settings.get("update_old_file") is not None
    # neue Version läuft: einmal fragen; „Behalten“ → Datei bleibt, nicht wieder fragen
    monkeypatch.setenv("APPIMAGE", str(new))
    updatecheck.offer_old_file_removal(window)
    assert len(asked) == 2 and old.name in asked[-1] and old.exists()
    assert window.settings.get("update_old_file") is None
    updatecheck.offer_old_file_removal(window)
    assert len(asked) == 2
    # „In den Papierkorb“
    trashed = []
    monkeypatch.setattr(fileops, "move_to_trash", trashed.append)
    monkeypatch.setattr(dialogs, "confirm", lambda *a, **k: True)
    window.settings.set("update_old_file", {"old": str(old), "new": str(new)})
    updatecheck.offer_old_file_removal(window)
    assert trashed == [str(old)]


def test_view_menu_rows(window, qtbot):  # noqa: F811
    from PySide6.QtCore import Qt

    w = window
    menu = QMenu()
    w._fill_view_menu(menu)
    rows = [a.defaultWidget() for a in menu.actions()]
    assert [r.dot.text() for r in rows] == ["", "", "", "●"]
    menu.show()
    qtbot.mouseClick(rows[2], Qt.MouseButton.LeftButton)
    assert w.active.icon_mode and w.active.icon_size == 64


def test_clip_button_menu_only(window):  # noqa: F811
    """1.23.1: keine eigenen Knöpfe für die Zwischenablage-Einträge; oben im Pfeil-Menü das normale Kopieren."""
    from panepilot import toolbar as tb

    for aid in tb.CLIP_MENU_ONLY:
        assert aid not in tb.available_actions()
    assert tb.clean_items(["clip_copy", "clip_path", "clip_details", "back"]) == ["clip_copy", "back"]
    menu = QMenu()
    window._fill_history_menu("clip_copy", menu)
    acts = [a for a in menu.actions() if not a.isSeparator()]
    assert acts[0] is window.qactions["clip_copy"] and len(acts) == 7
