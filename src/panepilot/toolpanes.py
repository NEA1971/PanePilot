"""Werkzeug-Seitenleisten Suche (F-810 ff.) und Prüfsummen (F-830 ff.).

Aufbau wie „Mehrfach umbenennen“: Titel oben, Optionen, Knöpfe unten (F-800).
"""

from __future__ import annotations

import hashlib
import os
import zlib

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import search as srch
from .config import config_dir, load_json, save_json
from .i18n import t

SEARCH_PROFILES = "Suche"


# --- gemeinsamer Rahmen -----------------------------------------------------------------------
class ToolPane(QWidget):
    close_clicked = Signal()

    def __init__(self, title: str, parent=None) -> None:
        from PySide6.QtCore import Qt

        super().__init__(parent)
        self._title = QLabel(title, self)
        self._title.setObjectName("renameTitle")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.inner = QWidget(self)
        self.inner_layout = QVBoxLayout(self.inner)
        self.inner_layout.setContentsMargins(4, 4, 4, 4)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.inner)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        self.buttons = QHBoxLayout()
        self.btn_close = QPushButton(t("button.close"), self)
        self.btn_close.clicked.connect(self.close_clicked)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 4)
        layout.addWidget(self._title)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.summary)
        layout.addLayout(self.buttons)

    def keyPressEvent(self, event) -> None:
        from PySide6.QtCore import Qt

        if event.key() == Qt.Key.Key_Escape:  # Esc in der Seitenleiste = Schließen (F-802)
            self.close_clicked.emit()
            return
        super().keyPressEvent(event)

    def finish_layout(self) -> None:
        self.inner_layout.addStretch(1)
        self.buttons.addWidget(self.btn_close)


# --- Profile (Suche) ---------------------------------------------------------------------------
def profile_names(subdir: str) -> list[str]:
    folder = os.path.join(str(config_dir()), subdir)
    os.makedirs(folder, exist_ok=True)
    return sorted((f[:-5] for f in os.listdir(folder) if f.endswith(".json") and not f.startswith(".")),
                  key=str.casefold)


