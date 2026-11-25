"""Schnellansicht (v2.7, L-3700 ff.): Vorschau der markierten Datei im anderen Fenster.

Text, Bilder, PDF (alle Seiten), Video (Standbild + Eckdaten), Audio (Cover + Tags),
LibreOffice-/Microsoft-Dokumente (Text, Tabellen je Blatt, Folien), sonst Größe und Art.
Schweres (Dokumente, Videos, Tags) wird im Hintergrund gelesen; nur das zuletzt Angefragte wird gezeigt.
"""

from __future__ import annotations

import html
import os
import subprocess
import threading

from PySide6.QtCore import QMimeDatabase, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontDatabase, QImage, QImageReader, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QLabel, QPlainTextEdit, QScrollArea, QSizePolicy,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from . import officetext
from .i18n import t
from .util import format_size

TEXT_LIMIT = 1024 * 1024
DEBOUNCE_MS = 120
PDF_MIN_WIDTH = 240  # Seiten werden auf die Breite des Fensters gezeichnet


def decode_text(data: bytes) -> str:
    """Zeichensatz erkennen: BOM, UTF-8, sonst Windows-1252 bzw. Latin-1."""
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if data.startswith(bom):
            return data.decode(enc, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.reason == "unexpected end of data":  # am Ende abgeschnittenes Zeichen (1-MB-Grenze)
            return data[:exc.start].decode("utf-8", errors="replace")
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def looks_binary(data: bytes) -> bool:
    head = data[:8192]
    if not head:
        return False
    if b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return True
    control = sum(1 for b in head if b < 9 or 13 < b < 32)
    return control / len(head) > 0.1


def classify(path: str) -> str:
    """dir, image, pdf, office, video, audio, text oder other."""
    from . import tags, thumbnails

    if os.path.isdir(path):
        return "dir"
    kind = thumbnails.kind_of(path)
    if kind == "pdf":
        return "pdf"
    if officetext.supported(path):
        return "office"
    if kind in ("image", "video", "audio"):
        return kind
    if tags.is_photo(path):
        return "image"
    try:
        with open(path, "rb") as fh:
            head = fh.read(8192)
    except OSError:
        return "other"
    return "other" if looks_binary(head) else "text"


# --- Hintergrund -------------------------------------------------------------------------------------------------
def load(path: str, kind: str) -> dict:
    """Läuft im Hintergrund – liefert nur einfache Daten (keine Widgets)."""
    result: dict = {"path": path, "kind": kind}
    try:
        if kind == "text":
            with open(path, "rb") as fh:
                data = fh.read(TEXT_LIMIT + 1)
            result["text"] = decode_text(data[:TEXT_LIMIT])
            result["truncated"] = len(data) > TEXT_LIMIT
        elif kind == "office":
            result["doc"] = officetext.extract(path)
        elif kind == "image":
            reader = QImageReader(path)
            reader.setAutoTransform(True)
            img = reader.read()
            if img.isNull():
                from . import thumbnails

                img = thumbnails._image(path, 2048) or QImage()
            result["image"] = img
        elif kind in ("video", "audio"):
            from . import tags

            rec = tags.read_file(path)
            result["rec"] = rec
            cover = rec.front_cover() if hasattr(rec, "front_cover") else None
            data = cover.data if cover is not None else None
            if data is None and kind == "video":
                data = video_frame(path, rec.length)
            result["picture"] = data
    except Exception as exc:  # noqa: BLE001 – kaputte Datei: Hinweis statt Absturz
        result["error"] = str(exc) or type(exc).__name__
    return result


def video_frame(path: str, length: float = 0.0) -> bytes | None:
    from . import videotags as vt

    tool = vt.ffmpeg()
    if tool is None:
        return None
    seek = f"{max(length * 0.1, 0):.1f}" if length else "10"
    for pos in (seek, "0"):
        try:
            proc = subprocess.run([tool, "-v", "error", "-nostdin", "-ss", pos, "-i", path, "-frames:v", "1", "-an",
                                   "-sn", "-vf", "scale=960:960:force_original_aspect_ratio=decrease",
                                   "-f", "image2pipe", "-vcodec", "png", "-"],
                                  capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
    return None


class _Loader(QObject):
    done = Signal(int, object)

    def start(self, gen: int, path: str, kind: str) -> None:
        threading.Thread(target=lambda: self.done.emit(gen, load(path, kind)), daemon=True).start()


# --- Anzeigen ----------------------------------------------------------------------------------------------------
class ImageView(QScrollArea):
    """Bild eingepasst; Mausrad zoomt (L-3704)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("quickImage")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWidget(self.label)
        self.setWidgetResizable(False)
        self._pixmap = QPixmap()
        self.zoom = 0.0  # 0 = eingepasst

    def set_image(self, img: QImage) -> None:
        self._pixmap = QPixmap.fromImage(img)
        self.zoom = 0.0
        self._apply()

    def fit_factor(self) -> float:
        if self._pixmap.isNull():
            return 1.0
        area = self.viewport().size()
        return min(area.width() / max(self._pixmap.width(), 1), area.height() / max(self._pixmap.height(), 1), 1.0)

    def _apply(self) -> None:
        if self._pixmap.isNull():
            self.label.clear()
            self.label.resize(QSize(1, 1))
            return
        factor = self.zoom or self.fit_factor()
        size = self._pixmap.size() * factor
        self.label.setPixmap(self._pixmap.scaled(size, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        self.label.resize(size)

    def wheelEvent(self, event) -> None:
        if self._pixmap.isNull():
            return
        steps = event.angleDelta().y() / 120
        if not steps:
            return
        factor = self.zoom or self.fit_factor()
        factor = max(0.05, min(factor * (1.2 ** steps), 8.0))
        self.zoom = factor
        self._apply()
        event.accept()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self.zoom:
            self._apply()


class PdfView(QScrollArea):
    """Alle Seiten untereinander; gezeichnet wird erst, was ins Bild kommt (L-3704)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("quickPdf")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.box = QWidget(self)
        self.lay = QVBoxLayout(self.box)
        self.lay.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.lay.setSpacing(10)
        self.setWidget(self.box)
        self.path = ""
        self.pages: list[QLabel] = []
        self.done: set[int] = set()
        self.verticalScrollBar().valueChanged.connect(lambda *_: self._render_visible())
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._render_visible)

    def set_pdf(self, path: str) -> int:
        from . import doctags

        for lbl in self.pages:
            self.lay.removeWidget(lbl)
            lbl.deleteLater()
        self.pages, self.done, self.path = [], set(), path
        self.width_px = self.page_width()
        count = doctags.pdf_page_count(path)
        for i in range(count):
            lbl = QLabel(t("quick.page", n=i + 1), self.box)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFrameShape(QFrame.Shape.Box)
            lbl.setFixedSize(self.width_px, int(self.width_px * 1.414))  # A4 bis zum Zeichnen
            lbl.setStyleSheet("background: white; color: #888;")
            self.lay.addWidget(lbl)
            self.pages.append(lbl)
        self.verticalScrollBar().setValue(0)
        self._timer.start()
        return count

    def _render_visible(self) -> None:
        from . import doctags

        top = self.verticalScrollBar().value()
        bottom = top + self.viewport().height()
        todo = [i for i, lbl in enumerate(self.pages)
                if i not in self.done and lbl.y() < bottom + 200 and lbl.y() + lbl.height() > top - 200][:3]
        for i in todo:
            self.done.add(i)
            data = doctags.pdf_render(self.path, [i], self.width_px, by_width=True)
            if not data:
                continue
            pm = QPixmap()
            pm.loadFromData(data[0])
            lbl = self.pages[i]
            lbl.setFixedSize(pm.size())
            lbl.setPixmap(pm)
        if todo:
            self._timer.start()

    def page_width(self) -> int:
        return max(self.viewport().width() - 30, PDF_MIN_WIDTH)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.path and abs(self.page_width() - getattr(self, "width_px", 0)) > 40:
            pos = self.verticalScrollBar().value() / max(self.verticalScrollBar().maximum(), 1)
            self.set_pdf(self.path)  # neu auf die neue Breite
            QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(
                int(pos * self.verticalScrollBar().maximum())))
            return
        self._timer.start()


