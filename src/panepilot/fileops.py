"""Dateioperationen: Kopieren, Verschieben, Papierkorb, endgültig Löschen.

Der eigentliche Ablauf (``OperationEngine``) ist reines Python und damit gut
testbar. ``OperationThread`` führt ihn im Hintergrund aus, damit die
Oberfläche bedienbar bleibt. Rückfragen bei Namenskonflikten werden über eine
Rückruffunktion an den Hauptthread weitergegeben.
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
import threading
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QFile, QThread, Signal

from .i18n import t
from .util import is_inside, unique_name

CHUNK = 1024 * 1024

COPY, MOVE, TRASH, DELETE = "copy", "move", "trash", "delete"
RESTORE, PURGE = "restore", "purge"  # Papierkorb: wiederherstellen / endgültig löschen
COMPRESS, EXTRACT = "compress", "extract"  # Archive (F-530 ff., F-540 ff.)


@dataclass
class ConflictDecision:
    action: str  # "overwrite" | "skip" | "rename" | "cancel"
    new_name: str = ""
    apply_all: bool = False


@dataclass
class OperationResult:
    errors: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False
    created: list[str] = field(default_factory=list)  # Namen auf oberster Ebene im Ziel
    skipped: int = 0


def _reason(exc: OSError) -> str:
    return exc.strerror or str(exc)


def tree_size(path: str) -> int:
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if stat.S_ISLNK(st.st_mode):
        return 0
    if not stat.S_ISDIR(st.st_mode):
        return st.st_size
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for name in files:
            try:
                fst = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            if stat.S_ISREG(fst.st_mode):
                total += fst.st_size
    return total


def _remove_any(path: str) -> None:
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path, onexc=_make_writable_and_retry)
    else:
        os.unlink(path)


def _make_writable_and_retry(func, path, exc) -> None:
    """Schreibgeschützte Ordner (z. B. von Freigaben oder aus Archiven) beim Löschen freigeben.

    Gehören Datei und Ordner dem Benutzer selbst, darf er die Rechte ändern; sonst
    bleibt der ursprüngliche Fehler bestehen.
    """
    if not isinstance(exc, PermissionError):
        raise exc
    parent = os.path.dirname(path)
    try:
        os.chmod(parent, os.stat(parent).st_mode | stat.S_IRWXU)
        if func in (os.rmdir, os.scandir, os.open) and os.path.isdir(path) and not os.path.islink(path):
            os.chmod(path, os.stat(path).st_mode | stat.S_IRWXU)
            shutil.rmtree(path, onexc=_make_writable_and_retry)
            return
        func(path)
    except OSError:
        raise exc from None


def _same_file(a: str, b: str) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def move_to_trash(path: str) -> None:
    result = QFile.moveToTrash(path)
    ok = result[0] if isinstance(result, tuple) else bool(result)
    if not ok:
        raise OSError(errno.EIO, t("error.trash_failed"))


class OperationEngine:
    def __init__(
        self,
        kind: str,
        sources: list[str],
        target_dir: str = "",
        ask_conflict: Callable[[str, str, bool, str], ConflictDecision] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        trash: Callable[[str], None] = move_to_trash,
        trash_info: dict[str, tuple[str, str]] | None = None,
        options: dict | None = None,
    ) -> None:
        # COMPRESS: {"archive": Pfad, "format": Typ}; EXTRACT: {"jobs": [(Archiv, Zielordner), …]}
        self.options = options or {}
        # Für RESTORE/PURGE: Datei im Papierkorb → (ursprünglicher Pfad, .trashinfo)
        self.trash_info = trash_info or {}
        self.kind = kind
        self.sources = list(sources)
        self.target_dir = target_dir
        self._ask = ask_conflict or (lambda s, d, same, sug: ConflictDecision("skip"))
        self._progress = progress or (lambda done, total, name: None)
        self._is_cancelled = is_cancelled or (lambda: False)
        self._trash = trash
        self._remembered: ConflictDecision | None = None
        self.result = OperationResult()
        self._done = 0
        self._total = 0

    # --- Hilfen ---------------------------------------------------------------------
    def _cancelled(self) -> bool:
        if self._is_cancelled():
            self.result.cancelled = True
        return self.result.cancelled

    def _error(self, path: str, reason: str) -> None:
        self.result.errors.append((path, reason))

    def _advance(self, amount: int, name: str) -> None:
        self._done += amount
        self._progress(self._done, max(self._total, 1), name)

    # --- Ablauf ---------------------------------------------------------------------
    def run(self) -> OperationResult:
        if self.kind == COMPRESS:
            return self._run_compress()
        if self.kind == EXTRACT:
            return self._run_extract()
        if self.kind == PURGE:
            self._total = len(self.sources)
            for src in self.sources:
                if self._cancelled():
                    break
                try:
                    _remove_any(src)
                    info = self.trash_info.get(src, ("", ""))[1]
                    if info and os.path.exists(info):
                        os.unlink(info)
                except OSError as exc:
                    self._error(src, _reason(exc))
                self._advance(1, os.path.basename(src))
            return self.result
        if self.kind == RESTORE:
            self._total = sum(tree_size(s) for s in self.sources)
            for src in self.sources:
                if self._cancelled():
                    break
                original, info = self.trash_info.get(src, ("", ""))
                if not original:
                    self._error(src, t("error.restore_unknown"))
                    continue
                try:
                    os.makedirs(os.path.dirname(original), exist_ok=True)
                except OSError as exc:
                    self._error(original, _reason(exc))
                    continue
                final = self._transfer(src, original, move=True, top_level=True)
                if final and not os.path.lexists(src):
                    self.result.created.append(final)
                    try:
                        if info and os.path.exists(info):
                            os.unlink(info)
                    except OSError:
                        pass
            return self.result
        if self.kind in (TRASH, DELETE):
            self._total = len(self.sources)
            for src in self.sources:
                if self._cancelled():
                    break
                try:
                    if self.kind == TRASH:
                        self._trash(src)
                    else:
                        _remove_any(src)
                except OSError as exc:
                    self._error(src, _reason(exc))
                self._advance(1, os.path.basename(src))
            return self.result

        valid = []
        for src in self.sources:
            if os.path.isdir(src) and not os.path.islink(src) and is_inside(self.target_dir, src):
                self._error(src, t("error.into_itself"))
            else:
                valid.append(src)
        self._total = sum(tree_size(s) for s in valid)
        for src in valid:
            if self._cancelled():
                break
            dst = os.path.join(self.target_dir, os.path.basename(src.rstrip(os.sep)))
            final = self._transfer(src, dst, self.kind == MOVE, top_level=True)
            if final:
                self.result.created.append(os.path.basename(final))
        return self.result

    # --- Archive ----------------------------------------------------------------------
    def _archive_ctx(self):
        from .archives import _Ctx

        return _Ctx(progress=self._advance, is_cancelled=self._is_cancelled, error=self._error)

    def _run_compress(self) -> OperationResult:
        from .archives import ArchiveError, Cancelled, create_archive, total_size

        archive = self.options["archive"]
        self._total = total_size(self.sources)
        try:
            create_archive(self.sources, archive, self.options["format"], self._archive_ctx())
            self.result.created.append(os.path.basename(archive))
        except Cancelled:
            self.result.cancelled = True
        except ArchiveError as exc:
            self._error(archive, str(exc))
        except OSError as exc:
            self._error(archive, _reason(exc))
        return self.result

    def _run_extract(self) -> OperationResult:
        """Erst in einen Hilfsordner im Ziel entpacken, dann einsortieren.

        So greift beim Einsortieren der bekannte Konfliktdialog (F-542), und ein
        Abbruch hinterlässt keine halben Dateien im Ziel.
        """
        import tempfile

        from .archives import ArchiveError, Cancelled, archive_format, extract_archive, uncompressed_size

        jobs = [(a, d, archive_format(os.path.basename(a))) for a, d in self.options.get("jobs", [])]
        sizes = [uncompressed_size(a, fmt) for a, _d, fmt in jobs]
        self._total = 2 * sum(sizes)  # Entpacken + Einsortieren
        for (archive, dest, fmt), size in zip(jobs, sizes):
            if self._cancelled():
                break
            target_existed = os.path.isdir(dest)
            try:
                os.makedirs(dest, exist_ok=True)
            except OSError as exc:
                self._error(dest, _reason(exc))
                continue
            if not target_existed and os.path.normpath(os.path.dirname(dest)) == os.path.normpath(self.target_dir):
                self.result.created.append(os.path.basename(dest))
            try:
                tmp = tempfile.mkdtemp(prefix=".panepilot-entpacken-", dir=dest)
            except OSError as exc:
                self._error(dest, _reason(exc))
                continue
            try:
                before = self._done
                extract_archive(archive, fmt, tmp, self._archive_ctx())
                self._done = before + size
                for name in sorted(os.listdir(tmp)):
                    if self._cancelled():
                        break
                    final = self._transfer(os.path.join(tmp, name), os.path.join(dest, name), move=True, top_level=True)
                    if final and target_existed and os.path.normpath(dest) == os.path.normpath(self.target_dir):
                        self.result.created.append(os.path.basename(final))
            except Cancelled:
                self.result.cancelled = True
            except ArchiveError as exc:
                self._error(archive, str(exc))
            except OSError as exc:
                self._error(archive, _reason(exc))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            if not target_existed:
                try:
                    os.rmdir(dest)  # nichts entpackt (Abbruch/Fehler): leeren Ordner wieder entfernen
                    if os.path.basename(dest) in self.result.created:
                        self.result.created.remove(os.path.basename(dest))
                except OSError:
                    pass
        return self.result

    def _resolve_conflict(self, src: str, dst: str) -> ConflictDecision:
        same = _same_file(src, dst)
        suggestion = unique_name(os.path.dirname(dst), os.path.basename(dst))
        if self._remembered is not None:
            decision = ConflictDecision(self._remembered.action, "", True)
        else:
            decision = self._ask(src, dst, same, suggestion)
            if decision.apply_all and decision.action != "cancel":
                self._remembered = ConflictDecision(decision.action, "", True)
        if decision.action == "overwrite" and same:
            decision = ConflictDecision("rename", suggestion)
        if decision.action == "rename":
            name = (decision.new_name or "").strip()
            if not name or "/" in name or os.path.lexists(os.path.join(os.path.dirname(dst), name)):
                name = suggestion
            decision = ConflictDecision("rename", name)
        return decision

    def _transfer(self, src: str, dst: str, move: bool, top_level: bool = False) -> str | None:
        """Überträgt src nach dst. Gibt den tatsächlichen Zielpfad zurück (None = nicht erfolgt)."""
        if self._cancelled():
            return None
        if os.path.lexists(dst):
            src_is_dir = os.path.isdir(src) and not os.path.islink(src)
            dst_is_dir = os.path.isdir(dst) and not os.path.islink(dst)
            if src_is_dir and dst_is_dir and not _same_file(src, dst):
                return dst if self._merge(src, dst, move) is not None else None
            decision = self._resolve_conflict(src, dst)
            if decision.action == "cancel":
                self.result.cancelled = True
                return None
            if decision.action == "skip":
                self.result.skipped += 1
                self._advance(tree_size(src), os.path.basename(src))
                return None
            if decision.action == "rename":
                dst = os.path.join(os.path.dirname(dst), decision.new_name)
            elif decision.action == "overwrite":
                try:
                    _remove_any(dst)
                except OSError as exc:
                    self._error(dst, _reason(exc))
                    return None
        if move:
            try:
                size = tree_size(src)
                os.rename(src, dst)
                self._advance(size, os.path.basename(src))
                return dst
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    self._error(src, _reason(exc))
                    return None
        ok = self._copy_any(src, dst)
        if ok and move:
            try:
                _remove_any(src)
            except OSError as exc:
                self._error(src, t("error.source_not_removed", reason=_reason(exc)))
        return dst if ok or os.path.lexists(dst) else None

    def _merge(self, src: str, dst: str, move: bool) -> str | None:
        try:
            names = sorted(os.listdir(src))
        except OSError as exc:
            self._error(src, _reason(exc))
            return None
        for name in names:
            if self._cancelled():
                return None
            self._transfer(os.path.join(src, name), os.path.join(dst, name), move)
        if move:
            try:
                os.rmdir(src)
            except OSError:
                pass  # nicht leer (übersprungene Einträge) – bleibt stehen
        return dst

    def _copy_any(self, src: str, dst: str) -> bool:
        if self._cancelled():
            return False
        try:
            if os.path.islink(src):
                os.symlink(os.readlink(src), dst)
                return True
            if os.path.isdir(src):
                os.mkdir(dst)
                ok = True
                try:
                    names = sorted(os.listdir(src))
                except OSError as exc:
                    self._error(src, _reason(exc))
                    return False
                for name in names:
                    if self._cancelled():
                        return False
                    ok = self._copy_any(os.path.join(src, name), os.path.join(dst, name)) and ok
                try:
                    shutil.copystat(src, dst)
                except OSError:
                    pass
                return ok
            return self._copy_file(src, dst)
        except OSError as exc:
            self._error(src, _reason(exc))
            return False

    def _copy_file(self, src: str, dst: str) -> bool:
        name = os.path.basename(src)
        complete = False
        try:
            with open(src, "rb") as fin, open(dst, "xb") as fout:
                while True:
                    if self._cancelled():
                        break
                    chunk = fin.read(CHUNK)
                    if not chunk:
                        complete = True
                        break
                    fout.write(chunk)
                    self._advance(len(chunk), name)
        except OSError as exc:
            self._error(src, _reason(exc))
        if not complete:
            try:
                os.unlink(dst)
            except OSError:
                pass
            return False
        try:
            shutil.copystat(src, dst)
        except OSError:
            pass
        return True


class OperationThread(QThread):
    """Führt eine OperationEngine im Hintergrund aus."""

    progress = Signal(int, str)  # Promille, aktueller Name
    conflict = Signal(str, str, bool, str)  # Quelle, Ziel, gleiche Datei, Vorschlag
    done = Signal(object)  # OperationResult

    def __init__(self, kind: str, sources: list[str], target_dir: str = "", parent=None,
                 trash_info: dict | None = None, options: dict | None = None) -> None:
        super().__init__(parent)
        self.options = options or {}
        self.kind = kind
        self.sources = sources
        self.target_dir = target_dir
        self.trash_info = trash_info or {}
        self._cancel = threading.Event()
        self._reply_ready = threading.Event()
        self._reply: ConflictDecision | None = None

    def cancel(self) -> None:
        self._cancel.set()
        self._reply = ConflictDecision("cancel")
        self._reply_ready.set()

    def reply(self, decision: ConflictDecision) -> None:
        self._reply = decision
        self._reply_ready.set()

    def _ask(self, src: str, dst: str, same: bool, suggestion: str) -> ConflictDecision:
        if self._cancel.is_set():
            return ConflictDecision("cancel")
        self._reply_ready.clear()
        self._reply = None
        self.conflict.emit(src, dst, same, suggestion)
        self._reply_ready.wait()
        return self._reply or ConflictDecision("cancel")

    def _progress(self, done: int, total: int, name: str) -> None:
        self.progress.emit(min(1000, int(done * 1000 / max(total, 1))), name)

    def run(self) -> None:
        engine = OperationEngine(
            self.kind,
            self.sources,
            self.target_dir,
            ask_conflict=self._ask,
            progress=self._progress,
            is_cancelled=self._cancel.is_set,
            trash_info=self.trash_info,
            options=self.options,
        )
        result = engine.run()
        self.done.emit(result)
