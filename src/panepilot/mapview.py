"""Kleine Karte für Fotos mit GPS-Position (v2.5, L-3506 ff.).

Zeigt die Position eines oder mehrerer Fotos als Stecknadeln auf OpenStreetMap-Kacheln. Bewusst schlank:
kein eingebauter Browser, nur Kacheln (256 × 256 px, Web-Mercator) über HTTPS.

- Ziehen verschiebt, Mausrad zoomt (über der Karte – die Seitenleiste rollt dann nicht mit).
- Kacheln werden unter ~/.cache/PanePilot/tiles zwischengespeichert (30 Tage) und mit eigener Kennung
  geladen, wie es die Nutzungsregeln von OpenStreetMap verlangen; „© OpenStreetMap“ steht sichtbar unten rechts.
- Die Karte zeigt nur – Positionen setzen oder verschieben gibt es nicht (Wunsch vom 22.11.2026).
"""

from __future__ import annotations

import math
import os
import queue
import threading
import time

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from .i18n import t

TILE = 256
MIN_ZOOM, MAX_ZOOM = 2, 18
FIT_MAX_ZOOM = 16
WHEEL_STEP = 0.25  # v2.5.1: ein Rad-Schritt = ¼ Zoomstufe (vorher eine ganze – zu sprunghaft)
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
MAX_AGE = 30 * 24 * 3600
ATTRIBUTION_URL = "https://www.openstreetmap.org/copyright"


# --- Mathematik (Web-Mercator) --------------------------------------------------------------------------
def world_xy(lat: float, lon: float, zoom: float) -> tuple[float, float]:
    """Pixelposition in der Weltkarte der Zoomstufe."""
    lat = max(min(lat, 85.0511), -85.0511)
    n = TILE * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * n
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * n
    return x, y


def latlon(x: float, y: float, zoom: float) -> tuple[float, float]:
    n = TILE * (2 ** zoom)
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    return lat, lon


def fit(points: list[tuple[float, float]], width: int, height: int, margin: int = 28) -> tuple[float, float, int]:
    """Mitte (lat, lon) und Zoomstufe, bei der alle Punkte zu sehen sind."""
    if not points:
        return 0.0, 0.0, MIN_ZOOM
    if len(points) == 1:
        return points[0][0], points[0][1], 15
    for zoom in range(FIT_MAX_ZOOM, MIN_ZOOM - 1, -1):
        xs, ys = zip(*(world_xy(la, lo, zoom) for la, lo in points))
        if max(xs) - min(xs) <= max(width - 2 * margin, 1) and max(ys) - min(ys) <= max(height - 2 * margin, 1):
            cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
            la, lo = latlon(cx, cy, zoom)
            return la, lo, zoom
    xs, ys = zip(*(world_xy(la, lo, MIN_ZOOM) for la, lo in points))
    la, lo = latlon((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, MIN_ZOOM)
    return la, lo, MIN_ZOOM


# --- Kacheln --------------------------------------------------------------------------------------------
def cache_dir() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "PanePilot", "tiles")


def tile_path(z: int, x: int, y: int) -> str:
    return os.path.join(cache_dir(), str(z), str(x), f"{y}.png")


def _user_agent() -> str:
    from . import __version__

    return f"PanePilot/{__version__} (+https://github.com/NEA1971/PanePilot)"


class TileLoader(QObject):
    """Lädt fehlende Kacheln im Hintergrund (eine Verbindung, neueste Anfrage zuerst)."""

    loaded = Signal(int, int, int)
    enabled = True  # Tests schalten das Netz ab

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.LifoQueue = queue.LifoQueue()
        self._pending: set[tuple[int, int, int]] = set()
        self._failed: dict[tuple[int, int, int], float] = {}
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def request(self, z: int, x: int, y: int) -> None:
        key = (z, x, y)
        if not self.enabled:
            return
        with self._lock:
            if key in self._pending or time.time() - self._failed.get(key, 0) < 60:
                return
            self._pending.add(key)
        self._queue.put(key)
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="panepilot-tiles", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        import urllib.request

        while True:
            try:
                key = self._queue.get(timeout=30)
            except queue.Empty:
                return
            z, x, y = key
            path = tile_path(z, x, y)
            try:
                req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y), headers={"User-Agent": _user_agent()})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                os.makedirs(os.path.dirname(path), exist_ok=True)
                tmp = path + ".part"
                with open(tmp, "wb") as fh:
                    fh.write(data)
                os.replace(tmp, path)
                ok = True
            except Exception:  # noqa: BLE001 – kein Netz, Server verweigert …: Kachel bleibt grau
                ok = False
            with self._lock:
                self._pending.discard(key)
                if not ok:
                    self._failed[key] = time.time()
            if ok:
                self.loaded.emit(z, x, y)


_loader: TileLoader | None = None


def loader() -> TileLoader:
    global _loader
    if _loader is None:
        _loader = TileLoader()
    return _loader


