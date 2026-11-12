"""Fenster für die MusicBrainz-Übernahme (v1.2): Suche, Trefferliste, Zuordnung und Feldauswahl."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from . import musicbrainz as mb
from .dialogs import free_window
from .i18n import t

YELLOW = QColor("#FFF59D")
MATCH = QColor("#C8E6C9")
LENGTH_TOLERANCE = 5.0  # Sekunden


def fmt_length(seconds: float | None) -> str:
    if not seconds:
        return "–:––"
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


# --- 1. Suche -----------------------------------------------------------------------------------------
class SearchDialog(QDialog):
    def __init__(self, parent, album: str, artist: str, count: int) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("mb.title"))
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        intro = QLabel(t("mb.search_intro", n=count), self)
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.album = QLineEdit(album, self)
        self.artist = QLineEdit(artist, self)
        form.addRow(t("mb.album"), self.album)
        form.addRow(t("mb.artist"), self.artist)
        lay.addLayout(form)
        box = QDialogButtonBox(self)
        self.btn_next = box.addButton(t("mb.next"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_next.setDefault(True)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        for e in (self.album, self.artist):
            e.textChanged.connect(self._update)
        self._update()

    def _update(self, *_a) -> None:
        self.btn_next.setEnabled(bool(self.album.text().strip() or self.artist.text().strip()))

    def terms(self) -> tuple[str, str]:
        return self.album.text().strip(), self.artist.text().strip()


# --- 2. Treffer ---------------------------------------------------------------------------------------
class _NumItem(QTableWidgetItem):
    def __init__(self, value: int) -> None:
        super().__init__(str(value))
        self.setData(Qt.ItemDataRole.UserRole, value)
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other) -> bool:
        a, b = self.data(Qt.ItemDataRole.UserRole), other.data(Qt.ItemDataRole.UserRole)
        if isinstance(a, int) and isinstance(b, int):
            return a < b
        return super().__lt__(other)


class ResultsDialog(QDialog):
    BACK = 2
    COLUMNS = ("score", "type", "artist", "album", "tracks", "year", "country", "format", "label", "catno")

    def __init__(self, parent, hits: list[mb.SearchHit], count: int) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("mb.title"))
        self.resize(1100, 560)
        self.hits = hits
        lay = QVBoxLayout(self)
        info = QLabel(t("mb.results_info", n=len(hits), files=count) if hits else t("mb.no_results"), self)
        info.setWordWrap(True)
        lay.addWidget(info)
        self.table = QTableWidget(len(hits), len(self.COLUMNS), self)
        self.table.setHorizontalHeaderLabels([t(f"mb.col_{c}") for c in self.COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        for row, h in enumerate(hits):
            values = (h.score, h.type, h.artist, h.album, h.tracks, h.year, h.country, h.format, h.label, h.catno)
            for col, v in enumerate(values):
                item = _NumItem(v) if isinstance(v, int) else QTableWidgetItem(v)
                item.setData(Qt.ItemDataRole.UserRole + 1, row)
                if h.tracks == count:
                    item.setBackground(QBrush(MATCH))
                    item.setToolTip(t("mb.tracks_match"))
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self.table.sortItems(0, Qt.SortOrder.DescendingOrder)  # bester Treffer oben
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.resizeColumnsToContents()
        for col in (2, 3):
            header.resizeSection(col, min(max(header.sectionSize(col), 120), 300))
        header.setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _i: self.accept() if self.selected() else None)
        lay.addWidget(self.table, 1)
        legend = QLabel(t("mb.legend"), self)
        legend.setEnabled(False)
        lay.addWidget(legend)
        box = QDialogButtonBox(self)
        back = box.addButton(t("mb.back"), QDialogButtonBox.ButtonRole.ResetRole)
        self.btn_next = box.addButton(t("mb.next"), QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_next.setDefault(True)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        back.clicked.connect(lambda: self.done(self.BACK))
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.table.itemSelectionChanged.connect(self._update)
        if hits:
            best = next((r for r in range(self.table.rowCount())
                         if self.table.item(r, 4).data(Qt.ItemDataRole.UserRole) == count), 0)
            self.table.selectRow(best)
        self._update()

    def _update(self) -> None:
        self.btn_next.setEnabled(self.selected() is not None)

    def selected(self) -> mb.SearchHit | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.hits[self.table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole + 1)]


# --- 3. Übernehmen ------------------------------------------------------------------------------------
def cover_mime(data: bytes) -> str:
    return "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


class ApplyDialog(QDialog):
    """Zuordnung MusicBrainz-Titel ↔ Dateien und Auswahl der Felder (wie Textdatei → Tag)."""

    def __init__(self, parent, release: mb.Release, cover: bytes | None, items, settings: dict) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("mb.apply_title", album=release.title))
        self.resize(1100, 760)
        self.release = release
        self.cover = cover
        self.left, self.right = mb.initial_pairs(release.tracks, items)
        self._pad()
        checked = settings.get("fields")
        checked = set(checked) if isinstance(checked, list) else {f.id for f in mb.FIELDS}
        lay = QVBoxLayout(self)
        split = QSplitter(Qt.Orientation.Vertical, self)
        lay.addWidget(split, 1)

        # oben: Felder und Cover
        top = QWidget(split)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(0, 0, 0, 0)
        self.track_table = self._field_table(top, "track", checked)
        self.album_table = self._field_table(top, "album", checked)
        for tbl, title in ((self.track_table, t("mb.track_fields")), (self.album_table, t("mb.album_fields"))):
            box = QVBoxLayout()
            box.addWidget(QLabel(f"<b>{title}</b>", top))
            box.addWidget(tbl, 1)
            tl.addLayout(box, 1)
        for row, f in enumerate(self._fields("album")):
            self.album_table.item(row, 1).setText(release.album_values.get(f.id, ""))
        cbox = QVBoxLayout()
        self.cover_check = QCheckBox(t("mb.cover"), top)
        self.cover_label = QLabel(top)
        self.cover_label.setFixedSize(220, 220)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet("border: 1px solid palette(mid);")
        img = QImage.fromData(QByteArray(cover)) if cover else QImage()
        if not img.isNull():
            self.cover_label.setPixmap(QPixmap.fromImage(img).scaled(
                216, 216, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.cover_label.setToolTip(f"{img.width()} × {img.height()}")
            self.cover_check.setChecked(bool(settings.get("cover", True)))
        else:
            self.cover_label.setText(t("mb.no_cover"))
            self.cover_check.setEnabled(False)
        cbox.addWidget(self.cover_check)
        cbox.addWidget(self.cover_label)
        cbox.addStretch(1)
        tl.addLayout(cbox)

        # unten: Zuordnung
        bottom = QWidget(split)
        grid = QGridLayout(bottom)
        grid.setContentsMargins(0, 0, 0, 0)
        hint = QLabel(t("mb.assign_hint"), bottom)
        hint.setWordWrap(True)
        hint.setEnabled(False)
        grid.addWidget(hint, 0, 0, 1, 2)
        grid.addWidget(QLabel(f"<b>{t('mb.mb_tracks')}</b>", bottom), 1, 0)
        grid.addWidget(QLabel(f"<b>{t('textimp.files')}</b>", bottom), 1, 1)
        self.list_left = QListWidget(bottom)
        self.list_right = QListWidget(bottom)
        grid.addWidget(self.list_left, 2, 0)
        grid.addWidget(self.list_right, 2, 1)
        for col, side in ((0, "left"), (1, "right")):
            b = QHBoxLayout()
            for text, fn in ((t("meta.field_up"), lambda s=side: self._move(s, -1)),
                             (t("meta.field_down"), lambda s=side: self._move(s, 1)),
                             (t("textimp.insert_skip"), lambda s=side: self._insert_skip(s)),
                             (t("textimp.remove_skip"), lambda s=side: self._remove_skip(s))):
                btn = QPushButton(text, bottom)
                btn.clicked.connect(fn)
                b.addWidget(btn)
            b.addStretch(1)
            grid.addLayout(b, 3, col)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([440, 300])

        box = QDialogButtonBox(self)
        box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.list_left.currentRowChanged.connect(lambda r: self._sync(self.list_right, r))
        self.list_right.currentRowChanged.connect(lambda r: self._sync(self.list_left, r))
        self.list_left.verticalScrollBar().valueChanged.connect(self.list_right.verticalScrollBar().setValue)
        self.list_right.verticalScrollBar().valueChanged.connect(self.list_left.verticalScrollBar().setValue)
        self.track_table.itemChanged.connect(self._track_value_edited)
        self._refresh()
        if self.list_left.count():
            self._select(0)

    # Felder
    @staticmethod
    def _fields(level: str) -> list[mb.MBField]:
        return [f for f in mb.FIELDS if f.level == level]

    def _field_table(self, parent, level: str, checked: set[str]) -> QTableWidget:
        fields = self._fields(level)
        tbl = QTableWidget(len(fields), 2, parent)
        tbl.setHorizontalHeaderLabels([t("mb.field"), t("mb.value")])
        tbl.verticalHeader().setVisible(False)
        tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tbl.horizontalHeader().setStretchLastSection(True)
        tbl.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
                            | QAbstractItemView.EditTrigger.SelectedClicked)
        for row, f in enumerate(fields):
            name = QTableWidgetItem(f.id)
            name.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsSelectable)
            name.setCheckState(Qt.CheckState.Checked if f.id in checked else Qt.CheckState.Unchecked)
            name.setData(Qt.ItemDataRole.UserRole, f.id)
            tbl.setItem(row, 0, name)
            tbl.setItem(row, 1, QTableWidgetItem(""))
        return tbl

    def checked_fields(self) -> list[str]:
        out = []
        for tbl in (self.track_table, self.album_table):
            for row in range(tbl.rowCount()):
                item = tbl.item(row, 0)
                if item.checkState() == Qt.CheckState.Checked:
                    out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def settings(self) -> dict:
        return {"fields": self.checked_fields(), "cover": self.cover_check.isChecked() or not self.cover_check.isEnabled()}

    def set_checked(self, field_id: str, on: bool) -> None:
        for tbl in (self.track_table, self.album_table):
            for row in range(tbl.rowCount()):
                if tbl.item(row, 0).data(Qt.ItemDataRole.UserRole) == field_id:
                    tbl.item(row, 0).setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _show_track_values(self) -> None:
        i = self.list_left.currentRow()
        track = self.left[i] if 0 <= i < len(self.left) else None
        self.track_table.blockSignals(True)
        for row, f in enumerate(self._fields("track")):
            cell = self.track_table.item(row, 1)
            cell.setText(track.values.get(f.id, "") if track else "")
            flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            cell.setFlags(flags | Qt.ItemFlag.ItemIsEditable if track else flags)
        self.track_table.blockSignals(False)

    def _track_value_edited(self, cell: QTableWidgetItem) -> None:
        if cell.column() != 1:
            return
        i = self.list_left.currentRow()
        if 0 <= i < len(self.left) and self.left[i] is not None:
            fid = self.track_table.item(cell.row(), 0).data(Qt.ItemDataRole.UserRole)
            self.left[i].values[fid] = cell.text()
            if fid == "TITLE":
                self._refresh()

    # Zuordnung
    def _pad(self) -> None:
        n = max(len(self.left), len(self.right))
        self.left += [None] * (n - len(self.left))
        self.right += [None] * (n - len(self.right))
        while self.left and self.left[-1] is None and self.right[-1] is None:
            self.left.pop()
            self.right.pop()

    def _track_text(self, tr: mb.MBTrack) -> str:
        prefix = f"{tr.disc}-{tr.number:02d}" if len({x.disc for x in self.release.tracks}) > 1 else f"{tr.number:02d}"
        return f"{prefix}  {tr.values.get('TITLE', tr.title)}  ({fmt_length(tr.length)})"

    @staticmethod
    def _file_text(it) -> str:
        return f"{it.display_name}  ({fmt_length(it.record.length)})"

    @staticmethod
    def length_differs(track, it) -> bool:
        if track is None or it is None or not track.length or not it.record.length:
            return False
        return abs(track.length - it.record.length) > LENGTH_TOLERANCE

    def _refresh(self) -> None:
        self._pad()
        cur = max(self.list_left.currentRow(), 0)
        skip = t("textimp.skipped")
        for widget, values, text_of in ((self.list_left, self.left, self._track_text),
                                        (self.list_right, self.right, self._file_text)):
            widget.blockSignals(True)
            widget.clear()
            for v in values:
                item = QListWidgetItem(skip if v is None else text_of(v))
                if v is None:
                    item.setForeground(Qt.GlobalColor.gray)
                    f = item.font()
                    f.setItalic(True)
                    item.setFont(f)
                widget.addItem(item)
            widget.blockSignals(False)
        for i, (tr, it) in enumerate(zip(self.left, self.right)):
            if self.length_differs(tr, it):
                for w in (self.list_left, self.list_right):
                    w.item(i).setBackground(QBrush(YELLOW))
                    w.item(i).setForeground(QBrush(QColor("black")))
                    w.item(i).setToolTip(t("mb.length_differs"))
        if self.list_left.count():
            self._select(min(cur, self.list_left.count() - 1))

    def _select(self, row: int) -> None:
        for w in (self.list_left, self.list_right):
            w.blockSignals(True)
            w.setCurrentRow(row)
            w.blockSignals(False)
        self._show_track_values()

    def _sync(self, other: QListWidget, row: int) -> None:
        if row >= 0:
            other.blockSignals(True)
            other.setCurrentRow(row)
            other.blockSignals(False)
        self._show_track_values()

    def _lists(self, side: str):
        return (self.left, self.list_left) if side == "left" else (self.right, self.list_right)

    def _move(self, side: str, delta: int) -> None:
        values, widget = self._lists(side)
        i = widget.currentRow()
        j = i + delta
        if not (0 <= i < len(values) and 0 <= j < len(values)):
            return
        values[i], values[j] = values[j], values[i]
        self._refresh()
        self._select(j)

    def _insert_skip(self, side: str) -> None:
        values, widget = self._lists(side)
        i = max(widget.currentRow(), 0)
        values.insert(i, None)
        self._refresh()
        self._select(i)

    def _remove_skip(self, side: str) -> None:
        values, widget = self._lists(side)
        i = widget.currentRow()
        if 0 <= i < len(values) and values[i] is None:
            del values[i]
            self._refresh()
            self._select(min(i, max(len(self.left) - 1, 0)))

    # Ergebnis
    def album_values(self) -> dict[str, str]:
        out = {}
        for row, f in enumerate(self._fields("album")):
            out[f.id] = self.album_table.item(row, 1).text().strip()
        return out

    def changes(self) -> list[tuple[object, dict[str, str]]]:
        """(Datei, {Feld-ID: Wert}) für jede zugeordnete Datei – nur angehakte Felder mit Wert."""
        checked = set(self.checked_fields())
        album = {k: v for k, v in self.album_values().items() if k in checked and v}
        result = []
        for tr, it in zip(self.left, self.right):
            if tr is None or it is None:
                continue
            values = {k: v.strip() for k, v in tr.values.items() if k in checked and v.strip()}
            values.update(album)
            result.append((it, values))
        return result

    def cover_data(self) -> bytes | None:
        return self.cover if self.cover and self.cover_check.isChecked() else None
