import sys
sys.path.insert(0, "src")
from panepilot import moviedb as md
wd = md.Wikidata("de-DE")
for kw in ({"imdb": "tt0078748"}, {"tmdb": "949"}, {"imdb": "tt0113277"}):
    m = wd.load(**kw)
    print("LOAD", kw, m and (m.title, m.original_title, m.year, m.genres, m.directors, m.imdb, m.tmdb))
for title, year in (("Alien", "1979"), ("Heat", "1995"), ("Der Pate", ""), ("Ronin", "1998")):
    hits = wd.search(title, year)
    print("SEARCH", title, year, [(h.title, h.year, h.original_title, h.imdb, h.tmdb, h.qid) for h in hits][:6])
    print("  pick", md.pick(hits, year))
