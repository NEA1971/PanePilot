"""Seitenleiste „Mehrfach umbenennen“ (F-710 ff.) und Vorschau-Modell (F-720 ff.)."""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import multirename as mr
from .config import config_dir
from .i18n import t
from .util import format_size

PROFILES_DIR = "Umbenennen"

PREVIEW_OLD, PREVIEW_NEW, PREVIEW_SIZE, PREVIEW_DATE, PREVIEW_CREATED = range(5)
PREVIEW_KEYS = ("rename.col_old", "rename.col_new", "column.size", "column.date", "column.created")


# --- Profile ----------------------------------------------------------------------------------
def profiles_folder() -> str:
    path = os.path.join(str(config_dir()), PROFILES_DIR)
    os.makedirs(path, exist_ok=True)
    return path


def profile_names() -> list[str]:
    try:
        files = os.listdir(profiles_folder())
    except OSError:
        return []
    return sorted((f[:-5] for f in files if f.endswith(".json") and not f.startswith(".")), key=str.casefold)


def load_profile(name: str) -> mr.RenameOptions:
    from .config import load_json

    return mr.RenameOptions.from_dict(load_json(f"{PROFILES_DIR}/{name}.json", {}))


def save_profile(name: str, opts: mr.RenameOptions) -> None:
    from .config import save_json

    save_json(f"{PROFILES_DIR}/{name}.json", opts.to_dict())


def delete_profile(name: str) -> None:
    os.unlink(os.path.join(profiles_folder(), name + ".json"))


