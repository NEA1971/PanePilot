"""Symbolleiste unter der Menüleiste (F-550 ff.)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .dialogs import free_window
from .actions import ACTION_DEFS, NOT_ASSIGNABLE
from .i18n import t
from .toolicons import action_icon

SEPARATOR = "|"
SPACER = "_:"  # fester Abstand, z. B. "_:24" (Breite in Pixeln) – v0.9.3
RIGHT = ">"  # alles danach rechtsbündig – höchstens einmal
SPACER_MIN, SPACER_MAX, SPACER_DEFAULT = 8, 200, 24


def spacer_width(item: str) -> int | None:
    if not isinstance(item, str) or not item.startswith(SPACER):
        return None
    try:
        return max(SPACER_MIN, min(SPACER_MAX, int(item[len(SPACER):])))
    except ValueError:
        return None
DEFAULT_ITEMS = ["back", "forward", "quick_view"]  # v2.7: Schnellansicht ab Werk
HISTORY_ACTIONS = ("back", "forward")
MENU_ACTIONS = HISTORY_ACTIONS + ("filter_toggle", "view_mode", "clip_copy", "archive", "tabs")  # Knopf mit Pfeil und Menü
# Nicht in der Symbolleiste: an eine Ansicht gebundene Aktionen; v1.23: die Ansichten stecken im Knopf „Ansicht“
VIEW_LEGACY = ("toggle_icon_view", "icons_small", "icons_medium", "icons_large")
# v1.23.1: die Zwischenablage-Einträge stecken nur im Pfeil-Menü des Knopfs „Kopieren“, keine eigenen Knöpfe
CLIP_MENU_ONLY = ("clip_path", "clip_name", "clip_stem", "clip_folder", "clip_url", "clip_details",
                  "clip_folder_short", "clip_path_short", "clip_name_short", "clip_folder_web", "clip_path_web",
                  "clip_folder_unc", "clip_path_unc", "clip_path_unc_web")
# v2.2 (L-3202): Packen/Entpacken stecken im Knopf „Archiv“
ARCHIVE_LEGACY = ("compress", "extract_here", "extract_subfolder", "extract_to", "archive_open")
# v2.2: die Reiter-Funktionen stecken im Knopf „Reiter“
TABS_LEGACY = ("tab_new", "tab_close", "tab_next", "tab_prev", "tab_lock", "tab_to_other", "open_in_tab")
# v2.6: Trennlinie nur im Rechtsklick-Menü der Favoritenleiste (kein Knopf ohne Absprache)
FAV_MENU_ONLY = ("fav_separator",)
# v2.7: nur Menü/Rechtsklick/Tasten – kein Knopf ohne Absprache (einziger neuer Knopf: „Schnellansicht“)
NO_BUTTON_27 = ("select_add", "select_remove", "select_invert", "select_same_ext", "folder_size", "folder_sizes_all",
                "compare_files", "change_date", "net_drive_connect", "net_drive_disconnect",
                "fav_import_fc", "fav_sort", "fav_popup")
EXCLUDED = (set(NOT_ASSIGNABLE) | set(VIEW_LEGACY) | set(CLIP_MENU_ONLY) | set(ARCHIVE_LEGACY) | set(TABS_LEGACY)
            | set(FAV_MENU_ONLY) | set(NO_BUTTON_27))


def available_actions() -> list[str]:
    return [a.id for a in ACTION_DEFS if a.id not in EXCLUDED]


def clean_items(items) -> list[str]:
    """Gespeicherte Liste prüfen: unbekannte Einträge und doppelte Trennstriche entfernen."""
    if not isinstance(items, list):
        return list(DEFAULT_ITEMS)
    valid = set(available_actions())
    result: list[str] = []
    for it in items:
        if it in VIEW_LEGACY:  # v1.23 (L-2302): alte Ansicht-Knöpfe → ein Knopf „Ansicht“
            it = "view_mode"
        if it in ARCHIVE_LEGACY:  # v2.2 (L-3202): alte Packen/Entpacken-Knöpfe → ein Knopf „Archiv“
            it = "archive"
        if it in TABS_LEGACY:  # v2.2: alte Reiter-Knöpfe → ein Knopf „Reiter“
            it = "tabs"
        if it == SEPARATOR:
            if result and result[-1] != SEPARATOR:
                result.append(it)
        elif spacer_width(it) is not None:
            result.append(f"{SPACER}{spacer_width(it)}")
        elif it == RIGHT:
            if RIGHT not in result:
                result.append(it)
        elif isinstance(it, str) and it in valid and it not in result:
            result.append(it)
    while result and result[-1] == SEPARATOR:
        result.pop()
    return result


def label_of(action_id: str) -> str:
    from .actions import ACTIONS_BY_ID

    special = t(f"toolbar.label.{action_id}")  # eindeutige Namen, wo der Menütext allein mehrdeutig ist
    if special != f"toolbar.label.{action_id}":
        return special
    return t(ACTIONS_BY_ID[action_id].text_key).replace(" …", "").replace("…", "")


class MainToolBar(QToolBar):
    customize_requested = Signal()
    hide_requested = Signal()
    rebuilt = Signal()  # nach set_items: veränderliche Symbole neu setzen

    def __init__(self, parent, qactions: dict[str, QAction], key_text, history_menu) -> None:
        """key_text(aid) → Tastenkürzel als Text; history_menu(aid, menu) füllt das Pfeil-Menü."""
        super().__init__(t("toolbar.title"), parent)
        self.setObjectName("main_toolbar")
        self.setMovable(False)
        self.setFloatable(False)
        self.setIconSize(QSize(22, 22))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._context_menu)
        self.toggleViewAction().setVisible(False)
        self._qactions = qactions
        self._key_text = key_text
        self._history_menu = history_menu
        self.items: list[str] = []
        self.proxies: dict[str, QAction] = {}

    def set_items(self, items: list[str]) -> None:
        self.clear()
        self.proxies.clear()
        self.items = clean_items(items)
        for aid in self.items:
            if aid == SEPARATOR:
                self.addSeparator()
                continue
            if spacer_width(aid) is not None or aid == RIGHT:
                gap = QWidget(self)
                if aid == RIGHT:
                    gap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                else:
                    gap.setFixedWidth(spacer_width(aid))
                gap.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                self.addWidget(gap)
                continue
            self.proxies[aid] = self._add_item(aid)
        self.rebuilt.emit()

    def _add_item(self, aid: str) -> QAction:
        source = self._qactions[aid]
        proxy = QAction(action_icon(aid, label_of(aid)), label_of(aid), self)
        keys = self._key_text(aid)
        proxy.setToolTip(f"{label_of(aid)} ({keys})" if keys else label_of(aid))
        proxy.setCheckable(source.isCheckable())

        def sync(src=source, prx=proxy) -> None:
            prx.setEnabled(src.isEnabled())
            if src.isCheckable():
                prx.setChecked(src.isChecked())

        sync()
        source.changed.connect(sync)
        proxy.triggered.connect(lambda _c=False, a=source, prx=proxy: (a.trigger(), sync()))
        if aid in MENU_ACTIONS:
            button = QToolButton(self)
            button.setDefaultAction(proxy)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            button.setIconSize(self.iconSize())
            menu = QMenu(button)
            menu.aboutToShow.connect(lambda m=menu, a=aid: self._history_menu(a, m))
            button.setMenu(menu)
            self.addWidget(button)
        else:
            self.addAction(proxy)
        return proxy

    def set_action_look(self, aid: str, icon=None, tooltip: str | None = None) -> None:
        """Symbol/Infotext eines Knopfs ändern (z. B. Filter an/aus)."""
        proxy = self.proxies.get(aid)
        if proxy is None:
            return
        if icon is not None:
            proxy.setIcon(icon)
        if tooltip is not None:
            proxy.setToolTip(tooltip)

    def _context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction(t("toolbar.customize")).triggered.connect(self.customize_requested)
        menu.addAction(t("toolbar.hide")).triggered.connect(self.hide_requested)
        menu.exec(self.mapToGlobal(pos))


class ToolbarDialog(QDialog):
    """„Symbolleiste anpassen“ (F-554)."""

    def __init__(self, parent, items: list[str]) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("toolbar.customize_title"))
        self.available = QListWidget(self)
        self.chosen = QListWidget(self)
        for w in (self.available, self.chosen):
            w.setIconSize(QSize(20, 20))
            w.setMinimumSize(260, 340)
        self.available.itemDoubleClicked.connect(lambda _i: self._add())
        self.chosen.itemDoubleClicked.connect(lambda _i: self._remove())

        self.btn_add = QPushButton(t("toolbar.add"), self)
        self.btn_remove = QPushButton(t("toolbar.remove"), self)
        self.btn_up = QPushButton(t("toolbar.up"), self)
        self.btn_down = QPushButton(t("toolbar.down"), self)
        self.btn_sep = QPushButton(t("toolbar.separator"), self)
        self.btn_space = QPushButton(t("toolbar.spacer"), self)
        self.space_width = QSpinBox(self)
        self.space_width.setRange(SPACER_MIN, SPACER_MAX)
        self.space_width.setValue(SPACER_DEFAULT)
        self.space_width.setSuffix(" px")
        self.space_width.setToolTip(t("toolbar.spacer_width"))
        self.btn_right = QPushButton(t("toolbar.right"), self)
        self.btn_space.clicked.connect(self._add_spacer)
        self.btn_right.clicked.connect(self._add_right)
        self.space_width.valueChanged.connect(self._spacer_width_changed)
        self.btn_default = QPushButton(t("toolbar.default"), self)
        self.btn_add.clicked.connect(self._add)
        self.btn_remove.clicked.connect(self._remove)
        self.btn_up.clicked.connect(lambda: self._move(-1))
        self.btn_down.clicked.connect(lambda: self._move(1))
        self.btn_sep.clicked.connect(self._add_separator)
        self.btn_default.clicked.connect(lambda: self._fill(list(DEFAULT_ITEMS)))

        buttons = QVBoxLayout()
        buttons.addStretch(1)
        for b in (self.btn_add, self.btn_remove, None, self.btn_up, self.btn_down, None, self.btn_sep,
                  self.btn_space, self.space_width, self.btn_right):
            if b is None:
                buttons.addSpacing(12)
            else:
                buttons.addWidget(b)
        buttons.addStretch(1)
        grid = QGridLayout()
        grid.addWidget(QLabel(t("toolbar.available"), self), 0, 0)
        grid.addWidget(QLabel(t("toolbar.chosen"), self), 0, 2)
        grid.addWidget(self.available, 1, 0)
        grid.addLayout(buttons, 1, 1)
        grid.addWidget(self.chosen, 1, 2)

        box = QDialogButtonBox(self)
        ok = box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.addButton(self.btn_default, QDialogButtonBox.ButtonRole.ResetRole)
        ok.setDefault(True)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(grid)
        layout.addWidget(box)
        self.chosen.currentRowChanged.connect(self._chosen_changed)
        self._fill(clean_items(items))

    @staticmethod
    def _item(aid: str) -> QListWidgetItem:
        if aid == SEPARATOR:
            item = QListWidgetItem(t("toolbar.separator_item"))
        elif spacer_width(aid) is not None:
            item = QListWidgetItem(t("toolbar.spacer_item", n=spacer_width(aid)))
        elif aid == RIGHT:
            item = QListWidgetItem(t("toolbar.right_item"))
        else:
            item = QListWidgetItem(action_icon(aid, label_of(aid)), label_of(aid))
        item.setData(Qt.ItemDataRole.UserRole, aid)
        return item

    def _fill(self, items: list[str]) -> None:
        self.chosen.clear()
        for aid in items:
            self.chosen.addItem(self._item(aid))
        self._refresh_available()

    def _refresh_available(self) -> None:
        used = set(self.items())
        self.available.clear()
        for aid in sorted((a for a in available_actions() if a not in used), key=lambda a: label_of(a).casefold()):
            self.available.addItem(self._item(aid))

    def items(self) -> list[str]:
        return [self.chosen.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.chosen.count())]

    def _insert_row(self) -> int:
        row = self.chosen.currentRow()
        return row + 1 if row >= 0 else self.chosen.count()

    def _add(self) -> None:
        item = self.available.currentItem()
        if item is None:
            return
        row = self._insert_row()
        self.chosen.insertItem(row, self._item(item.data(Qt.ItemDataRole.UserRole)))
        self.chosen.setCurrentRow(row)
        current = self.available.currentRow()
        self._refresh_available()
        self.available.setCurrentRow(min(current, self.available.count() - 1))

    def _add_separator(self) -> None:
        row = self._insert_row()
        self.chosen.insertItem(row, self._item(SEPARATOR))
        self.chosen.setCurrentRow(row)

    def _add_spacer(self) -> None:
        row = self._insert_row()
        self.chosen.insertItem(row, self._item(f"{SPACER}{self.space_width.value()}"))
        self.chosen.setCurrentRow(row)

    def _add_right(self) -> None:
        if RIGHT in self.items():
            return
        row = self._insert_row()
        self.chosen.insertItem(row, self._item(RIGHT))
        self.chosen.setCurrentRow(row)
        self._chosen_changed(row)

    def _chosen_changed(self, row: int) -> None:
        item = self.chosen.item(row) if row >= 0 else None
        width = spacer_width(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None
        if width is not None:
            self.space_width.blockSignals(True)
            self.space_width.setValue(width)
            self.space_width.blockSignals(False)
        self.btn_right.setEnabled(RIGHT not in self.items())

    def _spacer_width_changed(self, value: int) -> None:
        """Breite des markierten Abstands ändern."""
        row = self.chosen.currentRow()
        item = self.chosen.item(row) if row >= 0 else None
        if item is not None and spacer_width(item.data(Qt.ItemDataRole.UserRole)) is not None:
            self.chosen.takeItem(row)
            self.chosen.insertItem(row, self._item(f"{SPACER}{value}"))
            self.chosen.setCurrentRow(row)

    def _remove(self) -> None:
        row = self.chosen.currentRow()
        if row < 0:
            return
        self.chosen.takeItem(row)
        self.chosen.setCurrentRow(min(row, self.chosen.count() - 1))
        self._refresh_available()
        self.btn_right.setEnabled(RIGHT not in self.items())

    def _move(self, delta: int) -> None:
        row = self.chosen.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < self.chosen.count():
            return
        item = self.chosen.takeItem(row)
        self.chosen.insertItem(new, item)
        self.chosen.setCurrentRow(new)

    def result_items(self) -> list[str]:
        return clean_items(self.items())
