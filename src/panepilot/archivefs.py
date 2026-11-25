"""Archive wie einen Ordner anzeigen (v2.2, L-3205 ff.).

Ein Archiv wird einmal eingelesen (``ArchiveIndex``); danach blättert das Fenster nur noch in dieser
Liste. Pfade im Fenster sehen aus wie ``/home/alice/Fotos.zip/Urlaub`` – der Teil bis zum Archiv ist
ein echter Pfad, der Rest der Ordner im Archiv („innerer Pfad“, mit „/“ getrennt, ohne führenden „/“).

Das Archiv ist nur lesbar. Entpackt wird mit denselben Hilfen wie in ``archives`` (zip/tar eingebaut,
7z/rar über 7zip bzw. unrar).
"""

from __future__ import annotations

import os
import posixpath
import re
import subprocess
import tarfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

from . import archives as ar
from .i18n import t


class PasswordNeeded(Exception):
    """Das Archiv (oder seine Inhaltsliste) ist verschlüsselt; ``wrong`` = Passwort war falsch."""

    def __init__(self, wrong: bool = False) -> None:
        super().__init__("password")
        self.wrong = wrong


@dataclass
class Item:
    name: str
    is_dir: bool
    size: int = 0
    mtime: float = 0.0
    member: str = ""  # Name im Archiv ("" = Ordner, der nur indirekt vorkommt)
    encrypted: bool = False
    is_link: bool = False


@dataclass
class ArchiveIndex:
    archive: str
    fmt: str
    dirs: dict[str, dict[str, Item]] = field(default_factory=lambda: {"": {}})
    password: str | None = None
    encrypted: bool = False  # mindestens eine Datei verschlüsselt
    needs_7z: bool = False  # zip mit AES-Verschlüsselung (nur mit 7zip)
    headers_encrypted: bool = False  # v2.8: Inhaltsliste nur mit Passwort lesbar (7z -mhe)
    stamp: tuple = ()

    # --- Aufbau -------------------------------------------------------------------------------------
    def add(self, member: str, is_dir: bool, size: int = 0, mtime: float = 0.0, encrypted: bool = False,
            is_link: bool = False) -> None:
        rel = ar._safe_relpath(member)
        if not rel:
            return  # Pfade nach außen und „.“ nicht anzeigen (F-544)
        inner = rel.replace(os.sep, "/")
        parent, name = posixpath.split(inner)
        self._ensure_dir(parent)
        folder = self.dirs[parent]
        if is_dir:
            self._ensure_dir(inner)
            old = folder.get(name)
            item = Item(name, True, 0, mtime or (old.mtime if old else 0.0), member)
            folder[name] = item
            return
        folder[name] = Item(name, False, size, mtime, member, encrypted, is_link)
        if encrypted:
            self.encrypted = True

    def _ensure_dir(self, inner: str) -> None:
        if inner in self.dirs:
            return
        parent, name = posixpath.split(inner)
        self._ensure_dir(parent)
        self.dirs[inner] = {}
        self.dirs[parent].setdefault(name, Item(name, True))

    def fill_dir_times(self) -> None:
        """Ordner ohne eigenen Eintrag: Zeit der jüngsten Datei darin (statt 1970)."""
        def walk(inner: str) -> float:
            newest = 0.0
            for it in (self.dirs.get(inner) or {}).values():
                t_ = walk(posixpath.join(inner, it.name)) if it.is_dir else it.mtime
                if it.is_dir and not it.mtime:
                    it.mtime = t_
                newest = max(newest, it.mtime or 0.0, t_)
            return newest
        walk("")

    # --- Abfragen ------------------------------------------------------------------------------------
    def listdir(self, inner: str) -> list[Item] | None:
        folder = self.dirs.get(inner.strip("/"))
        return None if folder is None else list(folder.values())

    def item(self, inner: str) -> Item | None:
        inner = inner.strip("/")
        if not inner:
            return Item("", True)
        parent, name = posixpath.split(inner)
        return (self.dirs.get(parent) or {}).get(name)

    def files_under(self, inner: str) -> list[Item]:
        """Alle Dateien eines Ordners (rekursiv) bzw. die Datei selbst."""
        inner = inner.strip("/")
        it = self.item(inner)
        if it is None:
            return []
        if not it.is_dir:
            return [it]
        out = []
        for sub in (self.dirs.get(inner) or {}).values():
            out.extend(self.files_under(posixpath.join(inner, sub.name)))
        return out

    def size_of(self, inners: list[str]) -> int:
        return sum(i.size for x in inners for i in self.files_under(x))

    def needs_password(self, inners: list[str] | None = None) -> bool:
        if not self.encrypted or self.password:
            return False
        if inners is None:
            return True
        return any(i.encrypted for x in inners for i in self.files_under(x))