# --- Vorschau ---------------------------------------------------------------------------------
class PreviewModel(QAbstractTableModel):
    """Name alt / Name neu / Größe / Geändert / Erstellt."""

    def __init__(self, icons, parent=None) -> None:
        super().__init__(parent)
        self._icons = icons
        self.entries: list = []  # filemodel.Entry
        self.results: list[mr.Result] = []

    def set_data(self, entries: list, results: list[mr.Result]) -> None:
        self.beginResetModel()
        self.entries = entries
        self.results = results
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.results)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(PREVIEW_KEYS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return t(PREVIEW_KEYS[section])
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.TextAlignmentRole and section == PREVIEW_SIZE:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        e = self.entries[index.row()]
        r = self.results[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == PREVIEW_OLD:
                return r.old
            if col == PREVIEW_NEW:
                return r.new
            if col == PREVIEW_SIZE:
                return "" if e.is_dir else format_size(e.size)
            if col == PREVIEW_DATE:
                return datetime.fromtimestamp(e.mtime).strftime("%d.%m.%Y %H:%M")
            if col == PREVIEW_CREATED:
                bt = e.birth_time()
                return datetime.fromtimestamp(bt).strftime("%d.%m.%Y %H:%M") if bt >= 0 else ""
        if role == Qt.ItemDataRole.DecorationRole and col == PREVIEW_OLD:
            return self._icons.dir_icon(e.path) if e.is_dir else self._icons.for_file(e.path)
        if role == Qt.ItemDataRole.ForegroundRole:
            if r.status == mr.CONFLICT:
                return QColor("#D32F2F")
            if r.status == mr.SAME and col == PREVIEW_NEW:
                return QColor("#9A9A9A")
            if r.status == mr.OK and col == PREVIEW_NEW:
                return QColor("#2E7D32")  # geändert: grün, normale Schrift
        if role == Qt.ItemDataRole.ToolTipRole and r.status == mr.CONFLICT:
            return t(r.reason, name=r.new)
        if role == Qt.ItemDataRole.TextAlignmentRole and col == PREVIEW_SIZE:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


# --- Seitenleiste -----------------------------------------------------------------------------
class RenamePane(QWidget):
    changed = Signal()  # Einstellungen geändert → Vorschau neu berechnen
    rename_clicked = Signal()
    cancel_clicked = Signal()
    save_profile_clicked = Signal()
    delete_profile_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("renamePane")
        self._loading = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self.changed)

        title = QLabel(t("rename.title"), self)
        title.setObjectName("renameTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Profile (F-730)
        self.profile_box = QComboBox(self)
        self.profile_box.setMinimumContentsLength(10)
        self.btn_save = QPushButton(t("rename.profile_save"), self)
        self.btn_delete = QPushButton(t("rename.profile_delete"), self)
        prow = QHBoxLayout()
        prow.addWidget(self.profile_box, 1)
        prow.addWidget(self.btn_save)
        prow.addWidget(self.btn_delete)
        gp = QGroupBox(t("rename.profile"), self)
        gp.setLayout(prow)

        # Muster (F-710)
        self.pattern = QLineEdit(self)
        self.ext_pattern = QLineEdit(self)
        self.pattern_btn = self._placeholder_button(self.pattern)
        self.ext_btn = self._placeholder_button(self.ext_pattern)
        fm = QFormLayout()
        fm.addRow(t("rename.pattern"), self._with_button(self.pattern, self.pattern_btn))
        fm.addRow(t("rename.ext_pattern"), self._with_button(self.ext_pattern, self.ext_btn))
        self.case_box = QComboBox(self)
        for key, mode in (("rename.case_none", mr.CASE_NONE), ("rename.case_upper", mr.CASE_UPPER),
                          ("rename.case_lower", mr.CASE_LOWER), ("rename.case_first", mr.CASE_FIRST),
                          ("rename.case_words", mr.CASE_WORDS)):
            self.case_box.addItem(t(key), mode)
        fm.addRow(t("rename.case"), self.case_box)
        self.include_ext = QCheckBox(t("rename.include_ext"), self)
        fm.addRow(self.include_ext)
        gm = QGroupBox(t("rename.group_pattern"), self)
        gm.setLayout(fm)

        # Suchen und Ersetzen (F-711)
        self.search = QLineEdit(self)
        self.replace = QLineEdit(self)
        self.mode_text = QRadioButton(t("rename.mode_text"), self)
        self.mode_wild = QRadioButton(t("rename.mode_wildcard"), self)
        self.mode_regex = QRadioButton(t("rename.mode_regex"), self)
        self.mode_group = QButtonGroup(self)
        for i, b in enumerate((self.mode_text, self.mode_wild, self.mode_regex)):
            self.mode_group.addButton(b, i)
        self.replace_all = QCheckBox(t("rename.replace_all"), self)
        self.search_case = QCheckBox(t("rename.search_case"), self)
        self.search_error = QLabel(self)
        self.search_error.setStyleSheet("color: #D32F2F;")
        self.search_error.setWordWrap(True)
        fs = QFormLayout()
        fs.addRow(t("rename.search"), self.search)
        fs.addRow(t("rename.replace"), self.replace)
        mrow = QHBoxLayout()
        for b in (self.mode_text, self.mode_wild, self.mode_regex):
            mrow.addWidget(b)
        mrow.addStretch(1)
        fs.addRow(mrow)
        fs.addRow(self.replace_all)
        fs.addRow(self.search_case)
        fs.addRow(self.search_error)
        gs = QGroupBox(t("rename.group_search"), self)
        gs.setLayout(fs)

        # Datum (F-713)
        self.date_source = QComboBox(self)
        for key, src in (("rename.date_now", mr.DATE_NOW), ("rename.date_mtime", mr.DATE_MTIME),
                         ("rename.date_created", mr.DATE_CREATED)):
            self.date_source.addItem(t(key), src)
        self.date_format = QComboBox(self)
        self.date_format.setEditable(True)
        self.date_format.addItems(mr.DATE_FORMATS)
        fd = QFormLayout()
        fd.addRow(t("rename.date_source"), self.date_source)
        fd.addRow(t("rename.date_format"), self.date_format)
        hint = QLabel(t("rename.date_hint"), self)
        hint.setWordWrap(True)
        hint.setEnabled(False)
        fd.addRow(hint)
        gd = QGroupBox(t("rename.group_date"), self)
        gd.setLayout(fd)

        # Zähler (F-714)
        self.counter_start = QSpinBox(self)
        self.counter_start.setRange(-999999, 99999999)
        self.counter_step = QSpinBox(self)
        self.counter_step.setRange(-9999, 9999)
        self.counter_digits = QSpinBox(self)
        self.counter_digits.setRange(1, 10)
        fc = QFormLayout()
        fc.addRow(t("rename.counter_start"), self.counter_start)
        fc.addRow(t("rename.counter_step"), self.counter_step)
        fc.addRow(t("rename.counter_digits"), self.counter_digits)
        gc = QGroupBox(t("rename.group_counter"), self)
        gc.setLayout(fc)

        inner = QWidget(self)
        il = QVBoxLayout(inner)
        il.setContentsMargins(4, 4, 4, 4)
        for w in (gp, gm, gs, gd, gc):
            il.addWidget(w)
        il.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)

        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        self.btn_rename = QPushButton(t("rename.do_rename"), self)
        self.btn_rename.setDefault(True)
        self.btn_cancel = QPushButton(t("button.cancel"), self)
        brow = QHBoxLayout()
        brow.addWidget(self.btn_rename, 1)
        brow.addWidget(self.btn_cancel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 4)
        layout.addWidget(title)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.summary)
        layout.addLayout(brow)

        for w in (self.pattern, self.ext_pattern, self.search, self.replace):
            w.textChanged.connect(self._schedule)
        self.date_format.editTextChanged.connect(self._schedule)
        for w in (self.case_box, self.date_source):
            w.currentIndexChanged.connect(self._schedule)
        for w in (self.include_ext, self.replace_all, self.search_case):
            w.toggled.connect(self._schedule)
        self.mode_group.idToggled.connect(lambda _i, on: on and self._schedule())
        for w in (self.counter_start, self.counter_step, self.counter_digits):
            w.valueChanged.connect(self._schedule)
        self.btn_rename.clicked.connect(self.rename_clicked)
        self.btn_cancel.clicked.connect(self.cancel_clicked)
        self.btn_save.clicked.connect(self.save_profile_clicked)
        self.btn_delete.clicked.connect(self.delete_profile_clicked)
        self.profile_box.activated.connect(self._profile_chosen)
        self.refresh_profiles()

    # --- Aufbau-Hilfen ----------------------------------------------------------------
    @staticmethod
    def _with_button(edit: QLineEdit, button: QToolButton) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        h.addWidget(edit, 1)
        h.addWidget(button)
        return w

    def _placeholder_button(self, edit: QLineEdit) -> QToolButton:
        btn = QToolButton(self)
        btn.setText("[…]")
        btn.setToolTip(t("rename.placeholders"))
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(btn)
        for token, key in (("[N]", "rename.ph_name"), ("[E]", "rename.ph_ext"), ("[N1-5]", "rename.ph_part"),
                           ("[N3-]", "rename.ph_from"), ("[C]", "rename.ph_counter"), ("[D]", "rename.ph_date")):
            menu.addAction(f"{token}   {t(key)}").triggered.connect(
                lambda _c=False, tok=token, e=edit: (e.insert(tok), e.setFocus()))
        btn.setMenu(menu)
        return btn

    def _schedule(self, *_args) -> None:
        if not self._loading:
            self._timer.start()

    # --- Einstellungen ------------------------------------------------------------------
    def options(self) -> mr.RenameOptions:
        mode = (mr.SEARCH_TEXT, mr.SEARCH_WILDCARD, mr.SEARCH_REGEX)[max(self.mode_group.checkedId(), 0)]
        return mr.RenameOptions(
            pattern=self.pattern.text(), ext_pattern=self.ext_pattern.text(),
            search=self.search.text(), replace=self.replace.text(), search_mode=mode,
            replace_all=self.replace_all.isChecked(), search_case=self.search_case.isChecked(),
            case_mode=self.case_box.currentData(), include_ext=self.include_ext.isChecked(),
            date_source=self.date_source.currentData(), date_format=self.date_format.currentText(),
            counter_start=self.counter_start.value(), counter_step=self.counter_step.value(),
            counter_digits=self.counter_digits.value(),
        )

    def set_options(self, opts: mr.RenameOptions) -> None:
        self._loading = True
        try:
            self.pattern.setText(opts.pattern)
            self.ext_pattern.setText(opts.ext_pattern)
            self.search.setText(opts.search)
            self.replace.setText(opts.replace)
            {mr.SEARCH_TEXT: self.mode_text, mr.SEARCH_WILDCARD: self.mode_wild,
             mr.SEARCH_REGEX: self.mode_regex}[opts.search_mode].setChecked(True)
            self.replace_all.setChecked(opts.replace_all)
            self.search_case.setChecked(opts.search_case)
            self.case_box.setCurrentIndex(max(self.case_box.findData(opts.case_mode), 0))
            self.include_ext.setChecked(opts.include_ext)
            self.date_source.setCurrentIndex(max(self.date_source.findData(opts.date_source), 0))
            self.date_format.setEditText(opts.date_format)
            self.counter_start.setValue(opts.counter_start)
            self.counter_step.setValue(opts.counter_step)
            self.counter_digits.setValue(opts.counter_digits)
        finally:
            self._loading = False
        self.changed.emit()

    def refresh_profiles(self, select: str | None = None) -> None:
        current = select if select is not None else self.profile_box.currentText()
        self.profile_box.clear()
        self.profile_box.addItem(t("rename.profile_none"), None)
        for name in profile_names():
            self.profile_box.addItem(name, name)
        idx = self.profile_box.findData(current) if current else 0
        self.profile_box.setCurrentIndex(max(idx, 0))
        self.btn_delete.setEnabled(self.profile_box.currentData() is not None)

    def current_profile(self) -> str | None:
        return self.profile_box.currentData()

    def _profile_chosen(self, index: int) -> None:
        name = self.profile_box.itemData(index)
        self.btn_delete.setEnabled(name is not None)
        if name:
            self.set_options(load_profile(name))

    def show_state(self, error: str | None, changes: int, conflicts: int, total: int) -> None:
        self.search_error.setText(t("rename.invalid_regex", reason=error) if error else "")
        if error:
            text = t("rename.summary_error")
        elif conflicts:
            text = t("rename.summary_conflicts", n=conflicts, total=total)
        else:
            text = t("rename.summary", n=changes, total=total)
        self.summary.setText(text)
        self.btn_rename.setEnabled(not error and not conflicts and changes > 0)
