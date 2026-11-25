"""v3.0.1: Korrekturen aus dem ersten Windows-Test, Netzwerk unter Windows, Sicherung vom anderen System."""

import json
import sys
import zipfile

import pytest

WIN = sys.platform.startswith("win")
only_windows = pytest.mark.skipif(not WIN, reason="nur unter Windows")


def test_unc_helpers():  # L-4050
    from panepilot import winsys

    assert winsys.server_of("\\\\nas") == "nas"
    assert winsys.server_of("\\\\nas\\") == "nas"
    assert winsys.server_of("//nas") == "nas"
    assert winsys.server_of("\\\\nas\\Daten") is None
    assert winsys.server_of("C:\\") is None
    assert winsys.share_root("\\\\nas\\Daten\\Fotos\\2024") == "\\\\nas\\Daten"
    assert winsys.share_root("C:\\x") is None
    assert winsys.is_share_root("\\\\nas\\Daten\\")
    assert not winsys.is_share_root("\\\\nas\\Daten\\Fotos")
    assert winsys.server_path("nas") == "\\\\nas"


def test_filter_shares():  # L-4050
    from panepilot import winsys

    raw = [("Daten", 0), ("IPC$", 3 | 0x80000000), ("ADMIN$", 0x80000000), ("C$", 0x80000000),
           ("print", 1), ("Musik", 0), ("versteckt$", 0), ("Archiv", 0)]
    assert winsys.filter_shares(raw) == ["Archiv", "Daten", "Musik"]


def test_needs_login():  # L-4051
    from panepilot import winsys

    exc = OSError(13, "denied")
    exc.winerror = 1326  # type: ignore[attr-defined]
    assert winsys.needs_login(exc)
    assert winsys.needs_login(PermissionError(13, "x"))
    assert not winsys.needs_login(FileNotFoundError(2, "x"))


def test_unc_parent_and_share_entries():
    from panepilot import filemodel

    assert filemodel.unc_parent("\\\\nas\\Daten") == "\\\\nas"
    assert filemodel.unc_parent("\\\\nas\\Daten\\x") is None
    entries = filemodel.share_entries("\\\\nas", ["Daten", "Musik"])
    assert [e.path for e in entries] == ["\\\\nas\\Daten", "\\\\nas\\Musik"] and all(e.is_dir for e in entries)


def test_merge_servers(qapp):  # L-4052: jeder Server nur einmal
    from panepilot import netbrowse

    merged = netbrowse.merge(["nas", "\\\\Backup\\"], ["NAS", "PC-KUECHE", "backup"])
    assert merged == [("Backup", True), ("nas", True), ("PC-KUECHE", False)]
    from panepilot import winsys

    assert winsys.parse_discovered("NAS\r\n\r\nPC-1\r\nNetzwerk Gerät\r\n") == ["NAS", "PC-1"]


def test_server_list_settings(qapp):  # L-4052/L-4053
    from panepilot import netbrowse
    from panepilot.config import Settings

    s = Settings()
    ns = netbrowse.NetworkServers()
    ns.configure(s)
    s.set("net_servers", [])
    s.set("net_browse", True)
    ns.found = ["NAS"]
    assert ns.add("nas") and not ns.add("NAS")
    assert ns.servers() == [("nas", True)]
    ns.found = ["PC1"]
    s.set("net_browse", False)
    assert ns.servers() == [("nas", True)]
    ns.remove("NAS")
    assert ns.manual() == []


def _make_backup(path, origin, state):
    with zipfile.ZipFile(path, "w") as zf:
        if origin:
            zf.writestr(".panepilot-origin", origin)
        zf.writestr("settings.json", json.dumps({"language": "en", "backup_dir": "D:\\Sicherung",
                                                 "toolbar": ["back", "|", "forward"]}))
        zf.writestr("state.json", json.dumps(state))
        zf.writestr("keymap.json", json.dumps({"copy": ["F9"]}))
        zf.writestr("Favoriten/Standard.json", '{"version": 1, "items": [{"name": "fremd"}]}')
        zf.writestr("sync_profiles.json", "[]")


def test_backup_origin(tmp_path):  # L-4060
    from panepilot import backup

    a = tmp_path / "a.zip"
    _make_backup(a, "windows", {})
    assert backup.backup_origin(a) == "windows"
    b = tmp_path / "b.zip"
    _make_backup(b, "", {"left": {"path": "C:\\Users\\x"}})
    assert backup.backup_origin(b) == "windows"
    c = tmp_path / "c.zip"
    _make_backup(c, "", {"left": {"path": "/home/x"}})
    assert backup.backup_origin(c) == "linux"
    d = tmp_path / "d.zip"
    _make_backup(d, "", {})
    assert backup.backup_origin(d) == "" and not backup.is_foreign(d)
    assert backup.is_foreign(a) == (backup.origin_platform() != "windows")


def test_backup_records_origin(tmp_path):
    from panepilot import backup

    zp = backup.create_backup(tmp_path / "bk")
    with zipfile.ZipFile(zp) as zf:
        assert zf.read(".panepilot-origin").decode() == backup.origin_platform()


