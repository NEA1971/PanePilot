"""Tests für v0.9.1: Zeile „..“, Feld-Editor, Konverter, langer Text."""

import os
import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from test_mainwindow import window  # noqa: F401

DATA = Path(__file__).parent / "data" / "audio"


@pytest.fixture
def album(tmp_path):
    from mutagen.id3 import ID3, PRIV, TXXX, WOAF

    from panepilot import tags as tg

    base = tmp_path / "Album"
    base.mkdir()
    songs = [("01 Eins.mp3", "1", "Eins/Zwei"), ("02 Zwei.mp3", "2", "Zwei"), ("03 Drei.flac", "3", "Drei")]
    for name, track, title in songs:
        p = base / name
        shutil.copy(DATA / ("leer.flac" if name.endswith(".flac") else "leer.mp3"), p)
        tg.write_file(tg.read_file(str(p)), {"track": track, "title": title, "artist": "PMEDIA Band"})
        if name.endswith(".mp3"):
            tags = ID3(str(p))
            tags.add(WOAF(url="www.t.me/pmedia_music"))
            tags.add(TXXX(encoding=3, desc="Uploader", text=["PMEDIA"]))
            tags.add(TXXX(encoding=3, desc="Thnx", text=["danke schön"]))
            tags.add(PRIV(owner="WM/Provider", data=b"A\x00M\x00G\x00"))
            tags.save(str(p), v2_version=3)
    return base


def _open(window, qtbot, folder):  # noqa: F811
    window.active.navigate(str(folder))
    QApplication.processEvents()
    window.trigger("meta_wizard")
    qtbot.waitUntil(lambda: window.meta_mode is not None and window.meta_mode.get("scan") is None, timeout=10000)
    QApplication.processEvents()
    return window._meta_pane()


def _wait_save(window, qtbot):  # noqa: F811
    qtbot.waitUntil(lambda: window.meta_mode.get("save") is None, timeout=10000)
    QApplication.processEvents()


# --- „..“ (F-960) ---------------------------------------------------------------------------------------
def test_parent_row_in_stem_column(window, tree):  # noqa: F811
    from PySide6.QtCore import Qt

    from panepilot.filemodel import COL_NAME_STEM

    panel = window.active
    panel.navigate(str(tree / "a"))
    model = panel.model
    row = next(r for r in range(model.rowCount()) if model.entries()[r].is_parent)
    assert model.data(model.index(row, COL_NAME_STEM), Qt.ItemDataRole.DisplayRole) == ".."


# --- Formatstrings ---------------------------------------------------------------------------------------
def test_format_engine():
    from panepilot import convert as cv

    vals = {"track": "3/12", "title": "Uf Dem Anger: Reie/Swaz", "artist": "carl orff", "albumartist": ""}

    def get(name):
        return vals.get(name, "")

    assert cv.evaluate("$num(%track%,2) - %title%", get) == "03 - Uf Dem Anger: Reie/Swaz"
    assert cv.safe_filename("03 - Uf Dem Anger: Reie/Swaz") == "03 - Uf Dem Anger- Reie-Swaz"  # F-995
    assert cv.evaluate("$caps(%artist%)", get) == "Carl Orff"
    assert cv.evaluate("$upper($left(%artist%,4))|$right(%artist%,4)", get) == "CARL|orff"
    assert cv.evaluate("$if(%albumartist%,%albumartist%,%artist%)", get) == "carl orff"
    assert cv.evaluate("$replace(%title%,Reie,R,Swaz,S)", get) == "Uf Dem Anger: R/S"
    assert cv.evaluate("$trim(' a ')'x''y'", get) == "ax'y"
    assert cv.evaluate("%TRACKNUMBER%", get) == "3/12"  # Alias
    with pytest.raises(cv.FormatError):
        cv.evaluate("$num(%track%", get)
    with pytest.raises(cv.FormatError):
        cv.evaluate("$gibtsnicht(x)", get)


def test_parse_filename():
    from panepilot import convert as cv

    assert cv.parse_filename("02. That Day", "%track%. %title%") == {"track": "02", "title": "That Day"}
    assert cv.parse_filename("083. Journey - Any Way You Want It", "%track%. %artist% - %title%") == {
        "track": "083", "artist": "Journey", "title": "Any Way You Want It"}
    assert cv.parse_filename("x - 01 - y", "%dummy% - %track% - %title%") == {"track": "01", "title": "y"}
    assert cv.parse_filename("ohne Muster", "%track% - %title%") is None


