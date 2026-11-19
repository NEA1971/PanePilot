"""Dialog „Kapitel …“ im Video-Modus (v1.15, L-1500 ff.)."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import chapters as chp
from .dialogs import free_window, show_error
from .i18n import t

COL_TIME, COL_NAME = range(2)
COL_FILE, COL_OLD, COL_NEW = range(3)


class ChapterDialog(QDialog):
    def __init__(self, parent, videos: list[chp.VideoChapters]) -> None:
        super().__init__(parent)
        free_window(self)
        self.videos = videos
        self.single = len(videos) == 1
        self.settings = getattr(parent, "settings", None)
        self.new: dict[str, list | None] = {v.path: None for v in videos}  # mehrere Videos: None = unverändert
        name = os.path.basename(videos[0].path) if self.single else ""
        self.setWindowTitle(t("chapters.title") + (f" – {name}" if self.single else ""))
        self.resize(760, 560 if self.single else 460)
        lay = QVBoxLayout(self)
        intro = QLabel(t("chapters.intro_one", length=chp.short_time(videos[0].duration).split(".")[0])
                       if self.single else t("chapters.intro_many", n=len(videos)), self)
        intro.setWordWrap(True)
        lay.addWidget(intro)
        if self.single:
            self.table = QTableWidget(0, 2, self)
            self.table.setHorizontalHeaderLabels([t("chapters.col_time"), t("chapters.col_name")])
            self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
            self.table.setColumnWidth(COL_TIME, 140)
            self.set_chapters(videos[0].chapters)
        else:
            self.table = QTableWidget(len(videos), 3, self)
            self.table.setHorizontalHeaderLabels([t("chapters.col_file"), t("chapters.col_old"),
                                                  t("chapters.col_new")])
            self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.table.horizontalHeader().setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
            for r, v in enumerate(videos):
                self.table.setItem(r, COL_FILE, QTableWidgetItem(os.path.basename(v.path)))
                self.table.setItem(r, COL_OLD, QTableWidgetItem(str(len(v.chapters))))
                self.table.setItem(r, COL_NEW, QTableWidgetItem(t("chapters.unchanged")))
        self.table.verticalHeader().hide()
        lay.addWidget(self.table, 1)

        if self.single:  # L-1501: Zeilen bearbeiten
            row = QHBoxLayout()
            for text, slot in ((t("chapters.add"), self.add_row), (t("chapters.remove"), self.remove_rows)):
                btn = QPushButton(text, self)
                btn.clicked.connect(slot)
                row.addWidget(btn)
            row.addStretch(1)
            lay.addLayout(row)
        row = QHBoxLayout()  # L-1503: fester Abstand
        row.addWidget(QLabel(t("chapters.every"), self))
        self.spin = QSpinBox(self)
        self.spin.setRange(1, 180)
        self.spin.setSuffix(" " + t("chapters.minutes"))
        try:
            self.spin.setValue(int(self.settings.get("chapters_interval") or 10) if self.settings else 10)
        except (TypeError, ValueError):
            self.spin.setValue(10)
        if self.settings is not None:
            self.spin.valueChanged.connect(lambda v: self.settings.set("chapters_interval", v))
        row.addWidget(self.spin)
        btn = QPushButton(t("chapters.make"), self)
        btn.clicked.connect(self.make_interval)
        row.addWidget(btn)
        row.addSpacing(16)
        btn = QPushButton(t("chapters.clear"), self)  # L-1502
        btn.clicked.connect(self.clear)
        row.addWidget(btn)
        row.addStretch(1)
        lay.addLayout(row)
        if self.single:  # L-1505 bis L-1507: Datei einlesen bzw. speichern
            row = QHBoxLayout()
            self.found = chp.candidates(videos[0].path)
            if self.found:
                btn = QPushButton(t("chapters.import_found", name=os.path.basename(self.found[0])), self)
                btn.setToolTip(self.found[0])
                btn.clicked.connect(lambda: self.import_file(self.found[0]))
                row.addWidget(btn)
            btn = QPushButton(t("chapters.import"), self)
            btn.clicked.connect(lambda: self.import_file(None))
            row.addWidget(btn)
            btn = QPushButton(t("chapters.export"), self)
            btn.clicked.connect(self.export_file)
            row.addWidget(btn)
            row.addStretch(1)
            lay.addLayout(row)
        self.warning = QLabel("", self)
        self.warning.setWordWrap(True)
        self.warning.setVisible(False)
        lay.addWidget(self.warning)
        self.chk_replace = QCheckBox(t("tracks.replace"), self)  # L-1508: nur MP4
        self.chk_replace.setToolTip(t("chapters.replace_tip"))
        self.chk_replace.setChecked(bool(self.settings.get("chapters_replace_original")) if self.settings else False)
        if self.settings is not None:
            self.chk_replace.toggled.connect(lambda on: self.settings.set("chapters_replace_original", on))
        self.has_mp4 = has_mp4 = any(v.fmt == "mp4" for v in videos)
        self.chk_replace.setVisible(has_mp4)
        lay.addWidget(self.chk_replace)
        note = QLabel(t("chapters.note_mp4") if has_mp4 else t("chapters.note_mkv"), self)
        note.setWordWrap(True)
        note.setEnabled(False)
        lay.addWidget(note)
        box = QDialogButtonBox(self)
        ok = box.addButton(t("chapters.save"), QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setDefault(True)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    # --- ein Video: Tabelle -----------------------------------------------------------------------------
    def set_chapters(self, chapters: list[chp.Chapter]) -> None:
        self.table.setRowCount(0)
        for c in sorted(chapters, key=lambda c: c.start):
            self._append(c)

    def _append(self, c: chp.Chapter, at: int | None = None) -> int:
        r = self.table.rowCount() if at is None else at
        self.table.insertRow(r)
        self.table.setItem(r, COL_TIME, QTableWidgetItem(chp.short_time(c.start)))
        self.table.setItem(r, COL_NAME, QTableWidgetItem(c.name))
        return r

    def add_row(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        chs = self.table_chapters(strict=False)
        if rows and rows[-1] < len(chs):
            base = chs[rows[-1]].start
            nxt = chs[rows[-1] + 1].start if rows[-1] + 1 < len(chs) else self.videos[0].duration
            start, at = (base + nxt) / 2 if nxt > base else base + 60, rows[-1] + 1
        else:
            start, at = (chs[-1].start + 60 if chs else 0.0), None
        r = self._append(chp.Chapter(round(start), chp.default_name(self.table.rowCount() + 1)), at)
        self.table.setCurrentCell(r, COL_NAME)
        self.table.editItem(self.table.item(r, COL_NAME))

    def remove_rows(self) -> None:
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def table_chapters(self, strict: bool = True) -> list[chp.Chapter]:
        out = []
        for r in range(self.table.rowCount()):
            text = (self.table.item(r, COL_TIME).text() if self.table.item(r, COL_TIME) else "").strip()
            sec = chp.parse_time(text)
            if sec is None:
                if strict:
                    raise ValueError(r)
                continue
            name = self.table.item(r, COL_NAME).text().strip() if self.table.item(r, COL_NAME) else ""
            out.append(chp.Chapter(sec, name))
        return sorted(out, key=lambda c: c.start)

    def _show_warning(self, text: str) -> None:
        self.warning.setText("⚠ " + text if text else "")
        self.warning.setVisible(bool(text))

    # --- Aktionen -----------------------------------------------------------------------------------------
    def make_interval(self) -> None:
        minutes = self.spin.value()
        if self.single:
            self.set_chapters(chp.interval(self.videos[0].duration, minutes))
        else:
            for r, v in enumerate(self.videos):
                self.new[v.path] = chp.interval(v.duration, minutes)
                self.table.item(r, COL_NEW).setText(str(len(self.new[v.path])))
        self._show_warning("")

    def clear(self) -> None:
        if self.single:
            self.table.setRowCount(0)
        else:
            for r, v in enumerate(self.videos):
                self.new[v.path] = []
                self.table.item(r, COL_NEW).setText("0")
        self._show_warning("")

    def import_file(self, path: str | None) -> None:
        if path is None:
            path, _f = QFileDialog.getOpenFileName(self, t("chapters.import"), os.path.dirname(self.videos[0].path),
                                                   t("chapters.filter_all"))
            if not path:
                return
        try:
            chapters = chp.read_file(path)
        except (OSError, ValueError) as exc:
            show_error(self, t("chapters.title"), t("chapters.read_error", name=os.path.basename(path),
                                                       reason=str(exc)))
            return
        if not chapters:
            show_error(self, t("chapters.title"), t("chapters.none_in_file", name=os.path.basename(path)))
            return
        chapters, warn = chp.fit(chapters, self.videos[0].duration)
        self.set_chapters(chapters)
        self._show_warning(warn)

    def export_file(self) -> None:
        try:
            chapters = self.table_chapters()
        except ValueError as exc:
            self._bad_time(exc.args[0])
            return
        stem = os.path.splitext(self.videos[0].path)[0]
        path, chosen = QFileDialog.getSaveFileName(self, t("chapters.export"), stem + ".chapters.txt",
                                                   f"{t('chapters.filter_txt')};;{t('chapters.filter_xml')}")
        if not path:
            return
        if chosen == t("chapters.filter_xml") and not path.lower().endswith(".xml"):
            path = os.path.splitext(path)[0] + ".xml"
        try:
            chp.save_file(path, chapters, chp.chapter_language())
        except OSError as exc:
            show_error(self, t("chapters.title"), str(exc))

    def _bad_time(self, row: int) -> None:
        show_error(self, t("chapters.title"), t("chapters.bad_time", n=row + 1))
        self.table.setCurrentCell(row, COL_TIME)

    # --- Ergebnis -----------------------------------------------------------------------------------------
    def accept(self) -> None:
        if self.single:
            try:
                chapters = self.table_chapters()
            except ValueError as exc:
                self._bad_time(exc.args[0])
                return
            duration = self.videos[0].duration
            if duration > 0 and any(c.start >= duration for c in chapters):
                show_error(self, t("chapters.title"),
                           t("chapters.after_end", length=chp.short_time(duration).split(".")[0]))
                return
        super().accept()

    def result_chapters(self) -> dict[str, list]:
        """{Videopfad: neue Kapitel} – nur geänderte Videos."""
        if not self.single:
            return {p: chs for p, chs in self.new.items() if chs is not None}
        v = self.videos[0]
        chapters = self.table_chapters()
        for i, c in enumerate(chapters, 1):
            if not c.name:
                c.name = chp.default_name(i)
        same = len(chapters) == len(v.chapters) and all(
            abs(a.start - b.start) < 0.0015 and a.name == b.name for a, b in zip(chapters, v.chapters))
        return {} if same else {v.path: chapters}

    def replace_wanted(self) -> bool:
        return self.has_mp4 and self.chk_replace.isChecked()
