"""Dialoge: Rückfragen, Konflikte, Fortschritt."""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .fileops import ConflictDecision
from .i18n import t
from .util import format_size


def free_window(dlg: QDialog) -> None:
    """Dialog als eigenständiges Fenster (v0.8.1).

    GNOME hängt modale Dialoge fest an das Hauptfenster: Verschieben bewegt dann die ganze
    Anwendung. Als normales Fenster bleibt der Dialog frei verschiebbar; modal (Hauptfenster
    gesperrt) bleibt er trotzdem, weil er mit exec() geöffnet wird.
    """
    dlg.setWindowFlags(
        Qt.WindowType.Window
        | Qt.WindowType.CustomizeWindowHint
        | Qt.WindowType.WindowTitleHint
        | Qt.WindowType.WindowCloseButtonHint
        | Qt.WindowType.WindowMaximizeButtonHint
    )
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)


def _msgbox(parent, icon, title, text, buttons):
    box = QMessageBox(icon, title, text, QMessageBox.StandardButton.NoButton, parent)
    result = {}
    for key, role, is_default in buttons:
        btn = box.addButton(t(key), role)
        result[btn] = key
        if is_default:
            box.setDefaultButton(btn)
    box.exec()
    return result.get(box.clickedButton())


def confirm(parent, title: str, text: str, yes_key: str = "button.yes", default_yes: bool = True,
            warning: bool = False) -> bool:
    icon = QMessageBox.Icon.Warning if warning else QMessageBox.Icon.Question
    clicked = _msgbox(parent, icon, title, text, [
        (yes_key, QMessageBox.ButtonRole.AcceptRole, default_yes),
        ("button.cancel", QMessageBox.ButtonRole.RejectRole, not default_yes),
    ])
    return clicked == yes_key


def show_error(parent, title: str, text: str) -> None:
    _msgbox(parent, QMessageBox.Icon.Warning, title, text, [("button.ok", QMessageBox.ButtonRole.AcceptRole, True)])


def show_info(parent, title: str, text: str) -> None:
    _msgbox(parent, QMessageBox.Icon.Information, title, text, [("button.ok", QMessageBox.ButtonRole.AcceptRole, True)])


def ask_text(parent, title: str, label: str, text: str = "") -> str | None:
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setTextValue(text)
    dlg.setOkButtonText(t("button.ok"))
    dlg.setCancelButtonText(t("button.cancel"))
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    value = dlg.textValue().strip()
    return value or None


def _buttons(dialog: QDialog, ok_key: str = "button.ok") -> QDialogButtonBox:
    box = QDialogButtonBox(dialog)
    ok = box.addButton(t(ok_key), QDialogButtonBox.ButtonRole.AcceptRole)
    box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
    ok.setDefault(True)
    box.accepted.connect(dialog.accept)
    box.rejected.connect(dialog.reject)
    return box


class CopyMoveDialog(QDialog):
    """Kurze Rückfrage vor F5/F6 mit (änderbarem) Zielpfad. Enter bestätigt."""

    def __init__(self, parent, move: bool, names: list[str], target: str) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("title.move" if move else "title.copy"))
        if len(names) == 1:
            what = t("dialog.one_item", name=names[0])
        else:
            what = t("dialog.n_items", n=len(names))
        label = QLabel(t("dialog.move_to" if move else "dialog.copy_to", what=what), self)
        label.setWordWrap(True)
        self.target_edit = QLineEdit(target, self)
        self.target_edit.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self.target_edit)
        layout.addWidget(_buttons(self, "button.move" if move else "button.copy"))

    def target(self) -> str:
        return os.path.abspath(os.path.expanduser(self.target_edit.text().strip()))


def _describe(path: str) -> str:
    try:
        st = os.stat(path)
    except OSError:
        return ""
    when = datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M")
    if os.path.isdir(path):
        return t("conflict.folder_info", date=when)
    return t("conflict.file_info", size=format_size(st.st_size), date=when)


