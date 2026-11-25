"""v3.0: Windows-Version Teil 1 – Papierkorb, Öffnen mit, Laufwerke, Attribute, Passwörter, Terminal, Pfade.

Der erste Teil läuft überall (reine Hilfen), der zweite nur unter Windows (GitHub-Lauf „Windows“).
"""

import os
import struct
import sys

import pytest

WIN = sys.platform.startswith("win")
only_windows = pytest.mark.skipif(not WIN, reason="nur unter Windows")


# --- überall -----------------------------------------------------------------------------------------------------
def _info_v2(path: str, size: int, ft: int) -> bytes:
    raw = (path + "\x00").encode("utf-16-le")
    return struct.pack("<qqqI", 2, size, ft, len(path) + 1) + raw


def _info_v1(path: str, size: int, ft: int) -> bytes:
    raw = path.encode("utf-16-le").ljust(520, b"\x00")
    return struct.pack("<qqq", 1, size, ft) + raw


def test_parse_recycle_info():
    from panepilot import winsys

    ft = (1_700_000_000 + 11644473600) * 10_000_000
    for make in (_info_v1, _info_v2):
        info = winsys.parse_recycle_info(make("C:\\Users\\x\\Bericht.docx", 1234, ft))
        assert info.original == "C:\\Users\\x\\Bericht.docx" and info.size == 1234
        assert abs(info.deleted - 1_700_000_000) < 1
    assert winsys.parse_recycle_info(b"kurz") is None
    assert winsys.parse_recycle_info(struct.pack("<qqq", 9, 0, 0) + b"\x00" * 8) is None


def test_windows_trash_items(tmp_path, monkeypatch):  # L-4010
    from panepilot import trash, winsys

    bin_dir = tmp_path / "S-1-5-21-1"
    bin_dir.mkdir()
    (bin_dir / "$RAB12CD.txt").write_text("inhalt")
    (bin_dir / "$IAB12CD.txt").write_bytes(_info_v2("D:\\Daten\\notiz.txt", 6, 133_000_000_000_000_000))
    (bin_dir / "$RXY").mkdir()
    (bin_dir / "$IXY").write_bytes(_info_v2("D:\\Daten\\Ordner", 0, 133_000_000_000_000_000))
    (bin_dir / "desktop.ini").write_text("x")
    tr = trash.WindowsTrash(dirs_provider=lambda: [str(bin_dir)])
    assert not tr.is_empty()
    items = {i.name: i for i in tr.items()}
    assert set(items) == {"notiz.txt", "Ordner"}
    assert items["notiz.txt"].original_path == "D:\\Daten\\notiz.txt" and items["notiz.txt"].size == 6
    assert items["notiz.txt"].info_path.endswith("$IAB12CD.txt") and items["Ordner"].is_dir
    assert tr.item_for(items["notiz.txt"].file_path).name == "notiz.txt"
    assert trash.WindowsTrash(dirs_provider=lambda: []).is_empty()
    monkeypatch.setattr(sys, "platform", "win32")
    assert isinstance(trash.make_trash(), trash.WindowsTrash)
    assert winsys.filetime_to_ts(0) == 0.0


def test_attr_text_and_hidden(monkeypatch):  # L-4020–L-4022
    from panepilot import filemodel, winsys

    assert winsys.attr_text(winsys.READONLY | winsys.ARCHIVE) == "RA"
    assert winsys.attr_text(0x27) == "RHSA"
    assert winsys.is_protected_system(winsys.HIDDEN | winsys.SYSTEM)
    assert not winsys.is_protected_system(winsys.HIDDEN)
    monkeypatch.setattr(filemodel, "IS_WINDOWS", True)
    monkeypatch.setattr(filemodel, "SHOW_PROTECTED", False)
    assert filemodel.hidden_state("a.txt", winsys.HIDDEN) == (True, False)
    assert filemodel.hidden_state(".profil", 0) == (True, False)
    assert filemodel.hidden_state("NTUSER.DAT", winsys.HIDDEN | winsys.SYSTEM | winsys.ARCHIVE) == (True, True)
    assert not filemodel.visible("NTUSER.DAT", winsys.HIDDEN | winsys.SYSTEM, True)  # auch mit „versteckte“
    assert filemodel.visible("a.txt", winsys.HIDDEN, True) and not filemodel.visible("a.txt", winsys.HIDDEN, False)
    assert filemodel.visible("normal.txt", winsys.ARCHIVE, False)
    monkeypatch.setattr(filemodel, "SHOW_PROTECTED", True)
    assert filemodel.visible("NTUSER.DAT", winsys.HIDDEN | winsys.SYSTEM, True)
    assert not filemodel.visible("NTUSER.DAT", winsys.HIDDEN | winsys.SYSTEM, False)


