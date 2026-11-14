"""Übertragungen zum und vom Server (v1.3): Warteschlange, Hintergrund-Thread und Übertragungsfenster.

Jeder Auftrag (Herunterladen/Hochladen, Kopieren/Verschieben) wird zuerst eingelesen – bei Ordnern mit
allen Unterordnern – und als Liste von Dateien abgearbeitet. Der Thread nutzt eigene Verbindungen, so dass
man im Dateifenster weiterarbeiten kann. Neue Aufträge werden hinten angehängt.
"""

from __future__ import annotations

import os
import posixpath
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
                               QPushButton, QTableView, QVBoxLayout, QWidget)

from . import remotefs as rf
from .fileops import ConflictDecision
from .i18n import t
from .util import format_size

DOWN, UP = "down", "up"
WAIT, RUN, DONE, ERROR, SKIP, CANCEL = "wait", "run", "done", "error", "skip", "cancel"


@dataclass
class Job:
    cfg: rf.ServerConfig
    password: str
    passphrase: str
    direction: str
    sources: list[tuple[str, bool]]  # (Pfad, ist Ordner) – lokal bzw. auf dem Server
    target: str  # Zielordner (lokal bzw. auf dem Server)
    move: bool = False
    remembered: ConflictDecision | None = None
    dirs: list[str] = field(default_factory=list)  # Quellordner (zum Entfernen nach dem Verschieben)
    finished: bool = False


@dataclass
class Item:
    job: Job
    src: str
    dst: str
    size: int = 0
    mtime: float = 0.0
    is_dir: bool = False
    status: str = WAIT
    error: str = ""
    done: int = 0

    @property
    def name(self) -> str:
        return os.path.basename(self.src.rstrip("/")) or self.src


def _local_exists(path: str) -> bool:
    return os.path.lexists(path)


