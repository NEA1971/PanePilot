"""Dialog „Spuren …“ im Video-Modus (v1.11, L-1100 ff.): Sprache, Name und Kennzeichen von MKV-Spuren."""

from __future__ import annotations

import os
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from . import mkvtracks as mt
from .dialogs import free_window
from .i18n import t

COL_TRACK, COL_FORMAT, COL_LANG, COL_NAME, COL_DEFAULT, COL_FORCED, COL_REMOVE = range(7)


def lang_label(code: str) -> str:
    from .tracks import language_name

    if not code or code == "und":
        return f"{t('track.unknown')} (und)"
    name = language_name(code)
    return f"{name} ({code})" if name else code


def parse_lang(text: str) -> str:
    """„Deutsch (ger)“ → ger; „ger“ → ger; „Deutsch“ → ger, soweit in der Liste."""
    text = (text or "").strip()
    m = re.search(r"\(([A-Za-z]{2,3}(?:-[A-Za-z0-9]+)*)\)\s*$", text)
    if m:
        return m.group(1).lower() if len(m.group(1)) <= 3 else m.group(1)
    if re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]+)*", text):
        return text.lower() if len(text) <= 3 else text
    for code in mt.LANGUAGES:
        if lang_label(code).split(" (")[0].casefold() == text.casefold():
            return code
    return text


class Row:
    """Eine Zeile: eine Spur (eine Datei) bzw. „Tonspur n“ über mehrere Dateien."""

    def __init__(self, kind: str, index: int, tracks: list[mt.MkvTrack]) -> None:
        self.kind, self.index, self.tracks = kind, index, tracks

    def common(self, attr: str):
        values = {getattr(tr, attr) for tr in self.tracks}
        return values.pop() if len(values) == 1 else None  # None = verschieden