# --- Suche ---------------------------------------------------------------------------------------
class SearchPane(ToolPane):
    start_clicked = Signal()
    stop_clicked = Signal()
    save_profile_clicked = Signal()
    delete_profile_clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(t("search.title"), parent)
        self.base_label = QLabel(self)
        self.base_label.setWordWrap(True)
        self.inner_layout.addWidget(self.base_label)

        # Profile (F-819)
        self.profile_box = QComboBox(self)
        self.btn_save = QPushButton(t("rename.profile_save"), self)
        self.btn_delete = QPushButton(t("rename.profile_delete"), self)
        prow = QHBoxLayout()
        prow.addWidget(self.profile_box, 1)
        prow.addWidget(self.btn_save)
        prow.addWidget(self.btn_delete)
        gp = QGroupBox(t("rename.profile"), self)
        gp.setLayout(prow)
        self.inner_layout.addWidget(gp)

        # Dateiname (F-811)
        self.name = QLineEdit(self)
        self.name.setPlaceholderText("*.pdf;*.docx")
        self.name_wild = QRadioButton(t("filter.wildcard"), self)
        self.name_regex = QRadioButton(t("filter.regex"), self)
        g1 = QButtonGroup(self)
        g1.addButton(self.name_wild)
        g1.addButton(self.name_regex)
        self.name_case = QCheckBox(t("filter.case"), self)
        gn = QGroupBox(t("search.group_name"), self)
        fn = QVBoxLayout(gn)
        fn.addWidget(self.name)
        r = QHBoxLayout()
        r.addWidget(self.name_wild)
        r.addWidget(self.name_regex)
        r.addStretch(1)
        fn.addLayout(r)
        fn.addWidget(self.name_case)
        self.inner_layout.addWidget(gn)

        # Enthaltener Text (F-812)
        self.text = QLineEdit(self)
        self.text_plain = QRadioButton(t("rename.mode_text"), self)
        self.text_regex = QRadioButton(t("filter.regex"), self)
        g2 = QButtonGroup(self)
        g2.addButton(self.text_plain)
        g2.addButton(self.text_regex)
        self.text_case = QCheckBox(t("filter.case"), self)
        gt = QGroupBox(t("search.group_text"), self)
        ft = QVBoxLayout(gt)
        ft.addWidget(self.text)
        r = QHBoxLayout()
        r.addWidget(self.text_plain)
        r.addWidget(self.text_regex)
        r.addStretch(1)
        ft.addLayout(r)
        ft.addWidget(self.text_case)
        hint = QLabel(t("search.text_hint"), self)
        hint.setWordWrap(True)
        hint.setEnabled(False)
        ft.addWidget(hint)
        self.inner_layout.addWidget(gt)

        # Optionen (F-814, F-815)
        self.depth = QComboBox(self)
        self.depth.addItem(t("search.depth_0"), 0)
        for n in range(1, 11):
            self.depth.addItem(t("search.depth_n", n=n), n)
        self.depth.addItem(t("search.depth_all"), srch.DEPTH_UNLIMITED)
        self.hidden = QCheckBox(t("search.hidden"), self)
        self.dirs = QCheckBox(t("search.dirs"), self)
        self.network = QCheckBox(t("search.network"), self)
        self.network_hint = QLabel(t("search.network_hint"), self)
        self.network_hint.setWordWrap(True)
        self.network_hint.setStyleSheet("color: gray;")
        self.network_hint.setVisible(False)
        self.network.toggled.connect(self.network_hint.setVisible)
        go = QGroupBox(t("search.group_options"), self)
        fo = QFormLayout(go)
        fo.addRow(t("search.depth"), self.depth)
        fo.addRow(self.hidden)
        fo.addRow(self.dirs)
        fo.addRow(self.network)
        fo.addRow(self.network_hint)
        self.inner_layout.addWidget(go)
        self.error = QLabel(self)
        self.error.setStyleSheet("color: #D32F2F;")
        self.error.setWordWrap(True)
        self.inner_layout.addWidget(self.error)

        self.btn_start = QPushButton(t("search.start"), self)
        self.btn_start.setDefault(True)
        self.btn_start.clicked.connect(self._start_or_stop)
        self.buttons.addWidget(self.btn_start, 1)
        self.finish_layout()
        self.running = False

        for w in (self.name, self.text):
            w.textChanged.connect(self._validate)
            w.returnPressed.connect(self._start_or_stop)
        for b in (self.name_wild, self.name_regex, self.text_plain, self.text_regex):
            b.toggled.connect(self._validate)
        self.btn_save.clicked.connect(self.save_profile_clicked)
        self.btn_delete.clicked.connect(self.delete_profile_clicked)
        self.profile_box.activated.connect(self._profile_chosen)
        self.refresh_profiles()

    def _start_or_stop(self) -> None:
        if self.running:
            self.stop_clicked.emit()
        elif self.btn_start.isEnabled():
            self.start_clicked.emit()

    def set_running(self, running: bool) -> None:
        self.running = running
        self.btn_start.setText(t("search.stop") if running else t("search.start"))
        self._validate()

    def options(self) -> srch.SearchOptions:
        return srch.SearchOptions(
            name=self.name.text(), name_mode=srch.NAME_REGEX if self.name_regex.isChecked() else srch.NAME_WILDCARD,
            name_case=self.name_case.isChecked(), text=self.text.text(),
            text_mode=srch.TEXT_REGEX if self.text_regex.isChecked() else srch.TEXT_PLAIN,
            text_case=self.text_case.isChecked(), depth=self.depth.currentData(),
            hidden=self.hidden.isChecked(), dirs=self.dirs.isChecked(), network=self.network.isChecked())

    def set_options(self, o: srch.SearchOptions) -> None:
        self.name.setText(o.name)
        (self.name_regex if o.name_mode == srch.NAME_REGEX else self.name_wild).setChecked(True)
        self.name_case.setChecked(o.name_case)
        self.text.setText(o.text)
        (self.text_regex if o.text_mode == srch.TEXT_REGEX else self.text_plain).setChecked(True)
        self.text_case.setChecked(o.text_case)
        self.depth.setCurrentIndex(max(self.depth.findData(o.depth), 0))
        self.hidden.setChecked(o.hidden)
        self.dirs.setChecked(o.dirs)
        self.network.setChecked(o.network)
        self._validate()

    def _validate(self, *_args) -> None:
        err = self.options().error()
        if err == "search.err_empty":
            self.error.setText("")
        elif err:
            self.error.setText(t("rename.invalid_regex", reason=err))
        else:
            self.error.setText("")
        self.btn_start.setEnabled(self.running or err is None)

    # Profile
    def refresh_profiles(self, select: str | None = None) -> None:
        current = select if select is not None else self.profile_box.currentData()
        self.profile_box.clear()
        self.profile_box.addItem(t("rename.profile_none"), None)
        for name in profile_names(SEARCH_PROFILES):
            self.profile_box.addItem(name, name)
        self.profile_box.setCurrentIndex(max(self.profile_box.findData(current) if current else 0, 0))
        self.btn_delete.setEnabled(self.profile_box.currentData() is not None)

    def current_profile(self) -> str | None:
        return self.profile_box.currentData()

    def _profile_chosen(self, index: int) -> None:
        name = self.profile_box.itemData(index)
        self.btn_delete.setEnabled(name is not None)
        if name:
            self.set_options(srch.SearchOptions.from_dict(load_json(f"{SEARCH_PROFILES}/{name}.json", {})))

    def save_profile(self, name: str) -> None:
        save_json(f"{SEARCH_PROFILES}/{name}.json", self.options().to_dict())
        self.refresh_profiles(select=name)

    def delete_profile(self, name: str) -> None:
        os.unlink(os.path.join(str(config_dir()), SEARCH_PROFILES, name + ".json"))
        self.refresh_profiles(select="")


