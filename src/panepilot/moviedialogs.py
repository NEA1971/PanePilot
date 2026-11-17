"""Fenster für „Online-Daten“ im Video-Modus (v1.9): Abfrage im Hintergrund, Auswahl, Übersicht."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QByteArray, QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
                               QListWidget, QListWidgetItem, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from . import moviedb as md
from . import netutil
from . import tags as tg
from .dialogs import free_window
from .i18n import t

COVER = "cover"


@dataclass
class SeriesGroup:
    """Alle Folgen einer Serie: die Serie wird nur einmal gesucht und ausgewählt (L-1111)."""
    name: str
    year: str = ""
    tmdb: str = ""
    hits: list = field(default_factory=list)
    reason: str = ""
    searched: bool = False


@dataclass
class Job:
    """Ein Video und was über den Film bzw. die Folge bekannt ist (L-910, L-1110)."""
    item: object
    imdb: str = ""
    tmdb: str = ""
    title: str = ""
    year: str = ""
    qid: str = ""
    movie: md.Movie | None = None
    hits: list = field(default_factory=list)
    reason: str = ""  # Grund ohne Ergebnis (L-943)
    ep: md.EpisodeRef | None = None
    group: SeriesGroup | None = None


def make_jobs(items) -> list[Job]:
    """Filme wie bisher; Folgen (S01E02) einer Serie teilen sich eine SeriesGroup."""
    groups: dict = {}
    jobs = []
    for it in items:
        ref = md.episode_ref(it.record.path)
        if ref is None or not ref.series:
            jobs.append(make_job(it))
            continue
        ref.tmdb = ref.tmdb or md.clean_tmdb(it.value(tg.EXTRA + md.F_TMDB))  # Serienkennung aus früherem Abruf
        key = ("tmdb", ref.tmdb) if ref.tmdb else (ref.series.casefold(), ref.year)
        group = groups.setdefault(key, SeriesGroup(ref.series, ref.year, ref.tmdb))
        jobs.append(Job(it, title=ref.series, year=ref.year, ep=ref, group=group))
    return jobs


def make_job(item) -> Job:
    """Kennung aus eigenen Feldern, sonst aus dem Dateinamen, sonst Titel und Jahr (L-910)."""
    name = item.display_name
    imdb = md.clean_imdb(item.value(tg.EXTRA + md.F_IMDB))
    tmdb = md.clean_tmdb(item.value(tg.EXTRA + md.F_TMDB))
    n_imdb, n_tmdb = md.ids_from_name(name)
    title, year = md.title_year(name)
    return Job(item, imdb or n_imdb, tmdb or n_tmdb, title, year)


class LookupThread(QThread):
    """Holt die Daten nacheinander (L-901, L-950); bei Abbruch bleiben die bisherigen Ergebnisse."""

    progress = Signal(int, int, str)
    fatal = Signal(str)

    def __init__(self, service, jobs: list[Job], parent=None) -> None:
        super().__init__(parent)
        self.service = service
        self.jobs = jobs
        self.cancelled = False

    def run(self) -> None:
        total = len(self.jobs)
        for i, job in enumerate(self.jobs):
            if self.cancelled:
                break
            self.progress.emit(i, total, job.item.display_name)
            try:
                self._one(job)
            except md.FatalError as exc:
                self.fatal.emit(str(exc))
                return
            except netutil.NetError as exc:
                job.reason = t("online.failed_one", reason=str(exc))
            except Exception as exc:  # noqa: BLE001 – unerwartete Antwort: nur diesen Film auslassen
                job.reason = t("online.failed_one", reason=f"{type(exc).__name__}: {exc}")
        self.progress.emit(total, total, "")

    def _one(self, job: Job) -> None:
        if job.movie is not None or job.reason:
            return
        if job.ep is not None:
            self._episode(job)
            return
        if job.imdb or job.tmdb or job.qid:
            job.movie = self.service.load(job.imdb, job.tmdb, job.qid)
            if job.movie is None:
                job.reason = t("online.not_found")
            return
        if not job.title:
            job.reason = t("online.no_id")
            return
        hits = self.service.search(job.title, job.year)
        if not hits:
            job.reason = t("online.not_found")
            return
        hit = md.pick(hits, job.year)
        if hit is not None:
            job.imdb, job.tmdb, job.qid = hit.imdb, hit.tmdb, hit.qid
            job.movie = self.service.load(hit.imdb, hit.tmdb, hit.qid)
            if job.movie is None:
                job.reason = t("online.not_found")
            return
        job.hits = hits[:12]
        _thumbs(job.hits)

    def _episode(self, job: Job) -> None:
        g = job.group
        if not isinstance(self.service, md.Tmdb):
            job.reason = t("online.series_no_key")  # L-1112
            return
        if not g.tmdb and not g.searched:
            g.searched = True
            hits = self.service.search_tv(g.name, g.year)
            hit = md.pick(hits, g.year) if hits else None
            if not hits:
                g.reason = t("online.not_found")
            elif hit is not None or len(hits) == 1:
                g.tmdb = (hit or hits[0]).tmdb
            else:
                g.hits = hits[:12]
                _thumbs(g.hits)
        if not g.tmdb:
            job.reason = g.reason  # leer, solange die Auswahl noch aussteht
            return
        job.movie = self.service.episode(g.tmdb, job.ep.season, job.ep.episode)
        if job.movie is None:
            job.reason = t("online.episode_not_found", s=f"{job.ep.season:02d}", e=f"{job.ep.episode:02d}")


def _thumbs(hits) -> None:
    for h in hits[:8]:  # kleine Poster für die Auswahl (nur TMDb)
        if h.thumb_url:
            try:
                h.thumb = md.http_get(h.thumb_url, None, "tmdb")
            except netutil.NetError:
                h.thumb = None


def run_lookup(parent, service, jobs: list[Job]) -> str | None:
    """Abfrage mit Fortschritt „Film x von y“ und „Abbrechen“; liefert einen Fehlertext oder None."""
    from PySide6.QtCore import QEventLoop
    from PySide6.QtWidgets import QProgressDialog

    dlg = QProgressDialog(t("online.progress", n=0, total=len(jobs)), t("button.cancel"), 0, max(1, len(jobs)), parent)
    dlg.setWindowTitle(t("online.title"))
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(300)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    worker = LookupThread(service, jobs)
    out: dict = {}

    def progress(i, total, name):
        dlg.setValue(i)
        dlg.setLabelText(t("online.progress", n=min(i + 1, total), total=total) + (f"\n{name}" if name else ""))

    worker.progress.connect(progress)
    worker.fatal.connect(lambda e: out.__setitem__("error", e))
    dlg.canceled.connect(lambda: setattr(worker, "cancelled", True))
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.start()
    if not worker.isFinished():
        loop.exec()
    worker.wait()
    dlg.close()
    dlg.deleteLater()
    if worker.cancelled:
        for job in jobs:
            if job.movie is None and not job.hits and not job.reason and not (job.group and job.group.hits):
                job.reason = t("online.cancelled")
    worker.deleteLater()
    return out.get("error")


def error_text(error: str) -> str:
    if error == "401":
        return t("online.bad_key")
    return t("online.no_connection", reason=error)


# --- Auswahl bei mehreren Treffern (L-911) --------------------------------------------------------------------
class ChoiceDialog(QDialog):
    SKIP = 2

    def __init__(self, parent, name: str, hits: list[md.Hit], index: int, total: int) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("online.choose_title", n=index, total=total))
        self.resize(560, 480)
        lay = QVBoxLayout(self)
        intro = QLabel(t("online.choose_intro", name=name), self)
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.list = QListWidget(self)
        self.list.setIconSize(QSize(46, 69))
        for h in hits:
            text = h.title + (f" ({h.year})" if h.year else "")
            if h.original_title and h.original_title != h.title:
                text += "\n" + t("online.original", title=h.original_title)
            item = QListWidgetItem(text, self.list)
            if h.thumb:
                pm = QPixmap()
                pm.loadFromData(QByteArray(h.thumb))
                if not pm.isNull():
                    item.setIcon(QIcon(pm))
            item.setData(Qt.ItemDataRole.UserRole, h)
        self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        lay.addWidget(self.list, 1)
        box = QDialogButtonBox(self)
        box.addButton(t("online.take"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        skip = box.addButton(t("online.skip"), QDialogButtonBox.ButtonRole.ActionRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        skip.clicked.connect(lambda: self.done(self.SKIP))
        lay.addWidget(box)

    def selected(self) -> md.Hit | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None


# --- Übersicht „Feld – bisher – neu“ (L-940 ff.) ----------------------------------------------------------------
def proposals(job: Job) -> list[tuple[str, str, str, object]]:
    """(Schlüssel, bisher, neu, Wert) für alle Felder mit neuem Wert; Cover mit Bilddaten als Wert."""
    m, it = job.movie, job.item
    if m is None:
        return []
    out = []

    def add(key: str, new: str) -> None:
        new = (new or "").strip()
        if not new:
            return
        if it.readonly(key):
            return
        old = it.value(key)
        if old.strip() == new:
            return
        out.append((key, old, new, new))

    add("title", m.title)
    if m.series:  # Folge einer Serie (L-1113)
        add(tg.EXTRA + md.F_SERIES, m.series)
        add(tg.EXTRA + md.F_SEASON, m.season)
        add(tg.EXTRA + md.F_EPISODE, m.episode)
    add("year", m.year)
    add("genre", "; ".join(m.genres))
    add("description", m.overview)
    add("author", "; ".join(m.directors))
    if m.poster and it.record.kind in ("video-mp4", "video-mkv", "video-asf") and not it.readonly("title"):
        has = any(p.ptype == tg.FRONT_COVER for p in it.pictures()) or bool(it.pictures())
        out.append((COVER, t("online.cover_present") if has else "", t("online.poster"), m.poster))
    add(tg.EXTRA + md.F_IMDB, m.imdb)
    add(tg.EXTRA + md.F_TMDB, m.tmdb)
    if m.original_title and m.original_title.casefold() != (m.title or "").casefold():
        add(tg.EXTRA + md.F_ORIG, m.original_title)
    return out


def label(key: str) -> str:
    from .metawizard import column_title

    if key == COVER:
        return t("meta.field.cover")
    if key.startswith(tg.EXTRA):
        return key[len(tg.EXTRA):]
    return column_title(key)


class ReviewDialog(QDialog):
    """Je Film eine Gruppe mit Häkchen je Feld; Vorgabe: nur leere Felder füllen (L-941)."""

    ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent, jobs: list[Job], source: str) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("online.review_title"))
        self.resize(1000, 640)
        self.jobs = jobs
        lay = QVBoxLayout(self)
        found = sum(1 for j in jobs if j.movie is not None)
        intro = QLabel(t("online.review_intro", n=found, total=len(jobs),
                         source=t("online.source_tmdb" if source == md.SOURCE_TMDB else "online.source_wikidata")),
                       self)
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([t("online.col_field"), t("online.col_old"), t("online.col_new")])
        self.tree.setWordWrap(True)
        self.tree.setUniformRowHeights(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tree.setIconSize(QSize(60, 90))
        head = self.tree.header()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        head.setStretchLastSection(True)
        self.tree.setColumnWidth(0, 220)
        self.tree.setColumnWidth(1, 300)
        self.rows: list[tuple[Job, QTreeWidgetItem, str, object]] = []
        for job in jobs:
            self._group(job)
        self.tree.expandAll()
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        b_all = QPushButton(t("online.all_fields"), self)
        b_empty = QPushButton(t("online.empty_fields"), self)
        b_all.clicked.connect(lambda: self.set_all(True))
        b_empty.clicked.connect(lambda: self.set_all(False))
        row.addWidget(b_all)
        row.addWidget(b_empty)
        row.addStretch(1)
        lay.addLayout(row)
        credit = QLabel(t("online.tmdb_notice") if source == md.SOURCE_TMDB else t("online.wikidata_notice"), self)
        credit.setWordWrap(True)
        credit.setEnabled(False)
        lay.addWidget(credit)
        box = QDialogButtonBox(self)
        self.btn_ok = box.addButton(t("online.apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_ok.setDefault(True)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.btn_ok.setEnabled(bool(self.rows))

    def _group(self, job: Job) -> None:
        name = job.item.display_name
        top = QTreeWidgetItem(self.tree)
        font = top.font(0)
        font.setBold(True)
        top.setFont(0, font)
        top.setFirstColumnSpanned(True)
        m = job.movie
        if m is None:
            top.setText(0, f"{name} – {job.reason or t('online.not_found')}")
            top.setForeground(0, self.palette().placeholderText())
            return
        head = m.title + (f" ({m.year})" if m.year else "")
        if m.series:
            head = f"{m.series} – S{m.season}E{m.episode} – {m.title}"
        rows = proposals(job)
        if job.item.readonly("title") and job.item.readonly("year"):
            top.setText(0, f"{name} → {head} – {t('online.readonly')}")
            return
        top.setText(0, f"{name} → {head}" if rows else f"{name} → {head} – {t('online.nothing_new')}")
        for key, old, new, value in rows:
            child = QTreeWidgetItem(top)
            child.setText(0, label(key))
            child.setText(1, old)
            child.setToolTip(1, old)
            child.setText(2, new)
            child.setToolTip(2, new)
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child.setCheckState(0, Qt.CheckState.Unchecked if old else Qt.CheckState.Checked)  # L-941, L-942
            child.setData(0, self.ROLE, bool(old))
            if key == COVER:
                pm = QPixmap()
                pm.loadFromData(QByteArray(value))
                if not pm.isNull():
                    child.setIcon(2, QIcon(pm))
            self.rows.append((job, child, key, value))

    def set_all(self, overwrite: bool) -> None:
        for _job, child, _key, _value in self.rows:
            on = overwrite or not child.data(0, self.ROLE)
            child.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def changes(self) -> list[tuple[object, dict, bytes | None]]:
        """(Eintrag, {Feld: Wert}, Poster oder None) für alle angehakten Zeilen."""
        out: dict[int, list] = {}
        for job, child, key, value in self.rows:
            if child.checkState(0) != Qt.CheckState.Checked:
                continue
            entry = out.setdefault(id(job), [job.item, {}, None])
            if key == COVER:
                entry[2] = value
            else:
                entry[1][key] = value
        return [tuple(v) for v in out.values()]
