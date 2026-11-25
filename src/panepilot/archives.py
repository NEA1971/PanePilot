"""Archive packen und entpacken (F-530 ff., F-540 ff.).

zip und tar (auch .gz/.bz2/.xz) erledigt Python selbst. Für .7z und .rar werden
installierte Programme genutzt (7zip, rar, unrar); fehlen sie, sind die
entsprechenden Einträge in der Oberfläche ausgegraut.

Die Funktionen laufen im Hintergrund-Thread der Dateioperationen. Fortschritt
und Abbruch laufen über Rückruffunktionen.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import tarfile
import time
import zipfile
from dataclasses import dataclass
from typing import Callable

from .i18n import t

CHUNK = 1024 * 1024

ZIP, TAR, TAR_GZ, TAR_BZ2, TAR_XZ, SEVEN_Z, RAR = "zip", "tar", "tar.gz", "tar.bz2", "tar.xz", "7z", "rar"
# Reihenfolge der Auswahlliste im Dialog „Komprimieren“
CREATE_FORMATS = (ZIP, TAR, TAR_GZ, TAR_BZ2, TAR_XZ, SEVEN_Z, RAR)
FORMAT_EXT = {ZIP: ".zip", TAR: ".tar", TAR_GZ: ".tar.gz", TAR_BZ2: ".tar.bz2", TAR_XZ: ".tar.xz",
              SEVEN_Z: ".7z", RAR: ".rar"}
# Erkennung an der Endung (längste zuerst)
_EXT_TO_FORMAT = (
    (".tar.gz", TAR_GZ), (".tar.bz2", TAR_BZ2), (".tar.xz", TAR_XZ),
    (".tgz", TAR_GZ), (".tbz2", TAR_BZ2), (".tbz", TAR_BZ2), (".txz", TAR_XZ),
    (".tar", TAR), (".zip", ZIP), (".7z", SEVEN_Z), (".rar", RAR),
)
_TAR_MODES = {TAR: "", TAR_GZ: "gz", TAR_BZ2: "bz2", TAR_XZ: "xz"}


class Cancelled(Exception):
    pass


class ArchiveError(Exception):
    pass


# --- Erkennung -------------------------------------------------------------------------
def archive_format(name: str) -> str | None:
    low = name.lower()
    for ext, fmt in _EXT_TO_FORMAT:
        if low.endswith(ext) and len(low) > len(ext):
            return fmt
    return None


def archive_stem(name: str) -> str:
    """'fotos.tar.gz' → 'fotos'."""
    low = name.lower()
    for ext, _fmt in _EXT_TO_FORMAT:
        if low.endswith(ext) and len(low) > len(ext):
            return name[: -len(ext)]
    return name


# --- Zusatzprogramme -----------------------------------------------------------------
def seven_zip() -> str | None:
    for prog in ("7z", "7zz", "7za"):
        path = shutil.which(prog)
        if path:
            return path
    return None


def rar_tool() -> str | None:
    return shutil.which("rar")


def unrar_tool() -> str | None:
    return shutil.which("unrar") or shutil.which("rar")


def can_create(fmt: str) -> bool:
    if fmt == SEVEN_Z:
        return seven_zip() is not None
    if fmt == RAR:
        return rar_tool() is not None
    return fmt in FORMAT_EXT


def can_extract(fmt: str | None) -> bool:
    if fmt == SEVEN_Z:
        return seven_zip() is not None
    if fmt == RAR:
        return unrar_tool() is not None or seven_zip() is not None
    return fmt in FORMAT_EXT


def missing_hint(fmt: str, create: bool) -> str:
    """Infotext für ausgegraute Einträge: welches Paket fehlt."""
    if fmt == SEVEN_Z:
        return t("archive.needs_package", package="7zip")
    if fmt == RAR:
        return t("archive.needs_package", package="rar") if create else t("archive.needs_unrar")
    return ""


def unique_archive_name(directory: str, stem: str, fmt: str) -> str:
    """'Name.zip', sonst 'Name (2).zip', 'Name (3).zip' … (F-534)."""
    ext = FORMAT_EXT[fmt]
    candidate = stem + ext
    n = 2
    while os.path.lexists(os.path.join(directory, candidate)):
        candidate = f"{stem} ({n}){ext}"
        n += 1
    return candidate


def _child_env() -> dict[str, str]:
    from .util import child_environment

    env = child_environment()
    return {k: env.value(k) for k in env.keys()}


# --- Hilfen ------------------------------------------------------------------------------
@dataclass
class _Ctx:
    progress: Callable[[int, str], None]  # (Bytes seit letztem Aufruf, Name)
    is_cancelled: Callable[[], bool]
    error: Callable[[str, str], None]

    def check(self) -> None:
        if self.is_cancelled():
            raise Cancelled()


class _CountingReader:
    """Datei-Wrapper: meldet gelesene Bytes und bricht bei Bedarf ab."""

    def __init__(self, fobj, ctx: _Ctx, name: str) -> None:
        self._f = fobj
        self._ctx = ctx
        self._name = name

    def read(self, size: int = -1) -> bytes:
        self._ctx.check()
        data = self._f.read(size)
        if data:
            self._ctx.progress(len(data), self._name)
        return data


def _walk_sources(sources: list[str]):
    """Liefert (Pfad, Name im Archiv) für alle Einträge; Basis ist der jeweilige Elternordner."""
    for src in sources:
        src = src.rstrip(os.sep) or src
        base = os.path.dirname(src)
        yield src, os.path.relpath(src, base)
        if os.path.isdir(src) and not os.path.islink(src):
            for root, dirs, files in os.walk(src, onerror=lambda e: None):
                dirs.sort()
                for name in sorted(dirs) + sorted(files):
                    full = os.path.join(root, name)
                    yield full, os.path.relpath(full, base)


def total_size(sources: list[str]) -> int:
    from .fileops import tree_size

    return sum(tree_size(s) for s in sources)


# --- Packen ------------------------------------------------------------------------------
def create_archive(sources: list[str], archive: str, fmt: str, ctx: _Ctx) -> None:
    """Packt sources nach archive. Bei Abbruch/Fehler wird das unvollständige Archiv gelöscht (F-535)."""
    try:
        if fmt == ZIP:
            _create_zip(sources, archive, ctx)
        elif fmt in _TAR_MODES:
            _create_tar(sources, archive, fmt, ctx)
        elif fmt == SEVEN_Z:
            prog = seven_zip()
            if not prog:
                raise ArchiveError(missing_hint(fmt, True))
            _create_external([prog, "a", "-t7z", "-mx=5", "-bsp1", "-bso0", "-y", archive, "--"], sources, ctx)
        elif fmt == RAR:
            prog = rar_tool()
            if not prog:
                raise ArchiveError(missing_hint(fmt, True))
            _create_external([prog, "a", "-m3", "-r", "-y", archive, "--"], sources, ctx)
        else:
            raise ArchiveError(t("archive.unknown_format"))
    except BaseException:
        try:
            if os.path.lexists(archive):
                os.unlink(archive)
        except OSError:
            pass
        raise


def _create_zip(sources: list[str], archive: str, ctx: _Ctx) -> None:
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as zf:
        for path, arcname in _walk_sources(sources):
            ctx.check()
            arcname = arcname.replace(os.sep, "/")
            try:
                if os.path.islink(path) and os.path.isdir(path):
                    ctx.error(path, t("archive.link_dir_skipped"))
                    continue
                if os.path.isdir(path):
                    zf.write(path, arcname + "/")
                    continue
                if not os.path.isfile(path):
                    continue  # Gerätedateien, Sockets …
                info = zipfile.ZipInfo.from_file(path, arcname)
                info.compress_type = zipfile.ZIP_DEFLATED
                name = os.path.basename(path)
                with open(path, "rb") as fin, zf.open(info, "w", force_zip64=True) as fout:
                    while True:
                        ctx.check()
                        chunk = fin.read(CHUNK)
                        if not chunk:
                            break
                        fout.write(chunk)
                        ctx.progress(len(chunk), name)
            except OSError as exc:
                ctx.error(path, exc.strerror or str(exc))


def _create_tar(sources: list[str], archive: str, fmt: str, ctx: _Ctx) -> None:
    mode = "x:" + _TAR_MODES[fmt] if _TAR_MODES[fmt] else "x"
    kwargs = {"compresslevel": 6} if fmt == TAR_GZ else {}
    with tarfile.open(archive, mode, **kwargs) as tar:
        for path, arcname in _walk_sources(sources):
            ctx.check()
            try:
                info = tar.gettarinfo(path, arcname)
                if info is None:
                    continue  # Sockets o. Ä.
                if info.isreg():
                    with open(path, "rb") as fin:
                        tar.addfile(info, _CountingReader(fin, ctx, os.path.basename(path)))
                else:
                    tar.addfile(info)
            except OSError as exc:
                ctx.error(path, exc.strerror or str(exc))


# --- Entpacken ---------------------------------------------------------------------------
def uncompressed_size(archive: str, fmt: str) -> int:
    """Gesamtgröße des Inhalts (für den Fortschritt); bei 7z/rar die Archivgröße."""
    try:
        if fmt == ZIP:
            with zipfile.ZipFile(archive) as zf:
                return sum(i.file_size for i in zf.infolist())
        if fmt in _TAR_MODES:
            with tarfile.open(archive, "r:*") as tar:
                return sum(m.size for m in tar.getmembers() if m.isreg())
        return os.path.getsize(archive)
    except (OSError, zipfile.BadZipFile, tarfile.TarError, EOFError):
        return 0


def _safe_relpath(name: str) -> str | None:
    """Pfad im Archiv → sicherer relativer Pfad, oder None, wenn er nach außen zeigt (F-544)."""
    name = name.replace("\\", "/")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return None if ".." in parts else ""
    return os.path.join(*parts)


def extract_archive(archive: str, fmt: str, dest: str, ctx: _Ctx) -> None:
    """Entpackt archive vollständig nach dest (einem leeren Hilfsordner)."""
    if fmt == ZIP:
        _extract_zip(archive, dest, ctx)
    elif fmt in _TAR_MODES:
        _extract_tar(archive, dest, ctx)
    elif fmt in (SEVEN_Z, RAR):
        size = max(os.path.getsize(archive), 1)
        prog = seven_zip()
        if fmt == RAR and unrar_tool():
            cmd = [unrar_tool(), "x", "-y", "-p-", "-idc", archive, dest + os.sep]
        elif prog:
            cmd = [prog, "x", "-y", "-bsp1", "-bso0", "-o" + dest, archive]
        else:
            raise ArchiveError(missing_hint(fmt, False))
        _run_tool(cmd, os.path.dirname(archive) or ".", size, os.path.basename(archive), ctx)
        _drop_escaping_links(dest, ctx)
    else:
        raise ArchiveError(t("archive.unknown_format"))


def _write_stream(src, target: str, name: str, ctx: _Ctx) -> None:
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as fout:
        while True:
            ctx.check()
            chunk = src.read(CHUNK)
            if not chunk:
                break
            fout.write(chunk)
            ctx.progress(len(chunk), name)


def _extract_zip(archive: str, dest: str, ctx: _Ctx) -> None:
    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise ArchiveError(t("archive.damaged", reason=str(exc))) from exc
    with zf:
        for info in zf.infolist():
            ctx.check()
            rel = _safe_relpath(info.filename)
            if rel is None:
                ctx.error(info.filename, t("archive.outside_target"))
                continue
            if not rel:
                continue
            target = os.path.join(dest, rel)
            try:
                if info.is_dir():
                    os.makedirs(target, exist_ok=True)
                    continue
                if info.flag_bits & 0x1:
                    ctx.error(info.filename, t("archive.encrypted"))
                    continue
                with zf.open(info) as src:
                    _write_stream(src, target, os.path.basename(rel), ctx)
                mode = (info.external_attr >> 16) & 0o777
                if mode & 0o111:
                    os.chmod(target, 0o755)
                mtime = time.mktime(info.date_time + (0, 0, -1))
                os.utime(target, (mtime, mtime))
            except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as exc:
                ctx.error(info.filename, getattr(exc, "strerror", None) or str(exc))


def _extract_tar(archive: str, dest: str, ctx: _Ctx) -> None:
    try:
        tar = tarfile.open(archive, "r:*")
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise ArchiveError(t("archive.damaged", reason=str(exc))) from exc
    dirs = []
    with tar:
        for member in tar:
            ctx.check()
            try:
                safe = tarfile.data_filter(member, dest)  # verhindert Pfade/Verknüpfungen nach außen (F-544)
            except tarfile.FilterError:
                ctx.error(member.name, t("archive.outside_target"))
                continue
            if safe is None:
                continue
            rel = _safe_relpath(safe.name)
            if not rel:
                if rel is None:
                    ctx.error(member.name, t("archive.outside_target"))
                continue
            target = os.path.join(dest, rel)
            try:
                if safe.isreg():
                    src = tar.extractfile(member)
                    if src is None:
                        continue
                    with src:
                        _write_stream(src, target, os.path.basename(rel), ctx)
                    if safe.mode is not None:
                        os.chmod(target, safe.mode & 0o777)
                    os.utime(target, (safe.mtime, safe.mtime))
                elif safe.isdir():
                    os.makedirs(target, exist_ok=True)
                    dirs.append((target, safe))
                else:
                    tar.extract(safe, dest, set_attrs=True, filter="fully_trusted")
            except (OSError, tarfile.TarError, EOFError) as exc:
                ctx.error(member.name, getattr(exc, "strerror", None) or str(exc))
    for target, info in reversed(dirs):  # Ordnerzeiten zuletzt setzen
        try:
            if info.mode is not None:
                os.chmod(target, (info.mode & 0o777) | stat.S_IRWXU)
            os.utime(target, (info.mtime, info.mtime))
        except OSError:
            pass


def _drop_escaping_links(dest: str, ctx: _Ctx) -> None:
    """Nach dem Entpacken mit 7z/rar: Verknüpfungen, die aus dem Ziel hinaus zeigen, entfernen."""
    real_dest = os.path.realpath(dest)
    for root, dirs, files in os.walk(dest):
        for name in dirs + files:
            full = os.path.join(root, name)
            if os.path.islink(full):
                target = os.path.realpath(full)
                if target != real_dest and not target.startswith(real_dest + os.sep):
                    os.unlink(full)
                    ctx.error(os.path.relpath(full, dest), t("archive.outside_target"))


# --- Externe Programme -------------------------------------------------------------------
_PERCENT = re.compile(rb"(\d{1,3})%")


def _create_external(cmd: list[str], sources: list[str], ctx: _Ctx) -> None:
    base = os.path.dirname(sources[0].rstrip(os.sep))
    names = [os.path.relpath(s.rstrip(os.sep), base) for s in sources]
    _run_tool(cmd + names, base, total_size(sources), os.path.basename(cmd[-2]), ctx)


def _run_tool(cmd: list[str], cwd: str, size: int, label: str, ctx: _Ctx) -> None:
    """Startet ein Packprogramm; wertet Prozentangaben für den Fortschritt aus."""
    import selectors

    try:
        proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=_child_env())
    except OSError as exc:
        raise ArchiveError(exc.strerror or str(exc)) from exc
    output = b""
    reported = 0
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    try:
        while True:
            if ctx.is_cancelled():
                proc.kill()
                proc.wait()
                raise Cancelled()
            if sel.select(timeout=0.2):
                data = os.read(proc.stdout.fileno(), 65536)
                if not data:
                    break
                output = (output + data)[-8192:]
                found = _PERCENT.findall(data)
                if found:
                    pct = min(100, int(found[-1]))
                    done = size * pct // 100
                    if done > reported:
                        ctx.progress(done - reported, label)
                        reported = done
            elif proc.poll() is not None:
                break
        proc.wait()
    finally:
        sel.close()
        proc.stdout.close()
    if size > reported:
        ctx.progress(size - reported, label)
    if proc.returncode not in (0, 1):  # 1 = Warnungen (z. B. einzelne Dateien nicht lesbar)
        text = output.decode("utf-8", "replace").replace("\b", "")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not re.fullmatch(r"\d{1,3}%", ln.strip())]
        raise ArchiveError("\n".join(lines[-4:]) or t("archive.tool_failed", code=proc.returncode))
