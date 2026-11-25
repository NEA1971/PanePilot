"""In Archive schreiben (v2.8, L-3800 ff.): hinzufügen, löschen, umbenennen, neuer Ordner.

Alle Änderungen eines Auftrags werden in **eine Kopie** neben dem Archiv geschrieben; erst wenn alles
geklappt hat, ersetzt die Kopie das Original (L-3802). ZIP und TAR schreibt Python selbst (die Einträge
werden dabei neu geschrieben), 7z und verschlüsselte ZIPs gehen über 7-Zip (L-3804). RAR bleibt nur lesbar.
"""

from __future__ import annotations

import os
import posixpath
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass, field

from . import archives as ar
from .i18n import t

CHUNK = 1024 * 1024


class ReadOnly(ar.ArchiveError):
    """Dieses Archiv lässt sich nicht beschreiben (RAR, oder verschlüsselt ohne 7-Zip)."""


@dataclass
class Plan:
    """Was mit dem Archiv geschehen soll; innere Pfade mit „/“, ohne führenden „/“."""

    add: list[tuple[str, str]] = field(default_factory=list)  # (Datei/Ordner auf der Platte, innerer Zielpfad)
    delete: list[str] = field(default_factory=list)  # innere Pfade (Ordner samt Inhalt)
    rename: list[tuple[str, str]] = field(default_factory=list)  # (alt, neu) – Ordner samt Inhalt
    mkdir: list[str] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.add or self.delete or self.rename or self.mkdir)


def engine(idx) -> str:
    """'zip', 'tar' oder '7z' – wirft ReadOnly, wenn das Archiv nicht beschreibbar ist."""
    fmt = idx.fmt
    if fmt == ar.RAR:
        raise ReadOnly(t("archive.rar_read_only"))
    if fmt == ar.SEVEN_Z or (fmt == ar.ZIP and (idx.encrypted or idx.needs_7z)):
        if not ar.seven_zip():
            raise ReadOnly(t("archive.needs_7z_write"))
        return "7z"
    if fmt == ar.ZIP:
        return "zip"
    if fmt in ar._TAR_MODES:
        return "tar"
    raise ReadOnly(t("archive.unknown_format"))


def writable(idx) -> str | None:
    """None = beschreibbar, sonst der Grund."""
    try:
        engine(idx)
    except ReadOnly as exc:
        return str(exc)
    return None


# --- Pfade umrechnen ------------------------------------------------------------------------------------------
def _under(path: str, top: str) -> bool:
    return path == top or path.startswith(top + "/")


def _map(inner: str, plan: Plan) -> str | None:
    """Neuer innerer Pfad eines vorhandenen Eintrags, None = gelöscht."""
    inner = inner.strip("/")
    for d in plan.delete:
        if _under(inner, d.strip("/")):
            return None
    for old, new in plan.rename:
        old, new = old.strip("/"), new.strip("/")
        if _under(inner, old):
            return new + inner[len(old):]
    return inner


def _walk_sources(plan: Plan) -> list[tuple[str, str, bool]]:
    """(Pfad auf der Platte, innerer Pfad, ist Ordner) für alles, was hinzukommt – Ordner rekursiv."""
    out = []
    for src, dest in plan.add:
        dest = dest.strip("/")
        if os.path.isdir(src) and not os.path.islink(src):
            out.append((src, dest, True))
            for root, dirs, files in os.walk(src):
                dirs.sort()
                rel_root = os.path.relpath(root, src)
                base = dest if rel_root == "." else dest + "/" + rel_root.replace(os.sep, "/")
                for d in dirs:
                    out.append((os.path.join(root, d), f"{base}/{d}", True))
                for f in sorted(files):
                    out.append((os.path.join(root, f), f"{base}/{f}", False))
        else:
            out.append((src, dest, False))
    return out


def total_bytes(plan: Plan, idx) -> int:
    size = sum(os.path.getsize(s) for s, _d, is_dir in _walk_sources(plan) if not is_dir and os.path.isfile(s))
    return size + sum(i.size for i in idx.files_under(""))


