"""v2.6: Trennlinien in der Favoritenleiste, Untertitel nach dem Einbinden, Sortieren, Spurreihenfolge."""

import json

from PySide6.QtCore import QModelIndex, Qt

from panepilot.config import FAVORITES_FILE, config_dir
from panepilot.favorites import FavNode, FavoritesModel, FavoritesView
from panepilot.icons import IconProvider


def _model(tree):
    m = FavoritesModel(IconProvider(), autosave=True)
    g = m.add_group("Projekte")
    m.add_link(str(tree / "a"), g)
    m.add_link(str(tree / "b"))
    return m, g


def test_separator_persist_and_style(qapp, tree):  # L-3600, L-3602, L-3603
    m, g = _model(tree)
    sep = m.add_separator(m.root, 1)
    assert sep.is_separator and sep.name == "" and "align" not in sep.style
    m.update_node(sep, "Arbeit", "", {"bold": True, "color": "red", "align": "left"})
    inner = m.add_separator(g, 0)
    data = json.loads((config_dir() / FAVORITES_FILE).read_text())
    item = data["items"][1]
    assert item["type"] == "separator" and item["name"] == "Arbeit" and "path" not in item
    assert item["style"] == {"bold": True, "color": "red", "align": "left"}
    m2 = FavoritesModel(IconProvider(), autosave=False)
    m2.load()
    assert [c.kind for c in m2.root.children] == ["group", "separator", "link"]
    assert m2.root.children[0].children[0].is_separator
    # Name darf wieder leer werden
    m.update_node(sep, "", "", {})
    assert sep.name == "" and sep.style == {}
    assert m.link_state(inner) == "ok"
    idx = m.index_for(sep)
    assert m.data(idx, Qt.ItemDataRole.DecorationRole) is None
    assert m.data(idx, Qt.ItemDataRole.ToolTipRole) is None


def test_separator_bounds_and_click(qapp, tree, qtbot):  # L-3601, L-3604
    m, g = _model(tree)
    m.update_node(m.root.children[1], "ein ziemlich langer Favoritenname", "", {})
    sep = m.add_separator(m.root, 1)
    view = FavoritesView(m)
    qtbot.addWidget(view)
    view.resize(400, 300)
    view.show()
    view.expandAll()
    opened = []
    view.open_link.connect(opened.append)
    view.repaint()
    idx = m.index_for(sep)
    left, right = view.separator_bounds(idx)
    link_idx = m.index_for(m.root.children[2])
    assert left == view.text_rect(link_idx).left()
    assert left < right < view.viewport().width() - 4
    # Linie im eingerückten Ordner beginnt weiter rechts
    inner = m.add_separator(g, 0)
    view.repaint()
    assert view.separator_bounds(m.index_for(inner))[0] > left
    view.activate(idx)
    assert opened == []
    view.grab()  # Zeichnen ohne Fehler


def test_separator_edit_dialog(qapp, tree):  # L-3602
    from panepilot.dialogs import FavoriteEditDialog
    from panepilot.favorites import FAV_COLORS

    node = FavNode("separator", "")
    dlg = FavoriteEditDialog(None, node, FAV_COLORS)
    assert dlg.align_combo is not None and dlg.align_combo.currentData() == "center"
    assert dlg.path_edit.isHidden()
    dlg.align_combo.setCurrentIndex(dlg.align_combo.findData("right"))
    dlg.checks["italic"].setChecked(True)
    name, _path, style = dlg.values()
    assert name == "" and style == {"italic": True, "align": "right"}
    link = FavNode("link", "x", str(tree / "a"))
    assert FavoriteEditDialog(None, link, FAV_COLORS).align_combo is None


def test_separator_not_a_toolbar_button():
    from panepilot.toolbar import available_actions

    assert "fav_separator" not in available_actions()


# --- Spuren: Reihenfolge, Untertitel danach ---------------------------------------------------------------------
import os  # noqa: E402
import shutil  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