# --- Prüfsummen ----------------------------------------------------------------------------------
ALGORITHMS = ("crc32", "md5", "sha1", "sha256", "sha512")
LABELS = {"crc32": "CRC32", "md5": "MD5", "sha1": "SHA-1", "sha256": "SHA-256", "sha512": "SHA-512"}
LENGTHS = {8: "crc32", 32: "md5", 40: "sha1", 64: "sha256", 128: "sha512"}  # F-833


def normalize_checksum(text: str) -> str:
    return "".join(text.split()).lower()


def detect_algorithm(text: str) -> str | None:
    value = normalize_checksum(text)
    if not value or any(c not in "0123456789abcdef" for c in value):
        return None
    return LENGTHS.get(len(value))


def compute_checksums(path: str, progress=None, stop=lambda: False) -> dict[str, str] | None:
    """Alle Prüfsummen in einem Durchgang. None bei Abbruch."""
    hashers = {"md5": hashlib.md5(), "sha1": hashlib.sha1(), "sha256": hashlib.sha256(), "sha512": hashlib.sha512()}
    crc = 0
    total = os.path.getsize(path) or 1
    done = 0
    with open(path, "rb") as fh:
        while True:
            if stop():
                return None
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
            for h in hashers.values():
                h.update(chunk)
            done += len(chunk)
            if progress:
                progress(int(done * 1000 / total))
    result = {k: h.hexdigest() for k, h in hashers.items()}
    result["crc32"] = f"{crc & 0xFFFFFFFF:08x}"
    return result


class ChecksumThread(QThread):
    progress = Signal(int)  # Promille
    done = Signal(str, dict)  # Pfad, Werte
    failed = Signal(str, str)

    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self.path = path
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            result = compute_checksums(self.path, self.progress.emit, lambda: self._stop)
        except OSError as exc:
            self.failed.emit(self.path, exc.strerror or str(exc))
            return
        if result is not None:
            self.done.emit(self.path, result)


CHECKSUM_FILE_MAX = 5 * 1024 * 1024  # größere Dateien sind keine Prüfsummen-Dateien


