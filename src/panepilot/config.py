"""Speicherort und robustes Lesen/Schreiben der Konfigurationsdateien.

Alle Daten (Einstellungen, Favoriten, Fensterzustand, Tastenbelegung) liegen
außerhalb des Programms in einem eigenen Ordner:

* Linux:   ~/.config/PanePilot/Settings/  (bzw. $XDG_CONFIG_HOME/PanePilot/Settings)
* Windows: %APPDATA%\\PanePilot\\Settings\\   (für die spätere Windows-Version)

Daneben liegt ``Backups/`` mit den Sicherungen (F-850 ff.). Bis v0.7 lagen die
Dateien direkt in ``PanePilot/``; sie werden beim ersten Start einmalig nach
``Settings/`` verschoben.

Für Tests kann der Ordner über die Umgebungsvariable PANEPILOT_CONFIG_DIR
umgelenkt werden.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import APP_NAME

FAVORITES_FILE = "favorites.json"
STATE_FILE = "state.json"
SETTINGS_FILE = "settings.json"
KEYMAP_FILE = "keymap.json"


SETTINGS_SUBDIR = "Settings"
BACKUPS_SUBDIR = "Backups"
_migrated: set[str] = set()


def config_root() -> Path:
    """~/.config/PanePilot – enthält Settings/ und Backups/."""
    override = os.environ.get("PANEPILOT_CONFIG_DIR")
    if override:
        path = Path(override)
    elif sys.platform.startswith("win"):
        path = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_dir() -> Path:
    """Ordner mit allen Einstellungsdateien (…/PanePilot/Settings)."""
    root = config_root()
    path = root / SETTINGS_SUBDIR
    key = str(root)
    if key not in _migrated:
        _migrated.add(key)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            # Einmalig: Dateien aus der Zeit vor v0.8 nach Settings/ verschieben (F-850)
            for entry in list(root.iterdir()):
                if entry.name in (SETTINGS_SUBDIR, BACKUPS_SUBDIR):
                    continue
                try:
                    os.replace(entry, path / entry.name)
                except OSError:
                    pass
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_backup_dir() -> Path:
    return config_root() / BACKUPS_SUBDIR


def load_json(name: str, default: Any) -> Any:
    """Liest eine JSON-Datei. Fehlt sie, kommt der Standardwert zurück.

    Ist sie beschädigt, wird sie als <name>.defekt beiseitegelegt (damit nichts
    verloren geht) und ebenfalls der Standardwert verwendet.
    """
    path = config_dir() / name
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        try:
            path.replace(path.with_name(path.name + ".defekt"))
        except OSError:
            pass
        return default


def save_json(name: str, data: Any) -> None:
    """Schreibt atomar: erst in eine temporäre Datei, dann umbenennen.

    So bleibt bei einem Absturz während des Schreibens die alte Datei intakt.
    """
    path = config_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class Settings:
    """Allgemeine Einstellungen (in 0.1 noch ohne Dialog, aber zentral abgelegt)."""

    DEFAULTS: dict[str, Any] = {
        "language": "system",  # „system“ = Systemvorgabe (F-861)
        "show_hidden": False,
        "dirs_first": True,
        "show_parent_entry": True,
        "confirm_trash": False,
        "confirm_copy_move": True,
        "show_buttonbar": True,
        "show_fkeybar": True,
        "show_toolbar": True,
        "toolbar": ["back", "forward"],  # Inhalt der Symbolleiste, "|" = Trennstrich
        "fkeys": {},  # Abweichungen von der Startbelegung, z. B. {"F3": "refresh", "F8": null}
        "recent_filters": [],  # zuletzt benutzte Filter (F-604)
        "multirename_last": {},  # zuletzt benutzte Umbenennen-Einstellungen (F-732)
        "search_last": {},  # zuletzt benutzte Suche (F-819)
        "dup_last": {},  # Duplikate suchen: letzte Einstellungen (v1.6, L-650)
        "dup_geometry": [],
        "size_unit": "auto",  # F-844: auto, B, KB, MB, GB, KiB, MiB, GiB
        "backup_dir": "",  # leer = Standard (…/PanePilot/Backups)
        "backup_keep": 30,  # Anzahl automatischer Sicherungen (F-853)
        "last_auto_backup": "",  # Datum der letzten automatischen Sicherung
        "meta_layout": {},  # Meta-Wizard: Spalten, Breiten, Ausrichtung der Titelliste (F-913)
        "meta_sidebar": [],  # Meta-Wizard: Felder der Seitenleiste (F-926)
        "meta_custom_fields": [],  # Meta-Wizard: eigene Felder aus dem Feld-Editor (F-975)
        "meta_presets": {},  # Meta-Wizard: Vorlagen der Konverter (F-998)
        # Foto-Modus des Meta-Wizards (v1.4): eigene Einstellungen
        "meta_photo_layout": {},
        "meta_photo_sidebar": [],
        "meta_photo_custom_fields": [],
        "meta_photo_presets": {},
        "meta_photo_last_format": {},
        "meta_video_layout": {},  # v1.5: Videos
        "meta_video_sidebar": [],
        "meta_video_custom_fields": [],
        "meta_video_presets": {},
        "meta_video_last_format": {},
        "meta_dateshift": {},  # Datum verschieben: letzte Eingabe
        "meta_last_format": {},  # Meta-Wizard: zuletzt benutzte Formatstrings (F-998)
        "meta_number": {},  # Meta-Wizard: letzte Einstellungen des Nummerierungs-Assistenten (v0.9.3)
        "meta_playlist_relative": True,
        "replaygain_target": -18.0,  # ReplayGain-Ziel-Lautheit in LUFS (v0.9.6)
        "replaygain_overwrite": False,  # vorhandene ReplayGain-Werte überschreiben (v0.9.6)
        # v1.1
        "ui_scale": 100,  # Skalierung der Oberfläche in Prozent (50–200, nach Neustart)
        "dirlist": {"files": True, "depth": 0, "hidden": False, "open": True},  # Verzeichnisliste (0 = unbegrenzt)
        # v1.2
        "update_check": False,  # einmal täglich beim Start nach Updates suchen (Vorgabe: aus)
        "update_last_check": "",  # Tag der letzten Prüfung (JJJJ-MM-TT)
        "update_skip": "",  # diese Version nicht mehr automatisch anbieten
        "meta_disc": {},  # Disc-Assistent: letzte Einstellungen
        "meta_musicbrainz": {},  # MusicBrainz: angehakte Felder und Cover
        # Spenden (v0.9.11)
        "first_start": "",  # Datum des ersten Starts (JJJJ-MM-TT); Hinweis erst nach 30 Tagen
        "donate_last_shown": "",  # an diesem Tag kam der Hinweis zuletzt
        "donor_name": "",  # Spender-Name und -Code (Code ist an den Namen gebunden)
        "donor_code": "",
        "backup_last_error": {},  # fehlgeschlagene automatische Sicherung: {"date": …, "reason": …}
    }

    def __init__(self) -> None:
        stored = load_json(SETTINGS_FILE, {})
        self._values = dict(self.DEFAULTS)
        if isinstance(stored, dict):
            self._values.update({k: v for k, v in stored.items() if k in self.DEFAULTS})

    def get(self, key: str) -> Any:
        return self._values.get(key, self.DEFAULTS.get(key))

    def set(self, key: str, value: Any) -> None:
        self._values[key] = value
        self.save()

    frozen = False  # nach dem Wiederherstellen einer Sicherung nichts mehr schreiben

    def save(self) -> None:
        if not self.frozen:
            save_json(SETTINGS_FILE, self._values)