class ConflictDialog(QDialog):
    def __init__(self, parent, src: str, dst: str, same_file: bool, suggestion: str) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("title.conflict"))
        self.decision = ConflictDecision("cancel")
        name = os.path.basename(dst)
        head = QLabel(t("conflict.exists", name=name, folder=os.path.dirname(dst)), self)
        head.setWordWrap(True)
        grid = QGridLayout()
        grid.addWidget(QLabel(t("conflict.existing"), self), 0, 0)
        grid.addWidget(QLabel(_describe(dst), self), 0, 1)
        grid.addWidget(QLabel(t("conflict.new"), self), 1, 0)
        grid.addWidget(QLabel(_describe(src), self), 1, 1)
        rename_row = QHBoxLayout()
        rename_row.addWidget(QLabel(t("conflict.new_name"), self))
        self.name_edit = QLineEdit(suggestion, self)
        rename_row.addWidget(self.name_edit, 1)
        self.apply_all = QCheckBox(t("conflict.apply_all"), self)

        self.btn_overwrite = QPushButton(t("button.overwrite"), self)
        self.btn_skip = QPushButton(t("button.skip"), self)
        self.btn_rename = QPushButton(t("button.rename"), self)
        self.btn_cancel = QPushButton(t("button.cancel"), self)
        if same_file:
            self.btn_overwrite.setEnabled(False)
            self.btn_overwrite.setToolTip(t("conflict.same_file"))
        self.btn_overwrite.clicked.connect(lambda: self._finish("overwrite"))
        self.btn_skip.clicked.connect(lambda: self._finish("skip"))
        self.btn_rename.clicked.connect(lambda: self._finish("rename"))
        self.btn_cancel.clicked.connect(lambda: self._finish("cancel"))
        (self.btn_rename if same_file else self.btn_skip).setDefault(True)
        buttons = QHBoxLayout()
        for b in (self.btn_overwrite, self.btn_skip, self.btn_rename):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(head)
        layout.addLayout(grid)
        layout.addLayout(rename_row)
        layout.addWidget(self.apply_all)
        layout.addLayout(buttons)

    def _finish(self, action: str) -> None:
        self.decision = ConflictDecision(action, self.name_edit.text().strip(), self.apply_all.isChecked())
        self.accept()

    def reject(self) -> None:
        self.decision = ConflictDecision("cancel")
        super().reject()


class ProgressDialog(QDialog):
    cancel_requested = Signal()

    def __init__(self, parent, title: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.label = QLabel("", self)
        self.label.setMinimumWidth(420)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(True)
        self.bar.setFormat("%p %")
        cancel = QPushButton(t("button.cancel"), self)
        cancel.clicked.connect(self._cancel)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        layout.addLayout(row)

    def update_progress(self, permille: int, name: str) -> None:
        self.bar.setValue(permille)
        self.label.setText(name)

    def _cancel(self) -> None:
        self.label.setText(t("progress.cancelling"))
        self.cancel_requested.emit()

    def closeEvent(self, event) -> None:
        self._cancel()
        event.ignore()

    def reject(self) -> None:
        self._cancel()


class ErrorListDialog(QDialog):
    def __init__(self, parent, title: str, intro: str, errors: list[tuple[str, str]]) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(intro, self))
        shown = errors[:20]
        text = "\n".join(f"• {p}: {r}" for p, r in shown)
        if len(errors) > len(shown):
            text += "\n" + t("errors.more", n=len(errors) - len(shown))
        body = QLabel(text, self)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setWordWrap(True)
        layout.addWidget(body)
        box = QDialogButtonBox(self)
        box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.accepted.connect(self.accept)
        layout.addWidget(box)


class AboutDialog(QDialog):
    def __init__(self, parent, version: str, config_path: str, extra: str = "") -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("title.about"))
        text = QLabel(t("about.text", version=version, config=config_path) + (f"<p>{extra}</p>" if extra else ""), self)
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout = QVBoxLayout(self)
        layout.addWidget(text)
        box = QDialogButtonBox(self)
        box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.accepted.connect(self.accept)
        layout.addWidget(box)


__all__ = [
    "AboutDialog",
    "ConflictDialog",
    "CopyMoveDialog",
    "ErrorListDialog",
    "ProgressDialog",
    "ask_text",
    "confirm",
    "show_error",
    "show_info",
]