# --- Feld-Editor (F-970 ff.) -----------------------------------------------------------------------------
def _run_field_editor(window, monkeypatch, action):  # noqa: F811
    from panepilot.metadialogs import FieldEditorDialog

    def fake_exec(dlg):
        action(dlg)
        dlg._accept()
        return dlg.result()

    monkeypatch.setattr(FieldEditorDialog, "exec", fake_exec)
    window.meta_field_editor()


def test_field_editor_rows(album, window, qtbot):  # noqa: F811
    from panepilot.metadialogs import collect_fields

    pane = _open(window, qtbot, album)
    rows = {r.label: r for r in collect_fields(pane.meta_model.items, [])}
    assert rows["WOAF"].count == 2 and rows["WOAF"].kind == "extra"
    assert rows["PRIV"].kind == "data" and not rows["PRIV"].renamable and rows["PRIV"].deletable
    title = next(r for r in rows.values() if r.key == "title")
    assert title.kind == "standard" and not title.deletable and title.count == 3  # F-976
    window.meta_close()


def test_field_editor_delete_rename_new_and_undo(album, window, qtbot, monkeypatch):  # noqa: F811
    from mutagen.id3 import ID3

    from panepilot import tags as tg

    pane = _open(window, qtbot, album)

    def edit(dlg):
        for i, row in enumerate(dlg.rows):
            if row.label in ("WOAF", "Uploader", "PRIV"):
                dlg.toggle_delete(i)
        rows = {r.label: r for r in dlg.rows}
        rows["Thnx"].new_name = "Danke"
        dlg.add_new()
        dlg.rows[-1].label = "Stimmung"

    _run_field_editor(window, monkeypatch, edit)
    model = pane.meta_model
    assert len(model.changed_items()) == 2  # die beiden MP3s
    assert "Stimmung" in model.custom_fields and "x:Stimmung" in model.extra_keys()
    # Neues Feld bekommt erst mit einem Wert einen Platz in den Dateien (F-975)
    pane.meta_view.selectAll()
    pane.field_committed.emit("x:Stimmung", "ruhig")
    window.meta_save()
    _wait_save(window, qtbot)
    mp3 = str(album / "01 Eins.mp3")
    tags = ID3(mp3)
    assert not tags.getall("WOAF") and not tags.getall("PRIV") and not tags.getall("TXXX:Uploader")
    assert str(tags["TXXX:Danke"]) == "danke schön" and not tags.getall("TXXX:Thnx")
    assert str(tags["TXXX:Stimmung"]) == "ruhig"
    flac = tg.read_file(str(album / "03 Drei.flac"))
    assert flac.fields["x:STIMMUNG"] == "ruhig"
    # Rückgängig holt auch Datenfelder zurück (F-977)
    window.meta_undo()
    _wait_save(window, qtbot)
    tags = ID3(mp3)
    assert tags.getall("PRIV") and tags.getall("WOAF") and str(tags["TXXX:Thnx"]) == "danke schön"
    assert not tags.getall("TXXX:Stimmung")
    window.meta_close()


def test_field_editor_rejects_known_and_duplicate_names(album, window, qtbot, monkeypatch):  # noqa: F811
    errors = []
    monkeypatch.setattr("panepilot.metadialogs.show_error", lambda *a: errors.append(a[2]))
    _open(window, qtbot, album)

    def edit(dlg):
        rows = {r.label: r for r in dlg.rows}
        rows["Thnx"].new_name = "Komponist"  # A-3

    _run_field_editor(window, monkeypatch, edit)
    assert errors and "Komponist" in errors[-1]

    def edit2(dlg):
        rows = {r.label: r for r in dlg.rows}
        rows["Thnx"].new_name = "Uploader"  # A-2

    _run_field_editor(window, monkeypatch, edit2)
    assert "Uploader" in errors[-1]

    def edit3(dlg):
        dlg.add_new()
        dlg.rows[-1].label = "böse/Name"

    _run_field_editor(window, monkeypatch, edit3)
    assert "böse/Name" in errors[-1]
    assert not window._meta_pane().meta_model.changed_items()
    window.meta_close()


# --- Konverter (F-990 ff.) -------------------------------------------------------------------------------
def _convert(window, monkeypatch, kind, fmt, field=None):  # noqa: F811
    from panepilot.metadialogs import ConverterDialog

    def fake_exec(dlg):
        dlg.combo.setEditText(fmt)
        if field is not None:
            i = dlg.field_box.findData(field)
            dlg.field_box.setCurrentIndex(i)
        assert dlg.btn_ok.isEnabled(), dlg.preview.text()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ConverterDialog, "exec", fake_exec)
    window.meta_convert(kind)


