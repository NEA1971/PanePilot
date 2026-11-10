"""Tests für v0.8.1: Netzfreigaben in der Suche, Prüfsummen folgen dem aktiven Fenster,
freie Dialogfenster, Liste der Sicherungen mit Import/Löschen und Fehlervermerk."""

import datetime as dt
import hashlib
import os
import zipfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from test_mainwindow import window  # noqa: F401


# --- Suche: Netzfreigaben ---------------------------------------------------------------------------
def test_network_mount_points():
    from panepilot.mounts import network_mount_points

    text = (
        "/dev/sda1 / ext4 rw 0 0\n"
        "//nas/musik /srv/NAS/Musik cifs rw 0 0\n"
        "nas:/daten /mnt/daten nfs4 rw 0 0\n"
        "gvfsd-fuse /run/user/1000/gvfs fuse.gvfsd-fuse rw 0 0\n"
        "/dev/sdb1 /media/alice/USB vfat rw 0 0\n"
    )
    assert network_mount_points(text) == {"/srv/NAS/Musik", "/mnt/daten", "/run/user/1000/gvfs"}


def test_search_skips_network_shares_but_not_start_folder(tree):
    from panepilot.search import SearchOptions, SearchThread

    def run(base, exclude):
        found = []
        th = SearchThread(str(base), SearchOptions(name="*.txt"), exclude=exclude)
        th.found.connect(found.extend)
        th.run()
        return sorted(os.path.relpath(p, base) for p in found)

    share = {str(tree / "a" / "sub")}
    assert run(tree, share) == ["a/eins.txt", "b/zwei.txt"]
    assert run(tree, set()) == ["a/eins.txt", "a/sub/tief.txt", "b/zwei.txt"]
    # Beginnt die Suche in der Freigabe selbst, wird sie durchsucht
    assert run(tree / "a" / "sub", share) == ["tief.txt"]


def test_search_pane_network_option(window):  # noqa: F811
    from panepilot.search import SearchOptions

    window.settings.set("search_last", SearchOptions(name="*.txt", network=True).to_dict())
    window.trigger("search")
    pane = window.sides[window.active_side].sidebar.widget_for("search")
    assert not pane.network.isChecked() and pane.network_hint.isHidden()  # neue Suche: aus
    pane.network.setChecked(True)
    assert not pane.network_hint.isHidden()
    assert pane.options().network
    assert SearchOptions.from_dict(pane.options().to_dict()).network  # im Profil gespeichert
    window.close_tool(window.active_side)


# --- Prüfsummen folgen dem aktiven Fenster -----------------------------------------------------------
def test_checksum_follows_active_panel(window, tree, qtbot):  # noqa: F811
    window.sides["left"].panel.view.setFocus()
    QApplication.processEvents()
    window.sides["left"].panel.select_names([], current="eins.txt")
    window.trigger("checksums")
    pane = window.sides["left"].sidebar.widget_for("checksum")
    qtbot.waitUntil(lambda: pane.values.get("md5") == hashlib.md5(b"eins").hexdigest(), timeout=5000)
    right = window.sides["right"].panel
    right.view.setFocus()
    QApplication.processEvents()
    right.select_names([], current="zwei.txt")
    qtbot.waitUntil(lambda: pane.values.get("md5") == hashlib.md5(b"zwei").hexdigest(), timeout=5000)
    # Ein Klick ins Vergleichsfeld (linke Seitenleiste) ändert die Quelle nicht
    pane.compare.setFocus()
    QApplication.processEvents()
    assert window._checksum_side == "right"
    window.close_tool("left")


# --- Freie Dialogfenster -------------------------------------------------------------------------------
def test_dialogs_are_free_windows(window):  # noqa: F811
    from panepilot.dialogs import FilterDialog
    from panepilot.settingsdialog import SettingsDialog

    for dlg in (SettingsDialog(window), FilterDialog(window, None, [])):
        flags = dlg.windowFlags()
        assert flags & Qt.WindowType.WindowType_Mask == Qt.WindowType.Window
        assert dlg.windowModality() == Qt.WindowModality.ApplicationModal
        dlg.deleteLater()