from test_mainwindow import window  # noqa: F401,E402
from test_v093 import _open  # noqa: E402
from test_v1130 import _mp4_two_audio_sub, _srt  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg fehlt")


def _tracks(path):
    from panepilot import mkvtracks as mt

    return mt.FileTracks(path, [mt.MkvTrack(1, "video", 1, stream=0), mt.MkvTrack(2, "audio", 1, lang="ger", stream=1),
                                mt.MkvTrack(3, "audio", 2, lang="eng", stream=2),
                                mt.MkvTrack(4, "subtitles", 1, "SubRip/SRT", "ger", stream=3),
                                mt.MkvTrack(5, "subtitles", 2, "SubRip/SRT", "eng", stream=4)])


def test_dialog_move_rows(window, tmp_path):  # noqa: F811  L-3630
    from PySide6.QtCore import Qt

    from panepilot.trackdialog import TrackDialog

    f = _tracks(str(tmp_path / "a.mkv"))
    dlg = TrackDialog(window, [f])
    assert dlg.orders() == {}
    dlg.widgets[2]["name"].setText("English")
    dlg.widgets[2]["default"].setChecked(True)
    dlg.table.selectRow(0)
    assert not dlg.btn_up.isEnabled() and not dlg.btn_down.isEnabled()  # Video bleibt zuerst
    assert not dlg.move_selected(1)
    dlg.table.selectRow(1)
    assert not dlg.btn_up.isEnabled() and dlg.btn_down.isEnabled()
    dlg.table.selectRow(2)
    assert dlg.btn_up.isEnabled() and not dlg.btn_down.isEnabled()  # nicht unter die Untertitel
    assert not dlg.move_selected(1)
    assert dlg.move_selected(-1)
    assert [(r.kind, r.index) for r in dlg.rows] == [("video", 1), ("audio", 2), ("audio", 1),
                                                     ("subtitles", 1), ("subtitles", 2)]
    assert dlg.widgets[1]["name"].text() == "English" and dlg.widgets[1]["default"].isChecked()
    assert dlg.table.currentRow() == 1
    edits, _ = dlg.edits()
    assert [(tr.number, ch.name, ch.default) for tr, ch in edits[f.path]] == [(3, "English", True)]
    order = dlg.orders()[f.path]
    assert [tr.number for tr in order] == [1, 3, 2, 4, 5]
    # zurück → keine Änderung mehr
    dlg.move_selected(1)
    assert dlg.orders() == {}
    # Strg+↓ bei Untertitel 1
    dlg.table.selectRow(3)
    from PySide6.QtTest import QTest

    dlg.show()
    dlg.activateWindow()
    dlg.table.setFocus()
    QTest.qWaitForWindowActive(dlg)
    QTest.keyClick(dlg.table, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
    assert [tr.number for tr in dlg.orders()[f.path]] == [1, 2, 3, 5, 4]
    dlg.close()


def test_ordered_and_mkv_args(tmp_path, monkeypatch):
    from panepilot import videoremux as vr

    f = _tracks(str(tmp_path / "a.mkv"))
    t = f.tracks
    order = [t[0], t[2], t[1], t[4], t[3]]
    keep = vr.ordered([t[3], t[1], t[0], t[2]], order)  # Untertitel 2 wird entfernt
    assert [tr.number for tr in keep] == [1, 3, 2, 4]
    seen = {}
    monkeypatch.setattr(vr, "_tool", lambda name: name)
    monkeypatch.setattr(vr, "_run_progress", lambda args, *a, **k: seen.setdefault("args", args))
    _keep, values = vr.plan_removal(f, [t[4]], [])
    vr._remove_mkv(f, keep, values, "tmp.mkv", None, None, [vr.SubAdd("x.srt")], reorder=True)
    args = seen["args"]
    assert args[args.index("--track-order") + 1] == "0:0,0:2,0:1,0:3,1:0"


@needs_ffmpeg
def test_mp4_reorder_audio(tmp_path):  # L-3631
    from panepilot import mp4tracks as m4
    from panepilot import videoremux as vr

    src = _mp4_two_audio_sub(tmp_path)
    f = m4.read(src)
    v, a1, a2, s1 = f.tracks
    new = vr.remove_tracks(f, [], [], order=[v, a2, a1, s1])
    kept = m4.read(new).tracks
    assert [(tr.kind, tr.lang) for tr in kept] == [("video", "und"), ("audio", "eng"), ("audio", "deu"),
                                                    ("subtitles", "deu")]


@needs_ffmpeg
def test_meta_reorder_and_own_subtitle_question(window, tmp_path, monkeypatch, qtbot):  # noqa: F811  L-3612
    from panepilot import mp4tracks as m4
    from panepilot import videoremux as vr
    from panepilot.trackdialog import TrackDialog

    folder = tmp_path / "F"
    folder.mkdir()
    _mp4_two_audio_sub(folder)
    srt = folder / "Film (2001).eng.srt"
    _srt(srt)
    pane = _open(window, qtbot, folder)
    pane.meta_view.select_items([it for it in pane.meta_model.items if it.record.name == "Film (2001).mp4"])
    asked = []
    monkeypatch.setattr("panepilot.dialogs.confirm", lambda parent, title, text, **k: asked.append(text) or True)

    def reorder(self):
        self.table.selectRow(2)
        self.move_selected(-1)
        self.adds = [vr.SubAdd(str(srt), "eng", "Englisch")]
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TrackDialog, "exec", reorder)
    questions = []
    monkeypatch.setattr(type(window), "_ask_subs_dispose",
                        lambda self, paths, title: questions.append(paths) or "delete")
    window.meta_tracks()
    assert "Reihenfolge" in asked[-1] and "fragt PanePilot" in asked[-1]
    copy = folder / "Film (2001)-Kopie.mp4"
    assert copy.exists()
    assert [(tr.kind, tr.lang) for tr in m4.read(str(copy)).tracks] == [
        ("video", "und"), ("audio", "eng"), ("audio", "deu"), ("subtitles", "deu"), ("subtitles", "eng")]
    assert questions == [[str(srt)]]
    qtbot.waitUntil(lambda: not srt.exists(), timeout=10000)
    window.meta_close()


