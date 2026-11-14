"""Tests for 1.3: FTP/SFTP client (server list, connections, panels, transfers, FileZilla import)."""

import base64
import io
import os

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from test_mainwindow import window  # noqa: F401

pytest.importorskip("paramiko")
pytest.importorskip("pyftpdlib")

import remote_servers as R  # noqa: E402


@pytest.fixture(autouse=True)
def no_keyring(monkeypatch):
    monkeypatch.setenv("PANEPILOT_NO_KEYRING", "1")


@pytest.fixture
def server_root(tmp_path):
    root = tmp_path / "srv" / "root"
    (root / "Fotos" / "2026").mkdir(parents=True)
    (root / "Fotos" / "a.jpg").write_bytes(b"A" * 1000)
    (root / "Fotos" / "2026" / "b.jpg").write_bytes(b"B" * 2000)
    (root / "liesmich.txt").write_text("hallo")
    return root


@pytest.fixture(params=["ftp", "sftp"])
def server(request, server_root):
    from panepilot import remotefs as rf

    if request.param == "sftp":
        srv = R.SftpTestServer(str(server_root))
        cfg = rf.ServerConfig(name="Test-SFTP", protocol=rf.SFTP, host="127.0.0.1", port=srv.port, user=R.USER)
    else:
        srv = R.FtpTestServer(str(server_root))
        cfg = rf.ServerConfig(name="Test-FTP", protocol=rf.FTP, encryption=rf.ENC_NONE, host="127.0.0.1",
                              port=srv.port, user=R.USER)
    yield cfg, srv
    srv.close()


def _open(cfg):
    from panepilot import remotefs as rf

    try:
        return rf.Connection.open(cfg, R.PASSWORD)
    except rf.UnknownHostKey as exc:
        assert not exc.changed and exc.fingerprint.startswith("SHA256:")
        rf.trust_host_key(exc)
        return rf.Connection.open(cfg, R.PASSWORD)


# --- Grundlagen --------------------------------------------------------------------------------------------
def test_uri_and_defaults():
    from panepilot import remotefs as rf

    cfg = rf.ServerConfig(protocol=rf.FTP, encryption=rf.ENC_EXPLICIT, host="192.168.1.20", port=2221, user="alice")
    assert cfg.base_uri() == "ftps://alice@192.168.1.20:2221"
    assert rf.ServerConfig(protocol=rf.SFTP, host="nas", user="u").base_uri() == "sftp://u@nas"
    assert rf.ServerConfig(protocol=rf.FTP, encryption=rf.ENC_IMPLICIT, host="h").real_port() == 990
    assert rf.ServerConfig(protocol=rf.FTP, encryption=rf.ENC_NONE, logon=rf.LOGON_ANONYMOUS, host="h").base_uri() == \
        "ftp://anonymous@h"
    assert rf.split_uri("sftp://u@nas/Fotos/2026") == ("sftp://u@nas", "/Fotos/2026")
    assert rf.split_uri("sftp://u@nas") == ("sftp://u@nas", "/")
    assert rf.is_remote_uri("ftp://x") and not rf.is_remote_uri("/home")


def test_parse_list_lines():
    from panepilot.remotefs import parse_list_line

    d = parse_list_line("drwxr-xr-x    2 user group     4096 Nov 12 10:00 Mein Ordner")
    assert d.is_dir and d.name == "Mein Ordner"
    f = parse_list_line("-rw-r--r--    1 user group      123 Jan  3  2024 datei.txt")
    assert not f.is_dir and f.size == 123 and f.mode & 0o644 == 0o644
    link = parse_list_line("lrwxrwxrwx 1 u g 4 Jan 3 2024 sd -> /storage")
    assert link.is_link and link.name == "sd"
    win = parse_list_line("11-12-26  09:15PM       <DIR>          Bilder")
    assert win.is_dir and win.name == "Bilder"
    assert parse_list_line("total 12") is None


