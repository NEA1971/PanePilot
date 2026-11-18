"""Untertitel von OpenSubtitles.com herunterladen (v1.14, L-1400 ff.).

REST-API v1: Suche ist frei, Herunterladen zählt gegen das Tageskontingent (ohne Anmeldung 5,
mit kostenlosem Konto mehr). Der API-Schlüssel und das Passwort liegen nur im Schlüsselbund.
"""

from __future__ import annotations

import json
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import __version__, netutil

API = "https://api.opensubtitles.com/api/v1"
USER_AGENT = f"PanePilot v{__version__}"
SECRET_ID = "opensubtitles"
KEY_KIND, PASSWORD_KIND = "apikey", "password"
DEFAULT_LANGUAGES = "de,en"

# ISO 639-1 (OpenSubtitles) → ISO 639-2/B (MKV, Dateinamen im Jellyfin-Stil)
_TO_MKV = {"de": "ger", "en": "eng", "fr": "fre", "es": "spa", "it": "ita", "nl": "dut", "pt": "por",
           "pt-pt": "por", "pt-br": "por", "pl": "pol", "ru": "rus", "tr": "tur", "da": "dan", "sv": "swe",
           "no": "nor", "nb": "nor", "fi": "fin", "cs": "cze", "hu": "hun", "el": "gre", "ja": "jpn",
           "zh": "chi", "zh-cn": "chi", "zh-tw": "chi", "ko": "kor", "ar": "ara", "he": "heb", "uk": "ukr",
           "ro": "rum", "bg": "bul", "hr": "hrv", "sr": "srp", "sk": "slo", "sl": "slv", "et": "est",
           "lv": "lav", "lt": "lit", "is": "ice", "fa": "per", "hi": "hin", "th": "tha", "vi": "vie",
           "id": "ind", "ms": "may", "ca": "cat", "eu": "baq", "gl": "glg", "tl": "tgl"}
_FROM_MKV = {v: k for k, v in _TO_MKV.items() if "-" not in k and k != "nb"}
_FROM_MKV.update({"deu": "de", "fra": "fr", "nld": "nl", "ces": "cs", "ell": "el", "zho": "zh", "ron": "ro",
                  "slk": "sk", "isl": "is", "fas": "fa", "msa": "ms", "eus": "eu"})


class FatalError(netutil.NetError):
    """Falscher Schlüssel, falsche Anmeldung, keine Verbindung – gilt für alle weiteren Anfragen."""


class QuotaError(netutil.NetError):
    """Tageskontingent für Downloads erschöpft."""

    def __init__(self, message: str, reset: str = "") -> None:
        super().__init__(message)
        self.reset = reset


def to_mkv_lang(code: str) -> str:
    c = (code or "").strip().lower()
    if len(c) == 3:
        return c
    return _TO_MKV.get(c, _TO_MKV.get(c.split("-")[0], c or "und"))


def from_mkv_lang(code: str) -> str:
    c = (code or "").strip().lower()
    if len(c) == 2:
        return c
    return _FROM_MKV.get(c, c)


def parse_languages(text: str) -> list[str]:
    """„de, en“ oder „ger eng“ → [de, en] (OpenSubtitles-Codes, ohne Doppelte)."""
    out: list[str] = []
    for part in re.split(r"[\s,;]+", text or ""):
        code = from_mkv_lang(part)
        if code and code not in out:
            out.append(code)
    return out


# --- Datei-Fingerabdruck -----------------------------------------------------------------------------------
_CHUNK = 65536


def moviehash(path: str) -> str:
    """OpenSubtitles-Hash: Dateigröße plus die 64-Bit-Wörter der ersten und letzten 64 KB."""
    try:
        size = os.path.getsize(path)
        if size < 2 * _CHUNK:
            return ""
        value = size
        with open(path, "rb") as fh:
            for pos in (0, size - _CHUNK):
                fh.seek(pos)
                data = fh.read(_CHUNK)
                for (word,) in struct.iter_unpack("<Q", data):
                    value = (value + word) & 0xFFFFFFFFFFFFFFFF
        return f"{value:016x}"
    except OSError:
        return ""


# --- Treffer ----------------------------------------------------------------------------------------------
@dataclass
class Hit:
    file_id: int
    lang: str  # OpenSubtitles-Code (de, en, pt-BR …)
    release: str = ""
    file_name: str = ""
    downloads: int = 0
    rating: float = 0.0
    hash_match: bool = False  # „passt genau“
    forced: bool = False  # nur fremdsprachige Stellen
    sdh: bool = False  # für Hörgeschädigte
    title: str = ""
    year: str = ""
    extra: dict = field(default_factory=dict)

    def sort_key(self):
        """Fingerabdruck zuerst, dann vollständige vor erzwungenen/SDH, dann meiste Downloads (L-1404)."""
        return (not self.hash_match, self.forced, self.sdh, -self.downloads, -self.rating)