def test_dispose_modes(window, tmp_path, qtbot):  # noqa: F811  L-3610
    a, b = tmp_path / "a.srt", tmp_path / "b.srt"
    _srt(a)
    _srt(b)
    window._subs_dispose([str(a)], "keep")
    assert a.exists()
    window._subs_dispose([str(a)], "delete")
    qtbot.waitUntil(lambda: not a.exists(), timeout=10000)
    assert window.settings.get("subs_after_embed") == "keep"


def test_settings_subs_after(window, monkeypatch):  # noqa: F811  L-3610
    from panepilot.settingsdialog import SettingsDialog

    dlg = SettingsDialog(window)
    assert dlg.subs_after["keep"].isChecked()
    dlg.subs_after["trash"].setChecked(True)
    dlg.accept()
    assert window.settings.get("subs_after_embed") == "trash"


def test_sort_track_columns(qapp):  # L-3620
    from types import SimpleNamespace as NS

    from panepilot.metawizard import MetaModel

    model = MetaModel()

    def item(*langs, vcodec=""):
        rec = NS(audio_tracks=[NS(code=x, forced=False) for x in langs], sub_tracks=[], vcodec=vcodec)
        return NS(record=rec)

    a, b = item("eng", vcodec="hevc"), item("deu", "eng", vcodec="h264")
    assert model.sort_key(b, "i:audio") < model.sort_key(a, "i:audio")
    assert model.sort_key(b, "i:vcodec") < model.sort_key(a, "i:vcodec")
