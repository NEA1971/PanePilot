"""Dialoge für Untertitel (v1.14): Treffer von OpenSubtitles (L-1404) und Untertiteldateien hinzufügen (L-1410)."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import mkvtracks as mt
from . import opensubs as osb
from . import videoremux as vr
from .dialogs import free_window
from .i18n import t

ROLE = Qt.ItemDataRole.UserRole + 1


def flags_text(hit: osb.Hit) -> str:
    parts = []
    if hit.hash_match:
        parts.append(t("subs.flag_match"))
    if hit.forced:
        parts.append(t("subs.flag_forced"))
    if hit.sdh:
        parts.append(t("subs.flag_sdh"))
    return ", ".join(parts)


class SubtitleSearchDialog(QDialog):
    """Je Video eine Gruppe mit den Treffern; je Sprache ist der beste vorgewählt."""

    def __init__(self, parent, results: list, languages: list[str], remaining: int | None,
                 can_embed: bool, logged_in: bool) -> None:
        """results: [(Videopfad, Anzeigename, [Hit], Fehlertext)]"""
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("subs.title"))
        self.resize(980, 560)
        lay = QVBoxLayout(self)
        found = sum(1 for r in results if r[2])
        intro = QLabel(t("subs.intro", n=found, total=len(results)), self)
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels([t("subs.col_lang"), t("subs.col_release"), t("subs.col_downloads"),
                                   t("subs.col_rating"), t("subs.col_flags")])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.rows: list[tuple[str, QTreeWidgetItem, osb.Hit]] = []
        from .trackdialog import lang_label

        for path, name, hits, error in results:
            top = QTreeWidgetItem(self.tree)
            top.setFirstColumnSpanned(True)
            if error or not hits:
                top.setText(0, f"{name} – {error or t('subs.none')}")
                top.setForeground(0, self.palette().placeholderText())
                continue
            top.setText(0, f"{name} – {t('subs.hits', n=len(hits))}")
            best = {id(h) for h in osb.best_per_language(hits, languages)}
            order = {lang: i for i, lang in enumerate(languages)}
            for hit in sorted(hits, key=lambda h: (order.get(h.lang.lower().split("-")[0], 99), h.sort_key())):
                child = QTreeWidgetItem(top)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked if id(hit) in best else Qt.CheckState.Unchecked)
                child.setText(0, lang_label(osb.to_mkv_lang(hit.lang)))
                child.setText(1, hit.release or hit.file_name)
                child.setToolTip(1, hit.file_name)
                child.setText(2, str(hit.downloads))
                child.setText(3, f"{hit.rating:.1f}" if hit.rating else "")
                child.setText(4, flags_text(hit))
                self.rows.append((path, child, hit))
        self.tree.expandAll()
        head = self.tree.header()
        head.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(0, 190)
        self.tree.setColumnWidth(1, 400)
        lay.addWidget(self.tree, 1)
        if remaining is not None:
            quota = t("subs.remaining", n=remaining)
        else:
            quota = t("subs.remaining_unknown") if logged_in else t("subs.anonymous")
        self.quota = QLabel("ℹ " + quota, self)
        self.quota.setWordWrap(True)
        lay.addWidget(self.quota)
        settings = getattr(parent, "settings", None)
        bar = QHBoxLayout()
        self.chk_direct = QCheckBox(t("subs.direct"), self)  # L-1405
        self.chk_direct.setToolTip(t("subs.direct_tip"))
        self.chk_direct.setEnabled(can_embed)
        self.chk_direct.setChecked(can_embed and bool(settings.get("subs_direct")) if settings else False)
        self.chk_replace = QCheckBox(t("tracks.replace"), self)
        self.chk_replace.setToolTip(t("tracks.replace_tip"))
        self.chk_replace.setChecked(bool(settings.get("tracks_replace_original")) if settings else False)
        self.chk_replace.setEnabled(self.chk_direct.isChecked())
        self.chk_direct.toggled.connect(self.chk_replace.setEnabled)
        if settings is not None:
            self.chk_direct.toggled.connect(lambda on: settings.set("subs_direct", on))
            self.chk_replace.toggled.connect(lambda on: settings.set("tracks_replace_original", on))
        bar.addWidget(self.chk_direct)
        bar.addWidget(self.chk_replace)
        bar.addStretch(1)
        lay.addLayout(bar)
        note = QLabel(t("subs.note"), self)
        note.setWordWrap(True)
        note.setEnabled(False)
        lay.addWidget(note)
        box = QDialogButtonBox(self)
        self.btn_ok = box.addButton(t("subs.download"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_ok.setDefault(True)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.tree.itemChanged.connect(lambda *_: self._update())
        self._update()

    def _update(self) -> None:
        self.btn_ok.setEnabled(bool(self.selected()))

    def selected(self) -> list[tuple[str, osb.Hit]]:
        return [(p, h) for p, item, h in self.rows if item.checkState(0) == Qt.CheckState.Checked]

    def direct_wanted(self) -> bool:
        return self.chk_direct.isEnabled() and self.chk_direct.isChecked()

    def replace_wanted(self) -> bool:
        return self.direct_wanted() and self.chk_replace.isChecked()


# --- Untertiteldateien ins Video übernehmen (L-1410) ---------------------------------------------------------
COL_USE, COL_FILE, COL_LANG, COL_NAME, COL_FORCED = range(5)


class AddSubtitlesDialog(QDialog):
    def __init__(self, parent, files: mt.FileTracks, current: list[vr.SubAdd] | None = None) -> None:
        super().__init__(parent)
        free_window(self)
        self.files = files
        self.setWindowTitle(t("addsubs.title"))
        self.resize(880, 380)
        lay = QVBoxLayout(self)
        intro = QLabel(t("addsubs.intro", name=os.path.basename(files.path)), self)
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(["", t("addsubs.col_file"), t("tracks.col_lang"), t("tracks.col_name"),
                                              t("tracks.col_forced")])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        head.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)
        self.widgets: list[dict] = []
        chosen = {os.path.abspath(a.path): a for a in current or []}
        for path in vr.subtitle_candidates(files.path):
            a = chosen.pop(os.path.abspath(path), None)
            self._add_row(a or vr.parse_sub_name(files.path, path), a is not None or not current)
        for a in chosen.values():
            self._add_row(a, True)
        self.table.setColumnWidth(COL_USE, 30)
        self.table.setColumnWidth(COL_FILE, 300)
        self.table.setColumnWidth(COL_LANG, 190)
        bar = QHBoxLayout()
        more = QPushButton(t("addsubs.more"), self)
        more.clicked.connect(self._pick)
        bar.addWidget(more)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.empty = QLabel(t("addsubs.none"), self)
        self.empty.setEnabled(False)
        self.empty.setVisible(not self.widgets)
        lay.addWidget(self.empty)
        if files.fmt != "mkv":
            note = QLabel(t("addsubs.mp4_note"), self)
            note.setWordWrap(True)
            note.setEnabled(False)
            lay.addWidget(note)
        box = QDialogButtonBox(self)
        ok = box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setDefault(True)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _add_row(self, add: vr.SubAdd, use: bool) -> None:
        from .trackdialog import lang_label

        r = self.table.rowCount()
        self.table.insertRow(r)
        w: dict = {"path": add.path}
        image = vr.is_image_sub(add.path) and self.files.fmt != "mkv"
        box = QCheckBox(self.table)
        box.setChecked(use and not image)
        box.setEnabled(not image)
        if image:
            box.setToolTip(t("remux.image_subs_add"))
        self.table.setCellWidget(r, COL_USE, _centered(self.table, box))
        w["use"] = box
        item = QTableWidgetItem(os.path.basename(add.path))
        item.setToolTip(add.path)
        self.table.setItem(r, COL_FILE, item)
        combo = QComboBox(self.table)
        combo.setEditable(True)
        codes = list(mt.LANGUAGES)
        if add.lang and add.lang not in codes:
            codes.insert(0, add.lang)
        for code in codes:
            combo.addItem(lang_label(code), code)
        combo.setCurrentIndex(max(combo.findData(add.lang or "und"), 0))
        self.table.setCellWidget(r, COL_LANG, combo)
        w["lang"] = combo
        name = QLineEdit(add.name or mt.suggest_name(mt.SUBS, add.lang, "srt", 0, add.forced), self.table)
        self.table.setCellWidget(r, COL_NAME, name)
        w["name"] = name
        forced = QCheckBox(self.table)
        forced.setChecked(add.forced)
        self.table.setCellWidget(r, COL_FORCED, _centered(self.table, forced))
        w["forced"] = forced
        w["default"] = add.default
        self.widgets.append(w)

    def _pick(self) -> None:
        pattern = " ".join("*" + e for e in vr.SUB_EXTENSIONS)
        paths, _f = QFileDialog.getOpenFileNames(self, t("addsubs.more"), os.path.dirname(self.files.path),
                                                 f"{t('addsubs.filter')} ({pattern})")
        known = {os.path.abspath(w["path"]) for w in self.widgets}
        for p in paths:
            if os.path.abspath(p) not in known:
                self._add_row(vr.parse_sub_name(self.files.path, p), True)
        self.empty.setVisible(not self.widgets)

    def additions(self) -> list[vr.SubAdd]:
        from .trackdialog import parse_lang

        out = []
        for w in self.widgets:
            if not w["use"].isChecked():
                continue
            combo = w["lang"]
            text = combo.currentText().strip()
            i = combo.currentIndex()
            lang = combo.itemData(i) if i >= 0 and combo.itemText(i) == text else parse_lang(text)
            out.append(vr.SubAdd(w["path"], lang or "und", w["name"].text().strip(), w["forced"].isChecked(),
                                 w["default"]))
        return out


def _centered(parent, widget) -> QWidget:
    holder = QWidget(parent)
    hl = QHBoxLayout(holder)
    hl.setContentsMargins(0, 0, 0, 0)
    hl.addWidget(widget, 0, Qt.AlignmentFlag.AlignCenter)
    return holder
