"""Tests for 1.13: removing tracks, exporting subtitles, changing the video format (MP4/AVI ↔ MKV)."""

import os
import shutil
import subprocess

import pytest
from PySide6.QtWidgets import QDialog

from test_mainwindow import window  # noqa: F401
from test_v093 import _open

VIDEO = os.path.join(os.path.dirname(__file__), "data", "video")
has_ffmpeg = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
has_mkv = all(shutil.which(x) for x in ("mkvmerge", "mkvextract", "mkvpropedit"))
needs_ffmpeg = pytest.mark.skipif(not has_ffmpeg, reason="ffmpeg fehlt")
needs_mkv = pytest.mark.skipif(not (has_ffmpeg and has_mkv), reason="mkvtoolnix fehlt")


def _srt(path):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:00,000 --> 00:00:00,800\nHallo Welt\n\n")


def _mp4_two_audio_sub(tmp_path, name="Film (2001).mp4"):
    """MP4 mit Video, zwei Tonspuren (ger/eng) und einem Text-Untertitel (ger)."""
    srt = tmp_path / "in.srt"
    _srt(srt)
    out = str(tmp_path / name)
    clip = os.path.join(VIDEO, "clip.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", clip, "-i", clip, "-i", str(srt),
                    "-map", "0:v", "-map", "0:a", "-map", "1:a", "-map", "2:s", "-c", "copy", "-c:s", "mov_text",
                    "-metadata:s:a:0", "language=deu", "-metadata:s:a:1", "language=eng",
                    "-metadata:s:s:0", "language=deu", out], check=True)
    os.remove(srt)
    return out


def test_names(tmp_path):
    from panepilot import mkvtracks as mt
    from panepilot import videoremux as vr

    film = tmp_path / "Film (2001).mkv"
    film.write_text("x")
    assert vr.copy_name(str(film)) == str(tmp_path / "Film (2001)-Kopie.mkv")
    assert vr.copy_name(str(tmp_path / "Film (2001).mp4"), ".mkv") == str(tmp_path / "Film (2001)-Kopie.mkv")
    assert vr.copy_name(str(tmp_path / "Neu.mp4"), ".mkv") == str(tmp_path / "Neu.mkv")
    taken = set()
    sub = mt.MkvTrack(3, "subtitles", 1, "SubRip/SRT", "ger")
    assert vr.subtitle_name(str(film), sub, taken).endswith("Film (2001).ger.srt")
    assert vr.subtitle_name(str(film), sub, taken).endswith("Film (2001).ger.2.srt")
    forced = mt.MkvTrack(4, "subtitles", 2, "HDMV PGS", "eng", forced=True)
    assert vr.subtitle_name(str(film), forced, taken).endswith("Film (2001).eng.forced.sup")
    assert vr.subtitle_kind("VobSub") == "vobsub" and vr.subtitle_kind("SubStationAlpha") == "ass"


def test_plan_removal_moves_default():
    from panepilot import mkvtracks as mt
    from panepilot import videoremux as vr

    tracks = [mt.MkvTrack(1, "video", 1), mt.MkvTrack(2, "audio", 1, default=True), mt.MkvTrack(3, "audio", 2)]
    files = mt.FileTracks("x.mkv", tracks)
    keep, values = vr.plan_removal(files, [tracks[1]], [])
    assert keep == [tracks[0], tracks[2]] and values[id(tracks[2])]["default"] is True  # L-1312


def test_convert_problems():
    from panepilot import mkvtracks as mt
    from panepilot import videoremux as vr

    assert vr.convert_problem("a.mkv", vr.MKV) == "ist schon im Zielformat"
    assert vr.convert_problem("a.avi", vr.MKV) == "" and vr.convert_problem("a.mp4", vr.MKV) == ""
    assert vr.convert_problem("a.avi", vr.MP4) != ""  # nicht nach AVI und nicht AVI → MP4
    pgs = mt.FileTracks("a.mkv", [mt.MkvTrack(1, "video", 1), mt.MkvTrack(2, "subtitles", 1, "HDMV PGS")])
    assert "Bild-Untertitel" in vr.convert_problem("a.mkv", vr.MP4, pgs)
    dts = mt.FileTracks("a.mkv", [mt.MkvTrack(1, "video", 1), mt.MkvTrack(2, "audio", 1, "DTS")])
    assert "DTS" in vr.convert_problem("a.mkv", vr.MP4, dts)


