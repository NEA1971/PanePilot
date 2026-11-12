"""Oberfläche für Server (v1.3): Seitenleiste „Server“, Servermanager, Rückfragen und FileZilla-Import."""

from __future__ import annotations

import copy

from PySide6.QtCore import QModelIndex, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QSplitter,
                               QTabWidget, QTreeView, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import remotefs as rf
from . import servers as sv
from .dialogs import free_window
from .i18n import t

ID_ROLE = Qt.ItemDataRole.UserRole + 1  # Server-ID bzw. "" für Ordner
FOLDER = ""


def server_icon(connected: bool) -> QIcon:
    """Kleines Server-Symbol mit Leuchtpunkt (grün = verbunden)."""
    pm = QPixmap(32, 32)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor("#455A64"))
    p.setBrush(QColor("#90A4AE"))
    for y in (4, 13, 22):
        p.drawRoundedRect(QRect(4, y, 22, 7), 2, 2)
    p.setBrush(QColor("#43A047") if connected else QColor("#CFD8DC"))
    p.setPen(QColor("#1B5E20") if connected else QColor("#78909C"))
    p.drawEllipse(QRect(19, 19, 12, 12))
    p.end()
    return QIcon(pm)


# --- Baum-Modell --------------------------------------------------------------------------------------
class ServerModel(QStandardItemModel):
    """Ordner und Server als Baum; Ziehen mit der Maus sortiert um (Server nur in Ordner)."""

    def __init__(self, folder_icon: QIcon, parent=None) -> None:
        super().__init__(parent)
        self.folder_icon = folder_icon
        self.connected: set[str] = set()
        self.store: sv.ServerStore | None = None

    def populate(self, store: sv.ServerStore) -> None:
        self.store = store
        self.clear()

        def add(parent_item, node: sv.Node) -> None:
            for c in node.children:
                item = QStandardItem(c.name)
                item.setEditable(False)
                if c.is_folder:
                    item.setData(FOLDER, ID_ROLE)
                    item.setIcon(self.folder_icon)
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDropEnabled | Qt.ItemFlag.ItemIsDragEnabled)
                    add(item, c)
                else:
                    item.setData(c.server.id, ID_ROLE)
                    item.setFlags((item.flags() | Qt.ItemFlag.ItemIsDragEnabled) & ~Qt.ItemFlag.ItemIsDropEnabled)
                    item.setToolTip(c.server.base_uri() + (f"\n{c.server.comment}" if c.server.comment else ""))
                parent_item.appendRow(item)
        add(self.invisibleRootItem(), store.root)
        self.refresh_states()

    def refresh_states(self) -> None:
        def walk(parent) -> None:
            for r in range(parent.rowCount()):
                item = parent.child(r)
                sid = item.data(ID_ROLE)
                if sid:
                    on = sid in self.connected
                    item.setIcon(server_icon(on))
                    f = item.font()
                    f.setBold(on)
                    item.setFont(f)
                else:
                    walk(item)
        walk(self.invisibleRootItem())

    def to_tree(self) -> sv.Node:
        """Neuen Baum aus der Anzeige bauen (nach Ziehen/Umbenennen)."""
        by_id = {s.id: s for s in self.store.servers()} if self.store else {}

        def build(parent) -> list[sv.Node]:
            nodes = []
            for r in range(parent.rowCount()):
                item = parent.child(r)
                sid = item.data(ID_ROLE)
                if sid:
                    cfg = by_id.get(sid)
                    if cfg is not None:
                        nodes.append(sv.Node(cfg.name, cfg))
                else:
                    nodes.append(sv.Node(item.text(), children=build(item)))
            return nodes
        return sv.Node("", children=build(self.invisibleRootItem()))

    def node_path(self, index: QModelIndex) -> list[int]:
        rows = []
        while index.isValid():
            rows.insert(0, index.row())
            index = index.parent()
        return rows

    def supportedDropActions(self):
        return Qt.DropAction.MoveAction