# --- Arbeits-Thread -------------------------------------------------------------------------------------
class TransferWorker(QThread):
    items_added = Signal(list)
    item_changed = Signal(object)
    job_finished = Signal(object)
    idle = Signal()
    conflict = Signal(object, str, str)  # Item, Info Ziel, Info Quelle → self.decision setzen

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._lock = threading.Condition()
        self._jobs: list[Job] = []  # noch einzulesen
        self._items: list[Item] = []  # alle Dateien (auch erledigte)
        self._paused = False
        self._cancel = False
        self._stop = False
        self._conns: dict[str, rf.Connection] = {}
        self.decision: ConflictDecision | None = None
        self.bytes_done = 0
        self._scanning = 0

    # Steuerung (aus dem Hauptthread)
    def add_job(self, job: Job) -> None:
        with self._lock:
            self._cancel = False
            self._jobs.append(job)
            self._lock.notify_all()

    def retry(self, items: list[Item]) -> None:
        with self._lock:
            for it in items:
                if it.status in (ERROR, CANCEL):
                    it.status, it.error, it.done = WAIT, "", 0
                    it.job.finished = False
            self._cancel = False
            self._lock.notify_all()

    def remove_waiting(self, items: list[Item]) -> None:
        with self._lock:
            for it in items:
                if it.status == WAIT:
                    it.status = SKIP
                    it.error = t("transfer.removed")

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused
            self._lock.notify_all()

    @property
    def paused(self) -> bool:
        return self._paused

    def cancel_all(self) -> None:
        with self._lock:
            self._cancel = True
            self._paused = False
            self._jobs.clear()
            for it in self._items:
                if it.status == WAIT:
                    it.status = CANCEL
            self._lock.notify_all()

    def stop(self) -> None:
        with self._lock:
            self._stop = True
            self._cancel = True
            self._lock.notify_all()
        self.wait(5000)

    def busy(self) -> bool:
        with self._lock:
            return bool(self._jobs) or self._scanning > 0 or any(it.status in (WAIT, RUN) for it in self._items)

    def items(self) -> list[Item]:
        return self._items

    # Ablauf
    def _next(self):
        with self._lock:
            while True:
                if self._stop:
                    return None
                if self._paused:
                    self._lock.wait(0.5)
                    continue
                if self._jobs:
                    self._scanning += 1
                    return self._jobs.pop(0)
                for it in self._items:
                    if it.status == WAIT:
                        it.status = RUN
                        return it
                return False

    def run(self) -> None:
        idle_sent = False
        while True:
            nxt = self._next()
            if nxt is None:
                break
            if nxt is False:
                self._finish_jobs()
                if not idle_sent:
                    idle_sent = True
                    self._close_all()
                    self.idle.emit()
                with self._lock:
                    if not self._stop and not self._jobs and not any(i.status == WAIT for i in self._items):
                        self._lock.wait(1.0)
                continue
            idle_sent = False
            if isinstance(nxt, Job):
                try:
                    self._scan(nxt)
                finally:
                    with self._lock:
                        self._scanning -= 1
            else:
                self._transfer(nxt)
        self._close_all()

    def _cancelled(self) -> bool:
        with self._lock:
            while self._paused and not self._cancel and not self._stop:
                self._lock.wait(0.5)
            return self._cancel or self._stop

    def _conn(self, job: Job) -> rf.Connection:
        conn = self._conns.get(job.cfg.id)
        if conn is not None and conn.alive():
            return conn
        if conn is not None:
            conn.close()
        conn = rf.Connection.open(job.cfg, job.password, job.passphrase)
        self._conns[job.cfg.id] = conn
        return conn

    def _close_all(self) -> None:
        for c in self._conns.values():
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        self._conns.clear()

    # Einlesen
    def _scan(self, job: Job) -> None:
        new: list[Item] = []
        try:
            if job.direction == DOWN:
                conn = self._conn(job)
                for src, is_dir in job.sources:
                    dst = os.path.join(job.target, posixpath.basename(src.rstrip("/")))
                    if is_dir:
                        self._scan_remote(conn, job, src, dst, new)
                    else:
                        item = conn.stat(src)
                        new.append(Item(job, src, dst, item.size if item else 0, item.mtime if item else 0.0))
            else:
                for src, is_dir in job.sources:
                    dst = posixpath.join(job.target, os.path.basename(src.rstrip(os.sep)))
                    if is_dir:
                        self._scan_local(job, src, dst, new)
                    else:
                        st = os.stat(src)
                        new.append(Item(job, src, dst, st.st_size, st.st_mtime))
        except (rf.RemoteError, OSError) as exc:
            new.append(Item(job, job.sources[0][0] if job.sources else "", job.target, status=ERROR,
                            error=_reason(exc)))
        with self._lock:
            self._items.extend(new)
        self.items_added.emit(new)

    def _scan_remote(self, conn, job: Job, src: str, dst: str, out: list[Item]) -> None:
        if self._cancelled():
            return
        job.dirs.append(src)
        out.append(Item(job, src, dst, is_dir=True))
        for it in sorted(conn.listdir(src), key=lambda i: (not i.is_dir, i.name.casefold())):
            child_src = posixpath.join(src, it.name)
            child_dst = os.path.join(dst, it.name)
            if it.is_dir:
                if not it.is_link:  # verknüpfte Ordner nicht verfolgen (Schleifen)
                    self._scan_remote(conn, job, child_src, child_dst, out)
            else:
                out.append(Item(job, child_src, child_dst, it.size, it.mtime))

    def _scan_local(self, job: Job, src: str, dst: str, out: list[Item]) -> None:
        if self._cancelled():
            return
        job.dirs.append(src)
        out.append(Item(job, src, dst, is_dir=True))
        try:
            entries = sorted(os.scandir(src), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.casefold()))
        except OSError as exc:
            out[-1].status, out[-1].error = ERROR, _reason(exc)
            return
        for e in entries:
            child_dst = posixpath.join(dst, e.name)
            if e.is_dir(follow_symlinks=False):
                self._scan_local(job, e.path, child_dst, out)
            else:
                try:
                    st = e.stat()
                except OSError as exc:
                    out.append(Item(job, e.path, child_dst, status=ERROR, error=_reason(exc)))
                    continue
                out.append(Item(job, e.path, child_dst, st.st_size, st.st_mtime))

    # Übertragen
    def _set(self, item: Item, status: str, error: str = "") -> None:
        item.status, item.error = status, error
        self.item_changed.emit(item)

    def _transfer(self, item: Item) -> None:
        self.item_changed.emit(item)
        if self._cancelled():
            self._set(item, CANCEL)
            return
        try:
            conn = self._conn(item.job)
            if item.is_dir:
                self._make_dir(conn, item)
                self._set(item, DONE)
                return
            target = self._resolve(conn, item)
            if target is None:
                self._set(item, SKIP, t("transfer.skipped"))
                return
            item.dst = target
            if item.job.direction == DOWN:
                self._download(conn, item)
            else:
                self._upload(conn, item)
            if item.job.move:
                self._remove_source(conn, item)
            self._set(item, DONE)
        except rf.Cancelled:
            self._set(item, CANCEL)
        except (rf.RemoteError, OSError) as exc:
            self._set(item, ERROR, _reason(exc))
            if isinstance(exc, rf.ConnectionLost):
                conn = self._conns.pop(item.job.cfg.id, None)
                if conn is not None:
                    conn.close()

    def _make_dir(self, conn, item: Item) -> None:
        if item.job.direction == DOWN:
            os.makedirs(item.dst, exist_ok=True)
        else:
            existing = conn.stat(item.dst)
            if existing is None:
                conn.mkdir(item.dst)
            elif not existing.is_dir:
                raise rf.RemoteError(t("transfer.not_a_folder"))

    def _exists(self, conn, item: Item, path: str):
        if item.job.direction == DOWN:
            if not _local_exists(path):
                return None
            st = os.stat(path)
            return st.st_size, st.st_mtime, os.path.isdir(path)
        existing = conn.stat(path)
        return None if existing is None else (existing.size, existing.mtime, existing.is_dir)

    def _resolve(self, conn, item: Item) -> str | None:
        """Ziel bestimmen; bei vorhandener Datei nachfragen (wie beim lokalen Kopieren)."""
        found = self._exists(conn, item, item.dst)
        if found is None:
            return item.dst
        job = item.job
        if job.remembered is not None:
            decision = job.remembered
        else:
            from datetime import datetime

            def info(size, mtime, is_dir):
                when = datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M") if mtime else "–"
                return t("conflict.folder_info", date=when) if is_dir else \
                    t("conflict.file_info", size=format_size(size), date=when)
            self.decision = None
            self.conflict.emit(item, info(*found), info(item.size, item.mtime, False))
            decision = self.decision or ConflictDecision("cancel")
            if decision.apply_all and decision.action != "cancel":
                job.remembered = ConflictDecision(decision.action, "", True)
        if decision.action == "cancel":
            self.cancel_all()
            raise rf.Cancelled()
        if decision.action == "skip":
            return None
        if decision.action == "rename":
            folder = os.path.dirname(item.dst) if job.direction == DOWN else posixpath.dirname(item.dst)
            name = (decision.new_name or "").strip() if not decision.apply_all else ""
            join = os.path.join if job.direction == DOWN else posixpath.join
            if not name or "/" in name or self._exists(conn, item, join(folder, name)) is not None:
                name = self._free_name(conn, item, folder)
            return join(folder, name)
        return item.dst  # überschreiben

    def _free_name(self, conn, item: Item, folder: str) -> str:
        join = os.path.join if item.job.direction == DOWN else posixpath.join
        base = os.path.basename(item.dst)
        stem, ext = os.path.splitext(base)
        n = 2
        while True:
            name = f"{stem} ({n}){ext}"
            if self._exists(conn, item, join(folder, name)) is None:
                return name
            n += 1

    def _progress(self, item: Item):
        def cb(n: int) -> None:
            item.done += n
            self.bytes_done += n
        return cb

    def _download(self, conn, item: Item) -> None:
        os.makedirs(os.path.dirname(item.dst), exist_ok=True)
        part = item.dst + ".part"
        item.done = 0
        try:
            with open(part, "wb") as fh:
                conn.download(item.src, fh, self._progress(item), self._cancelled)
            os.replace(part, item.dst)
        except BaseException:
            try:
                os.remove(part)
            except OSError:
                pass
            raise
        if item.mtime:
            try:
                os.utime(item.dst, (item.mtime, item.mtime))
            except OSError:
                pass

    def _upload(self, conn, item: Item) -> None:
        item.done = 0
        fh = open(item.src, "rb")  # Lesefehler: nichts auf dem Server anfassen
        try:
            with fh:
                conn.upload(fh, item.dst, self._progress(item), self._cancelled)
        except BaseException:
            try:
                fresh = self._conn(item.job)
                fresh.remove(item.dst)
            except (rf.RemoteError, OSError):
                pass
            raise
        if item.mtime:
            self._conn(item.job).set_mtime(item.dst, item.mtime)

    def _remove_source(self, conn, item: Item) -> None:
        if item.job.direction == DOWN:
            conn.remove(item.src)
        else:
            os.remove(item.src)

    def _finish_jobs(self) -> None:
        jobs = []
        with self._lock:
            for it in self._items:
                if not it.job.finished and it.job not in jobs:
                    jobs.append(it.job)
            pending = {id(it.job) for it in self._items if it.status in (WAIT, RUN)}
        for job in jobs:
            if id(job) in pending:
                continue
            job.finished = True
            if job.move and job.dirs:
                self._remove_dirs(job)
            self.job_finished.emit(job)

    def _remove_dirs(self, job: Job) -> None:
        ok = {it.src for it in self._items if it.job is job and it.status == DONE}
        for d in sorted(set(job.dirs), key=lambda p: p.count("/"), reverse=True):
            if d not in ok:
                continue
            try:
                if job.direction == DOWN:
                    self._conn(job).rmdir(d)
                else:
                    os.rmdir(d)
            except (rf.RemoteError, OSError):
                pass  # nicht leer (z. B. übersprungene Dateien) → bleibt


