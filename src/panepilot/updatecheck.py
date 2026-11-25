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

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout

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
    packages: dict | None = None  # v2.0: {"deb": (Name, URL, Größe), "rpm": …}

    def for_install(self) -> "Release":
        """Die Datei, die zur laufenden Installation passt (AppImage bzw. .deb/.rpm)."""
        from . import installkind

        fmt = installkind.package_format()
        if fmt and self.packages and fmt in self.packages:
            name, url, size = self.packages[fmt]
            return Release(self.version, self.notes, self.page, name, url, size, self.packages)
        if fmt:
            return Release(self.version, self.notes, self.page, None, None, 0, self.packages)
        return self


def version_tuple(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(candidate: str, current: str = __version__) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def parse_release(data: dict) -> Release:
    version = str(data.get("tag_name") or "").lstrip("vV")
    assets = data.get("assets") or []
    asset = next((a for a in assets if str(a.get("name", "")).endswith("x86_64.AppImage")), None)
    packages = {}
    for a in assets:
        name = str(a.get("name", ""))
        for fmt, suffix in (("deb", "amd64.deb"), ("rpm", "x86_64.rpm"),
                            ("winsetup", "windows-x64-setup.exe"), ("winzip", "windows-x64.zip")):
            if name.endswith(suffix):
                packages[fmt] = (name, a.get("browser_download_url"), int(a.get("size") or 0))
    return Release(version=version, notes=str(data.get("body") or ""), page=str(data.get("html_url") or RELEASES_URL),
                   asset_name=asset.get("name") if asset else None,
                   asset_url=asset.get("browser_download_url") if asset else None,
                   asset_size=int(asset.get("size") or 0) if asset else 0, packages=packages)


def fetch_latest() -> Release:
    return parse_release(netutil.get_json(API_LATEST))


NEVER, DAILY, START = "never", "daily", "start"  # v2.3: wie oft automatisch suchen


def check_mode(settings) -> str:
    if not settings.get("update_check"):
        return NEVER
    return START if settings.get("update_interval") == START else DAILY


def set_check_mode(settings, mode: str) -> None:
    settings.set("update_check", mode in (DAILY, START))
    if mode in (DAILY, START):
        settings.set("update_interval", mode)


def due_today(settings, today: dt.date | None = None) -> bool:
    """Automatische Prüfung: eingeschaltet und – bei „einmal am Tag“ – heute noch nicht geprüft."""
    today = today or dt.date.today()
    mode = check_mode(settings)
    if mode == START:
        return True
    return mode == DAILY and settings.get("update_last_check") != today.isoformat()


def download_folder() -> str:
    from PySide6.QtCore import QStandardPaths

    return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation) or \
        os.path.expanduser("~")


def target_path(release: Release) -> str | None:
    """Wohin die neue Version geladen wird: in den Ordner der laufenden AppImage-Datei –
    bzw. bei .deb/.rpm in „Downloads“ (v2.0, L-3004)."""
    from . import installkind

    release = release.for_install()
    if installkind.package_format():
        if not release.asset_name:
            return None
        folder = download_folder()
        return os.path.join(folder, release.asset_name) if os.access(folder, os.W_OK) else None
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
        from . import installkind

        fmt = installkind.package_format()
        key = ("update.hint_package" if fmt else "update.hint_appimage") if target_path(release) else "update.hint_page"
        hint = QLabel(t(key, kind=f".{fmt}" if fmt else ""), self)
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

    from .dialogs import WaitDialog

    dlg = WaitDialog(parent, t("update.title"), t("update.downloading", name=release.asset_name), 100, delay=0)
    state = {"cancel": False}
    dlg.canceled.connect(lambda: state.__setitem__("cancel", True))

    def work():
        netutil.download(release.asset_url, target,
                         progress=lambda d, tot: task.progress_value.emit(int(d * 100 / tot) if tot else 0),
                         cancel=lambda: state["cancel"])
        if target.endswith(".AppImage"):
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
    dlg.finish()
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
    from . import installkind

    fmt = installkind.package_format()
    if fmt in (installkind.WINSETUP, installkind.WINZIP):  # v3.0 (L-4005)
        pkg = release.for_install()
        if not os.path.exists(target) and not download_release(window, pkg, target):
            return
        if fmt == installkind.WINSETUP:
            if confirm(window, t("update.title"), t("update.win_setup_ready", name=os.path.basename(target)),
                       yes_key="update.win_setup_start", no_key="donate.later"):
                run_windows_setup(window, target)
            return
        util.open_with_default_app(os.path.dirname(target))
        show_info(window, t("update.title"), t("update.win_zip_ready", name=os.path.basename(target),
                                                  folder=os.path.dirname(target)))
        return
    if fmt:  # v2.0 (L-3004): Paket laden und mit der Software-Installation öffnen
        pkg = release.for_install()
        if not os.path.exists(target) and not download_release(window, pkg, target):
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(target))
        show_info(window, t("update.title"), t("update.package_ready", name=os.path.basename(target),
                                                  command=installkind.install_command(target, fmt)))
        return
    if not os.path.exists(target) and not download_release(window, release, target):
        return
    launcher = point_launcher(target)
    remember_old_file(settings, target)
    text = t("update.restart", name=os.path.basename(target))
    if launcher:
        text += "\n\n" + t("update.launcher_hint")
    if confirm(window, t("update.title"), text, yes_key="button.restart_now", no_key="donate.later"):
        restart_into(window, target)