class ServerView(QTreeView):
    """Seitenleiste „Server“ – Doppelklick verbindet, Rechtsklick zeigt das Kontextmenü."""

    connect_requested = Signal(str)
    focus_entered = Signal()
    dropped = Signal()  # nach dem Umsortieren mit der Maus

    def __init__(self, model: ServerModel, parent=None) -> None:
        super().__init__(parent)
        self.setModel(model)
        self.setHeaderHidden(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.doubleClicked.connect(self._double)
        self.expandAll()
        model.modelReset.connect(self.expandAll)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.focus_entered.emit()

    def _double(self, index: QModelIndex) -> None:
        sid = index.data(ID_ROLE)
        if sid:
            self.connect_requested.emit(sid)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentIndex().data(ID_ROLE):
            self.connect_requested.emit(self.currentIndex().data(ID_ROLE))
            return
        super().keyPressEvent(event)

    def server_at(self, pos: QPoint) -> str | None:
        idx = self.indexAt(pos)
        return idx.data(ID_ROLE) if idx.isValid() else None

    def dropEvent(self, event) -> None:
        # Server und Ordner nur in Ordner oder auf die oberste Ebene ablegen
        idx = self.indexAt(event.position().toPoint())
        pos = self.dropIndicatorPosition()
        if idx.isValid() and idx.data(ID_ROLE) and pos == QAbstractItemView.DropIndicatorPosition.OnItem:
            event.ignore()
            return
        super().dropEvent(event)
        self.expandAll()
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, self.dropped.emit)  # erst wenn Qt die alten Zeilen entfernt hat