class InfoView(QScrollArea):
    """Bild (Standbild/Cover) und Eckdaten."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("quickInfo")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        box = QWidget(self)
        lay = QVBoxLayout(box)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.picture = QLabel(box)
        self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text = QLabel(box)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.picture)
        lay.addWidget(self.text)
        self.setWidget(box)
        self._pixmap = QPixmap()

    def set_info(self, rows: list[tuple[str, str]], picture: bytes | None = None, note: str = "") -> None:
        self._pixmap = QPixmap()
        if picture:
            self._pixmap.loadFromData(picture)
        self._scale()
        body = "".join(f"<tr><td style='padding-right:12px; color:gray'>{html.escape(k)}</td>"
                       f"<td>{html.escape(v)}</td></tr>" for k, v in rows if v)
        extra = f"<p>{html.escape(note)}</p>" if note else ""
        self.text.setText(f"<table>{body}</table>{extra}")

    def _scale(self) -> None:
        if self._pixmap.isNull():
            self.picture.clear()
            self.picture.hide()
            return
        width = max(self.viewport().width() - 24, 64)
        height = max(int(self.viewport().height() * 0.65), 64)
        self.picture.setPixmap(self._pixmap.scaled(QSize(width, height), Qt.AspectRatioMode.KeepAspectRatio,
                                                   Qt.TransformationMode.SmoothTransformation))
        self.picture.show()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._scale()


class QuickView(QWidget):
    """Wird mit FilePanel.set_custom_view() im anderen Fenster gezeigt."""

    def __init__(self, parent=None, on_replaced=None) -> None:
        super().__init__(parent)
        self.setObjectName("quickView")
        self.on_replaced = on_replaced  # vom Dateifenster gerufen, wenn eine andere Ansicht uns ersetzt
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.title = QLabel(self)
        self.title.setObjectName("quickTitle")
        self.title.setStyleSheet("font-weight: bold; padding: 2px 4px;")
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.title)
        self.stack = QStackedWidget(self)
        lay.addWidget(self.stack, 1)
        self.note = QLabel(self)
        self.note.setObjectName("quickNote")
        self.note.setEnabled(False)
        self.note.setStyleSheet("padding: 1px 4px;")
        lay.addWidget(self.note)
        self.text = QPlainTextEdit(self)
        self.text.setObjectName("quickText")
        self.text.setReadOnly(True)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.image = ImageView(self)
        self.pdf = PdfView(self)
        self.sheets = QTabWidget(self)
        self.sheets.setObjectName("quickSheets")
        self.info = InfoView(self)
        for w in (self.text, self.image, self.pdf, self.sheets, self.info):
            w.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            self.stack.addWidget(w)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.path = ""
        self.kind = ""
        self._gen = 0
        self._pending = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._load_pending)
        self._loader = _Loader(self)
        self._loader.done.connect(self._loaded)

    # --- Ablauf ---------------------------------------------------------------------------------------------
    def show_path(self, path: str | None, immediate: bool = False) -> None:
        self._pending = path or ""
        if immediate:
            self._timer.stop()
            self._load_pending()
        else:
            self._timer.start()

    def _load_pending(self) -> None:
        path = self._pending
        if path == self.path and self.kind:
            return
        self._gen += 1
        self.path = path
        self.note.clear()
        if not path:
            self.kind = ""
            self.title.setText("")
            self._show_info([], t("quick.nothing"))
            return
        self.title.setText(os.path.basename(path.rstrip(os.sep)) or path)
        self.title.setToolTip(path)
        kind = classify(path)
        self.kind = kind
        if kind == "dir":
            self._show_dir(path)
        elif kind == "pdf":
            self.stack.setCurrentWidget(self.pdf)
            count = self.pdf.set_pdf(path)
            self.note.setText(t("quick.pages", n=count) if count else t("quick.no_preview"))
        elif kind == "other":
            self._show_other(path)
        else:
            self._show_info([], t("quick.loading"))
            self._loader.start(self._gen, path, kind)

    def _loaded(self, gen: int, result: dict) -> None:
        if gen != self._gen:
            return  # inzwischen eine andere Datei markiert
        if result.get("error"):
            self._show_other(result["path"], t("quick.error", error=result["error"]))
            return
        kind = result["kind"]
        if kind == "text":
            self.text.setPlainText(result["text"])
            self.stack.setCurrentWidget(self.text)
            if result.get("truncated"):
                self.note.setText(t("quick.truncated"))
        elif kind == "image":
            img = result["image"]
            if img.isNull():
                self._show_other(result["path"])
                return
            self.stack.setCurrentWidget(self.image)
            self.image.set_image(img)
            self.note.setText(f"{img.width()} × {img.height()}")
        elif kind == "office":
            self._show_doc(result["doc"])
        else:
            self._show_media(result)

    # --- Inhalte ------------------------------------------------------------------------------------------------
    def _show_info(self, rows, note: str = "", picture: bytes | None = None) -> None:
        self.info.set_info(rows, picture, note)
        self.stack.setCurrentWidget(self.info)

    def _show_dir(self, path: str) -> None:
        try:
            with os.scandir(path) as it:
                count = sum(1 for _ in it)
        except OSError:
            count = 0
        self._show_info([], t("quick.folder", n=count))

    def _basic_rows(self, path: str) -> list[tuple[str, str]]:
        import datetime as dt

        rows = []
        try:
            st = os.stat(path)
            rows.append((t("quick.size"), format_size(st.st_size)))
            rows.append((t("quick.modified"), dt.datetime.fromtimestamp(st.st_mtime).strftime("%d.%m.%Y %H:%M")))
        except OSError:
            pass
        mime = QMimeDatabase().mimeTypeForFile(path)
        rows.insert(0, (t("quick.type"), mime.comment() or mime.name()))
        return rows

    def _show_other(self, path: str, note: str = "") -> None:
        self._show_info(self._basic_rows(path), note or t("quick.no_preview"))

    def _show_doc(self, doc) -> None:
        if doc.kind == "text":
            self.text.setPlainText(doc.text)
            self.stack.setCurrentWidget(self.text)
            return
        if doc.kind == "slides":
            parts = []
            for i, text in enumerate(doc.slides, 1):
                parts.append(f"── {t('quick.slide', n=i)} ──")
                parts.append(text)
                parts.append("")
            self.text.setPlainText("\n".join(parts))
            self.stack.setCurrentWidget(self.text)
            self.note.setText(t("quick.slides", n=len(doc.slides)))
            return
        self.sheets.clear()
        for name, rows in doc.sheets:
            table = QTableWidget(self.sheets)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            cols = max((len(r) for r in rows), default=0)
            table.setRowCount(len(rows))
            table.setColumnCount(cols)
            table.setHorizontalHeaderLabels([_col_name(c) for c in range(cols)])
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    if value:
                        table.setItem(r, c, QTableWidgetItem(value))
            table.resizeColumnsToContents()
            for c in range(cols):
                table.setColumnWidth(c, min(table.columnWidth(c), 320))
            self.sheets.addTab(table, name)
        self.stack.setCurrentWidget(self.sheets)
        if doc.truncated:
            self.note.setText(t("quick.rows_limit", n=officetext.ROW_LIMIT))

    def _show_media(self, result: dict) -> None:
        from .tags import format_length

        rec = result["rec"]
        path = result["path"]
        rows = self._basic_rows(path)
        if rec.length:
            rows.append((t("quick.length"), format_length(rec.length)))
        if result["kind"] == "video":
            if rec.width and rec.height:
                rows.append((t("quick.resolution"), f"{rec.width} × {rec.height}"))
            if rec.vcodec:
                rows.append((t("quick.vcodec"), rec.vcodec))
            audio = ", ".join(getattr(tr, "code", "") or "?" for tr in rec.audio_tracks)
            subs = ", ".join(getattr(tr, "code", "") or "?" for tr in rec.sub_tracks)
            rows.append((t("quick.audio_tracks"), audio))
            rows.append((t("quick.sub_tracks"), subs))
        else:
            for key in ("title", "artist", "album", "albumartist", "date", "genre", "tracknumber"):
                value = rec.fields.get(key, "")
                if value:
                    rows.append((t(f"quick.tag_{key}"), value))
            if rec.bitrate:
                rows.append((t("quick.bitrate"), f"{rec.bitrate // 1000} kbit/s"))
        if rec.codec and result["kind"] == "audio":
            rows.append((t("quick.format"), rec.codec))
        self._show_info(rows, rec.error or "", result.get("picture"))

    def replaced(self) -> None:
        self._gen += 1
        if self.on_replaced is not None:
            callback, self.on_replaced = self.on_replaced, None
            callback()


def _col_name(c: int) -> str:
    name = ""
    c += 1
    while c:
        c, rem = divmod(c - 1, 26)
        name = chr(65 + rem) + name
    return name