def test_tag_to_filename_and_undo(album, window, qtbot, monkeypatch):  # noqa: F811
    pane = _open(window, qtbot, album)
    pane.meta_view.selectAll()
    _convert(window, monkeypatch, "tag2file", "$num(%track%,2) - %title%")
    names = sorted(it.pending_name for it in pane.meta_model.items)
    assert names == ["01 - Eins-Zwei.mp3", "02 - Zwei.mp3", "03 - Drei.flac"]
    window.meta_save()
    _wait_save(window, qtbot)
    assert sorted(os.listdir(album)) == names
    window.meta_undo()
    _wait_save(window, qtbot)
    assert sorted(os.listdir(album)) == ["01 Eins.mp3", "02 Zwei.mp3", "03 Drei.flac"]
    window.meta_close()


def test_tag_to_filename_conflict_marked(album, window, qtbot, monkeypatch):  # noqa: F811
    pane = _open(window, qtbot, album)
    pane.meta_view.selectAll()
    _convert(window, monkeypatch, "tag2file", "%artist%")
    marked = [it for it in pane.meta_model.items if it.mark]
    assert len(marked) == 2 and all(it.pending_name is None for it in marked)  # zwei MP3s gleicher Name
    window.meta_discard()
    window.meta_close()


def test_filename_to_tag_and_tag_to_tag(album, window, qtbot, monkeypatch):  # noqa: F811
    from panepilot import tags as tg

    pane = _open(window, qtbot, album)
    pane.meta_view.selectAll()
    _convert(window, monkeypatch, "file2tag", "%track% %title%")
    _convert(window, monkeypatch, "tag2tag", "%title% (Live)", field="title")
    window.meta_save()
    _wait_save(window, qtbot)
    rec = tg.read_file(str(album / "02 Zwei.mp3"))
    assert rec.fields["track"] == "02" and rec.fields["title"] == "Zwei (Live)"
    # passt nicht → rot, nicht geändert (F-996)
    pane.meta_view.selectAll()
    _convert(window, monkeypatch, "file2tag", "%track% - %title%")
    assert all(it.mark for it in pane.meta_model.items) and not pane.meta_model.changed_items()
    window.meta_close()


def test_presets_saved(album, window, qtbot, monkeypatch):  # noqa: F811
    from panepilot.metadialogs import ConverterDialog

    pane = _open(window, qtbot, album)
    pane.meta_view.selectAll()

    def fake_exec(dlg):
        assert dlg.combo.count() >= 2  # Startvorlagen (F-998)
        dlg.presets = dlg.presets + [{"name": "Meins", "format": "%artist% - %title%", "desc": ""}]
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ConverterDialog, "exec", fake_exec)
    window.meta_convert("tag2file")
    assert any(p["name"] == "Meins" for p in window.settings.get("meta_presets")["tag2file"])
    window.meta_close()


# --- Langer Text (F-980) -------------------------------------------------------------------------------
def test_long_text(album, window, qtbot, monkeypatch):  # noqa: F811
    from panepilot.metadialogs import TextDialog

    pane = _open(window, qtbot, album)
    pane.meta_view.selectAll()

    def fake_exec(dlg):
        dlg.edit.setPlainText("Zeile 1\nZeile 2")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(TextDialog, "exec", fake_exec)
    window._meta_long_text("lyrics")
    assert all(it.value("lyrics") == "Zeile 1\nZeile 2" for it in pane.meta_model.items)
    window.meta_discard()
    window.meta_close()


def test_converter_preview_red_only_on_mismatch(album, window, qtbot, monkeypatch):  # noqa: F811
    from panepilot.metadialogs import ConverterDialog

    pane = _open(window, qtbot, album)
    pane.meta_view.selectAll()
    seen = {}

    def fake_exec(dlg):
        dlg.combo.setEditText("%track% %title%")
        seen["ok"] = (dlg.preview_is_error, dlg.preview.text())
        dlg.combo.setEditText("%track% - %title%")
        seen["bad"] = (dlg.preview_is_error, dlg.preview.text())
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ConverterDialog, "exec", fake_exec)
    window.meta_convert("file2tag")
    assert seen["ok"][0] is False and "color" not in seen["ok"][1]
    assert seen["bad"][0] is True and "#D32F2F" in seen["bad"][1]
    window.meta_close()