@needs_ffmpeg
def test_mp4_remove_track_and_export(tmp_path):
    from mutagen.mp4 import MP4, MP4FreeForm

    from panepilot import mp4tracks as m4
    from panepilot import videoremux as vr

    src = _mp4_two_audio_sub(tmp_path)
    tags = MP4(src)
    tags["\xa9nam"] = ["Testfilm"]
    tags["----:com.apple.iTunes:imdbid"] = [MP4FreeForm(b"tt1")]
    tags.save()
    before = open(src, "rb").read()
    f = m4.read(src)
    assert [(tr.kind, tr.lang) for tr in f.tracks] == [("video", "und"), ("audio", "deu"), ("audio", "eng"),
                                                        ("subtitles", "deu")]
    sub = f.find("subtitles", 1)
    made = vr.export_subtitles(f, [sub])
    assert [os.path.basename(p) for p in made] == ["Film (2001).deu.srt"]
    assert "Hallo Welt" in open(made[0], encoding="utf-8").read()
    new = vr.remove_tracks(f, [f.find("audio", 2), sub], [])
    assert os.path.basename(new) == "Film (2001)-Kopie.mp4"
    assert open(src, "rb").read() == before  # Original unverändert (L-1300)
    kept = m4.read(new).tracks
    assert [(tr.kind, tr.lang) for tr in kept] == [("video", "und"), ("audio", "deu")]
    after = MP4(new)
    assert after["\xa9nam"] == ["Testfilm"] and bytes(after["----:com.apple.iTunes:imdbid"][0]) == b"tt1"
    g = m4.read(new)
    with pytest.raises(OSError):
        vr.remove_tracks(g, [g.find("audio", 1)], [])  # letzte Tonspur (L-1311)


@needs_mkv
def test_mkv_remove_export_and_convert(tmp_path):
    from panepilot import mkvtracks as mt
    from panepilot import mp4tracks as m4
    from panepilot import tags as tg
    from panepilot import videoremux as vr

    mp4 = _mp4_two_audio_sub(tmp_path, "Quelle.mp4")
    from mutagen.mp4 import MP4, MP4FreeForm

    tags = MP4(mp4)
    tags["\xa9nam"] = ["Mein Film"]
    tags["----:com.apple.iTunes:Season"] = [MP4FreeForm(b"01")]
    tags.save()
    # MP4 → MKV: neue Datei, Tags und eigene Felder übertragen (L-1304)
    mkv = vr.convert(mp4, vr.MKV, m4.read(mp4))
    assert os.path.basename(mkv) == "Quelle.mkv" and os.path.exists(mp4)
    rec = tg.read_file(mkv)
    assert rec.fields.get("title") == "Mein Film"
    assert any(rec.labels.get(k, "").casefold() == "season" and v == "01" for k, v in rec.fields.items())
    f = mt.read(mkv)
    assert [tr.kind for tr in f.tracks] == ["video", "audio", "audio", "subtitles"]
    # Untertitel exportieren und Spur entfernen
    made = vr.export_subtitles(f, [f.find("subtitles", 1)])
    assert made and made[0].endswith(".srt") and "Hallo Welt" in open(made[0], encoding="utf-8").read()
    new = vr.remove_tracks(f, [f.find("audio", 1), f.find("subtitles", 1)],
                           [(f.find("audio", 2), mt.TrackChange(name="Englisch"))])
    assert os.path.basename(new) == "Quelle-Kopie.mkv"
    g = mt.read(new)
    assert [tr.kind for tr in g.tracks] == ["video", "audio"]
    assert g.find("audio", 1).name == "Englisch" and g.find("audio", 1).default  # Standard übernommen
    assert len(mt.read(mkv).tracks) == 4  # Original unverändert
    # MKV → MP4 (zweites Mal: „-Kopie“)
    back = vr.convert(mkv, vr.MP4, m4.read(mkv))
    assert os.path.basename(back) == "Quelle-Kopie.mp4"
    assert [tr.kind for tr in m4.read(back).tracks] == ["video", "audio", "audio", "subtitles"]


