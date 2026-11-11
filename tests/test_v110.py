"""Tests for 1.1: open terminal here, directory listing, UI scaling, application-menu integration."""

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog

from test_mainwindow import window  # noqa: F401

linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux")


def _exe(path, text="#!/bin/sh\n"):
    path.write_text(text)
    path.chmod(0o755)
    return path


# --- Terminal (L-100 ff.) ---------------------------------------------------------------------------
@linux
def test_terminal_command_debian_alternative(tmp_path, monkeypatch):
    from panepilot import util

    bin_ = tmp_path / "bin"
    bin_.mkdir()
    _exe(bin_ / "gnome-terminal")
    wrapper = _exe(bin_ / "gnome-terminal.wrapper")
    os.symlink(wrapper, bin_ / "x-terminal-emulator")
    monkeypatch.setenv("PATH", str(bin_))
    program, args = util.terminal_command("/data/Musik")
    # Debians Wrapper versteht keine --working-directory → gnome-terminal direkt
    assert program == str(bin_ / "gnome-terminal")
    assert args == ["--working-directory=/data/Musik"]


@linux
def test_terminal_command_fallbacks(tmp_path, monkeypatch):
    from panepilot import util

    bin_ = tmp_path / "bin"
    bin_.mkdir()
    monkeypatch.setenv("PATH", str(bin_))
    assert util.terminal_command("/x") is None
    _exe(bin_ / "konsole")
    assert util.terminal_command("/x") == (str(bin_ / "konsole"), ["--workdir=/x"])


@linux
def test_open_terminal_starts_in_folder(tmp_path, monkeypatch, qtbot):
    from panepilot import util

    bin_ = tmp_path / "bin"
    bin_.mkdir()
    out = tmp_path / "out.txt"
    _exe(bin_ / "x-terminal-emulator", f'#!/bin/sh\npwd > "{out}"\necho "$APPIMAGE" >> "{out}"\n')
    monkeypatch.setenv("PATH", f"{bin_}:/usr/bin:/bin")
    monkeypatch.setenv("APPIMAGE", "/should/not/leak")
    folder = tmp_path / "Ordner mit Leerzeichen"
    folder.mkdir()
    assert util.open_terminal(str(folder))
    qtbot.waitUntil(lambda: out.exists() and out.read_text().count("\n") >= 2, timeout=5000)
    lines = out.read_text().splitlines()
    assert lines[0] == str(folder) and lines[1] == ""


def test_open_terminal_action_uses_current_folder(window, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import util

    calls = []
    monkeypatch.setattr(util, "open_terminal", lambda f: calls.append(f) or True)
    window.active.navigate(str(tmp_path))
    QApplication.processEvents()
    window.trigger("open_terminal")
    window.do_open_terminal(str(tmp_path / "x"))
    assert calls == [str(tmp_path), str(tmp_path / "x")]


# --- Verzeichnisliste (L-110 ff.) ---------------------------------------------------------------------
@pytest.fixture
def music(tmp_path):
    root = tmp_path / "Musik"
    (root / "Album - Sample Band" / "CD1").mkdir(parents=True)
    (root / "Album - Sample Band" / "01 Morning Light.mp3").write_bytes(b"x" * 8000)
    (root / "Album - Sample Band" / "CD1" / "tief.flac").write_bytes(b"y" * 2000)
    (root / "a.txt").write_bytes(b"z" * 10)
    (root / ".versteckt").write_bytes(b"h" * 5)
    return root


def test_scan_and_render(music):
    from panepilot import dirlist

    node = dirlist.scan(str(music))
    assert node.size == 10010  # versteckte Dateien zählen nicht
    text = dirlist.render(node, lambda n: f"{n} B", "%Y", header=["H"])
    lines = text.splitlines()
    assert lines[0] == "H"
    expected = ["Musik/", "    Album - Sample Band/", "        CD1/", "            tief.flac",
                "        01 Morning Light.mp3", "    a.txt"]  # Ordner zuerst, eingerückt
    assert len(lines) == 1 + len(expected)
    for ln, name in zip(lines[1:], expected):
        assert ln.startswith(name + " "), (ln, name)
    # Größe und Datum stehen in allen Zeilen untereinander (Spalten ausgerichtet)
    ends = {ln.rindex(" B") for ln in lines[1:]}
    assert len(ends) == 1


def test_scan_options(music):
    from panepilot import dirlist

    node = dirlist.scan(str(music), files=False, depth=1)
    assert [c.name for c in node.children] == ["Album - Sample Band"]
    assert node.children[0].children == []  # Tiefe 1
    assert node.children[0].size == 10000  # Größe zählt trotzdem alles darunter
    node = dirlist.scan(str(music), hidden=True)
    assert ".versteckt" in [c.name for c in node.children]


def test_next_free_name(tmp_path):
    import datetime as dt

    from panepilot import dirlist

    day = dt.date(2026, 11, 11)
    assert dirlist.next_free_name(str(tmp_path), "Verzeichnisliste_Musik", day) == \
        "Verzeichnisliste_Musik_2026-11-11a.txt"
    (tmp_path / "Verzeichnisliste_Musik_2026-11-11a.txt").write_text("")
    assert dirlist.next_free_name(str(tmp_path), "Verzeichnisliste_Musik", day).endswith("11b.txt")


def test_dir_list_from_window(window, music, monkeypatch):  # noqa: F811
    from panepilot import dirlist, util

    opened = []
    monkeypatch.setattr(dirlist, "options_dialog",
                        lambda parent, folder, settings: {"files": True, "depth": 0, "hidden": False, "open": True})
    seen = {}

    def fake_save(parent, title, path, filt):
        seen["path"] = path
        return path, filt
    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save)
    monkeypatch.setattr(util, "open_with_default_app", lambda p: opened.append(p) or True)
    window.active.navigate(str(music))
    QApplication.processEvents()
    window.trigger("dir_list")
    assert os.path.basename(seen["path"]).startswith("Verzeichnisliste_Musik_")
    text = open(seen["path"], encoding="utf-8").read()
    assert text.startswith(f"Verzeichnisliste: {music}\nErstellt: ")
    assert "    Album - Sample Band/" in text and "01 Morning Light.mp3" in text
    assert opened == [seen["path"]]