# --- Pfade --------------------------------------------------------------------------------------------
def split_path(path: str) -> tuple[str, str] | None:
    """'/a/Fotos.zip/Urlaub/x' → ('/a/Fotos.zip', 'Urlaub/x'); None, wenn kein Archiv im Pfad steckt."""
    if not path or "://" in path:
        return None
    path = os.path.normpath(path)
    if os.path.isdir(path):
        return None
    head, rest = path, []
    while head and head != os.path.dirname(head):
        if os.path.isfile(head):
            if ar.archive_format(os.path.basename(head)) is None:
                return None
            return head, "/".join(reversed(rest))
        if os.path.isdir(head):
            return None
        head, tail = os.path.split(head)
        rest.append(tail)
    return None


def join(archive: str, inner: str) -> str:
    inner = inner.strip("/")
    return archive + ("/" + inner if inner else "")


def is_archive_file(name: str) -> bool:
    return ar.archive_format(name) is not None


def can_browse(name: str) -> bool:
    return ar.can_extract(ar.archive_format(name))


# --- Einlesen -------------------------------------------------------------------------------------------
_cache: dict[str, ArchiveIndex] = {}
CACHE_SIZE = 6


def _stamp(archive: str) -> tuple:
    st = os.stat(archive)
    return st.st_size, st.st_mtime_ns


def cached(archive: str) -> ArchiveIndex | None:
    idx = _cache.get(archive)
    try:
        if idx is not None and idx.stamp == _stamp(archive):
            return idx
    except OSError:
        pass
    _cache.pop(archive, None)
    return None


def remember(idx: ArchiveIndex) -> None:
    _cache.pop(idx.archive, None)
    _cache[idx.archive] = idx
    while len(_cache) > CACHE_SIZE:
        _cache.pop(next(iter(_cache)))


def forget(archive: str) -> None:
    _cache.pop(archive, None)


class _ProgressFile:
    """Datei-Wrapper fürs Einlesen: meldet den Anteil des gelesenen Archivs und bricht ab."""

    def __init__(self, path: str, progress, cancelled) -> None:
        self._f = open(path, "rb")  # noqa: SIM115
        self._size = max(os.path.getsize(path), 1)
        self._progress, self._cancelled = progress, cancelled

    def read(self, size: int = -1) -> bytes:
        if self._cancelled():
            raise ar.Cancelled()
        data = self._f.read(size)
        self._progress(min(self._f.tell() / self._size, 1.0))
        return data

    def close(self) -> None:
        self._f.close()


def read_index(archive: str, password: str | None = None, progress=lambda f: None,
               cancelled=lambda: False) -> ArchiveIndex:
    """Liest die Inhaltsliste. progress(Anteil 0…1). Wirft ArchiveError, PasswordNeeded, Cancelled."""
    fmt = ar.archive_format(os.path.basename(archive))
    if fmt is None:
        raise ar.ArchiveError(t("archive.unknown_format"))
    idx = ArchiveIndex(archive, fmt, password=password)
    idx.stamp = _stamp(archive)
    if fmt == ar.ZIP:
        _index_zip(idx)
    elif fmt in ar._TAR_MODES:
        _index_tar(idx, progress, cancelled)
    elif fmt == ar.SEVEN_Z or (fmt == ar.RAR and ar.seven_zip()):
        if not ar.seven_zip():
            raise ar.ArchiveError(ar.missing_hint(fmt, False))
        _index_7z(idx, cancelled)
    elif fmt == ar.RAR:
        if not ar.unrar_tool():
            raise ar.ArchiveError(ar.missing_hint(fmt, False))
        _index_unrar(idx, cancelled)
    idx.fill_dir_times()
    progress(1.0)
    return idx