@needs_mkv
def test_avi_to_mkv(tmp_path):
    from panepilot import mp4tracks as m4
    from panepilot import videoremux as vr

    avi = str(tmp_path / "Alt.avi")
    shutil.copy(os.path.join(VIDEO, "clip.avi"), avi)
    new = vr.convert(avi, vr.MKV, m4.read(avi))
    assert os.path.basename(new) == "Alt.mkv" and os.path.exists(avi)


@needs_ffmpeg
def test_cancel_leaves_nothing(tmp_path):
    import threading

    from panepilot import mp4tracks as m4
    from panepilot import videoremux as vr

    folder = tmp_path / "C"
    folder.mkdir()
    src = _mp4_two_audio_sub(folder)
    stop = threading.Event()
    stop.set()
    f = m4.read(src)
    with pytest.raises(vr.Cancelled):
        vr.remove_tracks(f, [f.find("audio", 2)], [], None, stop)
    assert sorted(os.listdir(folder)) == ["Film (2001).mp4"]


def test_dialog_remove_column(window, tmp_path):  # noqa: F811
    from panepilot import mkvtracks as mt
    from panepilot.trackdialog import TrackDialog

    one = mt.FileTracks(str(tmp_path / "a.mkv"), [mt.MkvTrack(1, "video", 1), mt.MkvTrack(2, "audio", 1),
                                                   mt.MkvTrack(3, "subtitles", 1, "SubRip/SRT", "ger")])
    dlg = TrackDialog(window, [one], on_export=lambda sel: None)
    assert "remove" not in dlg.widgets[0]  # Video
    assert not dlg.widgets[1]["remove"].isEnabled()  # einzige Tonspur (L-1311)
    dlg.widgets[2]["remove"].setChecked(True)
    removals, notes = dlg.removals()
    assert [tr.number for tr in removals[one.path]] == [3] and not notes
    assert dlg.chk_export.isChecked() and dlg.btn_export.isEnabled()
    # mehrere Dateien: „Tonspur 1“ entfernen, wo sie die letzte ist → bleibt, mit Hinweis
    two = mt.FileTracks(str(tmp_path / "b.mkv"), [mt.MkvTrack(1, "video", 1), mt.MkvTrack(2, "audio", 1),
                                                   mt.MkvTrack(3, "audio", 2)])
    many = TrackDialog(window, [one, two])
    many.widgets[1]["remove"].setChecked(True)
    removals, notes = many.removals()
    assert one.path not in removals and [tr.number for tr in removals[two.path]] == [2]
    assert any("a.mkv" in n and "letzte Tonspur" in n for n in notes)


@needs_ffmpeg
def test_meta_flows(window, tmp_path, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot.convertdialog import ConvertDialog
    from panepilot.trackdialog import TrackDialog

    folder = tmp_path / "F"
    folder.mkdir()
    _mp4_two_audio_sub(folder)
    pane = _open(window, qtbot, folder)
    assert pane.convert_buttons[cv.VIDEO_FORMAT].isVisibleTo(pane)
    asked = []
    monkeypatch.setattr("panepilot.dialogs.confirm", lambda parent, title, text, **k: asked.append(text) or True)

    def remove(self):
        self.widgets[2]["remove"].setChecked(True)  # Tonspur 2
        self.widgets[3]["remove"].setChecked(True)  # Untertitel 1
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TrackDialog, "exec", remove)
    window.meta_convert(cv.TRACKS)
    assert "-Kopie" in asked[-1] and "Untertitel" in asked[-1]
    names = sorted(os.listdir(folder))
    assert names == sorted(["Film (2001).deu.srt", "Film (2001)-Kopie.mp4", "Film (2001).mp4"])
    assert any(it.record.name == "Film (2001)-Kopie.mp4" for it in pane.meta_model.items)  # gleich in der Liste
    if shutil.which("mkvmerge"):
        seen = {}

        def convert(self):
            seen["items"] = [self.tree.topLevelItem(i).text(1) for i in range(self.tree.topLevelItemCount())]
            self.rb_mkv.setChecked(True)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(ConvertDialog, "exec", convert)
        pane.meta_view.select_items([it for it in pane.meta_model.items if it.record.name == "Film (2001).mp4"])
        window.meta_convert(cv.VIDEO_FORMAT)
        assert os.path.exists(folder / "Film (2001).mkv")
    window.meta_close()
