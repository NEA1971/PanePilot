"""Mehrsprachigkeit (F-860 ff.).

Kein Text der Oberfläche steht fest im Programmcode. Jeder Text wird über einen
Schlüssel aus einer Sprachdatei geladen. Sprachdateien gibt es an zwei Orten:

* mitgeliefert: ``i18n/<kürzel>.json`` im Programm
* eigene: ``Settings/Sprachen/<kürzel>.json``

Gehört eine eigene Datei zu einer mitgelieferten Sprache, enthält sie nur die
geänderten Texte (v0.9.10). Alle anderen Texte kommen weiter aus der
mitgelieferten Datei, so kommen neue Texte späterer Versionen trotzdem an.
Selbst angelegte Sprachen stehen ganz in ihrer eigenen Datei. Andere Dateien im
Ordner (z. B. Exporte ``PanePilot_Sprache-de_….json``) werden nicht geladen.

Jede Datei enthält unter ``_meta`` ihren Anzeigenamen, ihr Kürzel und ihre
Ersatzsprache. Fehlt ein Text, wird erst die Ersatzsprache (Dialekte: Deutsch,
sonst Englisch), dann Deutsch verwendet; fehlt er auch dort, erscheint der
Schlüssel selbst (fällt beim Testen sofort auf).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..resources import resource_path

BASE_LANGUAGE = "de"
SYSTEM = "system"
USER_SUBDIR = "Sprachen"

_strings: dict[str, str] = {}
_fallback: dict[str, str] = {}
_base: dict[str, str] = {}
_current = BASE_LANGUAGE


@dataclass
class LanguageInfo:
    code: str
    name: str
    fallback: str  # Kürzel der Ersatzsprache
    path: Path  # eigene Datei, falls vorhanden, sonst die mitgelieferte
    user: bool  # es gibt eine eigene Datei im Einstellungsordner
    bundled: Path | None = None  # mitgelieferte Datei (None bei selbst angelegten Sprachen)

    @property
    def own(self) -> bool:
        """Selbst angelegte Sprache (keine mitgelieferte Datei dazu)."""
        return self.bundled is None


def user_folder() -> Path:
    from ..config import config_dir

    folder = config_dir() / USER_SUBDIR
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _read_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _strings_of(data: dict[str, Any]) -> dict[str, str]:
    return {k: v for k, v in data.items() if isinstance(v, str) and not k.startswith("_")}


def _meta(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("_meta") if isinstance(data.get("_meta"), dict) else {}


def _info(path: Path, user: bool) -> LanguageInfo | None:
    data = _read_file(path)
    if not data:
        return None
    meta = _meta(data)
    code = str(meta.get("code") or path.stem)
    fallback = str(meta.get("fallback") or ("" if code == BASE_LANGUAGE else "en"))
    return LanguageInfo(code=code, name=str(meta.get("name") or code), fallback=fallback, path=path, user=user)


def bundled_languages() -> dict[str, LanguageInfo]:
    found: dict[str, LanguageInfo] = {}
    for path in sorted(resource_path("i18n").glob("*.json")):
        info = _info(path, False)
        if info:
            info.bundled = path
            found[info.code] = info
    return found


def languages() -> dict[str, LanguageInfo]:
    """Alle verfügbaren Sprachen (F-862); eigene Dateien ergänzen bzw. ändern mitgelieferte."""
    found = bundled_languages()
    try:
        user_files = sorted(user_folder().glob("*.json"))
    except OSError:
        user_files = []
    for path in user_files:
        info = _info(path, True)
        if not info or info.code != path.stem:
            continue  # z. B. ein Export im selben Ordner
        base = found.get(info.code)
        if base is not None:
            # Änderungen zu einer mitgelieferten Sprache: Name und Ersatzsprache bleiben
            found[info.code] = LanguageInfo(info.code, base.name, base.fallback, path, True, base.bundled)
        else:
            found[info.code] = info
    return found


def available_languages() -> list[str]:
    return sorted(languages())


def read_language(code: str) -> dict[str, str]:
    """Alle Texte einer Sprache, eigene Änderungen eingerechnet."""
    info = languages().get(code)
    if not info:
        return {}
    result = read_bundled(code)
    if info.user:
        result.update({k: v for k, v in _strings_of(_read_file(info.path)).items() if v})
    return result


def read_bundled(code: str) -> dict[str, str]:
    """Nur die mitgelieferten Texte (Spalte „Original“ im Editor)."""
    info = bundled_languages().get(code)
    return _strings_of(_read_file(info.bundled)) if info and info.bundled else {}


def read_user(code: str) -> dict[str, str]:
    """Nur der Inhalt der eigenen Datei."""
    path = user_folder() / f"{code}.json"
    return _strings_of(_read_file(path)) if path.exists() else {}


def system_language() -> str:
    """Systemsprache, wenn es dafür eine Datei gibt, sonst Englisch (F-861)."""
    from PySide6.QtCore import QLocale

    langs = languages()
    for name in QLocale.system().uiLanguages() or [QLocale.system().name()]:
        code = name.replace("-", "_").split("_")[0].lower()
        if code in langs:
            return code
    return "en" if "en" in langs else BASE_LANGUAGE


def resolve(lang: str | None) -> str:
    langs = languages()
    if not lang or lang == SYSTEM or lang not in langs:
        return system_language()
    return lang


def load_language(lang: str = BASE_LANGUAGE) -> None:
    global _strings, _fallback, _base, _current
    code = resolve(lang)
    langs = languages()
    _base = read_language(BASE_LANGUAGE)
    _strings = read_language(code) or _base
    info = langs.get(code)
    fb = info.fallback if info else ""
    _fallback = read_language(fb) if fb and fb != code else {}
    _current = code if code in langs else BASE_LANGUAGE


def current_language() -> str:
    return _current


def qt_locale_name(code: str | None = None) -> str:
    """Für Qt-Übersetzungen: Dialekte nehmen ihre Ersatzsprache (F-867)."""
    code = code or _current
    info = languages().get(code)
    if info and len(code) > 2 and info.fallback:
        return info.fallback
    return code


def t(key: str, /, **kwargs: Any) -> str:
    if not _base:
        load_language(_current)
    text = _strings.get(key) or _fallback.get(key) or _base.get(key) or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text


def all_keys(lang: str = BASE_LANGUAGE) -> set[str]:
    return set(read_language(lang))


def save_user_language(code: str, name: str, fallback: str, strings: dict[str, str]) -> Path:
    """Schreibt eine eigene Sprachdatei nach Settings/Sprachen/<code>.json.

    Bei mitgelieferten Sprachen werden nur die Texte gespeichert, die vom Original abweichen.
    """
    from ..config import save_json

    original = read_bundled(code)
    if original:
        strings = {k: v for k, v in strings.items() if v and v != original.get(k)}
    data: dict[str, Any] = {"_meta": {"code": code, "name": name, "fallback": fallback}}
    data.update({k: v for k, v in sorted(strings.items()) if v})
    save_json(f"{USER_SUBDIR}/{code}.json", data)
    return user_folder() / f"{code}.json"


def remove_user_language(code: str) -> bool:
    """„Auf Original zurücksetzen“ bzw. „Sprache löschen“: eigene Datei entfernen."""
    path = user_folder() / f"{code}.json"
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def export_data(code: str) -> dict[str, Any]:
    """Vollständige Sprachdatei mit dem aktuellen Stand (inkl. eigener Änderungen)."""
    info = languages()[code]
    data: dict[str, Any] = {"_meta": {"code": code, "name": info.name, "fallback": info.fallback}}
    data.update(dict(sorted(read_language(code).items())))
    return data


def export_language(code: str, path: Path) -> None:
    path.write_text(json.dumps(export_data(code), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


PLACEHOLDER = __import__("re").compile(r"\{(\w*)\}")


@dataclass
class ImportResult:
    code: str
    name: str
    fallback: str
    strings: dict[str, str]
    bad_placeholders: list[str]  # Schlüssel mit falschen Platzhaltern (nicht übernommen)
    unknown: int  # unbekannte Schlüssel (nicht übernommen)


def read_import(path: Path) -> ImportResult:
    """Sprachdatei zum Import lesen und prüfen. ValueError bei unbrauchbarer Datei."""
    import re

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(str(exc)) from exc
    except ValueError as exc:
        raise ValueError(f"JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON")
    meta = _meta(data)
    code = str(meta.get("code") or "").strip().lower()
    if not code:
        m = re.match(r"PanePilot_Sprache-([a-z0-9_]+)_", path.name)
        code = m.group(1) if m else path.stem.lower()
    if not re.fullmatch(r"[a-z]{2,8}(_[a-z0-9]{2,8})?", code):
        raise ValueError(code)
    base = read_bundled(BASE_LANGUAGE)
    strings, bad, unknown = {}, [], 0
    for key, value in _strings_of(data).items():
        if key not in base:
            unknown += 1
        elif set(PLACEHOLDER.findall(base[key])) != set(PLACEHOLDER.findall(value)):
            bad.append(key)
        elif value:
            strings[key] = value
    if not strings:
        raise ValueError("leer")
    known = languages().get(code)
    name = str(meta.get("name") or (known.name if known else code))
    fallback = str(meta.get("fallback") or (known.fallback if known else "en"))
    return ImportResult(code, name, fallback, strings, sorted(bad), unknown)
