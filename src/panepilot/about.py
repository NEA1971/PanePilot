"""„Über PanePilot“ (v0.9.11): Über · Danksagungen · System."""

from __future__ import annotations

import os
import platform
import shutil
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from . import __version__, donation
from .i18n import t

GPL_URL = "https://www.gnu.org/licenses/gpl-3.0.html"


def build_date() -> str:
    """Datum des AppImage-Baus (schreibt packaging/build_appimage.sh); leer bei Start aus dem Quellcode."""
    try:
        from ._build import BUILD_DATE  # type: ignore[import-not-found]
    except ImportError:
        return ""
    return BUILD_DATE


def _os_name() -> str:
    try:
        return platform.freedesktop_os_release().get("PRETTY_NAME", platform.platform())
    except (OSError, AttributeError):
        return platform.platform()


def _versions() -> dict[str, str]:
    import PySide6
    from PySide6.QtCore import qVersion

    try:
        import mutagen

        mutagen_version = mutagen.version_string
    except ImportError:
        mutagen_version = "–"
    return {"python": platform.python_version(), "pyside": PySide6.__version__, "qt": qVersion(),
            "mutagen": mutagen_version}


def system_info(config_path: str) -> str:
    """Text für den Reiter „System“ – zum Kopieren in eine Fehlermeldung."""
    from .i18n import current_language

    v = _versions()
    build = build_date() or t("about.dev_build")
    ffmpeg = shutil.which("ffmpeg")
    lines = [
        f"PanePilot {__version__} ({build})",
        f"{t('about.sys_os')}: {_os_name()} ({platform.machine()})",
        f"{t('about.sys_desktop')}: {os.environ.get('XDG_CURRENT_DESKTOP', '?')}, "
        f"{os.environ.get('XDG_SESSION_TYPE', '?')} / Qt-Plattform {QGuiApplication.platformName()}",
        f"Python {v['python']} · PySide6 {v['pyside']} · Qt {v['qt']} · mutagen {v['mutagen']}",
        f"ffmpeg: {ffmpeg or t('about.sys_missing')}",
        f"AppImage: {t('about.sys_yes') if os.environ.get('APPIMAGE') else t('about.sys_no')}",
        f"{t('about.sys_language')}: {current_language()}",
        f"{t('about.sys_config')}: {config_path}",
    ]
    return "\n".join(lines)


