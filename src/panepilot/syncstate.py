"""Gemerkter Stand gespeicherter Abgleiche (v2.8, L-3810 ff.) – wie die Datenbank von FreeFileSync.

Nach jedem erfolgreichen Lauf eines gespeicherten Abgleichs merkt sich PanePilot für jede Datei Größe und
Änderungszeit auf beiden Seiten. Beim nächsten Vergleich zeigt das, welche Seite sich seither geändert hat:

* nur eine Seite geändert → diese Seite gewinnt, auch wenn ihre Uhrzeit älter ist (L-3811),
* beide geändert → Konflikt „auf beiden Seiten geändert“ (L-3811),
* auf einer Seite gelöscht → in Richtung „beide“ auch auf der anderen löschen (L-3813),
* bei einer Richtung: Ziel seither verändert → Konflikt statt überschreiben (L-3814).

Der Stand liegt unter ``~/.config/PanePilot/…/sync-state/`` – nicht in den abgeglichenen Ordnern.
"""

from __future__ import annotations

import hashlib
import json
import os

from . import folderdiff as fd
from .config import config_dir

DIR_NAME = "sync-state"
VERSION = 1


def _file(profile: str) -> str:
    key = hashlib.sha1(profile.lower().encode("utf-8")).hexdigest()[:16]
    return os.path.join(str(config_dir()), DIR_NAME, key + ".json")


def _side(s: fd.Side | None):
    return None if s is None or s.is_dir else [s.size, s.mtime]


def save(profile: str, left: str, right: str, entries: list[fd.Entry], keep: set[str] | None = None) -> None:
    """Stand nach dem Lauf merken. keep: Dateien, deren alter Stand bleibt (übersprungene Konflikte und
    Änderungen, die nicht übertragen wurden) – sonst wären sie beim nächsten Mal nicht mehr erkennbar."""
    old = load(profile, left, right) or {}
    files = {}
    for e in entries:
        if e.is_dir:
            continue
        if keep and e.rel in keep:
            if e.rel in old:
                files[e.rel] = old[e.rel]
            continue
        files[e.rel] = [_side(e.left), _side(e.right)]
    path = _file(profile)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"version": VERSION, "profile": profile, "left": left, "right": right, "files": files}, fh,
                  ensure_ascii=False)
    os.replace(tmp, path)


def load(profile: str, left: str, right: str) -> dict | None:
    """Gemerkter Stand – nur, wenn er zu genau diesen beiden Ordnern gehört."""
    try:
        with open(_file(profile), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("left") != left or data.get("right") != right:
        return None
    files = data.get("files")
    return files if isinstance(files, dict) else None


def forget(profile: str) -> None:
    try:
        os.unlink(_file(profile))
    except OSError:
        pass


def rename(old: str, new: str) -> None:
    if old.lower() == new.lower():
        return
    try:
        os.replace(_file(old), _file(new))
    except OSError:
        pass


def _changed(now: fd.Side | None, before, opts: fd.Options) -> str:
    """'' = unverändert, sonst 'new', 'deleted' oder 'changed'."""
    if now is not None and now.is_dir:
        now = None
    if before is None:
        return "" if now is None else "new"
    if now is None:
        return "deleted"
    size, mtime = before
    if now.size != size or fd.same_time(now.mtime, mtime, opts) != 0:
        return "changed"
    return ""


def apply(entries: list[fd.Entry], state: dict, opts: fd.Options) -> int:
    """Zustände und Aktionen anhand des gemerkten Stands anpassen; liefert die Zahl der Konflikte."""
    conflicts = 0
    for e in entries:
        if e.is_dir or e.status == fd.CONFLICT and e.left is not None and e.right is not None \
                and e.left.is_dir != e.right.is_dir:
            continue
        before = state.get(e.rel)
        if not isinstance(before, list) or len(before) != 2:
            continue  # neu seit dem letzten Abgleich: wie bisher nach der Uhrzeit (L-3812)
        lc = _changed(e.left, before[0], opts)
        rc = _changed(e.right, before[1], opts)
        e.since = tuple(x for x in ((f"left_{lc}" if lc else ""), (f"right_{rc}" if rc else "")) if x)
        if e.status == fd.SAME or not (lc or rc):
            continue  # gleich – oder seither nichts geändert: bleibt, wie es ist
        target_changed = (opts.direction == fd.LR and rc) or (opts.direction == fd.RL and lc)
        if opts.direction != fd.BOTH:
            if target_changed:  # L-3814: Ziel seither verändert → nicht überschreiben
                e.status = fd.CONFLICT
            elif lc and e.left is None:
                e.status = fd.LEFT_DELETED
            elif rc and e.right is None:
                e.status = fd.RIGHT_DELETED
            elif lc and e.left is not None and e.right is not None:
                e.status = fd.LEFT_NEWER
            elif rc and e.left is not None and e.right is not None:
                e.status = fd.RIGHT_NEWER
        elif lc and rc:
            e.status = fd.BOTH_CHANGED  # L-3811
        elif lc:
            e.status = fd.LEFT_DELETED if e.left is None else (fd.LEFT_NEWER if e.right is not None
                                                                else fd.LEFT_ONLY)
        else:
            e.status = fd.RIGHT_DELETED if e.right is None else (fd.RIGHT_NEWER if e.left is not None
                                                                  else fd.RIGHT_ONLY)
        e.action = fd.default_action(e, opts)
        if e.status in fd.CONFLICTS:
            conflicts += 1
    _fold_deleted_dirs(entries, opts)
    return conflicts


def _fold_deleted_dirs(entries: list[fd.Entry], opts: fd.Options) -> None:
    """Ordner, die nur noch auf einer Seite liegen und deren Dateien alle auf der anderen Seite gelöscht
    wurden, gelten selbst als gelöscht – sonst würde die Ordnerzeile sie zurückkopieren (L-3813)."""
    for e in sorted((x for x in entries if x.is_dir and (x.left is None) != (x.right is None)),
                    key=lambda x: -x.rel.count("/")):
        files = [x for x in entries if not x.is_dir and x.rel.startswith(e.rel + "/")]
        if not files:
            continue
        gone = fd.LEFT_DELETED if e.left is None else fd.RIGHT_DELETED
        if all(x.status == gone for x in files):
            e.status = gone
            e.since = (("left_deleted",) if gone == fd.LEFT_DELETED else ("right_deleted",))
            e.action = fd.default_action(e, opts)
