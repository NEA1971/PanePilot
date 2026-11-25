"""Dateien vergleichen (v2.7, L-3730 ff.).

Textdateien nebeneinander mit farbigen Unterschieden (nur ansehen), PDF und Office-Dokumente über ihren Text,
alle anderen Dateien Byte für Byte: identisch oder verschieden ab Stelle n.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QKeySequence, QShortcut, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QTextEdit, QVBoxLayout)

from . import officetext
from .dialogs import free_window
from .i18n import t

TEXT_LIMIT = 4 * 1024 * 1024
CHUNK = 1024 * 1024

# Farben (hell genug für dunkle Schrift, mit Alpha auch im dunklen Thema erkennbar)
COLOR_CHANGED = QColor(255, 210, 80, 110)
COLOR_REMOVED = QColor(240, 90, 90, 100)
COLOR_ADDED = QColor(90, 200, 90, 100)
COLOR_FILLER = QColor(128, 128, 128, 45)


def text_of(path: str) -> str | None:
    """Text einer Datei für den Vergleich – None, wenn es keine Textdatei/kein Dokument ist."""
    from .quickview import decode_text, looks_binary

    if officetext.supported(path):
        try:
            return officetext.as_text(officetext.extract(path), t("compare.page"))
        except Exception:  # noqa: BLE001 – kaputtes Dokument: Byte-Vergleich
            return None
    try:
        with open(path, "rb") as fh:
            data = fh.read(TEXT_LIMIT)
    except OSError:
        return None
    if looks_binary(data):
        return None
    return decode_text(data)


def first_difference(a: str, b: str) -> int | None:
    """Byte-Position der ersten Abweichung (0-basiert), None = identisch."""
    pos = 0
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            ca, cb = fa.read(CHUNK), fb.read(CHUNK)
            if ca != cb:
                n = min(len(ca), len(cb))
                for i in range(n):
                    if ca[i] != cb[i]:
                        return pos + i
                return pos + n
            if not ca:
                return None
            pos += len(ca)


@dataclass
class Row:
    left: str | None  # None = Füllzeile
    right: str | None
    lnum: int | None
    rnum: int | None
    tag: str  # equal, replace, delete, insert


def align(a: list[str], b: list[str]) -> list[Row]:
    rows: list[Row] = []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            rows += [Row(a[i1 + k], b[j1 + k], i1 + k + 1, j1 + k + 1, tag) for k in range(i2 - i1)]
            continue
        n = max(i2 - i1, j2 - j1)
        for k in range(n):
            left = a[i1 + k] if i1 + k < i2 else None
            right = b[j1 + k] if j1 + k < j2 else None
            rows.append(Row(left, right, i1 + k + 1 if left is not None else None,
                            j1 + k + 1 if right is not None else None, tag))
    return rows


def blocks(rows: list[Row]) -> list[int]:
    """Erste Zeile jedes Unterschieds-Blocks."""
    out = []
    prev = "equal"
    for i, r in enumerate(rows):
        if r.tag != "equal" and prev == "equal":
            out.append(i)
        prev = r.tag
    return out


class DiffDialog(QDialog):
    """L-3731: nebeneinander, gemeinsames Scrollen, nächster/vorheriger Unterschied; nur ansehen."""

    def __init__(self, parent, left: str, right: str, ltext: str, rtext: str) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("compare.title"))
        self.resize(1200, 760)
        lay = QVBoxLayout(self)
        heads = QHBoxLayout()
        for path in (left, right):
            lbl = QLabel(path, self)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setStyleSheet("font-weight: bold;")
            heads.addWidget(lbl, 1)
        lay.addLayout(heads)
        self.rows = align(ltext.splitlines(), rtext.splitlines())
        self.blocks = blocks(self.rows)
        self.pos = -1
        body = QHBoxLayout()
        self.left = self._editor()
        self.right = self._editor()
        body.addWidget(self.left, 1)
        body.addWidget(self.right, 1)
        lay.addLayout(body, 1)
        self._fill()
        # gemeinsames Scrollen
        for a, b in ((self.left, self.right), (self.right, self.left)):
            a.verticalScrollBar().valueChanged.connect(b.verticalScrollBar().setValue)
            a.horizontalScrollBar().valueChanged.connect(b.horizontalScrollBar().setValue)
        bottom = QHBoxLayout()
        self.summary = QLabel(self)
        bottom.addWidget(self.summary, 1)
        self.btn_prev = QPushButton(t("compare.prev"), self)
        self.btn_next = QPushButton(t("compare.next"), self)
        self.btn_prev.setToolTip("Alt+↑")
        self.btn_next.setToolTip("Alt+↓")
        self.btn_prev.clicked.connect(lambda: self.jump(-1))
        self.btn_next.clicked.connect(lambda: self.jump(1))
        bottom.addWidget(self.btn_prev)
        bottom.addWidget(self.btn_next)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close.rejected.connect(self.reject)
        bottom.addWidget(close)
        lay.addLayout(bottom)
        QShortcut(QKeySequence("Alt+Down"), self, lambda: self.jump(1))
        QShortcut(QKeySequence("Alt+Up"), self, lambda: self.jump(-1))
        n = len(self.blocks)
        self.summary.setText(t("compare.same_text") if n == 0 else t("compare.differences", n=n))
        self.btn_prev.setEnabled(n > 0)
        self.btn_next.setEnabled(n > 0)
        if n:
            self.jump(1)

    def _editor(self) -> QPlainTextEdit:
        ed = QPlainTextEdit(self)
        ed.setObjectName("diffText")
        ed.setReadOnly(True)
        ed.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        ed.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        return ed

    def _fill(self) -> None:
        width = len(str(max(len(self.rows), 1)))
        for ed, side in ((self.left, "left"), (self.right, "right")):
            lines = []
            for r in self.rows:
                text = getattr(r, side)
                num = r.lnum if side == "left" else r.rnum
                lines.append(f"{num:>{width}} │ {text}" if text is not None else f"{'':>{width}} │")
            ed.setPlainText("\n".join(lines))
            selections = []
            doc = ed.document()
            for i, r in enumerate(self.rows):
                if r.tag == "equal":
                    continue
                text = getattr(r, side)
                if text is None:
                    color = COLOR_FILLER
                elif r.tag == "replace":
                    color = COLOR_CHANGED
                else:
                    color = COLOR_REMOVED if side == "left" else COLOR_ADDED
                sel = QTextEdit.ExtraSelection()
                fmt = QTextCharFormat()
                fmt.setBackground(color)
                fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)
                sel.format = fmt
                cursor = QTextCursor(doc.findBlockByNumber(i))
                sel.cursor = cursor
                selections.append(sel)
            ed.setExtraSelections(selections)

    def jump(self, step: int) -> None:
        if not self.blocks:
            return
        self.pos = (self.pos + step) % len(self.blocks)
        line = self.blocks[self.pos]
        for ed in (self.left, self.right):
            cursor = QTextCursor(ed.document().findBlockByNumber(line))
            ed.setTextCursor(cursor)
        self.left.centerCursor()
        self.summary.setText(t("compare.position", i=self.pos + 1, n=len(self.blocks)))


def compare(parent, left: str, right: str) -> None:
    """Einstieg: Text/Dokumente nebeneinander, sonst Byte-Vergleich mit Meldung (L-3733)."""
    from PySide6.QtWidgets import QApplication

    from .dialogs import show_error, show_info
    from .util import format_size

    title = t("compare.title")
    QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        ltext, rtext = text_of(left), text_of(right)
        if ltext is not None and rtext is not None:
            dlg = DiffDialog(parent, left, right, ltext, rtext)
        else:
            dlg = None
            diff = first_difference(left, right)
    except OSError as exc:
        QApplication.restoreOverrideCursor()
        show_error(parent, title, str(exc))
        return
    QApplication.restoreOverrideCursor()
    if dlg is not None:
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dlg.show()
        return
    sizes = t("compare.sizes", left=format_size(os.path.getsize(left)), right=format_size(os.path.getsize(right)))
    if diff is None:
        show_info(parent, title, t("compare.identical") + "\n\n" + sizes)
    else:
        show_info(parent, title, t("compare.different", pos=f"{diff:,}".replace(",", "."), hex=f"0x{diff:X}")
                  + "\n\n" + sizes)