# --- Ausführen -------------------------------------------------------------------------------------------------
def apply(idx, plan: Plan, progress=lambda part: None, cancelled=lambda: False) -> None:
    """Schreibt die Änderungen; das Original wird nur bei Erfolg ersetzt. Wirft ArchiveError/Cancelled."""
    if plan.empty():
        return
    kind = engine(idx)
    archive = idx.archive
    folder = os.path.dirname(archive) or "."
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(archive) + ".", suffix=".pp-tmp", dir=folder)
    os.close(fd)
    try:
        if kind == "zip":
            _write_zip(archive, tmp, plan, idx, progress, cancelled)
        elif kind == "tar":
            _write_tar(archive, tmp, plan, idx, progress, cancelled)
        else:
            _write_7z(archive, tmp, plan, idx, progress, cancelled)
        try:
            os.chmod(tmp, stat.S_IMODE(os.stat(archive).st_mode))
        except OSError:
            pass
        os.replace(tmp, archive)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    progress(1.0)


class _Counter:
    def __init__(self, total: int, progress, cancelled) -> None:
        self.total = max(total, 1)
        self.done = 0
        self.progress = progress
        self.cancelled = cancelled

    def add(self, n: int) -> None:
        if self.cancelled():
            raise ar.Cancelled()
        self.done += n
        self.progress(min(self.done / self.total, 0.99))


def _copy_stream(src, dst, counter: _Counter) -> None:
    while True:
        block = src.read(CHUNK)
        if not block:
            return
        dst.write(block)
        counter.add(len(block))


def _new_dirs(plan: Plan) -> list[str]:
    return [d.strip("/") for d in plan.mkdir if d.strip("/")]


def _write_zip(archive, tmp, plan, idx, progress, cancelled) -> None:
    sources = _walk_sources(plan)
    added = {dest for _s, dest, _d in sources}
    counter = _Counter(total_bytes(plan, idx), progress, cancelled)
    try:
        src_zip = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ar.ArchiveError(t("archive.damaged", reason=str(exc))) from exc
    written: set[str] = set()
    with src_zip, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as out:
        for info in src_zip.infolist():
            raw = info.filename
            safe = ar._safe_relpath(raw)
            if safe is None:
                continue  # Pfade nach außen nicht mitnehmen
            inner = safe.replace(os.sep, "/")
            new = _map(inner, plan)
            if new is None or (not info.is_dir() and new in added):
                continue
            key = new + ("/" if info.is_dir() else "")
            if key in written:
                continue
            written.add(key)
            clone = zipfile.ZipInfo(key, info.date_time)
            clone.external_attr = info.external_attr
            clone.compress_type = info.compress_type if info.compress_type in (0, 8, 12, 14) else zipfile.ZIP_DEFLATED
            clone.comment = info.comment
            clone.extra = b""
            if info.is_dir():
                out.writestr(clone, b"")
                continue
            with src_zip.open(info) as fin, out.open(clone, "w", force_zip64=info.file_size > 0x7FFFFFFF) as fout:
                _copy_stream(fin, fout, counter)
        for d in _new_dirs(plan):
            if d + "/" not in written:
                out.writestr(zipfile.ZipInfo(d + "/", time.localtime()[:6]), b"")
                written.add(d + "/")
        for src, dest, is_dir in sources:
            if is_dir:
                if dest + "/" not in written:
                    out.write(src, dest + "/")
                    written.add(dest + "/")
                continue
            info = zipfile.ZipInfo.from_file(src, dest)
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(src, "rb") as fin, out.open(info, "w", force_zip64=os.path.getsize(src) > 0x7FFFFFFF) as fout:
                _copy_stream(fin, fout, counter)


def _write_tar(archive, tmp, plan, idx, progress, cancelled) -> None:
    sources = _walk_sources(plan)
    added = {dest for _s, dest, _d in sources}
    counter = _Counter(total_bytes(plan, idx), progress, cancelled)
    comp = ar._TAR_MODES[idx.fmt]
    try:
        src_tar = tarfile.open(archive, "r:" + comp if comp else "r:")
    except (tarfile.TarError, OSError) as exc:
        raise ar.ArchiveError(t("archive.damaged", reason=str(exc))) from exc
    written: set[str] = set()
    with src_tar, tarfile.open(tmp, "w:" + comp if comp else "w", format=tarfile.PAX_FORMAT) as out:
        for member in src_tar:
            safe = ar._safe_relpath(member.name)
            if safe is None:
                continue
            inner = safe.replace(os.sep, "/")
            new = _map(inner, plan)
            if new is None or (not member.isdir() and new in added) or new in written:
                continue
            written.add(new)
            member.name = new
            if member.isfile():
                fin = src_tar.extractfile(member)
                out.addfile(member, _CountingReader(fin, counter))
            else:
                out.addfile(member)
        for d in _new_dirs(plan):
            if d not in written:
                info = tarfile.TarInfo(d)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.mtime = int(time.time())
                out.addfile(info)
                written.add(d)
        for src, dest, is_dir in sources:
            if dest in written:
                continue
            written.add(dest)
            info = out.gettarinfo(src, dest)
            if info.isfile():
                with open(src, "rb") as fin:
                    out.addfile(info, _CountingReader(fin, counter))
            else:
                out.addfile(info)


