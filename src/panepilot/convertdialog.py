"""Dialog „Format wechseln …“ im Video-Modus (v1.13, L-1330 ff.)."""

from __future__ import annotations

import os

from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QRadioButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from . import videoremux as vr
from .dialogs import free_window
from .i18n import t


class ConvertDialog(QDialog):
    def __init__(self, parent, files: list) -> None:
        """files: [(Pfad, FileTracks oder None)]"""
        super().__init__(parent)
        free_window(self)
        self.files = files
        self.setWindowTitle(t("convert.title"))
        self.resize(760, 460)
        lay = QVBoxLayout(self)
        intro = QLabel(t("convert.intro"), self)
        intro.setWordWrap(True)
        lay.addWidget(intro)
        row = QHBoxLayout()
        row.addWidget(QLabel(t("convert.target"), self))
        self.group = QButtonGroup(self)
        self.rb_mkv = QRadioButton("MKV", self)
        self.rb_mp4 = QRadioButton("MP4", self)
        for b in (self.rb_mkv, self.rb_mp4):
            self.group.addButton(b)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.tree = QTreeWidget(self)
        self.tree.setRootIsDecorated(False)
        self.tree.setHeaderLabels([t("convert.col_file"), t("convert.col_result")])
        self.tree.setColumnWidth(0, 360)
        lay.addWidget(self.tree, 1)
        settings = getattr(parent, "settings", None)
        self.chk_replace = QCheckBox(t("convert.replace"), self)  # v1.13.2
        self.chk_replace.setToolTip(t("convert.replace_tip"))
        self.chk_replace.setChecked(bool(settings.get("convert_replace_original")) if settings else False)
        if settings is not None:
            self.chk_replace.toggled.connect(lambda on: settings.set("convert_replace_original", on))
        lay.addWidget(self.chk_replace)
        note = QLabel(t("convert.note"), self)
        note.setWordWrap(True)
        note.setEnabled(False)
        lay.addWidget(note)
        box = QDialogButtonBox(self)
        self.btn_ok = box.addButton(t("convert.start"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_ok.setDefault(True)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        # Vorgabe: was die meisten Dateien noch nicht sind – meist MKV (L-1331)
        mkv = sum(1 for p, _f in files if p.lower().endswith((".mkv", ".webm")))
        (self.rb_mp4 if mkv > len(files) / 2 else self.rb_mkv).setChecked(True)
        self.group.buttonToggled.connect(lambda *_: self._fill())
        self._fill()

    def target(self) -> str:
        return vr.MP4 if self.rb_mp4.isChecked() else vr.MKV

    def plan(self) -> list[tuple[str, object, str, str]]:
        """(Pfad, FileTracks, Grund fürs Auslassen, neuer Name)"""
        out = []
        target = self.target()
        for path, files in self.files:
            problem = files.error if files is not None and files.error else vr.convert_problem(path, target, files)
            new = "" if problem else vr.copy_name(path, ".mkv" if target == vr.MKV else ".mp4")
            out.append((path, files, problem, new))
        return out

    def _fill(self) -> None:
        self.tree.clear()
        ok = 0
        for path, _files, problem, new in self.plan():
            item = QTreeWidgetItem(self.tree)
            item.setText(0, os.path.basename(path))
            if problem:
                item.setText(1, t("convert.skip", reason=problem))
                item.setForeground(1, self.palette().placeholderText())
            else:
                item.setText(1, "→ " + os.path.basename(new))
                ok += 1
        self.btn_ok.setEnabled(ok > 0)

    def replace_wanted(self) -> bool:
        return self.chk_replace.isChecked()

    def jobs(self) -> list[tuple[str, object]]:
        return [(p, f) for p, f, problem, _n in self.plan() if not problem]

    def skipped(self) -> list[str]:
        return [f"{os.path.basename(p)}: {problem}" for p, _f, problem, _n in self.plan() if problem]
