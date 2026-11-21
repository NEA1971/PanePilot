"""Fingerabdrücke von Bildern und Videos für „f) Ähnliches Bild/Video“ (v1.22, L-2200 ff.).

Bilder: Differenz-Hash (dHash) mit 64 Bit – unempfindlich gegen andere Größe, Kompression, Format und leichte
Farb-/Helligkeitsänderungen, aber nicht gegen Drehen, Spiegeln oder starkes Beschneiden.
Videos: Laufzeit plus dHash von 5 Einzelbildern bei 10/30/50/70/90 % (ffmpeg).
Die Fingerabdrücke werden in ``~/.cache/PanePilot/fingerprints.sqlite`` gemerkt (Pfad + Größe + Änderungszeit).
"""

from __future__ import annotations

import io
import os
import sqlite3
import subprocess
import threading
from dataclasses import dataclass, field

IMAGE_EXT = {".jpg", ".jpeg", ".jpe", ".png", ".webp", ".heic", ".heif", ".gif", ".bmp", ".tif", ".tiff"}
FRAMES = (0.1, 0.3, 0.5, 0.7, 0.9)
BITS = 64
DURATION_TOLERANCE = 0.02  # Laufzeit darf höchstens 2 % abweichen (L-2203)
KIND_IMAGE, KIND_VIDEO = "image", "video"


@dataclass
class Print:
    kind: str
    hashes: list[int] = field(default_factory=list)  # 1 (Bild) bzw. bis zu 5 (Video)
    width: int = 0
    height: int = 0
    duration: float = 0.0  # Sekunden (Video)

    @property
    def pixels(self) -> int:
        return self.width * self.height


def kind_of(path: str) -> str | None:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXT:
        return KIND_IMAGE
    from .videotags import is_video

    return KIND_VIDEO if is_video(path) else None


def dhash(img) -> int:
    """64-Bit-Differenz-Hash eines PIL-Bilds."""
    from PIL import Image

    small = img.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    px = list(small.getdata())
    value = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            value = (value << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return value


def similarity(a: int, b: int) -> float:
    return 1.0 - (a ^ b).bit_count() / BITS


_heif_lock = threading.Lock()
_heif_done = False


def _register_heif(path: str) -> None:
    global _heif_done
    if _heif_done or os.path.splitext(path)[1].lower() not in (".heic", ".heif"):
        return
    with _heif_lock:
        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except Exception:  # noqa: BLE001
            pass
        _heif_done = True


def image_print(path: str) -> Print | None:
    from PIL import Image, ImageOps

    _register_heif(path)
    try:
        with Image.open(path) as img:
            w, h = img.size
            try:
                if img.getexif().get(0x0112, 1) in (5, 6, 7, 8):  # hochkant gespeichert
                    w, h = h, w
            except Exception:  # noqa: BLE001
                pass
            img.draft("RGB", (128, 128))  # JPEG: schnell verkleinert laden
            if getattr(img, "is_animated", False):
                img.seek(0)
            return Print(KIND_IMAGE, [dhash(ImageOps.exif_transpose(img))], w, h)
    except Exception:  # noqa: BLE001 – kaputtes oder unbekanntes Bild: kein Fingerabdruck
        return None


def _video_info(path: str) -> tuple[float, int, int]:
    from . import videotags as vt

    info = vt.probe(path) or {}
    try:
        duration = float((info.get("format") or {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    w = h = 0
    for st in info.get("streams") or []:
        if st.get("codec_type") == "video" and not (st.get("disposition") or {}).get("attached_pic"):
            w, h = int(st.get("width") or 0), int(st.get("height") or 0)
            if not duration:
                try:
                    duration = float(st.get("duration") or 0)
                except ValueError:
                    pass
            break
    return duration, w, h


def video_print(path: str, stop=lambda: False) -> Print | None:
    from PIL import Image

    from . import videotags as vt

    tool = vt.ffmpeg()
    if tool is None:
        return None
    duration, w, h = _video_info(path)
    if duration <= 0 or not w:
        return None
    hashes = []
    for share in FRAMES:
        if stop():
            return None
        try:
            proc = subprocess.run([tool, "-v", "error", "-nostdin", "-ss", f"{duration * share:.2f}", "-i", path,
                                   "-map", "0:V:0", "-frames:v", "1", "-an", "-sn", "-vf", "scale=64:-2",
                                   "-f", "image2pipe", "-vcodec", "png", "-"],
                                  capture_output=True, env=vt._env(), timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0 or not proc.stdout:
            continue
        try:
            with Image.open(io.BytesIO(proc.stdout)) as frame:
                hashes.append(dhash(frame))
        except Exception:  # noqa: BLE001
            continue
    if len(hashes) < 3:  # zu wenige Bilder lesbar
        return None
    return Print(KIND_VIDEO, hashes, w, h, duration)


def make_print(path: str, stop=lambda: False) -> Print | None:
    kind = kind_of(path)
    if kind == KIND_IMAGE:
        return image_print(path)
    if kind == KIND_VIDEO:
        return video_print(path, stop)
    return None


def print_similarity(a: Print, b: Print) -> float:
    """0–1; Bilder nur mit Bildern, Videos nur mit Videos ähnlicher Laufzeit (L-2203/L-2204)."""
    if a.kind != b.kind or not a.hashes or not b.hashes:
        return 0.0
    if a.kind == KIND_IMAGE:
        return similarity(a.hashes[0], b.hashes[0])
    longer = max(a.duration, b.duration)
    if longer <= 0 or abs(a.duration - b.duration) > longer * DURATION_TOLERANCE:
        return 0.0
    n = min(len(a.hashes), len(b.hashes))
    return sum(similarity(x, y) for x, y in zip(a.hashes[:n], b.hashes[:n])) / n


# --- Zwischenspeicher ---------------------------------------------------------------------------------------
def cache_file() -> str:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "PanePilot", "fingerprints.sqlite")


class Cache:
    """Fingerabdrücke je Pfad, gültig solange Größe und Änderungszeit gleich sind (L-2205)."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or cache_file()
        self.db = None
        try:
            os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
            self.db = sqlite3.connect(self.path, timeout=5)
            self.db.execute("CREATE TABLE IF NOT EXISTS prints (path TEXT PRIMARY KEY, size INTEGER, mtime REAL,"
                            " kind TEXT, hashes TEXT, width INTEGER, height INTEGER, duration REAL)")
        except sqlite3.Error:
            self.db = None

    def get(self, path: str, size: int, mtime: float) -> Print | None:
        if self.db is None:
            return None
        try:
            row = self.db.execute("SELECT size, mtime, kind, hashes, width, height, duration FROM prints"
                                  " WHERE path = ?", (path,)).fetchone()
        except sqlite3.Error:
            return None
        if row is None or row[0] != size or abs(row[1] - mtime) > 0.001:
            return None
        hashes = [int(h, 16) for h in (row[3] or "").split(",") if h]
        return Print(row[2], hashes, row[4], row[5], row[6])

    def put(self, path: str, size: int, mtime: float, p: Print) -> None:
        if self.db is None:
            return
        try:
            self.db.execute("INSERT OR REPLACE INTO prints VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (path, size, mtime, p.kind, ",".join(f"{h:016x}" for h in p.hashes), p.width,
                             p.height, p.duration))
        except sqlite3.Error:
            pass

    def close(self) -> None:
        if self.db is not None:
            try:
                self.db.commit()
                self.db.close()
            except sqlite3.Error:
                pass
            self.db = None
