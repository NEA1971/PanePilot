"""Dialog „Eigenschaften“ (F-870 ff.)."""

from __future__ import annotations

import os
import stat
from datetime import datetime

from PySide6.QtCore import QMimeDatabase, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QStyledItemDelegate,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .dialogs import free_window
from .filemodel import group_name, owner_name
from .i18n import t
from .util import format_size

# Stufen je Gruppe (F-872): Bits für Lesen/Schreiben; „x“ bei Ordnern = Inhalt betreten
LEVEL_NONE, LEVEL_READ, LEVEL_WRITE = 0, 1, 2


def level_of(mode: int, shift: int, is_dir: bool) -> int:
    r = mode & (4 << shift)
    w = mode & (2 << shift)
    if is_dir:
        x = mode & (1 << shift)
        if r and x and w:
            return LEVEL_WRITE
        return LEVEL_READ if r else LEVEL_NONE
    if r and w:
        return LEVEL_WRITE
    return LEVEL_READ if r else LEVEL_NONE


def apply_level(mode: int, shift: int, level: int, is_dir: bool) -> int:
    mask = 7 << shift
    mode &= ~mask
    if level == LEVEL_READ:
        mode |= (4 | (1 if is_dir else 0)) << shift
    elif level == LEVEL_WRITE:
        mode |= (6 | (1 if is_dir else 0)) << shift
    return mode


def mode_text(mode: int) -> str:
    """0o644 → '644 (rw-r--r--)'."""
    perms = mode & 0o7777
    sym = stat.filemode(mode)[1:]
    return f"{perms & 0o777:o} ({sym})" if perms <= 0o777 else f"{perms:o} ({sym})"


def _fmt_time(ts: float | None) -> str:
    if ts is None or ts < 0:
        return t("props.unknown")
    return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M:%S")


class FolderSizeThread(QThread):
    progress = Signal(int, int, int)  # Bytes, Dateien, Ordner
    done = Signal(int, int, int)

    def __init__(self, paths: list[str], parent=None) -> None:
        super().__init__(parent)
        self.paths = paths
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        size = files = dirs = 0
        count = 0
        for p in self.paths:
            if self._stop:
                return
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if not stat.S_ISDIR(st.st_mode):
                size += st.st_size
                files += 1
                continue
            for root, dnames, fnames in os.walk(p, onerror=lambda e: None):
                if self._stop:
                    return
                dirs += len(dnames)
                for f in fnames:
                    try:
                        size += os.lstat(os.path.join(root, f)).st_size
                    except OSError:
                        pass
                    files += 1
                    count += 1
                    if count % 500 == 0:
                        self.progress.emit(size, files, dirs)
        self.done.emit(size, files, dirs)


class _WrapDelegate(QStyledItemDelegate):
    """Umbruch auch mitten im Wort – lange Werte ohne Leerzeichen (E-Mail-Listen, Kennungen) bleiben lesbar."""

    PAD = 4

    def _doc(self, option, index, width: int):
        from PySide6.QtGui import QTextDocument, QTextOption

        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        doc.setDefaultTextOption(opt)
        doc.setDocumentMargin(0)
        doc.setPlainText(index.data() or "")
        doc.setTextWidth(max(10, width - 2 * self.PAD))
        return doc

    def paint(self, painter, option, index) -> None:
        from PySide6.QtGui import QAbstractTextDocumentLayout, QPalette
        from PySide6.QtWidgets import QStyle, QStyleOptionViewItem

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        doc = self._doc(option, index, option.rect.width())
        ctx = QAbstractTextDocumentLayout.PaintContext()
        role = QPalette.ColorRole.HighlightedText if option.state & QStyle.StateFlag.State_Selected \
            else QPalette.ColorRole.Text
        ctx.palette.setColor(QPalette.ColorRole.Text, option.palette.color(role))
        painter.save()
        painter.translate(option.rect.left() + self.PAD, option.rect.top() + 2)
        painter.setClipRect(0, 0, option.rect.width() - self.PAD, option.rect.height())
        doc.documentLayout().draw(painter, ctx)
        painter.restore()

    def sizeHint(self, option, index):
        from PySide6.QtCore import QSize

        view = option.widget
        width = view.columnWidth(index.column()) if view is not None else option.rect.width()
        doc = self._doc(option, index, width)
        return QSize(int(doc.idealWidth()) + 2 * self.PAD, int(doc.size().height()) + 4)