def _reason(exc: BaseException) -> str:
    if isinstance(exc, OSError) and exc.strerror:
        return exc.strerror
    return str(exc) or type(exc).__name__


# --- Liste ----------------------------------------------------------------------------------------------
class TransferModel(QAbstractTableModel):
    COLS = ("transfer.col_status", "transfer.col_dir", "transfer.col_file", "transfer.col_target",
            "transfer.col_size", "transfer.col_progress")
    ICONS = {WAIT: "…", RUN: "▶", DONE: "✔", ERROR: "✖", SKIP: "–", CANCEL: "■"}

    def __init__(self, worker: TransferWorker, parent=None) -> None:
        super().__init__(parent)
        self.worker = worker
        self.rows: list[Item] = []
        self._row_of: dict[int, int] = {}

    def add(self, items: list[Item]) -> None:
        if not items:
            return
        first = len(self.rows)
        self.beginInsertRows(QModelIndex(), first, first + len(items) - 1)
        for i, it in enumerate(items):
            self._row_of[id(it)] = first + i
        self.rows.extend(items)
        self.endInsertRows()

    def changed(self, item: Item) -> None:
        r = self._row_of.get(id(item))
        if r is not None:
            self.dataChanged.emit(self.index(r, 0), self.index(r, len(self.COLS) - 1))

    def refresh_running(self) -> None:
        for it in self.rows:
            if it.status == RUN:
                self.changed(it)

    def clear_finished(self) -> None:
        self.beginResetModel()
        self.rows = [it for it in self.rows if it.status in (WAIT, RUN, ERROR)]
        self._row_of = {id(it): i for i, it in enumerate(self.rows)}
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.COLS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return t(self.COLS[section])
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        it = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return f"{self.ICONS[it.status]} {t('transfer.status_' + it.status)}"
            if col == 1:
                return "↓" if it.job.direction == DOWN else "↑"
            if col == 2:
                return it.src
            if col == 3:
                return it.dst
            if col == 4:
                return "" if it.is_dir else format_size(it.size)
            if col == 5:
                if it.is_dir or it.status != RUN:
                    return ""
                return f"{min(100, int(it.done * 100 / it.size)) if it.size else 0} %"
        if role == Qt.ItemDataRole.ToolTipRole and it.error:
            return it.error
        if role == Qt.ItemDataRole.ForegroundRole:
            from PySide6.QtGui import QColor

            if it.status == ERROR:
                return QColor("#D32F2F")
            if it.status in (SKIP, CANCEL):
                return QColor("gray")
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (1, 4, 5):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter) if col != 1 else \
                int(Qt.AlignmentFlag.AlignCenter)
        return None


