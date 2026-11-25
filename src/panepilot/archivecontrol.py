"""Archiv-Knopf und Archive wie einen Ordner (v2.2, L-3200 ff.) – Teil des Hauptfensters."""

from __future__ import annotations

import os
import posixpath

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QMenu, QVBoxLayout

from . import archivefs
from . import archives as ar
from . import archivewrite
from .dialogs import free_window, show_error, show_info
from .i18n import t

# Im Archiv nicht möglich (L-3209, L-3211). Seit v2.8 gehen Verschieben, Neuer Ordner, Umbenennen
# und Löschen (L-3801) – sie laufen über archive_* weiter unten.
ARCHIVE_BLOCKED = {"new_textfile", "open_terminal", "dir_list", "edit_text",
                   "open_with_other", "duplicate", "multi_rename", "meta_wizard", "rename_undo", "search",
                   "checksums", "find_duplicates", "compare_folders", "sync_folders", "properties", "compress",
                   "extract_here", "extract_subfolder", "clip_copy", "clip_cut",
                   "clip_paste", "add_favorite", "archive_open"}
WRITEBACK_INTERVAL_MS = 1500


class PasswordDialog(QDialog):
    def __init__(self, parent, name: str, wrong: bool) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("archive.password_title"))
        lay = QVBoxLayout(self)
        text = t("archive.password_wrong" if wrong else "archive.password_for", name=name)
        label = QLabel(text, self)
        label.setWordWrap(True)
        lay.addWidget(label)
        self.edit = QLineEdit(self)
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        lay.addWidget(self.edit)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        box.button(QDialogButtonBox.StandardButton.Ok).setText(t("button.ok"))
        box.button(QDialogButtonBox.StandardButton.Cancel).setText(t("button.cancel"))
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.setMinimumWidth(400)


def run_with_progress(parent, title: str, text: str, fn):
    """fn(progress, cancelled) im Hintergrund; progress(Anteil 0…1). (Wert, Ausnahme, abgebrochen)."""
    from .dialogs import WaitDialog
    from .remotecontrol import _Task

    state = {"cancel": False, "part": 0.0}
    dlg = WaitDialog(parent, title, text, maximum=1000)
    task = _Task(lambda: fn(lambda part: state.__setitem__("part", part), lambda: state["cancel"]))
    loop = QEventLoop()
    task.finished.connect(loop.quit)
    timer = QTimer()
    timer.setInterval(150)
    timer.timeout.connect(lambda: dlg.setValue(int(1000 * min(max(state["part"], 0.0), 1.0))))

    def cancel() -> None:
        state["cancel"] = True
    dlg.canceled.connect(cancel)
    task.start()
    timer.start()
    if not task.isFinished():
        loop.exec()
    timer.stop()
    dlg.finish()
    task.wait()
    error = task.error
    cancelled = state["cancel"] or isinstance(error, ar.Cancelled)
    return task.value, (None if isinstance(error, ar.Cancelled) else error), cancelled


