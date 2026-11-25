"""Änderungsdatum setzen (v2.7, L-3740 ff.): festes Datum, jetzt, Aufnahmedatum oder Datum im Dateinamen."""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QDateTimeEdit, QDialog, QDialogButtonBox,
                               QHBoxLayout, QHeaderView, QLabel, QRadioButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from .i18n import t

FIXED, NOW, TAKEN, NAME = "fixed", "now", "taken", "name"
PREVIEW_MAX = 2000

# Datum im Dateinamen: 20240512_143012, 2024-05-12 14.30.12, 2024-05-12, 20240512 …
_NAME_PATTERNS = (
    re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})[_\-T ]?(\d{2})(\d{2})(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})[ _T.-](\d{2})[.:\-](\d{2})(?:[.:\-](\d{2}))?(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)"),
)


def date_from_name(name: str) -> dt.datetime | None:
    for pattern in _NAME_PATTERNS:
        for m in pattern.finditer(name):
            parts = [int(x) if x else 0 for x in m.groups()]
            try:
                when = dt.datetime(*parts[:3], *(parts[3:] + [0, 0, 0])[:3])
            except ValueError:
                continue
            if 1971 <= when.year <= 2100:
                return when
    return None


def date_taken(path: str) -> dt.datetime | None:
    """Aufnahmedatum aus EXIF (Fotos) bzw. den Metadaten von Videos."""
    from . import tags

    if not (tags.is_photo(path) or tags.is_video(path)):
        return None
    try:
        rec = tags.read_file(path)
    except Exception:  # noqa: BLE001 – kaputte Datei: kein Datum
        return None
    from .phototags import parse_date

    return parse_date(rec.fields.get("datetaken", "") if getattr(rec, "fields", None) else "")


def collect(paths: list[str], recursive: bool) -> list[str]:
    """Die gewählten Einträge, mit „auch Unterordner“ zusätzlich alles darin (ohne symbolische Links)."""
    out: list[str] = []
    for p in paths:
        out.append(p)
        if recursive and os.path.isdir(p) and not os.path.islink(p):
            for root, dirs, files in os.walk(p):
                dirs.sort()
                for name in sorted(dirs) + sorted(files):
                    full = os.path.join(root, name)
                    if not os.path.islink(full):
                        out.append(full)
    return out


@dataclass
class Change:
    path: str
    old: float
    new: float | None  # None = bleibt unverändert


def plan(paths: list[str], mode: str, fixed: dt.datetime | None = None) -> list[Change]:
    now = dt.datetime.now()
    result = []
    for p in paths:
        try:
            old = os.lstat(p).st_mtime
        except OSError:
            continue
        is_dir = os.path.isdir(p)
        when: dt.datetime | None
        if mode == FIXED:
            when = fixed
        elif mode == NOW:
            when = now
        elif mode == TAKEN:
            when = None if is_dir else date_taken(p)
        else:
            when = None if is_dir else date_from_name(os.path.basename(p))
        result.append(Change(p, old, when.timestamp() if when is not None else None))
    return result


def apply(changes: list[Change]) -> list[str]:
    """Setzt die neuen Zeiten; Ordner zuletzt (sonst ändert das Anpassen ihres Inhalts nichts mehr daran)."""
    errors = []
    for ch in sorted(changes, key=lambda c: os.path.isdir(c.path)):
        if ch.new is None:
            continue
        try:
            st = os.stat(ch.path)
            os.utime(ch.path, (st.st_atime, ch.new))
        except OSError as exc:
            errors.append(f"{os.path.basename(ch.path)}: {exc.strerror or exc}")
    return errors


def _fmt(ts: float | None) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M:%S") if ts is not None else ""


class DateDialog(QDialog):
    """L-3740/L-3741: Quelle wählen, Vorschau alt → neu, „auch Unterordner“."""

    def __init__(self, parent, paths: list[str]) -> None:
        super().__init__(parent)
        self.paths = paths
        self.setWindowTitle(t("date.title"))
        self.resize(760, 520)
        lay = QVBoxLayout(self)
        self.group = QButtonGroup(self)
        self.radios: dict[str, QRadioButton] = {}
        row = QHBoxLayout()
        fixed = QRadioButton(t("date.fixed"), self)
        self.radios[FIXED] = fixed
        self.edit = QDateTimeEdit(self)
        self.edit.setDisplayFormat("dd.MM.yyyy HH:mm:ss")
        self.edit.setCalendarPopup(True)
        try:
            self.edit.setDateTime(QDateTime.fromSecsSinceEpoch(int(os.lstat(paths[0]).st_mtime)))
        except (OSError, IndexError):
            self.edit.setDateTime(QDateTime.currentDateTime())
        row.addWidget(fixed)
        row.addWidget(self.edit)
        row.addStretch(1)
        lay.addLayout(row)
        for key, text in ((NOW, "date.now"), (TAKEN, "date.taken"), (NAME, "date.from_name")):
            self.radios[key] = QRadioButton(t(text), self)
            lay.addWidget(self.radios[key])
        for key, radio in self.radios.items():
            self.group.addButton(radio)
            radio.toggled.connect(lambda on, _k=key: on and self.update_preview())
        self.edit.dateTimeChanged.connect(lambda *_: self.radios[FIXED].isChecked() and self.update_preview())
        self.recursive = QCheckBox(t("date.recursive"), self)
        self.recursive.setVisible(any(os.path.isdir(p) and not os.path.islink(p) for p in paths))
        self.recursive.toggled.connect(lambda *_: self.update_preview())
        lay.addWidget(self.recursive)
        hint = QLabel(t("date.hint"), self)
        hint.setWordWrap(True)
        hint.setEnabled(False)
        lay.addWidget(hint)
        self.tree = QTreeWidget(self)
        self.tree.setObjectName("datePreview")
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setHeaderLabels([t("date.col_name"), t("date.col_old"), t("date.col_new")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.tree, 1)
        self.summary = QLabel(self)
        lay.addWidget(self.summary)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
                                        self)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.changes: list[Change] = []
        fixed.setChecked(True)  # löst die erste Vorschau aus

    def mode(self) -> str:
        return next(k for k, r in self.radios.items() if r.isChecked())

    def update_preview(self) -> None:
        from PySide6.QtWidgets import QApplication

        mode = self.mode()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            fixed = self.edit.dateTime().toPython() if mode == FIXED else None
            self.changes = plan(collect(self.paths, self.recursive.isChecked()), mode, fixed)
        finally:
            QApplication.restoreOverrideCursor()
        self.tree.clear()
        base = os.path.dirname(self.paths[0]) if self.paths else ""
        items = []
        for ch in self.changes[:PREVIEW_MAX]:
            name = os.path.relpath(ch.path, base) if base else ch.path
            item = QTreeWidgetItem([name, _fmt(ch.old), _fmt(ch.new) if ch.new is not None else t("date.unchanged")])
            if ch.new is None:
                item.setForeground(2, self.palette().placeholderText())
            items.append(item)
        self.tree.addTopLevelItems(items)
        for col in (1, 2):
            self.tree.resizeColumnToContents(col)
        n = sum(1 for ch in self.changes if ch.new is not None)
        self.summary.setText(t("date.summary", n=n, total=len(self.changes)))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(n > 0)
