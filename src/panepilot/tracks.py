"""Audiospuren und Untertitel eines Videos (v1.7, L-700 ff.): Sprache, Format, Kennzeichen – nur zur Anzeige."""

from __future__ import annotations

from dataclasses import dataclass

from .i18n import t

_SUB_CODECS = {"subrip": "SRT", "srt": "SRT", "ass": "ASS", "ssa": "SSA", "hdmv_pgs_subtitle": "PGS",
               "dvd_subtitle": "VobSub", "dvb_subtitle": "DVB", "mov_text": "Text (MP4)", "webvtt": "WebVTT",
               "eia_608": "CEA-608", "text": "Text"}

# Ausgeschriebene Sprachen auf Deutsch (für die deutschen Oberflächen); sonst liefert Qt den englischen Namen
_GERMAN = {
    "deu": "Deutsch", "ger": "Deutsch", "gsw": "Schweizerdeutsch", "eng": "Englisch", "fra": "Französisch",
    "fre": "Französisch", "spa": "Spanisch", "ita": "Italienisch", "por": "Portugiesisch", "nld": "Niederländisch",
    "dut": "Niederländisch", "dan": "Dänisch", "swe": "Schwedisch", "nor": "Norwegisch", "nob": "Norwegisch",
    "nno": "Norwegisch", "fin": "Finnisch", "isl": "Isländisch", "ice": "Isländisch", "pol": "Polnisch",
    "ces": "Tschechisch", "cze": "Tschechisch", "slk": "Slowakisch", "slo": "Slowakisch", "hun": "Ungarisch",
    "ron": "Rumänisch", "rum": "Rumänisch", "bul": "Bulgarisch", "hrv": "Kroatisch", "srp": "Serbisch",
    "slv": "Slowenisch", "ell": "Griechisch", "gre": "Griechisch", "tur": "Türkisch", "rus": "Russisch",
    "ukr": "Ukrainisch", "est": "Estnisch", "lav": "Lettisch", "lit": "Litauisch", "heb": "Hebräisch",
    "ara": "Arabisch", "fas": "Persisch", "per": "Persisch", "hin": "Hindi", "tha": "Thailändisch",
    "vie": "Vietnamesisch", "ind": "Indonesisch", "msa": "Malaiisch", "may": "Malaiisch", "fil": "Filipino",
    "tgl": "Tagalog", "ceb": "Cebuano", "zho": "Chinesisch", "chi": "Chinesisch", "jpn": "Japanisch",
    "kor": "Koreanisch", "lat": "Latein", "cat": "Katalanisch", "eus": "Baskisch", "baq": "Baskisch",
    "gle": "Irisch", "cym": "Walisisch", "wel": "Walisisch",
}
_UNKNOWN = {"", "und", "unk", "unknown", "mis", "zxx"}


@dataclass
class Track:
    kind: str  # "audio" oder "subtitle"
    lang: str = ""
    codec: str = ""
    channels: int = 0
    layout: str = ""
    default: bool = False
    forced: bool = False
    sdh: bool = False  # für Hörgeschädigte
    title: str = ""

    @property
    def code(self) -> str:
        return "?" if self.lang.lower() in _UNKNOWN else self.lang


def from_stream(stream: dict) -> Track | None:
    kind = stream.get("codec_type")
    if kind not in ("audio", "subtitle"):
        return None
    tags = {k.lower(): v for k, v in (stream.get("tags") or {}).items()}
    disp = stream.get("disposition") or {}
    name = stream.get("codec_name") or ""
    if kind == "subtitle":
        from .videotags import codec_name

        codec = _SUB_CODECS.get(name, codec_name(name))
    else:
        from .videotags import codec_name

        codec = codec_name(name)
    try:
        channels = int(stream.get("channels") or 0)
    except ValueError:
        channels = 0
    return Track(kind, (tags.get("language") or "").strip(), codec, channels, stream.get("channel_layout") or "",
                 bool(disp.get("default")), bool(disp.get("forced")), bool(disp.get("hearing_impaired")),
                 (tags.get("title") or "").strip())


def language_name(code: str) -> str:
    """Sprache ausgeschrieben in der Sprache der Oberfläche (Deutsch) bzw. auf Englisch."""
    c = (code or "").lower()
    if c in _UNKNOWN or c == "?":
        return t("track.unknown")
    from .i18n import current_language

    if current_language() in ("de", "frk", "sxu") and c in _GERMAN:
        return _GERMAN[c]
    from PySide6.QtCore import QLocale

    try:
        lang = QLocale.codeToLanguage(c, QLocale.LanguageCodeType.ISO639) if len(c) in (2, 3) else None
    except (TypeError, AttributeError):
        lang = None
    if lang is None or lang == QLocale.Language.AnyLanguage:
        return ""
    return QLocale.languageToString(lang)


def lang_list(tracks: list[Track]) -> str:
    """„deu, eng (forced)“ – für Spalte und Platzhalter (L-710, L-730)."""
    parts = []
    for tr in tracks:
        parts.append(tr.code + (" (forced)" if tr.forced else ""))
    return ", ".join(parts)


def _sound(tr: Track) -> str:
    layout = tr.layout.split("(")[0].strip().lower()
    if layout == "stereo" or (not layout and tr.channels == 2):
        return t("track.stereo")
    if layout == "mono" or (not layout and tr.channels == 1):
        return t("track.mono")
    if layout:
        return layout
    return t("track.channels", n=tr.channels) if tr.channels else ""


def track_line(tr: Track) -> str:
    """„deu (Deutsch) – AC-3 5.1 – Standard“ (L-713)."""
    name = language_name(tr.lang)
    head = f"{tr.code} ({name})" if name and tr.code != "?" else (tr.code if tr.code != "?" else t("track.unknown"))
    fmt = tr.codec
    if tr.kind == "audio":
        sound = _sound(tr)
        fmt = f"{tr.codec} {sound}".strip()
    parts = [head]
    if fmt:
        parts.append(fmt)
    flags = [t(k) for on, k in ((tr.default, "track.default"), (tr.forced, "track.forced"),
                                (tr.sdh, "track.sdh")) if on]
    if flags:
        parts.append(", ".join(flags))
    if tr.title:
        parts.append(f"„{tr.title}“")
    return " – ".join(parts)


def tooltip(tracks: list[Track]) -> str:
    return "\n".join(track_line(tr) for tr in tracks)