# --- Fenster -------------------------------------------------------------------------------------------
class TransferWindow(QWidget):
    def __init__(self, manager: TransferManager, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.manager = manager
        self.setWindowTitle(t("transfer.title"))
        self.resize(900, 480)
        self.summary = QLabel(self)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 1000)
        self.bar.setFormat("%p %")
        self.table = QTableView(self)
        self.table.setModel(manager.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for col, w in enumerate((120, 30, 330, 330, 80, 70)):
            hdr.resizeSection(col, w)
        hdr.setStretchLastSection(True)
        self.btn_pause = QPushButton(t("transfer.pause"), self)
        self.btn_cancel = QPushButton(t("transfer.cancel_all"), self)
        self.btn_remove = QPushButton(t("transfer.remove"), self)
        self.btn_retry = QPushButton(t("transfer.retry"), self)
        self.btn_close = QPushButton(t("transfer.close"), self)
        self.auto_close = QCheckBox(t("transfer.auto_close"), self)
        self.auto_close.setChecked(bool(manager.settings.get("transfer_autoclose")) if manager.settings else False)
        self.auto_close.toggled.connect(
            lambda on: manager.settings.set("transfer_autoclose", on) if manager.settings else None)
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_cancel.clicked.connect(manager.worker.cancel_all)
        self.btn_remove.clicked.connect(self._remove)
        self.btn_retry.clicked.connect(self._retry)
        self.btn_close.clicked.connect(self.close)
        row = QHBoxLayout()
        for b in (self.btn_pause, self.btn_cancel, self.btn_remove, self.btn_retry):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.auto_close)
        row.addWidget(self.btn_close)
        lay = QVBoxLayout(self)
        lay.addWidget(self.summary)
        lay.addWidget(self.bar)
        lay.addWidget(self.table, 1)
        lay.addLayout(row)
        self.update_summary()

    def _selected(self) -> list[Item]:
        rows = {i.row() for i in self.table.selectionModel().selectedRows()}
        return [self.manager.model.rows[r] for r in sorted(rows)]

    def _remove(self) -> None:
        self.manager.worker.remove_waiting(self._selected())
        for it in self._selected():
            self.manager.model.changed(it)
        self.update_summary()

    def _retry(self) -> None:
        sel = [it for it in self._selected() if it.status in (ERROR, CANCEL)]
        failed = sel or [it for it in self.manager.model.rows if it.status in (ERROR, CANCEL)]
        self.manager.worker.retry(failed)
        for it in failed:
            self.manager.model.changed(it)
        self.update_summary()

    def _toggle_pause(self) -> None:
        w = self.manager.worker
        w.set_paused(not w.paused)
        self.btn_pause.setText(t("transfer.resume") if w.paused else t("transfer.pause"))
        self.update_summary()

    def update_summary(self) -> None:
        rows = self.manager.model.rows
        files = [it for it in rows if not it.is_dir and it.status != SKIP]
        done = sum(1 for it in files if it.status == DONE)
        total_bytes = sum(it.size for it in files)
        done_bytes = sum(it.size if it.status == DONE else it.done for it in files)
        errors = sum(1 for it in rows if it.status == ERROR)
        speed = self.manager.speed()
        left = (total_bytes - done_bytes) / speed if speed > 0 else 0
        parts = [t("transfer.files", done=done, total=len(files)),
                 t("transfer.bytes", done=format_size(done_bytes), total=format_size(total_bytes))]
        busy = self.manager.worker.busy()
        if busy and speed > 0:
            parts.append(t("transfer.speed", speed=format_size(int(speed))))
            parts.append(t("transfer.left", time=_fmt_time(left)))
        if errors:
            parts.append(t("transfer.errors", n=errors))
        if self.manager.worker.paused:
            parts.append(t("transfer.paused"))
        elif not busy and rows:
            parts.append(t("transfer.finished"))
        self.summary.setText("  ·  ".join(parts))
        self.bar.setValue(int(done_bytes * 1000 / total_bytes) if total_bytes else (1000 if not busy and rows else 0))
        self.btn_retry.setEnabled(any(it.status in (ERROR, CANCEL) for it in rows))
        self.btn_cancel.setEnabled(busy)
        self.btn_pause.setEnabled(busy or self.manager.worker.paused)