def parse_checksum_file(path: str, target_name: str | None) -> str | None:
    """Prüfsumme zur Datei target_name aus einer Prüfsummen-Datei holen (v0.9.3).

    Formate: GNU („summe  datei“ bzw. „summe *datei“), BSD („SHA256 (datei) = summe“), SFV („datei CRC32“),
    eine einzelne Prüfsumme ohne Dateibezug. Kommentarzeilen (; oder #) werden übersprungen.
    """
    import re

    try:
        if os.path.getsize(path) > CHECKSUM_FILE_MAX:
            return None
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    text = raw.decode("utf-8", "replace")
    entries: list[tuple[str | None, str]] = []
    hexre = r"[0-9a-fA-F]{8,128}"
    for line in text.splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line or line[0] in ";#":
            continue
        m = re.match(rf"^[A-Za-z0-9-]+\s*\((.+)\)\s*=\s*({hexre})$", line)  # BSD
        if m:
            entries.append((m.group(1), m.group(2)))
            continue
        m = re.match(rf"^({hexre})\s+\*?(.+)$", line)  # GNU
        if m and detect_algorithm(m.group(1)):
            entries.append((m.group(2).strip(), m.group(1)))
            continue
        m = re.match(rf"^(.+?)\s+({hexre})$", line)  # SFV
        if m and len(m.group(2)) == 8:
            entries.append((m.group(1).strip(), m.group(2)))
            continue
        if re.fullmatch(hexre, line) and detect_algorithm(line):
            entries.append((None, line))
    if target_name:
        for name, value in entries:
            if name is not None and os.path.basename(name.replace("\\", "/")) == target_name:
                return value
    nameless = [v for n, v in entries if n is None]
    if len(entries) == 1 and nameless:
        return nameless[0]
    return None


class ChecksumDropEdit(QLineEdit):
    """Vergleichsfeld: Prüfsummen-Datei darauf ziehen übernimmt ihren Inhalt (v0.9.3)."""

    file_dropped = Signal(str)

    def dragEnterEvent(self, event) -> None:
        if any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if files:
            event.acceptProposedAction()
            self.file_dropped.emit(files[0])
        else:
            super().dropEvent(event)