class AboutDialog(QDialog):
    def __init__(self, window, config_path: str) -> None:
        super().__init__(window)
        from .dialogs import free_window

        free_window(self)
        self.window = window
        self.config_path = config_path
        self.setWindowTitle(t("title.about"))
        self.setMinimumWidth(600)
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._about_tab(), t("about.tab_about"))
        self.tabs.addTab(self._credits_tab(), t("about.tab_credits"))
        self.tabs.addTab(self._system_tab(), t("about.tab_system"))
        box = QDialogButtonBox(self)
        box.addButton(t("button.close"), QDialogButtonBox.ButtonRole.RejectRole)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(box)

    # --- Über -----------------------------------------------------------------------------------
    def _about_tab(self) -> QWidget:
        from .icons import app_icon

        w = QWidget(self)
        icon = QLabel(w)
        icon.setPixmap(app_icon().pixmap(72, 72))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        build = build_date()
        head = QLabel(f"<h2 style='margin:0'>PanePilot {__version__}</h2>"
                      + (f"<div>{t('about.build', date=build)}</div>" if build else ""), w)
        top = QHBoxLayout()
        top.addWidget(icon)
        top.addSpacing(10)
        top.addWidget(head, 1)
        text = QLabel(t("about.description"), w)
        text.setWordWrap(True)
        legal = QLabel(t("about.legal", url=GPL_URL), w)
        legal.setWordWrap(True)
        legal.setTextFormat(Qt.TextFormat.RichText)
        legal.setOpenExternalLinks(False)
        legal.linkActivated.connect(self._open)
        links = QLabel(" · ".join([
            f"<a href='{donation.PROJECT_URL}'>{t('about.link_project')}</a>",
            f"<a href='{donation.ISSUES_URL}'>{t('about.link_issues')}</a>",
        ]), w)
        links.setTextFormat(Qt.TextFormat.RichText)
        links.linkActivated.connect(self._open)
        self.donor_label = QLabel(w)
        self.donor_label.setWordWrap(True)
        self.btn_support = QPushButton(t("donate.support"), w)
        self.btn_code = QPushButton(t("donate.enter_code"), w)
        self.btn_support.clicked.connect(lambda: self._open(donation.KOFI_URL))
        self.btn_code.clicked.connect(self._enter_code)
        donate_row = QHBoxLayout()
        donate_row.addWidget(self.btn_support)
        donate_row.addWidget(self.btn_code)
        donate_row.addStretch(1)
        layout = QVBoxLayout(w)
        layout.addLayout(top)
        layout.addWidget(text)
        layout.addWidget(legal)
        layout.addWidget(links)
        layout.addSpacing(8)
        layout.addWidget(self.donor_label)
        layout.addLayout(donate_row)
        layout.addStretch(1)
        self._update_donor()
        return w

    def _update_donor(self) -> None:
        name = donation.registered_name(self.window.settings)
        if name:
            self.donor_label.setText("<b>" + t("about.registered", name=name).replace("<", "&lt;") + "</b>")
        else:
            self.donor_label.setText(t("about.donate_hint"))
        self.btn_code.setVisible(not name)

    def _enter_code(self) -> None:
        if donation.DonorCodeDialog(self, self.window.settings).exec() == QDialog.DialogCode.Accepted:
            self._update_donor()

    @staticmethod
    def _open(url: str) -> None:
        from . import util

        util.open_url(url)

    # --- Danksagungen ----------------------------------------------------------------------------
    def _credits_tab(self) -> QWidget:
        v = _versions()
        ffmpeg = t("about.credit_ffmpeg_found") if shutil.which("ffmpeg") else t("about.credit_ffmpeg_missing")
        rows = [
            ("Qt / PySide6", f"{v['pyside']} (Qt {v['qt']})", "LGPL-3.0", "https://www.qt.io/qt-for-python",
             t("about.credit_qt")),
            ("mutagen", v["mutagen"], "GPL-2.0-or-later", "https://github.com/quodlibet/mutagen",
             t("about.credit_mutagen")),
            ("FFmpeg", ffmpeg, "LGPL/GPL", "https://ffmpeg.org", t("about.credit_ffmpeg")),
            ("Python", v["python"], "PSF", "https://www.python.org", t("about.credit_python")),
            ("freedesktop.org", "", "", "https://www.freedesktop.org", t("about.credit_icons")),
            ("FreeCommander", "", "", "https://freecommander.com", t("about.credit_freecommander")),
        ]
        html = "<table cellspacing='0' cellpadding='4'>"
        for name, version, lic, url, what in rows:
            meta = " · ".join(x for x in (version, lic) if x)
            html += (f"<tr><td valign='top'><b><a href='{url}'>{name}</a></b></td>"
                     f"<td valign='top'>{what}" + (f"<br><small>{meta}</small>" if meta else "") + "</td></tr>")
        html += "</table>"
        w = QWidget(self)
        intro = QLabel(t("about.credits_intro"), w)
        intro.setWordWrap(True)
        label = QLabel(html, w)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setWordWrap(True)
        label.linkActivated.connect(self._open)
        layout = QVBoxLayout(w)
        layout.addWidget(intro)
        layout.addWidget(label)
        layout.addStretch(1)
        return w

    # --- System ---------------------------------------------------------------------------------
    def _system_tab(self) -> QWidget:
        w = QWidget(self)
        self.system_text = QPlainTextEdit(system_info(self.config_path), w)
        self.system_text.setReadOnly(True)
        hint = QLabel(t("about.sys_hint"), w)
        hint.setWordWrap(True)
        copy = QPushButton(t("about.sys_copy"), w)
        copy.clicked.connect(self.copy_system_info)
        row = QHBoxLayout()
        row.addWidget(hint, 1)
        row.addWidget(copy)
        layout = QVBoxLayout(w)
        layout.addWidget(self.system_text, 1)
        layout.addLayout(row)
        return w

    def copy_system_info(self) -> None:
        QGuiApplication.clipboard().setText(self.system_text.toPlainText())