class FavoriteEditDialog(QDialog):
    """„Bearbeiten …“ für einen Favoriten: Name, Link, Schriftstil, Farbe (F-220)."""

    def __init__(self, parent, node, colors) -> None:
        from PySide6.QtGui import QColor, QIcon, QPixmap
        from PySide6.QtWidgets import QComboBox, QFormLayout

        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("title.fav_edit"))
        self.name_edit = QLineEdit(node.name, self)
        self.path_edit = QLineEdit(node.path if not node.is_group else "", self)
        self.path_edit.setMinimumWidth(420)
        self.path_edit.setEnabled(not node.is_group)
        if node.is_group:
            self.path_edit.setPlaceholderText(t("fav_edit.group_no_link"))
        self.checks = {}
        style_row = QHBoxLayout()
        for flag in ("bold", "italic", "underline", "strike"):
            cb = QCheckBox(t(f"fav_edit.{flag}"), self)
            cb.setChecked(bool(node.style.get(flag)))
            font = cb.font()
            if flag == "bold":
                font.setBold(True)
            elif flag == "italic":
                font.setItalic(True)
            elif flag == "underline":
                font.setUnderline(True)
            else:
                font.setStrikeOut(True)
            cb.setFont(font)
            self.checks[flag] = cb
            style_row.addWidget(cb)
        style_row.addStretch(1)
        self.color_combo = QComboBox(self)
        self.color_combo.addItem(t("color.default"), None)
        for key, hexval in colors:
            pm = QPixmap(14, 14)
            pm.fill(QColor(hexval))
            self.color_combo.addItem(QIcon(pm), t(f"color.{key}"), key)
        current = node.style.get("color")
        idx = self.color_combo.findData(current) if current else 0
        self.color_combo.setCurrentIndex(max(idx, 0))

        form = QFormLayout()
        form.addRow(t("fav_edit.name"), self.name_edit)
        form.addRow(t("fav_edit.link"), self.path_edit)
        form.addRow(t("fav_edit.font"), style_row)
        form.addRow(t("fav_edit.color"), self.color_combo)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(_buttons(self))

    def values(self) -> tuple[str, str, dict]:
        style = {flag: True for flag, cb in self.checks.items() if cb.isChecked()}
        color = self.color_combo.currentData()
        if color:
            style["color"] = color
        return self.name_edit.text().strip(), self.path_edit.text().strip(), style


class OpenWithDialog(QDialog):
    """„Andere Anwendung …“: alle Programme mit Suchfeld (F-301/F-302)."""

    def __init__(self, parent, apps, file_label: str) -> None:
        from PySide6.QtWidgets import QListWidget, QListWidgetItem

        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("title.open_with"))
        self.resize(460, 520)
        self._apps = apps
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(t("open_with.choose", name=file_label), self))
        self.search = QLineEdit(self)
        self.search.setPlaceholderText(t("open_with.search"))
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.list = QListWidget(self)
        for app in apps:
            item = QListWidgetItem(app.qicon(), app.name)
            item.setData(Qt.ItemDataRole.UserRole, app.id)
            item.setToolTip(app.id)
            self.list.addItem(item)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        layout.addWidget(self.list, 1)
        self.make_default = QCheckBox(t("open_with.make_default"), self)
        layout.addWidget(self.make_default)
        layout.addWidget(_buttons(self, "button.open"))
        if self.list.count():
            self.list.setCurrentRow(0)
        self.search.setFocus()

    def _filter(self, text: str) -> None:
        needle = text.casefold().strip()
        first = None
        for row in range(self.list.count()):
            item = self.list.item(row)
            hidden = bool(needle) and needle not in item.text().casefold()
            item.setHidden(hidden)
            if not hidden and first is None:
                first = item
        if first is not None:
            self.list.setCurrentItem(first)

    def selected_app(self):
        item = self.list.currentItem()
        if item is None or item.isHidden():
            return None
        app_id = item.data(Qt.ItemDataRole.UserRole)
        return next((a for a in self._apps if a.id == app_id), None)


class CompressDialog(QDialog):
    """„Komprimieren …“ (F-531): Archivname und Archivtyp."""

    def __init__(self, parent, what: str, stem: str, target_dir: str) -> None:
        from PySide6.QtGui import QStandardItemModel
        from PySide6.QtWidgets import QComboBox, QFormLayout

        from . import archives

        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("title.compress"))
        self._target_dir = target_dir
        info = QLabel(t("dialog.compress_what", what=what, folder=target_dir), self)
        info.setWordWrap(True)
        self.name_edit = QLineEdit(stem, self)
        self.name_edit.setMinimumWidth(380)
        self.type_box = QComboBox(self)
        for fmt in archives.CREATE_FORMATS:
            self.type_box.addItem(archives.FORMAT_EXT[fmt], fmt)
        model = self.type_box.model()
        if isinstance(model, QStandardItemModel):
            for row, fmt in enumerate(archives.CREATE_FORMATS):
                if not archives.can_create(fmt):
                    item = model.item(row)
                    item.setEnabled(False)
                    item.setToolTip(archives.missing_hint(fmt, True))
        form = QFormLayout()
        form.addRow(t("dialog.archive_name"), self.name_edit)
        form.addRow(t("dialog.archive_type"), self.type_box)
        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addLayout(form)
        layout.addWidget(_buttons(self, "button.compress"))
        self.name_edit.selectAll()

    def archive_format(self) -> str:
        return self.type_box.currentData()

    def stem(self) -> str:
        from . import archives

        name = self.name_edit.text().strip()
        # Hat jemand die Endung mit eingetippt, nicht doppelt anhängen
        ext = archives.FORMAT_EXT[self.archive_format()]
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
        return name


