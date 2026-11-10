"""ReplayGain 2.0 (v0.9.6): Lautheit nach EBU R128 mit ffmpeg messen, Track- und Album-Werte berechnen.

Bezug: −18 LUFS (einstellbar). Album-Lautheit nach dem Verfahren von EBU R128/ITU-R BS.1770 aus den
400-ms-Blöcken aller Titel des Albums (Absolut-Gate −70 LUFS, Relativ-Gate −10 LU).
Opus speichert die Werte als R128_*_GAIN (Q7.8, bezogen auf −23 LUFS).
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
from dataclasses import dataclass, field

DEFAULT_TARGET = -18.0
OPUS_REFERENCE_OFFSET = -5.0  # Opus: −23 LUFS statt −18 LUFS

TRACK_GAIN, TRACK_PEAK = "REPLAYGAIN_TRACK_GAIN", "REPLAYGAIN_TRACK_PEAK"
ALBUM_GAIN, ALBUM_PEAK = "REPLAYGAIN_ALBUM_GAIN", "REPLAYGAIN_ALBUM_PEAK"
R128_TRACK, R128_ALBUM = "R128_TRACK_GAIN", "R128_ALBUM_GAIN"


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def _env() -> dict:
    """Umgebung ohne die Bibliothekspfade des AppImage (sonst kann das System-ffmpeg abstürzen)."""
    from .util import child_environment

    env = child_environment()
    return {k: env.value(k) for k in env.keys()}


@dataclass
class Measurement:
    loudness: float  # integrierte Lautheit (LUFS)
    peak: float  # Spitzenwert, linear (1.0 = 0 dBFS)
    blocks: list[float] = field(default_factory=list)  # Momentan-Lautheit je 100 ms (400-ms-Fenster)


_BLOCK = re.compile(r"t:\s*([\d.]+)\s.*?M:\s*(-?[\d.]+)")
_SUMMARY_I = re.compile(r"Integrated loudness:\s*I:\s*(-?[\d.]+|-inf)\s*LUFS", re.S)
_SUMMARY_PEAK = re.compile(r"Sample peak:\s*Peak:\s*(-?[\d.]+|-inf)\s*dBFS", re.S)


def measure(path: str, stop=lambda: False) -> Measurement:
    """Misst einen Titel; wirft OSError/ValueError bei Fehlern."""
    exe = ffmpeg_path()
    if not exe:
        raise OSError("ffmpeg")
    cmd = [exe, "-hide_banner", "-nostdin", "-nostats", "-v", "verbose", "-i", path, "-vn", "-map", "0:a:0",
           "-filter:a", "ebur128=peak=sample:framelog=verbose", "-f", "null", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=_env(),
                            text=True, encoding="utf-8", errors="replace")
    blocks: list[float] = []
    tail: list[str] = []
    assert proc.stderr is not None
    for line in proc.stderr:
        if stop():
            proc.kill()
            proc.wait()
            raise InterruptedError()
        if "Parsed_ebur128" in line and " M:" in line:
            m = _BLOCK.search(line)
            if m and float(m.group(1)) >= 0.399:  # erst ab vollem 400-ms-Fenster
                blocks.append(float(m.group(2)))
        else:
            tail.append(line)
            if len(tail) > 60:
                del tail[:20]
    proc.wait()
    text = "".join(tail)
    mi, mp = _SUMMARY_I.search(text), _SUMMARY_PEAK.search(text)
    if proc.returncode != 0 or mi is None or mp is None:
        last = next((ln.strip() for ln in reversed(tail) if ln.strip()), "")
        raise ValueError(last or f"ffmpeg {proc.returncode}")
    loud = float("-inf") if mi.group(1) == "-inf" else float(mi.group(1))
    if blocks:
        loud = integrated(blocks)  # genauer als die auf 0,1 gerundete Zusammenfassung
    peak = 0.0 if mp.group(1) == "-inf" else 10 ** (float(mp.group(1)) / 20)
    return Measurement(loud, peak, blocks)


def integrated(blocks: list[float]) -> float:
    """Integrierte Lautheit aus Blöcken (ITU-R BS.1770: Absolut- und Relativ-Gate)."""
    gated = [b for b in blocks if b > -70.0]
    if not gated:
        return float("-inf")

    def mean_lufs(values):
        return -0.691 + 10 * math.log10(sum(10 ** ((v + 0.691) / 10) for v in values) / len(values))

    relative = mean_lufs(gated) - 10.0
    final = [b for b in gated if b > relative]
    return mean_lufs(final) if final else float("-inf")


def gain_text(gain: float) -> str:
    return f"{gain:+.2f} dB".replace("+", "") if gain < 0 else f"{gain:+.2f} dB"


def peak_text(peak: float) -> str:
    return f"{peak:.6f}"


def r128_text(gain: float) -> str:
    """Opus: Q7.8-Festkommazahl (Gain × 256), begrenzt auf 16 Bit."""
    return str(max(-32768, min(32767, int(round(gain * 256)))))


def gain_for(loudness: float, target: float) -> float:
    if math.isinf(loudness):
        return 0.0  # Stille: nichts verändern
    return round(target - loudness, 2)


def album_values(measurements: list[Measurement]) -> tuple[float, float]:
    """Album-Lautheit aus allen Blöcken der Titel und größter Spitzenwert."""
    blocks = [b for m in measurements for b in m.blocks]
    loud = integrated(blocks) if blocks else max((m.loudness for m in measurements), default=float("-inf"))
    return loud, max((m.peak for m in measurements), default=0.0)


def tag_values(codec: str, track: Measurement, album_loudness: float | None, album_peak: float | None,
               target: float) -> dict[str, str]:
    """Zu schreibende Felder (Name → Wert) für einen Titel."""
    if codec == "Opus":
        values = {R128_TRACK: r128_text(gain_for(track.loudness, target + OPUS_REFERENCE_OFFSET))}
        if album_loudness is not None:
            values[R128_ALBUM] = r128_text(gain_for(album_loudness, target + OPUS_REFERENCE_OFFSET))
        return values
    values = {TRACK_GAIN: gain_text(gain_for(track.loudness, target)), TRACK_PEAK: peak_text(track.peak)}
    if album_loudness is not None:
        values[ALBUM_GAIN] = gain_text(gain_for(album_loudness, target))
        values[ALBUM_PEAK] = peak_text(album_peak or 0.0)
    return values
