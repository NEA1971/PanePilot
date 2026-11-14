"""Meta-Wizard v0.9.3: Tags als Textdatei/CSV exportieren und importieren (mit Zuordnungsfenster),
Nummerierungs-Assistent, Playlist-Generator (M3U8)."""

from __future__ import annotations

import csv
import datetime as _dt
import io
import os
import re
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
)

from . import convert as cv
from . import metaprofile as mp
from . import tags as tg
from .dialogs import free_window
from .i18n import t

REMOVE_MARKERS = {"<entfernen>", "<remove>"}


def is_remove(cell: str) -> bool:
    """„<entfernen>“ (auch in der eingestellten Sprache, z. B. „<remove>“) löscht ein Feld."""
    text = cell.strip().casefold()
    return text in REMOVE_MARKERS or text == t("meta.remove").replace(" ", "").casefold()
READONLY_COLUMNS = {"filename", "path"}  # beim Import ignoriert (Infos „i:…“ ebenso)


# --- Export (Tag → Textdatei/CSV) ----------------------------------------------------------------------
def next_export_name(folder: str, day: _dt.date | None = None) -> str:
    """Tags_JJJJ-MM-TTa.txt, bei Belegung b, c, …"""
    day = day or _dt.date.today()
    for i in range(26 * 27):
        suffix = chr(97 + i) if i < 26 else chr(96 + i // 26) + chr(97 + i % 26)
        name = f"Tags_{day.isoformat()}{suffix}"
        if not any(os.path.exists(os.path.join(folder, name + ext)) for ext in (".txt", ".csv")):
            return name
    return f"Tags_{day.isoformat()}"


def export_table(items, columns: list[str], model) -> tuple[list[str], list[list[str]]]:
    from .metawizard import column_title

    header = [column_title(c) for c in columns]
    rows = []
    for it in items:
        row = []
        for c in columns:
            if c == "filename":
                row.append(it.display_name)
            elif c == "path" or c.startswith("i:"):
                row.append(model.text(it, c))
            else:
                row.append(it.value(c))
        rows.append(row)
    return header, rows


def write_table(path: str, header: list[str], rows: list[list[str]]) -> None:
    delimiter = ";" if path.lower().endswith(".csv") else "\t"
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
        w.writerow(header)
        w.writerows(rows)


# --- Import (Textdatei → Tag) ---------------------------------------------------------------------------
def column_lookup(extra_labels: list[str]) -> dict[str, str]:
    """Spaltenüberschrift (Anzeigename oder Kennung) → Spalte."""
    from .metawizard import column_title

    lookup: dict[str, str] = {}
    for c in ("filename", "path", *mp.fields(), *mp.info_columns()):
        lookup[column_title(c).casefold()] = c
        lookup[c.casefold()] = c
    for label in extra_labels:
        lookup.setdefault(label.casefold(), tg.EXTRA + label)
    return lookup


@dataclass
class TextData:
    header: list[str] | None  # Spalten (Kennungen) im Tabellenmodus, None = einfache Liste
    rows: list[list[str]]  # Tabellenmodus: Zellen; Liste: [Zeile]


def read_text_file(path: str, extra_labels: list[str]) -> TextData:
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    lines = text.splitlines()
    first = next((ln for ln in lines if ln.strip()), "")
    delimiter = "\t" if "\t" in first else (";" if ";" in first else None)
    lookup = column_lookup(extra_labels)
    if delimiter:
        table = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        table = [r for r in table if any(c.strip() for c in r)]
        if table and any(c.strip().casefold() in lookup for c in table[0]):
            header = []
            for cell in table[0]:
                name = cell.strip()
                col = lookup.get(name.casefold())
                if col is None and tg.valid_field_name(name):
                    col = tg.EXTRA + name  # unbekannte Überschrift = eigenes Feld
                header.append(col or "")
            return TextData(header, table[1:])
    return TextData(None, [[ln.strip()] for ln in lines if ln.strip()])


def row_values(data: TextData, row: list[str], fmt: str) -> dict[str, str | None] | None:
    """Werte einer Zeile; leere Zelle = unverändert, „<entfernen>“ = Feld löschen. None = passt nicht."""
    if data.header is None:
        parsed = cv.parse_filename(row[0], fmt) if fmt.strip() else None
        if parsed is None:
            return None
        values = {}
        for name, v in parsed.items():
            if not name.startswith("_"):
                values[name if name in mp.fields() else tg.EXTRA + name] = v
        return {k: (None if is_remove(v) else v) for k, v in values.items() if v.strip()}
    values: dict[str, str | None] = {}
    for col, cell in zip(data.header, row):
        if not col or col in READONLY_COLUMNS or col.startswith("i:"):
            continue
        if not cell.strip():
            continue
        values[col] = None if is_remove(cell) else cell
    return values


def initial_order(data: TextData, items) -> tuple[list, list]:
    """Startzuordnung: im Tabellenmodus über Dateiname (und Pfad), sonst in Dateireihenfolge.

    Liefert zwei gleich lange Listen (Titel bzw. Zeilenindex), None = „übersprungen“."""
    rows = list(range(len(data.rows)))
    if data.header is None or "filename" not in data.header:
        return list(items), rows
    fi = data.header.index("filename")
    pi = data.header.index("path") if "path" in data.header else None
    by_key: dict[tuple[str, str], int] = {}
    by_name: dict[str, list[int]] = {}
    for r, row in enumerate(data.rows):
        name = row[fi].strip() if fi < len(row) else ""
        folder = row[pi].strip() if pi is not None and pi < len(row) else ""
        by_key.setdefault((folder, name), r)
        by_name.setdefault(name, []).append(r)
    used: set[int] = set()
    left, right = [], []
    for it in items:
        r = by_key.get((it.folder(), it.display_name))
        if r is None or r in used:
            r = next((x for x in by_name.get(it.display_name, []) if x not in used), None)
        left.append(it)
        right.append(r)
        if r is not None:
            used.add(r)
    for r in rows:  # übrige Zeilen ans Ende, gegenüber „übersprungen“
        if r not in used:
            left.append(None)
            right.append(r)
    return left, right


class ImportDialog(QDialog):
    """Zuordnung Dateien ↔ Zeilen wie bei MP3TAG: verschieben, „übersprungen“ einfügen (v0.9.3)."""

    def __init__(self, parent, items, data: TextData, presets: list[dict], last: str, insert_menu) -> None:
        from .metawizard import column_title

        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("conv.text2tag").replace(" …", ""))
        self.resize(900, 600)
        self.data = data
        self.column_title = column_title
        self.left, self.right = initial_order(data, items)
        self.fmt_combo = None
        lay = QVBoxLayout(self)
        if data.header is None:
            lay.addWidget(QLabel(t("textimp.format"), self))
            self.fmt_combo = QComboBox(self)
            self.fmt_combo.setEditable(True)
            self.fmt_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            mono = QFont("monospace")
            mono.setStyleHint(QFont.StyleHint.Monospace)
            self.fmt_combo.setFont(mono)
            for p in presets:
                self.fmt_combo.addItem(p["format"])
            self.fmt_combo.setEditText(last or (presets[0]["format"] if presets else "%track%. %title%"))
            self.fmt_combo.editTextChanged.connect(self._refresh)
            ins = QToolButton(self)
            ins.setText("▸")
            ins.clicked.connect(lambda: insert_menu(self.fmt_combo.lineEdit(), ins))
            row = QHBoxLayout()
            row.addWidget(self.fmt_combo, 1)
            row.addWidget(ins)
            lay.addLayout(row)
        else:
            known = [column_title(c) if not c.startswith(tg.EXTRA) else tg.label_of(c)
                     for c in data.header if c and c not in READONLY_COLUMNS and not c.startswith("i:")]
            info = QLabel(t("textimp.columns", cols=", ".join(known)), self)
            info.setWordWrap(True)
            lay.addWidget(info)
        hint = QLabel(t("textimp.hint"), self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        lay.addWidget(hint)
        self.list_left = QListWidget(self)
        self.list_right = QListWidget(self)
        grid = QGridLayout()
        grid.addWidget(QLabel(t("textimp.files"), self), 0, 0)
        grid.addWidget(QLabel(t("textimp.lines"), self), 0, 1)
        grid.addWidget(self.list_left, 1, 0)
        grid.addWidget(self.list_right, 1, 1)
        for col, side in ((0, "left"), (1, "right")):
            b = QHBoxLayout()
            for text, fn in ((t("meta.field_up"), lambda s=side: self._move(s, -1)),
                             (t("meta.field_down"), lambda s=side: self._move(s, 1)),
                             (t("textimp.insert_skip"), lambda s=side: self._insert_skip(s)),
                             (t("textimp.remove_skip"), lambda s=side: self._remove_skip(s))):
                btn = QPushButton(text, self)
                btn.clicked.connect(fn)
                b.addWidget(btn)
            b.addStretch(1)
            grid.addLayout(b, 2, col)
        lay.addLayout(grid, 1)
        self.preview = QLabel(self)
        self.preview.setWordWrap(True)
        self.preview.setTextFormat(Qt.TextFormat.RichText)
        self.preview.setMinimumHeight(48)
        lay.addWidget(self.preview)
        box = QDialogButtonBox(self)
        self.btn_ok = box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.list_left.currentRowChanged.connect(lambda r: self._sync(self.list_right, r))
        self.list_right.currentRowChanged.connect(lambda r: self._sync(self.list_left, r))
        self.list_left.verticalScrollBar().valueChanged.connect(self.list_right.verticalScrollBar().setValue)
        self.list_right.verticalScrollBar().valueChanged.connect(self.list_left.verticalScrollBar().setValue)
        self._refresh()
        if self.list_left.count():
            self.list_left.setCurrentRow(0)

    # Darstellung
    def format_string(self) -> str:
        return self.fmt_combo.currentText() if self.fmt_combo is not None else ""

    def _pad(self) -> None:
        n = max(len(self.left), len(self.right))
        self.left += [None] * (n - len(self.left))
        self.right += [None] * (n - len(self.right))
        while self.left and self.left[-1] is None and self.right[-1] is None:
            self.left.pop()
            self.right.pop()

    def _row_text(self, r) -> str:
        row = self.data.rows[r]
        if self.data.header is None:
            return row[0]
        return " | ".join(c for c in row if c.strip())

    def _refresh(self) -> None:
        self._pad()
        cur = max(self.list_left.currentRow(), 0)
        skip = t("textimp.skipped")
        fmt = self.format_string()
        for widget, values, text_of in ((self.list_left, self.left, lambda it: it.display_name),
                                        (self.list_right, self.right, self._row_text)):
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
        bad = 0
        for i, (it, r) in enumerate(zip(self.left, self.right)):
            if it is not None and r is not None:
                try:
                    ok = row_values(self.data, self.data.rows[r], fmt) is not None
                except cv.FormatError:
                    ok = False
                if not ok:
                    bad += 1
                    self.list_right.item(i).setForeground(Qt.GlobalColor.red)
        self.btn_ok.setEnabled(self.data.header is not None or bool(fmt.strip()))
        if self.list_left.count():
            self._select(min(cur, self.list_left.count() - 1))
        self._show_preview()

    def _select(self, row: int) -> None:
        for w in (self.list_left, self.list_right):
            w.blockSignals(True)
            w.setCurrentRow(row)
            w.blockSignals(False)
        self._show_preview()

    def _sync(self, other: QListWidget, row: int) -> None:
        if row >= 0:
            other.blockSignals(True)
            other.setCurrentRow(row)
            other.blockSignals(False)
        self._show_preview()

    def _show_preview(self) -> None:
        from html import escape

        i = self.list_left.currentRow()
        if not 0 <= i < len(self.left):
            self.preview.setText("")
            return
        it, r = self.left[i], self.right[i]
        if it is None or r is None:
            self.preview.setText(escape(t("textimp.preview_skip")))
            return
        try:
            values = row_values(self.data, self.data.rows[r], self.format_string())
        except cv.FormatError as exc:
            self.preview.setText(f'<span style="color:#D32F2F">{escape(t("conv.format_error", reason=str(exc)))}</span>')
            return
        if values is None:
            self.preview.setText(f'<span style="color:#D32F2F">{escape(t("conv.no_match"))}</span>')
            return
        parts = [f"<b>{escape(it.display_name)}</b>"]
        for k, v in values.items():
            name = self.column_title(k) if not k.startswith(tg.EXTRA) else tg.label_of(k)
            parts.append(f"{escape(name)}: {escape(v) if v is not None else escape(t('meta.remove'))}")
        if len(parts) == 1:
            parts.append(escape(t("textimp.nothing")))
        self.preview.setText("<br>".join(parts))

    # Verschieben
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

    def pairs(self) -> list[tuple[object, dict | None]]:
        """(Titel, Werte) je zugeordnetem Paar; Werte None = Zeile passt nicht zum Muster."""
        fmt = self.format_string()
        result = []
        for it, r in zip(self.left, self.right):
            if it is None or r is None:
                continue
            result.append((it, row_values(self.data, self.data.rows[r], fmt)))
        return result


# --- Nummerierungs-Assistent ----------------------------------------------------------------------------
def track_numbers(count: int, start: int, digits: int, with_total: bool, total: int) -> list[str]:
    result = []
    for i in range(count):
        n = str(start + i).zfill(digits)
        result.append(f"{n}/{str(total).zfill(digits)}" if with_total else n)
    return result


class NumberDialog(QDialog):
    def __init__(self, parent, count: int, settings: dict) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("number.title"))
        self.count = count
        self.start = QSpinBox(self)
        self.start.setRange(0, 9999)
        self.start.setValue(int(settings.get("start", 1)))
        self.digits = QSpinBox(self)
        self.digits.setRange(1, 4)
        self.digits.setValue(int(settings.get("digits", 2)))
        self.with_total = QCheckBox(t("number.with_total"), self)
        self.with_total.setChecked(bool(settings.get("with_total", False)))
        self.total = QSpinBox(self)
        self.total.setRange(1, 99999)
        self.total.setValue(count)
        self.preview = QLabel(self)
        intro = QLabel(t("number.intro", n=count), self)
        intro.setWordWrap(True)
        form = QFormLayout()
        form.addRow(t("number.start"), self.start)
        form.addRow(t("number.digits"), self.digits)
        form.addRow("", self.with_total)
        form.addRow(t("number.total"), self.total)
        form.addRow(t("number.preview"), self.preview)
        box = QDialogButtonBox(self)
        box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addLayout(form)
        lay.addWidget(box)
        for w in (self.start, self.digits, self.total):
            w.valueChanged.connect(self._update)
        self.with_total.toggled.connect(self._update)
        self._update()

    def values(self) -> list[str]:
        return track_numbers(self.count, self.start.value(), self.digits.value(), self.with_total.isChecked(),
                             self.total.value())

    def settings(self) -> dict:
        return {"start": self.start.value(), "digits": self.digits.value(), "with_total": self.with_total.isChecked()}

    def _update(self, *_args) -> None:
        self.total.setEnabled(self.with_total.isChecked())
        vals = self.values()
        self.preview.setText(", ".join(vals[:4]) + (", …" if len(vals) > 4 else ""))