class ExtractToDialog(QDialog):
    """„Entpacken nach …“ (F-540): Pfadfeld mit „Durchsuchen …“."""

    def __init__(self, parent, what: str, target: str) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("title.extract"))
        label = QLabel(t("dialog.extract_to", what=what), self)
        label.setWordWrap(True)
        self.target_edit = QLineEdit(target, self)
        self.target_edit.setMinimumWidth(420)
        browse = QPushButton(t("button.browse"), self)
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.target_edit, 1)
        row.addWidget(browse)
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addLayout(row)
        layout.addWidget(_buttons(self, "button.extract"))

    def _browse(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        start = self.target_edit.text().strip() or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, t("title.extract"), start)
        if path:
            self.target_edit.setText(path)

    def target(self) -> str:
        return os.path.abspath(os.path.expanduser(self.target_edit.text().strip()))


class FilterDialog(QDialog):
    """„Filter definieren“ (F-601, F-602)."""

    def __init__(self, parent, current, recent: list) -> None:
        from PySide6.QtWidgets import QCheckBox, QComboBox, QRadioButton

        from .filters import FilterSpec

        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("title.filter"))
        self._recent = recent
        self.pattern = QComboBox(self)
        self.pattern.setEditable(True)
        self.pattern.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.pattern.setMinimumWidth(380)
        for spec in recent:
            self.pattern.addItem(spec.label() + ("   (RegEx)" if spec.regex else ""), spec)
        self.wildcard = QRadioButton(t("filter.wildcard"), self)
        self.regex = QRadioButton(t("filter.regex"), self)
        self.case = QCheckBox(t("filter.case"), self)
        self.invert = QCheckBox(t("filter.invert"), self)
        self.dirs = QCheckBox(t("filter.dirs"), self)
        self.hide_dirs = QCheckBox(t("filter.hide_dirs"), self)
        self.hint = QLabel(self)
        self.hint.setWordWrap(True)
        self.error = QLabel(self)
        self.error.setStyleSheet("color: #D32F2F;")
        self.error.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(t("filter.pattern"), self))
        layout.addWidget(self.pattern)
        row = QHBoxLayout()
        row.addWidget(self.wildcard)
        row.addWidget(self.regex)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(self.hint)
        for w in (self.case, self.invert, self.dirs, self.hide_dirs):
            layout.addWidget(w)
        layout.addWidget(self.error)
        self.buttons = _buttons(self, "button.filter_apply")
        layout.addWidget(self.buttons)

        self._fill(current if current is not None else FilterSpec(""))
        self.pattern.activated.connect(self._recent_chosen)
        self.pattern.editTextChanged.connect(self._validate)
        self.wildcard.toggled.connect(self._validate)
        self.hide_dirs.toggled.connect(self._validate)
        self._validate()
        self.pattern.lineEdit().selectAll()
        self.pattern.setFocus()

    def _fill(self, spec) -> None:
        self.pattern.setEditText(spec.pattern)
        (self.regex if spec.regex else self.wildcard).setChecked(True)
        self.case.setChecked(spec.case_sensitive)
        self.invert.setChecked(spec.invert)
        self.dirs.setChecked(spec.dirs)
        self.hide_dirs.setChecked(spec.hide_dirs)

    def _recent_chosen(self, index: int) -> None:
        spec = self.pattern.itemData(index)
        if spec is not None:
            self._fill(spec)

    def spec(self):
        from .filters import FilterSpec

        return FilterSpec(pattern=self.pattern.currentText().strip(), regex=self.regex.isChecked(),
                          case_sensitive=self.case.isChecked(), invert=self.invert.isChecked(),
                          dirs=self.dirs.isChecked(), hide_dirs=self.hide_dirs.isChecked())

    def _validate(self, *_args) -> None:
        self.hint.setText(t("filter.hint_regex") if self.regex.isChecked() else t("filter.hint_wildcard"))
        self.dirs.setEnabled(not self.hide_dirs.isChecked())
        err = self.spec().error()
        ok_button = next(b for b in self.buttons.buttons()
                         if self.buttons.buttonRole(b) == QDialogButtonBox.ButtonRole.AcceptRole)
        ok_button.setEnabled(err is None)
        if err is None or err == "empty":
            self.error.setText("")
        else:
            self.error.setText(t("filter.invalid_regex", reason=err))
