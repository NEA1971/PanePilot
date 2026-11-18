"""Tests for 1.12: editing tracks in MP4 files (language in place, name/default by repacking)."""

import os
import shutil
import subprocess
import threading

import pytest
from PySide6.QtWidgets import QDialog

from test_mainwindow import window  # noqa: F401
from test_v093 import _open
from test_v190 import PNG

VIDEO = os.path.join(os.path.dirname(__file__), "data", "video")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                  reason="ffmpeg fehlt")


def _mp4(tmp_path, name="film.mp4"):
    path = str(tmp_path / name)
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), path)
    return path


def _probe(path):
    import json

    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", path],
                         capture_output=True, text=True, check=True).stdout
    return [s for s in json.loads(out)["streams"] if not (s.get("disposition") or {}).get("attached_pic")]


def test_language_codes():
    from panepilot import mp4tracks as m4

    assert m4.to_t("ger") == "deu" and m4.to_t("FRE") == "fra" and m4.to_t("eng") == "eng"
    assert m4._pack("deu") == m4._pack("ger")
    with pytest.raises(ValueError):
        m4._pack("de-DE")


def test_language_in_place(tmp_path):
    from panepilot import mp4tracks as m4

    path = _mp4(tmp_path)
    size = os.path.getsize(path)
    fields = m4.language_fields(path)
    assert sorted((tid, kind) for tid, (_p, _c, kind) in fields.items()) == [(1, "video"), (2, "audio")]
    m4.set_languages(path, {2: "ger"})
    assert m4.language_fields(path)[2][1] == "deu" and os.path.getsize(path) == size  # L-1201: gleiche Datei
    if shutil.which("ffprobe"):
        assert _probe(path)[1]["tags"]["language"] == "deu"


@needs_ffmpeg
def test_read_and_plan(tmp_path):
    from panepilot import mkvtracks as mt
    from panepilot import mp4tracks as m4

    f = m4.read(_mp4(tmp_path))
    assert f.fmt == "mp4" and [(tr.kind, tr.number, tr.stream) for tr in f.tracks] == [("video", 1, 0),
                                                                                         ("audio", 2, 1)]
    audio = f.find("audio", 1)
    assert audio.name == ""  # „SoundHandler“ ist kein echter Name
    assert m4.plan([(audio, mt.TrackChange(lang="ger"))]) == ({2: "deu"}, False)
    assert m4.plan([(audio, mt.TrackChange(name="Deutsch"))])[1] is True
    assert not f.has_effect(audio, mt.TrackChange(forced=True))  # L-1204: forced bei MP4 ohne Wirkung


@needs_ffmpeg
def test_remux_keeps_tags_and_cover(tmp_path):
    from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

    from panepilot import mkvtracks as mt
    from panepilot import mp4tracks as m4

    path = _mp4(tmp_path)
    tags = MP4(path)
    tags["\xa9nam"] = ["Mein Film"]
    tags["----:com.apple.iTunes:imdbid"] = [MP4FreeForm(b"tt0078748")]
    tags["covr"] = [MP4Cover(PNG, imageformat=MP4Cover.FORMAT_PNG)]
    tags.save()
    f = m4.read(path)
    audio = f.find("audio", 1)
    seen = []
    m4.write(f, [(audio, mt.TrackChange(lang="ger", name="Deutsch AAC Mono", default=True))], seen.append)
    streams = _probe(path)
    assert len(streams) == 2  # kein Cover als zusätzliche Videospur
    a = streams[1]
    assert a["tags"]["language"] == "deu" and a["disposition"]["default"] == 1
    again = m4.read(path).find("audio", 1)
    assert again.name == "Deutsch AAC Mono"
    after = MP4(path)
    assert after["\xa9nam"] == ["Mein Film"] and bytes(after["----:com.apple.iTunes:imdbid"][0]) == b"tt0078748"
    assert after["covr"] and bytes(after["covr"][0]) == PNG
    assert not [n for n in os.listdir(tmp_path) if "panepilot-tmp" in n]


@needs_ffmpeg
def test_remux_cancel_keeps_original(tmp_path):
    from panepilot import mkvtracks as mt
    from panepilot import mp4tracks as m4

    path = _mp4(tmp_path)
    before = open(path, "rb").read()
    f = m4.read(path)
    stop = threading.Event()
    stop.set()
    with pytest.raises(m4.Cancelled):
        m4.write(f, [(f.find("audio", 1), mt.TrackChange(name="X"))], None, stop)
    assert open(path, "rb").read() == before
    assert not [n for n in os.listdir(tmp_path) if "panepilot-tmp" in n]


def test_dialog_forced_disabled_for_mp4(window, tmp_path):  # noqa: F811
    from panepilot import mkvtracks as mt
    from panepilot.trackdialog import TrackDialog

    tracks = [mt.MkvTrack(1, "video", 1, "H.264"), mt.MkvTrack(2, "audio", 1, "AAC", channels=2),
              mt.MkvTrack(3, "subtitles", 1, "Text (MP4)", "eng")]
    dlg = TrackDialog(window, [mt.FileTracks(str(tmp_path / "a.mp4"), tracks, fmt="mp4")])
    assert not dlg.widgets[2]["forced"].isEnabled() and dlg.widgets[2]["default"].isEnabled()
    assert "MP4" in dlg.widgets[2]["forced"].toolTip()


@needs_ffmpeg
def test_meta_tracks_mp4_flow(window, tmp_path, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import mp4tracks as m4
    from panepilot.trackdialog import TrackDialog

    folder = tmp_path / "F"
    folder.mkdir()
    path = _mp4(folder, "b.mp4")
    pane = _open(window, qtbot, folder)
    asked = []
    monkeypatch.setattr("panepilot.dialogs.confirm", lambda parent, title, text, **k: asked.append(text) or True)

    def run(self):
        w = self.widgets[1]  # Tonspur 1
        w["lang"].setCurrentIndex(w["lang"].findData("ger"))
        w["name"].setText("Deutsch")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TrackDialog, "exec", run)
    window.meta_convert(cv.TRACKS)
    assert "neu" in asked[0] and "Tags, eigene Felder und Cover" in asked[0]  # Hinweis aufs Neupacken
    assert m4.read(path).find("audio", 1).name == "Deutsch"
    item = pane.meta_model.items[0]
    assert item.record.audio_tracks[0].lang == "deu"  # Spalte neu eingelesen
    window.meta_close()
