"""Tests für v0.9.9: AppImage-Umgebung nicht weitergeben, nicht eingehängte USB-Datenträger."""

import os
import sys

import pytest

linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux")


# --- AppImage-Angaben (I-100) ----------------------------------------------------------------------
def test_child_environment_drops_appimage_vars(monkeypatch):
    from panepilot.util import child_environment

    for var, value in (("APPIMAGE", "/home/alice/PanePilot.AppImage"), ("APPDIR", "/tmp/.mount_Pane"),
                       ("ARGV0", "PanePilot.AppImage"), ("OWD", "/home/alice"), ("HOME_TEST_KEEP", "1")):
        monkeypatch.setenv(var, value)
    env = child_environment()
    for var in ("APPIMAGE", "APPDIR", "ARGV0", "OWD"):
        assert not env.contains(var), var
    assert env.value("HOME_TEST_KEEP") == "1"


@linux
def test_started_program_does_not_see_appimage(qtbot, tmp_path, monkeypatch):
    """Ein gestartetes Programm (z. B. ein AppImage mit Updater) darf den Pfad von PanePilot nicht erfahren."""
    from panepilot import util

    monkeypatch.setenv("APPIMAGE", "/home/alice/PanePilot-0.9.8-x86_64.AppImage")
    out = tmp_path / "env.txt"
    script = tmp_path / "programm.sh"
    script.write_text(f'#!/bin/sh\nenv > "{out}"\n')
    script.chmod(0o755)
    assert util._start_detached(str(script), [], str(tmp_path))
    qtbot.waitUntil(out.exists, timeout=5000)
    qtbot.waitUntil(lambda: "PATH=" in out.read_text(), timeout=5000)
    assert "PanePilot-0.9.8" not in out.read_text()


