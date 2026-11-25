"""Auswahl nach Muster (v2.7, L-3710 ff.): Auswahl erweitern/verringern, umkehren, gleiche Endung."""

from __future__ import annotations

import fnmatch

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from .i18n import t

HISTORY_MAX = 15


def split_patterns(text: str) -> list[str]:
    """„*.jpg; *.png“ → ["*.jpg", "*.png"]; ein Muster ohne Platzhalter gilt als Teil des Namens."""
    out = []
    for part in (text or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if not any(c in part for c in "*?["):
            part = f"*{part}*"
        out.append(part)
    return out


def matches(name: str, patterns: list[str]) -> bool:
    low = name.casefold()
    return any(fnmatch.fnmatchcase(low, p.casefold()) for p in patterns)


def ext_pattern(name: str | None, is_dir: bool = False) -> str:
    """Vorbelegung: Endung der aktuellen Datei, z. B. „*.jpg“ – sonst „*“."""
    if not name or is_dir or "." not in name[1:]:
        return "*"
    ext = name.rsplit(".", 1)[1]
    return "*." + ext if ext else "*"


def remember(history: list | None, text: str) -> list[str]:
    items = [h for h in (history or []) if isinstance(h, str) and h != text]
    return ([text] + items)[:HISTORY_MAX]


class PatternDialog(QDialog):
    """Musterfeld mit den letzten Mustern und Häkchen „auch Ordner“ (L-3710, L-3712)."""

    def __init__(self, parent, title: str, initial: str, history: list[str], include_dirs: bool) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(t("select.pattern_label"), self))
        self.combo = QComboBox(self)
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.combo.addItems([h for h in history if h != initial])
        self.combo.insertItem(0, initial)
        self.combo.setCurrentIndex(0)
        self.combo.setMinimumWidth(320)
        self.combo.lineEdit().selectAll()
        lay.addWidget(self.combo)
        hint = QLabel(t("select.pattern_hint"), self)
        hint.setWordWrap(True)
        hint.setEnabled(False)
        lay.addWidget(hint)
        self.dirs = QCheckBox(t("select.include_dirs"), self)
        self.dirs.setChecked(include_dirs)
        lay.addWidget(self.dirs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.combo.setFocus()

    def values(self) -> tuple[str, bool]:
        return self.combo.currentText().strip(), self.dirs.isChecked()