class ArchiveMixin:
    """Wird in MainWindow eingemischt."""

    # --- Einlesen und Passwort ---------------------------------------------------------------------------
    def ask_archive_password(self, name: str, wrong: bool = False) -> str | None:
        dlg = PasswordDialog(self, name, wrong)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return dlg.edit.text()

    def load_archive_index(self, archive: str):
        """Inhaltsliste lesen (mit Fortschritt, L-3213); fragt nach dem Passwort, wenn nötig (L-3212)."""
        idx = archivefs.cached(archive)
        if idx is not None:
            return idx
        name = os.path.basename(archive)
        password = None
        while True:
            value, error, cancelled = run_with_progress(
                self, t("archive.title"), t("archive.reading", name=name),
                lambda progress, cancel, pw=password: archivefs.read_index(archive, pw, progress, cancel))
            if cancelled:
                return None
            if isinstance(error, archivefs.PasswordNeeded):
                password = self.ask_archive_password(name, wrong=error.wrong)
                if password is None:
                    return None
                continue
            if error is not None:
                show_error(self, t("archive.title"), t("archive.cannot_open", name=name, reason=str(error)))
                return None
            if password is not None:
                value.headers_encrypted = True  # v2.8: schon die Inhaltsliste war verschlüsselt (7z -mhe)
            archivefs.remember(value)
            return value

    def ensure_archive_password(self, idx, inners: list[str]) -> bool:
        if idx.needs_7z and not ar.seven_zip():
            show_error(self, t("archive.title"), t("archive.needs_7z_aes"))
            return False
        wrong = False
        while idx.needs_password(inners):
            pw = self.ask_archive_password(os.path.basename(idx.archive), wrong)
            if pw is None:
                return False
            if archivefs.check_password(idx, pw):
                idx.password = pw
                return True
            wrong = True
        return True

    # --- Öffnen und Entpacken ------------------------------------------------------------------------------
    def archive_open(self, panel, entry) -> None:
        """Datei im Archiv: in einen Zwischenordner entpacken und öffnen (L-3208)."""
        import tempfile

        from .util import open_with_default_app

        idx = panel.archive
        inner = panel.archive_inner(entry.path)
        if idx is None or not inner or not self.ensure_archive_password(idx, [inner]):
            return
        folder = tempfile.mkdtemp(prefix="PanePilot-")
        errors: list[tuple[str, str]] = []

        def work(progress, cancelled):
            size = max(idx.size_of([inner]), 1)
            done = [0]

            def step(n: int, _name: str) -> None:
                done[0] += n
                progress(done[0] / size)
            ctx = ar._Ctx(progress=step, is_cancelled=cancelled, error=lambda p, r: errors.append((p, r)))
            archivefs.extract_items(idx, [inner], posixpath.dirname(inner), folder, ctx)
        _v, error, cancelled = run_with_progress(self, t("archive.title"), t("srv.opening", name=entry.name), work)
        target = os.path.join(folder, entry.name)
        if cancelled:
            return
        if error is not None or errors or not os.path.exists(target):
            reason = str(error) if error is not None else (errors[0][1] if errors else "")
            show_error(self, t("title.open"), t("archive.cannot_open", name=entry.name, reason=reason))
            return
        if not open_with_default_app(target):
            show_error(self, t("title.open"), t("error.open_failed", path=target))
            return
        self._watch_for_writeback(target, idx, inner)

    def archive_unpack(self, panel, paths: list[str], target: str, move: bool = False) -> None:
        from .fileops import UNPACK

        idx = panel.archive
        inners = [panel.archive_inner(p) for p in paths]
        inners = [i for i in inners if i]
        if idx is None or not inners:
            return
        if not os.path.isdir(target):
            show_error(self, t("title.extract"), t("error.target_missing", path=target))
            return
        if not self.ensure_archive_password(idx, inners):
            return
        options = {"index": idx, "items": inners, "base": panel.archive_inner()}
        if move:  # v2.8 (L-3801): heraus verschieben = entpacken, dann im Archiv löschen
            options["on_done"] = lambda result, i=idx: self._archive_after_move_out(i, result)
        self.ops.start(UNPACK, paths, target, options=options)

    def _archive_after_move_out(self, idx, result) -> None:
        moved = list(getattr(result, "unpacked", []) or [])
        if moved and not result.cancelled:
            self.archive_apply(idx, archivewrite.Plan(delete=moved))

    def archive_transfer(self, move: bool, ask: bool = True) -> bool:
        """F5/F6 mit einem Archiv-Fenster. True, wenn erledigt (oder abgelehnt)."""
        src, dst = self.active, self.other
        if dst.in_archive and not src.in_archive:
            if src.in_remote or src.in_trash:
                show_info(self, t("archive.title"), t("archive.no_copy_into"))
                return True
            entries = [e for e in src.target_entries() if not e.is_parent]
            if entries:
                self.archive_add(dst, [e.path for e in entries], dst.archive_inner(), move, ask)
            return True
        if not src.in_archive:
            return False
        entries = [e for e in src.target_entries() if not e.is_parent]
        if not entries:
            return True
        if dst.in_archive or dst.in_remote or dst.in_trash or dst.search_mode:
            show_info(self, t("archive.title"), t("archive.no_copy_into"))
            return True
        if move and not self._archive_writable(src.archive):
            return True
        target = dst.current_path
        if ask and self.settings.get("confirm_copy_move"):
            from .dialogs import CopyMoveDialog

            dlg = CopyMoveDialog(self, move, [e.name for e in entries], target)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return True
            target = dlg.target()
        self.archive_unpack(src, [e.path for e in entries], target, move=move)
        return True

    def archive_drop(self, payload: dict, target: str, action) -> None:
        """Aus einem Archiv-Fenster gezogen → entpacken (Verschieben gibt es nicht)."""
        side = payload.get("side", "")
        if side not in self.sides:
            return
        panel = self.sides[side].panel
        if not panel.in_archive or not os.path.isdir(target):
            return
        move = action == Qt.DropAction.MoveAction
        if move and not self._archive_writable(panel.archive):
            return
        self.archive_unpack(panel, list(payload.get("paths") or []), target, move=move)

    # --- Knopf und Menüs (L-3200 ff.) --------------------------------------------------------------------
    def _archive_target(self):
        """Markiertes bzw. aktuelles Archiv, das sich öffnen lässt."""
        panel = self.active
        if panel.in_archive or panel.in_remote or panel.in_trash:
            return None
        entries = [e for e in panel.target_entries() if not e.is_parent]
        if len(entries) != 1:
            return None
        return entries[0] if panel.can_open_archive(entries[0]) else None

    def do_archive(self) -> None:
        """Klick auf den Knopf: markiertes Archiv öffnen, sonst „Archiv erstellen …“ (L-3201)."""
        if self._archive_target() is not None:
            self.do_archive_open()
        elif not self.active.in_archive:
            self.trigger("compress")

    def do_archive_open(self) -> None:
        entry = self._archive_target()
        if entry is not None:
            self.active.navigate(entry.path)
            self.active.focus_view()

    def _fill_archive_menu(self, menu: QMenu) -> None:
        """Gleiche Einträge für Knopf-Menü und Untermenü im Rechtsklick (L-3200, L-3203)."""
        panel = self.active
        inside = panel.in_archive
        picked = [e for e in panel.target_entries() if not e.is_parent]
        archives_sel = self._selected_archives() if not inside else []
        usable = [p for p in archives_sel if ar.can_extract(ar.archive_format(os.path.basename(p)))]
        hint = ""
        if archives_sel and not usable:
            hint = ar.missing_hint(ar.archive_format(os.path.basename(archives_sel[0])) or "", False)
            menu.setToolTipsVisible(True)

        def add(text: str, aid: str, enabled: bool) -> None:
            act = menu.addAction(text)
            act.setEnabled(enabled)
            if hint and aid.startswith("extract"):
                act.setToolTip(hint)
            act.triggered.connect(lambda _c=False, x=aid: self.trigger(x))

        add(t("menu.archive_open"), "archive_open", self._archive_target() is not None)
        menu.addSeparator()
        add(t("action.extract_here"), "extract_here", bool(usable))
        add(t("action.extract_to"), "extract_to", bool(usable) or (inside and bool(picked)))
        if len(archives_sel) == 1:
            sub = t("action.extract_subfolder_one", name=ar.archive_stem(os.path.basename(archives_sel[0])))
        elif archives_sel:
            sub = t("action.extract_subfolder_many")
        else:
            sub = t("action.extract_subfolder")
        add(sub, "extract_subfolder", bool(usable))
        menu.addSeparator()
        can_pack = bool(picked) and not inside and not panel.in_remote and not panel.in_trash
        add(t("action.compress"), "compress", can_pack)


    # --- In Archive schreiben (v2.8, L-3800 ff.) --------------------------------------------------------------
    def _archive_writable(self, idx) -> bool:
        reason = archivewrite.writable(idx) if idx is not None else t("archive.read_only")
        if reason:
            show_info(self, t("archive.title"), t("archive.cannot_write", reason=reason))
            return False
        if idx.encrypted and not idx.password and not self.ensure_archive_password(idx, None):
            return False
        return True

    def archive_apply(self, idx, plan, title_key: str = "archive.writing") -> bool:
        """Änderungen schreiben (Kopie → Original ersetzen, L-3802), danach alle Fenster mit dem Archiv neu lesen."""
        if plan.empty() or not self._archive_writable(idx):
            return False
        name = os.path.basename(idx.archive)
        _v, error, cancelled = run_with_progress(self, t("archive.title"), t(title_key, name=name),
                                                 lambda progress, cancel: archivewrite.apply(idx, plan, progress,
                                                                                             cancel))
        if error is not None and not cancelled:
            show_error(self, t("archive.title"), t("archive.write_failed", name=name, reason=str(error)))
        if error is None and not cancelled:
            self._archive_reload(idx)
        return error is None and not cancelled

    def _archive_reload(self, idx) -> None:
        archivefs.forget(idx.archive)
        try:
            new = archivefs.read_index(idx.archive, idx.password)
            new.headers_encrypted = idx.headers_encrypted
            archivefs.remember(new)
        except Exception:  # noqa: BLE001 – beim nächsten Öffnen wird neu gefragt
            pass
        for sd in self.sides.values():
            panel = sd.panel
            if panel.in_archive and panel.archive is not None and panel.archive.archive == idx.archive:
                panel.refresh()

    def _ask_archive_conflicts(self, idx, adds: list[tuple[str, str]]):
        """L-3803: dieselbe Rückfrage wie beim Kopieren; liefert die bereinigte Liste oder None (Abbruch)."""
        from .dialogs import ConflictDialog
        from .fileops import ConflictDecision

        out = []
        remembered = None
        for src, dest in adds:
            existing = idx.item(dest)
            if existing is None or existing.is_dir and os.path.isdir(src):
                out.append((src, dest))
                continue
            parent, name = posixpath.split(dest)
            if remembered is not None:
                decision = remembered
            else:
                taken = set((idx.dirs.get(parent) or {}).keys()) | {posixpath.basename(d) for _s, d in out
                                                                    if posixpath.dirname(d) == parent}
                stem, ext = os.path.splitext(name)
                n = 2
                suggestion = f"{stem}-{n}{ext}"
                while suggestion in taken:
                    n += 1
                    suggestion = f"{stem}-{n}{ext}"
                when = existing.mtime
                from datetime import datetime

                from .util import format_size

                info = t("conflict.file_info", size=format_size(existing.size),
                         date=datetime.fromtimestamp(when).strftime("%d.%m.%Y %H:%M") if when else "")
                dlg = ConflictDialog(self, src, archivefs.join(idx.archive, dest), False, suggestion, dst_info=info)
                dlg.exec()
                decision = dlg.decision or ConflictDecision("cancel")
                if decision.apply_all and decision.action in ("overwrite", "skip"):
                    remembered = decision
            if decision.action == "cancel":
                return None
            if decision.action == "skip":
                continue
            if decision.action == "rename":
                new = (decision.new_name or "").strip()
                if not new or "/" in new or idx.item(posixpath.join(parent, new)) is not None:
                    show_error(self, t("archive.title"), t("error.invalid_name", name=new or name))
                    return None
                dest = posixpath.join(parent, new)
            out.append((src, dest))
        return out

    def archive_add(self, panel, paths: list[str], inner: str, move: bool = False, ask: bool = True) -> bool:
        """Dateien/Ordner ins Archiv (F5/F6/Ziehen, L-3801); beim Verschieben danach in den Papierkorb."""
        from .fileops import TRASH

        idx = panel.archive
        if idx is None or not paths or not self._archive_writable(idx):
            return False
        inner = inner.strip("/")
        if ask and self.settings.get("confirm_copy_move"):
            from .dialogs import confirm

            names = ", ".join(os.path.basename(p) for p in paths[:5]) + (" …" if len(paths) > 5 else "")
            where = os.path.basename(idx.archive) + ("/" + inner if inner else "")
            key = "archive.confirm_move_into" if move else "archive.confirm_copy_into"
            if not confirm(self, t("archive.title"), t(key, names=names, where=where)):
                return False
        # Dateien einzeln (Konflikte je Datei), leere Ordner als „neuer Ordner“
        adds, dirs = [], []
        for p in paths:
            dest = posixpath.join(inner, os.path.basename(p.rstrip("/"))) if inner else os.path.basename(p.rstrip("/"))
            for src, d, is_dir in archivewrite._walk_sources(archivewrite.Plan(add=[(p, dest)])):
                (dirs if is_dir else adds).append((src, d) if not is_dir else d)
        adds = self._ask_archive_conflicts(idx, adds)
        if adds is None:
            return False
        plan = archivewrite.Plan(add=adds, mkdir=[d for d in dirs if idx.item(d) is None])
        if plan.empty():
            return False
        ok = self.archive_apply(idx, plan)
        if ok and move:
            self.ops.start(TRASH, paths)
        return ok

    def archive_new_folder(self, panel, name: str) -> None:
        idx = panel.archive
        inner = posixpath.join(panel.archive_inner(), name) if panel.archive_inner() else name
        if idx.item(inner) is not None:
            show_error(self, t("title.new_folder"), t("error.name_exists", name=name))
            return
        if self.archive_apply(idx, archivewrite.Plan(mkdir=[inner])):
            panel.select_names([name], current=name)
            panel.focus_view()

    def archive_rename(self, panel) -> None:
        from .dialogs import ask_text

        entries = [e for e in panel.target_entries() if not e.is_parent]
        if len(entries) != 1:
            return
        entry = entries[0]
        idx = panel.archive
        if not self._archive_writable(idx):
            return
        name = ask_text(self, t("title.rename"), t("archive.rename_label"), entry.name)
        if not name or name == entry.name:
            return
        if "/" in name or name in (".", ".."):
            show_error(self, t("title.rename"), t("error.invalid_name", name=name))
            return
        old = panel.archive_inner(entry.path)
        new = posixpath.join(posixpath.dirname(old), name)
        if idx.item(new) is not None:
            show_error(self, t("title.rename"), t("error.name_exists", name=name))
            return
        if self.archive_apply(idx, archivewrite.Plan(rename=[(old, new)])):
            panel.select_names([name], current=name)

    def archive_delete(self, panel) -> None:
        """F8/Entf im Archiv: endgültig, mit Rückfrage (L-3801)."""
        from .dialogs import confirm

        entries = [e for e in panel.target_entries() if not e.is_parent]
        idx = panel.archive
        if not entries or not self._archive_writable(idx):
            return
        what = t("dialog.one_item", name=entries[0].name) if len(entries) == 1 else t("dialog.n_items",
                                                                                         n=len(entries))
        if not confirm(self, t("title.delete"), t("archive.delete_confirm", what=what, archive=os.path.basename(
                idx.archive)), yes_key="button.delete", default_yes=False, warning=True):
            return
        self.archive_apply(idx, archivewrite.Plan(delete=[panel.archive_inner(e.path) for e in entries]))

    def archive_drop_into(self, panel, paths: list[str], action) -> None:
        """Aus dem anderen Fenster oder einem anderen Programm ins Archiv gezogen."""
        paths = [p for p in paths if os.path.exists(p)]
        if paths:
            self.archive_add(panel, paths, panel.archive_inner(), action == Qt.DropAction.MoveAction, ask=False)

    # --- Zurückschreiben geöffneter Dateien (L-3805) ----------------------------------------------------------
    def _watch_for_writeback(self, path: str, idx, inner: str) -> None:
        if archivewrite.writable(idx):
            return  # nur lesbar: nichts zurückzuschreiben
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            return
        watched = self.__dict__.setdefault("_archive_watched", {})
        watched[path] = {"archive": idx.archive, "inner": inner, "mtime": mtime, "password": idx.password}
        timer = self.__dict__.get("_archive_watch_timer")
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(WRITEBACK_INTERVAL_MS)
            timer.timeout.connect(self._check_writeback)
            self._archive_watch_timer = timer
        timer.start()

    def _check_writeback(self) -> None:
        from PySide6.QtWidgets import QApplication

        from .dialogs import confirm

        watched = self.__dict__.get("_archive_watched") or {}
        if QApplication.activeModalWidget() is not None or getattr(self, "_writeback_busy", False):
            return
        for path, info in list(watched.items()):
            try:
                mtime = os.stat(path).st_mtime
            except OSError:
                continue  # Editor speichert evtl. gerade über Umbenennen – beim nächsten Mal
            if mtime == info["mtime"]:
                continue
            info["mtime"] = mtime
            archive = info["archive"]
            if not os.path.isfile(archive):
                watched.pop(path, None)
                continue
            self._writeback_busy = True
            try:
                if not confirm(self, t("archive.title"), t("archive.writeback_question",
                                                           name=os.path.basename(path),
                                                           archive=os.path.basename(archive))):
                    continue
                idx = archivefs.cached(archive)
                if idx is None:
                    try:
                        idx = archivefs.read_index(archive, info["password"])
                    except Exception as exc:  # noqa: BLE001
                        show_error(self, t("archive.title"), t("archive.write_failed", name=os.path.basename(
                            archive), reason=str(exc)))
                        continue
                    archivefs.remember(idx)
                idx.password = idx.password or info["password"]
                self.archive_apply(idx, archivewrite.Plan(add=[(path, info["inner"])]))
            finally:
                self._writeback_busy = False
        if not watched:
            self._archive_watch_timer.stop()
