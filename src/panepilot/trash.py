"""Papierkorb nach dem freedesktop.org-Standard (wie GNOME/Nautilus).

* Persönlicher Papierkorb: ``$XDG_DATA_HOME/Trash`` (meist ``~/.local/share/Trash``)
* Papierkörbe auf anderen Laufwerken: ``<laufwerk>/.Trash/<uid>`` oder ``<laufwerk>/.Trash-<uid>``
* Auch eingehängte Netzfreigaben haben so einen Papierkorb (Qt legt ihn beim Löschen an).
  Weil ein nicht erreichbarer Server den Zugriff blockieren kann, werden sie nicht
  ständig abgefragt, sondern nur bei Bedarf (``network=True``).

Jeder Papierkorb hat ``files/`` (die gelöschten Dateien) und ``info/`` (je eine
``.trashinfo`` mit ursprünglichem Pfad und Löschzeitpunkt).
"""

from __future__ import annotations

import configparser
import ntpath
import os
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

TRASH_URI = "trash:///"


def is_trash_uri(path: str | None) -> bool:
    return bool(path) and path.startswith("trash:")


@dataclass
class TrashItem:
    name: str  # angezeigter Name (aus dem ursprünglichen Pfad)
    file_path: str  # Datei im Papierkorb
    info_path: str
    original_path: str
    deleted: float  # Zeitstempel
    is_dir: bool
    size: int
    mode: int = 0
    uid: int = -1
    gid: int = -1

    @property
    def original_dir(self) -> str:
        return os.path.dirname(self.original_path)


def home_trash() -> str:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return os.path.join(base, "Trash")


def topdir_trashes(mount_points: list[str]) -> list[tuple[str, str]]:
    """(Papierkorb-Ordner, Laufwerkswurzel) für weitere Laufwerke."""
    uid = os.getuid() if hasattr(os, "getuid") else 0
    result = []
    for top in mount_points:
        if not top or top == "/":
            continue
        shared = os.path.join(top, ".Trash")
        candidates = []
        try:
            st = os.lstat(shared)
            if stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode) and st.st_mode & stat.S_ISVTX:
                candidates.append(os.path.join(shared, str(uid)))
        except OSError:
            pass
        candidates.append(os.path.join(top, f".Trash-{uid}"))
        for c in candidates:
            if os.path.isdir(os.path.join(c, "files")):
                result.append((c, top))
    return result


def _parse_info(info_path: str) -> tuple[str, float] | None:
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    try:
        parser.read(info_path, encoding="utf-8")
        sec = parser["Trash Info"]
        path = unquote(sec.get("Path", ""))
        date = sec.get("DeletionDate", "")
    except (configparser.Error, KeyError, OSError, UnicodeDecodeError):
        return None
    try:
        when = datetime.fromisoformat(date).timestamp() if date else 0.0
    except ValueError:
        when = 0.0
    return path, when


