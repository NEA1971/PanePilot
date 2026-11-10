"""Dialog „Eigenschaften“ (F-870 ff.)."""

from __future__ import annotations

import os
import stat
from datetime import datetime

from PySide6.QtCore import QMimeDatabase, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
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


class PropertiesDialog(QDialog):
    def _meta_tab(self) -> tuple[QWidget, bool]:
        """Reiter „Metadaten“ (F-950): Tags, Cover und technische Infos einer Musikdatei, nur zur Anzeige."""
        from PySide6.QtCore import QByteArray
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QPushButton, QScrollArea

        from . import tags as tg
        from .metawizard import column_title, picture_info

        w = QWidget(self)
        if len(self.paths) != 1 or not tg.is_audio(self.paths[0]) or not os.path.isfile(self.paths[0]):
            return w, False
        rec = tg.read_file(self.paths[0])
        if rec.error:
            QVBoxLayout(w).addWidget(QLabel(t("meta.read_error", reason=rec.error), w))
            return w, True
        inner = QWidget(w)
        form = QFormLayout(inner)

        def row(label: str, value: str) -> None:
            val = QLabel(value, inner)
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(label + ":", val)

        for key in tg.FIELDS:
            if rec.fields.get(key):
                row(column_title(key), rec.fields[key])
        for key in sorted((k for k in rec.fields if k.startswith(tg.EXTRA)), key=lambda k: rec.labels.get(k, k).casefold()):
            row(rec.labels.get(key, key), rec.fields[key])
        row(t("meta.info.codec"), rec.codec)
        if rec.length:
            row(t("meta.info.length"), tg.format_length(rec.length))
        if rec.bitrate:
            row(t("meta.info.bitrate"), f"{round(rec.bitrate / 1000)} kbit/s")
        if rec.sample_rate:
            row(t("meta.info.samplerate"), f"{rec.sample_rate} Hz")
        cover = rec.front_cover()
        if cover is not None:
            img = QLabel(inner)
            pm = QPixmap()
            pm.loadFromData(QByteArray(cover.data))
            if not pm.isNull():
                img.setPixmap(pm.scaled(160, 160, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
            form.addRow(t("meta.field.cover") + ":", img)
            form.addRow("", QLabel(picture_info(cover), inner))
        scroll = QScrollArea(w)
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        btn = QPushButton(t("props.meta_edit"), w)
        btn.setEnabled(not self.read_only)
        btn.clicked.connect(self._edit_in_meta)
        lay = QVBoxLayout(w)
        lay.addWidget(scroll, 1)
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignRight)
        return w, True

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
        if self._thread is not None and self._thread.isRunning():
            self._thread.stop()
            self._thread.wait(2000)
        super().done(result)
