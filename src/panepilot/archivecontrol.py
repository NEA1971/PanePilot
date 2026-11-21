"""Archiv-Knopf und Archive wie einen Ordner (v2.2, L-3200 ff.) – Teil des Hauptfensters."""

from __future__ import annotations

import os
import posixpath

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QLineEdit, QMenu, QVBoxLayout

from . import archivefs
from . import archives as ar
from .dialogs import free_window, show_error, show_info
from .i18n import t

# Im Archiv nicht möglich – es ist nur lesbar (L-3209, L-3211)
ARCHIVE_BLOCKED = {"move", "move_direct", "new_folder", "new_textfile", "open_terminal", "dir_list", "edit_text",
                   "open_with_other", "rename", "duplicate", "multi_rename", "meta_wizard", "rename_undo", "search",
                   "checksums", "find_duplicates", "compare_folders", "sync_folders", "properties", "compress",
                   "extract_here", "extract_subfolder", "delete", "delete_permanent", "clip_copy", "clip_cut",
                   "clip_paste", "add_favorite", "archive_open"}


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

    def archive_unpack(self, panel, paths: list[str], target: str) -> None:
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
        self.ops.start(UNPACK, paths, target, options={"index": idx, "items": inners, "base": panel.archive_inner()})

    def archive_transfer(self, move: bool, ask: bool = True) -> bool:
        """F5/F6 mit einem Archiv-Fenster. True, wenn erledigt (oder abgelehnt)."""
        src, dst = self.active, self.other
        if dst.in_archive and not src.in_archive:
            show_info(self, t("archive.title"), t("archive.no_copy_into"))
            return True
        if not src.in_archive:
            return False
        if move:
            show_info(self, t("archive.title"), t("archive.read_only"))
            return True
        entries = [e for e in src.target_entries() if not e.is_parent]
        if not entries:
            return True
        if dst.in_archive or dst.in_remote or dst.in_trash or dst.search_mode:
            show_info(self, t("archive.title"), t("archive.no_copy_into"))
            return True
        target = dst.current_path
        if ask and self.settings.get("confirm_copy_move"):
            from .dialogs import CopyMoveDialog

            dlg = CopyMoveDialog(self, False, [e.name for e in entries], target)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return True
            target = dlg.target()
        self.archive_unpack(src, [e.path for e in entries], target)
        return True

    def archive_drop(self, payload: dict, target: str, action) -> None:
        """Aus einem Archiv-Fenster gezogen → entpacken (Verschieben gibt es nicht)."""
        side = payload.get("side", "")
        if side not in self.sides:
            return
        panel = self.sides[side].panel
        if not panel.in_archive or not os.path.isdir(target):
            return
        if action == Qt.DropAction.MoveAction:
            show_info(self, t("archive.title"), t("archive.read_only"))
        self.archive_unpack(panel, list(payload.get("paths") or []), target)

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
