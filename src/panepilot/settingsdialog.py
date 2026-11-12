"""Fenster „Einstellungen“ (F-840 ff.) und Bearbeitungsfenster für Sprachen (F-865, F-866)."""

from __future__ import annotations

import os
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import colprofiles
from .dialogs import confirm, free_window, show_error
from .filemodel import COLUMN_COUNT, COLUMN_KEYS, COL_SIZE, MENU_ORDER
from .i18n import (
    BASE_LANGUAGE,
    SYSTEM,
    languages,
    read_language,
    save_user_language,
    t,
)
from .util import SIZE_UNITS, format_size

_PLACEHOLDER = re.compile(r"\{(\w*)\}")


def size_unit_label(unit: str) -> str:
    return t("settings.size_auto") if unit == "auto" else (t("settings.size_bytes") if unit == "B" else unit)


class SectionPage(QWidget):
    """Reiter im Stil der Firefox-Einstellungen (v0.9.10).

    Links die Bereiche des Reiters, rechts eine durchgehende Seite mit Rollbalken. Jeder Bereich
    steht in einem eigenen Rahmen. Ein Klick links springt zum Bereich, beim Rollen wird links der
    sichtbare Bereich hervorgehoben.
    """

    def __init__(self, parent) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QFrame, QScrollArea

        self.nav = QListWidget(self)
        self.nav.setMaximumWidth(190)
        self.nav.setMinimumWidth(130)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body = QWidget(self.scroll)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(4, 0, 8, 0)
        self.body_layout.setSpacing(14)
        self.body_layout.addStretch(1)
        self.scroll.setWidget(self.body)
        self.groups: list = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.addWidget(self.nav)
        layout.addWidget(self.scroll, 1)
        self.nav.currentRowChanged.connect(self.jump_to)
        self.scroll.verticalScrollBar().valueChanged.connect(self._follow_scroll)
        self._jumping = False

    def add_section(self, title: str, content: QWidget):
        from PySide6.QtWidgets import QGroupBox

        group = QGroupBox(title, self.body)
        font = group.font()
        font.setBold(True)
        group.setFont(font)
        content.setFont(self.font())  # Inhalt wieder in normaler Schrift
        inner = QVBoxLayout(group)
        inner.addWidget(content)
        self.body_layout.insertWidget(self.body_layout.count() - 1, group)
        self.groups.append(group)
        self.nav.addItem(title)
        if self.nav.count() == 1:
            self.nav.blockSignals(True)
            self.nav.setCurrentRow(0)
            self.nav.blockSignals(False)
        return group

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._pad_bottom()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._pad_bottom()

    def _pad_bottom(self) -> None:
        """Platz unter dem letzten Bereich, damit auch er ganz nach oben gerollt werden kann."""
        if len(self.groups) < 2:
            return
        free = self.scroll.viewport().height() - self.groups[-1].sizeHint().height() - 8
        self.body_layout.setContentsMargins(4, 0, 8, max(free, 0))

    def jump_to(self, row: int) -> None:
        if not 0 <= row < len(self.groups) or self._jumping:
            return
        self._jumping = True
        bar = self.scroll.verticalScrollBar()
        bar.setValue(min(self.groups[row].y() - 2, bar.maximum()))
        self._jumping = False

    def _follow_scroll(self, value: int) -> None:
        if self._jumping or not self.groups:
            return
        bar = self.scroll.verticalScrollBar()
        row = 0
        if bar.maximum() > 0 and value >= bar.maximum():
            row = len(self.groups) - 1
        else:
            for i, g in enumerate(self.groups):
                if g.y() <= value + 20:
                    row = i
        self.nav.blockSignals(True)
        self.nav.setCurrentRow(row)
        self.nav.blockSignals(False)


# Schalter im Bereich „Darstellung“ – dieselben Aktionen wie im Menü „Ansicht“ (v0.9.10)
DISPLAY_TOGGLES = ("toggle_buttonbar", "toggle_fkeybar", "toggle_toolbar", "toggle_hidden", "toggle_single")


