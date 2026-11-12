"""MusicBrainz-Schnittstelle (v1.2): Suche, Release-Daten, Cover und Zuordnung zu den Tag-Feldern.

Abfragen gehen an die öffentliche MusicBrainz-API (höchstens eine pro Sekunde, wie von MusicBrainz
verlangt) und an das Cover Art Archive. Die Feldnamen folgen den Konventionen von MusicBrainz Picard,
damit andere Programme (Picard, Navidrome, Jellyfin …) die Angaben wiedererkennen.
"""

from __future__ import annotations

import threading
import time
import urllib.parse
from dataclasses import dataclass, field

from . import netutil
from . import tags as tg

API = "https://musicbrainz.org/ws/2"
COVER_API = "https://coverartarchive.org/release/{id}/front-1200"
RELEASE_PAGE = "https://musicbrainz.org/release/{id}"
SEARCH_LIMIT = 50
MIN_INTERVAL = 1.1  # Sekunden zwischen zwei Abfragen

_lock = threading.Lock()
_last_request = [0.0]


def _throttle() -> None:
    with _lock:
        wait = _last_request[0] + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request[0] = time.monotonic()


def _get_json(url: str):
    _throttle()
    return netutil.get_json(url)


# --- Felder -------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class MBField:
    id: str  # Anzeigename wie bei MP3TAG, z. B. "MUSICBRAINZ_ALBUMID"
    level: str  # "track" oder "album"
    std: str | None = None  # Standardfeld von PanePilot (title, artist …)
    id3: str | None = None
    vorbis: str | None = None
    mp4: str | None = None
    asf: str | None = None

    def key(self, kind: str) -> str:
        """Schlüssel, unter dem das Feld in einer Datei des Formats kind gespeichert wird."""
        if self.std:
            return self.std
        name = {"id3": self.id3, "vorbis": self.vorbis, "mp4": self.mp4, "asf": self.asf}.get(kind) or self.id
        return tg.EXTRA + name


def _ff(name: str) -> str:
    return "----:com.apple.iTunes:" + name


def _mbf(fid, level, desc, vorbis, mp4=None, asf=None, id3=None):
    return MBField(fid, level, id3=id3 or f"TXXX:{desc}", vorbis=vorbis, mp4=mp4 or _ff(desc),
                   asf=asf or f"MusicBrainz/{desc.replace('MusicBrainz ', '')}")


FIELDS: tuple[MBField, ...] = (
    MBField("TRACK", "track", std="track"),
    MBField("DISCNUMBER", "track", std="disc"),
    MBField("TITLE", "track", std="title"),
    MBField("ARTIST", "track", std="artist"),
    MBField("ARTISTSORT", "track", id3="TSOP", vorbis="ARTISTSORT", mp4="soar", asf="WM/ArtistSortOrder"),
    MBField("ISRC", "track", std="isrc"),
    _mbf("MUSICBRAINZ_TRACKID", "track", "MusicBrainz Track Id", "MUSICBRAINZ_TRACKID",
         id3="UFID:http://musicbrainz.org"),
    _mbf("MUSICBRAINZ_ARTISTID", "track", "MusicBrainz Artist Id", "MUSICBRAINZ_ARTISTID"),
    MBField("ALBUM", "album", std="album"),
    MBField("ALBUMARTIST", "album", std="albumartist"),
    MBField("ALBUMARTISTSORT", "album", id3="TSO2", vorbis="ALBUMARTISTSORT", mp4="soaa",
            asf="WM/AlbumArtistSortOrder"),
    MBField("YEAR", "album", std="year"),
    MBField("ORIGYEAR", "album", id3="TXXX:originalyear", vorbis="ORIGINALYEAR", mp4=_ff("ORIGINALYEAR"),
            asf="WM/OriginalReleaseYear"),
    MBField("GENRE", "album", std="genre"),
    MBField("PUBLISHER", "album", std="publisher"),
    MBField("CATALOGNUMBER", "album", id3="TXXX:CATALOGNUMBER", vorbis="CATALOGNUMBER", mp4=_ff("CATALOGNUMBER"),
            asf="WM/CatalogNo"),
    MBField("BARCODE", "album", id3="TXXX:BARCODE", vorbis="BARCODE", mp4=_ff("BARCODE"), asf="WM/Barcode"),
    MBField("ASIN", "album", id3="TXXX:ASIN", vorbis="ASIN", mp4=_ff("ASIN"), asf="ASIN"),
    _mbf("MUSICBRAINZ_ALBUMID", "album", "MusicBrainz Album Id", "MUSICBRAINZ_ALBUMID"),
    _mbf("MUSICBRAINZ_ALBUMARTISTID", "album", "MusicBrainz Album Artist Id", "MUSICBRAINZ_ALBUMARTISTID"),
    _mbf("MUSICBRAINZ_RELEASEGROUPID", "album", "MusicBrainz Release Group Id", "MUSICBRAINZ_RELEASEGROUPID"),
    _mbf("MUSICBRAINZ_ALBUMTYPE", "album", "MusicBrainz Album Type", "RELEASETYPE"),
    _mbf("MUSICBRAINZ_ALBUMRELEASECOUNTRY", "album", "MusicBrainz Album Release Country", "RELEASECOUNTRY"),
)
FIELD_BY_ID = {f.id: f for f in FIELDS}


