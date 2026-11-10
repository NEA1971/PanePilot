"""Filter für die Dateiliste (F-600 ff.): Platzhalter oder reguläre Ausdrücke."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import asdict, dataclass

MAX_RECENT = 15


@dataclass(frozen=True)
class FilterSpec:
    pattern: str
    regex: bool = False
    case_sensitive: bool = False
    invert: bool = False  # „Treffer ausblenden statt anzeigen“
    dirs: bool = False  # „Auch auf Ordner anwenden“
    hide_dirs: bool = False  # „Ordner ausblenden“ – alle Ordner weg, Muster darf leer sein

    # --- Prüfen ------------------------------------------------------------------------
    def error(self) -> str | None:
        """Fehlermeldung bei ungültigem Muster, sonst None (F-602)."""
        if not self.pattern.strip():
            return None if self.hide_dirs else "empty"
        if self.regex:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                return str(exc)
        return None

    def matcher(self):
        """Funktion name → bool (True = Name passt zum Muster)."""
        flags = 0 if self.case_sensitive else re.IGNORECASE
        if not self.pattern.strip():
            return lambda name: True  # nur „Ordner ausblenden“
        if self.regex:
            rx = re.compile(self.pattern, flags)
            return lambda name: rx.search(name) is not None
        parts = [p.strip() for p in self.pattern.split(";") if p.strip()]
        # Ohne Platzhalter: Teil des Namens genügt (wie im FreeCommander-Schnellfilter)
        regexes = [re.compile(fnmatch.translate(p if any(c in p for c in "*?[") else f"*{p}*"), flags)
                   for p in parts]
        return lambda name: any(r.match(name) for r in regexes)

    def accepts(self):
        """Funktion (name, is_dir) → bool: Eintrag bleibt sichtbar."""
        match = self.matcher()

        def accept(name: str, is_dir: bool) -> bool:
            if is_dir and self.hide_dirs:
                return False
            if not self.pattern.strip():
                return True
            if is_dir and not self.dirs:
                return True
            return match(name) != self.invert

        return accept

    # --- Anzeige / Speichern -------------------------------------------------------
    def label(self) -> str:
        from .i18n import t

        if not self.pattern.strip():
            return t("filter.only_hide_dirs")
        return self.pattern

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> FilterSpec | None:
        if not isinstance(data, dict) or not isinstance(data.get("pattern"), str):
            return None
        spec = cls(pattern=data["pattern"], regex=bool(data.get("regex")),
                   case_sensitive=bool(data.get("case_sensitive")), invert=bool(data.get("invert")),
                   dirs=bool(data.get("dirs")), hide_dirs=bool(data.get("hide_dirs")))
        return spec if spec.error() is None else None


def add_recent(recent: list, spec: FilterSpec) -> list[dict]:
    """Zuletzt benutzte Filter: neuester zuerst, ohne Doppelte, höchstens MAX_RECENT."""
    items = [spec.to_dict()]
    for d in recent if isinstance(recent, list) else []:
        s = FilterSpec.from_dict(d)
        if s is not None and s != spec:
            items.append(s.to_dict())
    return items[:MAX_RECENT]


def recent_specs(recent) -> list[FilterSpec]:
    return [s for s in (FilterSpec.from_dict(d) for d in (recent if isinstance(recent, list) else [])) if s]
