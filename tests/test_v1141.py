"""Tests for 1.14.1: MKV tags with „TargetType MOVIE“ but without TargetTypeValue."""

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

VIDEO = os.path.join(os.path.dirname(__file__), "data", "video")
has_mkv = all(shutil.which(x) for x in ("mkvmerge", "mkvextract", "mkvpropedit", "ffprobe"))

TAGS = """<?xml version="1.0"?>
<Tags>
  <Tag><Targets><TargetType>MOVIE</TargetType></Targets>
    <Simple><Name>DATE_RELEASED</Name><String>2018</String></Simple>
    <Simple><Name>GENRE</Name><String>Horror</String></Simple>
    <Simple><Name>IMDBID</Name><String>tt5726086</String></Simple>
  </Tag>
</Tags>
"""


def test_plain_tags_and_global():
    from panepilot import videotags as vt

    tags = vt._mkv_plain_tags({"title": "X", "MOVIE/DATE_RELEASED": "2018", "MOVIE/IMDBID": "tt1",
                               "GENRE": "Krimi", "MOVIE/GENRE": "Horror", "COLLECTION/TITLE": "Reihe"})
    assert tags == {"title": "X", "DATE_RELEASED": "2018", "IMDBID": "tt1", "GENRE": "Krimi",
                    "MOVIE/GENRE": "Horror", "COLLECTION/TITLE": "Reihe"}

    def tag(xml):
        return ET.fromstring(f"<Tag><Targets>{xml}</Targets></Tag>")

    assert vt._is_global(tag("<TargetType>MOVIE</TargetType>"))
    assert vt._is_global(tag("")) and vt._is_global(tag("<TargetTypeValue>50</TargetTypeValue>"))
    assert not vt._is_global(tag("<TargetType>COLLECTION</TargetType>"))
    assert not vt._is_global(tag("<TargetTypeValue>70</TargetTypeValue>"))


@pytest.mark.skipif(not has_mkv, reason="mkvtoolnix fehlt")
def test_movie_target_read_and_write(tmp_path):
    from panepilot import tags as tg
    from panepilot import videotags as vt

    src = str(tmp_path / "Film.mkv")
    subprocess.run(["mkvmerge", "-q", "-o", src, os.path.join(VIDEO, "clip.mp4")], check=True)
    xml = tmp_path / "t.xml"
    xml.write_text(TAGS, encoding="utf-8")
    subprocess.run(["mkvpropedit", "-q", src, "--tags", f"all:{xml}"], check=True)
    rec = tg.read_file(src)
    assert rec.fields.get("year") == "2018" and rec.fields.get("genre") == "Horror"
    assert rec.fields.get(tg.EXTRA + "IMDBID") == "tt5726086"
    vt.write_file(rec, {"year": "2019", tg.EXTRA + "RATING": "6.3"})
    again = tg.read_file(src)
    assert again.fields.get("year") == "2019" and again.fields.get(tg.EXTRA + "RATING") == "6.3"
    assert again.fields.get(tg.EXTRA + "IMDBID") == "tt5726086"


EMPTY = """<?xml version="1.0"?>
<Tags>
  <Tag><Targets /><Simple><Name>ENCODER</Name><String>Lavf56.1.0</String></Simple></Tag>
  <Tag><Targets><TrackUID>2</TrackUID></Targets></Tag>
</Tags>
"""


def test_empty_tag_dropped(tmp_path):
    """v1.15.1: Tag ohne „Simple“ (von anderen Programmen) wird vor mkvpropedit entfernt."""
    from panepilot import videotags as vt

    root = ET.fromstring(EMPTY)
    vt.mkv_set_simple(root, "DATE_RELEASED", "1954")
    args = vt._mkv_tags_args(root, str(tmp_path))
    written = ET.parse(args[1].split(":", 1)[1]).getroot()
    assert len(written.findall("Tag")) == 1
    assert [s.findtext("Name") for s in written.find("Tag").findall("Simple")] == ["ENCODER", "DATE_RELEASED"]
    only_empty = ET.fromstring("<Tags><Tag><Targets><TrackUID>2</TrackUID></Targets></Tag></Tags>")
    assert vt._mkv_tags_args(only_empty, str(tmp_path)) == ["--tags", "all:"]