# --- Daten --------------------------------------------------------------------------------------------
@dataclass
class SearchHit:
    id: str
    score: int
    type: str
    artist: str
    album: str
    tracks: int
    year: str
    country: str
    format: str
    label: str
    catno: str


@dataclass
class MBTrack:
    disc: int
    number: int
    title: str
    length: float | None  # Sekunden
    values: dict[str, str] = field(default_factory=dict)  # Feld-ID → Wert (nur Titel-Felder)


@dataclass
class Release:
    id: str
    title: str
    artist: str
    album_values: dict[str, str]
    tracks: list[MBTrack]
    has_cover: bool = False


def _credit(credits) -> str:
    return "".join(f"{c.get('name') or (c.get('artist') or {}).get('name', '')}{c.get('joinphrase', '')}"
                   for c in credits or [])


def _credit_sort(credits) -> str:
    return "".join(f"{(c.get('artist') or {}).get('sort-name') or c.get('name', '')}{c.get('joinphrase', '')}"
                   for c in credits or [])


def _credit_ids(credits) -> str:
    return "; ".join((c.get("artist") or {}).get("id", "") for c in credits or [] if (c.get("artist") or {}).get("id"))


def _join_unique(values) -> str:
    out = []
    for v in values:
        if v and v not in out:
            out.append(v)
    return ", ".join(out)


def _escape(text: str) -> str:
    """Sonderzeichen für die Lucene-Suche von MusicBrainz maskieren."""
    special = '+-&|!(){}[]^"~*?:\\/'
    return "".join("\\" + c if c in special else c for c in text.strip())


def search_url(album: str, artist: str, limit: int = SEARCH_LIMIT) -> str:
    parts = []
    if album.strip():
        parts.append(f'release:"{_escape(album)}"')
    if artist.strip():
        parts.append(f'artist:"{_escape(artist)}"')
    query = " AND ".join(parts)
    return f"{API}/release/?" + urllib.parse.urlencode({"query": query, "fmt": "json", "limit": limit})


def parse_search(data: dict) -> list[SearchHit]:
    hits = []
    for r in data.get("releases") or []:
        media = r.get("media") or []
        labels = r.get("label-info") or []
        hits.append(SearchHit(
            id=r.get("id", ""), score=int(r.get("score") or 0),
            type=((r.get("release-group") or {}).get("primary-type") or ""),
            artist=_credit(r.get("artist-credit")), album=r.get("title", ""),
            tracks=int(r.get("track-count") or sum(int(m.get("track-count") or 0) for m in media)),
            year=r.get("date", "") or "", country=r.get("country", "") or "",
            format=_join_unique(m.get("format", "") for m in media),
            label=_join_unique(((li.get("label") or {}).get("name", "")) for li in labels),
            catno=_join_unique(li.get("catalog-number", "") for li in labels)))
    return hits


def search(album: str, artist: str) -> list[SearchHit]:
    return parse_search(_get_json(search_url(album, artist)))


def release_url(release_id: str) -> str:
    inc = "recordings+artist-credits+labels+release-groups+isrcs+genres"
    return f"{API}/release/{urllib.parse.quote(release_id)}?inc={inc}&fmt=json"


def _top_genre(*lists) -> str:
    for genres in lists:
        if genres:
            best = max(genres, key=lambda g: int(g.get("count") or 0))
            name = best.get("name", "")
            return name[:1].upper() + name[1:] if name else ""
    return ""