def _fmt_time(seconds: float) -> str:
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"
    return f"{s // 60}:{s % 60:02d}"


class TransferManager(QObject):
    """Verbindet Thread, Liste und Fenster; eine Instanz je Hauptfenster."""

    job_done = Signal(object)

    def __init__(self, parent_window, settings=None) -> None:
        super().__init__(parent_window)
        self.parent_window = parent_window
        self.settings = settings
        self.worker = TransferWorker()
        self.model = TransferModel(self.worker, self)
        self.window: TransferWindow | None = None
        self._samples: list[tuple[float, int]] = []
        self.worker.items_added.connect(self._added)
        self.worker.item_changed.connect(self.model.changed)
        self.worker.job_finished.connect(self.job_done)
        self.worker.idle.connect(self._idle)
        self.worker.conflict.connect(self._ask_conflict, Qt.ConnectionType.BlockingQueuedConnection)
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._tick)
        self.worker.start()

    def add(self, job: Job) -> None:
        self.show_window()
        self.worker.add_job(job)
        self.timer.start()

    def show_window(self) -> None:
        if self.window is None:
            self.window = TransferWindow(self, self.parent_window)
        self.window.show()
        self.window.raise_()

    def busy(self) -> bool:
        return self.worker.busy()

    def shutdown(self) -> None:
        self.worker.cancel_all()
        self.worker.stop()

    def speed(self) -> float:
        if len(self._samples) < 2:
            return 0.0
        (t0, b0), (t1, b1) = self._samples[0], self._samples[-1]
        return (b1 - b0) / (t1 - t0) if t1 > t0 else 0.0

    def _added(self, items: list) -> None:
        self.model.add(items)
        if self.window is not None:
            self.window.update_summary()

    def _tick(self) -> None:
        now = time.monotonic()
        self._samples.append((now, self.worker.bytes_done))
        self._samples = [s for s in self._samples if now - s[0] <= 5.0]
        self.model.refresh_running()
        if self.window is not None:
            self.window.update_summary()

    def _idle(self) -> None:
        self._tick()
        self.timer.stop()
        self._samples.clear()
        if self.window is None:
            return
        self.window.update_summary()
        rows = self.model.rows
        ok = rows and not any(it.status in (ERROR, CANCEL) for it in rows)
        if ok and self.window.auto_close.isChecked():
            self.window.close()
            self.model.clear_finished()

    def _ask_conflict(self, item: Item, dst_info: str, src_info: str) -> None:
        from .dialogs import ConflictDialog

        folder = os.path.dirname(item.dst) if item.job.direction == DOWN else posixpath.dirname(item.dst)
        stem, ext = os.path.splitext(os.path.basename(item.dst))
        dlg = ConflictDialog(self.window or self.parent_window, item.src, item.dst, False, f"{stem} (2){ext}",
                             dst_info=dst_info, src_info=src_info, folder=folder)
        dlg.exec()
        self.worker.decision = dlg.decision