class _CountingReader:
    def __init__(self, fh, counter: _Counter) -> None:
        self.fh = fh
        self.counter = counter

    def read(self, n: int = -1) -> bytes:
        data = self.fh.read(n)
        self.counter.add(len(data))
        return data


def _run_7z(args: list[str], cwd: str | None, cancelled) -> None:
    proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, text=True, errors="replace")
    while True:
        try:
            out, _ = proc.communicate(timeout=0.3)
            break
        except subprocess.TimeoutExpired:
            if cancelled():
                proc.kill()
                proc.wait()
                raise ar.Cancelled() from None
    if proc.returncode not in (0, 1):  # 1 = Warnung
        lines = [ln for ln in (out or "").splitlines() if ln.strip()]
        raise ar.ArchiveError("\n".join(lines[-3:]) or t("archive.tool_failed", code=proc.returncode))


def _write_7z(archive, tmp, plan, idx, progress, cancelled) -> None:
    tool = ar.seven_zip()
    pw = ["-p" + idx.password] if idx.password else []  # ohne Passwort kein -p (stdin ist zu, keine Nachfrage)
    if idx.password and idx.fmt == ar.SEVEN_Z and _headers_encrypted(idx):
        pw.append("-mhe=on")  # war die Inhaltsliste verschlüsselt, bleibt sie es
    kind = ["-t7z"] if idx.fmt == ar.SEVEN_Z else ["-tzip"]
    shutil.copy2(archive, tmp)
    progress(0.05)
    # 1. Löschen und ersetzte Dateien entfernen
    sources = _walk_sources(plan)
    added = {dest for _s, dest, is_dir in sources if not is_dir}
    remove = [d.strip("/") for d in plan.delete] + [a for a in added if idx.item(a) is not None]
    if remove:
        _run_7z([tool, "d", *kind, *pw, "-y", tmp, "--", *remove], None, cancelled)
    progress(0.25)
    # 2. Umbenennen (7z benennt auch Ordner samt Inhalt um, wenn jeder Eintrag genannt wird)
    if plan.rename:
        pairs: list[str] = []
        for old, new in plan.rename:
            old, new = old.strip("/"), new.strip("/")
            for item in _all_members(idx, old):
                pairs += [item, new + item[len(old):]]
        if pairs:
            _run_7z([tool, "rn", *kind, *pw, "-y", tmp, "--", *pairs], None, cancelled)
    progress(0.45)
    # 3. Hinzufügen: über einen Bereitstellungsordner mit der richtigen inneren Struktur
    if sources or plan.mkdir:
        stage = tempfile.mkdtemp(prefix="PanePilot-7z-")
        try:
            tops = set()
            for d in _new_dirs(plan):
                os.makedirs(os.path.join(stage, *d.split("/")), exist_ok=True)
                tops.add(d.split("/")[0])
            for src, dest, is_dir in sources:
                target = os.path.join(stage, *dest.split("/"))
                tops.add(dest.split("/")[0])
                if is_dir:
                    os.makedirs(target, exist_ok=True)
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                try:
                    os.link(src, target)  # schnell, ohne Kopie (gleiche Platte)
                except OSError:
                    shutil.copy2(src, target)
            if cancelled():
                raise ar.Cancelled()
            _run_7z([tool, "a", *kind, *pw, "-y", tmp, "--", *sorted(tops)], stage, cancelled)
        finally:
            shutil.rmtree(stage, ignore_errors=True)


def _headers_encrypted(idx) -> bool:
    return bool(getattr(idx, "headers_encrypted", False))


def _all_members(idx, top: str) -> list[str]:
    """Alle Einträge unter top (inklusive top selbst), wie sie im Archiv heißen."""
    out = [top]
    it = idx.item(top)
    if it is not None and it.is_dir:
        stack = [top]
        while stack:
            cur = stack.pop()
            for sub in (idx.dirs.get(cur) or {}).values():
                path = posixpath.join(cur, sub.name)
                out.append(path)
                if sub.is_dir:
                    stack.append(path)
    return out