def _index_zip(idx: ArchiveIndex) -> None:
    try:
        zf = zipfile.ZipFile(idx.archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ar.ArchiveError(t("archive.damaged", reason=str(exc))) from exc
    with zf:
        for info in zf.infolist():
            try:
                mtime = time.mktime(info.date_time + (0, 0, -1))
            except (OverflowError, ValueError):
                mtime = 0.0
            enc = bool(info.flag_bits & 0x1)
            if enc and info.compress_type == 99:
                idx.needs_7z = True
            idx.add(info.filename, info.is_dir(), info.file_size, mtime, enc)


def _index_tar(idx: ArchiveIndex, progress, cancelled) -> None:
    raw = _ProgressFile(idx.archive, progress, cancelled)
    try:
        with tarfile.open(fileobj=raw, mode="r|*") as tar:
            for m in tar:
                if m.isdir():
                    idx.add(m.name, True, 0, m.mtime)
                elif m.isreg() or m.issym() or m.islnk():
                    idx.add(m.name, False, m.size if m.isreg() else 0, m.mtime, is_link=not m.isreg())
    except (tarfile.TarError, EOFError, OSError, ValueError) as exc:
        raise ar.ArchiveError(t("archive.damaged", reason=str(exc))) from exc
    finally:
        raw.close()


def _run(cmd: list[str], cancelled) -> tuple[int, str]:
    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=ar._child_env())
    except OSError as exc:
        raise ar.ArchiveError(exc.strerror or str(exc)) from exc
    chunks = []
    while True:
        try:
            out, _ = proc.communicate(timeout=0.2)
            chunks.append(out or b"")
            break
        except subprocess.TimeoutExpired:
            if cancelled():
                proc.kill()
                proc.wait()
                raise ar.Cancelled() from None
    return proc.returncode, b"".join(chunks).decode("utf-8", "replace")


_WRONG_PW = re.compile(r"wrong password|can ?not open encrypted|incorrect password|password is incorrect|"
                       r"enter password|encrypted.*headers", re.I)


def _password_arg_7z(idx: ArchiveIndex) -> str:
    return "-p" + (idx.password or "-")  # „-p-“: kein Passwort, nicht nachfragen


def _parse_time(text: str) -> float:
    text = text.strip().split(",")[0].split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return 0.0


def parse_7z_list(text: str) -> list[dict]:
    """Ausgabe von ``7z l -slt`` → Einträge (Path, Size, Modified, Attributes, Folder, Encrypted)."""
    body = text.split("\n----------\n", 1)
    if len(body) < 2:
        return []
    out, cur = [], {}
    for line in body[1].splitlines():
        if not line.strip():
            if cur.get("Path"):
                out.append(cur)
            cur = {}
            continue
        key, sep, value = line.partition(" = ")
        if sep:
            cur[key.strip()] = value
    if cur.get("Path"):
        out.append(cur)
    return out


def _index_7z(idx: ArchiveIndex, cancelled) -> None:
    code, out = _run([ar.seven_zip(), "l", "-slt", "-sccUTF-8", _password_arg_7z(idx), "--", idx.archive],
                     cancelled)
    if code != 0:
        if _WRONG_PW.search(out):
            raise PasswordNeeded(wrong=bool(idx.password))
        lines = [ln for ln in out.splitlines() if ln.strip()]
        raise ar.ArchiveError("\n".join(lines[-3:]) or t("archive.tool_failed", code=code))
    for e in parse_7z_list(out):
        is_dir = e.get("Folder") == "+" or e.get("Attributes", "").startswith("D")
        try:
            size = int(e.get("Size") or 0)
        except ValueError:
            size = 0
        idx.add(e["Path"], is_dir, size, _parse_time(e.get("Modified", "")), e.get("Encrypted") == "+")