def test_server_store_roundtrip():
    from panepilot import remotefs as rf
    from panepilot import servers as sv

    store = sv.ServerStore()
    folder = sv.Node("NAS")
    store.root.children.append(folder)
    cfg = rf.ServerConfig(name="Phone", host="192.168.1.20", port=2221, user="alice")
    store.add(cfg, folder)
    store.save()
    raw = open(os.path.join(os.environ["PANEPILOT_CONFIG_DIR"], "Settings", "servers.json"), encoding="utf-8").read()
    assert "password" not in raw.lower() and "Phone" in raw
    again = sv.ServerStore()
    assert again.by_id(cfg.id).port == 2221 and again.root.children[0].name == "NAS"
    copy = again.duplicate(cfg.id)
    assert copy.name == "Phone (2)" and copy.id != cfg.id


FZ_XML = """<?xml version="1.0" encoding="UTF-8"?>
<FileZilla3><Servers>
  <Server><Host>192.168.1.20</Host><Port>2221</Port><Protocol>4</Protocol><Type>0</Type>
    <User>alice</User><Pass encoding="base64">{pw}</Pass><Logontype>1</Logontype>
    <PasvMode>MODE_DEFAULT</PasvMode><EncodingType>Auto</EncodingType><Name>Phone FTP</Name>
    <RemoteDir>1 0 7 Android 4 data</RemoteDir>Phone FTP</Server>
  <Folder expanded="1">Phones
    <Server><Host>nas</Host><Port>22</Port><Protocol>1</Protocol><User>root</User><Logontype>2</Logontype>
      <Name>NAS</Name><Colour>2</Colour>NAS</Server>
  </Folder>
</Servers></FileZilla3>
"""


def test_filezilla_import(tmp_path, monkeypatch):
    from panepilot import remotefs as rf
    from panepilot import servers as sv

    cfg_home = tmp_path / "xdg"
    (cfg_home / "filezilla").mkdir(parents=True)
    (cfg_home / "filezilla" / "sitemanager.xml").write_text(
        FZ_XML.format(pw=base64.b64encode(b"geheim").decode()), encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg_home))
    items = sv.parse_filezilla(sv.filezilla_file())
    poco, nas = items
    assert poco.cfg.protocol == rf.FTP and poco.cfg.encryption == rf.ENC_EXPLICIT and poco.cfg.port == 2221
    assert poco.password == "geheim" and poco.cfg.remote_dir == "/Android/data" and poco.folder == []
    assert nas.cfg.protocol == rf.SFTP and nas.cfg.port == 0 and nas.cfg.logon == rf.LOGON_ASK
    assert nas.folder == ["Phones"] and nas.cfg.color
    store = sv.ServerStore()
    assert sv.import_servers(store, items) == (2, 0, 1)  # ohne Schlüsselbund: Passwort nicht gespeichert
    assert sv.import_servers(store, items) == (0, 2, 0)  # schon da → übersprungen
    assert [n.name for n in store.root.children] == ["Phone FTP", "Phones"]


# --- Verbindungen ------------------------------------------------------------------------------------------
def test_connection_basics(server, server_root):
    from panepilot import remotefs as rf

    cfg, _srv = server
    conn = _open(cfg)
    try:
        names = {i.name: i for i in conn.listdir("/")}
        assert names["Fotos"].is_dir and names["liesmich.txt"].size == 5
        buf = io.BytesIO()
        conn.download("/liesmich.txt", buf)
        assert buf.getvalue() == b"hallo"
        conn.upload(io.BytesIO(b"neu"), "/neu.txt")
        conn.set_mtime("/neu.txt", 1_000_000_000)
        assert (server_root / "neu.txt").read_bytes() == b"neu"
        assert int(os.path.getmtime(server_root / "neu.txt")) == 1_000_000_000
        conn.makedirs("/x/y")
        conn.rename("/x", "/z")
        conn.remove_tree("/z")
        assert not (server_root / "z").exists()
        with pytest.raises(rf.RemoteError):
            conn.listdir("/gibtsnicht")
    finally:
        conn.close()
    with pytest.raises(rf.AuthFailed):
        rf.Connection.open(cfg, "falsch")