def point_launcher(target: str) -> bool:
    """v1.23 (L-2320): Starter im Anwendungsmenü/der Taskleiste gleich auf die neue Datei umstellen."""
    from . import desktopint

    if not desktopint.is_integrated():
        return False
    try:
        desktopint.integrate(target)
    except OSError:
        return False
    return True


def remember_old_file(settings, target: str) -> None:
    """L-2321: laufende (alte) Datei merken – die neue Version fragt beim ersten Start, ob sie weg soll."""
    current = os.environ.get("APPIMAGE")
    if current and os.path.abspath(current) != os.path.abspath(target):
        settings.set("update_old_file", {"old": os.path.abspath(current), "new": os.path.abspath(target)})


def offer_old_file_removal(window) -> None:
    """Beim Start: lief vorher eine ältere Datei, einmal fragen, ob sie in den Papierkorb soll (L-2321)."""
    from .dialogs import confirm, show_error

    info = window.settings.get("update_old_file")
    current = os.environ.get("APPIMAGE")
    if not isinstance(info, dict) or not current:
        return
    old, new = info.get("old"), info.get("new")
    if not isinstance(old, str) or os.path.abspath(current) != new:
        return  # noch die alte Version oder eine andere Datei gestartet: später fragen
    window.settings.set("update_old_file", None)  # nur einmal fragen
    if not os.path.isfile(old) or os.path.abspath(old) == os.path.abspath(current):
        return
    policy = window.settings.get("update_old_policy")  # v2.3: ask / trash / keep
    if policy == "keep":
        return
    if policy == "trash" or confirm(window, t("update.title"), t("update.remove_old", name=os.path.basename(old),
                                                                  folder=os.path.dirname(old)),
                                    yes_key="update.remove_old_yes", no_key="update.remove_old_keep",
                                    default_yes=False):
        from .fileops import move_to_trash

        try:
            move_to_trash(old)
        except OSError as exc:
            show_error(window, t("update.title"), f"{old}: {exc.strerror or exc}")


def run_windows_setup(window, path: str) -> None:
    """Startet das heruntergeladene Windows-Setup und beendet PanePilot, damit es ersetzt werden kann."""
    from PySide6.QtWidgets import QApplication

    from . import util
    from .dialogs import show_error

    if util._start_detached(path, ["/SP-", "/CLOSEAPPLICATIONS"], os.path.dirname(path)):
        window.close()
        QApplication.quit()
    else:
        show_error(window, t("update.title"), t("error.launch_failed", app=os.path.basename(path)))


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


def offer_appimage_launcher_removal(window) -> None:
    """v2.0 (L-3007): Paket läuft, aber ein Menüeintrag der AppImage-Version verdeckt den des Pakets."""
    from . import desktopint, installkind
    from .dialogs import confirm

    if not installkind.package_format() or not desktopint.is_integrated():
        return
    if window.settings.get("package_launcher_asked"):
        return
    window.settings.set("package_launcher_asked", True)
    if confirm(window, t("update.title"), t("update.appimage_launcher"), yes_key="update.appimage_launcher_remove",
               no_key="update.remove_old_keep"):
        desktopint.remove()
