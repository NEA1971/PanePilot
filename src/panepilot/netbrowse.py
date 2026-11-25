"""Netzwerk im Ordnerbaum (v3.0.1, L-4052/L-4053, nur Windows).

Hält die Serverliste für den Eintrag „Netzwerk“: selbst eingetragene Server (Einstellung ``net_servers``)
und – falls „Netzwerk im Ordnerbaum durchsuchen“ an ist – die im Netz gefundenen Rechner. Gleiche Namen
(ohne Groß-/Kleinschreibung) erscheinen nur einmal; die eigene Schreibweise gewinnt.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal


def merge(manual: list[str], found: list[str]) -> list[tuple[str, bool]]:
    """[(Name, selbst eingetragen)] ohne Doppelte, sortiert."""
    seen: dict[str, tuple[str, bool]] = {}
    for name in manual:
        name = clean(name)
        if name and name.casefold() not in seen:
            seen[name.casefold()] = (name, True)
    for name in found:
        name = clean(name)
        if name and name.casefold() not in seen:
            seen[name.casefold()] = (name, False)
    return sorted(seen.values(), key=lambda x: x[0].casefold())


def clean(name: str) -> str:
    return (name or "").strip().strip("\\/").split("\\")[0].split("/")[0].strip()


class NetworkServers(QObject):
    changed = Signal()
    _found_signal = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.settings = None
        self.found: list[str] = []
        self._running = False
        self._found_signal.connect(self._on_found)

    def configure(self, settings) -> None:
        self.settings = settings

    @property
    def browse(self) -> bool:
        return bool(self.settings.get("net_browse")) if self.settings is not None else False

    def manual(self) -> list[str]:
        value = self.settings.get("net_servers") if self.settings is not None else None
        return [clean(v) for v in value if isinstance(v, str) and clean(v)] if isinstance(value, list) else []

    def servers(self) -> list[tuple[str, bool]]:
        return merge(self.manual(), self.found if self.browse else [])

    def add(self, name: str) -> bool:
        name = clean(name)
        if not name or self.settings is None:
            return False
        current = self.manual()
        if any(n.casefold() == name.casefold() for n in current):
            return False
        self.settings.set("net_servers", current + [name])
        self.changed.emit()
        return True

    def remove(self, name: str) -> None:
        if self.settings is None:
            return
        self.settings.set("net_servers", [n for n in self.manual() if n.casefold() != name.casefold()])
        self.changed.emit()

    def refresh(self) -> None:
        """Netz im Hintergrund durchsuchen (nur wenn eingeschaltet)."""
        if not self.browse:
            self.changed.emit()
            return
        if self._running:
            return
        self._running = True

        def work() -> None:
            from . import winsys

            try:
                names = winsys.discover_servers()
            except Exception:  # noqa: BLE001 – Suche darf nie stören
                names = []
            self._found_signal.emit(names)

        threading.Thread(target=work, daemon=True).start()

    def _on_found(self, names: list) -> None:
        self._running = False
        self.found = [n for n in names if isinstance(n, str)]
        self.changed.emit()


_INSTANCE: NetworkServers | None = None


def instance() -> NetworkServers:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = NetworkServers()
    return _INSTANCE
