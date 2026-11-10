"""Zuordnung von Partitionen zu physischen Platten (Linux, über /sys).

Ein fstab-Eintrag nennt nur die Partition (UUID, LABEL oder /dev/…). Über
``/dev/disk/by-uuid`` wird daraus das Gerät (z. B. ``nvme0n1p5``), über
``/sys/class/block`` die zugehörige Platte (``nvme0n1``) samt Gerätename,
Größe und ob sie per USB angeschlossen ist.

Für Tests lassen sich die Wurzeln über PANEPILOT_SYSFS / PANEPILOT_DEVROOT umlenken.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .i18n import t

DISK_FIXED, DISK_USB, DISK_OPTICAL, DISK_IMAGE, DISK_UNKNOWN = "fixed", "usb", "optical", "image", "unknown"


def sys_root() -> str:
    return os.environ.get("PANEPILOT_SYSFS", "/sys")


def dev_root() -> str:
    return os.environ.get("PANEPILOT_DEVROOT", "/dev")


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def device_name(source: str) -> str | None:
    """'UUID=…' / 'LABEL=…' / '/dev/sda1' / '/dev/disk/by-uuid/…' → 'sda1'."""
    dev = dev_root()
    for prefix, folder in (("UUID=", "by-uuid"), ("LABEL=", "by-label"), ("PARTUUID=", "by-partuuid"),
                           ("PARTLABEL=", "by-partlabel")):
        if source.startswith(prefix):
            value = source[len(prefix):].strip('"')
            link = os.path.join(dev, "disk", folder, value)
            return os.path.basename(os.path.realpath(link)) if os.path.lexists(link) else None
    if source.startswith("/dev/"):
        local = os.path.join(dev, source[len("/dev/"):])
        if os.path.lexists(local):
            return os.path.basename(os.path.realpath(local))
        return os.path.basename(source)
    return None


def parent_disk(name: str, _depth: int = 0) -> str | None:
    """Partition → Platte. Bei Geräte-Mappern (LVM/Verschlüsselung) über die darunterliegenden Geräte."""
    base = os.path.join(sys_root(), "class", "block", name)
    if not os.path.lexists(base):
        return None
    if os.path.exists(os.path.join(base, "partition")):
        return os.path.basename(os.path.dirname(os.path.realpath(base)))
    slaves = os.path.join(base, "slaves")
    if _depth < 4 and os.path.isdir(slaves):
        for slave in sorted(os.listdir(slaves)):
            disk = parent_disk(slave, _depth + 1)
            if disk:
                return disk
    return name


def _size_text(nbytes: int) -> str:
    if nbytes <= 0:
        return ""
    for unit, factor in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6)):
        if nbytes >= factor * 0.95:
            value = nbytes / factor
            text = f"{value:.0f}" if value >= 10 else f"{value:.1f}".rstrip("0").rstrip(".")
            return f"{text.replace('.', ',')} {unit}"
    return f"{nbytes} B"


@dataclass
class DiskInfo:
    name: str  # z. B. "nvme0n1", "sdb", "sr0", "loop3"
    kind: str
    label: str
    has_medium: bool = True
    entries: list = field(default_factory=list)  # MountEntry

    @property
    def device(self) -> str:
        return os.path.join("/dev", self.name)


def disk_info(name: str) -> DiskInfo:
    base = os.path.join(sys_root(), "class", "block", name)
    size = 0
    try:
        size = int(_read(os.path.join(base, "size")) or 0) * 512
    except ValueError:
        pass
    if name.startswith("loop"):
        backing = _read(os.path.join(base, "loop", "backing_file"))
        label = t("drives.image", name=os.path.basename(backing) if backing else name)
        return DiskInfo(name, DISK_IMAGE, label)
    vendor = _read(os.path.join(base, "device", "vendor"))
    model = _read(os.path.join(base, "device", "model"))
    if vendor.upper() in ("ATA", "NVME", "") or model.lower().startswith(vendor.lower()):
        vendor = ""
    text = " ".join(p for p in (vendor, model) if p).strip()
    if name.startswith("sr"):
        label = text or t("drives.optical")
        return DiskInfo(name, DISK_OPTICAL, label, has_medium=size > 0)
    real = os.path.realpath(base)
    removable = _read(os.path.join(base, "removable")) == "1"
    kind = DISK_USB if ("/usb" in real or removable) else DISK_FIXED
    if not text:
        text = t("drives.disk", name=name)
    size_text = _size_text(size)
    label = f"{text} ({size_text})" if size_text else text
    return DiskInfo(name, kind, label)


def optical_drives() -> list[str]:
    folder = os.path.join(sys_root(), "class", "block")
    try:
        return sorted(n for n in os.listdir(folder) if n.startswith("sr"))
    except OSError:
        return []


# --- Nicht eingehängte USB-Datenträger (v0.9.9) ----------------------------------------------
# Nautilus erfährt von udisks, welche Geräte ein Dateisystem haben. Dieselben Angaben legt udev
# für jedes Gerät unter /run/udev/data ab – die lesen wir direkt, ohne D-Bus.
SKIP_PART_TYPES = {
    "c12a7328-f81f-11d2-ba4b-00a0c93ec93b",  # EFI-Systempartition
    "e3c9e316-0b5c-4db8-817d-f92df00215ae",  # Microsoft reserviert
    "de94bba4-06d1-4d40-a16a-bfd50179d6ac",  # Windows-Wiederherstellung
    "21686148-6449-6e6f-744e-656564454649",  # BIOS-Boot
    "0xef", "0x27",  # MBR: EFI, Windows-Wiederherstellung
}


def udev_root() -> str:
    return os.environ.get("PANEPILOT_UDEVDATA", "/run/udev/data")


def _decode_udev(text: str) -> str:
    """'Intenso\\x208TB' → 'Intenso 8TB' (ID_FS_LABEL_ENC)."""
    import re

    raw = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), text)
    try:
        return raw.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return raw


def udev_properties(name: str) -> dict[str, str]:
    devnum = _read(os.path.join(sys_root(), "class", "block", name, "dev"))
    if not devnum:
        return {}
    props = {}
    for line in _read(os.path.join(udev_root(), f"b{devnum}")).splitlines():
        if line.startswith("E:") and "=" in line:
            key, value = line[2:].split("=", 1)
            props[key] = value
    return props


@dataclass
class Volume:
    """Partition (oder Platte ohne Partitionen) mit Dateisystem, die noch nicht eingehängt ist."""

    name: str  # z. B. "sdc1"
    disk: str  # z. B. "sdc"
    fstype: str
    label: str
    uuid: str
    size: int

    @property
    def device(self) -> str:
        return os.path.join("/dev", self.name)

    @property
    def size_text(self) -> str:
        return _size_text(self.size)


def _has_partitions(disk: str) -> bool:
    base = os.path.join(sys_root(), "class", "block", disk)
    try:
        return any(os.path.exists(os.path.join(base, n, "partition")) for n in os.listdir(base))
    except OSError:
        return False


def usb_volumes(exclude: set[str]) -> list[Volume]:
    """Alle USB-Datenträger mit Dateisystem, deren Gerät nicht in exclude steht.

    Interne Platten bleiben bewusst außen vor, ebenso EFI-, Wiederherstellungs- und
    Swap-Partitionen: In der Seitenleiste soll nichts stehen, womit man das System beschädigen kann.
    """
    folder = os.path.join(sys_root(), "class", "block")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    usb_cache: dict[str, bool] = {}
    result = []
    for name in names:
        if name in exclude or name.startswith(("loop", "sr", "ram", "zram", "dm-", "md")):
            continue
        is_part = os.path.exists(os.path.join(folder, name, "partition"))
        disk = parent_disk(name) if is_part else name
        if not disk:
            continue
        if not is_part and _has_partitions(name):
            continue
        if disk not in usb_cache:
            usb_cache[disk] = disk_info(disk).kind == DISK_USB
        if not usb_cache[disk]:
            continue
        props = udev_properties(name)
        if props.get("ID_FS_USAGE") != "filesystem" or props.get("UDISKS_IGNORE") == "1":
            continue
        if props.get("ID_PART_ENTRY_TYPE", "").lower() in SKIP_PART_TYPES:
            continue
        label = _decode_udev(props.get("ID_FS_LABEL_ENC", "")) or props.get("ID_FS_LABEL", "")
        try:
            size = int(_read(os.path.join(folder, name, "size")) or 0) * 512
        except ValueError:
            size = 0
        result.append(Volume(name, disk, props.get("ID_FS_TYPE", ""), label, props.get("ID_FS_UUID", ""), size))
    return result
