"""Installierte Programme (Linux, .desktop-Dateien) für „Öffnen mit …“.

Gelesen werden die Anwendungsordner nach freedesktop.org-Standard:
``$XDG_DATA_HOME/applications`` und ``$XDG_DATA_DIRS/*/applications``
(dazu gehören auch Flatpak-Programme). Das Standardprogramm je Dateityp
liefert ``xdg-mime``; damit wird es auch gesetzt – genau wie in Nautilus.
"""

from __future__ import annotations

import configparser
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QLocale, QMimeDatabase, QProcess
from PySide6.QtGui import QIcon

from .util import child_environment, detached_ok


@dataclass
class DesktopApp:
    id: str  # z. B. "org.gnome.TextEditor.desktop"
    name: str
    exec: str
    icon: str = ""
    mime_types: list[str] = field(default_factory=list)
    path: str = ""

    def qicon(self) -> QIcon:
        if not self.icon:
            return QIcon.fromTheme("application-x-executable")
        if os.path.isabs(self.icon):
            return QIcon(self.icon)
        return QIcon.fromTheme(self.icon, QIcon.fromTheme("application-x-executable"))


def application_dirs() -> list[str]:
    home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    dirs = [home] + (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    for extra in (str(Path.home() / ".local/share/flatpak/exports/share"), "/var/lib/flatpak/exports/share"):
        if extra not in dirs:
            dirs.append(extra)
    result = []
    for d in dirs:
        p = os.path.join(d, "applications")
        if d and p not in result and os.path.isdir(p):
            result.append(p)
    return result


def _localized(section, key: str) -> str:
    lang = QLocale().name()  # z. B. "de_DE"
    for k in (f"{key}[{lang}]", f"{key}[{lang.split('_')[0]}]", key):
        if k in section:
            return section[k]
    return ""


def parse_desktop_file(path: str, app_id: str) -> DesktopApp | None:
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # Groß-/Kleinschreibung der Schlüssel erhalten
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError, OSError):
        return None
    if "Desktop Entry" not in parser:
        return None
    sec = parser["Desktop Entry"]
    if sec.get("Type", "Application") != "Application":
        return None
    if sec.get("NoDisplay", "false").lower() == "true" or sec.get("Hidden", "false").lower() == "true":
        return None
    exec_line = sec.get("Exec", "")
    name = _localized(sec, "Name")
    if not exec_line or not name:
        return None
    try_exec = sec.get("TryExec", "")
    if try_exec and not _which(try_exec):
        return None
    mimes = [m for m in sec.get("MimeType", "").split(";") if m]
    return DesktopApp(app_id, name, exec_line, sec.get("Icon", ""), mimes, path)


def _which(program: str) -> bool:
    if os.path.isabs(program):
        return os.access(program, os.X_OK)
    return any(os.access(os.path.join(d, program), os.X_OK) for d in os.environ.get("PATH", "").split(":") if d)


_cache: tuple[tuple, list[DesktopApp]] | None = None


def all_apps() -> list[DesktopApp]:
    """Alle sichtbaren Programme (zwischengespeichert, bis sich ein Anwendungsordner ändert)."""
    global _cache
    dirs = application_dirs()
    stamp = tuple((d, _tree_mtime(d)) for d in dirs)
    if _cache is not None and _cache[0] == stamp:
        return list(_cache[1])
    apps = _scan_apps(dirs)
    _cache = (stamp, apps)
    return list(apps)


def _tree_mtime(folder: str) -> float:
    latest = 0.0
    for root, _dirs, _files in os.walk(folder):
        try:
            latest = max(latest, os.stat(root).st_mtime)
        except OSError:
            pass
    return latest


def _scan_apps(dirs: list[str]) -> list[DesktopApp]:
    """Bei gleicher ID gewinnt der Benutzerordner."""
    seen: dict[str, DesktopApp] = {}
    for folder in dirs:
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if not name.endswith(".desktop"):
                    continue
                rel = os.path.relpath(os.path.join(root, name), folder)
                app_id = rel.replace(os.sep, "-")
                if app_id in seen:
                    continue
                app = parse_desktop_file(os.path.join(root, name), app_id)
                if app is not None:
                    seen[app_id] = app
    return sorted(seen.values(), key=lambda a: a.name.casefold())