class Trash:
    def __init__(self, mount_points_provider=None, network_mounts_provider=None) -> None:
        self._mounts = mount_points_provider or (lambda: [])
        self._network = network_mounts_provider or (lambda: [])

    def locations(self, network: bool = True, local: bool = True) -> list[tuple[str, str]]:
        """(Papierkorb-Ordner, Basis für relative Pfade)."""
        locs = []
        if local:
            locs.append((home_trash(), "/"))
            locs.extend(topdir_trashes(list(self._mounts())))
        if network:
            locs.extend(topdir_trashes(list(self._network())))
        return locs

    def files_dirs(self, network: bool = True, local: bool = True) -> list[str]:
        return [os.path.join(t, "files") for t, _ in self.locations(network, local)
                if os.path.isdir(os.path.join(t, "files"))]

    def is_empty(self, network: bool = True, local: bool = True) -> bool:
        for d in self.files_dirs(network, local):
            try:
                with os.scandir(d) as it:
                    if any(True for _ in it):
                        return False
            except OSError:
                continue
        return True

    def items(self) -> list[TrashItem]:
        result = []
        for trash_dir, base in self.locations():
            files = os.path.join(trash_dir, "files")
            info = os.path.join(trash_dir, "info")
            try:
                names = os.listdir(files)
            except OSError:
                continue
            for name in names:
                fpath = os.path.join(files, name)
                ipath = os.path.join(info, name + ".trashinfo")
                parsed = _parse_info(ipath)
                if parsed is None:
                    original, when = os.path.join(base, name), 0.0
                else:
                    original, when = parsed
                    if not os.path.isabs(original):
                        original = os.path.join(base, original)
                try:
                    st = os.lstat(fpath)
                except OSError:
                    continue
                is_dir = stat.S_ISDIR(st.st_mode)
                result.append(TrashItem(
                    name=os.path.basename(original.rstrip("/")) or name,
                    file_path=fpath,
                    info_path=ipath,
                    original_path=os.path.normpath(original),
                    deleted=when or st.st_mtime,
                    is_dir=is_dir,
                    size=0 if is_dir else st.st_size,
                    mode=st.st_mode,
                    uid=st.st_uid,
                    gid=st.st_gid,
                ))
        return result

    def item_for(self, file_path: str) -> TrashItem | None:
        for item in self.items():
            if item.file_path == file_path:
                return item
        return None


class WindowsTrash:
    """v3.0 (L-4010): Windows-Papierkorb – liest ``X:\\$Recycle.Bin\\<SID>`` direkt.

    Zu jeder gelöschten Datei gibt es ``$R…`` (Inhalt) und ``$I…`` (ursprünglicher Pfad, Größe, Zeitpunkt).
    Wiederherstellen und endgültiges Löschen laufen wie unter Linux über ``file_path``/``info_path``.
    """

    def __init__(self, sid: str | None = None, dirs_provider=None) -> None:
        self._sid = sid
        self._dirs = dirs_provider

    def files_dirs(self, network: bool = True, local: bool = True) -> list[str]:
        if not local:
            return []
        if self._dirs is not None:
            return list(self._dirs())
        from . import winsys

        if self._sid is None:
            self._sid = winsys.user_sid()
        return winsys.recycle_dirs(self._sid)

    def locations(self, network: bool = True, local: bool = True) -> list[tuple[str, str]]:
        return [(d, ntpath.splitdrive(d)[0] + "\\") for d in self.files_dirs(network, local)]

    def _pairs(self):
        for folder in self.files_dirs():
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            for name in names:
                if not name.upper().startswith("$R"):
                    continue
                yield folder, name, os.path.join(folder, "$I" + name[2:])

    def is_empty(self, network: bool = True, local: bool = True) -> bool:
        if not local:
            return True
        return not any(True for _ in self._pairs())

    def items(self) -> list[TrashItem]:
        from . import winsys

        result = []
        for folder, name, info_path in self._pairs():
            fpath = os.path.join(folder, name)
            try:
                st = os.lstat(fpath)
            except OSError:
                continue
            info = None
            try:
                with open(info_path, "rb") as fh:
                    info = winsys.parse_recycle_info(fh.read(4096))
            except OSError:
                pass
            if info is None:
                original, when, size = ntpath.join(ntpath.splitdrive(folder)[0] + "\\", name), st.st_mtime, st.st_size
            else:
                original, when, size = info.original, info.deleted, info.size
            is_dir = stat.S_ISDIR(st.st_mode)
            result.append(TrashItem(
                name=ntpath.basename(original.rstrip("\\/")) or name,
                file_path=fpath,
                info_path=info_path,
                original_path=original,
                deleted=when or st.st_mtime,
                is_dir=is_dir,
                size=0 if is_dir else size,
                mode=st.st_mode,
            ))
        return result

    def item_for(self, file_path: str) -> TrashItem | None:
        for item in self.items():
            if item.file_path == file_path:
                return item
        return None


def make_trash(mount_points_provider=None, network_mounts_provider=None):
    import sys

    if sys.platform.startswith("win"):
        return WindowsTrash()
    return Trash(mount_points_provider, network_mounts_provider)