def test_restore_settings_only(tmp_path):  # L-4060
    from panepilot import backup
    from panepilot.config import config_dir

    cfg = config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "settings.json").write_text(json.dumps({"language": "de", "backup_dir": "/srv/sich"}), encoding="utf-8")
    (cfg / "state.json").write_text('{"left": {"path": "/home/x"}}', encoding="utf-8")
    (cfg / "Favoriten").mkdir(exist_ok=True)
    (cfg / "Favoriten" / "Standard.json").write_text('{"version": 1, "items": [{"name": "meins"}]}', encoding="utf-8")
    zp = tmp_path / "w.zip"
    _make_backup(zp, "windows", {"left": {"path": "C:\\Users\\x"}})
    backup.restore_settings_only(zp)
    cfg = config_dir()
    data = json.loads((cfg / "settings.json").read_text(encoding="utf-8"))
    assert data["language"] == "en" and data["toolbar"] == ["back", "|", "forward"]
    assert data["backup_dir"] == "/srv/sich"  # eigener Pfad bleibt
    assert "meins" in (cfg / "Favoriten" / "Standard.json").read_text(encoding="utf-8")
    assert "/home/x" in (cfg / "state.json").read_text(encoding="utf-8")
    assert json.loads((cfg / "keymap.json").read_text(encoding="utf-8")) == {"copy": ["F9"]}
    assert not (cfg / ".panepilot-origin").exists()
    assert not (cfg / "sync_profiles.json").exists()  # gab es hier nicht → bleibt weg


def test_restore_asks_for_foreign(qapp, tmp_path, monkeypatch):  # L-4060
    from panepilot import backup, dialogs
    from panepilot.mainwindow import MainWindow

    w = MainWindow()
    try:
        zp = tmp_path / "f.zip"
        _make_backup(zp, "windows" if not WIN else "linux", {})
        calls = []
        monkeypatch.setattr("panepilot.mainwindow.confirm", lambda *a, **k: True)
        monkeypatch.setattr(dialogs, "ask_yes_no_cancel", lambda *a, **k: calls.append("ask") or None)
        monkeypatch.setattr(backup, "restore_backup", lambda p: calls.append("full"))
        monkeypatch.setattr(backup, "restore_settings_only", lambda p: calls.append("only"))
        monkeypatch.setattr(w, "restart", lambda: calls.append("restart"))
        w.do_restore_backup(str(zp))
        assert calls == ["ask"]  # Abbrechen
        monkeypatch.setattr(dialogs, "ask_yes_no_cancel", lambda *a, **k: True)
        w.do_restore_backup(str(zp))
        assert calls[-2:] == ["only", "restart"]
        monkeypatch.setattr(dialogs, "ask_yes_no_cancel", lambda *a, **k: False)
        w.do_restore_backup(str(zp))
        assert calls[-2:] == ["full", "restart"]
    finally:
        w._skip_save_state = True
        w.close()


def test_trash_button_enabled():  # L-4040
    import panepilot.mainwindow as mw

    src = open(mw.__file__, encoding="utf-8").read()
    assert "trash_button.setEnabled(False)" not in src


def test_terminal_windows_start(monkeypatch, tmp_path):  # L-4041
    from panepilot import util

    started = []
    monkeypatch.setattr(util.sys, "platform", "win32")
    monkeypatch.setattr(util, "chosen_terminal", lambda f, c, x: ("cmd.exe", ["/K"]))
    monkeypatch.setattr(util, "start_console", lambda p, a, w: started.append((p, a, w)) or True)
    assert util.open_terminal(str(tmp_path), "cmd")
    assert started == [("cmd.exe", ["/K"], str(tmp_path))]


def test_wt_app_alias(monkeypatch, tmp_path):  # L-4041
    from panepilot import winsys

    apps = tmp_path / "Microsoft" / "WindowsApps"
    apps.mkdir(parents=True)
    (apps / "wt.exe").write_text("")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert winsys._app_alias("wt.exe") == str(apps / "wt.exe")
    assert winsys._app_alias("fehlt.exe") is None


# --- nur Windows -------------------------------------------------------------------------------------------------
@only_windows
def test_win_list_local_shares():
    import os

    from panepilot import winsys

    shares = winsys.list_shares(os.environ.get("COMPUTERNAME", "localhost"))
    assert isinstance(shares, list) and all(not s.endswith("$") for s in shares)


@only_windows
def test_win_terminal_console(tmp_path):
    import subprocess
    import time

    from panepilot import util

    marker = tmp_path / "ok.txt"
    assert util.start_console("cmd.exe", ["/C", f"echo ok> \"{marker}\""], str(tmp_path))
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.2)
    assert marker.exists()
    del subprocess


@only_windows
def test_win_panel_server_path(qapp, monkeypatch):
    import os

    from panepilot import winsys
    from panepilot.mainwindow import MainWindow

    monkeypatch.setattr(winsys, "list_shares", lambda server: ["Daten", "Musik"])
    w = MainWindow()
    try:
        panel = w.sides["left"].panel
        name = os.environ.get("COMPUTERNAME", "localhost")
        assert panel.navigate("\\\\" + name)
        names = [e.name for e in panel.model.entries()]
        assert names[:2] == ["Daten", "Musik"] or set(names) >= {"Daten", "Musik"}
        assert w.button_bar.trash_button.isEnabled()
    finally:
        w._skip_save_state = True
        w.close()