class MetaTable(QTableWidget):
    """Metadaten als Tabelle „Feld | Wert“ (v1.8.1): Spaltenbreite per Maus, wird gemerkt;
    Doppelklick auf die Trennlinie passt sie an den längsten Feldnamen an."""

    SETTING = "props_meta_field_width"

    def __init__(self, parent, settings=None) -> None:
        super().__init__(0, 2, parent)
        from PySide6.QtWidgets import QAbstractItemView, QHeaderView

        self.settings = settings
        self.setHorizontalHeaderLabels([t("props.meta_field"), t("props.meta_value")])
        self.verticalHeader().hide()
        self.setAlternatingRowColors(True)
        self.setWordWrap(True)
        self.setItemDelegate(_WrapDelegate(self))
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        head = self.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        head.setStretchLastSection(True)
        head.setHighlightSections(False)
        head.sectionResized.connect(self._resized)
        head.sectionHandleDoubleClicked.connect(self._fit)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self._ready = False

    def add_row(self, label: str, value: str) -> None:
        from PySide6.QtWidgets import QTableWidgetItem

        r = self.rowCount()
        self.insertRow(r)
        key = QTableWidgetItem(label)
        key.setTextAlignment(int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop))
        val = QTableWidgetItem(value)
        val.setTextAlignment(int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop))
        val.setToolTip(value)
        self.setItem(r, 0, key)
        self.setItem(r, 1, val)

    def finish(self) -> None:
        width = 0
        if self.settings is not None:
            try:
                width = int(self.settings.get(self.SETTING) or 0)
            except (TypeError, ValueError):
                width = 0
        if width > 20:
            self.setColumnWidth(0, width)
        else:  # automatisch, aber höchstens 260 Pixel – sehr lange Feldnamen werden umgebrochen
            self.setColumnWidth(0, min(self._fit_width(), self.AUTO_MAX))
        self.resizeRowsToContents()
        self._ready = True

    def rows(self) -> list[tuple[str, str]]:
        return [(self.item(r, 0).text(), self.item(r, 1).text()) for r in range(self.rowCount())]

    AUTO_MAX = 260

    def _fit_width(self) -> int:
        fm = self.fontMetrics()
        texts = [self.item(r, 0).text() for r in range(self.rowCount())] + [t("props.meta_field")]
        return max(fm.horizontalAdvance(x) for x in texts) + 2 * _WrapDelegate.PAD + 8

    def _fit(self, section: int) -> None:
        if section == 0:
            self.setColumnWidth(0, self._fit_width())

    def _resized(self, section: int, _old: int, new: int) -> None:
        self.resizeRowsToContents()
        if section == 0 and self._ready and self.settings is not None:
            self._width = int(new)
            if not hasattr(self, "_save_timer"):
                from PySide6.QtCore import QTimer

                self._save_timer = QTimer(self)
                self._save_timer.setSingleShot(True)
                self._save_timer.setInterval(400)
                self._save_timer.timeout.connect(self.save_width)
            self._save_timer.start()

    def save_width(self) -> None:
        if self.settings is not None and getattr(self, "_width", 0):
            self.settings.set(self.SETTING, self._width)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.resizeRowsToContents()  # Umbruch an die neue Breite anpassen

    def _selected(self) -> list[int]:
        return sorted({i.row() for i in self.selectedIndexes()})

    def copy_values(self) -> None:
        rows = self._selected()
        if rows:
            QApplication.clipboard().setText("\n".join(self.item(r, 1).text() for r in rows))

    def copy_rows(self) -> None:
        rows = self._selected()
        if rows:
            QApplication.clipboard().setText("\n".join(f"{self.item(r, 0).text()}: {self.item(r, 1).text()}"
                                                       for r in rows))

    def keyPressEvent(self, event) -> None:
        from PySide6.QtGui import QKeySequence

        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_values()
            return
        super().keyPressEvent(event)

    def _menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        if self.itemAt(pos) is not None and not self.itemAt(pos).isSelected():
            self.selectRow(self.itemAt(pos).row())
        if not self._selected():
            return
        menu = QMenu(self)
        menu.addAction(t("props.copy_value")).triggered.connect(self.copy_values)
        menu.addAction(t("props.copy_row")).triggered.connect(self.copy_rows)
        menu.exec(self.viewport().mapToGlobal(pos))