# --- Anzeige --------------------------------------------------------------------------------------------
class MapView(QWidget):
    """Karte mit Stecknadeln; set_points([(lat, lon, beschriftung), …])."""

    def __init__(self, parent=None, height: int = 200) -> None:
        super().__init__(parent)
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(height)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.points: list[tuple[float, float, str]] = []
        self.lat, self.lon, self.zoom = 0.0, 0.0, MIN_ZOOM
        self._tiles: dict[tuple[int, int, int], QImage] = {}
        self._drag: QPointF | None = None
        self._fitted_for: tuple = ()
        loader().loaded.connect(self._tile_loaded)
        self.setToolTip("")

    # --- Daten ---
    def set_points(self, points: list[tuple[float, float, str]]) -> None:
        self.points = list(points)
        self._fitted_for = ()
        self._fit()
        self.update()

    def _fit(self) -> None:
        if self.width() <= 1:
            return
        key = (tuple((la, lo) for la, lo, _n in self.points), self.width(), self.height())
        if key == self._fitted_for:
            return
        self._fitted_for = key
        self.lat, self.lon, self.zoom = fit([(la, lo) for la, lo, _n in self.points], self.width(), self.height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fitted_for = ()
        self._fit()

    # --- Kacheln ---
    def _tile(self, z: int, x: int, y: int) -> QImage | None:
        n = 2 ** z
        x %= n
        if y < 0 or y >= n:
            return None
        key = (z, x, y)
        img = self._tiles.get(key)
        if img is not None:
            return img
        path = tile_path(z, x, y)
        try:
            fresh = time.time() - os.path.getmtime(path) < MAX_AGE
        except OSError:
            fresh = None
        if fresh is not None:
            img = QImage(path)
            if not img.isNull():
                if len(self._tiles) > 300:
                    self._tiles.clear()
                self._tiles[key] = img
                if not fresh:
                    loader().request(z, x, y)  # veraltet: neu holen, bis dahin die alte zeigen
                return img
        loader().request(z, x, y)
        return None

    def _tile_loaded(self, z: int, x: int, y: int) -> None:
        self._tiles.pop((z, x, y), None)
        if z == self._tile_zoom():
            self.update()

    def _tile_zoom(self) -> int:
        return max(MIN_ZOOM, min(MAX_ZOOM, int(math.floor(self.zoom + 1e-9))))

    # --- Zeichnen ---
    def _origin(self) -> tuple[float, float]:
        cx, cy = world_xy(self.lat, self.lon, self.zoom)
        return cx - self.width() / 2, cy - self.height() / 2

    def screen_pos(self, lat: float, lon: float) -> QPointF:
        ox, oy = self._origin()
        x, y = world_xy(lat, lon, self.zoom)
        return QPointF(x - ox, y - oy)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#e5e3df"))
        ox, oy = self._origin()
        z = self._tile_zoom()
        size = TILE * 2 ** (self.zoom - z)  # Kacheln der ganzen Stufe, stufenlos vergrößert
        x0, y0 = int(math.floor(ox / size)), int(math.floor(oy / size))
        x1, y1 = int(math.floor((ox + self.width()) / size)), int(math.floor((oy + self.height()) / size))
        for tx in range(x0, x1 + 1):
            for ty in range(y0, y1 + 1):
                img = self._tile(z, tx, ty)
                if img is not None:
                    p.drawImage(QRectF(tx * size - ox, ty * size - oy, size + 0.5, size + 0.5), img)
        for lat, lon, _label in self.points:
            self._pin(p, self.screen_pos(lat, lon))
        self._attribution(p)
        p.setPen(QPen(QColor(0, 0, 0, 60)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()

    @staticmethod
    def _pin(p: QPainter, pos: QPointF) -> None:
        path = QPainterPath()
        path.moveTo(pos)
        path.cubicTo(pos + QPointF(-2, -6), pos + QPointF(-9, -12), pos + QPointF(-9, -19))
        path.arcTo(QRectF(pos.x() - 9, pos.y() - 28, 18, 18), 180, -180)
        path.cubicTo(pos + QPointF(9, -12), pos + QPointF(2, -6), pos)
        p.setPen(QPen(QColor("#7a1010"), 1.2))
        p.setBrush(QColor("#d63b3b"))
        p.drawPath(path)
        p.setBrush(QColor("white"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(pos + QPointF(0, -19), 3.2, 3.2)

    def _attribution_rect(self) -> QRectF:
        fm = self.fontMetrics()
        text = t("map.attribution")
        w = fm.horizontalAdvance(text) + 10
        h = fm.height() + 2
        return QRectF(self.width() - w, self.height() - h, w, h)

    def _attribution(self, p: QPainter) -> None:
        r = self._attribution_rect()
        p.fillRect(r, QColor(255, 255, 255, 200))
        p.setPen(QColor("#333333"))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, t("map.attribution"))

    # --- Bedienung ---
    def wheelEvent(self, event) -> None:
        steps = event.angleDelta().y() / 120
        if not steps:
            event.accept()
            return
        new = max(float(MIN_ZOOM), min(float(MAX_ZOOM), self.zoom + steps * WHEEL_STEP))
        if new != self.zoom:
            # um den Mauszeiger herum zoomen
            pos = event.position()
            ox, oy = self._origin()
            la, lo = latlon(ox + pos.x(), oy + pos.y(), self.zoom)
            self.zoom = new
            px, py = world_xy(la, lo, new)
            cx, cy = px - pos.x() + self.width() / 2, py - pos.y() + self.height() / 2
            self.lat, self.lon = latlon(cx, cy, new)
            self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if self._attribution_rect().contains(event.position()):
                QDesktopServices.openUrl(QUrl(ATTRIBUTION_URL))
                return
            self._drag = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None:
            d = event.position() - self._drag
            self._drag = event.position()
            cx, cy = world_xy(self.lat, self.lon, self.zoom)
            self.lat, self.lon = latlon(cx - d.x(), cy - d.y(), self.zoom)
            self.update()
            return
        near = [label for la, lo, label in self.points
                if (self.screen_pos(la, lo) - QPointF(0, 14) - event.position()).manhattanLength() < 16]
        if near:
            QToolTip.showText(event.globalPosition().toPoint(), "\n".join(near[:10]), self)
        else:
            QToolTip.hideText()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self._fitted_for = ()
        self._fit()  # Doppelklick: wieder alle Stecknadeln zeigen
        self.update()