# --- Servermanager -----------------------------------------------------------------------------------------
class ServerManagerDialog(QDialog):
    """Links die Serverliste, rechts die Einstellungen des markierten Servers (wie FileZilla)."""

    CONNECT = 2

    def __init__(self, parent, store: sv.ServerStore, folder_icon: QIcon, select_id: str | None = None,
                 new_in_folder: list[int] | None = None) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("srv.manager_title"))
        self.resize(980, 640)
        self.store = store
        self.work = copy.deepcopy(store.root)  # Änderungen erst mit OK/Verbinden übernehmen
        self.passwords: dict[str, str | None] = {}  # neu eingegebene Passwörter (None = löschen)
        self.deleted: list[str] = []
        self.current: rf.ServerConfig | None = None
        self.chosen: str | None = None
        tmp_store = sv.ServerStore.__new__(sv.ServerStore)
        tmp_store.root = self.work
        self.model = ServerModel(folder_icon, self)
        self.model.populate(tmp_store)
        self.tree = ServerView(self.model, self)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.tree.selectionModel().currentChanged.connect(self._on_current)
        self.tree.connect_requested.connect(lambda sid: self._finish(self.CONNECT))
        self.tree.dropped.connect(self._sync_from_model)

        left = QWidget(self)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel(t("srv.choose_entry"), left))
        ll.addWidget(self.tree, 1)
        grid = QGridLayout()
        self.btn_new = QPushButton(t("srv.new_server"), left)
        self.btn_folder = QPushButton(t("srv.new_folder"), left)
        self.btn_rename = QPushButton(t("srv.rename"), left)
        self.btn_delete = QPushButton(t("srv.delete"), left)
        self.btn_copy = QPushButton(t("srv.copy"), left)
        for i, b in enumerate((self.btn_new, self.btn_folder, self.btn_rename, self.btn_delete, self.btn_copy)):
            grid.addWidget(b, i // 2, i % 2)
        ll.addLayout(grid)
        self.btn_new.clicked.connect(self.new_server)
        self.btn_folder.clicked.connect(self.new_folder)
        self.btn_rename.clicked.connect(self.rename_current)
        self.btn_delete.clicked.connect(self.delete_current)
        self.btn_copy.clicked.connect(self.copy_current)

        self.tabs = QTabWidget(self)
        self._build_general()
        self._build_advanced()
        self._build_transfer()
        self._build_charset()
        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.addWidget(left)
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 1)
        split.setSizes([360, 620])

        box = QDialogButtonBox(self)
        self.btn_connect = box.addButton(t("srv.connect"), QDialogButtonBox.ButtonRole.ActionRole)
        box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        self.btn_connect.clicked.connect(lambda: self._finish(self.CONNECT))
        box.accepted.connect(lambda: self._finish(QDialog.DialogCode.Accepted))
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(split, 1)
        lay.addWidget(box)

        if new_in_folder is not None:
            self._select_path(new_in_folder)
            self.new_server()
        elif select_id:
            self._select_id(select_id)
        self._load_form(None if self.current is None else self.current)
        self._update_buttons()

    # Formular -------------------------------------------------------------------------------------------
    def _build_general(self) -> None:
        w = QWidget(self.tabs)
        form = QFormLayout(w)
        self.f_protocol = QComboBox(w)
        self.f_protocol.addItem(t("srv.proto_ftp"), rf.FTP)
        self.f_protocol.addItem(t("srv.proto_sftp"), rf.SFTP)
        self.f_host = QLineEdit(w)
        self.f_port = QSpinBox(w)
        self.f_port.setRange(0, 65535)
        self.f_port.setSpecialValueText(t("srv.port_default"))
        hostrow = QHBoxLayout()
        hostrow.addWidget(self.f_host, 1)
        hostrow.addWidget(QLabel(t("srv.port"), w))
        hostrow.addWidget(self.f_port)
        self.f_encryption = QComboBox(w)
        self.f_encryption.addItem(t("srv.enc_explicit"), rf.ENC_EXPLICIT)
        self.f_encryption.addItem(t("srv.enc_implicit"), rf.ENC_IMPLICIT)
        self.f_encryption.addItem(t("srv.enc_none"), rf.ENC_NONE)
        self.f_logon = QComboBox(w)
        self.f_user = QLineEdit(w)
        self.f_password = QLineEdit(w)
        self.f_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.f_keyfile = QLineEdit(w)
        browse = QPushButton(t("srv.browse"), w)
        browse.clicked.connect(self._browse_key)
        keyrow = QHBoxLayout()
        keyrow.addWidget(self.f_keyfile, 1)
        keyrow.addWidget(browse)
        self.key_widgets = (self.f_keyfile, browse)
        self.f_color = QComboBox(w)
        self.f_color.addItem(t("srv.color_none"), "")
        for name, value in (("srv.color_red", "#FFCDD2"), ("srv.color_green", "#C8E6C9"),
                            ("srv.color_blue", "#BBDEFB"), ("srv.color_yellow", "#FFF9C4"),
                            ("srv.color_cyan", "#B2EBF2"), ("srv.color_magenta", "#E1BEE7"),
                            ("srv.color_orange", "#FFE0B2")):
            self.f_color.addItem(self._color_icon(value), t(name), value)
        self.f_color.addItem(t("srv.color_other"), "*")
        self.f_color.activated.connect(self._color_chosen)
        self.f_comment = QPlainTextEdit(w)
        self.f_comment.setMaximumHeight(90)
        self.keyring_hint = QLabel(t("srv.no_keyring"), w)
        self.keyring_hint.setWordWrap(True)
        self.keyring_hint.setEnabled(False)
        self.keyring_hint.setVisible(not sv.keyring_available())
        form.addRow(t("srv.protocol"), self.f_protocol)
        form.addRow(t("srv.host"), hostrow)
        form.addRow(t("srv.encryption"), self.f_encryption)
        form.addRow(t("srv.logon"), self.f_logon)
        form.addRow(t("srv.user"), self.f_user)
        form.addRow(t("srv.password"), self.f_password)
        form.addRow(t("srv.keyfile"), keyrow)
        form.addRow("", self.keyring_hint)
        form.addRow(t("srv.color"), self.f_color)
        form.addRow(t("srv.comment"), self.f_comment)
        self.general_form = form
        self.f_protocol.currentIndexChanged.connect(self._protocol_changed)
        self.f_logon.currentIndexChanged.connect(self._update_fields)
        self.tabs.addTab(w, t("srv.tab_general"))

    @staticmethod
    def _color_icon(value: str) -> QIcon:
        pm = QPixmap(16, 16)
        pm.fill(QColor(value))
        return QIcon(pm)

    def _color_chosen(self, index: int) -> None:
        if self.f_color.itemData(index) != "*":
            return
        col = QColorDialog.getColor(QColor(self._custom_color or "#FFFFFF"), self, t("srv.color"))
        if col.isValid():
            self._set_color(col.name())
        else:
            self._set_color(self._custom_color or "")

    _custom_color = ""

    def _set_color(self, value: str) -> None:
        i = self.f_color.findData(value)
        if i < 0 and value:
            self._custom_color = value
            j = self.f_color.findData("*")
            self.f_color.setItemIcon(j, self._color_icon(value))
            self.f_color.setItemData(j, "*")
            self.f_color.setCurrentIndex(j)
            return
        self.f_color.setCurrentIndex(max(i, 0))

    def _color_value(self) -> str:
        v = self.f_color.currentData()
        return self._custom_color if v == "*" else (v or "")

    def _build_advanced(self) -> None:
        w = QWidget(self.tabs)
        form = QFormLayout(w)
        self.f_remote_dir = QLineEdit(w)
        self.f_remote_dir.setPlaceholderText(t("srv.remote_dir_hint"))
        self.f_local_dir = QLineEdit(w)
        self.f_local_dir.setPlaceholderText(t("srv.local_dir_hint"))
        browse = QPushButton(t("srv.browse"), w)
        browse.clicked.connect(self._browse_local)
        row = QHBoxLayout()
        row.addWidget(self.f_local_dir, 1)
        row.addWidget(browse)
        form.addRow(t("srv.remote_dir"), self.f_remote_dir)
        form.addRow(t("srv.local_dir"), row)
        self.tabs.addTab(w, t("srv.tab_advanced"))

    def _build_transfer(self) -> None:
        w = QWidget(self.tabs)
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(t("srv.transfer_mode"), w))
        self.f_passive = QRadioButton(t("srv.passive"), w)
        self.f_active = QRadioButton(t("srv.active"), w)
        grp = QButtonGroup(w)
        grp.addButton(self.f_passive)
        grp.addButton(self.f_active)
        lay.addWidget(self.f_passive)
        lay.addWidget(self.f_active)
        hint = QLabel(t("srv.transfer_hint"), w)
        hint.setWordWrap(True)
        hint.setEnabled(False)
        lay.addWidget(hint)
        lay.addStretch(1)
        self.transfer_tab = w
        self.tabs.addTab(w, t("srv.tab_transfer"))

    def _build_charset(self) -> None:
        w = QWidget(self.tabs)
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel(t("srv.charset_intro"), w))
        self.f_cs_auto = QRadioButton(t("srv.charset_auto"), w)
        self.f_cs_utf8 = QRadioButton(t("srv.charset_utf8"), w)
        self.f_cs_custom = QRadioButton(t("srv.charset_custom"), w)
        grp = QButtonGroup(w)
        for b in (self.f_cs_auto, self.f_cs_utf8, self.f_cs_custom):
            grp.addButton(b)
            lay.addWidget(b)
        self.f_cs_name = QLineEdit(w)
        self.f_cs_name.setPlaceholderText("ISO-8859-1")
        row = QHBoxLayout()
        row.addSpacing(24)
        row.addWidget(QLabel(t("srv.charset_name"), w))
        row.addWidget(self.f_cs_name)
        row.addStretch(1)
        lay.addLayout(row)
        hint = QLabel(t("srv.charset_hint"), w)
        hint.setWordWrap(True)
        hint.setEnabled(False)
        lay.addWidget(hint)
        lay.addStretch(1)
        self.f_cs_custom.toggled.connect(self.f_cs_name.setEnabled)
        self.charset_tab = w
        self.tabs.addTab(w, t("srv.tab_charset"))

    def _browse_key(self) -> None:
        import os

        path, _f = QFileDialog.getOpenFileName(self, t("srv.keyfile"), os.path.expanduser("~/.ssh"))
        if path:
            self.f_keyfile.setText(path)

    def _browse_local(self) -> None:
        path = QFileDialog.getExistingDirectory(self, t("srv.local_dir"), self.f_local_dir.text())
        if path:
            self.f_local_dir.setText(path)

    def _protocol_changed(self) -> None:
        self._fill_logon()
        self._update_fields()

    def _fill_logon(self) -> None:
        current = self.f_logon.currentData()
        self.f_logon.blockSignals(True)
        self.f_logon.clear()
        sftp = self.f_protocol.currentData() == rf.SFTP
        options = [(rf.LOGON_NORMAL, "srv.logon_normal"), (rf.LOGON_ASK, "srv.logon_ask")]
        options.insert(0 if not sftp else 2, (rf.LOGON_KEY if sftp else rf.LOGON_ANONYMOUS,
                                              "srv.logon_key" if sftp else "srv.logon_anonymous"))
        for value, key in options:
            self.f_logon.addItem(t(key), value)
        i = self.f_logon.findData(current)
        self.f_logon.setCurrentIndex(i if i >= 0 else self.f_logon.findData(rf.LOGON_NORMAL))
        self.f_logon.blockSignals(False)

    def _update_fields(self) -> None:
        enabled = self.current is not None
        for w in (self.f_protocol, self.f_host, self.f_port, self.f_logon, self.f_color, self.f_comment,
                  self.f_remote_dir, self.f_local_dir):
            w.setEnabled(enabled)
        sftp = self.f_protocol.currentData() == rf.SFTP
        logon = self.f_logon.currentData()
        self.f_encryption.setEnabled(enabled and not sftp)
        self.f_user.setEnabled(enabled and logon != rf.LOGON_ANONYMOUS)
        self.f_password.setEnabled(enabled and logon in (rf.LOGON_NORMAL, rf.LOGON_KEY) and sv.keyring_available())
        self.f_password.setPlaceholderText(t("srv.passphrase_hint") if logon == rf.LOGON_KEY else "")
        for w in self.key_widgets:
            w.setEnabled(enabled and logon == rf.LOGON_KEY)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.transfer_tab), enabled and not sftp)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.charset_tab), enabled and not sftp)

    def _load_form(self, cfg: rf.ServerConfig | None) -> None:
        cfg = cfg or rf.ServerConfig()
        self.f_protocol.setCurrentIndex(max(self.f_protocol.findData(cfg.protocol), 0))
        self._fill_logon()
        self.f_logon.setCurrentIndex(max(self.f_logon.findData(cfg.logon), 0))
        self.f_host.setText(cfg.host)
        self.f_port.setValue(cfg.port)
        self.f_encryption.setCurrentIndex(max(self.f_encryption.findData(cfg.encryption), 0))
        self.f_user.setText(cfg.user)
        self.f_keyfile.setText(cfg.keyfile)
        self.f_password.setText("")
        if self.current is not None:
            pw = self.passwords.get(cfg.id)
            if pw is None and cfg.id not in self.passwords:
                kind = "passphrase" if cfg.logon == rf.LOGON_KEY else "password"
                pw = sv.load_secret(cfg.id, kind)
            self.f_password.setText(pw or "")
        self._password_loaded = self.f_password.text()
        self._custom_color = ""
        self._set_color(cfg.color)
        self.f_comment.setPlainText(cfg.comment)
        self.f_remote_dir.setText(cfg.remote_dir)
        self.f_local_dir.setText(cfg.local_dir)
        (self.f_passive if cfg.passive else self.f_active).setChecked(True)
        {rf.CHARSET_UTF8: self.f_cs_utf8, rf.CHARSET_CUSTOM: self.f_cs_custom}.get(cfg.charset, self.f_cs_auto) \
            .setChecked(True)
        self.f_cs_name.setText(cfg.custom_charset)
        self.f_cs_name.setEnabled(cfg.charset == rf.CHARSET_CUSTOM)
        self._update_fields()

    def _store_form(self) -> None:
        cfg = self.current
        if cfg is None:
            return
        cfg.protocol = self.f_protocol.currentData()
        cfg.host = self.f_host.text().strip()
        cfg.port = self.f_port.value()
        cfg.encryption = self.f_encryption.currentData()
        cfg.logon = self.f_logon.currentData()
        cfg.user = self.f_user.text().strip()
        cfg.keyfile = self.f_keyfile.text().strip()
        cfg.color = self._color_value()
        cfg.comment = self.f_comment.toPlainText()
        cfg.remote_dir = self.f_remote_dir.text().strip()
        cfg.local_dir = self.f_local_dir.text().strip()
        cfg.passive = self.f_passive.isChecked()
        cfg.charset = (rf.CHARSET_UTF8 if self.f_cs_utf8.isChecked() else
                       rf.CHARSET_CUSTOM if self.f_cs_custom.isChecked() else rf.CHARSET_AUTO)
        cfg.custom_charset = self.f_cs_name.text().strip()
        if self.f_password.text() != self._password_loaded:
            self.passwords[cfg.id] = self.f_password.text() or None
            self._password_loaded = self.f_password.text()

    # Baum -----------------------------------------------------------------------------------------------
    def _node_at(self, index: QModelIndex) -> sv.Node | None:
        node = self.work
        for r in self.model.node_path(index):
            if r >= len(node.children):
                return None
            node = node.children[r]
        return node

    def _on_current(self, cur: QModelIndex, _prev=None) -> None:
        self._store_form()
        node = self._node_at(cur) if cur.isValid() else None
        self.current = node.server if node is not None and not node.is_folder else None
        self._load_form(self.current)
        self._update_buttons()

    def _update_buttons(self) -> None:
        cur = self.tree.currentIndex()
        node = self._node_at(cur) if cur.isValid() else None
        has = node is not None
        self.btn_rename.setEnabled(has)
        self.btn_delete.setEnabled(has and (not node.is_folder or not node.children))
        self.btn_copy.setEnabled(has and not node.is_folder)
        self.btn_connect.setEnabled(self.current is not None)

    def _sync_from_model(self) -> None:
        self._store_form()
        self.work.children = self._rebuild_from_model().children

    def _rebuild_from_model(self) -> sv.Node:
        by_id = {}

        def collect(node: sv.Node) -> None:
            for c in node.children:
                if c.is_folder:
                    collect(c)
                else:
                    by_id[c.server.id] = c.server
        collect(self.work)

        def build(parent) -> list[sv.Node]:
            out = []
            for r in range(parent.rowCount()):
                item = parent.child(r)
                sid = item.data(ID_ROLE)
                if sid:
                    if sid in by_id:
                        out.append(sv.Node(by_id[sid].name, by_id[sid]))
                else:
                    out.append(sv.Node(item.text(), children=build(item)))
            return out
        return sv.Node("", children=build(self.model.invisibleRootItem()))

    def _repopulate(self, select_id: str | None = None, select_path: list[int] | None = None) -> None:
        tmp = sv.ServerStore.__new__(sv.ServerStore)
        tmp.root = self.work
        self.tree.selectionModel().blockSignals(True)
        self.model.populate(tmp)
        self.tree.expandAll()
        self.tree.selectionModel().blockSignals(False)
        if select_id:
            self._select_id(select_id)
        elif select_path is not None:
            self._select_path(select_path)
        else:
            self.current = None
            self._load_form(None)
        self._update_buttons()

    def _select_index(self, idx: QModelIndex) -> None:
        if idx.isValid():
            self.tree.setCurrentIndex(idx)
            node = self._node_at(idx)
            self.current = node.server if node is not None and not node.is_folder else None
            self._load_form(self.current)

    def _select_id(self, sid: str) -> None:
        hits = self.model.match(self.model.index(0, 0), ID_ROLE, sid, 1,
                                Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive)
        if hits:
            self._select_index(hits[0])

    def _select_path(self, rows: list[int]) -> None:
        idx = QModelIndex()
        for r in rows:
            idx = self.model.index(r, 0, idx)
        self._select_index(idx)

    def _target_folder(self) -> tuple[sv.Node, list[int]]:
        cur = self.tree.currentIndex()
        if not cur.isValid():
            return self.work, []
        node = self._node_at(cur)
        path = self.model.node_path(cur)
        if node is not None and node.is_folder:
            return node, path
        parent_path = path[:-1]
        parent = self.work
        for r in parent_path:
            parent = parent.children[r]
        return parent, parent_path

    def new_server(self) -> None:
        self._store_form()
        folder, path = self._target_folder()
        tmp = sv.ServerStore.__new__(sv.ServerStore)
        tmp.root = self.work
        cfg = rf.ServerConfig(name=tmp.unique_name(folder, t("srv.new_server_name")))
        folder.children.append(sv.Node(cfg.name, cfg))
        self._repopulate(select_id=cfg.id)
        self.tabs.setCurrentIndex(0)
        self.rename_current()

    def new_folder(self) -> None:
        from .dialogs import ask_text

        self._store_form()
        folder, path = self._target_folder()
        name = ask_text(self, t("srv.new_folder"), t("srv.folder_name"), t("srv.new_folder_name"))
        if not name:
            return
        folder.children.append(sv.Node(name.strip()))
        self._repopulate(select_path=path + [len(folder.children) - 1])

    def rename_current(self) -> None:
        from .dialogs import ask_text

        cur = self.tree.currentIndex()
        node = self._node_at(cur) if cur.isValid() else None
        if node is None:
            return
        self._store_form()
        name = ask_text(self, t("srv.rename"), t("srv.new_name"), node.name)
        if not name or not name.strip():
            return
        node.name = name.strip()
        if node.server is not None:
            node.server.name = node.name
        self.model.itemFromIndex(cur).setText(node.name)

    def delete_current(self) -> None:
        from .dialogs import confirm

        cur = self.tree.currentIndex()
        node = self._node_at(cur) if cur.isValid() else None
        if node is None or (node.is_folder and node.children):
            return
        if not confirm(self, t("srv.delete"), t("srv.delete_confirm", name=node.name), yes_key="button.delete",
                       default_yes=False):
            return
        parent, _p = self._parent_of(cur)
        parent.children.remove(node)
        if node.server is not None:
            self.deleted.append(node.server.id)
        self.current = None
        self._repopulate()

    def _parent_of(self, index: QModelIndex) -> tuple[sv.Node, list[int]]:
        path = self.model.node_path(index)[:-1]
        node = self.work
        for r in path:
            node = node.children[r]
        return node, path

    def copy_current(self) -> None:
        cur = self.tree.currentIndex()
        node = self._node_at(cur) if cur.isValid() else None
        if node is None or node.is_folder:
            return
        self._store_form()
        import uuid

        parent, _p = self._parent_of(cur)
        tmp = sv.ServerStore.__new__(sv.ServerStore)
        tmp.root = self.work
        cfg = node.server.copy(id=uuid.uuid4().hex, name=tmp.unique_name(parent, node.server.name))
        parent.children.insert(parent.children.index(node) + 1, sv.Node(cfg.name, cfg))
        pw = self.passwords.get(node.server.id)
        if pw is None and node.server.id not in self.passwords:
            pw = sv.load_secret(node.server.id, "passphrase" if node.server.logon == rf.LOGON_KEY else "password")
        if pw:
            self.passwords[cfg.id] = pw
        self._repopulate(select_id=cfg.id)

    # Abschluss -------------------------------------------------------------------------------------------
    def _finish(self, code) -> None:
        self._store_form()
        self.chosen = self.current.id if self.current is not None else None
        self.apply()
        self.done(code)

    def apply(self) -> None:
        """Arbeitskopie übernehmen und Passwörter speichern."""
        self.store.root = self.work
        self.store.save()
        by_id = {s.id: s for s in self.store.servers()}
        for sid, pw in self.passwords.items():
            cfg = by_id.get(sid)
            if cfg is None:
                continue
            kind = "passphrase" if cfg.logon == rf.LOGON_KEY else "password"
            if pw:
                sv.store_secret(sid, pw, cfg.name, kind)
            else:
                sv.delete_secret(sid)
        for sid in self.deleted:
            if sid not in by_id:
                sv.delete_secret(sid)