def test_sftp_host_key_change(server_root):
    import paramiko

    from panepilot import remotefs as rf

    srv = R.SftpTestServer(str(server_root))
    cfg = rf.ServerConfig(name="s", protocol=rf.SFTP, host="127.0.0.1", port=srv.port, user=R.USER)
    try:
        _open(cfg).close()
        _open(cfg).close()  # jetzt bekannt → keine Rückfrage
        # anderer Schlüssel für denselben Server in known_hosts → „geändert“
        keys = paramiko.HostKeys(str(rf.known_hosts_file()))
        entry = f"[127.0.0.1]:{srv.port}"
        del keys[entry]
        fake = paramiko.RSAKey.generate(2048)
        keys.add(entry, fake.get_name(), fake)
        keys.save(str(rf.known_hosts_file()))
        with pytest.raises(rf.UnknownHostKey) as info:
            rf.Connection.open(cfg, R.PASSWORD)
        assert info.value.changed
        rf.trust_host_key(info.value)
        rf.Connection.open(cfg, R.PASSWORD).close()
    finally:
        srv.close()


def test_ftps_self_signed(server_root, tmp_path):
    pytest.importorskip("OpenSSL")
    from panepilot import remotefs as rf

    srv = R.FtpTestServer(str(server_root), tls=True, certfile=R.make_cert(str(tmp_path)))
    cfg = rf.ServerConfig(name="Handy", protocol=rf.FTP, encryption=rf.ENC_EXPLICIT, host="127.0.0.1",
                          port=srv.port, user=R.USER)
    try:
        with pytest.raises(rf.UnknownCertificate) as info:
            rf.Connection.open(cfg, R.PASSWORD)
        rf.trust_certificate(info.value.host, info.value.fingerprint)
        conn = rf.Connection.open(cfg, R.PASSWORD)
        buf = io.BytesIO()
        conn.download("/liesmich.txt", buf)  # Datenverbindung mit TLS
        assert buf.getvalue() == b"hallo"
        conn.close()
    finally:
        srv.close()


# --- Hauptfenster ----------------------------------------------------------------------------------------
def _connect(window, cfg, side="left", monkeypatch=None):  # noqa: F811
    from panepilot import remotefs as rf
    from panepilot import serverui

    window.server_store.add(cfg)
    window.server_store.save()
    monkeypatch.setattr(serverui.PasswordDialog, "exec",
                        lambda dlg: dlg.edit.setText(R.PASSWORD) or QDialog.DialogCode.Accepted)

    def trust(_parent, err):
        assert isinstance(err, (rf.UnknownHostKey, rf.UnknownCertificate))
        return True
    monkeypatch.setattr(serverui, "confirm_host_key", trust)

    def fail(_parent, title, text):
        raise AssertionError(f"{title}: {text}")
    monkeypatch.setattr("panepilot.remotecontrol.show_error", fail)
    monkeypatch.setattr("panepilot.remotecontrol.confirm", lambda _p, title, text, **k: fail(_p, title, text))
    assert window.remote_connect(side, cfg.id)
    return window.sides[side].panel


def _wait_transfers(window, qtbot):
    qtbot.waitUntil(lambda: window._transfers is not None and not window.transfers.busy(), timeout=15000)
    QApplication.processEvents()


def test_connect_browse_and_disconnect(window, server, qtbot, monkeypatch, tmp_path):  # noqa: F811
    cfg, _srv = server
    window.set_sidebar_mode("left", "servers")
    window.sides["left"].panel.navigate(str(tmp_path))
    panel = _connect(window, cfg, monkeypatch=monkeypatch)
    assert panel.in_remote and panel.current_path == cfg.base_uri() + "/"
    assert panel.path_edit.text() == cfg.base_uri() + "/"
    names = [e.name for e in panel.model.entries()]
    assert names == ["Fotos", "liesmich.txt"]
    assert window.server_models["left"].connected == {cfg.id}
    # in Unterordner und zurück
    panel.open_entry(next(e for e in panel.model.entries() if e.name == "Fotos"))
    assert panel.current_path.endswith("/Fotos") and panel.model.entries()[0].is_parent
    panel.go_up()
    assert panel.current_path == cfg.base_uri() + "/"
    # gesperrte Funktion
    infos = []
    monkeypatch.setattr("panepilot.mainwindow.show_info", lambda *a: infos.append(a[2]))
    window.trigger("search")
    assert infos == ["Das geht auf dem Server nicht."]
    # Zurück bis vor den Server → Verbindung endet, Verlauf ohne Server
    for _i in range(3):  # Verlauf: lokal, Server, Fotos, Server
        panel.back()
    assert not panel.in_remote and panel.remote is None and panel.current_path == str(tmp_path)
    assert not any(h.startswith(cfg.base_uri()) for h in panel.history_state()[0])
    assert window.server_models["left"].connected == set() and not window.remote_sessions


