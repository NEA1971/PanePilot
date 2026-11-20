"""„Ordner synchronisieren“ als Seitenleiste mit Vergleichsansicht (v1.18, L-1800 ff.).

SyncPane ist die Seitenleiste (Einstellungen), SyncView die Ansicht mit den beiden Ordnern als Baum,
der Aktionsspalte in der Mitte und den Knöpfen für die markierten Zeilen.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime

from PySide6.QtCore import QEventLoop, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFrame, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMenu, QProgressDialog, QPushButton, QRadioButton, QScrollArea,
                               QStyle, QStyledItemDelegate, QStyleOptionViewItem, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import folderdiff as fd
from . import syncprofiles as sp
from . import util
from .dialogs import confirm, show_error, show_info
from .i18n import t

L_NAME, L_SIZE, L_DATE, ACT, R_NAME, R_SIZE, R_DATE = range(7)
SIZE_W, DATE_W, ACT_W = 80, 120, 44
INDENT, TOGGLE_W = 16, 14
ROLE_ENTRY = Qt.ItemDataRole.UserRole + 1  # Index in entries oder -1 bei Ordnerknoten
ROLE_DEPTH = Qt.ItemDataRole.UserRole + 2
ROLE_ICON = Qt.ItemDataRole.UserRole + 3  # (Zeichen, Farbe)
MIXED = "mixed"

STATUS_KEYS = {fd.SAME: "sync.status_same", fd.LEFT_ONLY: "sync.status_left_only",
               fd.RIGHT_ONLY: "sync.status_right_only", fd.LEFT_NEWER: "sync.status_left_newer",
               fd.RIGHT_NEWER: "sync.status_right_newer", fd.CONFLICT: "sync.status_conflict"}
ACTIONS = (fd.TO_RIGHT, fd.TO_LEFT, fd.DEL_RIGHT, fd.DEL_LEFT, fd.NONE)
BLUE, RED, GREY, ORANGE = "#1d5fa6", "#a33a12", "#7a7a7a", "#b26a00"
GLYPHS = {fd.TO_RIGHT: ("→", BLUE), fd.TO_LEFT: ("←", BLUE), fd.DEL_RIGHT: ("✕", RED), fd.DEL_LEFT: ("✕", RED),
          fd.NONE: ("–", GREY), MIXED: ("•", "#5a5a5a")}
BUTTON_GLYPHS = {fd.TO_RIGHT: "→", fd.TO_LEFT: "←", fd.DEL_RIGHT: "✕▸", fd.DEL_LEFT: "◂✕", fd.NONE: "–"}


def action_text(e: fd.Entry) -> str:
    """Tooltip der Mittelspalte (L-1803)."""
    if e.action == fd.TO_RIGHT:
        text = t("sync.tip_over_right") if fd.overwrites(e) else t("sync.tip_copy_right")
    elif e.action == fd.TO_LEFT:
        text = t("sync.tip_over_left") if fd.overwrites(e) else t("sync.tip_copy_left")
    elif e.action == fd.DEL_RIGHT:
        text = t("sync.tip_del_right")
    elif e.action == fd.DEL_LEFT:
        text = t("sync.tip_del_left")
    else:
        text = t("sync.tip_none")
    if e.status == fd.CONFLICT:
        text = t("sync.status_conflict") + "\n" + text
    return text


def menu_label(action: str) -> str:
    return {fd.TO_RIGHT: t("sync.set_right"), fd.TO_LEFT: t("sync.set_left"), fd.DEL_RIGHT: t("sync.set_del_right"),
            fd.DEL_LEFT: t("sync.set_del_left"), fd.NONE: t("sync.set_none")}[action]


def entry_glyph(e: fd.Entry) -> tuple[str, str]:
    if e.status == fd.CONFLICT and e.action == fd.NONE:
        return "!", ORANGE
    return GLYPHS[e.action]


# --- Darstellung ------------------------------------------------------------------------------------------
class NameDelegate(QStyledItemDelegate):
    """Name mit Einrückung, „+“/„−“ und Symbol – links und rechts gleich (L-1804)."""

    def paint(self, painter: QPainter, option, index) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else None
        from PySide6.QtGui import QIcon

        text, icon = opt.text, QIcon(opt.icon)  # Kopie: opt.icon wird gleich geleert
        opt.text, opt.icon = "", QIcon()
        if style is not None:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        depth = int(index.data(ROLE_DEPTH) or 0)
        tree = opt.widget
        item = tree.itemFromIndex(index) if tree is not None and hasattr(tree, "itemFromIndex") else None
        x = opt.rect.x() + 4 + depth * INDENT
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        color = opt.palette.highlightedText().color() if selected else opt.palette.text().color()
        painter.save()
        painter.setPen(QPen(color))
        if text and item is not None and item.childCount():
            painter.drawText(QRect(x, opt.rect.y(), TOGGLE_W, opt.rect.height()), Qt.AlignmentFlag.AlignCenter,
                             "−" if item.isExpanded() else "+")
        x += TOGGLE_W
        if text:
            size = opt.decorationSize if opt.decorationSize.width() > 0 else QSize(16, 16)
            if not icon.isNull():
                icon.paint(painter, QRect(x, opt.rect.y() + (opt.rect.height() - size.height()) // 2,
                                          size.width(), size.height()))
            x += size.width() + 4
            painter.drawText(QRect(x, opt.rect.y(), opt.rect.right() - x, opt.rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             opt.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, opt.rect.right() - x))
        painter.restore()

    @staticmethod
    def toggle_rect(option_rect: QRect, depth: int) -> QRect:
        return QRect(option_rect.x() + 4 + depth * INDENT, option_rect.y(), TOGGLE_W, option_rect.height())


class ActionDelegate(QStyledItemDelegate):
    """Mittelspalte: nur das Symbol, farbig hinterlegt (L-1803)."""

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.fillRect(option.rect, option.palette.highlight() if selected else QColor("#f1f1f1"))
        painter.setPen(QPen(QColor("#c8c8c8")))
        painter.drawLine(option.rect.topLeft(), option.rect.bottomLeft())
        painter.drawLine(option.rect.topRight(), option.rect.bottomRight())
        data = index.data(ROLE_ICON)
        if data:
            glyph, color = data
            side = min(option.rect.height() - 4, 18)
            r = QRect(option.rect.center().x() - side // 2, option.rect.center().y() - side // 2, side, side)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 70) if selected else QColor(color))
            painter.drawRoundedRect(r, 4, 4)
            font = QFont(option.font)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QPen(QColor("#ffffff")))
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, glyph)
        painter.restore()


class SyncTree(QTreeWidget):
    toggle_clicked = Signal(object)

    def paintEvent(self, event) -> None:
        """Die Mittelspalte zieht sich bis nach unten durch (v1.18.1)."""
        x = self.header().sectionViewportPosition(ACT)
        w = self.header().sectionSize(ACT)
        p = QPainter(self.viewport())
        rect = QRect(x, 0, w, self.viewport().height())
        p.fillRect(rect, QColor("#f1f1f1"))
        p.setPen(QPen(QColor("#c8c8c8")))
        p.drawLine(rect.topLeft(), rect.bottomLeft())
        p.drawLine(rect.topRight(), rect.bottomRight())
        p.end()
        super().paintEvent(event)

    def mousePressEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and index.column() in (L_NAME, R_NAME):
            item = self.itemFromIndex(index)
            rect = NameDelegate.toggle_rect(self.visualRect(index), int(index.data(ROLE_DEPTH) or 0))
            if item is not None and item.childCount() and rect.contains(event.position().toPoint()) \
                    and index.data(Qt.ItemDataRole.DisplayRole):
                item.setExpanded(not item.isExpanded())
                return
        super().mousePressEvent(event)


class SyncView(QWidget):
    """Beide Ordner nebeneinander, Zeilen auf gleicher Höhe, Aktion in der Mitte (L-1802 ff.)."""

    action_clicked = Signal(str)
    paths_changed = Signal()

    def __init__(self, icons=None, parent=None) -> None:
        super().__init__(parent)
        self.icons = icons
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(2)
        self.ed_left, self.ed_right = QLineEdit(self), QLineEdit(self)
        self.btn_left, self.btn_right = QToolButton(self), QToolButton(self)
        for e in (self.ed_left, self.ed_right):
            e.setObjectName("syncPath")
            e.editingFinished.connect(self.paths_changed)
        for b, e in ((self.btn_left, self.ed_left), (self.btn_right, self.ed_right)):
            b.setText("…")
            b.setToolTip(t("sync.pick_folder"))
            b.clicked.connect(lambda _c=False, ed=e: self._pick(ed))
        self.btn_swap = QToolButton(self)
        self.btn_swap.setText("⇄")
        self.btn_swap.setToolTip(t("sync.swap"))
        self.left_box = QWidget(self)
        lb = QHBoxLayout(self.left_box)
        lb.setContentsMargins(0, 0, 0, 0)
        lb.setSpacing(2)
        lb.addWidget(self.ed_left, 1)
        lb.addWidget(self.btn_left)
        self.right_box = QWidget(self)
        rb = QHBoxLayout(self.right_box)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(2)
        rb.addWidget(self.ed_right, 1)
        rb.addWidget(self.btn_right)
        top.addWidget(self.left_box)
        top.addWidget(self.btn_swap)
        top.addWidget(self.right_box, 1)
        lay.addLayout(top)

        self.tree = SyncTree(self)
        self.tree.setColumnCount(7)
        self.tree.setHeaderLabels([t("sync.col_name"), t("sync.col_size"), t("sync.col_modified"), "⇄",
                                   t("sync.col_name"), t("sync.col_size"), t("sync.col_modified")])
        self.tree.headerItem().setToolTip(ACT, t("sync.col_action"))
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setUniformRowHeights(True)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.setExpandsOnDoubleClick(False)
        self.name_delegate = NameDelegate(self.tree)
        self.tree.setItemDelegateForColumn(L_NAME, self.name_delegate)
        self.tree.setItemDelegateForColumn(R_NAME, self.name_delegate)
        self.tree.setItemDelegateForColumn(ACT, ActionDelegate(self.tree))
        head = self.tree.header()
        head.setStretchLastSection(False)
        head.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        head.setSectionsMovable(False)
        head.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.tree.itemExpanded.connect(lambda _i: self.tree.viewport().update())
        self.tree.itemCollapsed.connect(lambda _i: self.tree.viewport().update())
        lay.addWidget(self.tree, 1)

        bottom = QHBoxLayout()  # L-1803: Knöpfe für die markierten Zeilen, unter der Mittelspalte
        bottom.addStretch(1)
        self.buttons: dict[str, QToolButton] = {}
        for action in ACTIONS:
            b = QToolButton(self)
            b.setText(BUTTON_GLYPHS[action])
            b.setToolTip(menu_label(action))
            b.setAccessibleName(menu_label(action))
            b.setMinimumSize(40, 30)
            font = b.font()
            font.setBold(action in (fd.TO_RIGHT, fd.TO_LEFT))
            font.setPointSizeF(font.pointSizeF() * 1.2)
            b.setFont(font)
            color = BLUE if action in (fd.TO_RIGHT, fd.TO_LEFT) else RED if action != fd.NONE else GREY
            b.setStyleSheet(f"QToolButton {{ color: {color}; }}")
            b.clicked.connect(lambda _c=False, a=action: self.action_clicked.emit(a))
            self.buttons[action] = b
            bottom.addWidget(b)
        bottom.addStretch(1)
        lay.addLayout(bottom)
        self.hint = QLabel("", self)
        self.hint.setEnabled(False)
        lay.addWidget(self.hint)

    def _pick(self, edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(None, t("sync.pick_folder"), edit.text() or os.path.expanduser("~"))
        if path:
            edit.setText(path)
            self.paths_changed.emit()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.relayout()

    def relayout(self) -> None:
        """Beide Namensspalten gleich breit; die Pfadzeilen stehen über ihren Spalten."""
        width = self.tree.viewport().width()
        name = max(120, (width - 2 * SIZE_W - 2 * DATE_W - ACT_W) // 2)
        for col, w in ((L_NAME, name), (L_SIZE, SIZE_W), (L_DATE, DATE_W), (ACT, ACT_W), (R_NAME, name),
                       (R_SIZE, SIZE_W), (R_DATE, DATE_W)):
            self.tree.setColumnWidth(col, w)
        frame = self.tree.frameWidth()
        self.left_box.setFixedWidth(name + SIZE_W + DATE_W + frame)
        self.btn_swap.setFixedWidth(ACT_W - 2)


# --- Seitenleiste ------------------------------------------------------------------------------------------
class SyncPane(QWidget):
    """Seitenleiste „Synchronisieren“ (L-1801); steuert die Vergleichsansicht."""

    close_clicked = Signal()

    def __init__(self, window=None, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("syncPane")
        self.window_ = window
        self.settings = getattr(window, "settings", None)
        self.entries: list[fd.Entry] = []
        self.scanned: tuple[str, str] | None = None
        self.view = SyncView(getattr(window, "icons", None))
        self.view.action_clicked.connect(self.set_selected)
        self.view.btn_swap.clicked.connect(self._swap)
        self.view.paths_changed.connect(self._paths_edited)
        self.view.tree.customContextMenuRequested.connect(self._menu)
        self.view.tree.itemDoubleClicked.connect(self._open)
        self.tree = self.view.tree
        self.ed_left, self.ed_right = self.view.ed_left, self.view.ed_right

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        bar = QFrame(self)
        bar.setObjectName("sidebarTitle")
        hb = QHBoxLayout(bar)
        hb.setContentsMargins(4, 1, 1, 1)
        title = QLabel(t("sync.title"), bar)
        title.setObjectName("renameTitle")  # gleiche Titelzeile wie beim Meta-Wizard
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hb.addWidget(title, 1)
        close = QToolButton(bar)
        close.setAutoRaise(True)
        close.setText("✕")
        close.setObjectName("sidebarClose")
        close.setToolTip(t("sync.close"))
        close.clicked.connect(self.close_clicked)
        hb.addWidget(close)
        outer.addWidget(bar)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget(scroll)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        gp = QGroupBox(t("sync.profile").rstrip(":"), body)  # gespeicherte Abgleiche (L-1621)
        gl = QVBoxLayout(gp)
        self.cb_profile = QComboBox(gp)
        gl.addWidget(self.cb_profile)
        # letzter Lauf des gewählten Abgleichs (v1.19, L-1901)
        self.last_row = QWidget(gp)
        lr = QHBoxLayout(self.last_row)
        lr.setContentsMargins(2, 0, 2, 0)
        lr.setSpacing(6)
        self.last_icon = QLabel(self.last_row)
        self.last_text = QLabel(self.last_row)
        lr.addWidget(self.last_icon)
        lr.addWidget(self.last_text, 1)
        self.last_row.hide()
        gl.addWidget(self.last_row)
        row = QHBoxLayout()
        for text, slot in ((t("sync.profile_save"), self.save_profile),
                           (t("sync.profile_rename"), self.rename_profile),
                           (t("sync.profile_delete"), self.delete_profile)):
            b = QPushButton(text, gp)
            b.clicked.connect(slot)
            row.addWidget(b)
        gl.addLayout(row)
        self.btn_ffs = QToolButton(gp)  # v1.17 zusammengefasst (L-1801)
        self.btn_ffs.setText("FreeFileSync")
        self.btn_ffs.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.btn_ffs)
        menu.addAction(t("ffs.import")).triggered.connect(self.import_ffs)
        menu.addAction(t("ffs.export")).triggered.connect(self.export_ffs)
        menu.addAction(t("ffs.export_all")).triggered.connect(self.export_all_ffs)
        self.btn_ffs.setMenu(menu)
        gl.addWidget(self.btn_ffs, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(gp)

        gd = QGroupBox(t("sync.direction"), body)
        dl = QVBoxLayout(gd)
        self.rb_lr = QRadioButton(t("sync.dir_lr"), gd)
        self.rb_rl = QRadioButton(t("sync.dir_rl"), gd)
        self.rb_both = QRadioButton(t("sync.dir_both"), gd)
        self.dir_group = QButtonGroup(self)
        for rb in (self.rb_lr, self.rb_rl, self.rb_both):
            self.dir_group.addButton(rb)
            dl.addWidget(rb)
        lay.addWidget(gd)

        gc = QGroupBox(t("sync.comparison"), body)
        cl = QVBoxLayout(gc)
        self.chk_subdirs = QCheckBox(t("sync.subdirs"), gc)
        self.chk_mirror = QCheckBox(t("sync.mirror"), gc)
        self.chk_mirror.setToolTip(t("sync.mirror_tip"))
        self.chk_dst = QCheckBox(t("sync.dst"), gc)
        self.chk_dst.setToolTip(t("sync.dst_tip"))
        self.chk_content = QCheckBox(t("sync.content"), gc)
        self.chk_content.setToolTip(t("sync.content_tip"))
        self.chk_same = QCheckBox(t("sync.show_same"), gc)
        self.chk_same.toggled.connect(lambda _on: self.fill())
        for w in (self.chk_subdirs, self.chk_mirror, self.chk_dst, self.chk_content, self.chk_same):
            w.setStyleSheet("QCheckBox { spacing: 6px; }")
            cl.addWidget(w)
        lay.addWidget(gc)

        gf = QGroupBox(t("sync.filter"), body)
        fl = QVBoxLayout(gf)
        fl.addWidget(QLabel(t("sync.include"), gf))
        self.ed_include = QLineEdit(gf)
        self.ed_include.setPlaceholderText("*")
        fl.addWidget(self.ed_include)
        fl.addWidget(QLabel(t("sync.exclude"), gf))
        self.ed_exclude = QLineEdit(gf)
        self.ed_exclude.setPlaceholderText("Thumbs.db; .DS_Store; *.tmp")
        fl.addWidget(self.ed_exclude)
        lay.addWidget(gf)

        ga = QGroupBox(t("sync.after"), body)  # L-1630 ff.
        al = QVBoxLayout(ga)
        self.cb_after = QComboBox(ga)
        for kind, key in ((sp.AFTER_NONE, "sync.after_none"), (sp.AFTER_COMMAND, "sync.after_command"),
                          (sp.AFTER_SUSPEND, "sync.after_suspend"), (sp.AFTER_SHUTDOWN, "sync.after_shutdown")):
            self.cb_after.addItem(t(key), kind)
        al.addWidget(self.cb_after)
        crow = QHBoxLayout()
        self.ed_command = QLineEdit(ga)
        self.ed_command.setPlaceholderText(t("sync.command_placeholder"))
        self.ed_command.setToolTip(t("sync.command_tip"))
        crow.addWidget(self.ed_command, 1)
        self.btn_command = QToolButton(ga)
        self.btn_command.setText("…")
        self.btn_command.clicked.connect(self._pick_command)
        crow.addWidget(self.btn_command)
        al.addLayout(crow)
        self.cb_when = QComboBox(ga)
        self.cb_when.addItem(t("sync.when_ok"), sp.WHEN_OK)
        self.cb_when.addItem(t("sync.when_always"), sp.WHEN_ALWAYS)
        al.addWidget(self.cb_when)
        self.cb_after.currentIndexChanged.connect(lambda _i: self._after_changed())
        lay.addWidget(ga)

        lay.addStretch(1)
        foot = QWidget(self)  # immer sichtbar, nicht mitgescrollt
        fl2 = QVBoxLayout(foot)
        fl2.setContentsMargins(8, 4, 8, 8)
        self.summary = QLabel("", foot)
        self.summary.setWordWrap(True)
        self.summary.setObjectName("syncSummary")
        fl2.addWidget(self.summary)
        row = QHBoxLayout()
        self.btn_compare = QPushButton(t("sync.compare"), foot)
        self.btn_compare.clicked.connect(self.compare)
        self.btn_start = QPushButton(t("sync.start"), foot)
        font = self.btn_start.font()
        font.setBold(True)
        self.btn_start.setFont(font)
        self.btn_start.clicked.connect(self.start)
        row.addWidget(self.btn_compare)
        row.addWidget(self.btn_start)
        fl2.addLayout(row)
        self.btn_close = QPushButton(t("button.close"), foot)  # v1.18.2: ✕ und Knopf, wie bei den anderen
        self.btn_close.clicked.connect(self.close_clicked)
        fl2.addWidget(self.btn_close)
        outer.addWidget(foot)

        last = (self.settings.get("sync_last") if self.settings is not None else None) or {}
        self.set_options(fd.Options.from_dict(last.get("options")), sp.After.from_dict(last.get("after")))
        self._fill_profiles(None)
        self.cb_profile.activated.connect(lambda _i: self._load_profile(self.cb_profile.currentData()))
        self.cb_profile.currentIndexChanged.connect(lambda _i: self.show_last_run())
        self._update_buttons()

    # --- Einstellungen ------------------------------------------------------------------------------------
    def set_paths(self, left: str, right: str) -> None:
        self.ed_left.setText(left)
        self.ed_right.setText(right)
        self.entries, self.scanned = [], None
        self.fill()

    def options(self) -> fd.Options:
        direction = fd.RL if self.rb_rl.isChecked() else fd.BOTH if self.rb_both.isChecked() else fd.LR
        return fd.Options(direction, self.chk_subdirs.isChecked(), self.chk_dst.isChecked(),
                          self.chk_content.isChecked(), self.chk_mirror.isChecked(),
                          self.ed_include.text().strip() or "*", self.ed_exclude.text().strip())

    def after(self) -> sp.After:
        return sp.After(self.cb_after.currentData(), self.ed_command.text().strip(), self.cb_when.currentData())

    def set_options(self, o: fd.Options, a: sp.After) -> None:
        {fd.LR: self.rb_lr, fd.RL: self.rb_rl, fd.BOTH: self.rb_both}[o.direction].setChecked(True)
        self.chk_subdirs.setChecked(o.subdirs)
        self.chk_mirror.setChecked(o.mirror)
        self.chk_dst.setChecked(o.dst)
        self.chk_content.setChecked(o.content)
        self.ed_include.setText("" if o.include == "*" else o.include)
        self.ed_exclude.setText(o.exclude)
        self.cb_after.setCurrentIndex(max(self.cb_after.findData(a.kind), 0))
        self.ed_command.setText(a.command)
        self.cb_when.setCurrentIndex(max(self.cb_when.findData(a.when), 0))
        self._after_changed()

    def remember(self) -> None:
        if self.settings is not None:
            self.settings.set("sync_last", {"options": self.options().to_dict(), "after": self.after().to_dict()})

    def _after_changed(self) -> None:
        cmd = self.cb_after.currentData() == sp.AFTER_COMMAND
        self.ed_command.setEnabled(cmd)
        self.btn_command.setEnabled(cmd)
        self.cb_when.setEnabled(self.cb_after.currentData() != sp.AFTER_NONE)

    def _pick_command(self) -> None:
        path, _f = QFileDialog.getOpenFileName(None, t("sync.after_command"), os.path.expanduser("~"))
        if path:
            self.ed_command.setText(f'"{path}"' if " " in path else path)

    def _swap(self) -> None:
        self.set_paths(self.ed_right.text(), self.ed_left.text())

    def _paths_edited(self) -> None:
        if self.scanned is not None and self.scanned != (self.ed_left.text().strip(), self.ed_right.text().strip()):
            self.entries, self.scanned = [], None
            self.fill()

    # --- gespeicherte Abgleiche ---------------------------------------------------------------------------
    def _fill_profiles(self, current: str | None = None) -> None:
        self.cb_profile.clear()
        self.cb_profile.addItem(t("sync.profile_none"), None)
        for p in sp.load():
            self.cb_profile.addItem(p.name, p.name)
        i = self.cb_profile.findData(current) if current else 0
        self.cb_profile.setCurrentIndex(max(i, 0))
        self.show_last_run()

    def show_last_run(self) -> None:
        """L-1901: Haken bzw. Verbotsschild mit Datum unter der Auswahl."""
        from .toolicons import last_run_icon

        name = self.current_profile()
        prof = next((p for p in sp.load() if p.name == name), None) if name else None
        last = prof.last if prof is not None else None
        if last is None:
            self.last_row.hide()
            return
        size = self.fontMetrics().height() + 2
        self.last_icon.setPixmap(last_run_icon(last).pixmap(size, size))
        self.last_text.setText(t("sync.last_run", date=last_run_date(last)))
        tip = last_run_tooltip(last)
        self.last_row.setToolTip(tip)
        self.last_icon.setToolTip(tip)
        self.last_text.setToolTip(tip)
        self.last_row.show()

    def current_profile(self) -> str | None:
        return self.cb_profile.currentData()

    def load_profile(self, name: str | None) -> bool:
        self._fill_profiles(name)
        return self._load_profile(name)

    def _load_profile(self, name: str | None) -> bool:
        if not name:
            return False
        prof = next((p for p in sp.load() if p.name == name), None)
        if prof is None:
            return False
        self.set_options(prof.options, prof.after)
        self.set_paths(prof.left, prof.right)
        return True

    def save_profile(self) -> None:
        name = self.current_profile() or ""
        name, ok = QInputDialog.getText(self, t("sync.profile_save"), t("sync.profile_name"), text=name)
        name = name.strip()
        if not ok or not name:
            return
        sp.put(sp.Profile(name, self.ed_left.text().strip(), self.ed_right.text().strip(), self.options(),
                          self.after()))
        self._fill_profiles(name)

    def rename_profile(self) -> None:
        old = self.current_profile()
        if not old:
            return
        name, ok = QInputDialog.getText(self, t("sync.profile_rename"), t("sync.profile_name"), text=old)
        name = name.strip()
        if not ok or not name or name == old:
            return
        prof = next((p for p in sp.load() if p.name == old), None)
        if prof is None:
            return
        prof.name = name
        sp.put(prof, old_name=old)
        self._fill_profiles(name)

    def delete_profile(self) -> None:
        name = self.current_profile()
        if not name or not confirm(self, t("sync.profile_delete"), t("sync.profile_delete_q", name=name)):
            return
        sp.remove(name)
        self._fill_profiles(None)

    # --- FreeFileSync (v1.17) -----------------------------------------------------------------------------
    def import_ffs(self) -> None:
        from . import ffsconvert as ffs

        paths, _f = QFileDialog.getOpenFileNames(None, t("ffs.import"), os.path.expanduser("~"), t("ffs.filter"))
        if not paths:
            return
        existing = {p.name.lower() for p in sp.load()}
        done, lines, last = [], [], None
        for path in paths:
            name = os.path.basename(path)
            try:
                profiles, notes = ffs.parse(path)
            except ValueError as exc:
                lines.append(f"✕ {name}: {exc}")
                continue
            if not profiles:
                lines.append(f"✕ {name}: {t('ffs.no_pairs')}")
                continue
            for prof in profiles:
                if prof.name.lower() in existing and not confirm(
                        self, t("ffs.import"), t("ffs.replace_q", name=prof.name)):
                    lines.append(f"– {prof.name}: {t('ffs.skipped')}")
                    continue
                sp.put(prof)
                existing.add(prof.name.lower())
                done.append(prof.name)
                last = prof.name
                lines.append(f"✓ {prof.name}")
            lines += [f"    • {n}" for n in notes]
        if last:
            self.load_profile(last)
        show_info(self, t("ffs.import"), t("ffs.import_done", n=len(done)) + "\n\n" + "\n".join(lines))

    def _profile_now(self) -> sp.Profile:
        return sp.Profile(self.current_profile() or "PanePilot", self.ed_left.text().strip(),
                          self.ed_right.text().strip(), self.options(), self.after())

    def export_ffs(self) -> None:
        from . import ffsconvert as ffs

        prof = self._profile_now()
        start = os.path.join(os.path.expanduser("~"), ffs.safe_file_name(prof.name) + ".ffs_gui")
        path, _f = QFileDialog.getSaveFileName(None, t("ffs.export"), start, t("ffs.filter_gui"))
        if not path:
            return
        if not path.lower().endswith(".ffs_gui"):
            path += ".ffs_gui"
        try:
            ffs.save(prof, path)
        except OSError as exc:
            show_error(self, t("ffs.export"), str(exc))
            return
        notes = ffs.export_notes(prof)
        show_info(self, t("ffs.export"), "\n".join([t("ffs.export_done", path=path)] + [f"• {n}" for n in notes]))

    def export_all_ffs(self) -> None:
        from . import ffsconvert as ffs

        profiles = sp.load()
        if not profiles:
            show_info(self, t("ffs.export_all"), t("menu.sync_profiles_none"))
            return
        folder = QFileDialog.getExistingDirectory(None, t("ffs.export_all"), os.path.expanduser("~"))
        if not folder:
            return
        targets = [(p, os.path.join(folder, ffs.safe_file_name(p.name) + ".ffs_gui")) for p in profiles]
        clash = [os.path.basename(path) for _p, path in targets if os.path.exists(path)]
        if clash and not confirm(self, t("ffs.export_all"), t("ffs.overwrite_q", n=len(clash),
                                                               names=", ".join(clash[:5]))):
            return
        errors, notes = [], []
        for prof, path in targets:
            try:
                ffs.save(prof, path)
            except OSError as exc:
                errors.append(f"{prof.name}: {exc}")
            notes += [f"• {prof.name}: {n}" for n in ffs.export_notes(prof)]
        text = t("ffs.export_all_done", n=len(targets) - len(errors), folder=folder)
        (show_error if errors else show_info)(self, t("ffs.export_all"), "\n".join([text] + errors + notes))

    # --- Vergleichen --------------------------------------------------------------------------------------
    def _paths(self) -> tuple[str, str] | None:
        left, right = os.path.expanduser(self.ed_left.text().strip()), os.path.expanduser(self.ed_right.text().strip())
        for p in (left, right):
            if not p or not os.path.isdir(p):
                show_error(self, t("sync.title"), t("sync.no_folder", path=p or "–"))
                return None
        a, b = os.path.realpath(left), os.path.realpath(right)
        if a == b or util.is_inside(a, b) or util.is_inside(b, a):
            show_error(self, t("sync.title"), t("sync.nested"))
            return None
        return left, right

    def compare(self) -> bool:
        from . import netutil

        paths = self._paths()
        if paths is None:
            return False
        opts = self.options()
        self.remember()
        entries, error = netutil.run_blocking(self, lambda: fd.scan(paths[0], paths[1], opts),
                                              t("sync.comparing"), t("sync.title"))
        if error:
            show_error(self, t("sync.title"), error)
            return False
        if entries is None:
            return False
        self.entries, self.scanned = entries, paths
        self.fill()
        return True

    def fill(self) -> None:
        """Baum aufbauen (L-1804): Ordner aus den Pfaden, alles aufgeklappt."""
        tree = self.tree
        tree.clear()
        show_same = self.chk_same.isChecked()
        folders: dict[str, QTreeWidgetItem] = {}
        left, right = self.scanned or ("", "")
        icons = getattr(self.window_, "icons", None)

        def folder(rel: str) -> QTreeWidgetItem | None:
            if not rel:
                return None
            if rel in folders:
                return folders[rel]
            parent_rel = rel.rsplit("/", 1)[0] if "/" in rel else ""
            parent = folder(parent_rel)
            item = QTreeWidgetItem(parent if parent is not None else tree)
            name = rel.rsplit("/", 1)[-1]
            depth = rel.count("/")
            item.setData(L_NAME, ROLE_ENTRY, -1)
            for col in (L_NAME, R_NAME):
                item.setText(col, name)
                item.setData(col, ROLE_DEPTH, depth)
                if icons is not None:
                    item.setIcon(col, icons.folder())
            for col, base in ((L_DATE, left), (R_DATE, right)):
                try:
                    item.setText(col, datetime.fromtimestamp(os.path.getmtime(os.path.join(base, rel)))
                                 .strftime("%d.%m.%Y %H:%M"))
                except OSError:
                    pass
            folders[rel] = item
            return item

        for i, e in enumerate(self.entries):
            if e.status == fd.SAME and not show_same:
                continue
            parent_rel = e.rel.rsplit("/", 1)[0] if "/" in e.rel else ""
            parent = folder(parent_rel)
            item = QTreeWidgetItem(parent if parent is not None else tree)
            item.setData(L_NAME, ROLE_ENTRY, i)
            if e.is_dir:
                folders[e.rel] = item  # v1.18.1: Inhalt hängt darunter
            depth = e.rel.count("/")
            for side, cols, base in ((e.left, (L_NAME, L_SIZE, L_DATE), left), (e.right, (R_NAME, R_SIZE, R_DATE), right)):
                c_name, c_size, c_date = cols
                item.setData(c_name, ROLE_DEPTH, depth)
                if side is None:
                    continue
                item.setText(c_name, e.name)
                if icons is not None:
                    item.setIcon(c_name, icons.folder() if side.is_dir else icons.for_file(os.path.join(base, e.rel)))
                item.setText(c_size, t("sync.n_files", n=side.files) if side.is_dir else util.format_size(side.size))
                item.setTextAlignment(c_size, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                item.setText(c_date, datetime.fromtimestamp(side.mtime).strftime("%d.%m.%Y %H:%M"))
            item.setToolTip(L_NAME, t(STATUS_KEYS[e.status]))
            item.setToolTip(R_NAME, t(STATUS_KEYS[e.status]))
            if e.status == fd.SAME:
                for c in range(7):
                    item.setForeground(c, self.palette().placeholderText())
        tree.collapseAll()  # v1.18.2: zuerst nur die oberste Ebene
        self.refresh_actions()
        self.view.relayout()

    def _entries_under(self, item: QTreeWidgetItem) -> list[fd.Entry]:
        idx = item.data(L_NAME, ROLE_ENTRY)
        out = [self.entries[idx]] if idx is not None and idx >= 0 else []
        for i in range(item.childCount()):
            out += self._entries_under(item.child(i))
        return out

    def refresh_actions(self) -> None:
        """Symbole und Tooltips der Mittelspalte; Ordner zeigen die Aktion ihres Inhalts (L-1804)."""
        def visit(item: QTreeWidgetItem) -> None:
            for i in range(item.childCount()):
                visit(item.child(i))
            entries = self._entries_under(item)
            idx = item.data(L_NAME, ROLE_ENTRY)
            if idx is not None and idx >= 0 and not item.childCount():
                e = entries[0]
                item.setData(ACT, ROLE_ICON, entry_glyph(e))
                item.setToolTip(ACT, action_text(e))
            else:
                acts = {e.action for e in entries}
                if len(acts) == 1:
                    act = acts.pop()
                    item.setData(ACT, ROLE_ICON, GLYPHS[act])
                    item.setToolTip(ACT, t("sync.folder_all", action=menu_label(act)))
                else:
                    item.setData(ACT, ROLE_ICON, GLYPHS[MIXED])
                    item.setToolTip(ACT, t("sync.folder_mixed"))

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            visit(root.child(i))
        self.tree.viewport().update()
        self._update_buttons()

    def selected_entries(self) -> list[fd.Entry]:
        out, seen = [], set()
        for item in self.tree.selectedItems():
            for e in self._entries_under(item):  # L-1805: ein Ordner gilt für alles darin
                if id(e) not in seen:
                    seen.add(id(e))
                    out.append(e)
        return out

    def set_selected(self, action: str) -> None:
        fd.set_action(self.selected_entries(), action)
        self.refresh_actions()

    def _menu(self, pos) -> None:
        """Rechtsklick: Aktionen für die Markierten, „Ordner ausschließen“; im leeren Bereich
        nur „Vergleichen“ und „Synchronisieren“ (v1.18.2)."""
        menu = QMenu(self)
        on_item = self.tree.itemAt(pos) is not None and self.tree.selectedItems()
        if on_item:
            for action in ACTIONS:
                menu.addAction(f"{BUTTON_GLYPHS[action]}  {menu_label(action)}").triggered.connect(
                    lambda _c=False, a=action: self.set_selected(a))
            names = self.selected_folder_names()
            if names:
                menu.addSeparator()
                text = t("sync.exclude_folder", name=names[0]) if len(names) == 1 else \
                    t("sync.exclude_folders", n=len(names))
                menu.addAction(text).triggered.connect(lambda: self.exclude_folders(names))
            menu.addSeparator()
        menu.addAction(t("sync.compare")).triggered.connect(self.compare)
        act = menu.addAction(t("sync.start"))
        act.setEnabled(self.btn_start.isEnabled())
        act.triggered.connect(self.start)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def selected_folder_names(self) -> list[str]:
        out = []
        for item in self.tree.selectedItems():
            idx = item.data(L_NAME, ROLE_ENTRY)
            is_dir = (idx is None or idx < 0) or self.entries[idx].is_dir
            name = item.text(L_NAME) or item.text(R_NAME)
            if is_dir and name and name not in out:
                out.append(name)
        return out

    def exclude_folders(self, names: list[str]) -> None:
        """Ordnernamen unter „Ausschließen“ eintragen und neu vergleichen (v1.18.2)."""
        current = fd.patterns(self.ed_exclude.text())
        low = {c.lower() for c in current}
        current += [n for n in names if n.lower() not in low]
        self.ed_exclude.setText("; ".join(current))
        self.compare()

    def _open(self, item: QTreeWidgetItem, column: int) -> None:
        """L-1807: Doppelklick öffnet die Datei der angeklickten Seite."""
        if self.scanned is None or column == ACT:
            return
        idx = item.data(L_NAME, ROLE_ENTRY)
        if idx is None or idx < 0 or item.childCount() or self.entries[idx].is_dir:
            item.setExpanded(not item.isExpanded())  # Ordner: auf-/zuklappen statt öffnen
            return
        e = self.entries[idx]
        left_side = column < ACT
        side = e.left if left_side else e.right
        if side is None:
            return
        base = self.scanned[0] if left_side else self.scanned[1]
        util.open_with_default_app(os.path.join(base, *e.rel.split("/")))

    def _update_buttons(self) -> None:
        c = fd.summary_counts(self.entries)
        n = c["to_right"] + c["to_left"] + c["delete"]
        self.btn_start.setEnabled(n > 0 and self.scanned is not None)
        for b in self.view.buttons.values():
            b.setEnabled(self.scanned is not None)
        if self.scanned is None:
            self.summary.setText(t("sync.hint_compare"))
        else:
            diff = sum(1 for e in self.entries if e.status != fd.SAME)
            self.summary.setText(t("sync.summary", diff=diff, right=c["to_right"], left=c["to_left"],
                                   delete=c["delete"], conflict=c["conflict"], size=util.format_size(c["bytes"])))

    # --- Starten ------------------------------------------------------------------------------------------
    def start(self) -> None:
        if self.scanned is None:
            return
        left, right = self.scanned
        c = fd.summary_counts(self.entries)
        if not (c["to_right"] + c["to_left"] + c["delete"]):
            return
        text = t("sync.confirm", right=c["to_right"], left=c["to_left"], size=util.format_size(c["bytes"]))
        if c["delete"]:
            text += "\n\n" + t("sync.confirm_delete", n=c["delete"])
        if not confirm(self, t("sync.title"), text):
            return
        self.remember()
        result = self.run(left, right)
        self.finish(left, right, result)

    def run(self, left: str, right: str) -> fd.Result:
        from .fileops import move_to_trash

        cancel = threading.Event()
        entries, opts = self.entries, self.options()

        class Worker(QThread):
            step = Signal(float, float, str)

            def run(self):
                self.result = fd.execute(entries, left, right, opts, move_to_trash,
                                         lambda d, tot, rel: self.step.emit(float(d), float(tot), rel), cancel)

        dlg = QProgressDialog(t("sync.running"), t("button.cancel"), 0, 1000, self)
        dlg.setWindowTitle(t("sync.title"))
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(400)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        worker = Worker()
        worker.step.connect(lambda d, tot, rel: (dlg.setValue(int(1000 * d / max(tot, 1))),
                                                 dlg.setLabelText(t("sync.running_file", name=rel))))
        dlg.canceled.connect(cancel.set)
        loop = QEventLoop()
        worker.finished.connect(loop.quit)
        worker.start()
        if not worker.isFinished():
            loop.exec()
        worker.wait()
        dlg.close()
        return worker.result

    def finish(self, left: str, right: str, result: fd.Result) -> None:
        if self.current_profile():  # L-1900: letzten Lauf merken
            sp.record_run(self.current_profile(), result)
            self.show_last_run()
        lines = [t("sync.done", copied=result.copied, over=result.overwritten, deleted=result.deleted,
                   failed=result.failed)]
        if result.cancelled:
            lines.append(t("sync.cancelled"))
        for rel, msg in result.errors[:15]:
            lines.append(f"• {rel}: {msg}")
        if len(result.errors) > 15:
            lines.append("…")
        after = self.after()
        if after.due(result) and after.kind == sp.AFTER_COMMAND:  # L-1633/L-1634
            from . import netutil

            env = sp.script_env(left, right, result, self.current_profile() or "")
            value, error = netutil.run_blocking(self, lambda: sp.run_command(after.command, env),
                                                t("sync.script_running"), t("sync.title"))
            code, out = value if value else (-1, error or "")
            if code != 0:
                lines.append("")
                lines.append(t("sync.script_failed", code=code))
                if out:
                    lines.append(out)
            else:
                lines.append(t("sync.script_ok"))
        (show_error if result.errors else show_info)(self, t("sync.title"), "\n".join(lines))
        if after.due(result) and after.kind in (sp.AFTER_SUSPEND, sp.AFTER_SHUTDOWN):  # L-1630
            if CountdownDialog(self, after.kind).exec() == QDialog.DialogCode.Accepted:
                problem = sp.power(after.kind)
                if problem:
                    show_error(self, t("sync.title"), t("sync.power_failed", reason=problem))
        self.compare()


def last_run_date(last: sp.LastRun) -> str:
    try:
        return datetime.fromisoformat(last.at).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return last.at


def last_run_tooltip(last: sp.LastRun) -> str:
    """L-1901: Datum, Ergebnis, Zahlen und bei Fehlern die ersten Meldungen."""
    key = {sp.RESULT_OK: "sync.last_ok", sp.RESULT_ERRORS: "sync.last_errors",
           sp.RESULT_CANCELLED: "sync.last_cancelled"}[last.result]
    lines = [t("sync.last_run", date=last_run_date(last)), t(key),
             t("sync.done", copied=last.copied, over=last.overwritten, deleted=last.deleted, failed=last.failed)]
    lines += [f"• {e}" for e in last.errors]
    if last.failed > len(last.errors):
        lines.append("…")
    return "\n".join(lines)


class CountdownDialog(QDialog):
    """30 Sekunden bis zur Bereitschaft bzw. zum Herunterfahren, mit „Abbrechen“ (L-1630)."""

    def __init__(self, parent, kind: str, seconds: int = sp.COUNTDOWN) -> None:
        super().__init__(parent)
        self.kind, self.left = kind, seconds
        self.setWindowTitle(t("sync.title"))
        lay = QVBoxLayout(self)
        self.label = QLabel(self)
        lay.addWidget(self.label)
        box = QDialogButtonBox(self)
        box.addButton(t("sync.countdown_now"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole).setDefault(True)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._show()

    def _show(self) -> None:
        key = "sync.countdown_suspend" if self.kind == sp.AFTER_SUSPEND else "sync.countdown_shutdown"
        self.label.setText(t(key, n=self.left))

    def _tick(self) -> None:
        self.left -= 1
        if self.left <= 0:
            self.timer.stop()
            self.accept()
        else:
            self._show()