class ChecksumPane(ToolPane):
    def __init__(self, parent=None) -> None:
        super().__init__(t("checksum.title"), parent)
        self.file_label = QLabel(self)
        self.file_label.setWordWrap(True)
        self.inner_layout.addWidget(self.file_label)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setMaximumHeight(10)
        self.inner_layout.addWidget(self.bar)
        form = QFormLayout()
        self.fields: dict[str, QLineEdit] = {}
        for alg in ALGORITHMS:
            edit = QLineEdit(self)
            edit.setReadOnly(True)
            edit.setStyleSheet("font-family: monospace;")
            copy = QToolButton(self)
            copy.setText("⧉")
            copy.setToolTip(t("checksum.copy", alg=LABELS[alg]))
            copy.clicked.connect(lambda _c=False, e=edit: QGuiApplication.clipboard().setText(e.text()))
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            row.addWidget(copy)
            form.addRow(LABELS[alg] + ":", row)
            self.fields[alg] = edit
        group = QGroupBox(t("checksum.values"), self)
        group.setLayout(form)
        self.inner_layout.addWidget(group)
        self.compare = ChecksumDropEdit(self)
        self.compare.setPlaceholderText(t("checksum.compare_hint"))
        self.compare.file_dropped.connect(self.load_checksum_file)
        self.result = QLabel(self)
        self.result.setWordWrap(True)
        gc = QGroupBox(t("checksum.compare"), self)
        fc = QVBoxLayout(gc)
        fc.addWidget(self.compare)
        fc.addWidget(self.result)
        self.inner_layout.addWidget(gc)
        self.finish_layout()
        self.compare.textChanged.connect(self.update_compare)
        self.values: dict[str, str] = {}
        self.path: str | None = None
        self.previous_path: str | None = None  # vorher gewählte Datei (für Drag & Drop aus dem Dateifenster)
        self._thread: ChecksumThread | None = None
        self._pending: tuple[str | None, bool] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._switch)

    def show_file(self, path: str | None, is_dir: bool = False) -> None:
        """Datei unter dem Cursor (F-831). Gewechselt wird leicht verzögert und erst, wenn keine Maustaste
        mehr gedrückt ist – wer eine Datei zum Ziehen greift, löst so keine Berechnung aus (v0.9.5)."""
        self._pending = (path, is_dir)
        self._timer.start()

    def _switch(self) -> None:
        if self._pending is None:
            return
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            self._timer.start()  # Maustaste noch gedrückt (evtl. Ziehen) – später nochmal schauen
            return
        path, is_dir = self._pending
        self._pending = None
        if path == self.path and (self.values or self._thread is not None):
            return
        self._stop_thread()
        if self.path and not os.path.isdir(self.path):
            self.previous_path = self.path
        self.path = path
        self.values = {}
        for e in self.fields.values():
            e.clear()
        self.bar.setValue(0)
        if not path or is_dir:
            self.file_label.setText(t("checksum.no_file"))
            self.update_compare()
            return
        self.file_label.setText(os.path.basename(path))
        self.file_label.setToolTip(path)
        self._thread = ChecksumThread(path, self)
        self._thread.progress.connect(self.bar.setValue)
        self._thread.done.connect(self._done)
        self._thread.failed.connect(lambda p, r: self.file_label.setText(t("checksum.failed", reason=r)))
        self._thread.start()

    def _done(self, path: str, values: dict) -> None:
        if path != self.path:
            return
        self.values = values
        for alg, v in values.items():
            self.fields[alg].setText(v)
            self.fields[alg].setCursorPosition(0)
        self.bar.setValue(1000)
        self._thread = None
        self.update_compare()

    def load_checksum_file(self, path: str) -> None:
        # Wird die Prüfsummen-Datei aus einem PanePilot-Fenster gezogen, steht der Cursor beim Ziehen auf ihr –
        # dann gilt die Datei, die vorher gewählt war (z. B. die ISO), und deren Prüfsummen werden berechnet.
        pending = self._pending[0] if self._pending else None
        if pending and os.path.abspath(path) == os.path.abspath(pending):
            self._timer.stop()  # Wechsel auf die gezogene Prüfsummen-Datei verwerfen
            self._pending = None
        elif self.path and os.path.abspath(path) == os.path.abspath(self.path) and self.previous_path:
            self.show_file(self.previous_path)
            self._timer.stop()
            self._switch()
        target = os.path.basename(self.path) if self.path else None
        value = parse_checksum_file(path, target)
        if value is None:
            self.compare.clear()
            self.result.setStyleSheet("color: #B26A00;")
            self.result.setText(t("checksum.file_no_entry", name=os.path.basename(path)))
            return
        self.compare.setText(value)

    def stop(self) -> None:
        self._timer.stop()
        self._pending = None
        self._stop_thread()

    def _stop_thread(self) -> None:
        if self._thread is not None:
            self._thread.stop()
            self._thread.wait(3000)
            self._thread = None

    def update_compare(self, *_args) -> None:
        for e in self.fields.values():
            e.setStyleSheet("font-family: monospace;")
        text = self.compare.text()
        if not text.strip():
            self.result.setText("")
            return
        alg = detect_algorithm(text)
        if alg is None:
            self.result.setStyleSheet("color: #B26A00;")
            self.result.setText(t("checksum.unknown_format"))
            return
        if not self.values:
            self.result.setStyleSheet("")
            self.result.setText(t("checksum.waiting", alg=LABELS[alg]))
            return
        if normalize_checksum(text) == self.values.get(alg):
            self.result.setStyleSheet("color: #2E7D32; font-weight: bold;")
            self.result.setText("✔ " + t("checksum.match", alg=LABELS[alg]))
            self.fields[alg].setStyleSheet("font-family: monospace; background: #DFF0D8;")
        else:
            self.result.setStyleSheet("color: #D32F2F; font-weight: bold;")
            self.result.setText("✘ " + t("checksum.mismatch", alg=LABELS[alg]))
