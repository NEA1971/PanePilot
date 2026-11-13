"""Fenster des Meta-Wizards: Feld-Editor (F-970 ff.), Konverter (F-990 ff.), Vorlagenliste (F-998),
Eingabe langer Texte (F-980)."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
)

from . import convert as cv
from . import metaprofile as mp
from . import tags as tg
from .dialogs import free_window, show_error
from .i18n import t


# --- Langer Text (F-980) ----------------------------------------------------------------------------
class TextDialog(QDialog):
    def __init__(self, parent, title: str, text: str) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(title)
        self.resize(520, 420)
        self.edit = QPlainTextEdit(self)
        self.edit.setPlainText(text)
        box = QDialogButtonBox(self)
        box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(False)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.edit, 1)
        lay.addWidget(box)

    def text(self) -> str:
        return self.edit.toPlainText()


# --- Feld-Editor (F-970 ff.) ------------------------------------------------------------------------
@dataclass
class FieldRow:
    key: str  # Feld (mp.fields()), "x:<Name>" oder "d:<Name>"
    label: str
    count: int
    kind: str  # "standard", "known", "extra", "fixed", "data", "new"
    deleted: bool = False
    new_name: str = ""

    @property
    def renamable(self) -> bool:
        return self.kind in ("extra", "new")

    @property
    def deletable(self) -> bool:
        return self.kind != "standard"


def collect_fields(items, custom: list[str]) -> list[FieldRow]:
    """Alle Felder der Titel mit Anzahl der Dateien (F-972)."""
    from .metawizard import column_title

    total: dict[str, FieldRow] = {}
    for it in items:
        rec = it.record
        seen: set[str] = set()
        for key in rec.fields:
            if key.startswith(tg.EXTRA):
                label = rec.labels.get(key, tg.label_of(key))
                gid = "x:" + label.casefold()
                kind = "fixed" if key in rec.fixed else "extra"
                row = total.setdefault(gid, FieldRow(tg.EXTRA + label, label, 0, kind))
            else:
                gid = key
                kind = "standard" if key in mp.standard_fields() else "known"
                row = total.setdefault(gid, FieldRow(key, column_title(key), 0, kind))
            if gid not in seen:
                row.count += 1
                seen.add(gid)
        for key, label in rec.data.items():
            gid = "d:" + label.casefold()
            row = total.setdefault(gid, FieldRow(key, label, 0, "data"))
            if gid not in seen:
                row.count += 1
                seen.add(gid)
    for name in custom:
        total.setdefault("x:" + name.casefold(), FieldRow(tg.EXTRA + name, name, 0, "extra"))
    order = {"standard": 0, "known": 1, "extra": 2, "fixed": 3, "data": 4}

    def sort_key(r: FieldRow):
        idx = mp.fields().index(r.key) if r.key in mp.fields() else 0
        return (order.get(r.kind, 5), idx, r.label.casefold())

    return sorted(total.values(), key=sort_key)


class FieldEditorDialog(QDialog):
    """Nur der Aufbau der Tags: Felder löschen, umbenennen, neu anlegen – keine Inhalte (F-971)."""

    def __init__(self, parent, rows: list[FieldRow], file_count: int) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("fields.title"))
        self.resize(620, 520)
        self.rows = rows
        self.file_count = file_count
        intro = QLabel(t("fields.intro", n=file_count), self)
        intro.setWordWrap(True)
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels([t("fields.col_name"), t("fields.col_count"), ""])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.itemChanged.connect(self._item_changed)
        self.btn_new = QPushButton(t("fields.new"), self)
        self.btn_new.clicked.connect(self.add_new)
        box = QDialogButtonBox(self)
        self.btn_ok = box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self._accept)
        box.rejected.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.btn_new)
        bottom.addStretch(1)
        bottom.addWidget(box)
        hint = QLabel(t("fields.hint"), self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addWidget(self.table, 1)
        lay.addWidget(hint)
        lay.addLayout(bottom)
        self._filling = False
        self._fill()

    def _fill(self) -> None:
        self._filling = True
        for r in range(self.table.rowCount()):  # alte Knöpfe sofort entfernen
            old = self.table.cellWidget(r, 2)
            if old is not None:
                self.table.removeCellWidget(r, 2)
                old.hide()
                old.deleteLater()
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            name = QTableWidgetItem(row.new_name or row.label)
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            if row.renamable and not row.deleted:
                flags |= Qt.ItemFlag.ItemIsEditable
            name.setFlags(flags)
            font = name.font()
            font.setStrikeOut(row.deleted)
            font.setItalic(row.kind == "data")
            name.setFont(font)
            if row.deleted or row.kind == "standard":
                name.setForeground(Qt.GlobalColor.gray)
            tip = {"standard": "fields.tip_standard", "known": "fields.tip_known", "fixed": "fields.tip_fixed",
                   "data": "fields.tip_data"}.get(row.kind)
            if tip:
                name.setToolTip(t(tip))
            label = (t("fields.count", n=row.count, total=self.file_count) if row.kind != "new"
                     else t("fields.count_new"))
            if row.kind == "data":
                label += " " + t("fields.data_suffix")
            count = QTableWidgetItem(label)
            count.setFlags(Qt.ItemFlag.ItemIsEnabled)
            count.setFont(font)
            if row.deleted:
                count.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, count)
            btn = QToolButton()
            btn.setText(t("fields.undo_delete") if row.deleted else "x")
            btn.setEnabled(row.deletable)
            btn.setToolTip(t("fields.delete_tip") if not row.deleted else "")
            btn.clicked.connect(lambda _c=False, i=r: self.toggle_delete(i))
            self.table.setCellWidget(r, 2, btn)
        self._filling = False

    def toggle_delete(self, index: int) -> None:
        row = self.rows[index]
        if not row.deletable:
            return
        if row.kind == "new" and not row.deleted:
            del self.rows[index]  # neues, noch leeres Feld einfach wieder weg
        else:
            row.deleted = not row.deleted
        self._fill()

    def _menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction(t("fields.new")).triggered.connect(self.add_new)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def add_new(self) -> None:
        self.rows.append(FieldRow("", "", 0, "new"))
        self._fill()
        r = len(self.rows) - 1
        self.table.setCurrentCell(r, 0)
        self.table.editItem(self.table.item(r, 0))

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != 0:
            return
        row = self.rows[item.row()]
        text = item.text().strip()
        if row.kind == "new":
            row.label = text
        else:
            row.new_name = "" if text == row.label else text

    def _names_taken(self) -> set[str]:
        from .metawizard import column_title

        taken = {k.casefold() for k in mp.fields()} | {column_title(k).casefold() for k in mp.fields()}
        return taken

    def _accept(self) -> None:
        """Prüfen (A-2, A-3): gültige, eindeutige Namen; bekannte Feldnamen sind gesperrt."""
        taken = self._names_taken()
        final: dict[str, int] = {}
        for i, row in enumerate(self.rows):
            if row.deleted:
                continue
            name = row.new_name or row.label
            if row.kind == "new" and not name:
                continue
            if row.kind in ("new",) or row.new_name:
                if not tg.valid_field_name(name):
                    show_error(self, t("fields.title"), t("fields.err_name", name=name))
                    return
                if name.casefold() in taken:
                    show_error(self, t("fields.title"), t("fields.err_known", name=name))
                    return
            key = name.casefold()
            if key in final:
                show_error(self, t("fields.title"), t("fields.err_exists", name=name))
                return
            final[key] = i
        self.accept()

    # Ergebnis
    def deletions(self) -> list[FieldRow]:
        return [r for r in self.rows if r.deleted and r.kind != "new"]

    def renames(self) -> list[tuple[FieldRow, str]]:
        return [(r, r.new_name) for r in self.rows if not r.deleted and r.new_name and r.kind != "new"]

    def new_fields(self) -> list[str]:
        return [r.label for r in self.rows if r.kind == "new" and not r.deleted and r.label]


def placeholder_menu(parent, kind: str, extra_labels: list[str], edit: QLineEdit, button, manage=None) -> None:
    """▸-Menü: Platzhalter, weitere Felder, Informationsfelder, Funktionen, „Liste verwalten …“."""
    menu = QMenu(parent)

    def add(text: str, target=menu, label: str | None = None) -> None:
        target.addAction(label or text).triggered.connect(lambda _c=False, s=text: edit.insert(s))

    for key in mp.fields():
        add(f"%{key}%", label=key)
    if kind == cv.FILE_TO_TAG:
        add(f"%{cv.DUMMY}%", label=cv.DUMMY)
    if extra_labels:
        more = menu.addMenu(t("meta.more_fields"))
        for label in extra_labels:
            add(f"%{label}%", more, label)
    if kind != cv.FILE_TO_TAG:
        info = menu.addMenu(t("conv.info_fields"))
        add("%_filename%", info, "_filename")
        add("%_folder%", info, "_folder")
        if mp.is_photo_mode():
            for name in ("camera", "width", "height", "format"):
                add(f"%{name}%", info, name)
        funcs = menu.addMenu(t("conv.functions"))
        for name, sample in cv.FUNCTIONS.items():
            if not mp.is_photo_mode():
                sample = sample.replace("%datetaken%", "%year%").replace("_hhmmss", "") if name == "date" else sample
            else:
                sample = sample.replace("%track%", "%rating%").replace("%albumartist%,%albumartist%,%artist%",
                                                                       "%title%,%title%,%_filename%")
            add(sample, funcs, f"${name}()")
    if manage is not None:
        menu.addSeparator()
        menu.addAction(t("conv.manage")).triggered.connect(manage)
    menu.exec(button.mapToGlobal(button.rect().bottomLeft()))


# --- Vorlagen („Liste verwalten“, F-998) ---------------------------------------------------------
class PresetDialog(QDialog):
    def __init__(self, parent, title: str, presets: list[dict], insert_menu) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("conv.manage_title"))
        self.resize(640, 460)
        self.presets = [dict(p) for p in presets]
        self.insert_menu = insert_menu
        head = QLabel(title, self)
        f = head.font()
        f.setBold(True)
        head.setFont(f)
        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels([t("conv.col_name"), t("conv.col_format")])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.currentCellChanged.connect(lambda *_: self._show_current())
        self.name = QLineEdit(self)
        self.format = QLineEdit(self)
        self.desc = QLineEdit(self)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.format.setFont(mono)
        ins = QToolButton(self)
        ins.setText("▸")
        ins.clicked.connect(lambda: self.insert_menu(self.format, ins))
        frow = QHBoxLayout()
        frow.addWidget(self.format, 1)
        frow.addWidget(ins)
        for w in (self.name, self.format, self.desc):
            w.textEdited.connect(self._store)
        form = QFormLayout()
        form.addRow(t("conv.col_name") + ":", self.name)
        form.addRow(t("conv.col_format") + ":", frow)
        form.addRow(t("conv.desc") + ":", self.desc)
        side = QVBoxLayout()
        self.btn_new = QPushButton(t("conv.new"), self)
        self.btn_dup = QPushButton(t("conv.duplicate"), self)
        self.btn_del = QPushButton(t("conv.delete"), self)
        self.btn_up = QPushButton(t("meta.field_up"), self)
        self.btn_down = QPushButton(t("meta.field_down"), self)
        for b, fn in ((self.btn_new, self._new), (self.btn_dup, self._dup), (self.btn_del, self._delete),
                      (self.btn_up, lambda: self._move(-1)), (self.btn_down, lambda: self._move(1))):
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addStretch(1)
        top = QHBoxLayout()
        top.addWidget(self.table, 1)
        top.addLayout(side)
        box = QDialogButtonBox(self)
        box.addButton(t("conv.apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(head)
        lay.addLayout(top, 1)
        lay.addLayout(form)
        lay.addWidget(box)
        self._fill(0)

    def _fill(self, select: int) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.presets))
        for r, p in enumerate(self.presets):
            self.table.setItem(r, 0, QTableWidgetItem(p.get("name", "")))
            self.table.setItem(r, 1, QTableWidgetItem(p.get("format", "")))
        self.table.blockSignals(False)
        if self.presets:
            self.table.setCurrentCell(max(0, min(select, len(self.presets) - 1)), 0)
        self._show_current()

    def _current(self) -> int:
        return self.table.currentRow() if 0 <= self.table.currentRow() < len(self.presets) else -1

    def _show_current(self) -> None:
        i = self._current()
        p = self.presets[i] if i >= 0 else {}
        for w, k in ((self.name, "name"), (self.format, "format"), (self.desc, "desc")):
            w.setText(p.get(k, ""))
            w.setEnabled(i >= 0)
        self.btn_dup.setEnabled(i >= 0)
        self.btn_del.setEnabled(i >= 0)
        self.btn_up.setEnabled(i > 0)
        self.btn_down.setEnabled(0 <= i < len(self.presets) - 1)

    def _store(self, *_args) -> None:
        i = self._current()
        if i < 0:
            return
        self.presets[i] = {"name": self.name.text(), "format": self.format.text(), "desc": self.desc.text()}
        self.table.item(i, 0).setText(self.name.text())
        self.table.item(i, 1).setText(self.format.text())

    def _new(self) -> None:
        self.presets.append({"name": "", "format": "", "desc": ""})
        self._fill(len(self.presets) - 1)
        self.format.setFocus()

    def _dup(self) -> None:
        i = self._current()
        if i >= 0:
            self.presets.insert(i + 1, dict(self.presets[i]))
            self._fill(i + 1)

    def _delete(self) -> None:
        i = self._current()
        if i >= 0:
            del self.presets[i]
            self._fill(i)

    def _move(self, delta: int) -> None:
        i = self._current()
        j = i + delta
        if i >= 0 and 0 <= j < len(self.presets):
            self.presets[i], self.presets[j] = self.presets[j], self.presets[i]
            self._fill(j)

    def result_presets(self) -> list[dict]:
        return [p for p in self.presets if p.get("format", "").strip()]


# --- Konverter (F-990 ff.) --------------------------------------------------------------------------------
class ConverterDialog(QDialog):
    """Formatstring mit Platzhalter-Menü, Vorschau für den ersten markierten Titel (F-991)."""

    def __init__(self, parent, kind: str, presets: list[dict], last: str, extra_labels: list[str],
                 preview, fields: list[tuple[str, str]] | None = None, last_field: str = "") -> None:
        super().__init__(parent)
        free_window(self)
        self.kind = kind
        self.presets = presets
        self.extra_labels = extra_labels
        self.preview_fn = preview
        self.setWindowTitle(t(f"conv.{kind}"))
        self.setMinimumWidth(560)
        lay = QVBoxLayout(self)
        self.field_box = None
        if kind == cv.TAG_TO_TAG:
            lay.addWidget(QLabel(t("conv.field"), self))
            self.field_box = QComboBox(self)
            self.field_box.setEditable(True)
            for key, label in fields or []:
                self.field_box.addItem(label, key)
            i = self.field_box.findData(last_field)
            self.field_box.setCurrentIndex(max(i, 0))
            self.field_box.currentTextChanged.connect(self._update)
            lay.addWidget(self.field_box)
        lay.addWidget(QLabel(t("conv.format"), self))
        self.combo = QComboBox(self)
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.combo.setFont(mono)
        self._fill_presets(last)
        ins = QToolButton(self)
        ins.setText("▸")
        ins.clicked.connect(lambda: self.insert_menu(self.combo.lineEdit(), ins, manage=True))
        row = QHBoxLayout()
        row.addWidget(self.combo, 1)
        row.addWidget(ins)
        lay.addLayout(row)
        self.preview = QLabel(self)
        self.preview.setTextFormat(Qt.TextFormat.RichText)
        self.preview_is_error = False
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.preview.setMinimumHeight(60)
        lay.addWidget(self.preview)
        box = QDialogButtonBox(self)
        self.btn_ok = box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.combo.editTextChanged.connect(self._update)
        self._update()

    def _fill_presets(self, current: str) -> None:
        self.combo.blockSignals(True)
        self.combo.clear()
        for p in self.presets:
            text = p.get("format", "")
            label = f"{p['name']}: {text}" if p.get("name") else text
            self.combo.addItem(label, text)
        self.combo.setEditText(current or (self.presets[0]["format"] if self.presets else ""))
        self.combo.blockSignals(False)

    def format_string(self) -> str:
        text = self.combo.currentText()
        i = self.combo.findText(text)
        if i >= 0 and isinstance(self.combo.itemData(i), str):
            return self.combo.itemData(i)
        return text

    def field(self) -> str:
        if self.field_box is None:
            return ""
        i = self.field_box.findText(self.field_box.currentText())
        if i >= 0:
            return self.field_box.itemData(i)
        name = self.field_box.currentText().strip()
        return tg.EXTRA + name if name else ""

    def _update(self, *_args) -> None:
        fmt = self.format_string()
        ok, text, warn = self.preview_fn(fmt, self.field())
        # Farbe direkt im Text statt per Stylesheet: Rot nur bei Fehlern, sonst normale Schrift
        html = escape(text).replace("\n", "<br>")
        self.preview.setText(f'<span style="color:#D32F2F">{html}</span>' if warn or not ok else html)
        self.preview_is_error = warn or not ok
        self.btn_ok.setEnabled(ok and bool(fmt.strip()) and (self.field_box is None or bool(self.field())))

    # Platzhalter-Menü (wie bei MP3TAG)
    def insert_menu(self, edit: QLineEdit, button, manage: bool = False) -> None:
        placeholder_menu(self, self.kind, self.extra_labels, edit, button, self._manage if manage else None)

    def _manage(self) -> None:
        dlg = PresetDialog(self, t(f"conv.{self.kind}"), self.presets, self.insert_menu)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            current = self.format_string()
            self.presets = dlg.result_presets()
            self._fill_presets(current)
            self._update()
