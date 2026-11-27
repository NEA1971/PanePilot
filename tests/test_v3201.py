"""v3.2.1: Hänger unter Windows (Netzpfade), sichtbare Zeilenfarben, Hell/Dunkel ohne Neustart."""

import sys
import time

import pytest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

WIN = sys.platform.startswith("win")
only_windows = pytest.mark.skipif(not WIN, reason="nur unter Windows")


def test_alternate_rows_visible(qapp):
    from panepilot import theme

    try:
        for mode in ("light", "dark"):
            theme.apply(mode)
            pal = QApplication.palette()
            base, alt = pal.color(QPalette.ColorRole.Base), pal.color(QPalette.ColorRole.AlternateBase)
            diff = abs(base.red() - alt.red()) + abs(base.green() - alt.green()) + abs(base.blue() - alt.blue())
            assert diff >= 30, mode  # vorher 36 (hell) bzw. 24 (dunkel) – auf manchen Bildschirmen unsichtbar
    finally:
        theme.apply("light")


def test_theme_switch_no_restart_and_icons_follow(qapp, monkeypatch):
    from panepilot import theme, toolicons
    from panepilot.mainwindow import MainWindow
    from panepilot.settingsdialog import SettingsDialog

    asked = []
    monkeypatch.setattr("panepilot.settingsdialog.confirm", lambda *a, **k: asked.append(a) or False)
    w = MainWindow()
    try:
        light_icon = w.button_bar.buttons["swap_panels"].icon().pixmap(24, 24).toImage()
        dlg = SettingsDialog(w)
        dlg.theme_choice["dark"].setChecked(True)
        dlg.accept()
        assert theme.is_dark() and asked == []  # keine Neustart-Frage mehr
        dark_icon = w.button_bar.buttons["swap_panels"].icon().pixmap(24, 24).toImage()
        assert dark_icon != light_icon  # Symbole sind gleich mit umgefärbt
        assert toolicons._cache == {} or all(not v.isNull() for v in toolicons._cache.values())
    finally:
        theme.apply("light")
        w.settings.set("theme", "system")
        w._skip_save_state = True
        w.close()


def test_favorite_status_in_background(qapp, monkeypatch, tmp_path):
    """Favoriten auf langsamen Netzpfaden: Neuzeichnen fragt den Server nicht im Vordergrund."""
    from panepilot import favorites as fav

    slow = str(tmp_path / "netz")
    calls = []
    real_exists = fav.os.path.exists

    def slow_exists(p):
        if p == slow:
            calls.append(p)
            time.sleep(0.3)
        return real_exists(p)

    status = fav.PathStatus()
    monkeypatch.setattr(fav.PathStatus, "is_slow", staticmethod(lambda p: p == slow))
    monkeypatch.setattr(fav.os.path, "exists", slow_exists)
    got = []
    status.ready.connect(got.append)
    t0 = time.monotonic()
    assert status.get(slow) is None  # sofort zurück, Prüfung läuft im Hintergrund
    assert time.monotonic() - t0 < 0.1
    for _ in range(100):
        qapp.processEvents()
        if got:
            break
        time.sleep(0.02)
    assert got == [slow] and status.get(slow) == (False, False)
    assert len(calls) == 1  # danach aus dem Gedächtnis
    local = str(tmp_path)
    assert status.get(local) == (True, True)


def test_favorites_model_uses_status(qapp, monkeypatch, tmp_path):
    from panepilot import favorites as fav
    from panepilot.icons import IconProvider

    slow = "\\\\server\\freigabe\\ordner"
    monkeypatch.setattr(fav.PathStatus, "is_slow", staticmethod(lambda p: "server" in p))
    monkeypatch.setattr(fav, "_STATUS", None)
    seen = []
    monkeypatch.setattr(fav.PathStatus, "_check", lambda self, p: seen.append(p))
    m = fav.FavoritesModel(IconProvider(), autosave=False)
    node = m.add_link(slow, name="Netz")
    idx = m.index_for(node)
    assert m.data(idx, fav.Qt.ItemDataRole.DecorationRole) is not None
    assert m.link_state(node) == "ok"  # unbekannt gilt als vorhanden – kein rotes Verbotsschild beim Start
    for _ in range(20):
        qapp.processEvents()
        if seen:
            break
        time.sleep(0.02)
    assert len(seen) == 1 and "server" in seen[0]


def test_network_path_detection():
    from panepilot import winsys

    assert winsys.is_network_path("\\\\nas\\Daten\\x")
    assert winsys.is_network_path("//nas/Daten")
    assert not winsys.is_network_path("")
    if not WIN:
        assert not winsys.is_network_path("C:\\x") and not winsys.is_network_path("/home/x")


def test_skip_watch(monkeypatch):
    import panepilot.platform as plat
    from panepilot.filepanel import FilePanel

    monkeypatch.setattr(plat, "IS_WINDOWS", True)
    assert FilePanel._skip_watch("\\\\nas\\Daten")
    assert FilePanel._skip_watch("\\\\nas")
    monkeypatch.setattr(plat, "IS_WINDOWS", False)
    assert not FilePanel._skip_watch("\\\\nas\\Daten")


def test_recycle_dirs_cached(monkeypatch, tmp_path):
    from panepilot import winsys

    calls = []
    import os

    root = str(tmp_path) + os.sep
    (tmp_path / "$Recycle.Bin" / "S-1").mkdir(parents=True)
    monkeypatch.setattr(winsys, "local_drive_roots", lambda: calls.append(1) or [root])
    monkeypatch.setitem(winsys._RECYCLE_CACHE, "time", 0.0)
    first = winsys.recycle_dirs("S-1")
    second = winsys.recycle_dirs("S-1")
    assert first == second == [str(tmp_path / "$Recycle.Bin" / "S-1")] and len(calls) == 1


def test_tree_shares_async(qapp, monkeypatch):
    from panepilot import foldertree as ft
    from panepilot import winsys
    from panepilot.icons import IconProvider

    monkeypatch.setattr(winsys, "list_shares", lambda server: (time.sleep(0.2), ["Daten", "Musik"])[1])
    model = ft.FolderTreeModel(IconProvider(), None)
    if model.network_item is None:
        pytest.skip("Netzwerk-Eintrag gibt es nur im Windows-Baum")
    model.network_item.removeRows(0, model.network_item.rowCount())
    item = model._dir_item("nas", "\\\\nas", ft.K_NETSERVER)
    model.network_item.appendRow(item)
    t0 = time.monotonic()
    model.load_children(item)
    assert time.monotonic() - t0 < 0.1  # Baum hängt nicht
    for _ in range(100):
        qapp.processEvents()
        if item.rowCount() == 2 and item.child(0).text() == "Daten":
            break
        time.sleep(0.02)
    assert [item.child(i).text() for i in range(item.rowCount())] == ["Daten", "Musik"]


@only_windows
def test_win_drives_fast():
    from panepilot import winsys

    t0 = time.monotonic()
    drives = winsys.drives()
    roots = winsys.local_drive_roots()
    assert drives and roots and time.monotonic() - t0 < 5
    assert winsys.is_network_path("C:\\Windows") is False
