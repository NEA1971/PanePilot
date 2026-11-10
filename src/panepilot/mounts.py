"""Laufwerke und Netzwerkfreigaben (Linux).

Quellen:
* ``/etc/fstab`` – fest eingetragene Laufwerke und Freigaben
* ``/proc/self/mounts`` – was gerade eingebunden ist (auch USB-Sticks usw.)
* ``/sys`` und ``/run/udev/data`` – USB-Datenträger, die noch nicht eingebunden sind

Eingebunden wird wie bei Nautilus über ``mount <einhängepunkt>`` (für
fstab-Einträge mit der Option ``user``), ausgehängt über ``umount``. Für
Wechseldatenträger, die das System selbst eingebunden hat, wird
``udisksctl unmount`` verwendet.

Für Tests lassen sich die Dateien über PANEPILOT_FSTAB / PANEPILOT_MOUNTS
umlenken.
"""

from __future__ import annotations

import getpass
import os
import re
import sys
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from .disks import DISK_UNKNOWN, DiskInfo, device_name, disk_info, optical_drives, parent_disk, usb_volumes
from .i18n import t
from .util import child_environment

NETWORK_TYPES = {"cifs", "smbfs", "smb3", "nfs", "nfs4", "sshfs", "fuse.sshfs", "davfs", "fuse.rclone"}
REMOVABLE_TYPES = {"vfat", "exfat", "ntfs", "ntfs3", "fuseblk", "iso9660", "udf", "ext2", "ext3", "ext4", "btrfs", "xfs", "hfsplus"}
SKIP_MOUNTPOINTS = {"/", "/boot", "/boot/efi", "none", "swap"}

KIND_NETWORK = "network"
KIND_LOCAL = "local"
KIND_REMOVABLE = "removable"


def _unescape(text: str) -> str:
    """fstab/mounts verwenden Oktal-Escapes, z. B. '\\040' für ein Leerzeichen."""
    return re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), text)


@dataclass
class MountEntry:
    source: str
    mount_point: str
    fstype: str
    options: list[str] = field(default_factory=list)
    in_fstab: bool = True
    mounted: bool = False
    display: str = ""  # abweichender Anzeigename, z. B. „System (/)“

    @property
    def kind(self) -> str:
        if self.fstype in NETWORK_TYPES or self.source.startswith("//"):
            return KIND_NETWORK
        if not self.in_fstab:
            return KIND_REMOVABLE
        return KIND_LOCAL

    @property
    def user_mountable(self) -> bool:
        return "user" in self.options or "users" in self.options or "owner" in self.options

    @property
    def server(self) -> str:
        """'//nas/Backup' → 'nas', 'nas:/export/x' → 'nas'."""
        src = self.source
        if src.startswith("//"):
            return src[2:].split("/", 1)[0]
        if ":" in src:
            host = src.split(":", 1)[0]
            return host.split("@")[-1]
        return ""

    @property
    def label(self) -> str:
        return self.display or os.path.basename(self.mount_point.rstrip("/")) or self.mount_point


def parse_fstab(text: str) -> list[MountEntry]:
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            continue
        source, mp, fstype = _unescape(parts[0]), _unescape(parts[1]), parts[2]
        options = parts[3].split(",") if len(parts) > 3 else []
        if fstype == "swap" or mp in SKIP_MOUNTPOINTS or not mp.startswith("/"):
            continue
        entries.append(MountEntry(source, os.path.normpath(mp), fstype, options))
    return entries


def parse_fstab_with_root(text: str) -> list[MountEntry]:
    """Wie parse_fstab, aber inklusive „/“ (für die Zuordnung der Systempartition)."""
    entries = []
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 3 and not parts[0].startswith("#") and _unescape(parts[1]) == "/":
            entries.append(MountEntry(_unescape(parts[0]), "/", parts[2], parts[3].split(",") if len(parts) > 3 else []))
    return entries