def test_command_lines():  # L-4011, L-4024
    from panepilot import winsys

    assert winsys.split_command('"C:\\Program Files\\App\\a.exe" /x "%1"') == ["C:\\Program Files\\App\\a.exe", "/x",
                                                                              "%1"]
    calls = winsys.build_args('"C:\\P\\a.exe" "%1"', ["C:\\x y.txt", "C:\\z.txt"])
    assert calls == [["C:\\P\\a.exe", "C:\\x y.txt"], ["C:\\P\\a.exe", "C:\\z.txt"]]
    assert winsys.build_args("C:\\P\\b.exe", ["f"]) == [["C:\\P\\b.exe", "f"]]  # ohne Platzhalter: anhängen
    assert winsys.build_args('a.exe %1 %2', ["f"]) == [["a.exe", "f"]]
    assert winsys.build_args('a.exe %*', ["f", "g"]) == [["a.exe", "f", "g"]]
    assert winsys.web_path("C:\\a\\b") == "C:/a/b"
    custom = winsys.terminal_command("custom", "C:\\Daten", '"C:\\Git\\git-bash.exe" --cd={folder}')
    assert custom == ["C:\\Git\\git-bash.exe", "--cd=C:\\Daten"]
    assert winsys.terminal_command("cmd", "C:\\D")[:2] == ["cmd.exe", "/K"]
    assert winsys.terminal_command("custom", "x", "") is None


def test_linux_terminal_choice(monkeypatch, tmp_path):  # L-4024
    from panepilot import util

    if WIN:
        pytest.skip("Linux-Auswahl")
    assert util.terminal_choices() == util.TERMINAL_CHOICES_LINUX
    prog, args = util.chosen_terminal(str(tmp_path), "custom", "xterm -e 'cd {folder}'")
    assert prog == "xterm" and args == ["-e", f"cd {tmp_path}"]
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/konsole" if name == "konsole" else None)
    assert util.chosen_terminal("/x", "konsole") == ("/usr/bin/konsole", ["--workdir=/x"])
    assert util.chosen_terminal("/x", "gnome-terminal") is None


def test_settings_terminal(qapp):  # noqa: F811  L-4024
    from test_mainwindow import window as _w  # noqa: F401

    from panepilot.mainwindow import MainWindow
    from panepilot.settingsdialog import SettingsDialog

    w = MainWindow()
    try:
        dlg = SettingsDialog(w)
        assert dlg.terminal_choice["auto"].isChecked() and not dlg.terminal_custom.isEnabled()
        dlg.terminal_choice["custom"].setChecked(True)
        assert dlg.terminal_custom.isEnabled()
        dlg.terminal_custom.setText("mein-terminal {folder}")
        dlg.accept()
        assert w.settings.get("terminal") == "custom" and w.settings.get("terminal_custom") == "mein-terminal {folder}"
        calls = []
        import panepilot.util as util

        orig = util._start_detached
        util._start_detached = lambda prog, args, wd: calls.append((prog, args)) or True
        try:
            w.do_open_terminal(os.getcwd())
        finally:
            util._start_detached = orig
        assert calls == [("mein-terminal", [os.getcwd()])]
    finally:
        w.close()


def test_update_assets_for_windows():  # L-4005
    from panepilot import updatecheck as uc

    data = {"tag_name": "v3.0.0", "body": "", "html_url": "u", "assets": [
        {"name": "PanePilot-3.0.0-x86_64.AppImage", "browser_download_url": "a", "size": 1},
        {"name": "PanePilot-3.0.0-windows-x64-setup.exe", "browser_download_url": "s", "size": 2},
        {"name": "PanePilot-3.0.0-windows-x64.zip", "browser_download_url": "z", "size": 3}]}
    rel = uc.parse_release(data)
    assert rel.packages["winsetup"] == ("PanePilot-3.0.0-windows-x64-setup.exe", "s", 2)
    assert rel.packages["winzip"][1] == "z"


def test_package_marker(tmp_path, monkeypatch):
    from panepilot import installkind

    (tmp_path / "PACKAGE").write_text("winsetup")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "PanePilot.exe"))
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert installkind.package_format() == installkind.WINSETUP
    (tmp_path / "PACKAGE").write_text("winzip")
    assert installkind.package_format() == installkind.WINZIP


