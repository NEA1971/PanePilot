"""Mehrfaches Umbenennen (F-700 ff.) – die Logik ohne Oberfläche.

Ablauf je Eintrag (F-716): Muster → Suchen und Ersetzen → Groß-/Kleinschreibung.
Ausgeführt wird in zwei Schritten über Zwischennamen (F-723): so klappen auch
Ringtausch (a→b, b→a) und reine Änderungen der Groß-/Kleinschreibung auf
Dateisystemen, die Groß-/Kleinschreibung nicht unterscheiden (NAS, USB-Sticks).
"""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, fields
from datetime import datetime

SEARCH_TEXT, SEARCH_WILDCARD, SEARCH_REGEX = "text", "wildcard", "regex"
CASE_NONE, CASE_UPPER, CASE_LOWER, CASE_FIRST, CASE_WORDS = "none", "upper", "lower", "first", "words"
DATE_NOW, DATE_MTIME, DATE_CREATED = "now", "mtime", "created"
DATE_FORMATS = ("JJJJ-MM-TT", "JJJJ-MM-TT hh-mm-ss", "JJJJ-MM-TT_hhmmss", "JJJJMMTT", "JJJJMMTT_hhmmss",
                "TT.MM.JJJJ", "JJ-MM-TT")
FORBIDDEN_CHARS = ("/", "\0")

OK, SAME, CONFLICT = "ok", "same", "conflict"


@dataclass
class RenameOptions:
    pattern: str = "[N]"
    ext_pattern: str = "[E]"
    search: str = ""
    replace: str = ""
    search_mode: str = SEARCH_TEXT
    replace_all: bool = False  # Standard: nur das erste Vorkommen (v0.7.2)
    search_case: bool = False
    case_mode: str = CASE_NONE
    include_ext: bool = False
    date_source: str = DATE_MTIME
    date_format: str = "JJJJ-MM-TT"
    counter_start: int = 1
    counter_step: int = 1
    counter_digits: int = 3

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> RenameOptions:
        opts = cls()
        if not isinstance(data, dict):
            return opts
        for f in fields(cls):
            default = getattr(opts, f.name)
            value = data.get(f.name)
            if isinstance(default, bool):
                ok = isinstance(value, bool)
            elif isinstance(default, int):
                ok = isinstance(value, int) and not isinstance(value, bool)
            else:
                ok = isinstance(value, str)
            if ok:
                setattr(opts, f.name, value)
        if opts.search_mode not in (SEARCH_TEXT, SEARCH_WILDCARD, SEARCH_REGEX):
            opts.search_mode = SEARCH_TEXT
        if opts.case_mode not in (CASE_NONE, CASE_UPPER, CASE_LOWER, CASE_FIRST, CASE_WORDS):
            opts.case_mode = CASE_NONE
        if opts.date_source not in (DATE_NOW, DATE_MTIME, DATE_CREATED):
            opts.date_source = DATE_MTIME
        opts.counter_digits = min(max(opts.counter_digits, 1), 10)
        return opts


@dataclass
class Item:
    """Ein Eintrag der Liste (Auszug aus filemodel.Entry)."""

    name: str
    is_dir: bool
    mtime: float = 0.0
    btime: float = -1.0  # Erstellungszeit, -1 = unbekannt


@dataclass
class Result:
    old: str
    new: str
    status: str  # OK, SAME, CONFLICT
    reason: str = ""  # i18n-Schlüssel bei CONFLICT


# --- Bausteine ----------------------------------------------------------------------------
def split_name(name: str, is_dir: bool) -> tuple[str, str]:
    """'foto.jpg' → ('foto', 'jpg'); Ordner und '.bashrc' haben keine Endung."""
    if is_dir:
        return name, ""
    stem, ext = os.path.splitext(name)
    if not stem or not ext:
        return name, ""
    return stem, ext[1:]


_DATE_TOKENS = re.compile(r"JJJJ|JJ|MM|TT|hh|mm|ss")


def format_date(ts: float, fmt: str) -> str:
    dt = datetime.fromtimestamp(ts)
    values = {"JJJJ": f"{dt.year:04d}", "JJ": f"{dt.year % 100:02d}", "MM": f"{dt.month:02d}",
              "TT": f"{dt.day:02d}", "hh": f"{dt.hour:02d}", "mm": f"{dt.minute:02d}", "ss": f"{dt.second:02d}"}
    return _DATE_TOKENS.sub(lambda m: values[m.group(0)], fmt)


_PLACEHOLDER = re.compile(r"\[(N(\d+)?(-)?(\d+)?|E|C|D)\]", re.IGNORECASE)


def expand_pattern(pattern: str, stem: str, ext: str, counter: str, date: str) -> str:
    def repl(m: re.Match) -> str:
        token = m.group(1).upper()
        if token == "E":
            return ext
        if token == "C":
            return counter
        if token == "D":
            return date
        start, dash, end = m.group(2), m.group(3), m.group(4)
        if start is None:
            return stem  # [N]
        a = max(int(start), 1) - 1
        if dash is None:
            return stem[a:a + 1]  # [N3]
        if end is None:
            return stem[a:]  # [N3-]
        return stem[a:int(end)]  # [N1-5]

    return _PLACEHOLDER.sub(repl, pattern)


