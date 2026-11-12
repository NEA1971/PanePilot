"""Eingebaute Hilfe (v0.9.11).

Die Seiten liegen als Markdown unter ``help/<sprache>/<thema>.md``. Dieselben Dateien zeigt GitHub als
Online-Hilfe an. Deutsch und Englisch gibt es, die anderen Sprachen zeigen die englische Hilfe. Die
Seite „Tastenkürzel“ wird aus der aktuellen Belegung erzeugt.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QListWidget, QPushButton, QTextBrowser, QVBoxLayout

from .i18n import current_language, t
from .resources import resource_path

TOPICS = ("basics", "sidebars", "servers", "search", "rename", "metawizard", "checksums", "settings", "shortcuts")
HELP_LANGUAGES = ("de", "en")


def help_language() -> str:
    lang = current_language()
    return lang if lang in HELP_LANGUAGES else "en"


def topic_markdown(topic: str, lang: str | None = None) -> str:
    path = resource_path("help", lang or help_language(), f"{topic}.md")
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def topic_title(topic: str) -> str:
    if topic == "shortcuts":
        return t("help.shortcuts")
    for line in topic_markdown(topic).splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return topic


def shortcuts_markdown(window) -> str:
    """Tabelle aller Funktionen mit Tastenkürzel, so wie sie gerade eingestellt sind."""
    from .actions import ACTION_DEFS

    german = current_language() in ("de", "frk", "sxu")
    names = {"Ctrl": "Strg", "Shift": "Umschalt", "Del": "Entf", "Backspace": "Rücktaste", "Return": "Eingabe",
             "Left": "Links", "Right": "Rechts", "Up": "Hoch", "Down": "Runter", "Space": "Leertaste", "Ins": "Einfg",
             "PgUp": "Bild↑", "PgDown": "Bild↓", "Home": "Pos1", "End": "Ende", "Esc": "Esc"}

    def local(key: str) -> str:
        if not german:
            return key
        return "+".join(names.get(part, part) for part in key.split("+"))

    rows, seen = [], set()
    for adef in ACTION_DEFS:
        act = window.qactions.get(adef.id)
        if act is None:
            continue
        keys = [k.toString(QKeySequence.SequenceFormat.NativeText) for k in act.shortcuts()]
        keys = [local(k) for k in keys if k]
        if keys:
            name = act.text().replace("&&", "\0").replace("&", "").replace("\0", "&")
            row = f"| {name} | {' · '.join(keys)} |"
            if row not in seen:
                seen.add(row)
                rows.append(row)
    lines = [f"# {t('help.shortcuts')}", "", t("help.shortcuts_intro"), "",
             f"| {t('help.col_function')} | {t('help.col_keys')} |", "|---|---|", *rows]
    return "\n".join(lines)


class HelpDialog(QDialog):
    def __init__(self, window, topic: str = "basics", parent=None) -> None:
        # Ohne Eltern bleibt die Hilfe neben dem Programm offen; aus einem modalen Fenster heraus
        # (z. B. Einstellungen) muss sie dessen Kind sein, sonst wäre sie gesperrt.
        super().__init__(parent)
        from .dialogs import free_window

        free_window(self)
        # Die Hilfe soll neben dem Programm offen bleiben können
        from PySide6.QtCore import Qt

        self.setWindowModality(Qt.WindowModality.NonModal)
        self.window = window
        self.setWindowTitle(t("help.title"))
        self.resize(940, 680)
        self.nav = QListWidget(self)
        self.nav.setMaximumWidth(220)
        for tp in TOPICS:
            self.nav.addItem(topic_title(tp))
        self.view = QTextBrowser(self)
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        online = QPushButton(t("help.online"), self)
        online.clicked.connect(self.open_online)
        box = QDialogButtonBox(self)
        box.addButton(t("button.close"), QDialogButtonBox.ButtonRole.RejectRole)
        box.rejected.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addWidget(online)
        bottom.addStretch(1)
        bottom.addWidget(box)
        row = QHBoxLayout()
        row.addWidget(self.nav)
        row.addWidget(self.view, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(row, 1)
        layout.addLayout(bottom)
        self.nav.currentRowChanged.connect(lambda r: self.show_topic(TOPICS[r]) if 0 <= r < len(TOPICS) else None)
        self.show_topic(topic)

    def show_topic(self, topic: str) -> None:
        if topic not in TOPICS:
            topic = "basics"
        self.topic = topic
        text = shortcuts_markdown(self.window) if topic == "shortcuts" else topic_markdown(topic)
        self.view.setMarkdown(text)
        row = TOPICS.index(topic)
        if self.nav.currentRow() != row:
            self.nav.blockSignals(True)
            self.nav.setCurrentRow(row)
            self.nav.blockSignals(False)

    def _link(self, url: QUrl) -> None:
        target = url.toString()
        if url.scheme() in ("http", "https"):
            from . import util

            util.open_url(target)
            return
        name = target.split("#")[0].rsplit("/", 1)[-1]
        if name.endswith(".md"):
            self.show_topic(name[:-3])

    def open_online(self) -> None:
        from . import util
        from .donation import HELP_ONLINE_URL

        util.open_url(f"{HELP_ONLINE_URL}/{help_language()}/{self.topic if self.topic != 'shortcuts' else 'basics'}.md")
