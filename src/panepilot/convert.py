"""Konverter des Meta-Wizards (F-990 ff.): Formatstrings wie bei MP3TAG auswerten und Dateinamen zerlegen.

Platzhalter: %title%, %artist%, … sowie %_filename%, %_folder% und %dummy% (nur beim Zerlegen).
Funktionen: $num, $left, $right, $upper, $lower, $caps, $replace, $trim, $if.
Text in einfachen Anführungszeichen wird wörtlich genommen ('…', zwei '' = ein ').
"""

from __future__ import annotations

import re

TAG_TO_FILE, FILE_TO_TAG, TAG_TO_TAG = "tag2file", "file2tag", "tag2tag"
KINDS = (TAG_TO_FILE, FILE_TO_TAG, TAG_TO_TAG)
TAG_TO_TEXT, TEXT_TO_TAG, NUMBER, PLAYLIST = "tag2text", "text2tag", "number", "playlist"  # v0.9.3
REPLAYGAIN = "replaygain"  # v0.9.6
DISC, MUSICBRAINZ = "disc", "musicbrainz"  # v1.2
TOOLS = KINDS + (TAG_TO_TEXT, TEXT_TO_TAG, NUMBER, DISC, MUSICBRAINZ, PLAYLIST, REPLAYGAIN)

ALIASES = {"tracknumber": "track", "discnumber": "disc", "date": "year", "album artist": "albumartist",
           "band": "albumartist"}
INVALID_NAME_CHARS = '/\\:*?"<>|'  # F-995
DUMMY = "dummy"

FUNCTIONS = {
    "num": "$num(%track%,2)",
    "left": "$left(%title%,10)",
    "right": "$right(%title%,10)",
    "upper": "$upper(%title%)",
    "lower": "$lower(%title%)",
    "caps": "$caps(%title%)",
    "replace": "$replace(%title%,alt,neu)",
    "trim": "$trim(%title%)",
    "if": "$if(%albumartist%,%albumartist%,%artist%)",
}

DEFAULT_PRESETS = {
    TAG_TO_FILE: [{"name": "", "format": "$num(%track%,2) - %title%", "desc": ""},
                  {"name": "", "format": "$num(%track%,2) - %artist% - %title%", "desc": ""}],
    FILE_TO_TAG: [{"name": "", "format": "%track% - %title%", "desc": ""},
                  {"name": "", "format": "%track%. %artist% - %title%", "desc": ""}],
    TAG_TO_TAG: [{"name": "", "format": "%title% (Live)", "desc": ""}],
    TEXT_TO_TAG: [{"name": "", "format": "%track%. %title%", "desc": ""},
                  {"name": "", "format": "%track% - %title%", "desc": ""},
                  {"name": "", "format": "%title%", "desc": ""}],
}


class FormatError(ValueError):
    pass


def canonical(name: str) -> str:
    n = name.strip().lower()
    return ALIASES.get(n, n)


# --- Formatstring auswerten ----------------------------------------------------------------------------
def _caps(text: str) -> str:
    return re.sub(r"[^\W_]+", lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(), text)


def _num(text: str, digits: str) -> str:
    m = re.match(r"\s*(\d+)", text)
    if not m:
        return text
    try:
        n = int(digits)
    except ValueError:
        raise FormatError(f"$num: {digits}") from None
    return str(int(m.group(1))).zfill(n)


def _int(arg: str, fn: str) -> int:
    try:
        return int(arg.strip())
    except ValueError:
        raise FormatError(f"${fn}: {arg}") from None


