"""Fenster für „Online-Daten“ im Video-Modus (v1.9): Abfrage im Hintergrund, Auswahl, Übersicht."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QByteArray, QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTreeWidget, QTreeWidgetItem,
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
    imdb: str = ""  # v2.3: Kennungen aus Ordner/Datei (wie Jellyfin), TMDb löst sie zur Serie auf
    tvdb: str = ""


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
    tvdb: str = ""  # v2.3


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
        group.imdb = group.imdb or ref.imdb
        group.tvdb = group.tvdb or ref.tvdb
        jobs.append(Job(it, title=ref.series, year=ref.year, ep=ref, group=group))
    return jobs


def make_job(item) -> Job:
    """Kennung aus eigenen Feldern, sonst aus dem Dateinamen, sonst Titel und Jahr (L-910)."""
    import os

    name = item.display_name
    imdb = md.clean_imdb(item.value(tg.EXTRA + md.F_IMDB))
    tmdb = md.clean_tmdb(item.value(tg.EXTRA + md.F_TMDB))
    n_imdb, n_tmdb, n_tvdb = md.all_ids_from_name(name)
    if not (n_imdb or n_tmdb or n_tvdb):  # v2.3: sonst aus dem Ordner darüber (Jellyfin: „Alien (1979) [imdbid-…]/“)
        folder = os.path.basename(os.path.dirname(getattr(item.record, "path", "") or ""))
        n_imdb, n_tmdb, n_tvdb = md.all_ids_from_name(folder)
    title, year = md.title_year(name)
    return Job(item, imdb or n_imdb, tmdb or n_tmdb, title, year, tvdb=n_tvdb)


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
        if job.tvdb and not (job.imdb or job.tmdb or job.qid) and isinstance(self.service, md.Tmdb):
            job.tmdb = self.service.find_external(job.tvdb, "tvdb_id")  # v2.3
            if not job.tmdb:
                job.reason = t("online.not_found")
                return
        if job.imdb or job.tmdb or job.qid:
            job.movie = self.service.load(job.imdb, job.tmdb, job.qid)
            if job.movie is None:
                job.reason = t("online.not_found")
            return
        if not job.title:
            job.reason = t("online.no_id")
            return
        hits = md.search_fallback(self.service.search, job.title, job.year)  # L-1430
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
        if not g.tmdb and not g.searched and (g.imdb or g.tvdb):
            g.tmdb = (self.service.find_external(g.imdb, "imdb_id", tv=True) if g.imdb else "") or \
                (self.service.find_external(g.tvdb, "tvdb_id", tv=True) if g.tvdb else "")  # v2.3
        if not g.tmdb and not g.searched:
            g.searched = True
            hits = md.search_fallback(self.service.search_tv, g.name, g.year)
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
    MANUAL = 3  # v2.2.1: „Manuell suchen …“ – keiner der Treffer passt

    def __init__(self, parent, name: str, hits: list[md.Hit], index: int, total: int, manual: bool = False) -> None:
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
        if manual:
            search = box.addButton(t("online.manual"), QDialogButtonBox.ButtonRole.ActionRole)
            search.clicked.connect(lambda: self.done(self.MANUAL))
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
    add(tg.EXTRA + md.F_ACTORS, "; ".join(m.actors))  # L-1433
    add(tg.EXTRA + md.F_RATING, m.rating)
    add(tg.EXTRA + md.F_CERT, m.certification)
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

    def __init__(self, parent, jobs: list[Job], source: str, service=None) -> None:
        super().__init__(parent)
        free_window(self)
        self.service = service  # v1.14: für „Manuell suchen …“ (L-1431)
        self.setWindowTitle(t("online.review_title"))
        self.resize(1000, 640)
        self.jobs = jobs
        self.source = source
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
        self.tops: dict[int, Job] = {}
        for job in jobs:
            self._group(job)
        self.tree.expandAll()
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.tree, 1)
        self.intro = intro
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
        self.tops[id(top)] = job
        m = job.movie
        if m is None:
            top.setText(0, f"{name} – {job.reason or t('online.not_found')}")
            top.setForeground(0, self.palette().placeholderText())
            if self.service is not None and not job.item.readonly("title"):
                holder = QTreeWidgetItem(top)
                btn = QPushButton(t("online.manual"), self.tree)
                btn.clicked.connect(lambda _c=False, j=job: self.manual(j))
                self.tree.setItemWidget(holder, 0, btn)
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

    # --- Manuelle Suche (v1.14, L-1431/L-1432) -------------------------------------------------
    def _menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        item = self.tree.itemAt(pos)
        while item is not None and item.parent() is not None:
            item = item.parent()
        job = self.tops.get(id(item)) if item is not None else None
        if job is None or self.service is None:
            return
        menu = QMenu(self)
        text = t("online.other_series") if job.ep is not None else t("online.other_movie")
        menu.addAction(text).triggered.connect(lambda: self.manual(job))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def manual(self, job: Job) -> None:
        if manual_lookup(self, self.service, self.jobs, job) == "done":
            self.rebuild()

    def rebuild(self) -> None:
        """Baum neu aufbauen; Häkchen bleiben, soweit es die Zeile schon gab."""
        states = {(id(j), key): child.checkState(0) for j, child, key, _v in self.rows}
        self.tree.clear()
        self.rows, self.tops = [], {}
        for job in self.jobs:
            self._group(job)
        for j, child, key, _v in self.rows:
            if (id(j), key) in states:
                child.setCheckState(0, states[(id(j), key)])
        self.tree.expandAll()
        found = sum(1 for j in self.jobs if j.movie is not None)
        self.intro.setText(t("online.review_intro", n=found, total=len(self.jobs),
                             source=t("online.source_tmdb" if self.source == md.SOURCE_TMDB
                                      else "online.source_wikidata")))
        self.btn_ok.setEnabled(bool(self.rows))

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


def auto_changes(jobs: list[Job], overwrite: bool) -> list[tuple[object, dict, bytes | None]]:
    """v1.20 (L-2020): ohne Übersicht – nur leere Felder oder alles (samt Poster), wie „changes()“."""
    out = []
    for job in jobs:
        if job.movie is None or (job.item.readonly("title") and job.item.readonly("year")):
            continue
        values, poster = {}, None
        for key, old, _new, value in proposals(job):
            if old and not overwrite:
                continue
            if key == COVER:
                poster = value
            else:
                values[key] = value
        if values or poster:
            out.append((job.item, values, poster))
    return out


def auto_report(jobs: list[Job], changes: list) -> str:
    """L-2022: kurze Meldung mit Zahlen und den Gründen für nicht übernommene Filme."""
    taken = {id(it) for it, _v, _p in changes}
    skipped = [j for j in jobs if j.movie is None and j.reason == t("online.skipped")]
    missing = [j for j in jobs if j.movie is None and j not in skipped]
    unchanged = [j for j in jobs if j.movie is not None and id(j.item) not in taken]
    lines = [t("online.auto_done", taken=len(taken), missing=len(missing), skipped=len(skipped))]
    if unchanged:
        lines.append(t("online.auto_unchanged", n=len(unchanged)))
    if missing or skipped:
        lines.append("")
        for j in missing + skipped:
            lines.append(f"• {j.item.display_name}: {j.reason or t('online.not_found')}")
    lines.append("")
    lines.append(t("online.auto_hint"))
    return "\n".join(lines)


def manual_lookup(parent, service, jobs: list[Job], job: Job, heading: str = "", allow_skip: bool = False) -> str:
    """Manuelle Suche für einen Film bzw. eine Serie (L-1431/L-1432, v2.2.1 auch ohne Übersicht).

    Ergebnis: "done" (gesucht und geladen), "skip" (Überspringen), "cancel" (Suche abgebrochen),
    "none" (nichts gefunden bzw. nichts gewählt).
    """
    from .dialogs import show_error, show_info

    dlg = ManualSearchDialog(parent, job, heading, allow_skip)
    res = dlg.exec()
    if res == ManualSearchDialog.SKIP:
        return "skip"
    if res != QDialog.DialogCode.Accepted:
        return "cancel"
    title, year, ident = dlg.values()
    series = job.ep is not None
    if series and not isinstance(service, md.Tmdb):
        show_error(parent, t("online.title"), t("online.series_no_key"))
        return "none"
    imdb, tmdb = md.clean_imdb(ident), (ident.strip() if ident.strip().isdigit() else "")

    def find():
        if imdb or tmdb:
            return []
        search = service.search_tv if series else service.search
        hits = md.search_fallback(search, title, year)
        _thumbs(hits[:8])
        return hits[:12]

    hits, error = netutil.run_blocking(parent, find, t("online.searching"), t("online.title"))
    if error:
        show_error(parent, t("online.title"), error_text(error))
        return "none"
    if not imdb and not tmdb:
        if not hits:
            show_info(parent, t("online.title"), t("online.manual_none", title=title))
            return "none"
        choice = ChoiceDialog(parent, title, hits, 1, 1)
        if choice.exec() != QDialog.DialogCode.Accepted or choice.selected() is None:
            return "none"
        hit = choice.selected()
        imdb, tmdb, qid = hit.imdb, hit.tmdb, hit.qid
    else:
        qid = ""
    targets = [j for j in jobs if j.group is job.group] if series else [job]

    def load():
        if series:
            tv = tmdb or (service.find_imdb(imdb, tv=True) if imdb else "")
            if not tv:
                for j in targets:
                    j.movie, j.reason = None, t("online.not_found")
                return True
            job.group.tmdb, job.group.hits, job.group.reason = tv, [], ""
            for j in targets:
                j.movie = service.episode(tv, j.ep.season, j.ep.episode)
                j.reason = "" if j.movie else t("online.episode_not_found", s=f"{j.ep.season:02d}",
                                                     e=f"{j.ep.episode:02d}")
        else:
            job.imdb, job.tmdb, job.qid = imdb, tmdb, qid
            job.movie = service.load(imdb, tmdb, qid)
            job.reason = "" if job.movie else t("online.not_found")
        return True

    _ok, error = netutil.run_blocking(parent, load, t("online.loading"), t("online.title"))
    if error:
        show_error(parent, t("online.title"), error_text(error))
        return "none"
    return "done"


class ManualSearchDialog(QDialog):
    """Titel und Jahr bzw. Kennung eingeben (L-1431)."""

    SKIP = 2

    def __init__(self, parent, job: Job, heading: str = "", allow_skip: bool = False) -> None:
        from PySide6.QtWidgets import QFormLayout

        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(heading or t("online.manual_title"))
        self.resize(520, 200)
        lay = QVBoxLayout(self)
        intro = QLabel(t("online.manual_intro_series" if job.ep is not None else "online.manual_intro",
                         name=job.item.display_name), self)
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        title = job.group.name if job.group is not None else job.title
        year = job.group.year if job.group is not None else job.year
        self.ed_title = QLineEdit(md.title_variants(title)[-1] if title else "", self)
        self.ed_year = QLineEdit(year or "", self)
        self.ed_year.setMaxLength(4)
        self.ed_id = QLineEdit(self)
        self.ed_id.setPlaceholderText(t("online.manual_id_hint"))
        form.addRow(t("online.manual_field_title"), self.ed_title)
        form.addRow(t("online.manual_field_year"), self.ed_year)
        form.addRow(t("online.manual_field_id"), self.ed_id)
        lay.addLayout(form)
        box = QDialogButtonBox(self)
        box.addButton(t("online.manual_search"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        if allow_skip:  # v2.2.1: nicht gefundene Filme ohne Übersicht nacheinander
            box.addButton(t("online.skip"), QDialogButtonBox.ButtonRole.ActionRole).clicked.connect(
                lambda: self.done(self.SKIP))
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.ed_title.selectAll()

    def values(self) -> tuple[str, str, str]:
        return self.ed_title.text().strip(), self.ed_year.text().strip(), self.ed_id.text().strip()
