"""Mehrere Favoritensätze (F-620 ff.).

Jeder Satz ist eine Datei ``Favoriten/<Name>.json`` im Konfigurationsordner;
der Name des Satzes ist der Dateiname ohne Endung. Je Satz gibt es genau ein
Modell – zeigen beide Panels denselben Satz, wirken Änderungen sofort in beiden.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QObject, Signal

from .config import FAVORITES_FILE, config_dir
from .favorites import FavoritesModel

SETS_DIR = "Favoriten"
DEFAULT_SET = "Standard"
_FORBIDDEN = set('/\\:*?"<>|')


class FavoriteSets(QObject):
    changed = Signal()  # Sätze angelegt/umbenannt/gelöscht
    renamed = Signal(str, str)  # alt, neu
    removed = Signal(str)

    def __init__(self, icons, parent=None) -> None:
        super().__init__(parent)
        self._icons = icons
        self._models: dict[str, FavoritesModel] = {}
        self.migrate()

    # --- Ablage ------------------------------------------------------------------------
    @staticmethod
    def folder() -> str:
        return str(config_dir() / SETS_DIR)

    @staticmethod
    def _file(name: str) -> str:
        return f"{SETS_DIR}/{name}.json"

    def migrate(self) -> None:
        """Einmalig: bisherige favorites.json → Favoriten/Standard.json (F-621)."""
        folder = self.folder()
        os.makedirs(folder, exist_ok=True)
        if self.names():
            return
        old = config_dir() / FAVORITES_FILE
        target = os.path.join(folder, DEFAULT_SET + ".json")
        if old.exists():
            os.replace(old, target)
        else:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write('{"version": 1, "items": []}\n')

    def names(self) -> list[str]:
        try:
            files = os.listdir(self.folder())
        except OSError:
            return []
        names = [f[:-5] for f in files if f.endswith(".json") and not f.startswith(".") and len(f) > 5]
        return sorted(names, key=lambda n: (n.casefold(), n))

    def exists(self, name: str) -> bool:
        return name in self.names()

    def model(self, name: str) -> FavoritesModel:
        m = self._models.get(name)
        if m is None:
            m = FavoritesModel(self._icons, autosave=True, parent=self, file=self._file(name))
            m.load()
            self._models[name] = m
        return m

    def loaded_models(self) -> list[FavoritesModel]:
        return list(self._models.values())

    def resolve(self, name) -> str:
        """Gespeicherten Namen prüfen; fehlt der Satz, den ersten vorhandenen nehmen."""
        names = self.names()
        if isinstance(name, str) and name in names:
            return name
        if DEFAULT_SET in names:
            return DEFAULT_SET
        if not names:
            self.migrate()
            names = self.names()
        return names[0]

    # --- Verwalten ---------------------------------------------------------------------
    def name_error(self, name: str, ignore: str | None = None) -> str | None:
        """i18n-Schlüssel der Fehlermeldung oder None (F-625)."""
        name = name.strip()
        if not name or name in (".", ".."):
            return "favsets.error_empty"
        if any(c in _FORBIDDEN for c in name) or name.startswith("."):
            return "favsets.error_chars"
        if name != ignore and any(n.casefold() == name.casefold() for n in self.names() if n != ignore):
            return "favsets.error_exists"
        return None

    def create(self, name: str) -> str:
        name = name.strip()
        path = os.path.join(self.folder(), name + ".json")
        with open(path, "x", encoding="utf-8") as fh:
            fh.write('{"version": 1, "items": []}\n')
        self.changed.emit()
        return name

    def rename(self, old: str, new: str) -> str:
        new = new.strip()
        if new == old:
            return old
        folder = self.folder()
        os.rename(os.path.join(folder, old + ".json"), os.path.join(folder, new + ".json"))
        m = self._models.pop(old, None)
        if m is not None:
            m.file = self._file(new)
            self._models[new] = m
        self.renamed.emit(old, new)
        self.changed.emit()
        return new

    def delete(self, name: str) -> None:
        if len(self.names()) <= 1:
            raise ValueError("last set")
        os.unlink(os.path.join(self.folder(), name + ".json"))
        self._models.pop(name, None)
        self.removed.emit(name)
        self.changed.emit()