class TrackDialog(QDialog):
    def __init__(self, parent, files: list[mt.FileTracks], on_export=None) -> None:
        super().__init__(parent)
        self.on_export = on_export  # v1.13: Untertitel exportieren ohne Entfernen (L-1321)
        free_window(self)
        self.files = files
        self.setWindowTitle(t("tracks.title"))
        self.resize(900, 480)
        lay = QVBoxLayout(self)
        if len(files) == 1:
            intro = t("tracks.intro_one", name=os.path.basename(files[0].path))
        else:
            intro = t("tracks.intro_many", n=len(files))
        label = QLabel(intro, self)
        label.setWordWrap(True)
        lay.addWidget(label)
        self.rows = self._rows()
        self.table = QTableWidget(len(self.rows), 7, self)
        self.table.setHorizontalHeaderLabels([t("tracks.col_track"), t("tracks.col_format"), t("tracks.col_lang"),
                                              t("tracks.col_name"), t("tracks.col_default"),
                                              t("tracks.col_forced"), t("tracks.col_remove")])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        head.setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.Stretch)
        # v1.15, L-1510: Klick auf „Erzwungen“ / „Entfernen“ hakt alle an bzw. wieder ab
        for col in (COL_FORCED, COL_REMOVE):
            self.table.horizontalHeaderItem(col).setToolTip(t("tracks.header_toggle"))
        head.sectionClicked.connect(self.toggle_column)
        self.widgets: list[dict] = []
        for r, row in enumerate(self.rows):
            self._fill(r, row)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(COL_LANG, max(self.table.columnWidth(COL_LANG), 190))
        lay.addWidget(self.table, 1)
        bar = QHBoxLayout()
        self.btn_suggest = QPushButton(t("tracks.suggest"), self)
        self.btn_suggest.setToolTip(t("tracks.suggest_tip"))
        self.btn_suggest.clicked.connect(self.suggest_names)
        bar.addWidget(self.btn_suggest)
        self.btn_export = QPushButton(t("tracks.export"), self)
        self.btn_export.setToolTip(t("tracks.export_tip"))
        self.btn_export.clicked.connect(self._export)
        self.btn_export.setEnabled(on_export is not None and any(r.kind == mt.SUBS for r in self.rows))
        bar.addWidget(self.btn_export)
        self.adds: list = []  # v1.14, L-1410: Untertiteldateien, die dazukommen
        self.btn_add = QPushButton(t("tracks.add_subs"), self)
        self.btn_add.setToolTip(t("tracks.add_subs_tip") if len(files) == 1 else t("tracks.add_subs_one"))
        self.btn_add.setEnabled(len(files) == 1)
        self.btn_add.clicked.connect(self._add_subs)
        bar.addWidget(self.btn_add)
        self.lbl_add = QLabel("", self)
        bar.addWidget(self.lbl_add)
        bar.addSpacing(16)
        settings = getattr(parent, "settings", None)
        self.chk_export = QCheckBox(t("tracks.export_before"), self)  # L-1320; gemerkt seit v1.13.3
        saved = settings.get("tracks_export_before") if settings is not None else None
        self.chk_export.setChecked(True if saved is None else bool(saved))
        if settings is not None:
            self.chk_export.toggled.connect(lambda on: settings.set("tracks_export_before", on))
        bar.addWidget(self.chk_export)
        self.chk_replace = QCheckBox(t("tracks.replace"), self)  # v1.13.2
        self.chk_replace.setToolTip(t("tracks.replace_tip"))
        self.chk_replace.setChecked(bool(settings.get("tracks_replace_original")) if settings else False)
        if settings is not None:
            self.chk_replace.toggled.connect(lambda on: settings.set("tracks_replace_original", on))
        bar.addWidget(self.chk_replace)
        bar.addStretch(1)
        lay.addLayout(bar)
        hint = QLabel(t("tracks.hint"), self)
        hint.setWordWrap(True)
        hint.setEnabled(False)
        lay.addWidget(hint)
        box = QDialogButtonBox(self)
        ok = box.addButton(t("online.apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        ok.setDefault(True)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def _rows(self) -> list[Row]:
        keys: dict[tuple[str, int], list[mt.MkvTrack]] = {}
        for f in self.files:
            for tr in f.tracks:
                keys.setdefault((tr.kind, tr.index), []).append(tr)
        order = {k: i for i, k in enumerate(mt.KINDS)}
        return [Row(k, i, trs) for (k, i), trs in sorted(keys.items(), key=lambda kv: (order[kv[0][0]], kv[0][1]))]

    def _fill(self, r: int, row: Row) -> None:
        label = mt.kind_label(row.kind, row.index)
        if len(self.files) > 1:
            label += "  " + t("tracks.in_files", n=len(row.tracks), total=len(self.files))
        item = QTableWidgetItem(label)
        self.table.setItem(r, COL_TRACK, item)
        codec = row.common("codec")
        fmt = mt.short_codec(codec) if codec is not None else t("tracks.mixed")
        if row.kind == mt.AUDIO:
            ch = row.common("channels")
            if ch:
                fmt += f" {mt._channels(ch)}"
        self.table.setItem(r, COL_FORMAT, QTableWidgetItem(fmt.strip()))
        w: dict = {}
        if row.kind != mt.VIDEO:
            combo = QComboBox(self.table)
            combo.setEditable(True)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            for code in mt.LANGUAGES:
                combo.addItem(lang_label(code), code)
            lang = row.common("lang")
            if lang is None:
                combo.setCurrentIndex(-1)
                combo.lineEdit().setPlaceholderText(t("tracks.mixed"))
                combo.setEditText("")
            else:
                i = combo.findData(lang)
                if i < 0:
                    combo.addItem(lang_label(lang), lang)
                    i = combo.count() - 1
                combo.setCurrentIndex(i)
            self.table.setCellWidget(r, COL_LANG, combo)
            w["lang"] = combo
            w["lang0"] = lang
        name = row.common("name")
        edit = QLineEdit(name or "", self.table)
        if name is None:
            edit.setPlaceholderText(t("tracks.mixed"))
        self.table.setCellWidget(r, COL_NAME, edit)
        w["name"], w["name0"] = edit, name
        for col, attr in ((COL_DEFAULT, "default"), (COL_FORCED, "forced")):
            if row.kind == mt.VIDEO:
                continue
            box = QCheckBox(self.table)
            if attr == "forced" and self._mp4_only(row):  # L-1204: MP4 kennt „Erzwungen“ kaum
                box.setEnabled(False)
                box.setToolTip(t("tracks.forced_mp4"))
            value = row.common(attr)
            if value is None:
                box.setTristate(True)
                box.setCheckState(Qt.CheckState.PartiallyChecked)
            else:
                box.setChecked(value)
            holder = QWidget(self.table)
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(box, 0, Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(r, col, holder)
            w[attr] = box
            w[attr + "0"] = value
        if row.kind != mt.VIDEO:  # L-1310/L-1311: Spuren entfernen (neue Datei)
            box = QCheckBox(self.table)
            single_audio = row.kind == mt.AUDIO and len(self.files) == 1 and \
                sum(1 for tr in self.files[0].tracks if tr.kind == mt.AUDIO) <= 1
            if single_audio:
                box.setEnabled(False)
                box.setToolTip(t("tracks.last_audio"))
            else:
                box.setToolTip(t("tracks.remove_tip"))
            holder = QWidget(self.table)
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.addWidget(box, 0, Qt.AlignmentFlag.AlignCenter)
            self.table.setCellWidget(r, COL_REMOVE, holder)
            w["remove"] = box
        self.widgets.append(w)

    def _mp4_only(self, row: Row) -> bool:
        fmt = {id(tr): f.fmt for f in self.files for tr in f.tracks}
        return all(fmt.get(id(tr)) == "mp4" for tr in row.tracks)

    # --- Werte ----------------------------------------------------------------------------------
    def _lang_of(self, r: int) -> str | None:
        w = self.widgets[r]
        combo = w.get("lang")
        if combo is None:
            return None
        text = combo.currentText().strip()
        if not text:
            return None  # leer bei „verschieden“: unverändert
        i = combo.currentIndex()
        if i >= 0 and combo.itemText(i) == text:
            return combo.itemData(i)
        return parse_lang(text)

    def change_of(self, r: int) -> mt.TrackChange:
        w = self.widgets[r]
        ch = mt.TrackChange()
        lang = self._lang_of(r)
        if lang is not None and lang != w.get("lang0"):
            ch.lang = lang
        name = w["name"].text().strip()
        if not (w["name0"] is None and not name) and name != (w["name0"] or ""):
            ch.name = name
        for attr in ("default", "forced"):
            box = w.get(attr)
            if box is None or not box.isEnabled() or box.checkState() == Qt.CheckState.PartiallyChecked:
                continue
            value = box.isChecked()
            if value != w.get(attr + "0"):
                setattr(ch, attr, value)
        return ch

    def suggest_names(self) -> None:
        """L-1103: markierte Zeilen, sonst alle Ton- und Untertitelzeilen."""
        rows = sorted({i.row() for i in self.table.selectedIndexes()}) or range(len(self.rows))
        for r in rows:
            row = self.rows[r]
            if row.kind == mt.VIDEO:
                continue
            lang = self._lang_of(r) or row.common("lang") or ""
            forced_box = self.widgets[r].get("forced")
            forced = forced_box is not None and forced_box.checkState() == Qt.CheckState.Checked
            codec = row.common("codec") or ""
            channels = row.common("channels") or 0
            name = mt.suggest_name(row.kind, lang, codec, channels, forced)
            if name:
                self.widgets[r]["name"].setText(name)

    def toggle_column(self, col: int) -> None:
        """Alle anhaken; sind schon alle angehakt, alle Haken heraus (L-1510, L-1511)."""
        key = {COL_FORCED: "forced", COL_REMOVE: "remove"}.get(col)
        if key is None:
            return
        boxes = [w[key] for w in self.widgets if w.get(key) is not None and w[key].isEnabled()]
        if not boxes:
            return
        on = not all(b.checkState() == Qt.CheckState.Checked for b in boxes)
        for b in boxes:
            b.setTristate(False)
            b.setChecked(on)

    def removals(self) -> tuple[dict[str, list], list[str]]:
        """{Datei: [Spuren zum Entfernen]} und Hinweise (fehlende Spur, letzte Tonspur bleibt)."""
        out: dict[str, list] = {}
        notes: list[str] = []
        for f in self.files:
            gone = []
            for r, row in enumerate(self.rows):
                box = self.widgets[r].get("remove")
                if box is None or not box.isChecked():
                    continue
                tr = f.find(row.kind, row.index)
                if tr is None:
                    notes.append(f"{os.path.basename(f.path)} – {mt.kind_label(row.kind, row.index)}")
                else:
                    gone.append(tr)
            audio = [tr for tr in f.tracks if tr.kind == mt.AUDIO]
            if audio and all(any(tr is g for g in gone) for tr in audio):  # L-1311: letzte Tonspur bleibt
                keep = audio[0]
                gone = [g for g in gone if g is not keep]
                notes.append(f"{os.path.basename(f.path)} – {mt.kind_label(keep.kind, keep.index)}: "
                             f"{t('tracks.last_audio')}")
            if gone:
                out[f.path] = gone
        return out, notes

    def replace_wanted(self) -> bool:
        return self.chk_replace.isChecked()

    def export_wanted(self) -> bool:
        return self.chk_export.isChecked()

    def selected_subtitles(self) -> list[tuple[mt.FileTracks, list]]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        rows = [r for r in rows if self.rows[r].kind == mt.SUBS] or \
            [r for r, row in enumerate(self.rows) if row.kind == mt.SUBS]
        out = []
        for f in self.files:
            trs = [f.find(self.rows[r].kind, self.rows[r].index) for r in rows]
            trs = [tr for tr in trs if tr is not None]
            if trs:
                out.append((f, trs))
        return out

    def _add_subs(self) -> None:
        from .subsdialog import AddSubtitlesDialog

        dlg = AddSubtitlesDialog(self, self.files[0], self.adds)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.adds = dlg.additions()
            self.lbl_add.setText(t("tracks.add_count", n=len(self.adds)) if self.adds else "")

    def additions(self) -> dict[str, list]:
        """{Datei: [SubAdd]} – nur bei einem Video (L-1410)."""
        return {self.files[0].path: list(self.adds)} if self.adds and len(self.files) == 1 else {}

    def _export(self) -> None:
        if self.on_export is not None:
            self.on_export(self.selected_subtitles())

    def edits(self) -> tuple[dict[str, list], list[str]]:
        """{Datei: [(Spur, Änderung)]} und Liste „Datei – Spur fehlt“ (L-1105)."""
        out: dict[str, list] = {}
        missing: list[str] = []
        for r, row in enumerate(self.rows):
            ch = self.change_of(r)
            if ch.empty():
                continue
            for f in self.files:
                tr = f.find(row.kind, row.index)
                if tr is None:
                    missing.append(f"{os.path.basename(f.path)} – {mt.kind_label(row.kind, row.index)}")
                    continue
                if f.has_effect(tr, ch):
                    out.setdefault(f.path, []).append((tr, ch))
        return out, missing
