"""Tests für v0.9.0: Meta-Wizard für Musikdateien (Tags lesen/schreiben, Titelliste, Seitenleiste, Cover)."""

import os
import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from test_mainwindow import window  # noqa: F401

DATA = Path(__file__).parent / "data" / "audio"
FORMATS = ("mp3", "flac", "ogg", "opus", "m4a", "wma", "wav")
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
       b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture
def music(tmp_path):
    base = tmp_path / "Musik"
    (base / "Album A").mkdir(parents=True)
    (base / "Album B" / "CD2").mkdir(parents=True)
    for ext in FORMATS:
        shutil.copy(DATA / f"leer.{ext}", base / "Album A" / f"song.{ext}")
    shutil.copy(DATA / "leer.mp3", base / "Album B" / "CD2" / "tief.mp3")
    (base / "Album A" / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0kein echtes Bild")
    (base / "notiz.txt").write_text("keine Musik")
    return base


# --- Tags lesen und schreiben ------------------------------------------------------------------------
@pytest.mark.parametrize("ext", FORMATS)
def test_tags_roundtrip_all_formats(tmp_path, ext):
    from panepilot import tags as tg

    path = tmp_path / f"t.{ext}"
    shutil.copy(DATA / f"leer.{ext}", path)
    rec = tg.read_file(str(path))
    assert rec.error is None and rec.kind
    cover = tg.Picture(PNG, "image/png")
    new = tg.write_file(rec, {"title": "Hällo Wörld", "artist": "Тест", "album": "Album", "track": "3/12",
                              "year": "2003", "genre": "Rock", "comment": "Kommentar", "composer": "Orff"}, [cover])
    for key, value in (("title", "Hällo Wörld"), ("artist", "Тест"), ("comment", "Kommentar"), ("genre", "Rock")):
        assert new.fields[key] == value, (ext, key, new.fields)
    assert new.fields["year"].startswith("2003")
    assert new.fields["track"] in ("3/12",)
    assert len(new.pictures) == 1 and new.pictures[0].data == PNG
    # Entfernen und Rückgängig
    gone = tg.write_file(new, {"comment": None, "composer": None}, [])
    assert "comment" not in gone.fields and "composer" not in gone.fields and not gone.pictures


def test_id3_saved_as_v23_and_unknown_tags_kept(tmp_path):
    from mutagen.id3 import ID3, PRIV, TXXX

    from panepilot import tags as tg

    path = tmp_path / "t.mp3"
    shutil.copy(DATA / "leer.mp3", path)
    tags = ID3()
    tags.add(TXXX(encoding=3, desc="replaygain_track_gain", text=["-4.34 dB"]))
    tags.add(PRIV(owner="WM/Provider", data=b"A\x00M\x00G\x00"))
    tags.save(str(path), v2_version=4)
    rec = tg.read_file(str(path))
    assert rec.fields["x:TXXX:replaygain_track_gain"] == "-4.34 dB"
    assert rec.labels["x:TXXX:replaygain_track_gain"] == "replaygain_track_gain"
    tg.write_file(rec, {"title": "Neu"})
    after = ID3(str(path))
    assert after.version[:2] == (2, 3)  # F-940
    assert after.getall("PRIV") and after.getall("TXXX")  # F-941: unbekannte Tags bleiben


def test_track_values_kept_as_typed(tmp_path):
    from panepilot import tags as tg

    path = tmp_path / "t.mp3"
    shutil.copy(DATA / "leer.mp3", path)
    rec = tg.write_file(tg.read_file(str(path)), {"track": "083", "disc": "1/2"})
    assert rec.fields["track"] == "083" and rec.fields["disc"] == "1/2"  # F-923, A-3


def test_comment_uses_first_and_keeps_others(tmp_path):
    from mutagen.id3 import COMM, ID3

    from panepilot import tags as tg

    path = tmp_path / "t.mp3"
    shutil.copy(DATA / "leer.mp3", path)
    tags = ID3()
    tags.add(COMM(encoding=3, lang="eng", desc="ID3v1 Comment", text=["alt"]))
    tags.add(COMM(encoding=3, lang="eng", desc="Notiz", text=["zweiter"]))
    tags.save(str(path))
    rec = tg.read_file(str(path))
    assert rec.fields["comment"] == "alt"  # A-4: der erste
    assert any(v == "zweiter" for k, v in rec.fields.items() if k.startswith("x:"))
    rec = tg.write_file(rec, {"comment": "neu"})
    assert rec.fields["comment"] == "neu"
    assert any(v == "zweiter" for k, v in rec.fields.items() if k.startswith("x:"))


def test_broken_file_reports_error(tmp_path):
    from panepilot import tags as tg

    bad = tmp_path / "kaputt.mp3"
    bad.write_bytes(b"das ist keine mp3")
    assert tg.read_file(str(bad)).error


def test_picture_helpers():
    from panepilot import tags as tg
    from panepilot.metawizard import remove_shown, replace_front

    front = tg.Picture(b"A", "image/jpeg", 3)
    back = tg.Picture(b"B", "image/jpeg", 4)
    new = tg.Picture(b"N", "image/png", 3)
    assert [p.data for p in replace_front([back, front], new)] == [b"B", b"N"]  # F-930: Rückseite bleibt
    assert [p.data for p in replace_front([back], new)] == [b"N", b"B"]
    assert [p.ptype for p in replace_front([back, front], new, 0)] == [4, 3]  # angezeigtes Bild ersetzen
    assert [p.data for p in remove_shown([back, front])] == [b"B"]
    assert [p.data for p in remove_shown([back, front], 0)] == [b"A"]


def test_picture_from_file(tmp_path):
    from panepilot.metawizard import picture_from_file

    png = tmp_path / "a.png"
    png.write_bytes(PNG)
    pic = picture_from_file(str(png))
    assert pic.mime == "image/png" and pic.data == PNG  # unverändert (F-931)
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    assert picture_from_file(str(txt)) is None


# --- Einlesen ------------------------------------------------------------------------------------------
def test_scan_thread_recursive_filter_and_shares(music):
    from panepilot.filters import FilterSpec
    from panepilot.metawizard import MetaScanThread

    def run(paths, accept=None, exclude=None):
        found = []
        th = MetaScanThread([str(p) for p in paths], False, accept, exclude)
        th.found.connect(found.extend)
        th.run()
        return sorted(os.path.relpath(r.path, music) for r in found)

    everything = run([music])
    assert len(everything) == len(FORMATS) + 1 and "Album B/CD2/tief.mp3" in everything  # F-901
    assert all(not p.endswith((".txt", ".jpg")) for p in everything)
    assert run([music / "Album A" / "song.mp3", music / "Album B"]) == ["Album A/song.mp3", "Album B/CD2/tief.mp3"]
    assert run([music], exclude={str(music / "Album B")}) == [p for p in everything if p.startswith("Album A")]
    spec = FilterSpec("*.mp3")
    assert run([music], accept=spec.accepts()) == ["Album A/song.mp3", "Album B/CD2/tief.mp3"]  # F-906


# --- Im Hauptfenster -----------------------------------------------------------------------------------
def _open(window, qtbot, folder):  # noqa: F811
    panel = window.active
    panel.navigate(str(folder))
    QApplication.processEvents()
    window.trigger("meta_wizard")
    pane = window._meta_pane()
    qtbot.waitUntil(lambda: window.meta_mode is not None and window.meta_mode.get("scan") is None, timeout=10000)
    QApplication.processEvents()
    return pane


def test_meta_wizard_edit_save_undo(window, qtbot, music):  # noqa: F811
    from panepilot import tags as tg

    pane = _open(window, qtbot, music)
    view, model = pane.meta_view, pane.meta_model
    assert window.single_mode and window.active.view.isHidden()
    assert len(model.items) == len(FORMATS) + 1
    assert model.columns[0] == "filename" and "path" in model.columns
    paths = {it.record.path: it for it in model.items}
    assert paths[str(music / "Album B" / "CD2" / "tief.mp3")].folder() == os.path.join("Album B", "CD2")
    # Andere Funktionen sind gesperrt
    assert not window.qactions["delete"].isEnabled()
    window.trigger("delete")
    assert os.path.exists(music / "Album A" / "song.mp3")

    view.selectAll()
    QApplication.processEvents()
    assert pane.boxes["album"].isEnabled()
    pane.field_committed.emit("album", "Testalbum")
    assert len(model.changed_items()) == len(model.items)
    assert model.text(model.items[0], "filename").startswith("✎ ")
    assert pane.btn_save.isEnabled() and pane.btn_discard.isEnabled()
    # Datei noch unverändert (F-924)
    assert tg.read_file(str(music / "Album A" / "song.flac")).fields.get("album") is None
    window.meta_save()
    qtbot.waitUntil(lambda: window.meta_mode.get("save") is None, timeout=10000)
    assert not model.changed_items()
    for it in model.items:
        assert tg.read_file(it.record.path).fields["album"] == "Testalbum"
    assert pane.btn_undo.isEnabled()
    window.meta_undo()
    qtbot.waitUntil(lambda: window.meta_mode.get("save") is None, timeout=10000)
    for it in model.items:
        assert tg.read_file(it.record.path).fields.get("album") is None
    assert not pane.btn_undo.isEnabled()
    assert window.meta_close()
    assert window.meta_mode is None and not window.active.view.isHidden()
    assert window.qactions["delete"].isEnabled()


def test_meta_wizard_mixed_values_and_remove(window, qtbot, music):  # noqa: F811
    from panepilot import tags as tg

    for name, artist in (("song.mp3", "A"), ("song.flac", "B")):
        p = str(music / "Album A" / name)
        tg.write_file(tg.read_file(p), {"artist": artist, "comment": "weg damit"})
    pane = _open(window, qtbot, music / "Album A")
    view, model = pane.meta_view, pane.meta_model
    targets = [it for it in model.items if it.record.name in ("song.mp3", "song.flac")]
    view.select_items(targets)
    QApplication.processEvents()
    box = pane.boxes["artist"]
    assert box.currentText() == "< beibehalten >"  # F-921
    assert {box.itemText(i) for i in range(box.count())} >= {"< beibehalten >", "< entfernen >", "A", "B"}
    assert pane.boxes["comment"].currentText() == "weg damit"
    genres = [pane.boxes["genre"].itemText(i) for i in range(pane.boxes["genre"].count())]
    assert "Rock" in genres  # F-922
    pane.field_committed.emit("comment", None)
    window.meta_save()
    qtbot.waitUntil(lambda: window.meta_mode.get("save") is None, timeout=10000)
    for it in targets:
        fields = tg.read_file(it.record.path).fields
        assert "comment" not in fields and fields["artist"] in ("A", "B")
    window.meta_close()


def test_meta_wizard_cover_and_unsaved_prompt(window, qtbot, music, monkeypatch):  # noqa: F811
    from panepilot import tags as tg

    pane = _open(window, qtbot, music / "Album A")
    view, model = pane.meta_view, pane.meta_model
    mp3 = next(it for it in model.items if it.record.name == "song.mp3")
    view.select_items([mp3])
    QApplication.processEvents()
    pane.cover_replace.emit(tg.Picture(PNG, "image/png"))
    assert mp3.changed and mp3.pending_pictures and pane.cover.current().data == PNG
    # Schließen mit ungespeicherten Änderungen: Abbrechen, dann Verwerfen (F-925)
    answers = iter(["button.cancel", "meta.discard_close"])
    monkeypatch.setattr("panepilot.metacontrol._msgbox", lambda *a, **k: next(answers))
    assert not window.meta_close() and window.meta_mode is not None
    assert window.meta_close() and window.meta_mode is None
    assert not tg.read_file(mp3.record.path).pictures


def test_meta_wizard_columns_and_sidebar_layout_saved(window, qtbot, music):  # noqa: F811
    pane = _open(window, qtbot, music)
    view = pane.meta_view
    view.set_columns(["filename", "title", "i:length", "x:ENCODER"])
    pane._apply([k for k in pane.layout_keys if k != "comment"] + ["bpm"])
    window.meta_close()
    layout = window.settings.get("meta_layout")
    assert layout["columns"] == ["filename", "title", "i:length", "x:ENCODER"]
    assert "comment" not in window.settings.get("meta_sidebar") and "bpm" in window.settings.get("meta_sidebar")
    pane = _open(window, qtbot, music)
    assert pane.meta_model.columns == ["filename", "title", "i:length", "x:ENCODER"]
    assert "bpm" in pane.boxes and "comment" not in pane.boxes
    window.meta_close()


def test_meta_wizard_only_marked_entries(window, qtbot, music):  # noqa: F811
    panel = window.active
    panel.navigate(str(music))
    QApplication.processEvents()
    panel.select_names(["Album B"])
    window.trigger("meta_wizard")
    qtbot.waitUntil(lambda: window.meta_mode is not None and window.meta_mode.get("scan") is None, timeout=10000)
    assert [it.record.name for it in window._meta_pane().meta_model.items] == ["tief.mp3"]
    window.meta_close()


def test_properties_metadata_tab(window, music):  # noqa: F811
    from panepilot import tags as tg
    from panepilot.propdialog import PropertiesDialog

    mp3 = str(music / "Album A" / "song.mp3")
    tg.write_file(tg.read_file(mp3), {"title": "Hells Bells"}, [tg.Picture(PNG, "image/png")])
    dlg = PropertiesDialog(window, [mp3])
    assert dlg.tabs.isTabEnabled(2)  # F-950
    from PySide6.QtWidgets import QLabel

    labels = [w.text() for w in dlg.tabs.widget(2).findChildren(QLabel)]
    assert "Hells Bells" in labels
    dlg._edit_in_meta()
    assert dlg.edit_in_meta
    other = PropertiesDialog(window, [str(music / "notiz.txt")])
    assert not other.tabs.isTabEnabled(2)