def parse_mounts(text: str) -> dict[str, tuple[str, str]]:
    """Einhängepunkt → (Quelle, Typ)."""
    result = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        result[os.path.normpath(_unescape(parts[1]))] = (_unescape(parts[0]), parts[2])
    return result


GVFS_TYPES = {"fuse.gvfsd-fuse", "fuse.gvfs-fuse-daemon"}


def network_mount_points(mounts_text: str) -> set[str]:
    """Eingehängte Netzfreigaben inkl. der von Nautilus verbundenen (gvfs) – für die Suche (F-880)."""
    result = set()
    for mp, (src, fstype) in parse_mounts(mounts_text).items():
        if fstype in NETWORK_TYPES or fstype in GVFS_TYPES or src.startswith("//"):
            result.add(mp)
    return result


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


class MountManager(QObject):
    """Kennt alle Laufwerke/Freigaben und bindet sie bei Bedarf ein oder aus."""

    changed = Signal()
    busy_changed = Signal(str, bool)  # Einhängepunkt, läuft gerade

    POLL_MS = 2000

    def __init__(self, parent=None, fstab_path: str | None = None, mounts_path: str | None = None,
                 poll: bool = True) -> None:
        super().__init__(parent)
        self.fstab_path = fstab_path or os.environ.get("PANEPILOT_FSTAB", "/etc/fstab")
        self.mounts_path = mounts_path or os.environ.get("PANEPILOT_MOUNTS", "/proc/self/mounts")
        self.mount_cmd = ["mount"]
        self.umount_cmd = ["umount"]
        self.udisks_cmd = ["udisksctl"]
        self._entries: list[MountEntry] = []
        self._disks: list[DiskInfo] = []
        self._disk_of: dict[str, DiskInfo] = {}
        self._signature = None
        self._running: dict[str, QProcess] = {}
        self._enabled = sys.platform.startswith("linux")
        self.reload()
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self.reload)
        if poll and self._enabled:
            self._timer.start()

    def network_mount_points(self) -> set[str]:
        return network_mount_points(_read(self.mounts_path))

    # --- Einlesen ---------------------------------------------------------------------
    def reload(self) -> None:
        if not self._enabled:
            return
        fstab = parse_fstab(_read(self.fstab_path))
        mounted = parse_mounts(_read(self.mounts_path))
        by_mp = {}
        for e in fstab:
            e.mounted = e.mount_point in mounted
            by_mp[e.mount_point] = e
        prefixes = tuple(b + os.sep for b in _media_bases())
        for mp, (src, fstype) in mounted.items():
            if mp in by_mp:
                continue
            if mp.startswith(prefixes) and (
                fstype in REMOVABLE_TYPES or fstype in NETWORK_TYPES
            ):
                by_mp[mp] = MountEntry(src, mp, fstype, [], in_fstab=False, mounted=True)
        # Nicht eingehängte USB-Datenträger (v0.9.9): erscheinen sofort beim Einstecken bzw. Einschalten,
        # ein Klick hängt sie über udisks ein – wie in Nautilus
        known = set()
        for e in fstab:
            dev = device_name(e.source)
            if dev:
                known.add(dev)
        for src, _fstype in mounted.values():
            dev = device_name(src) if src.startswith(("/dev/", "UUID=", "LABEL=")) else None
            if dev:
                known.add(dev)
        for vol in usb_volumes(known):
            mp = _predicted_mount_point(vol.label or vol.uuid or vol.name)
            if mp in by_mp:
                mp = f"{mp} ({vol.name})"
            display = vol.label or t("drives.volume", size=vol.size_text or vol.name)
            by_mp[mp] = MountEntry(vol.device, mp, vol.fstype, [], in_fstab=False, mounted=False, display=display)
        entries = [e for e in by_mp.values() if e.mounted or e.user_mountable or not e.in_fstab]
        entries.sort(key=lambda e: (e.kind, e.server.casefold(), e.label.casefold()))
        self._entries = entries
        self._build_disks(fstab_all=parse_fstab_with_root(_read(self.fstab_path)), mounted=mounted)
        signature = (
            tuple((e.mount_point, e.mounted, e.kind) for e in entries),
            tuple((d.name, d.label, d.has_medium, tuple(e.mount_point for e in d.entries)) for d in self._disks),
        )
        if signature != self._signature:
            self._signature = signature
            self.changed.emit()

    def _build_disks(self, fstab_all: list[MountEntry], mounted: dict[str, tuple[str, str]]) -> None:
        """Lokale Partitionen nach physischer Platte gruppieren (F-260 ff.)."""
        disks: dict[str, DiskInfo] = {}
        disk_of: dict[str, DiskInfo] = {}
        candidates = [e for e in self._entries if e.kind != KIND_NETWORK]
        # Systempartition „/“ zusätzlich (nicht in _entries, damit sie nie ein-/ausgehängt wird)
        root = None
        if "/" in mounted:
            src, fstype = mounted["/"]
            root = MountEntry(src, "/", fstype, [], in_fstab=True, mounted=True, display=t("drives.system"))
        else:
            for e in fstab_all:
                if e.mount_point == "/":
                    root = MountEntry(e.source, "/", e.fstype, e.options, mounted=True, display=t("drives.system"))
        if root is not None:
            candidates.insert(0, root)
        for e in candidates:
            source = e.source
            if e.mounted and e.mount_point in mounted:
                source = mounted[e.mount_point][0]
            dev = device_name(source) or device_name(e.source)
            disk_name = parent_disk(dev) if dev else None
            key = disk_name or "?"
            if key not in disks:
                disks[key] = disk_info(disk_name) if disk_name else DiskInfo("?", DISK_UNKNOWN, t("drives.other"))
            disks[key].entries.append(e)
            disk_of[e.mount_point] = disks[key]
        for name in optical_drives():
            if name not in disks:
                disks[name] = disk_info(name)
        order = {"fixed": 0, "usb": 1, "optical": 2, "image": 3, DISK_UNKNOWN: 9}
        result = sorted(disks.values(), key=lambda d: (order.get(d.kind, 0), "/" not in [x.mount_point for x in d.entries], d.label.casefold()))
        for d in result:
            d.entries.sort(key=lambda e: (e.mount_point != "/", e.label.casefold()))
        self._disks = result
        self._disk_of = disk_of

    def disks(self) -> list[DiskInfo]:
        return list(self._disks)

    def disk_for(self, entry: MountEntry) -> DiskInfo | None:
        return self._disk_of.get(entry.mount_point)

    # --- Abfragen ----------------------------------------------------------------------
    def entries(self, kind: str | None = None) -> list[MountEntry]:
        return [e for e in self._entries if kind is None or e.kind == kind]

    def entry_for_mount_point(self, path: str) -> MountEntry | None:
        p = os.path.normpath(path)
        for e in self._entries:
            if e.mount_point == p:
                return e
        return None

    def entry_containing(self, path: str) -> MountEntry | None:
        """Tiefster bekannter Einhängepunkt, in dem path liegt (oder der path ist)."""
        p = os.path.normpath(path)
        best = None
        for e in self._entries:
            mp = e.mount_point
            if p == mp or p.startswith(mp.rstrip("/") + "/"):
                if best is None or len(mp) > len(best.mount_point):
                    best = e
        return best

    def needs_mount(self, path: str) -> MountEntry | None:
        """Freigabe, die erst eingebunden werden muss, um path zu öffnen."""
        e = self.entry_containing(path)
        if e is not None and not e.mounted and (e.user_mountable or not e.in_fstab):
            return e
        return None

    def mounted_at(self, source: str) -> str | None:
        """Aktueller Einhängepunkt eines Geräts (z. B. nachdem udisks es eingehängt hat)."""
        dev = device_name(source)
        for mp, (src, _fstype) in parse_mounts(_read(self.mounts_path)).items():
            if src == source or (dev and src.startswith("/dev/") and device_name(src) == dev):
                return mp
        return None

    def is_busy(self, mount_point: str) -> bool:
        return mount_point in self._running

    # --- Einbinden / Aushängen -------------------------------------------------------------
    def mount(self, entry: MountEntry, callback=None) -> None:
        if entry.in_fstab:
            cmd = list(self.mount_cmd) + [entry.mount_point]
        else:
            cmd = self.udisks_cmd + ["mount", "-b", entry.source]
        self._run(entry.mount_point, [cmd], callback)

    def _unmount_cmd(self, entry: MountEntry) -> list[str]:
        if entry.in_fstab:
            return list(self.umount_cmd) + [entry.mount_point]
        return self.udisks_cmd + ["unmount", "-b", entry.source]

    def unmount(self, entry: MountEntry, callback=None) -> None:
        self._run(entry.mount_point, [self._unmount_cmd(entry)], callback)

    def mount_device(self, device: str, callback=None) -> None:
        """Z. B. eine eingelegte DVD einbinden (über udisks)."""
        self._run(device, [self.udisks_cmd + ["mount", "-b", device]], callback)

    def safely_remove(self, disk: DiskInfo, callback=None) -> None:
        """USB-Gerät: alle Partitionen aushängen und Gerät abschalten (F-265)."""
        cmds = [self._unmount_cmd(e) for e in disk.entries if e.mounted]
        cmds.append(self.udisks_cmd + ["power-off", "-b", disk.device])
        self._run(disk.device, cmds, callback)

    def eject_image(self, disk: DiskInfo, callback=None) -> None:
        """Eingehängtes ISO-Abbild aushängen und freigeben (F-264)."""
        cmds = [self._unmount_cmd(e) for e in disk.entries if e.mounted]
        cmds.append(self.udisks_cmd + ["loop-delete", "-b", disk.device])
        self._run(disk.device, cmds, callback)

    def _run(self, key: str, cmds: list[list[str]], callback) -> None:
        """Befehle nacheinander ausführen; beim ersten Fehler abbrechen."""
        if key in self._running or not cmds:
            return
        self._running[key] = None
        self.busy_changed.emit(key, True)
        remaining = list(cmds)

        def done(ok: bool, output: str) -> None:
            self._running.pop(key, None)
            self.reload()
            self.busy_changed.emit(key, False)
            if callback is not None:
                callback(ok, output)

        def next_cmd() -> None:
            cmd = remaining.pop(0)
            proc = QProcess(self)
            proc.setProcessEnvironment(child_environment())
            proc.setProgram(cmd[0])
            proc.setArguments(cmd[1:])
            self._running[key] = proc
            handled = {"done": False}

            def finished(code=0, started=True):
                if handled["done"]:
                    return
                handled["done"] = True
                output = bytes(proc.readAllStandardError()).decode("utf-8", "replace").strip()
                if not output:
                    output = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace").strip()
                if not started:
                    output = t("mount.command_missing", cmd=cmd[0])
                ok = started and code == 0
                proc.deleteLater()
                if ok and remaining:
                    next_cmd()
                else:
                    done(ok, output)

            proc.finished.connect(lambda code, _status: finished(code))
            proc.errorOccurred.connect(
                lambda err: finished(-1, started=False) if err == QProcess.ProcessError.FailedToStart else None
            )
            proc.start()

        next_cmd()


def _predicted_mount_point(name: str) -> str:
    """Wo udisks das Gerät einhängen wird: /media/<benutzer>/<name> (Fedora u. a.: /run/media/…)."""
    media, run_media = _media_bases()
    return os.path.join(run_media if os.path.isdir(run_media) else media, name.replace("/", "_"))


def _media_bases() -> tuple[str, str]:
    """Wohin das System Wechseldatenträger einhängt: /media/<benutzer> bzw. /run/media/<benutzer>."""
    return os.path.join("/media", _username()), os.path.join("/run/media", _username())


def _username() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001
        return os.environ.get("USER", "")