def parse_unrar_list(text: str) -> list[dict]:
    """Ausgabe von ``unrar lt`` → Einträge (Name, Type, Size, mtime, Flags)."""
    out, cur = [], {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition(": ")
        if not sep:
            continue
        key = key.strip()
        if key == "Name":
            if cur.get("Name"):
                out.append(cur)
            cur = {}
        cur[key] = value.strip()
    if cur.get("Name"):
        out.append(cur)
    return out


def _index_unrar(idx: ArchiveIndex, cancelled) -> None:
    code, out = _run([ar.unrar_tool(), "lt", "-p" + (idx.password or "-"), idx.archive], cancelled)
    if code != 0:
        if _WRONG_PW.search(out) or code == 11:
            raise PasswordNeeded(wrong=bool(idx.password))
        lines = [ln for ln in out.splitlines() if ln.strip()]
        raise ar.ArchiveError("\n".join(lines[-3:]) or t("archive.tool_failed", code=code))
    for e in parse_unrar_list(out):
        is_dir = e.get("Type", "").lower().startswith("dir")
        try:
            size = int(e.get("Size") or 0)
        except ValueError:
            size = 0
        idx.add(e["Name"], is_dir, size, _parse_time(e.get("mtime", "")), "encrypted" in e.get("Flags", "").lower())


# --- Passwort prüfen ------------------------------------------------------------------------------------
def check_password(idx: ArchiveIndex, password: str) -> bool:
    """zip: an der ersten verschlüsselten Datei prüfen; sonst erst beim Entpacken (dann Fehlermeldung)."""
    if idx.fmt != ar.ZIP or idx.needs_7z:
        return True
    try:
        with zipfile.ZipFile(idx.archive) as zf:
            for info in zf.infolist():
                if info.flag_bits & 0x1 and not info.is_dir():
                    with zf.open(info, pwd=password.encode("utf-8")) as fh:
                        fh.read(1)
                    return True
    except RuntimeError:
        return False
    except (OSError, zipfile.BadZipFile, NotImplementedError):
        return True
    return True


# --- Entpacken ----------------------------------------------------------------------------------------
def extract_items(idx: ArchiveIndex, inners: list[str], base: str, dest: str, ctx) -> None:
    """Entpackt Dateien/Ordner (innere Pfade) nach dest, relativ zu base (dem Ordner im Archiv).

    dest ist ein leerer Hilfsordner; ``inners`` müssen in ``base`` liegen.
    """
    base = base.strip("/")
    wanted = [x.strip("/") for x in inners]

    def target_of(inner: str) -> str | None:
        rel = posixpath.relpath(inner, base) if base else inner
        if rel.startswith(".."):
            return None
        return os.path.join(dest, *rel.split("/"))

    def selected(inner: str) -> bool:
        return any(inner == w or inner.startswith(w + "/") for w in wanted)

    use_7z = idx.fmt in (ar.SEVEN_Z, ar.RAR) or (idx.fmt == ar.ZIP and idx.needs_7z)
    if use_7z:
        _extract_tool(idx, wanted, base, dest, ctx)
        return
    if idx.fmt == ar.ZIP:
        _extract_zip_items(idx, selected, target_of, ctx)
    else:
        _extract_tar_items(idx, selected, target_of, ctx)
    # leere Ordner mit anlegen
    for w in wanted:
        it = idx.item(w)
        if it is not None and it.is_dir:
            stack = [w]
            while stack:
                d = stack.pop()
                target = target_of(d)
                if target:
                    os.makedirs(target, exist_ok=True)
                stack.extend(posixpath.join(d, s.name) for s in (idx.dirs.get(d) or {}).values() if s.is_dir)


def _inner_of(member: str) -> str:
    rel = ar._safe_relpath(member)
    return rel.replace(os.sep, "/") if rel else ""


def _extract_zip_items(idx: ArchiveIndex, selected, target_of, ctx) -> None:
    pwd = idx.password.encode("utf-8") if idx.password else None
    try:
        zf = zipfile.ZipFile(idx.archive)
    except zipfile.BadZipFile as exc:
        raise ar.ArchiveError(t("archive.damaged", reason=str(exc))) from exc
    with zf:
        for info in zf.infolist():
            ctx.check()
            inner = _inner_of(info.filename)
            if not inner or not selected(inner):
                continue
            target = target_of(inner)
            if target is None:
                continue
            try:
                if info.is_dir():
                    os.makedirs(target, exist_ok=True)
                    continue
                with zf.open(info, pwd=pwd) as src:
                    ar._write_stream(src, target, posixpath.basename(inner), ctx)
                mode = (info.external_attr >> 16) & 0o777
                if mode & 0o111:
                    os.chmod(target, 0o755)
                mtime = time.mktime(info.date_time + (0, 0, -1))
                os.utime(target, (mtime, mtime))
            except RuntimeError as exc:
                if "password" in str(exc).lower():
                    raise ar.ArchiveError(t("archive.wrong_password")) from exc
                ctx.error(info.filename, str(exc))
            except (OSError, zipfile.BadZipFile, ValueError, NotImplementedError) as exc:
                ctx.error(info.filename, getattr(exc, "strerror", None) or str(exc))


def _extract_tar_items(idx: ArchiveIndex, selected, target_of, ctx) -> None:
    try:
        tar = tarfile.open(idx.archive, "r:*")
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ar.ArchiveError(t("archive.damaged", reason=str(exc))) from exc
    with tar:
        for member in tar:
            ctx.check()
            inner = _inner_of(member.name)
            if not inner or not selected(inner):
                continue
            target = target_of(inner)
            if target is None:
                continue
            try:
                if member.isdir():
                    os.makedirs(target, exist_ok=True)
                elif member.isreg():
                    src = tar.extractfile(member)
                    if src is None:
                        continue
                    with src:
                        ar._write_stream(src, target, posixpath.basename(inner), ctx)
                    os.chmod(target, (member.mode or 0o644) & 0o777 | 0o600)
                    os.utime(target, (member.mtime, member.mtime))
                elif member.issym():
                    link = member.linkname
                    if os.path.isabs(link) or ".." in link.replace("\\", "/").split("/"):
                        ctx.error(member.name, t("archive.outside_target"))
                        continue
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    os.symlink(link, target)
            except (OSError, tarfile.TarError, EOFError) as exc:
                ctx.error(member.name, getattr(exc, "strerror", None) or str(exc))


def _extract_tool(idx: ArchiveIndex, wanted: list[str], base: str, dest: str, ctx) -> None:
    """7z/rar (oder AES-zip): mit vollem Pfad in einen Unterordner entpacken, dann umhängen."""
    import shutil
    import tempfile

    work = tempfile.mkdtemp(prefix=".panepilot-archiv-", dir=dest)
    try:
        members = []
        for w in wanted:
            it = idx.item(w)
            members.append(w)
            if it is not None and it.is_dir:
                members.append(w + "/*")
        size = max(idx.size_of(wanted), 1)
        prog = ar.seven_zip()
        if idx.fmt == ar.RAR and not prog and ar.unrar_tool():
            cmd = [ar.unrar_tool(), "x", "-y", "-idc", "-p" + (idx.password or "-"), idx.archive, *members,
                   work + os.sep]
        elif prog:
            cmd = [prog, "x", "-y", "-bsp1", "-bso0", "-o" + work, _password_arg_7z(idx), "--", idx.archive,
                   *[m for m in members if not m.endswith("/*")]]
        else:
            raise ar.ArchiveError(ar.missing_hint(idx.fmt, False))
        try:
            ar._run_tool(cmd, os.path.dirname(idx.archive) or ".", size, os.path.basename(idx.archive), ctx)
        except ar.ArchiveError as exc:
            if _WRONG_PW.search(str(exc)):
                raise ar.ArchiveError(t("archive.wrong_password")) from exc
            raise
        ar._drop_escaping_links(work, ctx)
        root = os.path.join(work, *base.split("/")) if base else work
        for w in wanted:
            rel = posixpath.relpath(w, base) if base else w
            src = os.path.join(work, *w.split("/"))
            if os.path.lexists(src):
                target = os.path.join(dest, *rel.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                os.replace(src, target)
        del root
    finally:
        shutil.rmtree(work, ignore_errors=True)