# --- USB-Datenträger (I-110 ff.) ---------------------------------------------------------------------
def _mk(path, text=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is not None:
        path.write_text(text)


@pytest.fixture
def usb_system(tmp_path, monkeypatch):
    sysfs, dev, udev = tmp_path / "sys", tmp_path / "dev", tmp_path / "udev"
    devices = sysfs / "devices"
    blk = sysfs / "class" / "block"
    blk.mkdir(parents=True)
    udev.mkdir()
    numbers = iter(range(1, 100))

    def node(path, name, props=None):
        n = next(numbers)
        _mk(path / "dev", f"8:{n}")
        _mk(path / "size", str(8_000_000_000_000 // 512))
        os.symlink(path, blk / name)
        if props is not None:
            (udev / f"b8:{n}").write_text("".join(f"E:{k}={v}\n" for k, v in props.items()))

    def disk(name, rel, vendor="", model="", props=None, parts=()):
        d = devices / rel / name
        if model:
            _mk(d / "device" / "model", model)
        if vendor:
            _mk(d / "device" / "vendor", vendor)
        node(d, name, props)
        for pname, pprops in parts:
            _mk(d / pname / "partition", "1")
            node(d / pname, pname, pprops)

    fs = {"ID_FS_USAGE": "filesystem"}
    disk("nvme0n1", "pci/nvme", model="Samsung SSD", parts=[
        ("nvme0n1p1", {**fs, "ID_FS_TYPE": "vfat"}),  # eingehängt (/)
        ("nvme0n1p7", {**fs, "ID_FS_TYPE": "ntfs", "ID_FS_LABEL": "Windows"}),  # intern, nicht eingehängt
    ])
    disk("sdc", "pci/usb2/2-1", vendor="Intenso", model="External", parts=[
        ("sdc1", {**fs, "ID_FS_TYPE": "vfat", "ID_PART_ENTRY_TYPE": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"}),  # EFI
        ("sdc2", {**fs, "ID_FS_TYPE": "ext4", "ID_FS_LABEL": "Intenso_8TB", "ID_FS_LABEL_ENC": "Intenso\\x208TB",
                  "ID_FS_UUID": "1234-ABCD"}),
        ("sdc3", {"ID_FS_USAGE": "other", "ID_FS_TYPE": "swap"}),
    ])
    disk("sdd", "pci/usb2/2-2", vendor="SanDisk", model="Stick", props={**fs, "ID_FS_TYPE": "exfat", "ID_FS_UUID": "77-88"})
    monkeypatch.setenv("PANEPILOT_SYSFS", str(sysfs))
    monkeypatch.setenv("PANEPILOT_DEVROOT", str(dev))
    monkeypatch.setenv("PANEPILOT_UDEVDATA", str(udev))
    media = tmp_path / "media"
    media.mkdir()
    import panepilot.mounts as mounts_mod

    monkeypatch.setattr(mounts_mod, "_media_bases", lambda: (str(media), str(tmp_path / "run-media")))
    fstab = tmp_path / "fstab"
    fstab.write_text("")
    mounts = tmp_path / "mounts"
    mounts.write_text("/dev/nvme0n1p1 / ext4 rw 0 0\n")
    return media, fstab, mounts


def test_usb_volumes_only_usable_usb(qapp, usb_system):
    from panepilot.disks import DISK_USB
    from panepilot.mounts import KIND_REMOVABLE, MountManager

    media, fstab, mounts = usb_system
    m = MountManager(fstab_path=str(fstab), mounts_path=str(mounts), poll=False)
    entries = {e.source: e for e in m.entries(KIND_REMOVABLE)}
    # EFI, Swap und die interne Windows-Partition erscheinen nicht
    assert set(entries) == {"/dev/sdc2", "/dev/sdd"}
    intenso = entries["/dev/sdc2"]
    assert intenso.label == "Intenso 8TB" and not intenso.mounted
    assert intenso.mount_point == str(media / "Intenso 8TB")
    assert entries["/dev/sdd"].label == "Datenträger (8 TB)"
    usb = {d.name: d for d in m.disks() if d.kind == DISK_USB}
    assert [e.source for e in usb["sdc"].entries] == ["/dev/sdc2"]
    assert m.needs_mount(intenso.mount_point) is intenso


def test_mounted_volume_not_listed_twice(qapp, usb_system):
    from panepilot.mounts import KIND_REMOVABLE, MountManager

    media, fstab, mounts = usb_system
    mounts.write_text(mounts.read_text() + f"/dev/sdd {media}/77-88 exfat rw 0 0\n")
    m = MountManager(fstab_path=str(fstab), mounts_path=str(mounts), poll=False)
    sdd = [e for e in m.entries(KIND_REMOVABLE) if e.source == "/dev/sdd"]
    assert len(sdd) == 1 and sdd[0].mounted


@linux
def test_click_mounts_with_udisks_and_opens(qtbot, usb_system, monkeypatch):
    """Klick auf die Platte hängt sie über udisks ein und öffnet den Ordner – auch wenn udisks einen anderen Namen wählt."""
    media, fstab, mounts = usb_system
    monkeypatch.setenv("PANEPILOT_FSTAB", str(fstab))
    monkeypatch.setenv("PANEPILOT_MOUNTS", str(mounts))
    from panepilot.app import create_app

    create_app([])
    from panepilot.mainwindow import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    real = media / "Intenso 8TB1"
    log = media.parent / "udisks.log"
    w.mounts.udisks_cmd = ["sh", "-c",
                           f'echo "$@" >> "{log}"; mkdir -p "{real}"; touch "{real}/film.mkv"; '
                           f"printf '%s\\n' '/dev/sdc2 {str(real).replace(' ', chr(92) + '040')} ext4 rw 0 0' >> '{mounts}'",
                           "udisksctl"]
    entry = next(e for e in w.mounts.entries() if e.source == "/dev/sdc2")
    panel = w.sides["left"].panel
    panel.navigate(entry.mount_point)
    qtbot.waitUntil(lambda: panel.current_path == str(real), timeout=5000)
    assert "mount -b /dev/sdc2" in log.read_text()
    assert "film.mkv" in [e.name for e in panel.model.entries()]
    assert w.mounts.entry_for_mount_point(str(real)).mounted
