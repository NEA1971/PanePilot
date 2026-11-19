"""Ordner vergleichen und synchronisieren (v1.16, L-1600 ff.) – ohne Oberfläche, damit gut testbar."""

from __future__ import annotations

import filecmp
import fnmatch
import os
import shutil
import threading
from dataclasses import dataclass, field

# Richtung
LR, RL, BOTH = "lr", "rl", "both"
# Zustand eines Eintrags
SAME, LEFT_ONLY, RIGHT_ONLY, LEFT_NEWER, RIGHT_NEWER, CONFLICT = (
    "same", "left_only", "right_only", "left_newer", "right_newer", "conflict")
# Aktion
NONE, TO_RIGHT, TO_LEFT, DEL_RIGHT, DEL_LEFT = "none", "to_right", "to_left", "del_right", "del_left"

TOLERANCE = 2.0  # Sekunden (FAT, NAS)
HOUR = 3600.0


@dataclass
class Options:
    direction: str = LR
    subdirs: bool = True
    dst: bool = False  # genau eine Stunde Abweichung zählt nicht
    content: bool = False  # zusätzlich Inhalt vergleichen
    mirror: bool = False  # Überzählige im Ziel löschen (Papierkorb)
    include: str = "*"
    exclude: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Options":
        o = cls()
        for k, v in (d or {}).items():
            if hasattr(o, k) and isinstance(v, type(getattr(o, k))):
                setattr(o, k, v)
        if o.direction not in (LR, RL, BOTH):
            o.direction = LR
        return o


@dataclass
class Side:
    size: int
    mtime: float
    is_dir: bool = False
    files: int = 0  # bei Ordnern, die nur auf einer Seite liegen: enthaltene Dateien


@dataclass
class Entry:
    rel: str  # Pfad relativ zum Startordner, „/“ als Trenner
    left: Side | None
    right: Side | None
    status: str = SAME
    action: str = NONE

    @property
    def is_dir(self) -> bool:
        return bool((self.left and self.left.is_dir) or (self.right and self.right.is_dir))

    @property
    def name(self) -> str:
        return self.rel.rsplit("/", 1)[-1]


def patterns(text: str) -> list[str]:
    return [p.strip() for p in (text or "").replace(",", ";").split(";") if p.strip()]


def _matches(name: str, pats: list[str]) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, p.lower()) for p in pats)


def wanted(name: str, is_dir: bool, opts: Options) -> bool:
    """Filter (L-1613): Ausschlüsse gelten für Dateien und Ordner, Einschlüsse nur für Dateien."""
    if _matches(name, patterns(opts.exclude)):
        return False
    if is_dir:
        return True
    inc = patterns(opts.include) or ["*"]
    return _matches(name, inc)


def same_time(a: float, b: float, opts: Options) -> int:
    """0 = gleich, sonst 1 (a neuer) bzw. -1 (b neuer)."""
    d = a - b
    if abs(d) <= TOLERANCE or (opts.dst and abs(abs(d) - HOUR) <= TOLERANCE):
        return 0
    return 1 if d > 0 else -1


def compare_files(lpath: str, rpath: str, left: Side, right: Side, opts: Options) -> str:
    t = same_time(left.mtime, right.mtime, opts)
    if left.size == right.size and t == 0:
        if opts.content:
            try:
                if not filecmp.cmp(lpath, rpath, shallow=False):
                    return CONFLICT
            except OSError:
                return CONFLICT
        return SAME
    if t == 0:
        return CONFLICT  # gleiche Zeit, aber anderer Inhalt: unklar, welche Seite stimmt (L-1617)
    return LEFT_NEWER if t > 0 else RIGHT_NEWER


def _side(path: str) -> Side | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    import stat as _stat

    return Side(st.st_size, st.st_mtime, _stat.S_ISDIR(st.st_mode))


def _listdir(path: str) -> dict[str, Side]:
    out = {}
    try:
        names = os.listdir(path)
    except OSError:
        return out
    for name in names:
        s = _side(os.path.join(path, name))
        if s is not None:
            out[name] = s
    return out


