"""Sicherung der Einstellungen als Zip (F-850 ff.)."""

from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .config import config_dir, default_backup_dir

PREFIX = "PanePilot_Settings_"
# Automatische Sicherungen bekommen eine versteckte Markierungsdatei „.<name>.auto“,
# damit beim Aufräumen nur sie gelöscht werden, nie die von Hand erstellten (F-853).


def _marker(folder: Path, name: str) -> Path:
    return folder / f".{name}.auto"


_NAME = re.compile(r"^PanePilot_Settings_(\d{4}-\d{2}-\d{2})([a-z]+)\.zip$")


def backup_folder(setting: str) -> Path:
    return Path(setting).expanduser() if setting else default_backup_dir()


def _suffix(n: int) -> str:
    """0 → a, 25 → z, 26 → aa …"""
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(ord("a") + r) + s
    return s


def next_name(folder: Path, day: _dt.date) -> str:
    stem = f"{PREFIX}{day.isoformat()}"
    i = 0
    while (folder / f"{stem}{_suffix(i)}.zip").exists():
        i += 1
    return f"{stem}{_suffix(i)}.zip"


def folder_reachable(folder: Path, mounts=None) -> bool:
    """Liegt der Ordner auf einer nicht eingehängten Freigabe, gilt er als nicht erreichbar (F-854)."""
    if mounts is not None:
        try:
            if mounts.needs_mount(str(folder)) is not None:
                return False
        except Exception:  # noqa: BLE001 – lieber sichern als abstürzen
            pass
    probe = folder
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return os.access(probe, os.W_OK)


def create_backup(folder: Path, auto: bool = False, day: _dt.date | None = None) -> Path:
    """Packt den Settings-Ordner in ein Zip im Zielordner und liefert dessen Pfad."""
    src = config_dir()
    folder.mkdir(parents=True, exist_ok=True)
    day = day or _dt.date.today()
    target = folder / next_name(folder, day)
    fd, tmp = tempfile.mkstemp(dir=str(folder), prefix=".panepilot-sicherung-", suffix=".zip")
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(ORIGIN_FILE, origin_platform())  # v3.0.1 (L-4060): von welchem System
            for root, dirs, files in os.walk(src):
                dirs.sort()
                for name in sorted(files):
                    if name.startswith(".") and name.endswith(".tmp"):
                        continue
                    full = os.path.join(root, name)
                    zf.write(full, os.path.relpath(full, src))
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    if auto:
        _marker(folder, target.name).touch()
    return target


def prune(folder: Path, keep: int) -> list[Path]:
    """Löscht ältere automatische Sicherungen, behält die letzten keep. Manuelle bleiben."""
    autos = sorted(p for p in folder.glob(f"{PREFIX}*.zip")
                   if _NAME.match(p.name) and _marker(folder, p.name).exists())
    autos.sort(key=lambda p: (_NAME.match(p.name).group(1), len(_NAME.match(p.name).group(2)), p.name))
    removed = []
    for p in autos[:-keep] if keep > 0 else autos:
        try:
            p.unlink()
            _marker(folder, p.name).unlink(missing_ok=True)
            removed.append(p)
        except OSError:
            pass
    return removed


# --- Sicherung vom anderen System (v3.0.1, L-4060) ----------------------------------------------------
ORIGIN_FILE = ".panepilot-origin"
# Bleiben beim „nur Einstellungen“-Wiederherstellen, wie sie sind (Pfade passen nicht zum anderen System)
KEEP_LOCAL = ("Favoriten", "favorites.json", "state.json", "sync_profiles.json", "servers.json", "sync-state")
KEEP_SETTINGS = ("backup_dir", "sync_last", "update_old_file", "terminal", "terminal_custom", "tool_paths",
                 "net_servers", "last_auto_backup", "backup_last_error", "dup_last", "search_last")


def origin_platform() -> str:
    import sys

    return "windows" if sys.platform.startswith("win") else "linux"


def backup_origin(zip_path: Path) -> str:
    """'windows', 'linux' oder '' (unbekannt). Ältere Sicherungen: an den Pfaden in state.json erkennen."""
    import json

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if ORIGIN_FILE in names:
            return zf.read(ORIGIN_FILE).decode("ascii", "replace").strip()
        if "state.json" in names:
            try:
                text = json.dumps(json.loads(zf.read("state.json").decode("utf-8")))
            except ValueError:
                return ""
            if re.search(r'"[A-Za-z]:\\\\', text):
                return "windows"
            if '"/home/' in text or '"/media/' in text or '"/mnt/' in text:
                return "linux"
    return ""


def is_foreign(zip_path: Path) -> bool:
    origin = backup_origin(zip_path)
    return bool(origin) and origin != origin_platform()