# --- Skalierung (L-120 ff.) ---------------------------------------------------------------------------
def test_apply_ui_scale_and_child_env(monkeypatch):
    from panepilot import util

    monkeypatch.delenv("QT_SCALE_FACTOR", raising=False)
    monkeypatch.setattr(util, "SCALE_ENV_SET_BY_US", False)
    monkeypatch.setattr(util, "ORIGINAL_QT_SCALE", None)
    util.apply_ui_scale(100)
    assert "QT_SCALE_FACTOR" not in os.environ
    util.apply_ui_scale(150)
    assert os.environ["QT_SCALE_FACTOR"] == "1.5"
    assert not util.child_environment().contains("QT_SCALE_FACTOR")  # gestartete Programme unverändert
    util.apply_ui_scale(33)  # ungültig → ignoriert
    assert os.environ["QT_SCALE_FACTOR"] == "1.5"
    monkeypatch.delenv("QT_SCALE_FACTOR")


def test_settings_scale_asks_restart(window, monkeypatch):  # noqa: F811
    from panepilot.settingsdialog import SettingsDialog

    asked, restarted = [], []
    monkeypatch.setattr("panepilot.settingsdialog.confirm", lambda *a, **k: asked.append(k) or True)
    monkeypatch.setattr(window, "restart", lambda: restarted.append(1))
    dlg = SettingsDialog(window)
    assert dlg.scale_value() == 100 and dlg.scale_label.text() == "100 %"
    dlg.scale_slider.setValue(dlg.scale_slider.value() + 2)
    assert dlg.scale_label.text() == "150 %"
    dlg.accept()
    assert window.settings.get("ui_scale") == 150
    assert asked and asked[0]["no_key"] == "donate.later" and restarted == [1]
    # unverändert → keine Frage
    asked.clear()
    SettingsDialog(window).accept()
    assert asked == []


# --- Anwendungsmenü (L-130 ff.) ------------------------------------------------------------------------
@pytest.fixture
def data_home(tmp_path, monkeypatch):
    home = tmp_path / "share"
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    app = tmp_path / "Versionen" / "PanePilot-1.1.0-x86_64.AppImage"
    app.parent.mkdir()
    app.write_bytes(b"\x7fELF")
    monkeypatch.setenv("APPIMAGE", str(app))
    return home, app


def test_integrate_update_remove(data_home):
    from panepilot import desktopint

    home, app = data_home
    assert not desktopint.is_integrated()
    (home / "applications").mkdir(parents=True)
    (home / "applications" / "PanePilot_alt.desktop").write_text("[Desktop Entry]\nExec=/x/PanePilot.AppImage\n")
    desktopint.integrate()
    entry = (home / "applications" / "panepilot.desktop").read_text()
    assert f'Exec="{app}" %U' in entry and "Icon=panepilot" in entry and desktopint.is_integrated()
    assert (home / "icons" / "hicolor" / "scalable" / "apps" / "panepilot.svg").exists()
    assert [p.name for p in desktopint.other_launchers()] == ["PanePilot_alt.desktop"]
    # neue Version gestartet → Starter wird nachgeführt
    assert not desktopint.update_if_moved()
    newer = app.parent / "PanePilot-1.2.0-x86_64.AppImage"
    newer.write_bytes(b"\x7fELF")
    os.environ["APPIMAGE"] = str(newer)
    assert desktopint.update_if_moved()
    assert "PanePilot-1.2.0" in (home / "applications" / "panepilot.desktop").read_text()
    desktopint.remove()
    assert not desktopint.is_integrated()
    assert not (home / "icons" / "hicolor" / "scalable" / "apps" / "panepilot.svg").exists()


def test_quote_special_paths():
    from panepilot import desktopint

    assert desktopint._quote('/a b/$x"y') == '"/a b/\\$x\\"y"'


def test_settings_menu_button(window, data_home, monkeypatch):  # noqa: F811
    from panepilot import desktopint
    from panepilot.settingsdialog import SettingsDialog

    infos = []
    monkeypatch.setattr("panepilot.dialogs.show_info", lambda *a, **k: infos.append(a[2]))
    dlg = SettingsDialog(window)
    assert dlg.menu_button.isEnabled() and dlg.menu_button.text() == "Ins Anwendungsmenü aufnehmen"
    dlg.menu_button.click()
    assert desktopint.is_integrated() and infos
    assert dlg.menu_button.text() == "Aus dem Anwendungsmenü entfernen"
    dlg.menu_button.click()
    assert not desktopint.is_integrated()
    monkeypatch.delenv("APPIMAGE")
    dlg2 = SettingsDialog(window)
    assert not dlg2.menu_button.isEnabled()
    dlg.reject()
    dlg2.reject()


def test_menus_contain_new_actions(window):  # noqa: F811
    file_menu = window.settings_menu.parentWidget()
    texts = [a.text() for a in file_menu.actions()]
    assert window.qactions["open_terminal"].text() in texts
    assert window.qactions["dir_list"].text() in texts