def test_columns_menu_per_platform(qapp, monkeypatch):  # L-4020
    from panepilot import filemodel
    from panepilot.filemodel import COL_ATTRS, COL_OWNER

    assert COL_ATTRS in filemodel.DEFAULT_HIDDEN and filemodel.COLUMN_COUNT == 12
    assert COL_ATTRS in filemodel.WINDOWS_ONLY_COLUMNS and COL_OWNER in filemodel.LINUX_ONLY_COLUMNS


def test_cache_base(monkeypatch):
    from panepilot import util

    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\x\\AppData\\Local")
    assert util.cache_base() == "C:\\Users\\x\\AppData\\Local"


# --- nur unter Windows -------------------------------------------------------------------------------------------
@only_windows
def test_win_credentials():  # L-4023
    from panepilot import servers as sv

    assert sv.keyring_available()
    assert sv.store_secret("pp-test-123", "geheim äöü", "Test")
    assert sv.load_secret("pp-test-123") == "geheim äöü"
    sv.delete_secret("pp-test-123")
    assert sv.load_secret("pp-test-123") is None


@only_windows
def test_win_attributes_and_paths(tmp_path):  # L-4020, L-4030
    from panepilot import filemodel, winsys

    folder = tmp_path / "attr"
    folder.mkdir()
    f = folder / "datei mit langem namen.txt"
    f.write_text("x")
    winsys.set_attrs(str(f), winsys.READONLY | winsys.HIDDEN)
    a = winsys.get_attrs(str(f))
    assert a & winsys.READONLY and a & winsys.HIDDEN
    entries = filemodel.scan_directory(str(folder), False, None)
    assert entries == []  # versteckt
    entries = filemodel.scan_directory(str(folder), True, None)
    assert entries[0].hidden and "R" in winsys.attr_text(entries[0].attrs)
    winsys.set_attrs(str(f), 0)
    assert not winsys.get_attrs(str(f)) & (winsys.READONLY | winsys.HIDDEN)
    short = winsys.short_path(str(f))
    assert os.path.exists(short)
    assert winsys.unc_path(str(f)) == str(f)  # lokal: bleibt
    assert winsys.user_sid().startswith("S-1-5-")
    assert any(d.root.upper().startswith("C:") for d in winsys.drives())


@only_windows
def test_win_recycle_bin_roundtrip(tmp_path):  # L-4010
    from PySide6.QtCore import QFile

    from panepilot import trash

    home = os.path.expanduser("~")
    target_dir = os.path.join(home, "pp-trash-test")
    os.makedirs(target_dir, exist_ok=True)
    path = os.path.join(target_dir, "weg.txt")
    with open(path, "w") as fh:
        fh.write("bitte wiederherstellen")
    assert QFile.moveToTrash(path)
    tr = trash.WindowsTrash()
    found = [i for i in tr.items() if i.original_path.lower() == path.lower()]
    assert found, [i.original_path for i in tr.items()]
    item = found[0]
    os.replace(item.file_path, item.original_path)  # wie „Wiederherstellen“
    os.unlink(item.info_path)
    with open(path) as fh:
        assert fh.read() == "bitte wiederherstellen"
    os.unlink(path)


@only_windows
def test_win_open_with_txt():  # L-4011
    from panepilot import winsys

    apps = winsys.apps_for("C:\\x\\test.txt")
    assert apps, "keine Programme für .txt gefunden"
    assert any("notepad" in (a.exe or a.command).lower() for a in apps)


@only_windows
def test_win_window_smoke(qapp, tmp_path):
    from panepilot.mainwindow import MainWindow
    from panepilot.propdialog import PropertiesDialog
    from panepilot.settingsdialog import SettingsDialog

    w = MainWindow()
    try:
        w.show()
        panel = w.sides["left"].panel
        assert panel.navigate("C:\\")
        assert panel.model.entries()
        w.do_open_trash()
        assert panel.in_trash
        dlg = SettingsDialog(w)
        assert "wt" in dlg.terminal_choice and hasattr(dlg, "show_protected")
        dlg.reject()
        f = tmp_path / "a.txt"
        f.write_text("x")
        props = PropertiesDialog(w, [str(f)])
        assert props.windows and props.tabs.tabText(1)
        props.attr_boxes[0x1].setChecked(True)
        props.apply_attributes()
        from panepilot import winsys

        assert winsys.get_attrs(str(f)) & winsys.READONLY
        winsys.set_attrs(str(f), 0)
        props.close()
    finally:
        w.close()
