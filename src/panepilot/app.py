"""Programmstart."""

from __future__ import annotations

import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import APP_NAME, __version__
from .config import Settings
from .i18n import load_language, qt_locale_name


def _setup_icon_theme() -> None:
    # Außerhalb von GNOME/KDE meldet Qt mitunter kein Symbolthema – dann Adwaita nutzen.
    if not QIcon.themeName() or QIcon.themeName() == "hicolor":
        QIcon.setThemeName("Adwaita")
    QIcon.setFallbackThemeName("hicolor")


def _install_qt_translations(app: QApplication, lang: str) -> None:
    """Deutsche Texte auch für Qt-eigene Dialogelemente (z. B. Kontextmenü im Eingabefeld)."""
    translator = QTranslator(app)
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(lang), "qtbase", "_", path):
        app.installTranslator(translator)


def create_app(argv: list[str] | None = None) -> QApplication:
    if QApplication.instance() is None:
        # Skalierung der Oberfläche (v1.1) – nur vor dem Anlegen der QApplication möglich
        from .util import apply_ui_scale

        apply_ui_scale(Settings().get("ui_scale"))
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("panepilot")
    settings = Settings()
    load_language(str(settings.get("language") or "system"))
    _install_qt_translations(app, qt_locale_name())
    from .util import set_size_unit

    set_size_unit(str(settings.get("size_unit") or "auto"))
    _setup_icon_theme()
    return app


def main() -> int:
    app = create_app()
    from .mainwindow import MainWindow  # erst nach QApplication importieren

    window = MainWindow()
    window.show()
    from PySide6.QtCore import QTimer

    QTimer.singleShot(2000, window.auto_backup)  # Sicherung beim ersten Start des Tages (F-852)
    QTimer.singleShot(3000, window.maybe_ask_for_donation)  # Bitte um Unterstützung (v0.9.11)
    QTimer.singleShot(5000, window.auto_update_check)  # einmal täglich nach Updates suchen (v1.2)
    from . import desktopint

    QTimer.singleShot(1500, desktopint.update_if_moved)  # Starter im Anwendungsmenü nachführen (v1.1)
    return app.exec()