# --- Rückfragen ---------------------------------------------------------------------------------------
class PasswordDialog(QDialog):
    def __init__(self, parent, cfg: rf.ServerConfig, passphrase: bool, offer_save: bool) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("srv.password_title"))
        lay = QVBoxLayout(self)
        text = t("srv.passphrase_for", name=cfg.name, file=cfg.keyfile) if passphrase else \
            t("srv.password_for", name=cfg.name, user=cfg.user or "–", host=cfg.host)
        label = QLabel(text, self)
        label.setWordWrap(True)
        lay.addWidget(label)
        self.edit = QLineEdit(self)
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        lay.addWidget(self.edit)
        self.save = QCheckBox(t("srv.save_password"), self)
        self.save.setChecked(True)
        self.save.setVisible(offer_save and sv.keyring_available())
        lay.addWidget(self.save)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        box.button(QDialogButtonBox.StandardButton.Ok).setText(t("button.ok"))
        box.button(QDialogButtonBox.StandardButton.Cancel).setText(t("button.cancel"))
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.setMinimumWidth(420)


def confirm_host_key(parent, err) -> bool:
    """Fingerabdruck bestätigen (SFTP-Schlüssel oder TLS-Zertifikat)."""
    from .dialogs import confirm

    if isinstance(err, rf.UnknownHostKey):
        key = "srv.hostkey_changed" if err.changed else "srv.hostkey_new"
        text = t(key, host=err.host, type=err.key_type, fp=err.fingerprint)
    else:
        key = "srv.cert_changed" if err.changed else "srv.cert_new"
        text = t(key, host=err.host, fp=err.fingerprint)
    return confirm(parent, t("srv.security_title"), text, yes_key="srv.trust", default_yes=not err.changed,
                   warning=err.changed)