# --- ReplayGain (v0.9.6) ---------------------------------------------------------------------------------
class ReplayGainDialog(QDialog):
    def __init__(self, parent, tracks: int, albums: int, target: float, overwrite: bool) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("conv.replaygain").replace(" …", ""))
        self.setMinimumWidth(520)
        intro = QLabel(t("rg.intro", n=tracks, albums=albums, target=f"{target:.1f}"), self)
        intro.setWordWrap(True)
        self.overwrite = QCheckBox(t("rg.overwrite"), self)
        self.overwrite.setChecked(overwrite)
        hint = QLabel(t("rg.hint"), self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        box = QDialogButtonBox(self)
        box.addButton(t("rg.start"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addWidget(self.overwrite)
        lay.addWidget(hint)
        lay.addWidget(box)


# --- Playlist (M3U8) -------------------------------------------------------------------------------------
def default_playlist_path(items) -> str:
    first = items[0]
    folder = os.path.dirname(first.record.path)
    album = first.value("album").strip()
    name = cv.safe_filename(album) or os.path.basename(folder) or "Playlist"
    return os.path.join(folder, name + ".m3u8")


def playlist_text(path: str, items, relative: bool) -> str:
    base = os.path.dirname(os.path.abspath(path))
    lines = ["#EXTM3U"]
    for it in items:
        rec = it.record
        artist, title = it.value("artist").strip(), it.value("title").strip()
        label = f"{artist} - {title}" if artist and title else (title or os.path.splitext(rec.name)[0])
        lines.append(f"#EXTINF:{int(round(rec.length)) if rec.length else -1},{label}")
        target = os.path.relpath(rec.path, base) if relative else rec.path
        lines.append(target.replace(os.sep, "/"))
    return "\n".join(lines) + "\n"


def write_playlist(path: str, items, relative: bool) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(playlist_text(path, items, relative))


class PlaylistDialog(QDialog):
    def __init__(self, parent, path: str, relative: bool, count: int) -> None:
        super().__init__(parent)
        free_window(self)
        self.setWindowTitle(t("playlist.title"))
        self.setMinimumWidth(620)
        self.path = QLineEdit(path, self)
        browse = QToolButton(self)
        browse.setText("…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        self.relative = QCheckBox(t("playlist.relative"), self)
        self.relative.setChecked(relative)
        self.hint = QLabel(self)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: gray;")
        self.relative.toggled.connect(self._update_hint)
        box = QDialogButtonBox(self)
        box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(t("playlist.intro", n=count), self))
        lay.addLayout(row)
        lay.addWidget(self.relative)
        lay.addWidget(self.hint)
        lay.addWidget(box)
        self._update_hint()

    def _update_hint(self, *_args) -> None:
        self.hint.setText(t("playlist.hint_relative" if self.relative.isChecked() else "playlist.hint_absolute"))

    def _browse(self) -> None:
        path, _f = QFileDialog.getSaveFileName(self, t("playlist.title"), self.path.text(), "M3U8 (*.m3u8)")
        if path:
            if not path.lower().endswith(".m3u8"):
                path += ".m3u8"
            self.path.setText(path)

    def target(self) -> str:
        p = self.path.text().strip()
        if p and not p.lower().endswith((".m3u8", ".m3u")):
            p += ".m3u8"
        return p



# --- Disc-Nummern-Assistent (v1.2) ----------------------------------------------------------------------
DISC_FOLDER, DISC_RESTART, DISC_MANUAL = "folder", "restart", "manual"
DISC_TOTAL_NONE, DISC_TOTAL_PAIR, DISC_TOTAL_FIELD = "none", "pair", "field"


def _track_no(item) -> int | None:
    m = re.match(r"\s*(\d+)", item.value("track") or "")
    return int(m.group(1)) if m else None


def disc_numbers(items, mode: str, manual: int = 1) -> list[int]:
    """Disc-Nummer je Titel (in Listenreihenfolge).

    folder:  Titel im selben Ordner bilden eine Disc, in der Reihenfolge ihres ersten Auftretens
    restart: Disc wechselt, sobald die Tracknummer wieder kleiner oder gleich der vorigen wird
    manual:  alle Titel bekommen dieselbe Nummer
    """
    if mode == DISC_MANUAL:
        return [manual] * len(items)
    if mode == DISC_FOLDER:
        order: dict[str, int] = {}
        result = []
        for it in items:
            folder = os.path.dirname(it.record.path)
            order.setdefault(folder, len(order) + 1)
            result.append(order[folder])
        return result
    result, disc, last = [], 1, None
    for it in items:
        n = _track_no(it)
        if n is not None and last is not None and n <= last:
            disc += 1
        if n is not None:
            last = n
        result.append(disc)
    return result


def disc_total_key(kind: str) -> str:
    """Eigenes Feld „Anzahl Discs“ im jeweiligen Tag-Format."""
    return tg.custom_key(kind, "DISCTOTAL")


def default_disc_mode(items) -> str:
    return DISC_FOLDER if len({os.path.dirname(it.record.path) for it in items}) > 1 else DISC_RESTART


class DiscDialog(QDialog):
    """Disc-Nummern vergeben: nach Ordner, Neubeginn der Tracknummer oder von Hand (v1.2)."""

    def __init__(self, parent, items, settings: dict) -> None:
        from PySide6.QtWidgets import QButtonGroup, QRadioButton, QSpinBox

        super().__init__(parent)
        free_window(self)
        self.items = items
        self.setWindowTitle(t("disc.title"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        intro = QLabel(t("disc.intro", n=len(items)), self)
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        mode = settings.get("mode") or default_disc_mode(items)
        for key in (DISC_FOLDER, DISC_RESTART, DISC_MANUAL):
            rb = QRadioButton(t(f"disc.mode_{key}"), self)
            self.mode_group.addButton(rb)
            self.mode_buttons[key] = rb
            lay.addWidget(rb)
        self.manual = QSpinBox(self)
        self.manual.setRange(1, 99)
        self.manual.setValue(int(settings.get("manual") or 1))
        row = QHBoxLayout()
        row.addSpacing(24)
        row.addWidget(QLabel(t("disc.manual_value"), self))
        row.addWidget(self.manual)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addSpacing(6)
        lay.addWidget(QLabel(t("disc.total"), self))
        self.total_group = QButtonGroup(self)
        self.total_buttons = {}
        for key in (DISC_TOTAL_NONE, DISC_TOTAL_PAIR, DISC_TOTAL_FIELD):
            rb = QRadioButton(t(f"disc.total_{key}"), self)
            self.total_group.addButton(rb)
            self.total_buttons[key] = rb
            lay.addWidget(rb)
        self.manual_total = QSpinBox(self)
        self.manual_total.setRange(1, 99)
        self.manual_total.setValue(int(settings.get("manual_total") or 1))
        row = QHBoxLayout()
        row.addSpacing(24)
        row.addWidget(QLabel(t("disc.manual_total"), self))
        row.addWidget(self.manual_total)
        row.addStretch(1)
        lay.addLayout(row)
        hint = QLabel(t("disc.hint_field"), self)
        hint.setWordWrap(True)
        hint.setEnabled(False)
        lay.addWidget(hint)
        self.preview = QLabel(self)
        self.preview.setWordWrap(True)
        lay.addWidget(self.preview)
        box = QDialogButtonBox(self)
        box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.mode_buttons.get(mode, self.mode_buttons[DISC_RESTART]).setChecked(True)
        self.total_buttons.get(settings.get("total") or DISC_TOTAL_NONE,
                               self.total_buttons[DISC_TOTAL_NONE]).setChecked(True)
        for w in list(self.mode_buttons.values()) + list(self.total_buttons.values()):
            w.toggled.connect(self._update)
        self.manual.valueChanged.connect(self._update)
        self.manual_total.valueChanged.connect(self._update)
        self._update()

    def mode(self) -> str:
        return next(k for k, b in self.mode_buttons.items() if b.isChecked())

    def total_mode(self) -> str:
        return next(k for k, b in self.total_buttons.items() if b.isChecked())

    def settings(self) -> dict:
        return {"mode": self.mode(), "total": self.total_mode(), "manual": self.manual.value(),
                "manual_total": self.manual_total.value()}

    def changes(self) -> list[tuple[object, dict[str, str]]]:
        """(Titel, {Schlüssel: Wert}) je Titel."""
        nums = disc_numbers(self.items, self.mode(), self.manual.value())
        total = self.manual_total.value() if self.mode() == DISC_MANUAL else max(nums, default=1)
        result = []
        for it, n in zip(self.items, nums):
            values = {}
            if self.total_mode() == DISC_TOTAL_PAIR:
                values["disc"] = f"{n}/{total}"
            else:
                values["disc"] = str(n)
            if self.total_mode() == DISC_TOTAL_FIELD:
                values[disc_total_key(it.record.kind)] = str(total)
            result.append((it, values))
        return result

    def _update(self, *_args) -> None:
        manual = self.mode() == DISC_MANUAL
        self.manual.setEnabled(manual)
        self.manual_total.setEnabled(manual and self.total_mode() != DISC_TOTAL_NONE)
        lines = []
        for it, values in self.changes()[:6]:
            extra = "".join(f", {tg.label_of(k)} {v}" for k, v in values.items() if k != "disc")
            lines.append(f"{it.display_name}: {values['disc']}{extra}")
        if len(self.items) > 6:
            lines.append("…")
        self.preview.setText(t("number.preview") + "\n" + "\n".join(lines))


# --- Datum verschieben (v1.4, L-450 ff.) -------------------------------------------------------------------
def shift_date(value: str, seconds: int) -> str | None:
    """Aufnahmedatum um seconds verschieben; None, wenn es keins gibt bzw. es nicht lesbar ist."""
    import datetime as dt

    from .phototags import parse_date

    when = parse_date(value)
    if when is None:
        return None
    return (when + dt.timedelta(seconds=seconds)).strftime("%Y-%m-%d %H:%M:%S")


class DateShiftDialog(QDialog):
    """Aufnahmedatum mehrerer Fotos verschieben – mit Hinweis und Vorschau."""

    PREVIEW = 12

    def __init__(self, parent, items, last: dict) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QComboBox, QGridLayout, QSpinBox, QTreeWidget, QTreeWidgetItem

        free_window(self)
        self.setWindowTitle(t("shift.title"))
        self.resize(640, 520)
        self.items = items
        lay = QVBoxLayout(self)
        hint = QLabel(t("shift.hint"), self)
        hint.setWordWrap(True)
        lay.addWidget(hint)
        grid = QGridLayout()
        self.sign = QComboBox(self)
        self.sign.addItem("+", 1)
        self.sign.addItem("−", -1)
        self.sign.setCurrentIndex(1 if last.get("sign") == -1 else 0)
        grid.addWidget(QLabel(t("shift.direction"), self), 0, 0)
        grid.addWidget(self.sign, 0, 1)
        self.spins = {}
        for col, (key, maximum) in enumerate((("days", 3650), ("hours", 23), ("minutes", 59), ("seconds", 59))):
            spin = QSpinBox(self)
            spin.setRange(0, maximum)
            try:
                spin.setValue(int(last.get(key, 0)))
            except (TypeError, ValueError):
                pass
            grid.addWidget(QLabel(t(f"shift.{key}"), self), 1, col)
            grid.addWidget(spin, 2, col)
            self.spins[key] = spin
            spin.valueChanged.connect(self._update)
        self.sign.currentIndexChanged.connect(self._update)
        lay.addLayout(grid)
        lay.addWidget(QLabel(t("shift.preview"), self))
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels([t("shift.col_file"), t("shift.col_old"), t("shift.col_new")])
        self.tree.setRootIsDecorated(False)
        self._rows = []
        for it in items[: self.PREVIEW]:
            old = it.value("datetaken") or t("shift.no_date")
            row = QTreeWidgetItem([it.display_name, old, ""])
            self.tree.addTopLevelItem(row)
            self._rows.append((it, row))
        lay.addWidget(self.tree, 1)
        self.summary = QLabel(self)
        lay.addWidget(self.summary)
        box = QDialogButtonBox(self)
        self.btn_ok = box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self._update()
        for i in range(3):
            self.tree.resizeColumnToContents(i)

    def seconds(self) -> int:
        s = self.spins
        total = ((s["days"].value() * 24 + s["hours"].value()) * 60 + s["minutes"].value()) * 60 + s["seconds"].value()
        return total * int(self.sign.currentData())

    def settings(self) -> dict:
        return {"sign": int(self.sign.currentData()), **{k: s.value() for k, s in self.spins.items()}}

    def _update(self, *_a) -> None:
        secs = self.seconds()
        for it, row in self._rows:
            if it.readonly("datetaken") and it.value("datetaken"):
                row.setText(2, t("shift.locked"))  # Videos ohne exiftool, WMV (v1.5)
                continue
            new = shift_date(it.value("datetaken"), secs)
            row.setText(2, new if new is not None else "–")
        dated = [it for it in self.items if shift_date(it.value("datetaken"), 0) is not None]
        locked = sum(1 for it in dated if it.readonly("datetaken"))
        ok = len(dated) - locked
        missing = len(self.items) - len(dated)
        text = t("shift.count", n=ok)
        if missing:
            text += " " + t("shift.missing", n=missing)
        if locked:
            text += " " + t("shift.locked_count", n=locked)
        self.summary.setText(text)
        self.btn_ok.setEnabled(secs != 0 and ok > 0)

    def changes(self) -> list[tuple[object, str]]:
        secs = self.seconds()
        out = []
        for it in self.items:
            if it.readonly("datetaken"):
                continue
            new = shift_date(it.value("datetaken"), secs)
            if new is not None:
                out.append((it, new))
        return out