def test_new_folder_rename_delete(window, server, server_root, qtbot, monkeypatch):  # noqa: F811
    cfg, _srv = server
    panel = _connect(window, cfg, monkeypatch=monkeypatch)
    monkeypatch.setattr("panepilot.mainwindow.ask_text", lambda *a, **k: "Neu")
    window.trigger("new_folder")
    assert (server_root / "Neu").is_dir() and panel.current_entry().name == "Neu"
    row = panel.model.row_of("Neu")
    assert panel.model.setData(panel.model.index(row, 0), "Umbenannt")
    assert (server_root / "Umbenannt").is_dir() and not (server_root / "Neu").exists()
    asked = []
    monkeypatch.setattr("panepilot.remotecontrol.confirm", lambda *a, **k: asked.append(a[2]) or True)
    panel.select_names(["Umbenannt", "liesmich.txt"])
    window.trigger("delete")  # auf dem Server immer endgültig
    assert asked and "keinen Papierkorb" in asked[0]
    assert not (server_root / "Umbenannt").exists() and not (server_root / "liesmich.txt").exists()
    assert [e.name for e in panel.model.entries()] == ["Fotos"]


def test_download_upload_queue(window, server, server_root, qtbot, monkeypatch, tmp_path):  # noqa: F811
    cfg, _srv = server
    local = tmp_path / "lokal"
    local.mkdir()
    (local / "hoch.txt").write_text("hoch")
    (local / "Ordner").mkdir()
    (local / "Ordner" / "drin.txt").write_text("drin")
    window.settings.set("confirm_copy_move", False)
    window.sides["right"].panel.navigate(str(local))
    panel = _connect(window, cfg, monkeypatch=monkeypatch)
    window.set_active_side("left")
    panel.select_names(["Fotos"])
    window.trigger("copy")  # F5: herunterladen
    _wait_transfers(window, qtbot)
    assert (local / "Fotos" / "a.jpg").read_bytes() == b"A" * 1000
    assert (local / "Fotos" / "2026" / "b.jpg").stat().st_size == 2000
    win = window.transfers.window
    assert win is not None and win.isVisible()
    rows = window.transfers.model.rows
    assert [os.path.basename(r.src) for r in rows] == ["Fotos", "2026", "b.jpg", "a.jpg"]
    assert all(r.status == "done" for r in rows)
    assert "Dateien 2 von 2" in win.summary.text()
    # hochladen und verschieben (Quelle wird erst nach Erfolg gelöscht)
    right = window.sides["right"].panel
    right.refresh()
    window.set_active_side("right")
    right.select_names(["hoch.txt", "Ordner"])
    window.trigger("move")
    _wait_transfers(window, qtbot)
    assert (server_root / "hoch.txt").read_text() == "hoch"
    assert (server_root / "Ordner" / "drin.txt").read_text() == "drin"
    assert not (local / "hoch.txt").exists() and not (local / "Ordner").exists()
    qtbot.waitUntil(lambda: panel.model.row_of("hoch.txt") >= 0, timeout=3000)


def test_conflict_and_retry(window, server, server_root, qtbot, monkeypatch, tmp_path):  # noqa: F811
    from panepilot import dialogs

    cfg, _srv = server
    local = tmp_path / "ziel"
    local.mkdir()
    (local / "liesmich.txt").write_text("alt")
    window.settings.set("confirm_copy_move", False)
    window.sides["right"].panel.navigate(str(local))
    panel = _connect(window, cfg, monkeypatch=monkeypatch)
    asked = []

    class FakeConflict:
        def __init__(self, parent, src, dst, same, suggestion, **kw):
            asked.append((os.path.basename(dst), kw.get("dst_info", "")))
            self.decision = dialogs.ConflictDecision("rename", "liesmich (neu).txt")

        def exec(self):
            return 1
    monkeypatch.setattr(dialogs, "ConflictDialog", FakeConflict)
    window.set_active_side("left")
    panel.select_names(["liesmich.txt"])
    window.trigger("copy")
    _wait_transfers(window, qtbot)
    assert asked and asked[0][0] == "liesmich.txt" and asked[0][1].startswith("3 B")
    assert (local / "liesmich.txt").read_text() == "alt"
    assert (local / "liesmich (neu).txt").read_text() == "hallo"
    # Fehler → erneut versuchen
    from panepilot.transfers import ERROR

    (server_root / "liesmich.txt").unlink()
    (local / "liesmich (neu).txt").unlink()
    (local / "liesmich.txt").unlink()
    panel.select_names(["liesmich.txt"])
    window.trigger("copy")
    _wait_transfers(window, qtbot)
    failed = [r for r in window.transfers.model.rows if r.status == ERROR]
    assert failed and window.transfers.window.btn_retry.isEnabled()
    assert "1 Fehler" in window.transfers.window.summary.text()
    (server_root / "liesmich.txt").write_text("wieder da")
    window.transfers.window._retry()
    _wait_transfers(window, qtbot)
    assert (local / "liesmich.txt").read_text() == "wieder da"


