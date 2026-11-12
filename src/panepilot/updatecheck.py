"""Nach Updates suchen (v1.2).

Wenn eingeschaltet (Vorgabe: aus), fragt PanePilot einmal täglich beim ersten Start bei GitHub nach der
neuesten Version. Über Hilfe ▸ Nach Updates suchen … geht das jederzeit von Hand. Eine neue Version
wird in den Ordner der laufenden AppImage-Datei geladen; die alte Datei bleibt liegen.
"""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressDialog, QPushButton, QTextBrowser,
                               QVBoxLayout)

from . import __version__, netutil
from .i18n import t

API_LATEST = "https://api.github.com/repos/NEA1971/PanePilot/releases/latest"
RELEASES_URL = "https://github.com/NEA1971/PanePilot/releases/latest"


@dataclass
class Release:
    version: str
    notes: str
    page: str
    asset_name: str | None
    asset_url: str | None
    asset_size: int


def version_tuple(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def parse_release(data: dict) -> Release:
    version = str(data.get("tag_name") or "").lstrip("vV")
    asset = next((a for a in data.get("assets") or []
                  if str(a.get("name", "")).endswith("x86_64.AppImage")), None)
    return Release(version=version, notes=str(data.get("body") or ""), page=str(data.get("html_url") or RELEASES_URL),
                   asset_name=asset.get("name") if asset else None,
                   asset_url=asset.get("browser_download_url") if asset else None,
                   asset_size=int(asset.get("size") or 0) if asset else 0)


def fetch_latest() -> Release:
    return parse_release(netutil.get_json(API_LATEST))


def due_today(settings, today: dt.date | None = None) -> bool:
    """Automatische Prüfung: nur wenn eingeschaltet und heute noch nicht geprüft."""
    today = today or dt.date.today()
    return bool(settings.get("update_check")) and settings.get("update_last_check") != today.isoformat()


def target_path(release: Release) -> str | None:
    """Wohin die neue Version geladen wird: in den Ordner der laufenden AppImage-Datei."""
    current = os.environ.get("APPIMAGE")
    if not current or not release.asset_name:
        return None
    folder = os.path.dirname(current)
    return os.path.join(folder, release.asset_name) if os.access(folder, os.W_OK) else None


def _short_notes(notes: str) -> str:
    """Release-Notizen ohne den deutschen Zusatz-Absatz bzw. mit ihm – je nach Sprache."""
    from .i18n import current_language

    parts = notes.split("\n---")
    if len(parts) > 1 and current_language() in ("de", "frk", "sxu"):
        return parts[-1].strip() + "\n\n---\n\n" + parts[0].strip()
    return notes.strip()


class UpdateDialog(QDialog):
    DOWNLOAD, LATER, SKIP = 1, 2, 3

    def __init__(self, parent, release: Release) -> None:
        super().__init__(parent)
        from .dialogs import free_window

        free_window(self)
        self.setWindowTitle(t("update.title"))
        self.resize(640, 480)
        self.choice = self.LATER
        head = QLabel(t("update.available", version=release.version, current=__version__), self)
        head.setWordWrap(True)
        font = head.font()
        font.setBold(True)
        head.setFont(font)
        notes = QTextBrowser(self)
        notes.setOpenExternalLinks(False)
        notes.setMarkdown(_short_notes(release.notes))
        hint = QLabel(t("update.hint_appimage") if target_path(release) else t("update.hint_page"), self)
        hint.setWordWrap(True)
        self.btn_download = QPushButton(t("update.download") if target_path(release) else t("update.open_page"), self)
        self.btn_download.setDefault(True)
        btn_later = QPushButton(t("donate.later"), self)
        btn_skip = QPushButton(t("update.skip"), self)
        self.btn_download.clicked.connect(lambda: self._done(self.DOWNLOAD))
        btn_later.clicked.connect(lambda: self._done(self.LATER))
        btn_skip.clicked.connect(lambda: self._done(self.SKIP))
        row = QHBoxLayout()
        row.addWidget(self.btn_download)
        row.addStretch(1)
        row.addWidget(btn_skip)
        row.addWidget(btn_later)
        layout = QVBoxLayout(self)
        layout.addWidget(head)
        layout.addWidget(notes, 1)
        layout.addWidget(hint)
        layout.addLayout(row)

    def _done(self, choice: int) -> None:
        self.choice = choice
        self.accept()


def download_release(parent, release: Release, target: str) -> bool:
    """Lädt die neue AppImage-Datei mit Fortschritt; True bei Erfolg."""
    from PySide6.QtCore import QEventLoop

    from .dialogs import show_error

    dlg = QProgressDialog(t("update.downloading", name=release.asset_name), t("button.cancel"), 0, 100, parent)
    dlg.setWindowTitle(t("update.title"))
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(0)
    state = {"cancel": False}
    dlg.canceled.connect(lambda: state.__setitem__("cancel", True))

    def work():
        netutil.download(release.asset_url, target,
                         progress=lambda d, tot: task.progress_value.emit(int(d * 100 / tot) if tot else 0),
                         cancel=lambda: state["cancel"])
        os.chmod(target, 0o755)
        return True

    from PySide6.QtCore import Signal

    class _Task(netutil.Task):
        progress_value = Signal(int)

    task = _Task(work, parent)
    task.progress_value.connect(dlg.setValue)
    out: dict = {}
    task.result.connect(lambda v: out.__setitem__("ok", v))
    task.failed.connect(lambda e: out.__setitem__("error", e))
    loop = QEventLoop()
    task.finished.connect(loop.quit)
    task.start()
    loop.exec()
    task.wait()
    cancelled = state["cancel"]
    dlg.canceled.disconnect()
    dlg.close()  # close() meldet selbst „canceled“, deshalb vorher auswerten
    task.deleteLater()
    if cancelled:
        return False
    if "error" in out:
        show_error(parent, t("update.title"), t("update.download_failed", reason=out["error"]))
        return False
    return True


def handle_release(window, release: Release, manual: bool) -> None:
    """Fenster zeigen und die Wahl ausführen."""
    from . import util
    from .dialogs import confirm, show_info

    settings = window.settings
    if not is_newer(release.version):
        if manual:
            show_info(window, t("update.title"), t("update.none", version=__version__))
        return
    if not manual and settings.get("update_skip") == release.version:
        return
    dlg = UpdateDialog(window, release)
    dlg.exec()
    if dlg.choice == UpdateDialog.SKIP:
        settings.set("update_skip", release.version)
        return
    if dlg.choice != UpdateDialog.DOWNLOAD:
        return
    target = target_path(release)
    if target is None:
        util.open_url(release.page)
        return
    if not os.path.exists(target) and not download_release(window, release, target):
        return
    if confirm(window, t("update.title"), t("update.restart", name=os.path.basename(target)),
               yes_key="button.restart_now", no_key="donate.later"):
        restart_into(window, target)


def restart_into(window, path: str) -> None:
    """Startet die neue AppImage-Datei und beendet die laufende."""
    from PySide6.QtWidgets import QApplication

    from . import util

    if util._start_detached(path, [], os.path.dirname(path)):
        window.close()
        QApplication.quit()


def check(window, manual: bool) -> None:
    """Prüfen und ggf. das Fenster zeigen (manual: auch „keine neue Version“ und Fehler melden)."""
    from .dialogs import show_error

    window.settings.set("update_last_check", dt.date.today().isoformat())
    if manual:
        release, error = netutil.run_blocking(window, fetch_latest, t("update.checking"), t("update.title"))
        if error:
            show_error(window, t("update.title"), t("update.failed", reason=error))
        if release is not None:
            handle_release(window, release, manual=True)
        return
    task = netutil.Task(fetch_latest, window)
    task.result.connect(lambda rel: handle_release(window, rel, manual=False))
    task.finished.connect(task.deleteLater)
    window._update_task = task  # Referenz halten
    task.start()
