"""Film-Daten aus dem Internet (v1.9, L-900 ff.): TMDb mit eigenem API-Schlüssel, ersatzweise Wikidata.

Abfragen gehen nur auf ausdrücklichen Wunsch hinaus („Online-Daten“ im Meta-Wizard). Übertragen werden
nur die Kennung (IMDb/TMDb) bzw. Titel und Jahr aus dem Dateinamen.

This product uses the TMDB API but is not endorsed or certified by TMDB.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import netutil

TMDB_API = "https://api.themoviedb.org/3"
TMDB_IMAGE = "https://image.tmdb.org/t/p/{size}{path}"
TMDB_PAGE = "https://www.themoviedb.org/movie/{id}"
WD_SPARQL = "https://query.wikidata.org/sparql"
WD_API = "https://www.wikidata.org/w/api.php"
POSTER_SIZE = "w500"  # L-931: etwa 500 Pixel breit
THUMB_SIZE = "w92"

SOURCE_TMDB, SOURCE_WIKIDATA = "tmdb", "wikidata"
SECRET_ID, SECRET_KIND = "tmdb", "apikey"

# Eigene Felder (L-931); vorhandene Felder mit anderer Schreibweise werden weiter benutzt (L-932)
F_IMDB, F_TMDB, F_ORIG = "imdbid", "themoviedb", "originaltitle"
F_SERIES, F_SEASON, F_EPISODE = "Series", "Season", "Episode"  # v1.11 (L-1113)


class FatalError(netutil.NetError):
    """Fehler, der für alle weiteren Filme gilt (falscher Schlüssel, keine Verbindung)."""


@dataclass
class Movie:
    source: str
    title: str = ""
    original_title: str = ""
    year: str = ""
    genres: list = field(default_factory=list)
    overview: str = ""
    directors: list = field(default_factory=list)
    imdb: str = ""
    tmdb: str = ""
    poster_url: str = ""
    poster: bytes | None = None
    # Serien (v1.11): bei Folgen gesetzt
    series: str = ""
    season: str = ""  # zweistellig, z. B. „01“
    episode: str = ""


@dataclass
class Hit:
    """Ein Suchtreffer für die Auswahlliste (L-911)."""
    title: str
    year: str = ""
    original_title: str = ""
    imdb: str = ""
    tmdb: str = ""
    qid: str = ""
    thumb_url: str = ""
    thumb: bytes | None = None

    def key(self) -> str:
        return self.tmdb or self.imdb or self.qid


# --- Sprache (L-930) ---------------------------------------------------------------------------------------
_LANGS = {"de": "de-DE", "frk": "de-DE", "sxu": "de-DE", "en": "en-US", "es": "es-ES", "fr": "fr-FR", "ru": "ru-RU"}


def language(code: str | None = None) -> str:
    """Sprache der Online-Daten = Programmsprache (Fränkisch und Sächsisch → Deutsch)."""
    if code is None:
        from .i18n import current_language

        code = current_language()
    if code in _LANGS:
        return _LANGS[code]
    base = (code or "en").split("_")[0].split("-")[0]
    return _LANGS.get(base, f"{base}-{base.upper()}" if len(base) == 2 else "en-US")


# --- Kennung und Titel aus Feldern bzw. Dateinamen (L-910) --------------------------------------------------
_IMDB_RX = re.compile(r"^tt\d{5,10}$")
_NAME_ID_RX = re.compile(r"[\[{]\s*(imdbid|imdb|tmdbid|tmdb)\s*[-=]\s*([A-Za-z0-9]+)\s*[\]}]", re.IGNORECASE)
_YEAR_RX = re.compile(r"[\(\[]\s*((?:19|20)\d\d)\s*[\)\]]")


def clean_imdb(value: str) -> str:
    value = (value or "").strip()
    m = re.search(r"tt\d{5,10}", value)
    return m.group(0) if m else ""


def clean_tmdb(value: str) -> str:
    value = (value or "").strip()
    m = re.search(r"(?:movie/)?(\d{1,9})", value)
    return m.group(1) if m and value and not value.startswith("tt") else ""


def ids_from_name(name: str) -> tuple[str, str]:
    imdb = tmdb = ""
    for kind, value in _NAME_ID_RX.findall(name or ""):
        if kind.lower().startswith("imdb") and not imdb:
            imdb = clean_imdb(value)
        elif kind.lower().startswith("tmdb") and not tmdb:
            tmdb = clean_tmdb(value)
    return imdb, tmdb


def title_year(name: str) -> tuple[str, str]:
    """„Alien (1979) [imdbid-tt0078748].mkv“ → („Alien“, „1979“)."""
    import os

    stem = os.path.splitext(name or "")[0]
    m = _YEAR_RX.search(stem)
    year = m.group(1) if m else ""
    title = stem[:m.start()] if m else stem
    title = _NAME_ID_RX.sub(" ", title)
    title = re.sub(r"[\[{].*?[\]}]", " ", title)
    title = re.sub(r"[._]+", " ", title)
    title = re.sub(r"\s+-\s*$", "", title)
    return re.sub(r"\s+", " ", title).strip(" -"), year


# --- Serien: Folge am Dateinamen erkennen (v1.11, L-1110) -------------------------------------
_EP_RX = re.compile(r"(?<![A-Za-z0-9])[Ss](\d{1,2})[ ._-]?[Ee](\d{1,3})(?![0-9])")
_EP_X_RX = re.compile(r"(?<![A-Za-z0-9])(\d{1,2})x(\d{2,3})(?![0-9])")
_SEASON_DIR_RX = re.compile(r"^(?:staffel|season|series|serie|s)[ ._-]*\d{1,2}$", re.IGNORECASE)


@dataclass
class EpisodeRef:
    series: str
    year: str
    season: int
    episode: int
    tmdb: str = ""


def episode_ref(path: str) -> EpisodeRef | None:
    """„Breaking Bad/Staffel 1/Breaking Bad - S01E02.mkv“ → Serie, Staffel 1, Folge 2."""
    import os

    folder, name = os.path.split(path)
    stem = os.path.splitext(name)[0]
    m = _EP_RX.search(stem) or _EP_X_RX.search(stem)
    if not m:
        return None
    season, episode = int(m.group(1)), int(m.group(2))
    parent = os.path.basename(folder)
    grand = os.path.basename(os.path.dirname(folder))
    series_dir = grand if _SEASON_DIR_RX.match(parent.strip()) else ""
    tmdb = ""
    for d in (parent, grand):
        _imdb, t_id = ids_from_name(d)
        tmdb = tmdb or t_id
    prefix = stem[:m.start()]
    if series_dir:
        title, year = title_year(series_dir)
    elif prefix.strip(" .-_"):
        title, year = title_year(prefix)
        if not year:  # Jahr ggf. aus dem Serienordner
            p_title, p_year = title_year(parent)
            if p_title.casefold() == title.casefold():
                year = p_year
    else:
        title, year = title_year(parent)
    return EpisodeRef(title, year, season, episode, tmdb)


# --- HTTP --------------------------------------------------------------------------------------------------
_lock = threading.Lock()
_last = {"tmdb": 0.0, "wikidata": 0.0}
_INTERVAL = {"tmdb": 0.06, "wikidata": 1.0}  # L-950: TMDb höchstens ~20/s, Wikidata gemächlich


def _throttle(service: str) -> None:
    with _lock:
        wait = _last[service] + _INTERVAL[service] - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[service] = time.monotonic()


def http_get(url: str, headers: dict | None = None, service: str = "tmdb") -> bytes:
    """Eine GET-Anfrage; in Tests wird diese Funktion ersetzt."""
    _throttle(service)
    req = urllib.request.Request(url, headers={"User-Agent": netutil.USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=netutil.TIMEOUT, context=netutil.ssl_context()) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise FatalError("401") from exc
        if exc.code == 404:
            raise netutil.NetError("404") from exc
        raise netutil.NetError(f"HTTP {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise FatalError(str(getattr(exc, "reason", exc))) from exc


def _json(data: bytes):
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise netutil.NetError(f"JSON: {exc}") from exc


# --- TMDb ------------------------------------------------------------------------------------------------------
class Tmdb:
    source = SOURCE_TMDB

    def __init__(self, key: str, lang: str | None = None) -> None:
        self.key = key.strip()
        self.lang = lang or language()

    def _get(self, path: str, **params):
        headers = {"Accept": "application/json"}
        if len(self.key) > 40:  # „API-Lesezugriffstoken“ (v4) statt API-Schlüssel (v3)
            headers["Authorization"] = f"Bearer {self.key}"
        else:
            params["api_key"] = self.key
        url = f"{TMDB_API}{path}?{urllib.parse.urlencode(params)}"
        return _json(http_get(url, headers, "tmdb"))

    def check(self) -> None:
        """Schlüssel prüfen (L-922, „Prüfen“); wirft FatalError bei falschem Schlüssel."""
        self._get("/configuration")

    def find_imdb(self, imdb: str) -> str:
        data = self._get(f"/find/{imdb}", external_source="imdb_id")
        results = data.get("movie_results") or []
        return str(results[0]["id"]) if results else ""

    def movie(self, tmdb: str, with_poster: bool = True) -> Movie:
        data = self._get(f"/movie/{tmdb}", language=self.lang, append_to_response="credits,external_ids")
        m = Movie(SOURCE_TMDB, tmdb=str(data.get("id") or tmdb))
        m.title = (data.get("title") or "").strip()
        m.original_title = (data.get("original_title") or "").strip()
        m.year = (data.get("release_date") or "")[:4]
        m.genres = [g.get("name", "") for g in data.get("genres") or [] if g.get("name")]
        m.overview = (data.get("overview") or "").strip()
        crew = (data.get("credits") or {}).get("crew") or []
        m.directors = list(dict.fromkeys(c.get("name", "") for c in crew if c.get("job") == "Director" and c.get("name")))
        m.imdb = data.get("imdb_id") or (data.get("external_ids") or {}).get("imdb_id") or ""
        if (not m.overview or not m.title) and not self.lang.startswith("en"):  # L-930: ersatzweise Englisch
            en = self._get(f"/movie/{tmdb}", language="en-US")
            m.overview = m.overview or (en.get("overview") or "").strip()
            m.title = m.title or (en.get("title") or "").strip()
            if not m.genres:
                m.genres = [g.get("name", "") for g in en.get("genres") or [] if g.get("name")]
        path = data.get("poster_path")
        if path:
            m.poster_url = TMDB_IMAGE.format(size=POSTER_SIZE, path=path)
            if with_poster:
                try:
                    m.poster = http_get(m.poster_url, None, "tmdb")
                except netutil.NetError:
                    m.poster = None
        return m

    def search(self, title: str, year: str = "") -> list[Hit]:
        params = {"query": title, "language": self.lang, "include_adult": "false"}
        if year:
            params["year"] = year
        data = self._get("/search/movie", **params)
        hits = []
        for r in (data.get("results") or [])[:20]:
            thumb = TMDB_IMAGE.format(size=THUMB_SIZE, path=r["poster_path"]) if r.get("poster_path") else ""
            hits.append(Hit(r.get("title") or r.get("original_title") or "", (r.get("release_date") or "")[:4],
                            r.get("original_title") or "", tmdb=str(r.get("id") or ""), thumb_url=thumb))
        if year and not hits:  # Jahr im Dateinamen weicht manchmal um eins ab
            return self.search(title, "")
        return hits

    # --- Serien (v1.11, L-1110 ff.) ------------------------------------------------------------
    def search_tv(self, title: str, year: str = "") -> list[Hit]:
        params = {"query": title, "language": self.lang, "include_adult": "false"}
        if year:
            params["first_air_date_year"] = year
        data = self._get("/search/tv", **params)
        hits = []
        for r in (data.get("results") or [])[:20]:
            thumb = TMDB_IMAGE.format(size=THUMB_SIZE, path=r["poster_path"]) if r.get("poster_path") else ""
            hits.append(Hit(r.get("name") or r.get("original_name") or "", (r.get("first_air_date") or "")[:4],
                            r.get("original_name") or "", tmdb=str(r.get("id") or ""), thumb_url=thumb))
        if year and not hits:
            return self.search_tv(title, "")
        return hits

    def _cached(self, key, fn):
        cache = self.__dict__.setdefault("_cache", {})
        if key not in cache:
            cache[key] = fn()
        return cache[key]

    def tv(self, tv_id: str) -> dict:
        return self._cached(("tv", tv_id), lambda: self._get(f"/tv/{tv_id}", language=self.lang))

    def season(self, tv_id: str, season: int, lang: str | None = None) -> dict:
        lang = lang or self.lang

        def load():
            try:
                return self._get(f"/tv/{tv_id}/season/{season}", language=lang)
            except netutil.NetError as exc:
                if str(exc) == "404":
                    return {}
                raise
        return self._cached(("season", tv_id, season, lang), load)

    def image(self, url: str) -> bytes | None:
        def load():
            try:
                return http_get(url, None, "tmdb")
            except netutil.NetError:
                return None
        return self._cached(("img", url), load)

    def episode(self, tv_id: str, season: int, episode: int) -> Movie | None:
        show = self.tv(tv_id)
        data = self.season(tv_id, season)
        eps = {e.get("episode_number"): e for e in data.get("episodes") or []}
        ep = eps.get(episode)
        if ep is None:
            return None
        m = Movie(SOURCE_TMDB, tmdb=str(show.get("id") or tv_id))
        m.series = (show.get("name") or show.get("original_name") or "").strip()
        m.season, m.episode = f"{season:02d}", f"{episode:02d}"
        m.title = (ep.get("name") or "").strip()
        m.overview = (ep.get("overview") or "").strip()
        m.year = (ep.get("air_date") or "")[:4]
        m.genres = [g.get("name", "") for g in show.get("genres") or [] if g.get("name")]
        if (not m.overview or not m.title or re.fullmatch(r"(Episode|Folge|Épisode|Episodio|Серия) \d+", m.title)) \
                and not self.lang.startswith("en"):  # L-930: ersatzweise Englisch
            en = {e.get("episode_number"): e for e in self.season(tv_id, season, "en-US").get("episodes") or []}
            other = en.get(episode) or {}
            m.overview = m.overview or (other.get("overview") or "").strip()
            if not m.title or re.fullmatch(r"(Episode|Folge|Épisode|Episodio|Серия) \d+", m.title):
                m.title = (other.get("name") or "").strip() or m.title
        path = data.get("poster_path") or show.get("poster_path")  # Staffelposter, sonst Serienposter
        if path:
            m.poster_url = TMDB_IMAGE.format(size=POSTER_SIZE, path=path)
            m.poster = self.image(m.poster_url)
        return m

    def load(self, imdb: str = "", tmdb: str = "", qid: str = "") -> Movie | None:
        if not tmdb and imdb:
            tmdb = self.find_imdb(imdb)
        if not tmdb:
            return None
        return self.movie(tmdb)


# --- Wikidata --------------------------------------------------------------------------------------------------
class Wikidata:
    source = SOURCE_WIKIDATA

    def __init__(self, lang: str | None = None) -> None:
        self.lang = (lang or language()).split("-")[0]

    def _labels(self) -> str:
        return ",".join(dict.fromkeys([self.lang, "mul", "en"]))

    def _sparql(self, query: str):
        url = f"{WD_SPARQL}?{urllib.parse.urlencode({'query': query, 'format': 'json'})}"
        data = _json(http_get(url, {"Accept": "application/sparql-results+json"}, "wikidata"))
        return data.get("results", {}).get("bindings", [])

    def _query(self, where: str) -> str:
        return f"""SELECT ?item ?itemLabel ?orig ?date ?genreLabel ?links ?dirLabel ?imdb ?tmdb WHERE {{
  {where}
  OPTIONAL {{ ?item wdt:P1476 ?orig . }}
  OPTIONAL {{ ?item wdt:P577 ?date . }}
  OPTIONAL {{ ?item wdt:P136 ?genre . ?genre wikibase:sitelinks ?links . }}
  OPTIONAL {{ ?item wdt:P57 ?dir . }}
  OPTIONAL {{ ?item wdt:P345 ?imdb . }}
  OPTIONAL {{ ?item wdt:P4947 ?tmdb . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{self._labels()}". }}
}}"""

    MAX_GENRES = 3

    @classmethod
    def _movies(cls, rows) -> dict[str, Movie]:
        out: dict[str, Movie] = {}
        weight: dict[tuple[str, str], int] = {}
        for r in rows:
            qid = r["item"]["value"].rsplit("/", 1)[-1]
            m = out.setdefault(qid, Movie(SOURCE_WIKIDATA))
            v = lambda k: (r.get(k) or {}).get("value", "")  # noqa: E731
            label = v("itemLabel")
            if label and not re.fullmatch(r"Q\d+", label):
                m.title = m.title or label
            m.original_title = m.original_title or v("orig")
            year = v("date")[:4]
            if year.isdigit() and (not m.year or year < m.year):
                m.year = year
            g = v("genreLabel")
            if g and not re.fullmatch(r"Q\d+", g) and g not in m.genres:
                m.genres.append(g)
                weight[(qid, g)] = int(v("links") or 0) if v("links").isdigit() else 0
            d = v("dirLabel")
            if d and not re.fullmatch(r"Q\d+", d) and d not in m.directors:
                m.directors.append(d)
            m.imdb = m.imdb or clean_imdb(v("imdb"))
            m.tmdb = m.tmdb or clean_tmdb(v("tmdb"))
            m.poster_url = qid  # Wikidata-Kennung merken (kein Poster, L-921)
        for qid, m in out.items():  # Wikidata kennt sehr viele Genres; die allgemeinsten (meiste Sprachen) nehmen
            m.genres = sorted(m.genres, key=lambda g: -weight.get((qid, g), 0))[:cls.MAX_GENRES]
        return out

    def load(self, imdb: str = "", tmdb: str = "", qid: str = "") -> Movie | None:
        if qid:
            where = f"VALUES ?item {{ wd:{qid} }}"
        elif imdb:
            where = f'?item wdt:P345 "{imdb}" .'
        elif tmdb:
            where = f'?item wdt:P4947 "{tmdb}" .'
        else:
            return None
        movies = self._movies(self._sparql(self._query(where)))
        if not movies:
            return None
        m = next(iter(movies.values()))
        m.poster_url = ""
        return m

    def search(self, title: str, year: str = "") -> list[Hit]:
        # Volltextsuche nur unter Filmen (Q11424); findet auch deutsche und Originaltitel
        params = {"action": "query", "list": "search", "srsearch": f"{title} haswbstatement:P31=Q11424",
                  "srnamespace": "0", "srlimit": "20", "format": "json"}
        data = _json(http_get(f"{WD_API}?{urllib.parse.urlencode(params)}", None, "wikidata"))
        qids = [e["title"] for e in (data.get("query") or {}).get("search") or []
                if re.fullmatch(r"Q\d+", e.get("title", ""))]
        if not qids:
            return []
        values = " ".join(f"wd:{q}" for q in qids)
        where = f"VALUES ?item {{ {values} }}"
        movies = self._movies(self._sparql(self._query(where)))
        hits = [Hit(m.title, m.year, m.original_title if m.original_title != m.title else "", m.imdb, m.tmdb, q)
                for q, m in sorted(movies.items(), key=lambda kv: qids.index(kv[0]) if kv[0] in qids else 99)]
        if year:
            near = [h for h in hits if h.year and abs(int(h.year) - int(year)) <= 1]
            return near or hits
        return hits


# --- Auswahl der Quelle (L-920, L-921) --------------------------------------------------------------------
def service(key: str | None, lang: str | None = None):
    return Tmdb(key, lang) if key else Wikidata(lang)


def pick(hits: list[Hit], year: str) -> Hit | None:
    """L-912: genau ein Treffer mit passendem Jahr wird ohne Rückfrage genommen."""
    if year:
        same = [h for h in hits if h.year == year]
        return same[0] if len(same) == 1 else None
    return hits[0] if len(hits) == 1 else None


# --- API-Schlüssel (L-923): nur im Schlüsselbund, sonst nur für diese Sitzung --------------------------------
_session_key: dict = {}


def load_key() -> str:
    if "key" in _session_key:
        return _session_key["key"]
    from . import servers as sv

    key = sv.load_secret(SECRET_ID, SECRET_KIND) or ""
    _session_key["key"] = key
    return key


def store_key(key: str) -> bool:
    """Speichert den Schlüssel im Schlüsselbund; False, wenn er nur für diese Sitzung gilt."""
    from . import servers as sv

    key = key.strip()
    _session_key["key"] = key
    if not key:
        _delete_key()
        return True
    return sv.store_secret(SECRET_ID, key, "TMDb API key", SECRET_KIND)


def _delete_key() -> None:
    from . import servers as sv

    if not sv.keyring_available():
        return

    def remove(col):
        for item in list(col.search_items(sv._attrs(SECRET_ID, SECRET_KIND))):
            item.delete()
    try:
        sv._with_collection(remove)
    except Exception:  # noqa: BLE001
        pass