def mime_of(path: str) -> str:
    db = QMimeDatabase()
    if os.path.isdir(path):
        return "inode/directory"
    return db.mimeTypeForFile(path).name()


def _mime_family(mime: str) -> list[str]:
    db = QMimeDatabase()
    mt = db.mimeTypeForName(mime)
    names = [mime] + ([a for a in mt.allAncestors()] if mt.isValid() else [])
    return names


def _run_quiet(cmd: list[str]) -> str:
    qenv = child_environment()
    env = {k: qenv.value(k) for k in qenv.keys()}
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3, env=env).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def default_app_id(mime: str) -> str:
    return _run_quiet(["xdg-mime", "query", "default", mime])


def set_default_app(app: DesktopApp, mime: str) -> bool:
    env = child_environment()
    try:
        result = subprocess.run(["xdg-mime", "default", app.id, mime], capture_output=True, timeout=5,
                                env={k: env.value(k) for k in env.keys()})
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def apps_for(mime: str, apps: list[DesktopApp] | None = None) -> list[DesktopApp]:
    """Programme für einen Dateityp; das Standardprogramm steht oben."""
    apps = apps if apps is not None else all_apps()
    family = _mime_family(mime)
    exact, related = [], []
    for app in apps:
        if mime in app.mime_types:
            exact.append(app)
        elif any(m in app.mime_types for m in family[1:]):
            related.append(app)
    result = exact + related
    default = default_app_id(mime)
    if default:
        for i, app in enumerate(result):
            if app.id == default:
                result.insert(0, result.pop(i))
                break
        else:
            match = next((a for a in apps if a.id == default), None)
            if match is not None:
                result.insert(0, match)
    return result


def file_uri(path: str) -> str:
    """Gültige file://-Adresse: Leerzeichen und Sonderzeichen kodiert (v0.9.8).

    Vorher wurde der Pfad unkodiert angehängt; VLC konnte dann den Ordner einer Playlist nicht bestimmen
    und suchte relative Einträge im Wurzelverzeichnis."""
    from PySide6.QtCore import QUrl

    return QUrl.fromLocalFile(path).toString(QUrl.ComponentFormattingOption.FullyEncoded)


def build_commands(app: DesktopApp, paths: list[str]) -> list[list[str]]:
    """Exec-Zeile nach freedesktop.org auflösen (%f/%F/%u/%U usw.)."""
    try:
        parts = shlex.split(app.exec)
    except ValueError:
        parts = app.exec.split()
    single = any(tok in ("%f", "%u") for tok in parts)
    multi = any(tok in ("%F", "%U") for tok in parts)
    targets = [[p] for p in paths] if single else [paths]
    commands = []
    for group in targets:
        cmd: list[str] = []
        for tok in parts:
            if tok == "%f":
                cmd.append(group[0])
            elif tok == "%u":
                cmd.append(file_uri(group[0]))
            elif tok == "%F":
                cmd.extend(group)
            elif tok == "%U":
                cmd.extend(file_uri(p) for p in group)
            elif tok == "%i":
                if app.icon:
                    cmd.extend(["--icon", app.icon])
            elif tok == "%c":
                cmd.append(app.name)
            elif tok == "%k":
                cmd.append(app.path)
            elif tok in ("%d", "%D", "%n", "%N", "%v", "%m"):
                continue
            else:
                cmd.append(tok.replace("%%", "%"))
        if not single and not multi:
            cmd.extend(group)
        if cmd:
            commands.append(cmd)
    return commands


def launch(app: DesktopApp, paths: list[str]) -> bool:
    ok = True
    workdir = os.path.dirname(paths[0]) if paths else str(Path.home())
    for cmd in build_commands(app, paths):
        proc = QProcess()
        proc.setProgram(cmd[0])
        proc.setArguments(cmd[1:])
        proc.setWorkingDirectory(workdir)
        proc.setProcessEnvironment(child_environment())
        ok = detached_ok(proc.startDetached()) and ok
    return ok


def default_text_editor(apps: list[DesktopApp] | None = None) -> DesktopApp | None:
    found = apps_for("text/plain", apps)
    return found[0] if found else None