# --- FileZilla-Import ----------------------------------------------------------------------------------
class ImportDialog(QDialog):
    def __init__(self, parent, items: list[sv.ImportedServer], folder_icon: QIcon) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("srv.import_title"))
        self.resize(560, 480)
        self.items = items
        lay = QVBoxLayout(self)
        info = QLabel(t("srv.import_info", n=len(items)), self)
        info.setWordWrap(True)
        lay.addWidget(info)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels([t("srv.import_col_name"), t("srv.import_col_server")])
        folders: dict[tuple, QTreeWidgetItem] = {}
        self.checks: list[tuple[QTreeWidgetItem, sv.ImportedServer]] = []
        for imp in items:
            parent = self.tree.invisibleRootItem()
            for i in range(len(imp.folder)):
                key = tuple(imp.folder[: i + 1])
                if key not in folders:
                    f = QTreeWidgetItem([imp.folder[i], ""])
                    f.setIcon(0, folder_icon)
                    f.setFlags(f.flags() | Qt.ItemFlag.ItemIsAutoTristate | Qt.ItemFlag.ItemIsUserCheckable)
                    f.setCheckState(0, Qt.CheckState.Checked)
                    parent.addChild(f)
                    folders[key] = f
                parent = folders[key]
            it = QTreeWidgetItem([imp.cfg.name, imp.cfg.base_uri()])
            it.setIcon(0, server_icon(False))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked)
            parent.addChild(it)
            self.checks.append((it, imp))
        self.tree.expandAll()
        self.tree.resizeColumnToContents(0)
        lay.addWidget(self.tree, 1)
        hint = QLabel(t("srv.import_hint") if sv.keyring_available() else t("srv.import_no_keyring"), self)
        hint.setWordWrap(True)
        hint.setEnabled(False)
        lay.addWidget(hint)
        box = QDialogButtonBox(self)
        box.addButton(t("srv.import_button"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

    def selected(self) -> list[sv.ImportedServer]:
        return [imp for it, imp in self.checks if it.checkState(0) == Qt.CheckState.Checked]


def bold_font(font: QFont) -> QFont:
    f = QFont(font)
    f.setBold(True)
    return f
