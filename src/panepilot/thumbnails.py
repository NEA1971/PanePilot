"""Vorschaubilder für die Symbolansicht (v1.19, L-1912).

Nutzt den gemeinsamen Zwischenspeicher nach freedesktop.org (``~/.cache/thumbnails``, auch von Nautilus,
Dolphin usw. verwendet): vorhandene Bilder werden gelesen, fehlende im Hintergrund erzeugt und dort abgelegt.

- Bilder: das Bild selbst
- MP3/FLAC/M4A/… und Videos: eingebettetes Cover bzw. Poster, bei Videos sonst ein Bild aus dem Film (ffmpeg)
- PDF: die erste Seite (pdfium)
"""

from __future__ import annotations

import hashlib
import os
import queue
import subprocess
import threading
from collections import OrderedDict
from urllib.parse import quote

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Qt, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap

NORMAL, LARGE = 128, 256  # Ordner „normal“ und „large“ des Zwischenspeichers
MEMORY_LIMIT = 1500  # so viele Vorschaubilder bleiben im Speicher
_SAFE = "/!$&'()*+,;=:@-._~"  # wie GLib (g_filename_to_uri), damit die Namen zu Nautilus passen


def bucket(size: int) -> int:
    return NORMAL if size <= NORMAL else LARGE


def cache_root() -> str:
    from .util import cache_base

    base = cache_base()
    return os.path.join(base, "thumbnails")


def file_uri(path: str) -> str:
    return "file://" + quote(os.path.abspath(path), safe=_SAFE)


def cache_path(path: str, size: int) -> str:
    name = hashlib.md5(file_uri(path).encode("utf-8")).hexdigest() + ".png"
    return os.path.join(cache_root(), "normal" if bucket(size) == NORMAL else "large", name)


def _image_suffixes() -> set[str]:
    return {bytes(f).decode("ascii", "replace").lower() for f in QImageReader.supportedImageFormats()}


_IMAGE_EXT: set[str] | None = None


def kind_of(path: str) -> str | None:
    """„image“, „audio“, „video“, „pdf“ – oder None, wenn es kein Vorschaubild gibt."""
    global _IMAGE_EXT
    from . import tags as tg

    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if not ext:
        return None
    if ext == "pdf":
        return "pdf"
    if tg.is_video(path):
        return "video"
    if tg.is_audio(path):
        return "audio"
    if _IMAGE_EXT is None:
        _IMAGE_EXT = _image_suffixes()
    if ext in _IMAGE_EXT or tg.is_photo(path):
        return "image"
    return None


# --- Zwischenspeicher lesen und schreiben -------------------------------------------------------------------
def read_cached(path: str, mtime: float, size: int) -> QImage | None:
    """Gültiges Vorschaubild aus ~/.cache/thumbnails (URI und Änderungszeit müssen passen)."""
    file = cache_path(path, size)
    if not os.path.isfile(file):
        return None
    img = QImage(file)
    if img.isNull():
        return None
    if img.text("Thumb::URI") != file_uri(path):
        return None
    try:
        if int(img.text("Thumb::MTime") or -1) != int(mtime):
            return None
    except ValueError:
        return None
    return img


def write_cached(path: str, mtime: float, size: int, img: QImage) -> bool:
    file = cache_path(path, size)
    folder = os.path.dirname(file)
    try:
        os.makedirs(folder, mode=0o700, exist_ok=True)
        out = QImage(img)
        out.setText("Thumb::URI", file_uri(path))
        out.setText("Thumb::MTime", str(int(mtime)))
        out.setText("Software", "PanePilot")
        try:
            out.setText("Thumb::Size", str(os.path.getsize(path)))
        except OSError:
            pass
        tmp = f"{file}.{os.getpid()}.{threading.get_ident()}.tmp"
        if not out.save(tmp, "PNG"):
            return False
        os.chmod(tmp, 0o600)
        os.replace(tmp, file)
        return True
    except OSError:
        return False


# --- Vorschaubilder erzeugen ----------------------------------------------------------------------------------
def _from_bytes(data: bytes | None) -> QImage | None:
    if not data:
        return None
    img = QImage()
    if not img.loadFromData(QByteArray(data)):
        return None
    return img


def _scaled(img: QImage | None, size: int) -> QImage | None:
    if img is None or img.isNull():
        return None
    if img.width() <= size and img.height() <= size:
        return img
    return img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def _image(path: str, size: int) -> QImage | None:
    reader = QImageReader(path)
    reader.setAutoTransform(True)  # Ausrichtung aus EXIF
    full = reader.size()
    if full.isValid() and (full.width() > size or full.height() > size):
        reader.setScaledSize(full.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio))
    img = reader.read()
    if img.isNull():
        return None
    return _scaled(img, size)


def _audio_cover(path: str) -> QImage | None:
    from . import tags as tg

    try:
        pic = tg.read_file(path).front_cover()
    except Exception:  # noqa: BLE001 – kaputte Datei: kein Cover
        return None
    return _from_bytes(pic.data) if pic is not None else None