def parse_hits(data) -> list[Hit]:
    out = []
    for row in (data or {}).get("data") or []:
        attr = row.get("attributes") or {}
        files = attr.get("files") or []
        if not files:
            continue
        feat = attr.get("feature_details") or {}
        try:
            rating = float(attr.get("ratings") or 0)
        except (TypeError, ValueError):
            rating = 0.0
        out.append(Hit(int(files[0].get("file_id") or 0), str(attr.get("language") or ""),
                       str(attr.get("release") or ""), str(files[0].get("file_name") or ""),
                       int(attr.get("download_count") or 0), rating, bool(attr.get("moviehash_match")),
                       bool(attr.get("foreign_parts_only")), bool(attr.get("hearing_impaired")),
                       str(feat.get("title") or feat.get("movie_name") or ""), str(feat.get("year") or "")))
    return [h for h in out if h.file_id]


def best_per_language(hits: list[Hit], languages: list[str]) -> list[Hit]:
    """Je gewünschter Sprache der beste Treffer."""
    out = []
    for lang in languages:
        same = sorted((h for h in hits if h.lang.lower() == lang.lower() or
                       h.lang.lower().split("-")[0] == lang.lower()), key=Hit.sort_key)
        if same:
            out.append(same[0])
    return out


def target_name(video: str, hit: Hit, taken: set[str] | None = None) -> str:
    """„Film.ger.srt“, „Film.ger.forced.srt“, „Film.ger.sdh.srt“; bei gleichem Namen „.2“ (L-1405)."""
    stem = os.path.splitext(video)[0]
    ext = os.path.splitext(hit.file_name)[1].lower()
    if ext not in (".srt", ".ass", ".ssa", ".vtt", ".sub"):
        ext = ".srt"
    base = f"{stem}.{to_mkv_lang(hit.lang)}" + (".forced" if hit.forced else "") + (".sdh" if hit.sdh else "")
    taken = taken if taken is not None else set()
    name, n = base + ext, 1
    while name in taken or os.path.exists(name):
        n += 1
        name = f"{base}.{n}{ext}"
    taken.add(name)
    return name


# --- Zugriff ----------------------------------------------------------------------------------------------
_lock = threading.Lock()
_last = [0.0]
_INTERVAL = 0.25  # höchstens 5 Anfragen je Sekunde erlaubt


def _throttle() -> None:
    with _lock:
        wait = _last[0] + _INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.monotonic()


def http(method: str, url: str, headers: dict, body: bytes | None = None) -> tuple[int, bytes]:
    """Eine Anfrage; liefert (Status, Inhalt). In Tests wird diese Funktion ersetzt."""
    _throttle()
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=netutil.TIMEOUT, context=netutil.ssl_context()) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        try:
            data = exc.read()
        except OSError:
            data = b""
        return exc.code, data
    except (urllib.error.URLError, OSError) as exc:
        raise FatalError(str(getattr(exc, "reason", exc))) from exc