def _call(name: str, args: list[str]) -> str:
    def need(n: int) -> None:
        if len(args) < n:
            raise FormatError(f"${name}()")

    if name == "num":
        need(2)
        return _num(args[0], args[1])
    if name == "left":
        need(2)
        return args[0][:_int(args[1], name)]
    if name == "right":
        need(2)
        n = _int(args[1], name)
        return args[0][-n:] if n > 0 else ""
    if name == "upper":
        need(1)
        return args[0].upper()
    if name == "lower":
        need(1)
        return args[0].lower()
    if name == "caps":
        need(1)
        return _caps(args[0])
    if name == "trim":
        need(1)
        return args[0].strip()
    if name == "replace":
        need(3)
        text = args[0]
        pairs = args[1:]
        for i in range(0, len(pairs) - 1, 2):
            if pairs[i]:
                text = text.replace(pairs[i], pairs[i + 1])
        return text
    if name == "if":
        need(2)
        return args[1] if args[0].strip() else (args[2] if len(args) > 2 else "")
    raise FormatError(f"${name}")


class _Parser:
    def __init__(self, text: str, getter) -> None:
        self.text = text
        self.pos = 0
        self.get = getter

    def parse(self, stop: str = "") -> str:
        out = []
        t = self.text
        while self.pos < len(t):
            c = t[self.pos]
            if stop and c in stop:
                break
            if c == "%":
                end = t.find("%", self.pos + 1)
                if end < 0:
                    raise FormatError("%")
                out.append(self.get(t[self.pos + 1:end]))
                self.pos = end + 1
            elif c == "$" and re.match(r"\$[a-z]+\(", t[self.pos:]):
                m = re.match(r"\$([a-z]+)\(", t[self.pos:])
                self.pos += m.end()
                args = [self.parse(",)")]
                while self.pos < len(t) and t[self.pos] == ",":
                    self.pos += 1
                    args.append(self.parse(",)"))
                if self.pos >= len(t) or t[self.pos] != ")":
                    raise FormatError(f"${m.group(1)}(")
                self.pos += 1
                out.append(_call(m.group(1), args))
            elif c == "'":
                end = self.pos + 1
                buf = []
                while end < len(t):
                    if t[end] == "'":
                        if t[end + 1:end + 2] == "'":
                            buf.append("'")
                            end += 2
                            continue
                        break
                    buf.append(t[end])
                    end += 1
                out.append("".join(buf))
                self.pos = end + 1
            else:
                out.append(c)
                self.pos += 1
        return "".join(out)


def evaluate(fmt: str, getter) -> str:
    """Wertet einen Formatstring aus; getter(name) liefert den Wert eines Platzhalters."""
    p = _Parser(fmt, lambda name: getter(canonical(name)))
    result = p.parse()
    if p.pos < len(fmt):
        raise FormatError(fmt[p.pos:])
    return result


def safe_filename(text: str) -> str:
    """Ungültige Zeichen durch „-“ ersetzen (F-995)."""
    for c in INVALID_NAME_CHARS:
        text = text.replace(c, "-")
    text = "".join(ch for ch in text if ch >= " ")
    return text.strip().rstrip(".").strip()


# --- Dateiname zerlegen (F-996) -------------------------------------------------------------------------
def pattern_fields(fmt: str) -> list[str]:
    return [canonical(m) for m in re.findall(r"%([^%]+)%", fmt)]


def compile_pattern(fmt: str) -> tuple[re.Pattern, list[str]]:
    parts = re.split(r"(%[^%]+%)", fmt)
    regex, names = "", []
    for i, part in enumerate(parts):
        if part.startswith("%") and part.endswith("%") and len(part) > 2:
            name = canonical(part[1:-1])
            last = all(not p for p in parts[i + 1:])
            group = "(.+)" if last else "(.+?)"
            regex += group
            names.append(name)
        else:
            regex += re.escape(part)
    if not names:
        raise FormatError(fmt)
    return re.compile("^" + regex + "$"), names


def parse_filename(stem: str, fmt: str) -> dict[str, str] | None:
    """Werte aus dem Dateinamen (ohne Endung); None, wenn er nicht zum Muster passt."""
    rx, names = compile_pattern(fmt)
    m = rx.match(stem)
    if m is None:
        return None
    result: dict[str, str] = {}
    for name, value in zip(names, m.groups()):
        if name != DUMMY:
            result[name] = value.strip()
    return result
