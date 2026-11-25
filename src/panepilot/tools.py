"""Zusatzprogramme finden (v3.1, L-4110 ff.).

PanePilot liefert ffmpeg/ffprobe, exiftool, MKVToolNix und 7-Zip nicht mit. Gesucht wird in dieser Reihenfolge:
1. eigener Pfad aus den Einstellungen (``tool_paths``: Programm → Datei),
2. der PATH,
3. unter Windows die üblichen Installationsordner (Programme, winget, Scoop, Chocolatey, ``C:\\ffmpeg\\bin``).
"""

from __future__ import annotations

import glob
import os
import shutil
import sys

IS_WINDOWS = sys.platform.startswith("win")

# Programm → (Gruppe für die Einstellungsseite)
TOOLS = ("ffmpeg", "ffprobe", "exiftool", "mkvmerge", "mkvextract", "mkvpropedit", "7z")
GROUPS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("ffmpeg", ("ffmpeg", "ffprobe"), "https://ffmpeg.org/download.html"),
    ("exiftool", ("exiftool",), "https://exiftool.org/"),
    ("mkvtoolnix", ("mkvmerge", "mkvextract", "mkvpropedit"), "https://mkvtoolnix.download/downloads.html"),
    ("7zip", ("7z",), "https://www.7-zip.org/download.html"),
)
ALIASES = {"7z": ("7z", "7zz", "7za")}

_overrides: dict[str, str] = {}


def configure(paths) -> None:
    """Eigene Pfade aus den Einstellungen übernehmen."""
    _overrides.clear()
    if isinstance(paths, dict):
        for k, v in paths.items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                _overrides[k] = v.strip()


def _win_dirs(name: str) -> list[str]:
    env = os.environ
    pf = [env.get("ProgramFiles", r"C:\Program Files"), env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
          env.get("ProgramW6432", "")]
    local = env.get("LOCALAPPDATA", "")
    home = env.get("USERPROFILE", "")
    dirs: list[str] = []
    if name in ("ffmpeg", "ffprobe"):
        dirs += [r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin"]
        if local:  # winget: …\WinGet\Packages\Gyan.FFmpeg_…\ffmpeg-…\bin
            dirs += glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "*", "bin"))
            dirs.append(os.path.join(local, "Microsoft", "WinGet", "Links"))
    elif name == "exiftool":
        dirs += [os.path.join(p, "ExifTool") for p in pf if p] + [r"C:\exiftool", r"C:\Windows"]
        if local:
            dirs += [os.path.join(local, "Programs", "ExifTool"), os.path.join(local, "Microsoft", "WinGet", "Links")]
    elif name.startswith("mkv"):
        dirs += [os.path.join(p, "MKVToolNix") for p in pf if p]
    elif name == "7z":
        dirs += [os.path.join(p, "7-Zip") for p in pf if p]
    if home:
        dirs.append(os.path.join(home, "scoop", "shims"))
    dirs.append(os.path.join(env.get("ProgramData", r"C:\ProgramData"), "chocolatey", "bin"))
    return dirs


def _candidates(name: str) -> list[str]:
    names = ALIASES.get(name, (name,))
    if name == "exiftool":
        names = ("exiftool", "exiftool(-k)")  # Windows-Download heißt „exiftool(-k).exe“
    return list(names)


def find(name: str) -> str | None:
    """Vollständiger Pfad des Programms oder None."""
    own = _overrides.get(name)
    if own and os.path.isfile(own):
        return own
    for cand in ALIASES.get(name, (name,)):
        path = shutil.which(cand)
        if path:
            return path
    if IS_WINDOWS:
        for folder in _win_dirs(name):
            for cand in _candidates(name):
                path = os.path.join(folder, cand + ".exe")
                if os.path.isfile(path):
                    return path
    return None


def status() -> dict[str, str | None]:
    return {name: find(name) for name in TOOLS}


def exiftool_args() -> list[str]:
    """exiftool unter Windows: Dateinamen als UTF-8 übergeben."""
    return ["-charset", "filename=utf8"] if IS_WINDOWS else []


# --- Windows: Hilfsprogramme ohne schwarzes Fenster, Ausgaben als UTF-8 -------------------------------------------
_patched = False


def install_windows_subprocess_defaults() -> None:
    """Startet PanePilot (Fensterprogramm) ffmpeg & Co., soll kein Konsolenfenster aufblitzen; Text kommt als UTF-8."""
    global _patched
    if not IS_WINDOWS or _patched:
        return
    import subprocess

    original = subprocess.Popen.__init__

    def init(self, *args, **kwargs):  # noqa: ANN001
        if not kwargs.get("creationflags"):
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        if (kwargs.get("text") or kwargs.get("universal_newlines")) and not kwargs.get("encoding"):
            kwargs["encoding"] = "utf-8"
            kwargs.setdefault("errors", "replace")
        original(self, *args, **kwargs)

    subprocess.Popen.__init__ = init  # type: ignore[method-assign]
    _patched = True