def _json(data: bytes):
    try:
        return json.loads((data or b"{}").decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise netutil.NetError(f"JSON: {exc}") from exc


def _message(data: bytes) -> str:
    try:
        d = json.loads(data.decode("utf-8"))
        return str(d.get("message") or d.get("errors") or "")
    except (ValueError, UnicodeDecodeError, AttributeError):
        return ""


class Client:
    def __init__(self, key: str, user: str = "", password: str = "") -> None:
        self.key = (key or "").strip()
        self.user = (user or "").strip()
        self.password = password or ""
        self.token = ""
        self.base = API
        self.remaining: int | None = None
        self.allowed: int | None = None

    def _headers(self, json_body: bool = False) -> dict:
        h = {"Api-Key": self.key, "User-Agent": USER_AGENT, "Accept": "application/json"}
        if json_body:
            h["Content-Type"] = "application/json"
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _call(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        url = self.base + path
        if params:
            # Werte klein und alphabetisch sortiert – so verlangt es die API (sonst Umleitung)
            items = sorted((k, str(v).lower()) for k, v in params.items() if v not in (None, ""))
            url += "?" + urllib.parse.urlencode(items)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        status, raw = http(method, url, self._headers(body is not None), data)
        if status in (401, 403):
            raise FatalError("401")
        if status == 406 or (status == 429 and path == "/download"):
            d = {}
            try:
                d = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                pass
            raise QuotaError(str(d.get("message") or "quota"), str(d.get("reset_time") or ""))
        if status == 429:
            time.sleep(1.0)
            status, raw = http(method, url, self._headers(body is not None), data)
        if status >= 400:
            raise netutil.NetError(f"HTTP {status} {_message(raw)}".strip())
        return _json(raw)

    def login(self) -> None:
        """Mit Benutzername und Passwort anmelden (mehr Downloads am Tag)."""
        if not self.user or not self.password or self.token:
            return
        d = self._call("POST", "/login", body={"username": self.user, "password": self.password})
        self.token = str(d.get("token") or "")
        base = str(d.get("base_url") or "")
        if base:
            self.base = f"https://{base.split('://')[-1].rstrip('/')}/api/v1"
        user = d.get("user") or {}
        self._quota(user)

    def _quota(self, user: dict) -> None:
        for attr, key in (("allowed", "allowed_downloads"), ("remaining", "remaining_downloads")):
            try:
                if user.get(key) is not None:
                    setattr(self, attr, int(user[key]))
            except (TypeError, ValueError):
                pass

    def check(self) -> int | None:
        """„Prüfen“: Schlüssel (und ggf. Anmeldung) testen; liefert die verbleibenden Downloads."""
        if self.user and self.password:
            self.login()
            d = self._call("GET", "/infos/user")
            self._quota(d.get("data") or {})
            return self.remaining
        self._call("GET", "/infos/formats")
        return None

    def search(self, languages: list[str], moviehash: str = "", imdb: str = "", tmdb: str = "",
               query: str = "", year: str = "", season: int | None = None, episode: int | None = None) -> list[Hit]:
        params = {"languages": ",".join(sorted(languages))}
        if moviehash:
            params["moviehash"] = moviehash
        imdb_num = re.sub(r"\D", "", imdb or "").lstrip("0")
        series = season is not None and episode is not None
        if series:
            params["season_number"], params["episode_number"] = season, episode
            if imdb_num:
                params["parent_imdb_id"] = imdb_num
            elif tmdb:
                params["parent_tmdb_id"] = tmdb
        else:
            if imdb_num:
                params["imdb_id"] = imdb_num
            elif tmdb:
                params["tmdb_id"] = tmdb
        if query and not imdb_num and not tmdb:
            params["query"] = query
            if year and not series:
                params["year"] = year
        return parse_hits(self._call("GET", "/subtitles", params))

    def download(self, hit: Hit) -> bytes:
        d = self._call("POST", "/download", body={"file_id": hit.file_id})
        try:
            if d.get("remaining") is not None:
                self.remaining = int(d["remaining"])
        except (TypeError, ValueError):
            pass
        link = str(d.get("link") or "")
        if not link:
            raise netutil.NetError(str(d.get("message") or "download"))
        status, raw = http("GET", link, {"User-Agent": USER_AGENT})
        if status >= 400:
            raise netutil.NetError(f"HTTP {status}")
        return raw


# --- Zugangsdaten (L-1400): Schlüssel und Passwort nur im Schlüsselbund -------------------------------------
_session: dict = {}


def load_secret(kind: str) -> str:
    if kind in _session:
        return _session[kind]
    from . import servers as sv

    value = sv.load_secret(SECRET_ID + "-" + kind, kind) or ""
    _session[kind] = value
    return value


def store_secret(kind: str, value: str) -> bool:
    """False, wenn kein Schlüsselbund da ist (dann gilt der Wert nur für diese Sitzung)."""
    from . import servers as sv

    value = value.strip() if kind == KEY_KIND else value
    _session[kind] = value
    sid = SECRET_ID + "-" + kind
    if not value:
        if sv.keyring_available():
            def remove(col):
                for item in list(col.search_items(sv._attrs(sid, kind))):
                    item.delete()
            try:
                sv._with_collection(remove)
            except Exception:  # noqa: BLE001
                pass
        return True
    label = "OpenSubtitles API key" if kind == KEY_KIND else "OpenSubtitles password"
    return sv.store_secret(sid, value, label, kind)


_clients: dict = {}


def client(settings) -> Client | None:
    """Ein Client je Zugangsdaten für die Sitzung (die Anmeldung gilt 24 Stunden)."""
    key = load_secret(KEY_KIND)
    if not key:
        return None
    user = (settings.get("opensubs_user") if settings is not None else "") or ""
    password = load_secret(PASSWORD_KIND) if user else ""
    ident = (key, user, password)
    c = _clients.get(ident)
    if c is None:
        _clients.clear()
        c = _clients[ident] = Client(key, user, password)
    return c


def languages(settings) -> list[str]:
    text = settings.get("opensubs_languages") if settings is not None else None
    return parse_languages(text or DEFAULT_LANGUAGES) or parse_languages(DEFAULT_LANGUAGES)
