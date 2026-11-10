import getpass
import os

import pytest

from panepilot.disks import DISK_FIXED, DISK_IMAGE, DISK_OPTICAL, DISK_USB
from panepilot.mounts import MountManager


def _mk(path, text=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is not None:
        path.write_text(text)


@pytest.fixture
def system(tmp_path, monkeypatch):
    sysfs, dev = tmp_path / "sys", tmp_path / "dev"
    devices = sysfs / "devices"
    blk = sysfs / "class" / "block"
    blk.mkdir(parents=True)

    def disk(name, rel, size, vendor="", model="", parts=()):
        d = devices / rel / name
        _mk(d / "size", str(size // 512))
        if model:
            _mk(d / "device" / "model", model)
        if vendor:
            _mk(d / "device" / "vendor", vendor)
        os.symlink(d, blk / name)
        for p in parts:
            _mk(d / p / "partition", "1")
            os.symlink(d / p, blk / p)

    disk("nvme0n1", "pci/nvme", 1_000_204_886_016, model="Samsung SSD 980 1TB", parts=("nvme0n1p5", "nvme0n1p6"))
    disk("sdb", "pci/usb1/1-1", 32_000_000_000, vendor="SanDisk", model="Ultra", parts=("sdb1",))
    disk("sr0", "pci/ata2", 0, model="DVD-RW")
    loop = devices / "virtual" / "loop3"
    _mk(loop / "size", "1000")
    _mk(loop / "loop" / "backing_file", "/home/alice/debian-13.iso")
    os.symlink(loop, blk / "loop3")
    (dev / "disk" / "by-uuid").mkdir(parents=True)
    os.symlink("../../nvme0n1p5", dev / "disk" / "by-uuid" / "AAA")
    os.symlink("../../nvme0n1p6", dev / "disk" / "by-uuid" / "ROOT")
    monkeypatch.setenv("PANEPILOT_SYSFS", str(sysfs))
    monkeypatch.setenv("PANEPILOT_DEVROOT", str(dev))
    user = getpass.getuser()
    fstab = tmp_path / "fstab2"
    fstab.write_text("UUID=ROOT / ext4 errors=remount-ro 0 1\nUUID=AAA /opt ext4 defaults 0 2\n")
    mounts = tmp_path / "mounts2"
    mounts.write_text(
        "/dev/nvme0n1p6 / ext4 rw 0 0\n/dev/nvme0n1p5 /opt ext4 rw 0 0\n"
        f"/dev/sdb1 /media/{user}/STICK vfat rw 0 0\n/dev/loop3 /media/{user}/DEBIAN iso9660 ro 0 0\n"
    )
    return fstab, mounts


def test_partitions_grouped_by_physical_disk(qapp, system):
    fstab, mounts = system
    m = MountManager(fstab_path=str(fstab), mounts_path=str(mounts), poll=False)
    disks = {d.kind: d for d in m.disks()}
    nvme = disks[DISK_FIXED]
    assert nvme.label == "Samsung SSD 980 1TB (1 TB)"
    assert [e.label for e in nvme.entries] == ["System (/)", "opt"]
    assert disks[DISK_USB].label == "SanDisk Ultra (32 GB)"
    assert [e.label for e in disks[DISK_USB].entries] == ["STICK"]
    assert disks[DISK_IMAGE].label == "Abbild: debian-13.iso"
    assert disks[DISK_OPTICAL].has_medium is False and not disks[DISK_OPTICAL].entries
    # Die Systempartition lässt sich nie ein-/aushängen
    assert m.entry_containing("/usr/bin") is None


def test_safely_remove_runs_unmount_then_power_off(qtbot, system, tmp_path):
    fstab, mounts = system
    m = MountManager(fstab_path=str(fstab), mounts_path=str(mounts), poll=False)
    log = tmp_path / "log"
    m.udisks_cmd = ["sh", "-c", f'echo "$@" >> {log}', "udisksctl"]
    usb = next(d for d in m.disks() if d.kind == DISK_USB)
    results = []
    m.safely_remove(usb, lambda ok, out: results.append(ok))
    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    assert results == [True]
    assert log.read_text().splitlines() == ["unmount -b /dev/sdb1", "power-off -b /dev/sdb"]
