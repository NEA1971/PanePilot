"""Tests for 1.13.2: optionally replace the original instead of creating a “-Copy” file."""

import os

from PySide6.QtWidgets import QDialog

from test_mainwindow import window  # noqa: F401
from test_v093 import _open
from test_v1130 import _mp4_two_audio_sub, needs_ffmpeg


@needs_ffmpeg
def test_remove_tracks_replace(tmp_path):
    from panepilot import mp4tracks as m4
    from panepilot import videoremux as vr

    folder = tmp_path / "R"
    folder.mkdir()
    src = _mp4_two_audio_sub(folder)
    f = m4.read(src)
    out = vr.remove_tracks(f, [f.find("audio", 2)], [], replace=True)
    assert out == src and sorted(os.listdir(folder)) == ["Film (2001).mp4"]
    assert [tr.kind for tr in m4.read(src).tracks] == ["video", "audio", "subtitles"]


@needs_ffmpeg
def test_convert_replace_deletes_original(tmp_path):
    from panepilot import mp4tracks as m4
    from panepilot import videoremux as vr

    folder = tmp_path / "V"
    folder.mkdir()
    mkv = folder / "Film.mkv"
    import shutil

    shutil.copy(os.path.join(os.path.dirname(__file__), "data", "video", "clip.mkv"), mkv)
    out = vr.convert(str(mkv), vr.MP4, m4.read(str(mkv)), replace=True)
    assert os.path.basename(out) == "Film.mp4" and sorted(os.listdir(folder)) == ["Film.mp4"]


def test_checkboxes_remembered(window, tmp_path):  # noqa: F811
    from panepilot import mkvtracks as mt
    from panepilot.convertdialog import ConvertDialog
    from panepilot.trackdialog import TrackDialog

    files = [mt.FileTracks(str(tmp_path / "a.mkv"), [mt.MkvTrack(1, "video", 1), mt.MkvTrack(2, "audio", 1)])]
    dlg = TrackDialog(window, files)
    assert not dlg.chk_replace.isChecked()  # Vorgabe: Kopie anlegen
    dlg.chk_replace.setChecked(True)
    assert TrackDialog(window, files).replace_wanted() and window.settings.get("tracks_replace_original")
    conv = ConvertDialog(window, [(str(tmp_path / "a.mp4"), None)])
    assert not conv.replace_wanted()
    conv.chk_replace.setChecked(True)
    assert ConvertDialog(window, [(str(tmp_path / "a.mp4"), None)]).replace_wanted()


@needs_ffmpeg
def test_meta_flow_replace(window, tmp_path, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot.trackdialog import TrackDialog

    folder = tmp_path / "F"
    folder.mkdir()
    src = _mp4_two_audio_sub(folder)
    pane = _open(window, qtbot, folder)
    asked = []
    monkeypatch.setattr("panepilot.dialogs.confirm", lambda parent, title, text, **k: asked.append(text) or True)

    def remove(self):
        self.chk_replace.setChecked(True)
        self.chk_export.setChecked(False)
        self.widgets[2]["remove"].setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TrackDialog, "exec", remove)
    window.meta_convert(cv.TRACKS)
    assert "ersetzt" in asked[-1] and "nicht rückgängig" in asked[-1]
    assert sorted(os.listdir(folder)) == ["Film (2001).mp4"]
    assert len(pane.meta_model.items) == 1 and len(pane.meta_model.items[0].record.audio_tracks) == 1
    assert os.path.exists(src)
    window.meta_close()