def _video_cover(path: str) -> QImage | None:
    """Eingebettetes Poster: MKV-Anhang (bevorzugt „cover…“) bzw. MP4-Cover."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".mkv", ".mka", ".webm"):
            from . import videotags as vt

            images = [(n, d) for n, m, d in vt.mkv_attachments(path) if m.startswith("image/")]
            images.sort(key=lambda x: (not x[0].lower().startswith("cover"), x[0].lower()))
            for _n, data in images:
                img = _from_bytes(data)
                if img is not None:
                    return img
            return None
        if ext in (".mp4", ".m4v", ".mov", ".3gp"):
            from mutagen.mp4 import MP4

            covers = (MP4(path).tags or {}).get("covr") or []
            return _from_bytes(bytes(covers[0])) if covers else None
    except Exception:  # noqa: BLE001
        return None
    return None


def _video_frame(path: str, size: int, env: dict | None) -> QImage | None:
    from . import videotags as vt

    tool = vt.ffmpeg()
    if tool is None:
        return None
    vf = f"scale={size}:{size}:force_original_aspect_ratio=decrease"
    for seek in ("10", "0"):  # kurze Filme: erstes Bild
        try:
            proc = subprocess.run([tool, "-v", "error", "-nostdin", "-ss", seek, "-i", path, "-frames:v", "1",
                                   "-an", "-sn", "-vf", vf, "-f", "image2pipe", "-vcodec", "png", "-"],
                                  capture_output=True, env=env, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        img = _from_bytes(proc.stdout) if proc.returncode == 0 else None
        if img is not None:
            return img
    return None


def _pdf(path: str, size: int) -> QImage | None:
    from . import doctags

    return _from_bytes(doctags.pdf_preview(path, size))


def generate(path: str, size: int, env: dict | None = None) -> QImage | None:
    """Neues Vorschaubild in der Größe des Zwischenspeicher-Ordners (128 bzw. 256)."""
    size = bucket(size)
    kind = kind_of(path)
    img = None
    if kind == "image":
        img = _image(path, size)
    elif kind == "audio":
        img = _audio_cover(path)
    elif kind == "video":
        img = _video_cover(path) or _video_frame(path, size, env)
    elif kind == "pdf":
        img = _pdf(path, size)
    img = _scaled(img, size)
    if img is not None and img.format() not in (QImage.Format.Format_ARGB32, QImage.Format.Format_RGB32):
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
    return img


def thumbnail(path: str, mtime: float, size: int, env: dict | None = None, write: bool = True) -> QImage | None:
    """Aus dem Zwischenspeicher oder neu erzeugt (und dann abgelegt)."""
    img = read_cached(path, mtime, size)
    if img is not None:
        return img
    img = generate(path, size, env)
    if img is not None and write:
        write_cached(path, mtime, size, img)
    return img


def to_png(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


# --- Hintergrund ------------------------------------------------------------------------------------------------
class ThumbnailLoader(QObject):
    """Ein Hintergrund-Thread (pdfium ist nicht threadsicher); zuletzt angefragte Bilder zuerst."""

    ready = Signal(str)  # Pfad – das Bild liegt dann im Speicher

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cache: OrderedDict[tuple, QPixmap | None] = OrderedDict()
        self._images: dict[tuple, QImage | None] = {}
        self._pending: set[tuple] = set()
        self._lock = threading.Lock()
        self._queue: queue.LifoQueue = queue.LifoQueue()
        self._thread: threading.Thread | None = None
        self._stop = False
        self.ready.connect(self._collect)
        try:
            from .videotags import _env

            self._env = _env()
        except Exception:  # noqa: BLE001
            self._env = None

    def get(self, path: str, mtime: float, size: int) -> QPixmap | None:
        """Sofort aus dem Speicher – sonst None und im Hintergrund anfordern."""
        key = (path, int(mtime), bucket(size))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        with self._lock:
            if key in self._pending:
                return None
            self._pending.add(key)
        self._queue.put(key)
        self._start()
        return None

    def drop_pending(self) -> None:
        """Ordnerwechsel: noch nicht begonnene Anfragen verwerfen (werden beim Zeichnen neu gestellt)."""
        with self._lock:
            self._pending.clear()

    def wanted(self, path: str) -> bool:
        return kind_of(path) is not None

    def clear(self) -> None:
        with self._lock:
            self._pending.clear()
        self._cache.clear()
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def shutdown(self) -> None:
        self._stop = True
        self._queue.put(None)

    def _start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop = False
            self._thread = threading.Thread(target=self._work, name="PanePilot-Vorschau", daemon=True)
            self._thread.start()

    def _work(self) -> None:
        while not self._stop:
            key = self._queue.get()
            if key is None:
                return
            with self._lock:
                if key not in self._pending:
                    continue  # inzwischen verworfen (Ordnerwechsel)
            path, mtime, size = key
            try:
                img = thumbnail(path, mtime, size, self._env)
            except Exception:  # noqa: BLE001 – ein kaputtes Bild darf den Thread nicht beenden
                img = None
            with self._lock:
                self._images[key] = img
            self.ready.emit(path)

    def _collect(self, _path: str) -> None:
        with self._lock:
            done, self._images = self._images, {}
            self._pending.difference_update(done)
        for key, img in done.items():
            self._cache[key] = QPixmap.fromImage(img) if img is not None else None
        while len(self._cache) > MEMORY_LIMIT:
            self._cache.popitem(last=False)

    def wait_idle(self, timeout: float = 30.0) -> bool:
        """Für Tests: warten, bis alles erzeugt ist."""
        import time

        from PySide6.QtWidgets import QApplication

        end = time.monotonic() + timeout
        while time.monotonic() < end:
            QApplication.processEvents()
            with self._lock:
                if not self._pending and not self._images:
                    return True
            time.sleep(0.02)
        return False


_loader: ThumbnailLoader | None = None


def loader() -> ThumbnailLoader:
    global _loader
    if _loader is None:
        _loader = ThumbnailLoader()
    return _loader