def _count(path: str, opts: Options) -> tuple[int, int]:
    """Dateien und Bytes in einem Ordner (mit Filter)."""
    files = size = 0
    for root, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs if wanted(d, True, opts)]
        for n in names:
            if wanted(n, False, opts):
                try:
                    size += os.path.getsize(os.path.join(root, n))
                    files += 1
                except OSError:
                    pass
    return files, size


def scan(left: str, right: str, opts: Options, cancel: threading.Event | None = None) -> list[Entry]:
    """Alle Einträge beider Seiten mit Zustand und vorgeschlagener Aktion."""
    out: list[Entry] = []

    def walk(rel: str) -> None:
        if cancel is not None and cancel.is_set():
            return
        lp = os.path.join(left, *rel.split("/")) if rel else left
        rp = os.path.join(right, *rel.split("/")) if rel else right
        ls, rs = _listdir(lp), _listdir(rp)
        for name in sorted(set(ls) | set(rs), key=lambda n: (n.lower(), n)):
            a, b = ls.get(name), rs.get(name)
            is_dir = bool((a and a.is_dir) or (b and b.is_dir))
            if not wanted(name, is_dir, opts):
                continue
            r = f"{rel}/{name}" if rel else name
            if a is not None and b is not None and a.is_dir != b.is_dir:
                out.append(Entry(r, a, b, CONFLICT))  # Datei hier, Ordner dort
                continue
            if is_dir:
                if a is not None and b is not None:
                    if opts.subdirs:
                        walk(r)
                    continue
                if not opts.subdirs:
                    continue
                one = a or b
                one.files, one.size = _count(os.path.join(lp if a else rp, name), opts)
                out.append(Entry(r, a, b, LEFT_ONLY if a else RIGHT_ONLY))
                continue
            if a is None or b is None:
                out.append(Entry(r, a, b, LEFT_ONLY if a else RIGHT_ONLY))
            else:
                out.append(Entry(r, a, b, compare_files(os.path.join(lp, name), os.path.join(rp, name), a, b, opts)))

    walk("")
    for e in out:
        e.action = default_action(e, opts)
    return out


def default_action(e: Entry, opts: Options) -> str:
    s, d = e.status, opts.direction
    if s in (SAME, CONFLICT):
        return NONE
    if d == BOTH:
        return {LEFT_ONLY: TO_RIGHT, RIGHT_ONLY: TO_LEFT, LEFT_NEWER: TO_RIGHT, RIGHT_NEWER: TO_LEFT}[s]
    # Eine Richtung: Ist das Ziel neuer, wird es nur beim Spiegeln überschrieben (sonst „nichts tun“,
    # damit keine neuere Fassung verloren geht)
    if d == LR:
        if s in (LEFT_ONLY, LEFT_NEWER):
            return TO_RIGHT
        if s == RIGHT_NEWER:
            return TO_RIGHT if opts.mirror else NONE
        return DEL_RIGHT if opts.mirror else NONE  # RIGHT_ONLY
    if s in (RIGHT_ONLY, RIGHT_NEWER):
        return TO_LEFT
    if s == LEFT_NEWER:
        return TO_LEFT if opts.mirror else NONE
    return DEL_LEFT if opts.mirror else NONE


def allowed(e: Entry, action: str) -> bool:
    if action == NONE:
        return True
    if action == TO_RIGHT:
        return e.left is not None
    if action == TO_LEFT:
        return e.right is not None
    if action == DEL_RIGHT:
        return e.right is not None
    if action == DEL_LEFT:
        return e.left is not None
    return False


def set_action(entries: list[Entry], action: str) -> int:
    """Für mehrere Einträge (L-1615); liefert die Zahl der geänderten. Unpassende bleiben, wie sie sind."""
    n = 0
    for e in entries:
        if allowed(e, action):
            e.action = action
            n += 1
    return n


def overwrites(e: Entry) -> bool:
    return (e.action == TO_RIGHT and e.right is not None) or (e.action == TO_LEFT and e.left is not None)


def quick_compare(left: str, right: str, opts: Options | None = None) -> tuple[list[str], list[str]]:
    """Ordner vergleichen (L-1600): Namen links bzw. rechts, die nur dort liegen oder dort neuer sind."""
    o = Options(**{**(opts or Options()).to_dict(), "subdirs": False})
    left_names, right_names = [], []
    for e in scan(left, right, o):
        if e.is_dir:
            continue
        if e.status in (LEFT_ONLY, LEFT_NEWER):
            left_names.append(e.rel)
        elif e.status in (RIGHT_ONLY, RIGHT_NEWER):
            right_names.append(e.rel)
        elif e.status == CONFLICT:
            if e.left is not None:
                left_names.append(e.rel)
            if e.right is not None:
                right_names.append(e.rel)
    return left_names, right_names