class SettingsDialog(QDialog):
    def __init__(self, window) -> None:
        super().__init__(window)
        free_window(self)
        self.window = window
        self.setWindowTitle(t("settings.title"))
        self.setMinimumWidth(820)
        self.resize(900, 640)
        self.tabs = QTabWidget(self)
        self.pages: dict[str, SectionPage] = {}
        # Reiter „Allgemein“: Sprache, Sicherung, Darstellung
        page = self._page("general", t("settings.tab_general"))
        page.add_section(t("settings.sec_language"), self._language_section())
        page.add_section(t("settings.sec_backup"), self._backup_tab())
        page.add_section(t("settings.sec_display"), self._display_section())
        page.add_section(t("settings.sec_updates"), self._updates_section())
        page.add_section(t("settings.sec_servers"), self._servers_section())
        # Reiter „Dateiansicht“: Größeneinheit, Spalten
        page = self._page("view", t("settings.tab_view"))
        page.add_section(t("settings.sec_size"), self._size_section())
        page.add_section(t("settings.sec_columns"), self._columns_tab())
        # Reiter „Meta-Wizard“: ReplayGain
        page = self._page("meta", t("settings.tab_meta"))
        page.add_section(t("settings.sec_replaygain"), self._replaygain_section())
        box = QDialogButtonBox(self)
        box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(box)
        from PySide6.QtGui import QKeySequence, QShortcut

        QShortcut(QKeySequence("F1"), self, lambda: self.window.do_help("settings", parent=self))

    def _page(self, key: str, title: str) -> SectionPage:
        page = SectionPage(self.tabs)
        self.pages[key] = page
        self.tabs.addTab(page, title)
        return page

    @staticmethod
    def _hint(text: str, parent: QWidget) -> QLabel:
        label = QLabel(text, parent)
        label.setWordWrap(True)
        label.setEnabled(False)
        return label

    # --- Updates (v1.2) -----------------------------------------------------------------
    def _updates_section(self) -> QWidget:
        from PySide6.QtWidgets import QCheckBox

        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.update_check = QCheckBox(t("settings.update_check"), w)
        self.update_check.setChecked(bool(self.window.settings.get("update_check")))
        lay.addWidget(self.update_check)
        lay.addWidget(self._hint(t("settings.update_hint"), w))
        return w

    # --- Server (v1.3) -------------------------------------------------------------------
    def _servers_section(self) -> QWidget:
        w = QWidget(self)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        self.btn_filezilla = QPushButton(t("settings.import_filezilla"), w)
        self.btn_filezilla.clicked.connect(lambda: self.window.import_filezilla(parent=self))
        row = QHBoxLayout()
        row.addWidget(self.btn_filezilla)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self._hint(t("settings.import_filezilla_hint"), w))
        return w

    # --- Sprache -----------------------------------------------------------------------
    def _language_section(self) -> QWidget:
        w = QWidget(self)
        self.lang_box = QComboBox(w)
        self._fill_languages(self.window.settings.get("language") or SYSTEM)
        self.btn_lang_edit = QPushButton(t("settings.lang_edit"), w)
        self.btn_lang_new = QPushButton(t("settings.lang_new"), w)
        self.btn_lang_export = QPushButton(t("settings.lang_export"), w)
        self.btn_lang_import = QPushButton(t("settings.lang_import"), w)
        self.btn_lang_reset = QPushButton(t("settings.lang_reset"), w)
        self.btn_lang_edit.clicked.connect(self._edit_language)
        self.btn_lang_new.clicked.connect(self._new_language)
        self.btn_lang_export.clicked.connect(self._export_language)
        self.btn_lang_import.clicked.connect(self._import_language)
        self.btn_lang_reset.clicked.connect(self._reset_language)
        row = QHBoxLayout()
        row.addWidget(QLabel(t("settings.language"), w))
        row.addWidget(self.lang_box, 1)
        buttons = QHBoxLayout()
        for b in (self.btn_lang_edit, self.btn_lang_new, self.btn_lang_export, self.btn_lang_import,
                  self.btn_lang_reset):
            buttons.addWidget(b)
        buttons.addStretch(1)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addLayout(buttons)
        layout.addWidget(self._hint(t("settings.lang_restart_hint"), w))
        self.lang_box.currentIndexChanged.connect(self._lang_changed)
        self._lang_changed()
        return w

    def _fill_languages(self, select: str) -> None:
        self.lang_box.blockSignals(True)
        self.lang_box.clear()
        self.lang_box.addItem(t("settings.lang_system"), SYSTEM)
        for code, info in sorted(languages().items(), key=lambda kv: kv[1].name.casefold()):
            self.lang_box.addItem(info.name + ("  ✎" if info.user else ""), code)
        self.lang_box.setCurrentIndex(max(self.lang_box.findData(select), 0))
        self.lang_box.blockSignals(False)

    def _lang_code(self) -> str | None:
        """Gewählte Sprache; bei „Systemvorgabe“ die Sprache, die tatsächlich verwendet wird."""
        from .i18n import resolve

        code = self.lang_box.currentData()
        if code in (None, SYSTEM):
            code = resolve(SYSTEM)
        return code if code in languages() else None

    def _lang_changed(self, *_args) -> None:
        code = self._lang_code()
        info = languages().get(code) if code else None
        for b in (self.btn_lang_edit, self.btn_lang_export):
            b.setEnabled(info is not None)
        if info is not None and info.own:
            self.btn_lang_reset.setText(t("settings.lang_delete"))
            self.btn_lang_reset.setEnabled(True)
        else:
            self.btn_lang_reset.setText(t("settings.lang_reset"))
            self.btn_lang_reset.setEnabled(bool(info and info.user))

    def _refresh_languages(self, select: str | None = None) -> None:
        self._fill_languages(select if select is not None else self.lang_box.currentData())
        self._lang_changed()

    def _edit_language(self) -> None:
        code = self._lang_code()
        if not code:
            return
        LanguageEditor(self, code).exec()
        self._refresh_languages()

    def _new_language(self) -> None:
        dlg = NewLanguageDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        code, name, fallback = dlg.values()
        save_user_language(code, name, fallback, {})
        self._refresh_languages(code)
        LanguageEditor(self, code).exec()
        self._refresh_languages(code)

    def _export_language(self) -> None:
        import datetime as _dt
        from pathlib import Path

        from .i18n import export_language, user_folder

        code = self._lang_code()
        if not code:
            return
        folder = user_folder()
        name = next_language_export_name(folder, code, _dt.date.today())
        path, _f = QFileDialog.getSaveFileName(self, t("settings.lang_export_title"), str(folder / name),
                                               t("settings.lang_files"))
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            export_language(code, Path(path))
        except OSError as exc:
            show_error(self, t("settings.lang_export_title"), t("lang.export_failed", reason=exc.strerror or str(exc)))
            return
        from .dialogs import show_info

        show_info(self, t("settings.lang_export_title"), t("lang.exported", name=languages()[code].name, path=path))

    def _import_language(self) -> None:
        from pathlib import Path

        from .dialogs import show_info
        from .i18n import read_import, user_folder

        path, _f = QFileDialog.getOpenFileName(self, t("settings.lang_import_title"), str(user_folder()),
                                               t("settings.lang_files"))
        if not path:
            return
        title = t("settings.lang_import_title")
        try:
            result = read_import(Path(path))
        except ValueError as exc:
            show_error(self, title, t("lang.import_failed", reason=str(exc)))
            return
        known = languages().get(result.code)
        if known is not None and not known.own:
            question = t("lang.import_confirm_bundled", name=known.name)
        elif known is not None:
            question = t("lang.import_confirm_own", name=known.name, code=known.code)
        else:
            question = None
        if question and not confirm(self, title, question, default_yes=False):
            return
        if known is not None and not known.own:
            save_user_language(result.code, known.name, known.fallback, result.strings)
            name = known.name
        else:
            save_user_language(result.code, result.name, result.fallback, result.strings)
            name = result.name
        text = t("lang.import_done", n=len(result.strings), name=name)
        if result.bad_placeholders:
            text += "\n\n" + t("lang.import_bad", n=len(result.bad_placeholders),
                                 keys=", ".join(result.bad_placeholders[:8]))
        if result.unknown:
            text += "\n\n" + t("lang.import_unknown", n=result.unknown)
        self._refresh_languages(result.code)
        show_info(self, title, text)

    def _reset_language(self) -> None:
        from .i18n import remove_user_language

        code = self._lang_code()
        info = languages().get(code) if code else None
        if info is None or not info.user:
            return
        if info.own:
            title, question = t("lang.delete_title"), t("lang.delete_confirm", name=info.name, code=code)
            yes = "button.delete"
        else:
            title, question = t("lang.reset_title"), t("lang.reset_confirm", name=info.name)
            yes = "settings.lang_reset"
        if not confirm(self, title, question, yes_key=yes, default_yes=False):
            return
        remove_user_language(code)
        self._refresh_languages(SYSTEM if info.own and self.lang_box.currentData() == code else None)

    # --- Darstellung --------------------------------------------------------------------
    def _display_section(self) -> QWidget:
        w = QWidget(self)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        self.display_boxes: dict[str, QCheckBox] = {}
        for aid in DISPLAY_TOGGLES:
            act = self.window.qactions.get(aid)
            box = QCheckBox(t(f"action.{aid}"), w)
            box.setChecked(bool(act and act.isChecked()))
            box.setEnabled(bool(act and act.isEnabled()))
            layout.addWidget(box)
            self.display_boxes[aid] = box
        layout.addWidget(self._hint(t("settings.display_hint"), w))
        # Skalierung (v1.1)
        from PySide6.QtWidgets import QSlider

        from .util import SCALE_STEPS

        self.scale_slider = QSlider(Qt.Orientation.Horizontal, w)
        self.scale_slider.setRange(0, len(SCALE_STEPS) - 1)
        self.scale_slider.setPageStep(1)
        self.scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.scale_slider.setTickInterval(1)
        try:
            current = int(self.window.settings.get("ui_scale") or 100)
        except (TypeError, ValueError):
            current = 100
        self.scale_slider.setValue(SCALE_STEPS.index(current) if current in SCALE_STEPS else SCALE_STEPS.index(100))
        self.scale_label = QLabel(w)
        self.scale_label.setMinimumWidth(50)
        self.scale_slider.valueChanged.connect(lambda v: self.scale_label.setText(f"{SCALE_STEPS[v]} %"))
        self.scale_label.setText(f"{SCALE_STEPS[self.scale_slider.value()]} %")
        row = QHBoxLayout()
        row.addWidget(QLabel(t("settings.scale"), w))
        row.addWidget(self.scale_slider, 1)
        row.addWidget(self.scale_label)
        layout.addSpacing(8)
        layout.addLayout(row)
        layout.addWidget(self._hint(t("settings.scale_hint"), w))
        # Anwendungsmenü (v1.1)
        from . import desktopint

        self.menu_button = QPushButton(w)
        self.menu_status = QLabel(w)
        self.menu_status.setWordWrap(True)
        self.menu_button.clicked.connect(self._toggle_menu_entry)
        row = QHBoxLayout()
        row.addWidget(self.menu_button)
        row.addWidget(self.menu_status, 1)
        layout.addSpacing(8)
        layout.addLayout(row)
        self._update_menu_entry()
        return w

    def scale_value(self) -> int:
        from .util import SCALE_STEPS

        return SCALE_STEPS[self.scale_slider.value()]

    def _update_menu_entry(self) -> None:
        from . import desktopint

        integrated = desktopint.is_integrated()
        self.menu_button.setText(t("settings.menu_remove" if integrated else "settings.menu_add"))
        if not desktopint.appimage_path() and not integrated:
            self.menu_button.setEnabled(False)
            self.menu_status.setText(t("settings.menu_only_appimage"))
        else:
            self.menu_button.setEnabled(True)
            self.menu_status.setText(t("settings.menu_is_added" if integrated else "settings.menu_not_added"))

    def _toggle_menu_entry(self) -> None:
        from . import desktopint
        from .dialogs import show_info

        title = t("settings.menu_title")
        if desktopint.is_integrated():
            desktopint.remove()
            self._update_menu_entry()
            return
        try:
            desktopint.integrate()
        except OSError as exc:
            show_error(self, title, t("settings.menu_failed", reason=exc.strerror or str(exc)))
            return
        self._update_menu_entry()
        others = desktopint.other_launchers()
        text = t("settings.menu_done")
        if others:
            text += "\n\n" + t("settings.menu_others", files="\n".join(str(p) for p in others))
        show_info(self, title, text)

    # --- Größeneinheit / ReplayGain ------------------------------------------------------
    def _size_section(self) -> QWidget:
        w = QWidget(self)
        self.unit_box = QComboBox(w)
        for unit in SIZE_UNITS:
            self.unit_box.addItem(size_unit_label(unit), unit)
        self.unit_box.setCurrentIndex(max(self.unit_box.findData(self.window.settings.get("size_unit")), 0))
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow(t("settings.size_unit"), self.unit_box)
        return w

    def _replaygain_section(self) -> QWidget:
        from PySide6.QtWidgets import QDoubleSpinBox

        w = QWidget(self)
        self.rg_target = QDoubleSpinBox(w)
        self.rg_target.setRange(-30.0, -10.0)
        self.rg_target.setSingleStep(0.5)
        self.rg_target.setDecimals(1)
        self.rg_target.setSuffix(" LUFS")
        try:
            self.rg_target.setValue(float(self.window.settings.get("replaygain_target")))
        except (TypeError, ValueError):
            self.rg_target.setValue(-18.0)
        form = QFormLayout(w)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow(t("settings.rg_target"), self.rg_target)
        form.addRow("", self._hint(t("settings.rg_hint"), w))
        return w

    # --- Spalten -----------------------------------------------------------------------
    def _columns_tab(self) -> QWidget:
        w = QWidget(self)
        self.profile_list = QListWidget(w)
        self.profile_list.setMaximumWidth(200)
        self.btn_prof_new = QPushButton(t("settings.prof_new"), w)
        self.btn_prof_rename = QPushButton(t("settings.prof_rename"), w)
        self.btn_prof_delete = QPushButton(t("settings.prof_delete"), w)
        self.btn_prof_new.clicked.connect(self._prof_new)
        self.btn_prof_rename.clicked.connect(self._prof_rename)
        self.btn_prof_delete.clicked.connect(self._prof_delete)
        left = QVBoxLayout()
        left.addWidget(QLabel(t("settings.profiles"), w))
        left.addWidget(self.profile_list, 1)
        for b in (self.btn_prof_new, self.btn_prof_rename, self.btn_prof_delete):
            left.addWidget(b)

        self.col_table = QTableWidget(len(MENU_ORDER), 2, w)
        self.col_table.setHorizontalHeaderLabels([t("settings.col_visible"), t("settings.col_align")])
        self.col_table.verticalHeader().setVisible(False)
        self.col_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.col_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.col_table.horizontalHeader().resizeSection(1, 150)
        self._align_boxes: dict[int, QComboBox] = {}
        for row, col in enumerate(MENU_ORDER):
            item = QTableWidgetItem(t(COLUMN_KEYS[col]))
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            item.setData(Qt.ItemDataRole.UserRole, col)
            self.col_table.setItem(row, 0, item)
            box = QComboBox(self.col_table)
            for mode in colprofiles.ALIGNMENTS:
                box.addItem(t(f"colprof.align_{mode}"), mode)
            self.col_table.setCellWidget(row, 1, box)
            self._align_boxes[col] = box
        self.col_table.itemChanged.connect(self._name_columns_exclusive)

        self.side_boxes: dict[str, QComboBox] = {}
        sides = QFormLayout()
        for side, key in (("left", "settings.prof_left"), ("right", "settings.prof_right")):
            box = QComboBox(w)
            self.side_boxes[side] = box
            sides.addRow(t(key), box)
        hint = QLabel(t("settings.prof_hint"), w)
        hint.setWordWrap(True)
        hint.setEnabled(False)

        right = QVBoxLayout()
        right.addWidget(self.col_table, 1)
        heading = QLabel(t("settings.prof_default_heading"), w)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        right.addWidget(heading)
        right.addLayout(sides)
        right.addWidget(hint)
        layout = QHBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        self.col_table.setMinimumHeight(330)
        layout.addLayout(left)
        layout.addLayout(right, 1)

        self._profiles: dict[str, dict] = {n: colprofiles.load(n) for n in colprofiles.names()}
        self._renamed: dict[str, str] = {}  # neu → ursprünglich
        self._deleted: set[str] = set()
        self._current_profile: str | None = None
        self.profile_list.currentTextChanged.connect(self._show_profile)
        self._refresh_profiles(select=self.window.active.column_profile)
        for side, box in self.side_boxes.items():
            box.setCurrentIndex(max(box.findText(self.window.sides[side].panel.column_profile), 0))
        return w

    def _refresh_profiles(self, select: str | None = None) -> None:
        self._store_current()
        names = sorted(self._profiles, key=str.casefold)
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        self.profile_list.addItems(names)
        self.profile_list.blockSignals(False)
        for side, box in self.side_boxes.items():
            current = box.currentText()
            box.clear()
            box.addItems(names)
            box.setCurrentIndex(max(box.findText(current), 0))
        rows = self.profile_list.findItems(select or "", Qt.MatchFlag.MatchExactly)
        self.profile_list.setCurrentRow(self.profile_list.row(rows[0]) if rows else 0)
        self._show_profile(self.profile_list.currentItem().text() if self.profile_list.currentItem() else "")
        self.btn_prof_delete.setEnabled(len(names) > 1)

    def _hidden_from_header(self, data: dict) -> set[int]:
        """Ausgeblendete Spalten aus dem gespeicherten Kopfzustand ermitteln."""
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QStandardItemModel
        from PySide6.QtWidgets import QTreeView

        from .filemodel import DEFAULT_HIDDEN

        view = QTreeView()
        model = QStandardItemModel(0, COLUMN_COUNT, view)
        view.setModel(model)
        hdr = view.header()
        for c in DEFAULT_HIDDEN:
            hdr.setSectionHidden(c, True)
        if data.get("header"):
            hdr.restoreState(QByteArray.fromHex(data["header"].encode()))
        hidden = {c for c in range(COLUMN_COUNT) if hdr.isSectionHidden(c)}
        view.deleteLater()
        return hidden

    def _show_profile(self, name: str) -> None:
        self._store_current()
        self._current_profile = name or None
        data = self._profiles.get(name, {})
        hidden = data.get("_hidden")
        if hidden is None:
            hidden = self._hidden_from_header(data)
            data["_hidden"] = hidden
        align = data.get("align") or {}
        self.col_table.blockSignals(True)
        for row, col in enumerate(MENU_ORDER):
            self.col_table.item(row, 0).setCheckState(
                Qt.CheckState.Unchecked if col in hidden else Qt.CheckState.Checked)
            box = self._align_boxes[col]
            box.setCurrentIndex(box.findData(align.get(col, "right" if col == COL_SIZE else "left")))
        self.col_table.blockSignals(False)

    def _store_current(self) -> None:
        name = self._current_profile
        if not name or name not in self._profiles or not hasattr(self, "col_table"):
            return
        data = self._profiles[name]
        hidden = set()
        align = {}
        for row, col in enumerate(MENU_ORDER):
            if self.col_table.item(row, 0).checkState() != Qt.CheckState.Checked:
                hidden.add(col)
            mode = self._align_boxes[col].currentData()
            if mode != ("right" if col == COL_SIZE else "left"):
                align[col] = mode
        data["_hidden"] = hidden
        data["align"] = align

    def _name_columns_exclusive(self, item: QTableWidgetItem) -> None:
        """Genau eine Namensspalte (F-521) – wie im Spaltenmenü."""
        from .filemodel import NAME_COLUMNS

        col = item.data(Qt.ItemDataRole.UserRole)
        if col not in NAME_COLUMNS:
            return
        self.col_table.blockSignals(True)
        on = item.checkState() == Qt.CheckState.Checked
        for row, c in enumerate(MENU_ORDER):
            if c in NAME_COLUMNS and c != col:
                self.col_table.item(row, 0).setCheckState(Qt.CheckState.Unchecked if on else Qt.CheckState.Checked)
        self.col_table.blockSignals(False)

    def _ask_profile_name(self, title_key: str, default: str, ignore: str | None = None) -> str | None:
        from .dialogs import ask_text, show_error

        name = ask_text(self, t(title_key), t("colprof.name_prompt_plain"), default)
        if not name:
            return None
        name = name.strip()
        err = colprofiles.name_error(name, ignore)
        if err is None and any(n.casefold() == name.casefold() for n in self._profiles if n != ignore):
            err = "colprof.error_exists"
        if err:
            show_error(self, t(title_key), t(err, name=name))
            return None
        return name

    def _prof_new(self) -> None:
        name = self._ask_profile_name("colprof.new_title", t("colprof.new_default"))
        if name:
            self._store_current()
            base = self._profiles.get(self._current_profile or "", {})
            self._profiles[name] = {"header": base.get("header", ""), "columns": base.get("columns", COLUMN_COUNT),
                                    "align": dict(base.get("align") or {}), "_hidden": set(base.get("_hidden") or ())}
            self._refresh_profiles(select=name)

    def _prof_rename(self) -> None:
        old = self._current_profile
        if not old:
            return
        name = self._ask_profile_name("settings.prof_rename_title", old, ignore=old)
        if name and name != old:
            self._store_current()
            self._profiles[name] = self._profiles.pop(old)
            self._renamed[name] = self._renamed.pop(old, old)
            for box in self.side_boxes.values():
                if box.currentText() == old:
                    i = box.currentIndex()
                    box.setItemText(i, name)
            self._current_profile = name
            self._refresh_profiles(select=name)

    def _prof_delete(self) -> None:
        from .dialogs import confirm

        name = self._current_profile
        if not name or len(self._profiles) <= 1:
            return
        if not confirm(self, t("settings.prof_delete_title"), t("settings.prof_delete_confirm", name=name),
                       yes_key="button.delete"):
            return
        self._profiles.pop(name)
        self._deleted.add(self._renamed.pop(name, name))
        self._current_profile = None
        self._refresh_profiles()

    # --- Sicherung -----------------------------------------------------------------------
    def _backup_tab(self) -> QWidget:
        from .backup import backup_folder

        w = QWidget(self)
        self.backup_dir = QLineEdit(str(backup_folder(self.window.settings.get("backup_dir") or "")), w)
        self.backup_dir.editingFinished.connect(self._refresh_backups)
        browse = QPushButton(t("button.browse"), w)
        browse.clicked.connect(self._browse_backup)
        row = QHBoxLayout()
        row.addWidget(self.backup_dir, 1)
        row.addWidget(browse)
        self.backup_keep = QSpinBox(w)
        self.backup_keep.setRange(1, 999)
        self.backup_keep.setValue(int(self.window.settings.get("backup_keep") or 30))

        # Zustand der automatischen Sicherung und Liste der vorhandenen Sicherungen (v0.8.1)
        self.backup_status = QLabel(w)
        self.backup_status.setWordWrap(True)
        self.backup_error = QLabel(w)
        self.backup_error.setWordWrap(True)
        self.backup_error.setStyleSheet("color: #D32F2F;")
        self.backup_list = QTreeWidget(w)
        self.backup_list.setRootIsDecorated(False)
        self.backup_list.setAlternatingRowColors(True)
        self.backup_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.backup_list.setHeaderLabels([t("backup.col_name"), t("backup.col_date"), t("backup.col_kind"),
                                          t("backup.col_size")])
        # Alle Spalten frei in der Breite; passt es nicht, erscheint unten ein Rollbalken (v0.8.2)
        self.backup_list.header().setStretchLastSection(False)
        self.backup_list.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.backup_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._backup_cols_sized = False
        self.backup_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.backup_list.customContextMenuRequested.connect(self._backup_menu)
        self.backup_list.itemSelectionChanged.connect(self._backup_selection_changed)
        self.backup_list.itemDoubleClicked.connect(lambda *_: self._restore_selected())

        self.btn_backup_now = QPushButton(t("settings.backup_now"), w)
        self.btn_restore = QPushButton(t("settings.restore_selected"), w)
        self.btn_import = QPushButton(t("settings.backup_import"), w)
        self.btn_backup_delete = QPushButton(t("settings.backup_delete"), w)
        self.btn_backup_now.clicked.connect(self._backup_now)
        self.btn_restore.clicked.connect(self._restore_selected)
        self.btn_import.clicked.connect(self._import_backup)
        self.btn_backup_delete.clicked.connect(self._delete_selected_backups)
        buttons = QHBoxLayout()
        for b in (self.btn_backup_now, self.btn_restore, self.btn_import, self.btn_backup_delete):
            buttons.addWidget(b)
        buttons.addStretch(1)

        form = QFormLayout()
        form.addRow(t("settings.backup_dir"), row)
        form.addRow(t("settings.backup_keep"), self.backup_keep)
        hint = QLabel(t("settings.backup_hint"), w)
        hint.setWordWrap(True)
        hint.setEnabled(False)
        form.addRow("", hint)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        self.backup_list.setMinimumHeight(170)
        layout.addLayout(form)
        layout.addWidget(self.backup_status)
        layout.addWidget(self.backup_error)
        layout.addWidget(QLabel(t("settings.backup_list"), w))
        layout.addWidget(self.backup_list, 1)
        layout.addLayout(buttons)
        self._refresh_backups()
        return w

    def _current_backup_folder(self):
        from .backup import backup_folder

        return backup_folder(self.backup_dir.text().strip())

    def _refresh_backups(self, select: str | None = None) -> None:
        import datetime as _dt

        from .backup import list_backups

        infos = list_backups(self._current_backup_folder())
        self.backup_list.clear()
        for info in infos:
            when = _dt.datetime.fromtimestamp(info.mtime).strftime("%d.%m.%Y %H:%M")
            item = QTreeWidgetItem([info.name, when, t("backup.kind_auto" if info.auto else "backup.kind_manual"),
                                    format_size(info.size)])
            item.setData(0, Qt.ItemDataRole.UserRole, str(info.path))
            item.setTextAlignment(3, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.backup_list.addTopLevelItem(item)
            if select and info.name == select:
                item.setSelected(True)
                self.backup_list.setCurrentItem(item)
        if not self._backup_cols_sized and infos:
            # Startbreiten nach Inhalt, danach bleiben die Breiten so, wie du sie ziehst
            for col in range(self.backup_list.columnCount()):
                self.backup_list.resizeColumnToContents(col)
                self.backup_list.setColumnWidth(col, self.backup_list.columnWidth(col) + 16)
            self._backup_cols_sized = True
        last_auto = next((i for i in infos if i.auto), None)
        if last_auto:
            when = _dt.datetime.fromtimestamp(last_auto.mtime).strftime("%d.%m.%Y, %H:%M")
            self.backup_status.setText(t("backup.last_auto", when=when))
        else:
            self.backup_status.setText(t("backup.last_auto_none"))
        err = self.window.settings.get("backup_last_error") or {}
        if isinstance(err, dict) and err.get("date"):
            try:
                day = _dt.date.fromisoformat(str(err["date"])).strftime("%d.%m.%Y")
            except ValueError:
                day = str(err["date"])
            self.backup_error.setText(t("backup.last_error", date=day, reason=str(err.get("reason", ""))))
            self.backup_error.setVisible(True)
        else:
            self.backup_error.setText("")
            self.backup_error.setVisible(False)
        self._backup_selection_changed()

    def _selected_backups(self) -> list[str]:
        return [it.data(0, Qt.ItemDataRole.UserRole) for it in self.backup_list.selectedItems()]

    def _backup_selection_changed(self) -> None:
        n = len(self._selected_backups())
        self.btn_restore.setEnabled(n == 1)
        self.btn_backup_delete.setEnabled(n > 0)

    def _backup_menu(self, pos) -> None:
        if not self._selected_backups():
            return
        menu = QMenu(self)
        act_restore = menu.addAction(t("settings.restore_selected"))
        act_restore.setEnabled(len(self._selected_backups()) == 1)
        act_delete = menu.addAction(t("settings.backup_delete"))
        chosen = menu.exec(self.backup_list.viewport().mapToGlobal(pos))
        if chosen is act_restore:
            self._restore_selected()
        elif chosen is act_delete:
            self._delete_selected_backups()

    def _backup_now(self) -> None:
        self._apply_backup_settings()
        self.window.do_backup_now(parent=self)
        self._refresh_backups()

    def _restore_selected(self) -> None:
        paths = self._selected_backups()
        if len(paths) != 1:
            return
        self._apply_backup_settings()
        self.window.do_restore_backup(paths[0], parent=self)

    def _import_backup(self) -> None:
        import zipfile
        from pathlib import Path

        from .backup import import_backup

        path, _f = QFileDialog.getOpenFileName(self, t("settings.backup_import_title"), str(Path.home()),
                                               "PanePilot (*.zip)")
        if not path:
            return
        try:
            target = import_backup(Path(path), self._current_backup_folder())
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            show_error(self, t("settings.backup_import_title"), t("backup.import_failed", reason=str(exc)))
            return
        self._refresh_backups(select=target.name)

    def _delete_selected_backups(self) -> None:
        from pathlib import Path

        from .backup import delete_backups

        paths = self._selected_backups()
        if not paths:
            return
        text = (t("backup.delete_confirm_one", name=os.path.basename(paths[0])) if len(paths) == 1
                else t("backup.delete_confirm", n=len(paths)))
        if not confirm(self, t("settings.backup_delete_title"), text, yes_key="button.delete", default_yes=False):
            return
        errors = delete_backups([Path(p) for p in paths])
        if errors:
            show_error(self, t("settings.backup_delete_title"),
                       "\n".join(f"{p.name}: {reason}" for p, reason in errors))
        self._refresh_backups()

    def _browse_backup(self) -> None:
        path = QFileDialog.getExistingDirectory(self, t("settings.backup_dir"), self.backup_dir.text())
        if path:
            self.backup_dir.setText(path)
            self._refresh_backups()

    def _apply_backup_settings(self) -> None:
        from .backup import backup_folder

        text = self.backup_dir.text().strip()
        default = str(backup_folder(""))
        self.window.settings.set("backup_dir", "" if not text or text == default else text)
        self.window.settings.set("backup_keep", self.backup_keep.value())

    # --- Übernehmen ----------------------------------------------------------------------
    def accept(self) -> None:
        self._store_current()
        s = self.window.settings
        self._apply_backup_settings()
        s.set("size_unit", self.unit_box.currentData())
        s.set("replaygain_target", round(self.rg_target.value(), 1))
        s.set("update_check", self.update_check.isChecked())
        # Spaltenprofile schreiben
        for name in self._deleted:
            try:
                colprofiles.delete(name)
            except OSError:
                pass
        for name, orig in self._renamed.items():
            if orig != name and orig not in self._deleted:
                try:
                    colprofiles.rename(orig, name)
                except OSError:
                    pass
        for name, data in self._profiles.items():
            out = {k: v for k, v in data.items() if not k.startswith("_")}
            out["header"] = _with_hidden(out.get("header", ""), data.get("_hidden"))
            out["columns"] = COLUMN_COUNT
            colprofiles.save(name, out)
        assign = {side: box.currentText() for side, box in self.side_boxes.items()}
        new_lang = self.lang_box.currentData()
        lang_changed = new_lang != (s.get("language") or "system")
        toggles = [aid for aid, box in self.display_boxes.items()
                   if box.isEnabled() and box.isChecked() != self.window.qactions[aid].isChecked()]
        try:
            old_scale = int(s.get("ui_scale") or 100)
        except (TypeError, ValueError):
            old_scale = 100
        scale_changed = self.scale_value() != old_scale
        s.set("ui_scale", self.scale_value())
        super().accept()
        for aid in toggles:
            self.window.trigger(aid)
        self.window.apply_settings(assign, new_lang)
        # Bei Sprachwechsel fragt schon apply_settings nach dem Neustart
        if scale_changed and not lang_changed and confirm(
                self.window, t("settings.scale_title"), t("settings.scale_restart"), yes_key="button.restart_now",
                no_key="donate.later"):
            self.window.restart()


def next_language_export_name(folder, code: str, day) -> str:
    """PanePilot_Sprache-<kürzel>_JJJJ-MM-TTa.json, bei Belegung b, c, …"""
    for i in range(26 * 27):
        suffix = chr(97 + i) if i < 26 else chr(96 + i // 26) + chr(97 + i % 26)
        name = f"PanePilot_Sprache-{code}_{day.isoformat()}{suffix}.json"
        if not os.path.exists(os.path.join(str(folder), name)):
            return name
    return f"PanePilot_Sprache-{code}_{day.isoformat()}.json"


def _with_hidden(header_hex: str, hidden) -> str:
    """Sichtbarkeit im gespeicherten Kopfzustand setzen, Reihenfolge/Breiten bleiben."""
    if hidden is None:
        return header_hex
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QStandardItemModel
    from PySide6.QtWidgets import QTreeView

    view = QTreeView()
    model = QStandardItemModel(0, COLUMN_COUNT, view)
    view.setModel(model)
    hdr = view.header()
    if header_hex:
        hdr.restoreState(QByteArray.fromHex(header_hex.encode()))
    for c in range(COLUMN_COUNT):
        hdr.setSectionHidden(c, c in hidden)
    out = bytes(hdr.saveState().toHex()).decode()
    view.deleteLater()
    return out


# --- Sprachen --------------------------------------------------------------------------------
class NewLanguageDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("lang.new_title"))
        self.name = QLineEdit(self)
        self.name.setPlaceholderText("Säggssch")
        self.code = QLineEdit(self)
        self.code.setPlaceholderText("sxu")
        self.fallback = QComboBox(self)
        self.fallback.addItem(t("lang.fallback_de"), "de")
        self.fallback.addItem(t("lang.fallback_en"), "en")
        self.error = QLabel(self)
        self.error.setStyleSheet("color: #D32F2F;")
        form = QFormLayout()
        form.addRow(t("lang.name"), self.name)
        form.addRow(t("lang.code"), self.code)
        form.addRow(t("lang.fallback"), self.fallback)
        box = QDialogButtonBox(self)
        self.ok = box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        hint = QLabel(t("lang.new_hint"), self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(self.error)
        layout.addWidget(box)
        self.name.textChanged.connect(self._validate)
        self.code.textChanged.connect(self._validate)
        self._validate()

    def _validate(self, *_args) -> None:
        code = self.code.text().strip().lower()
        err = ""
        if code and not re.fullmatch(r"[a-z]{2,8}(_[a-z0-9]{2,8})?", code):
            err = t("lang.err_code")
        elif code in languages():
            err = t("lang.err_exists", code=code)
        self.error.setText(err)
        self.ok.setEnabled(bool(self.name.text().strip() and code and not err))

    def values(self) -> tuple[str, str, str]:
        return self.code.text().strip().lower(), self.name.text().strip(), self.fallback.currentData()


class LanguageEditor(QDialog):
    """Sprache bearbeiten (F-865, v0.9.10).

    Mitgelieferte Sprachen (auch Deutsch): Spalten „Original“ und „Dein Text“. Gespeichert werden nur
    die geänderten Texte, alle anderen bleiben beim Original.
    Selbst angelegte Sprachen: Spalten „Deutsch (Vorlage)“ und Übersetzung wie bisher.
    """

    COL_KEY, COL_BASE, COL_TEXT = range(3)

    def __init__(self, parent, code: str) -> None:
        super().__init__(parent)
        from .i18n import read_bundled

        free_window(self)
        info = languages()[code]
        self.code = code
        self.lang_name = info.name
        self.fallback = info.fallback or ("" if code == BASE_LANGUAGE else "en")
        self.bundled = not info.own
        self.setWindowTitle(t("lang.edit_title", name=info.name))
        self.resize(980, 640)
        german = read_bundled(BASE_LANGUAGE)
        self.german = german
        if self.bundled:
            self.template = read_bundled(code)
            current = read_language(code)
            headers = [t("lang.col_key"), t("lang.col_original"), t("lang.col_mine")]
        else:
            self.template = german
            current = read_language(code)
            headers = [t("lang.col_key"), t("lang.col_base"), t("lang.col_text", name=info.name)]
        keys = sorted(german)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText(t("lang.search"))
        self.only_missing = QCheckBox(t("lang.only_changed" if self.bundled else "lang.only_missing"), self)
        self.counter = QLabel(self)
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.only_missing)
        top.addWidget(self.counter)
        self.table = QTableWidget(len(keys), 3, self)
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(self.COL_KEY, QHeaderView.ResizeMode.Interactive)
        hh.resizeSection(self.COL_KEY, 220)
        hh.setSectionResizeMode(self.COL_BASE, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(self.COL_TEXT, QHeaderView.ResizeMode.Stretch)
        for row, key in enumerate(keys):
            k = QTableWidgetItem(key)
            k.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            b = QTableWidgetItem(self._original(key))
            b.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            v = QTableWidgetItem(current.get(key, ""))
            self.table.setItem(row, self.COL_KEY, k)
            self.table.setItem(row, self.COL_BASE, b)
            self.table.setItem(row, self.COL_TEXT, v)
        self.error = QLabel(self)
        self.error.setStyleSheet("color: #D32F2F;")
        self.error.setWordWrap(True)
        box = QDialogButtonBox(self)
        self.save_button = box.addButton(t("lang.save"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        hint = QLabel(t("lang.edit_hint_bundled" if self.bundled else "lang.edit_hint"), self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addLayout(top)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.error)
        layout.addWidget(box)
        self.table.itemChanged.connect(self._update)
        self.search.textChanged.connect(self._apply_view)
        self.only_missing.toggled.connect(self._apply_view)
        self._update()

    def _original(self, key: str) -> str:
        if self.bundled:
            return self.template.get(key) or self.german.get(key, "")
        return self.template.get(key, "")

    def _row_problem(self, row: int) -> str | None:
        base = self.table.item(row, self.COL_BASE).text()
        text = self.table.item(row, self.COL_TEXT).text()
        if not text:
            return None if self.bundled else "missing"
        if set(_PLACEHOLDER.findall(base)) != set(_PLACEHOLDER.findall(text)):
            return "placeholder"
        if self.bundled and text != base:
            return "changed"
        return None

    def _update(self, *_args) -> None:
        self.table.blockSignals(True)
        missing = bad = changed = 0
        bad_keys = []
        for row in range(self.table.rowCount()):
            problem = self._row_problem(row)
            item = self.table.item(row, self.COL_TEXT)
            if problem == "missing":
                missing += 1
                item.setBackground(QColor("#FFF3B0"))
                item.setForeground(QColor("#000000"))
                item.setToolTip(t("lang.tip_missing"))
            elif problem == "placeholder":
                bad += 1
                bad_keys.append(self.table.item(row, self.COL_KEY).text())
                item.setBackground(QColor("#F8C8C8"))
                item.setForeground(QColor("#000000"))
                item.setToolTip(t("lang.tip_placeholder"))
            elif problem == "changed":
                changed += 1
                item.setBackground(QColor("#CCE4FF"))
                item.setForeground(QColor("#000000"))
                item.setToolTip(t("lang.tip_changed", original=self.table.item(row, self.COL_BASE).text()))
            else:
                item.setData(Qt.ItemDataRole.BackgroundRole, None)
                item.setData(Qt.ItemDataRole.ForegroundRole, None)
                item.setToolTip("")
        self.table.blockSignals(False)
        if self.bundled:
            self.counter.setText(t("lang.counter_changed", changed=changed, total=self.table.rowCount()))
        else:
            self.counter.setText(t("lang.counter", missing=missing, total=self.table.rowCount()))
        self.error.setText(t("lang.err_placeholders", keys=", ".join(bad_keys[:5])) if bad else "")
        self.save_button.setEnabled(bad == 0)
        self._apply_view()

    def _apply_view(self, *_args) -> None:
        needle = self.search.text().strip().casefold()
        only = self.only_missing.isChecked()
        wanted = "changed" if self.bundled else "missing"
        for row in range(self.table.rowCount()):
            texts = " ".join(self.table.item(row, c).text() for c in range(3)).casefold()
            hide = (needle and needle not in texts) or (only and self._row_problem(row) != wanted)
            self.table.setRowHidden(row, bool(hide))

    def strings(self) -> dict[str, str]:
        return {self.table.item(r, self.COL_KEY).text(): self.table.item(r, self.COL_TEXT).text()
                for r in range(self.table.rowCount()) if self.table.item(r, self.COL_TEXT).text()}

    def accept(self) -> None:
        from .i18n import read_bundled, remove_user_language

        strings = self.strings()
        if self.bundled:
            original = read_bundled(self.code)
            if not any(v != original.get(k) for k, v in strings.items()):
                remove_user_language(self.code)  # nichts geändert → wieder ganz das Original
                super().accept()
                return
        save_user_language(self.code, self.lang_name, self.fallback, strings)
        super().accept()
