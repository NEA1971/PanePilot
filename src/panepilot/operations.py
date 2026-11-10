"""Steuert laufende Dateioperationen: Fortschrittsfenster, Konfliktdialoge, Fehler."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from .dialogs import ConflictDialog, ErrorListDialog, ProgressDialog
from .fileops import COMPRESS, COPY, DELETE, EXTRACT, MOVE, PURGE, RESTORE, TRASH, ConflictDecision, OperationResult, OperationThread
from .i18n import t

TITLES = {COPY: "title.copy", MOVE: "title.move", TRASH: "title.trash", DELETE: "title.delete",
          RESTORE: "title.restore", PURGE: "title.delete", COMPRESS: "title.compress", EXTRACT: "title.extract"}


class OperationController(QObject):
    finished = Signal(str, str, list)  # Art, Zielordner, neu angelegte Namen

    def __init__(self, parent_widget) -> None:
        super().__init__(parent_widget)
        self._parent = parent_widget
        self._running: list[tuple[OperationThread, ProgressDialog, QTimer]] = []

    def is_busy(self) -> bool:
        return bool(self._running)

    def start(self, kind: str, sources: list[str], target_dir: str = "", trash_info: dict | None = None,
              options: dict | None = None) -> OperationThread:
        thread = OperationThread(kind, sources, target_dir, self, trash_info=trash_info, options=options)
        dialog = ProgressDialog(self._parent, t(TITLES[kind]))
        dialog.cancel_requested.connect(thread.cancel)
        show_timer = QTimer(self)
        show_timer.setSingleShot(True)
        show_timer.setInterval(400)
        show_timer.timeout.connect(dialog.show)
        thread.progress.connect(dialog.update_progress)
        thread.conflict.connect(lambda s, d, same, sug, th=thread: self._on_conflict(th, s, d, same, sug))
        thread.done.connect(lambda result, th=thread: self._on_done(th, result))
        entry = (thread, dialog, show_timer)
        self._running.append(entry)
        show_timer.start()
        thread.start()
        return thread

    def _on_conflict(self, thread: OperationThread, src: str, dst: str, same: bool, suggestion: str) -> None:
        dlg = ConflictDialog(self._parent, src, dst, same, suggestion)
        dlg.exec()
        thread.reply(dlg.decision if dlg.decision else ConflictDecision("cancel"))

    def _on_done(self, thread: OperationThread, result: OperationResult) -> None:
        for entry in list(self._running):
            if entry[0] is thread:
                _th, dialog, timer = entry
                timer.stop()
                dialog.hide()
                dialog.deleteLater()
                self._running.remove(entry)
        thread.wait()
        if result.errors:
            ErrorListDialog(
                self._parent,
                t(TITLES[thread.kind]),
                t("errors.intro"),
                result.errors,
            ).exec()
        self.finished.emit(thread.kind, thread.target_dir, result.created)
        thread.deleteLater()

    def wait_all(self, msecs: int = 3000) -> None:
        for thread, _dialog, _timer in list(self._running):
            thread.cancel()
            thread.wait(msecs)
