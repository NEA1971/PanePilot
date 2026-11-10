import getpass
import os
import sys

import pytest

from panepilot.mounts import KIND_LOCAL, KIND_NETWORK, KIND_REMOVABLE, MountManager, parse_fstab

FSTAB = r"""
UUID=605d /               ext4    errors=remount-ro 0       1
UUID=1681  /boot/efi       vfat    umask=0077      0       1
UUID=84f0 /opt            ext4    defaults        0       2
//nas/Classic\040Music	{base}/nas/Classic\040Music	cifs 	rw,user,noauto,credentials=/x	0	0
//nas/Backup	{base}/nas/Backup	cifs 	rw,user,noauto,credentials=/x	0	0
//fileserver/alice	{base}/home/alice	cifs 	rw,user,noauto,credentials=/x	0	0
/dev/disk/by-uuid/E07E /mnt/E07E auto nosuid,nodev,nofail,noauto 0 0
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    base = tmp_path / "media"
    for d in ("nas/Classic Music", "nas/Backup", "home/alice"):
        (base / d).mkdir(parents=True)
    fstab = tmp_path / "fstab"
    mounts = tmp_path / "mounts"
    fstab.write_text(FSTAB.format(base=base))
    mounts.write_text("/dev/x / ext4 rw 0 0\n/dev/y /opt ext4 rw 0 0\n")
    return base, fstab, mounts


def test_parse_fstab_unescapes_spaces(env):
    base, fstab, _ = env
    entries = parse_fstab(fstab.read_text())
    mps = [e.mount_point for e in entries]
    assert str(base / "nas" / "Classic Music") in mps
    assert "/" not in mps and "/boot/efi" not in mps


def test_entries_and_kinds(qapp, env):
    base, fstab, mounts = env
    m = MountManager(fstab_path=str(fstab), mounts_path=str(mounts), poll=False)
    net = m.entries(KIND_NETWORK)
    assert sorted(e.server for e in net) == ["fileserver", "nas", "nas"]
    assert all(not e.mounted for e in net)
    local = [e.mount_point for e in m.entries(KIND_LOCAL)]
    assert local == ["/opt"]  # /mnt/E07E: weder eingebunden noch für Benutzer einbindbar
    inner = str(base / "nas" / "Backup" / "Steuer" / "2025")
    assert m.needs_mount(inner).label == "Backup"
    assert m.needs_mount("/home") is None


def test_removable_media_detected(qapp, env):
    _base, fstab, mounts = env
    user = getpass.getuser()
    mounts.write_text(mounts.read_text() + f"/dev/sdc1 /media/{user}/USB\\040STICK vfat rw 0 0\n")
    m = MountManager(fstab_path=str(fstab), mounts_path=str(mounts), poll=False)
    rem = m.entries(KIND_REMOVABLE)
    assert [e.label for e in rem] == ["USB STICK"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux")
def test_mount_and_unmount_commands(qtbot, env):
    base, fstab, mounts = env
    m = MountManager(fstab_path=str(fstab), mounts_path=str(mounts), poll=False)
    # "mount" simulieren: Zeile in die mounts-Datei schreiben und eine Datei anlegen
    m.mount_cmd = ["sh", "-c", f'echo "//nas/Backup $0 cifs rw 0 0" >> {mounts}; touch "$0/inhalt.txt"']
    m.umount_cmd = ["sh", "-c", f'grep -v "$0" {mounts} > {mounts}.n; mv {mounts}.n {mounts}']
    entry = m.needs_mount(str(base / "nas" / "Backup"))
    results = []
    m.mount(entry, lambda ok, out: results.append(ok))
    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    assert results == [True]
    assert m.entry_for_mount_point(str(base / "nas" / "Backup")).mounted
    m.unmount(m.entry_for_mount_point(str(base / "nas" / "Backup")), lambda ok, out: results.append(ok))
    qtbot.waitUntil(lambda: len(results) == 2, timeout=5000)
    assert not m.entry_for_mount_point(str(base / "nas" / "Backup")).mounted


def test_failed_mount_reports_message(qtbot, env):
    base, fstab, mounts = env
    m = MountManager(fstab_path=str(fstab), mounts_path=str(mounts), poll=False)
    m.mount_cmd = ["sh", "-c", 'echo "mount error(113): No route to host" >&2; exit 32']
    results = []
    m.mount(m.needs_mount(str(base / "nas" / "Backup")), lambda ok, out: results.append((ok, out)))
    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    assert results[0][0] is False and "No route to host" in results[0][1]


def test_panel_mounts_before_opening(qtbot, env, monkeypatch):
    base, fstab, mounts = env
    monkeypatch.setenv("PANEPILOT_FSTAB", str(fstab))
    monkeypatch.setenv("PANEPILOT_MOUNTS", str(mounts))
    from panepilot.app import create_app

    create_app([])
    from panepilot.mainwindow import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.mounts.mount_cmd = ["sh", "-c", f'echo "//nas/Backup $0 cifs rw 0 0" >> {mounts}; touch "$0/inhalt.txt"']
    panel = w.sides["left"].panel
    target = str(base / "nas" / "Backup")
    panel.navigate(target)
    qtbot.waitUntil(lambda: panel.current_path == target, timeout=5000)
    assert "inhalt.txt" in [e.name for e in panel.model.entries()]
    # Aushängen: Panel wechselt vorher aus der Freigabe heraus
    w.mounts.umount_cmd = ["sh", "-c", f'grep -v "$0" {mounts} > {mounts}.n; mv {mounts}.n {mounts}']
    w.unmount_entry(w.mounts.entry_for_mount_point(target))
    assert panel.current_path == str(base / "nas")
    qtbot.waitUntil(lambda: not w.mounts.entry_for_mount_point(target).mounted, timeout=5000)
