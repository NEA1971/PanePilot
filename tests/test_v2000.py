"""Tests for 2.0: .deb/.rpm packages – install kind, updater, settings, about."""

import os
import sys

from test_mainwindow import window  # noqa: F401


def _fake_package(monkeypatch, tmp_path, fmt):
    exe_dir = tmp_path / "opt" / "panepilot"
    exe_dir.mkdir(parents=True)
    (exe_dir / "PACKAGE").write_text(fmt + "\n")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "PanePilot"))
    monkeypatch.delenv("APPIMAGE", raising=False)


def test_install_kind(monkeypatch, tmp_path):
    from panepilot import installkind as ik

    monkeypatch.delenv("APPIMAGE", raising=False)
    assert ik.package_format() is None and ik.kind() in (ik.SOURCE, ik.FROZEN)
    monkeypatch.setenv("APPIMAGE", "/x/PanePilot.AppImage")
    assert ik.kind() == ik.APPIMAGE
    _fake_package(monkeypatch, tmp_path, "deb")
    assert ik.package_format() == "deb" and ik.kind() == "deb"
    (tmp_path / "opt" / "panepilot" / "PACKAGE").write_text("quatsch")
    assert ik.package_format() is None and ik.kind() == ik.FROZEN
    assert "sudo apt install ./\"a.deb\"" in ik.install_command("/home/x/Downloads/a.deb", "deb")
    assert "zypper" in ik.install_command("/d/a.rpm", "rpm") and "dnf" in ik.install_command("/d/a.rpm", "rpm")


RELEASE = {"tag_name": "v99.0.0", "body": "neu", "html_url": "https://example.invalid/r",
           "assets": [{"name": "PanePilot-99.0.0-x86_64.AppImage", "browser_download_url": "https://e/a", "size": 3},
                      {"name": "PanePilot-99.0.0-x86_64.AppImage.zsync", "browser_download_url": "https://e/z"},
                      {"name": "PanePilot-99.0.0-amd64.deb", "browser_download_url": "https://e/d", "size": 5},
                      {"name": "PanePilot-99.0.0-x86_64.rpm", "browser_download_url": "https://e/r", "size": 7}]}


def test_release_assets_per_install(monkeypatch, tmp_path):
    from panepilot import updatecheck as uc

    rel = uc.parse_release(RELEASE)
    assert rel.asset_name == "PanePilot-99.0.0-x86_64.AppImage"
    assert rel.packages["deb"][0] == "PanePilot-99.0.0-amd64.deb" and rel.packages["rpm"][2] == 7
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert rel.for_install() is rel
    _fake_package(monkeypatch, tmp_path, "rpm")
    pkg = rel.for_install()
    assert (pkg.asset_name, pkg.asset_url, pkg.asset_size) == ("PanePilot-99.0.0-x86_64.rpm", "https://e/r", 7)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr(uc, "download_folder", lambda: str(downloads))
    assert uc.target_path(rel) == str(downloads / "PanePilot-99.0.0-x86_64.rpm")
    old = uc.parse_release({**RELEASE, "assets": RELEASE["assets"][:2]})  # Release ohne Pakete
    assert uc.target_path(old) is None  # → Release-Seite öffnen


def test_package_update_flow(window, monkeypatch, tmp_path):  # noqa: F811
    from PySide6.QtGui import QDesktopServices

    from panepilot import dialogs
    from panepilot import updatecheck as uc

    _fake_package(monkeypatch, tmp_path, "deb")
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr(uc, "download_folder", lambda: str(downloads))
    got = []

    def fake_download(parent, release, target):
        got.append((release.asset_name, target))
        open(target, "wb").write(b"deb")
        return True

    monkeypatch.setattr(uc, "download_release", fake_download)
    monkeypatch.setattr(uc, "UpdateDialog", type("D", (), {
        "DOWNLOAD": 1, "SKIP": 2, "LATER": 3,
        "__init__": lambda self, *a: setattr(self, "choice", 1), "exec": lambda self: 0}))
    opened, infos = [], []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: opened.append(url.toLocalFile()) or True)
    monkeypatch.setattr(dialogs, "show_info", lambda *a: infos.append(a[2]))
    uc.handle_release(window, uc.parse_release(RELEASE), manual=True)
    target = str(downloads / "PanePilot-99.0.0-amd64.deb")
    assert got == [("PanePilot-99.0.0-amd64.deb", target)] and opened == [target]
    assert "sudo apt install" in infos[-1] and os.stat(target).st_mode & 0o111 == 0  # nicht ausführbar


def test_package_hides_menu_entry_and_about(window, monkeypatch, tmp_path):  # noqa: F811
    from panepilot import about
    from panepilot.settingsdialog import SettingsDialog

    dlg = SettingsDialog(window)
    assert not dlg.menu_button.isHidden()
    _fake_package(monkeypatch, tmp_path, "deb")
    dlg = SettingsDialog(window)
    assert dlg.menu_button.isHidden() and dlg.menu_status.isHidden()
    text = about.system_info("/cfg") if hasattr(about, "system_info") else ""
    if text:
        assert "Debian-Paket (.deb)" in text


def test_appimage_launcher_question(window, monkeypatch, tmp_path):  # noqa: F811
    from panepilot import desktopint, dialogs
    from panepilot import updatecheck as uc

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("APPIMAGE", str(tmp_path / "PanePilot.AppImage"))
    (tmp_path / "PanePilot.AppImage").write_bytes(b"x")
    desktopint.integrate(str(tmp_path / "PanePilot.AppImage"))
    asked = []
    monkeypatch.setattr(dialogs, "confirm", lambda *a, **k: asked.append(a[2]) or True)
    uc.offer_appimage_launcher_removal(window)  # läuft als AppImage: keine Frage
    assert asked == []
    _fake_package(monkeypatch, tmp_path, "deb")
    uc.offer_appimage_launcher_removal(window)
    assert len(asked) == 1 and not desktopint.is_integrated()
    uc.offer_appimage_launcher_removal(window)
    assert len(asked) == 1  # nur einmal