class PropertiesDialog(QDialog):
    def _meta_tab(self) -> tuple[QWidget, bool]:
        """Reiter „Metadaten“ (F-950): Tags und technische Infos einer Musik-, Foto- oder Videodatei (v1.5),
        nur zur Anzeige."""
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QPushButton

        from . import metaprofile as mp
        from . import phototags as ph
        from . import doctags as dc
        from . import tags as tg
        from . import videotags as vt
        from .metawizard import doc_hint, picture_info

        w = QWidget(self)
        kind = mp.kind_of(self.paths[0]) if len(self.paths) == 1 else None
        if kind is None or not os.path.isfile(self.paths[0]):
            return w, False
        rec = tg.read_file(self.paths[0])
        if rec.error:
            QVBoxLayout(w).addWidget(QLabel(t("meta.read_error", reason=rec.error), w))
            return w, True
        table = MetaTable(w, getattr(self.parent(), "settings", None))
        self.meta_table = table
        below = QWidget(w)  # Vorschau, Hinweise und Kartenlink unter der Tabelle (v1.8.1)
        form = QFormLayout(below)
        form.setContentsMargins(0, 4, 0, 0)

        def row(label: str, value: str) -> None:
            if value:
                table.add_row(label, value)

        def image(label: str, pm: QPixmap, info: str = "") -> None:
            if pm.isNull():
                return
            img = QLabel(below)
            img.setPixmap(pm.scaled(160, 160, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))
            form.addRow(label + ":", img)
            if info:
                form.addRow("", QLabel(info, below))

        fields = {mp.AUDIO: tg.FIELDS, mp.PHOTO: ph.FIELDS, mp.VIDEO: vt.FIELDS, mp.DOC: dc.FIELDS}[kind]
        for key in fields:
            if rec.fields.get(key):
                row(t(f"meta.field.{key}"), rec.fields[key])
        for key in sorted((k for k in rec.fields if k.startswith(tg.EXTRA)), key=lambda k: rec.labels.get(k, k).casefold()):
            row(rec.labels.get(key, key), rec.fields[key])
        if kind == mp.AUDIO:
            row(t("meta.info.codec"), rec.codec)
            if rec.length:
                row(t("meta.info.length"), tg.format_length(rec.length))
            if rec.bitrate:
                row(t("meta.info.bitrate"), f"{round(rec.bitrate / 1000)} kbit/s")
            if rec.sample_rate:
                row(t("meta.info.samplerate"), f"{rec.sample_rate} Hz")
        elif kind == mp.DOC:  # v1.8 (L-860)
            row(t("meta.info.format"), rec.codec)
            hint = doc_hint([rec])
            if hint:
                form.addRow("", QLabel(hint, below))
        elif kind == mp.PHOTO:
            row(t("meta.info.format"), rec.codec)
            if rec.width:
                row(t("meta.info.dims"), f"{rec.width} × {rec.height}")
        else:
            row(t("meta.info.format"), rec.codec)
            if rec.length:
                row(t("meta.info.duration"), tg.format_length(rec.length))
            if rec.width:
                row(t("meta.info.resolution"), f"{rec.width} × {rec.height}")
            row(t("meta.info.fps"), vt.format_fps(rec.fps))
            row(t("meta.info.vcodec"), rec.vcodec)
            row(t("meta.info.acodec"), rec.acodec)
            from .tracks import tooltip  # v1.7 (L-720)

            row(t("meta.info.audio"), tooltip(rec.audio_tracks))
            row(t("meta.info.subs"), tooltip(rec.sub_tracks))
            if rec.bitrate:
                row(t("meta.info.bitrate"), f"{round(rec.bitrate / 1000)} kbit/s")
        if kind == mp.DOC:
            data = dc.preview(rec, 320)
            if data:
                pm = QPixmap()
                pm.loadFromData(QByteArray(data))
                image(t("photo.preview"), pm)
        elif kind != mp.PHOTO:
            cover = rec.front_cover()
            label = t("video.poster") if kind == mp.VIDEO else t("meta.field.cover")
            if cover is not None:
                pm = QPixmap()
                pm.loadFromData(QByteArray(cover.data))
                image(label, pm, picture_info(cover))
            elif kind == mp.VIDEO:  # Standbild, wenn das Video kein eigenes Vorschaubild hat (L-522)
                data = vt.grab_frame(rec.path, rec.length, 320)
                if data:
                    pm = QPixmap()
                    pm.loadFromData(QByteArray(data))
                    image(label, pm, t("video.frame_info"))
        else:
            img = ph.preview(rec.path, 160)
            if img is not None:
                image(t("photo.preview"), QPixmap.fromImage(img))
        url = ph.map_url(rec) if kind not in (mp.AUDIO, mp.DOC) else None
        if url:
            link = QLabel(f'<a href="{url}">{t("photo.show_map")}</a>', below)
            link.setOpenExternalLinks(True)
            form.addRow("", link)
        table.finish()
        btn = QPushButton(t("props.meta_edit"), w)
        btn.setEnabled(not self.read_only)
        btn.clicked.connect(self._edit_in_meta)
        lay = QVBoxLayout(w)
        lay.addWidget(table, 1)
        if form.rowCount():
            lay.addWidget(below, 0)
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignRight)
        return w, True

    def meta_texts(self) -> list[str]:
        """Alle Texte des Reiters „Metadaten“ (Feldnamen, Werte, Hinweise) – für Tests."""
        out: list[str] = []
        table = getattr(self, "meta_table", None)
        if table is not None:
            for k, v in table.rows():
                out += [k, v]
        out += [w.text() for w in self.tabs.widget(2).findChildren(QLabel)]
        return out

    def _edit_in_meta(self) -> None:
        self.edit_in_meta = True
        self.accept()

    def __init__(self, parent, paths: list[str], read_only: bool = False) -> None:
        super().__init__(parent)
        free_window(self)
        self.paths = paths
        self.read_only = read_only
        self.setMinimumWidth(520)
        name = os.path.basename(paths[0].rstrip(os.sep)) or paths[0]
        self.setWindowTitle(t("props.title", name=name) if len(paths) == 1 else t("props.title_many", n=len(paths)))
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._info_tab(), t("props.tab_info"))
        self.tabs.addTab(self._perm_tab(), t("props.tab_perm"))
        self.edit_in_meta = False  # „Im Meta-Wizard bearbeiten“ gewählt (F-950)
        meta, has_meta = self._meta_tab()
        self.tabs.addTab(meta, t("props.tab_meta"))
        self.tabs.setTabEnabled(2, has_meta)
        if read_only:
            self.tabs.setTabEnabled(1, False)
        box = QDialogButtonBox(self)
        self.apply_button = box.addButton(t("props.apply"), QDialogButtonBox.ButtonRole.ApplyRole)
        close = box.addButton(t("button.close"), QDialogButtonBox.ButtonRole.RejectRole)
        close.setDefault(True)
        self.apply_button.clicked.connect(self.apply_permissions)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(box)
        self.apply_button.setEnabled(False)
        self._thread: FolderSizeThread | None = None
        self._start_size()

    # --- Dateiinfo ---------------------------------------------------------------------
    def _info_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)
        self.size_label = QLabel(w)
        self.count_label = QLabel(w)
        if len(self.paths) == 1:
            p = self.paths[0]
            try:
                st = os.stat(p)
            except OSError:
                st = os.lstat(p)
            is_dir = stat.S_ISDIR(st.st_mode)
            mime = QMimeDatabase().mimeTypeForFile(p)
            kind = t("props.kind_folder") if is_dir else f"{mime.comment()} ({mime.name()})"
            if os.path.islink(p):
                kind += "  " + t("props.link_to", target=os.readlink(p))
            from .filemodel import birth_time_of

            rows = [
                ("props.name", os.path.basename(p.rstrip(os.sep)) or p),
                ("props.kind", kind),
                ("props.size", None),
                ("props.path", os.path.dirname(p.rstrip(os.sep)) or os.sep),
                ("props.created", _fmt_time(birth_time_of(p))),
                ("props.accessed", _fmt_time(st.st_atime)),
                ("props.modified", _fmt_time(st.st_mtime)),
            ]
            for key, value in rows:
                if key == "props.size":
                    form.addRow(t(key), self.size_label)
                    if is_dir:
                        form.addRow(t("props.contents"), self.count_label)
                    continue
                label = QLabel(value, w)
                label.setWordWrap(True)
                label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                form.addRow(t(key), label)
            if not is_dir:
                self.size_label.setText(t("props.size_value", human=format_size(st.st_size, "auto"),
                                          bytes=f"{st.st_size:,}".replace(",", ".")))
        else:
            form.addRow(t("props.selection"), QLabel(t("props.n_items", n=len(self.paths)), w))
            form.addRow(t("props.size"), self.size_label)
            form.addRow(t("props.contents"), self.count_label)
            form.addRow(t("props.path"), QLabel(os.path.dirname(self.paths[0].rstrip(os.sep)), w))
        return w

    def _start_size(self) -> None:
        if len(self.paths) == 1 and not os.path.isdir(self.paths[0]):
            return
        self.size_label.setText(t("props.calculating"))
        self._thread = FolderSizeThread(self.paths, self)
        self._thread.progress.connect(self._show_size)
        self._thread.done.connect(lambda s, f, d: self._show_size(s, f, d, True))
        self._thread.start()

    def _show_size(self, size: int, files: int, dirs: int, final: bool = False) -> None:
        text = t("props.size_value", human=format_size(size, "auto"), bytes=f"{size:,}".replace(",", "."))
        self.size_label.setText(text + ("" if final else " …"))
        self.count_label.setText(t("props.counts", files=files, dirs=dirs))

    # --- Berechtigungen ----------------------------------------------------------------
    def _perm_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)
        try:
            st = os.lstat(self.paths[0])
        except OSError:
            form.addRow(QLabel(t("props.no_access"), w))
            self._mode = None
            return w
        self._mode = st.st_mode
        self._is_dir = all(os.path.isdir(p) for p in self.paths)
        same_owner = len({os.lstat(p).st_uid for p in self.paths if os.path.lexists(p)}) == 1
        same_group = len({os.lstat(p).st_gid for p in self.paths if os.path.lexists(p)}) == 1
        owner = f"{owner_name(st.st_uid)} ({st.st_uid})" if same_owner else t("props.mixed")
        group = f"{group_name(st.st_gid)} ({st.st_gid})" if same_group else t("props.mixed")
        form.addRow(t("props.owner"), QLabel(owner, w))
        form.addRow(t("props.group"), QLabel(group, w))
        levels = ("props.lvl_dir_none", "props.lvl_dir_read", "props.lvl_dir_write") if self._is_dir else \
            ("props.lvl_none", "props.lvl_read", "props.lvl_write")
        self.level_boxes: dict[int, QComboBox] = {}
        for shift, key in ((6, "props.perm_owner"), (3, "props.perm_group"), (0, "props.perm_other")):
            box = QComboBox(w)
            for lvl, lkey in enumerate(levels):
                box.addItem(t(lkey), lvl)
            box.setCurrentIndex(level_of(st.st_mode, shift, self._is_dir))
            box.currentIndexChanged.connect(self._perm_changed)
            self.level_boxes[shift] = box
            form.addRow(t(key), box)
        self.exec_box = QCheckBox(t("props.executable"), w)
        self.exec_box.setChecked(bool(st.st_mode & stat.S_IXUSR))
        self.exec_box.setVisible(not self._is_dir)
        self.exec_box.toggled.connect(self._perm_changed)
        form.addRow("", self.exec_box)
        self.code_label = QLabel(mode_text(st.st_mode), w)
        self.code_label.setStyleSheet("font-family: monospace;")
        form.addRow(t("props.code"), self.code_label)
        if len(self.paths) > 1:
            hint = QLabel(t("props.perm_many_hint"), w)
            hint.setWordWrap(True)
            hint.setEnabled(False)
            form.addRow("", hint)
        return w

    def new_mode(self) -> int:
        mode = self._mode
        for shift, box in self.level_boxes.items():
            keep_x = mode & (1 << shift) if not self._is_dir else 0
            mode = apply_level(mode, shift, box.currentData(), self._is_dir)
            mode |= keep_x
        if not self._is_dir:
            x_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            if self.exec_box.isChecked():
                # ausführbar für alle, die lesen dürfen
                for shift in (6, 3, 0):
                    if mode & (4 << shift):
                        mode |= 1 << shift
                mode |= stat.S_IXUSR
            else:
                mode &= ~x_bits
        return mode

    def _perm_changed(self, *_args) -> None:
        if self._mode is None:
            return
        mode = self.new_mode()
        self.code_label.setText(mode_text(mode))
        self.apply_button.setEnabled(not self.read_only and (mode & 0o7777) != (self._mode & 0o7777))

    def apply_permissions(self) -> None:
        from .dialogs import show_error

        if self._mode is None:
            return
        errors = []
        for p in self.paths:
            try:
                st = os.lstat(p)
                if stat.S_ISLNK(st.st_mode):
                    continue
                is_dir = stat.S_ISDIR(st.st_mode)
                mode = st.st_mode
                if len(self.paths) == 1 or is_dir == self._is_dir:
                    mode = self.new_mode() if len(self.paths) == 1 else self._mode_for(mode, is_dir)
                os.chmod(p, stat.S_IMODE(mode))
            except OSError as exc:
                errors.append(f"{os.path.basename(p)}: {exc.strerror or exc}")
        if errors:
            show_error(self, t("props.tab_perm"), t("props.perm_failed", errors="\n".join(errors[:10])))
        try:
            self._mode = os.lstat(self.paths[0]).st_mode
        except OSError:
            pass
        self._perm_changed()

    def _mode_for(self, mode: int, is_dir: bool) -> int:
        """Bei Mehrfachauswahl die gewählten Stufen auf jeden Eintrag einzeln anwenden."""
        for shift, box in self.level_boxes.items():
            keep_x = mode & (1 << shift) if not is_dir else 0
            mode = apply_level(mode, shift, box.currentData(), is_dir) | keep_x
        if not is_dir and not self._is_dir:
            if self.exec_box.isChecked():
                for shift in (6, 3, 0):
                    if mode & (4 << shift):
                        mode |= 1 << shift
            else:
                mode &= ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return mode

    def done(self, result: int) -> None:  # noqa: D401 – QDialog.done
        table = getattr(self, "meta_table", None)
        if table is not None:
            table.save_width()  # Breite auch merken, wenn der Dialog gleich nach dem Ziehen schließt
        if self._thread is not None and self._thread.isRunning():
            self._thread.stop()
            self._thread.wait(2000)
        super().done(result)