def test_drag_between_panels(window, server, server_root, qtbot, monkeypatch, tmp_path):  # noqa: F811
    from panepilot.filemodel import REMOTE_MIME

    cfg, _srv = server
    local = tmp_path / "drop"
    local.mkdir()
    window.sides["right"].panel.navigate(str(local))
    panel = _connect(window, cfg, monkeypatch=monkeypatch)
    row = panel.model.row_of("liesmich.txt")
    md = panel.model.mimeData([panel.model.index(row, 0)])
    assert md.hasFormat(REMOTE_MIME) and not md.hasUrls()
    import json

    payload = json.loads(bytes(md.data(REMOTE_MIME)).decode())
    window.remote_drop_from_server(payload, str(local), Qt.DropAction.CopyAction)
    _wait_transfers(window, qtbot)
    assert (local / "liesmich.txt").read_text() == "hallo"
    (local / "neu.bin").write_bytes(b"\0" * 10)
    window._on_drop([str(local / "neu.bin")], cfg.base_uri() + "/Fotos", Qt.DropAction.CopyAction)
    _wait_transfers(window, qtbot)
    assert (server_root / "Fotos" / "neu.bin").stat().st_size == 10


def test_open_remote_file(window, server, qtbot, monkeypatch):  # noqa: F811
    cfg, _srv = server
    panel = _connect(window, cfg, monkeypatch=monkeypatch)
    opened = []
    monkeypatch.setattr("panepilot.util.open_with_default_app", lambda p: opened.append(p) or True)
    panel.open_entry(next(e for e in panel.model.entries() if e.name == "liesmich.txt"))
    assert opened and open(opened[0]).read() == "hallo" and "PanePilot-" in opened[0]


def test_save_state_skips_server(window, server, monkeypatch, tmp_path):  # noqa: F811
    import json

    cfg, _srv = server
    window.sides["left"].panel.navigate(str(tmp_path))
    _connect(window, cfg, monkeypatch=monkeypatch)
    window.save_state()
    state = json.load(open(os.path.join(os.environ["PANEPILOT_CONFIG_DIR"], "Settings", "state.json")))
    left = state["sides"]["left"]
    assert left["path"] == str(tmp_path)
    assert not any("://" in h for h in left["history"])


def test_server_manager_dialog(window, monkeypatch):  # noqa: F811
    from panepilot import remotefs as rf
    from panepilot.serverui import ServerManagerDialog

    dlg = ServerManagerDialog(window, window.server_store, window.icons.folder())
    monkeypatch.setattr("panepilot.dialogs.ask_text", lambda *a, **k: "NAS")
    dlg.new_server()
    assert dlg.current is not None and dlg.current.name == "NAS"
    dlg.f_protocol.setCurrentIndex(dlg.f_protocol.findData(rf.SFTP))
    assert not dlg.f_encryption.isEnabled()
    assert dlg.f_logon.findData(rf.LOGON_KEY) >= 0 and dlg.f_logon.findData(rf.LOGON_ANONYMOUS) < 0
    dlg.f_host.setText("192.168.1.10")
    dlg.f_user.setText("alice")
    dlg._set_color("#C8E6C9")
    dlg._finish(QDialog.DialogCode.Accepted)
    store = window.server_store
    cfg = store.servers()[0]
    assert (cfg.name, cfg.protocol, cfg.host, cfg.user, cfg.color) == ("NAS", rf.SFTP, "192.168.1.10", "alice",
                                                                       "#C8E6C9")
    assert cfg.base_uri() == "sftp://alice@192.168.1.10"