def parse_release(data: dict) -> Release:
    group = data.get("release-group") or {}
    labels = data.get("label-info") or []
    first = (group.get("first-release-date") or data.get("date") or "")[:4]
    album = {
        "ALBUM": data.get("title", ""),
        "ALBUMARTIST": _credit(data.get("artist-credit")),
        "ALBUMARTISTSORT": _credit_sort(data.get("artist-credit")),
        "YEAR": first,
        "ORIGYEAR": first,
        "GENRE": _top_genre(data.get("genres"), group.get("genres")),
        "PUBLISHER": _join_unique(((li.get("label") or {}).get("name", "")) for li in labels),
        "CATALOGNUMBER": _join_unique(li.get("catalog-number", "") for li in labels),
        "BARCODE": data.get("barcode") or "",
        "ASIN": data.get("asin") or "",
        "MUSICBRAINZ_ALBUMID": data.get("id", ""),
        "MUSICBRAINZ_ALBUMARTISTID": _credit_ids(data.get("artist-credit")),
        "MUSICBRAINZ_RELEASEGROUPID": group.get("id", ""),
        "MUSICBRAINZ_ALBUMTYPE": (group.get("primary-type") or "").lower(),
        "MUSICBRAINZ_ALBUMRELEASECOUNTRY": data.get("country") or "",
    }
    media = data.get("media") or []
    discs = len(media) or 1
    tracks = []
    for m_index, medium in enumerate(media, 1):
        disc = int(medium.get("position") or m_index)
        mtracks = medium.get("tracks") or []
        total = int(medium.get("track-count") or len(mtracks))
        for t_index, tr in enumerate(mtracks, 1):
            rec = tr.get("recording") or {}
            credits = tr.get("artist-credit") or rec.get("artist-credit") or data.get("artist-credit")
            length = tr.get("length") or rec.get("length")
            number = int(tr.get("position") or t_index)
            values = {
                "TRACK": f"{number}/{total}",
                "DISCNUMBER": f"{disc}/{discs}",
                "TITLE": tr.get("title") or rec.get("title", ""),
                "ARTIST": _credit(credits),
                "ARTISTSORT": _credit_sort(credits),
                "ISRC": _join_unique(rec.get("isrcs") or []),
                "MUSICBRAINZ_TRACKID": rec.get("id", ""),
                "MUSICBRAINZ_ARTISTID": _credit_ids(credits),
            }
            tracks.append(MBTrack(disc, number, values["TITLE"], length / 1000 if length else None, values))
    cover = bool((data.get("cover-art-archive") or {}).get("front"))
    return Release(data.get("id", ""), data.get("title", ""), album["ALBUMARTIST"], album, tracks, cover)


def get_release(release_id: str) -> Release:
    return parse_release(_get_json(release_url(release_id)))


def get_cover(release_id: str) -> bytes | None:
    """Front-Cover aus dem Cover Art Archive (höchstens 1200 px); None, wenn es keins gibt."""
    return netutil.get_bytes(COVER_API.format(id=urllib.parse.quote(release_id)), allow_404=True)


def load_release(release_id: str) -> tuple[Release, bytes | None]:
    rel = get_release(release_id)
    cover = None
    if rel.has_cover:
        try:
            cover = get_cover(release_id)
        except netutil.NetError:
            cover = None
    return rel, cover


# --- Zuordnung ----------------------------------------------------------------------------------------
def _num(text: str) -> int | None:
    import re

    m = re.match(r"\s*(\d+)", text or "")
    return int(m.group(1)) if m else None


def initial_pairs(tracks: list[MBTrack], items) -> tuple[list, list]:
    """Startzuordnung: über Disc/Track der Dateien, sonst in Listenreihenfolge."""
    keyed = {}
    for it in items:
        n = _num(it.value("track"))
        d = _num(it.value("disc")) or 1
        if n is None or (d, n) in keyed:
            keyed = {}
            break
        keyed[(d, n)] = it
    wanted = {(tr.disc, tr.number) for tr in tracks}
    if keyed and len(wanted & keyed.keys()) * 2 >= len(keyed):
        left = list(tracks)
        right = [keyed.pop((tr.disc, tr.number), None) for tr in tracks]
        right += list(keyed.values())  # Dateien ohne passende Nummer ans Ende
        left += [None] * (len(right) - len(left))
        return left, right
    return list(tracks), list(items)


def search_terms(items) -> tuple[str, str]:
    """Album und Interpret für die Suche aus den Tags (häufigster Wert)."""
    from collections import Counter

    def common(key: str) -> str:
        values = Counter(v for v in (it.value(key).strip() for it in items) if v)
        return values.most_common(1)[0][0] if values else ""

    return common("album"), common("albumartist") or common("artist")