# --- Sicherungen: Liste, Import, Löschen, Fehlervermerk ----------------------------------------------
def test_backup_list_import_delete(tmp_path):
    from panepilot import backup
    from panepilot.config import save_json

    save_json("settings.json", {"show_hidden": True})
    folder = tmp_path / "sich"
    a = backup.create_backup(folder, auto=True, day=dt.date(2026, 11, 6))
    b = backup.create_backup(folder, auto=False, day=dt.date(2026, 11, 7))
    infos = backup.list_backups(folder)
    assert [i.name for i in infos] == [b.name, a.name]  # neueste zuerst
    assert [i.auto for i in infos] == [False, True]

    # Import: Name bleibt, wenn frei; sonst nächster Buchstabe
    usb = tmp_path / "usb"
    usb.mkdir()
    ext = usb / "PanePilot_Settings_2026-10-01a.zip"
    ext.write_bytes(a.read_bytes())
    imp = backup.import_backup(ext, folder)
    assert imp.name == ext.name and not backup.list_backups(folder)[-1].auto
    clash = usb / b.name
    clash.write_bytes(b.read_bytes())
    imp2 = backup.import_backup(clash, folder)
    assert imp2.name == "PanePilot_Settings_2026-11-07b.zip"
    other = usb / "irgendwas.zip"
    other.write_bytes(a.read_bytes())
    assert backup.import_backup(other, folder).name.startswith("PanePilot_Settings_")

    bad = usb / "kaputt.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("readme.txt", "x")
    try:
        backup.import_backup(bad, folder)
        raise AssertionError("ungültige Sicherung wurde importiert")
    except ValueError:
        pass

    assert backup.delete_backups([a]) == []
    assert not a.exists() and not (folder / f".{a.name}.auto").exists()


def test_auto_backup_failure_is_noted(window, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import backup

    window.settings.set("backup_dir", str(tmp_path / "sich"))
    window.settings.set("last_auto_backup", "")
    monkeypatch.setattr(backup, "folder_reachable", lambda folder, mounts=None: False)
    window.auto_backup()
    err = window.settings.get("backup_last_error")
    assert err["date"] == dt.date.today().isoformat() and "sich" in err["reason"]
    assert window.settings.get("last_auto_backup") == ""  # beim nächsten Start neuer Versuch
    monkeypatch.undo()
    window.auto_backup()
    assert window.settings.get("backup_last_error") == {}
    assert window.settings.get("last_auto_backup") == dt.date.today().isoformat()


def test_settings_backup_tab(window, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import backup
    from panepilot.settingsdialog import SettingsDialog

    folder = tmp_path / "sich"
    window.settings.set("backup_dir", str(folder))
    backup.create_backup(folder, auto=True)
    backup.create_backup(folder, auto=False)
    window.settings.set("backup_last_error", {"date": "2026-11-05", "reason": "Freigabe weg"})
    dlg = SettingsDialog(window)
    assert dlg.backup_list.topLevelItemCount() == 2
    assert "05.11.2026" in dlg.backup_error.text() and not dlg.backup_error.isHidden()
    assert dlg.backup_status.text() != ""
    assert not dlg.btn_restore.isEnabled() and not dlg.btn_backup_delete.isEnabled()
    dlg.backup_list.topLevelItem(0).setSelected(True)
    assert dlg.btn_restore.isEnabled() and dlg.btn_backup_delete.isEnabled()
    dlg.backup_list.topLevelItem(1).setSelected(True)
    assert not dlg.btn_restore.isEnabled() and dlg.btn_backup_delete.isEnabled()

    # Wiederherstellen der markierten Sicherung (ohne Neustart im Test)
    restored = []
    monkeypatch.setattr("panepilot.mainwindow.confirm", lambda *a, **k: True)
    monkeypatch.setattr(backup, "restore_backup", lambda p: restored.append(p))
    monkeypatch.setattr(window, "restart", lambda: None)
    dlg.backup_list.topLevelItem(1).setSelected(False)
    dlg._restore_selected()
    assert restored and restored[0].name == dlg.backup_list.topLevelItem(0).text(0)
    window.settings.frozen = False
    window._skip_save_state = False

    # Löschen nach Rückfrage
    monkeypatch.setattr("panepilot.settingsdialog.confirm", lambda *a, **k: True)
    dlg.backup_list.topLevelItem(0).setSelected(True)
    dlg.backup_list.topLevelItem(1).setSelected(True)
    dlg._delete_selected_backups()
    assert dlg.backup_list.topLevelItemCount() == 1  # die vor dem Wiederherstellen angelegte Sicherung
    dlg.deleteLater()


def test_backup_list_columns_resizable(window, tmp_path):  # noqa: F811
    from PySide6.QtWidgets import QHeaderView

    from panepilot import backup
    from panepilot.settingsdialog import SettingsDialog

    folder = tmp_path / "sich"
    window.settings.set("backup_dir", str(folder))
    backup.create_backup(folder, auto=True)
    dlg = SettingsDialog(window)
    header = dlg.backup_list.header()
    assert not header.stretchLastSection()
    for col in range(dlg.backup_list.columnCount()):
        assert header.sectionResizeMode(col) == QHeaderView.ResizeMode.Interactive
    other = header.sectionSize(1)
    header.resizeSection(0, 900)  # Name breiter ziehen: andere Spalten bleiben, Rollbalken statt Stauchen
    assert header.sectionSize(0) == 900 and header.sectionSize(1) == other
    dlg._refresh_backups()
    assert header.sectionSize(0) == 900  # Breiten bleiben nach dem Aktualisieren erhalten
    dlg.deleteLater()