def search_regex(opts: RenameOptions) -> re.Pattern | None:
    """Kompiliertes Suchmuster oder None (kein Suchen). Wirft re.error bei ungültigem Ausdruck."""
    if not opts.search:
        return None
    flags = 0 if opts.search_case else re.IGNORECASE
    if opts.search_mode == SEARCH_REGEX:
        return re.compile(opts.search, flags)
    if opts.search_mode == SEARCH_WILDCARD:
        parts = []
        for ch in opts.search:
            parts.append(".*?" if ch == "*" else "." if ch == "?" else re.escape(ch))
        return re.compile("".join(parts), flags)
    return re.compile(re.escape(opts.search), flags)


def validate(opts: RenameOptions) -> str | None:
    """Fehlermeldung (Text) bei ungültigem regulärem Ausdruck oder Ersetzungstext, sonst None."""
    try:
        rx = search_regex(opts)
        if rx is not None and opts.search_mode == SEARCH_REGEX:
            rx.sub(opts.replace, "")  # prüft auch Rückbezüge wie \3 ohne dritte Gruppe
    except (re.error, IndexError) as exc:
        return str(exc)
    return None


def change_case(text: str, mode: str) -> str:
    if mode == CASE_UPPER:
        return text.upper()
    if mode == CASE_LOWER:
        return text.lower()
    if mode == CASE_FIRST:
        return text[:1].upper() + text[1:].lower()
    if mode == CASE_WORDS:
        return re.sub(r"[^\W_]+", lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(), text)
    return text


def _replace(rx: re.Pattern | None, opts: RenameOptions, text: str) -> str:
    if rx is None:
        return text
    count = 0 if opts.replace_all else 1
    if opts.search_mode == SEARCH_REGEX:
        return rx.sub(opts.replace, text, count=count)
    return rx.sub(lambda _m: opts.replace, text, count=count)


def new_name(item: Item, opts: RenameOptions, index: int, now: float, rx: re.Pattern | None) -> str:
    stem, ext = split_name(item.name, item.is_dir)
    counter = opts.counter_start + index * opts.counter_step
    sign = "-" if counter < 0 else ""
    counter_text = sign + str(abs(counter)).zfill(max(1, opts.counter_digits))
    if opts.date_source == DATE_NOW:
        ts = now
    elif opts.date_source == DATE_CREATED and item.btime is not None and item.btime >= 0:
        ts = item.btime
    else:
        ts = item.mtime
    date = format_date(ts, opts.date_format)
    name = expand_pattern(opts.pattern, stem, ext, counter_text, date)
    new_ext = "" if item.is_dir else expand_pattern(opts.ext_pattern, stem, ext, counter_text, date)
    if opts.include_ext:
        full = f"{name}.{new_ext}" if new_ext else name
        return change_case(_replace(rx, opts, full), opts.case_mode)
    name = change_case(_replace(rx, opts, name), opts.case_mode)
    return f"{name}.{new_ext}" if new_ext else name


def compute(items: list[Item], opts: RenameOptions, existing: set[str], now: float | None = None) -> list[Result]:
    """Neue Namen samt Prüfung (F-722). existing = alle Namen im Ordner (auch ausgefilterte)."""
    now = time.time() if now is None else now
    rx = search_regex(opts)
    results = []
    for i, item in enumerate(items):
        new = new_name(item, opts, i, now, rx)
        results.append(Result(item.name, new, SAME if new == item.name else OK))
    olds = {r.old for r in results}
    counts: dict[str, int] = {}
    for r in results:
        counts[r.new] = counts.get(r.new, 0) + 1
    for r in results:
        reason = ""
        if not r.new.strip() or r.new in (".", ".."):
            reason = "rename.err_empty"
        elif any(c in r.new for c in FORBIDDEN_CHARS):
            reason = "rename.err_chars"
        elif counts[r.new] > 1:
            reason = "rename.err_duplicate"
        elif r.status == OK and r.new in existing and r.new not in olds:
            reason = "rename.err_exists"
        if reason:
            r.status, r.reason = CONFLICT, reason
    return results


# --- Ausführen ----------------------------------------------------------------------------
def perform(folder: str, pairs: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Benennt um (alt → neu). Liefert (erledigt, Fehler [(Name, Grund)]).

    Schritt 1: alle Quellen auf eindeutige Zwischennamen. Schritt 2: Zwischennamen
    auf die Zielnamen. Belegt ein fremder Eintrag den Zielnamen (z. B. auf einem
    Dateisystem ohne Unterscheidung der Groß-/Kleinschreibung), wird nicht
    überschrieben, sondern der alte Name wiederhergestellt.
    """
    tag = uuid.uuid4().hex[:8]
    staged: list[tuple[str, str, str]] = []  # (alt, Zwischenname, neu)
    errors: list[tuple[str, str]] = []
    for i, (old, new) in enumerate(pairs):
        if old == new:
            continue
        tmp = f".pp-umbenennen-{tag}-{i}"
        try:
            os.rename(os.path.join(folder, old), os.path.join(folder, tmp))
            staged.append((old, tmp, new))
        except OSError as exc:
            errors.append((old, exc.strerror or str(exc)))
    done: list[tuple[str, str]] = []
    for old, tmp, new in staged:
        target = os.path.join(folder, new)
        try:
            if os.path.lexists(target):
                raise FileExistsError(17, "exists")
            os.rename(os.path.join(folder, tmp), target)
            done.append((old, new))
        except OSError as exc:
            reason = "exists" if isinstance(exc, FileExistsError) else (exc.strerror or str(exc))
            errors.append((old, reason))
            try:
                os.rename(os.path.join(folder, tmp), os.path.join(folder, old))
            except OSError as exc2:
                errors.append((old, f"{tmp}: {exc2.strerror or exc2}"))
    return done, errors