def test_server_sidebar_menu_and_switch(window):  # noqa: F811
    from panepilot import remotefs as rf

    window.server_store.add(rf.ServerConfig(name="Eins", host="h"))
    window.server_store.save()
    window.set_sidebar_mode("right", "servers")
    view = window.server_view("right")
    assert view is not None
    model = window.server_models["right"]
    assert model.rowCount() == 1 and model.item(0).text() == "Eins"
    window._server_copy(window.server_store.servers()[0].id)
    assert [model.item(r).text() for r in range(model.rowCount())] == ["Eins", "Eins (2)"]
    # Umsortieren mit der Maus: Modell → Speicher
    model.insertRow(0, model.takeRow(1))
    window._server_tree_dropped(model)
    assert [s.name for s in window.server_store.servers()] == ["Eins (2)", "Eins"]


def test_settings_import_button(window, monkeypatch, tmp_path):  # noqa: F811
    from panepilot.settingsdialog import SettingsDialog

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "leer"))
    infos = []
    monkeypatch.setattr("panepilot.remotecontrol.show_info", lambda *a: infos.append(a[2]))
    dlg = SettingsDialog(window)
    dlg.btn_filezilla.click()
    assert infos and "sitemanager.xml" in infos[0]
    dlg.reject()


def test_keyring_with_fake_secret_service(monkeypatch):
    """Passwörter landen im Schlüsselbund (hier ein nachgebauter Secret Service)."""
    import sys
    import types

    from panepilot import servers as sv

    store: dict = {}

    class Item:
        def __init__(self, attrs, secret):
            self.attrs, self.secret = attrs, secret

        def get_secret(self):
            return self.secret

        def delete(self):
            store.pop(tuple(sorted(self.attrs.items())))

    class Col:
        def is_locked(self):
            return False

        def create_item(self, label, attrs, secret, replace=True):
            store[tuple(sorted(attrs.items()))] = Item(attrs, secret)

        def search_items(self, attrs):
            return [v for k, v in store.items() if dict(k).items() >= attrs.items()]

    class Conn:
        def close(self):
            pass

    fake = types.SimpleNamespace(dbus_init=lambda: Conn(), get_default_collection=lambda conn: Col())
    monkeypatch.setitem(sys.modules, "secretstorage", fake)
    monkeypatch.delenv("PANEPILOT_NO_KEYRING")
    monkeypatch.setattr(sv._Keyring, "available", None)
    assert sv.keyring_available()
    assert sv.store_secret("id1", "geheim", "Phone")
    assert sv.load_secret("id1") == "geheim" and sv.load_secret("id1", "passphrase") is None
    sv.delete_secret("id1")
    assert sv.load_secret("id1") is None
    monkeypatch.setattr(sv._Keyring, "available", None)


def test_wait_dialog_never_reappears(window, server, qtbot, monkeypatch):  # noqa: F811
    """1.3.1: Nach Ende der Abfrage taucht kein Wartefenster mehr auf (auch keins, das noch nicht zu sehen war)."""
    import time

    from panepilot.dialogs import WaitDialog
    from panepilot.remotecontrol import run_task

    cfg, _srv = server
    panel = _connect(window, cfg, monkeypatch=monkeypatch)
    panel.open_entry(next(e for e in panel.model.entries() if e.name == "Fotos"))
    value, error, cancelled = run_task(window, lambda: time.sleep(0.6) or 42, "x")
    assert (value, error, cancelled) == (42, None, False)
    qtbot.wait(700)
    assert not [d for d in window.findChildren(WaitDialog) if d.isVisible()]
    # Abbrechen wirkt sofort
    dlg = WaitDialog(window, "t", "x", delay=0)
    hits = []
    dlg.canceled.connect(lambda: hits.append(1))
    qtbot.wait(50)
    assert dlg.isVisible()
    dlg.btn_cancel.click()
    assert hits == [1] and dlg.wasCanceled()
    dlg.finish()
    qtbot.wait(50)
    import shiboken6

    assert not shiboken6.isValid(dlg) or not dlg.isVisible()