# --- Ausführen --------------------------------------------------------------------------------------------
@dataclass
class Result:
    copied: int = 0
    overwritten: int = 0
    deleted: int = 0
    errors: list = field(default_factory=list)  # (relativer Pfad, Meldung)
    cancelled: bool = False

    @property
    def failed(self) -> int:
        return len(self.errors)


class Cancelled(Exception):
    pass


def _copy_file(src: str, dst: str, cancel) -> None:
    """Erst in eine temporäre Datei, dann umbenennen – so bleibt bei Fehlern keine halbe Datei zurück."""
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    tmp = os.path.join(os.path.dirname(dst), f".{os.path.basename(dst)}.panepilot-sync")
    try:
        with open(src, "rb") as fi, open(tmp, "wb") as fo:
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                buf = fi.read(1 << 20)
                if not buf:
                    break
                fo.write(buf)
        shutil.copystat(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _copy_tree(src: str, dst: str, opts: Options, cancel) -> int:
    n = 0
    os.makedirs(dst, exist_ok=True)
    for root, dirs, names in os.walk(src):
        dirs[:] = sorted(d for d in dirs if wanted(d, True, opts))
        target = os.path.join(dst, os.path.relpath(root, src))
        os.makedirs(target, exist_ok=True)
        for name in sorted(names):
            if wanted(name, False, opts):
                _copy_file(os.path.join(root, name), os.path.join(target, name), cancel)
                n += 1
        try:
            shutil.copystat(root, target)
        except OSError:
            pass
    return n


def execute(entries: list[Entry], left: str, right: str, opts: Options, trash, progress=None,
            cancel: threading.Event | None = None) -> Result:
    """Führt die Aktionen aus. trash(path) verschiebt in den Papierkorb (L-1616).

    progress(done_bytes, total_bytes, rel) wird nach jedem Eintrag gemeldet."""
    res = Result()
    todo = [e for e in entries if e.action != NONE]
    total = sum((e.left if e.action == TO_RIGHT else e.right).size for e in todo
                if e.action in (TO_RIGHT, TO_LEFT)) or 1
    done = 0
    for e in todo:
        if cancel is not None and cancel.is_set():
            res.cancelled = True
            break
        lp = os.path.join(left, *e.rel.split("/"))
        rp = os.path.join(right, *e.rel.split("/"))
        try:
            if e.action in (TO_RIGHT, TO_LEFT):
                src, dst, side = (lp, rp, e.left) if e.action == TO_RIGHT else (rp, lp, e.right)
                over = overwrites(e)
                if side.is_dir:
                    if over and os.path.isfile(dst):
                        raise OSError("file exists")
                    n = _copy_tree(src, dst, opts, cancel)
                    res.copied += n
                else:
                    if os.path.isdir(dst):
                        raise OSError("folder exists")
                    _copy_file(src, dst, cancel)
                    if over:
                        res.overwritten += 1
                    else:
                        res.copied += 1
                done += side.size
            elif e.action in (DEL_RIGHT, DEL_LEFT):
                trash(rp if e.action == DEL_RIGHT else lp)
                res.deleted += 1
        except Cancelled:
            res.cancelled = True
            break
        except OSError as exc:
            res.errors.append((e.rel, exc.strerror or str(exc)))
        if progress is not None:
            progress(done, total, e.rel)
    return res


def summary_counts(entries: list[Entry]) -> dict:
    c = {"to_right": 0, "to_left": 0, "delete": 0, "conflict": 0, "bytes": 0}
    for e in entries:
        if e.action == TO_RIGHT:
            c["to_right"] += 1
            c["bytes"] += e.left.size
        elif e.action == TO_LEFT:
            c["to_left"] += 1
            c["bytes"] += e.right.size
        elif e.action in (DEL_RIGHT, DEL_LEFT):
            c["delete"] += 1
        if e.status == CONFLICT:
            c["conflict"] += 1
    return c
