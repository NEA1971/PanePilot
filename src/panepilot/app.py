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
    from . import theme  # v3.2 (L-4200): Hell/Dunkel, Schrift

    theme.apply(str(settings.get("theme") or "system"), str(settings.get("font_family") or ""),
                float(settings.get("font_size") or 0))
    return app


def start_hang_log(seconds: float = 5.0):
    """Hänger-Diagnose (v1.6.2): Mit PANEPILOT_HANG_LOG=1 schreibt PanePilot den Stand aller Programmteile in
    „hang.log“ im Einstellungsordner, sobald die Oberfläche länger als einige Sekunden nicht reagiert.
    Gibt die Datei bzw. None zurück."""
    import faulthandler
    import time

    from PySide6.QtCore import QTimer

    from .config import config_dir

    try:
        path = config_dir() / "hang.log"
        fh = open(path, "a", encoding="utf-8")  # noqa: SIM115 – bleibt bis zum Programmende offen
    except OSError:
        return None
    fh.write(f"\n=== PanePilot gestartet {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    fh.flush()

    def arm() -> None:
        faulthandler.dump_traceback_later(seconds, repeat=True, file=fh)

    timer = QTimer(QApplication.instance())
    timer.setObjectName("panepilotHangLog")
    timer.setInterval(1000)
    timer.timeout.connect(arm)  # solange die Oberfläche arbeitet, wird die Uhr immer wieder zurückgesetzt
    timer.start()
    arm()
    return path


def main() -> int:
    app = create_app()
    import os

    if os.environ.get("PANEPILOT_HANG_LOG"):
        start_hang_log()
    from .mainwindow import MainWindow  # erst nach QApplication importieren

    window = MainWindow()
    window.show()
    from PySide6.QtCore import QTimer

    QTimer.singleShot(2000, window.auto_backup)  # Sicherung beim ersten Start des Tages (F-852)
    QTimer.singleShot(3000, window.maybe_ask_for_donation)  # Bitte um Unterstützung (v0.9.11)
    QTimer.singleShot(5000, window.auto_update_check)  # einmal täglich nach Updates suchen (v1.2)
    from . import updatecheck

    QTimer.singleShot(2500, lambda: updatecheck.offer_old_file_removal(window))  # alte Datei nach Update (v1.23)
    QTimer.singleShot(2600, lambda: updatecheck.offer_appimage_launcher_removal(window))  # v2.0
    from . import desktopint

    QTimer.singleShot(1500, desktopint.update_if_moved)  # Starter im Anwendungsmenü nachführen (v1.1)
    return app.exec()