def restore_settings_only(zip_path: Path) -> None:
    """Nur Einstellungen übernehmen: Favoriten, Ordner, Abgleiche und Server bleiben (L-4060)."""
    import json

    dest = config_dir()
    with zipfile.ZipFile(zip_path) as zf:
        staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=str(dest.parent)))
        try:
            for n in zf.namelist():
                parts = Path(n).parts
                if Path(n).is_absolute() or ".." in parts:
                    raise ValueError(f"unsafe entry {n}")
            zf.extractall(staging)
            (staging / ORIGIN_FILE).unlink(missing_ok=True)
            for name in KEEP_LOCAL:  # eigene Stände zurücklegen
                target = staging / name
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                elif target.exists():
                    target.unlink()
                current = dest / name
                if current.is_dir():
                    shutil.copytree(current, target)
                elif current.exists():
                    shutil.copy2(current, target)
            new_settings = staging / "settings.json"
            if new_settings.exists():
                try:
                    data = json.loads(new_settings.read_text(encoding="utf-8"))
                    mine = json.loads((dest / "settings.json").read_text(encoding="utf-8")) \
                        if (dest / "settings.json").exists() else {}
                except ValueError:
                    data, mine = None, {}
                if isinstance(data, dict):
                    for key in KEEP_SETTINGS:
                        if key in mine:
                            data[key] = mine[key]
                        else:
                            data.pop(key, None)
                    new_settings.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            old = dest.parent / ".Settings-alt"
            if old.exists():
                shutil.rmtree(old, ignore_errors=True)
            os.replace(dest, old)
            os.replace(staging, dest)
            shutil.rmtree(old, ignore_errors=True)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)


def restore_backup(zip_path: Path) -> None:
    """Ersetzt den Inhalt des Settings-Ordners durch den des Zips."""
    dest = config_dir()
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        for n in names:  # Schutz: nichts außerhalb des Settings-Ordners
            parts = Path(n).parts
            if Path(n).is_absolute() or ".." in parts:
                raise ValueError(f"unsafe entry {n}")
        staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=str(dest.parent)))
        try:
            zf.extractall(staging)
            (staging / ORIGIN_FILE).unlink(missing_ok=True)
            old = dest.parent / ".Settings-alt"
            if old.exists():
                shutil.rmtree(old, ignore_errors=True)
            os.replace(dest, old)
            os.replace(staging, dest)
            shutil.rmtree(old, ignore_errors=True)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)


# --- Liste, Import, Löschen (v0.8.1) ------------------------------------------------------------
@dataclass
class BackupInfo:
    path: Path
    mtime: float
    size: int
    auto: bool

    @property
    def name(self) -> str:
        return self.path.name


def _sort_key(p: Path):
    m = _NAME.match(p.name)
    return (m.group(1), len(m.group(2)), m.group(2)) if m else ("", 0, p.name)


def list_backups(folder: Path) -> list[BackupInfo]:
    """Alle Sicherungen im Ordner, die neueste zuerst."""
    result = []
    try:
        paths = [p for p in folder.glob(f"{PREFIX}*.zip") if _NAME.match(p.name)]
    except OSError:
        return []
    for p in paths:
        try:
            st = p.stat()
        except OSError:
            continue
        result.append(BackupInfo(p, st.st_mtime, st.st_size, _marker(folder, p.name).exists()))
    result.sort(key=lambda b: _sort_key(b.path), reverse=True)
    return result


def check_zip(path: Path) -> None:
    """Wirft ValueError/BadZipFile, wenn die Datei keine brauchbare Sicherung ist."""
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        for n in names:
            parts = Path(n).parts
            if Path(n).is_absolute() or ".." in parts:
                raise ValueError(f"unsafe entry {n}")
        if not any(n.endswith(".json") for n in names):
            raise ValueError("no PanePilot settings")


def import_backup(src: Path, folder: Path) -> Path:
    """Kopiert eine Sicherung in den Sicherungsordner; sie zählt dann als manuelle Sicherung."""
    check_zip(src)
    folder.mkdir(parents=True, exist_ok=True)
    if _NAME.match(src.name) and not (folder / src.name).exists():
        name = src.name
    else:
        m = _NAME.match(src.name)
        day = _dt.date.fromisoformat(m.group(1)) if m else _dt.date.fromtimestamp(src.stat().st_mtime)
        name = next_name(folder, day)
    target = folder / name
    shutil.copy2(src, target)
    _marker(folder, name).unlink(missing_ok=True)
    return target


def delete_backups(paths: list[Path]) -> list[tuple[Path, str]]:
    """Löscht Sicherungen samt Markierung; liefert die Fehler."""
    errors = []
    for p in paths:
        try:
            p.unlink()
            _marker(p.parent, p.name).unlink(missing_ok=True)
        except OSError as exc:
            errors.append((p, exc.strerror or str(exc)))
    return errors
