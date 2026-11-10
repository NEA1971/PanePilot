"""Tests für v0.9.3: Tags exportieren/importieren, Nummerieren, Playlist, Prüfsummen-Datei, Symbolleiste."""

import os
import shutil
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from test_mainwindow import window  # noqa: F401

DATA = Path(__file__).parent / "data" / "audio"


@pytest.fixture
def album(tmp_path):
    from panepilot import tags as tg

    base = tmp_path / "Back In Black"
    base.mkdir()
    for i, title in enumerate(("Hells Bells", "Shoot to Thrill", "What Do You Do"), 1):
        p = base / f"song{i}.mp3"
        shutil.copy(DATA / "leer.mp3", p)
        tg.write_file(tg.read_file(str(p)), {"title": title, "artist": "AC/DC", "album": "Back In Black",
                                             "track": str(i)})
    return base


def _open(window, qtbot, folder):  # noqa: F811
    window.active.navigate(str(folder))
    QApplication.processEvents()
    window.trigger("meta_wizard")
    qtbot.waitUntil(lambda: window.meta_mode is not None and window.meta_mode.get("scan") is None, timeout=10000)
    QApplication.processEvents()
    pane = window._meta_pane()
    # sortiert nach Dateiname, damit die Reihenfolge feststeht
    pane.meta_view.sortByColumn(0, pane.meta_view.header().sortIndicatorOrder().AscendingOrder)
    pane.meta_view.clearSelection()
    return pane


# --- Nummerieren --------------------------------------------------------------------------------------------
def test_track_numbers():
    from panepilot.metaextras import track_numbers

    assert track_numbers(3, 1, 2, False, 3) == ["01", "02", "03"]
    assert track_numbers(2, 9, 1, True, 12) == ["9/12", "10/12"]
    assert track_numbers(2, 1, 3, True, 2) == ["001/002", "002/002"]


def test_number_wizard(album, window, qtbot, monkeypatch):  # noqa: F811
    from panepilot.metaextras import NumberDialog

    pane = _open(window, qtbot, album)

    def fake_exec(dlg):
        assert dlg.count == 3 and dlg.start.value() == 1 and dlg.digits.value() == 2
        assert not dlg.with_total.isChecked()  # Vorgabe: ohne Gesamtzahl
        dlg.start.setValue(5)
        dlg.with_total.setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(NumberDialog, "exec", fake_exec)
    window.meta_convert("number")
    order = pane.meta_view.target_items()
    assert [it.value("track") for it in order] == ["05/03", "06/03", "07/03"]
    assert window.settings.get("meta_number")["start"] == 5
    window.meta_discard()
    window.meta_close()


# --- Export / Import -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("ext", ["txt", "csv"])
def test_export_and_reimport_with_assignment(album, window, qtbot, monkeypatch, tmp_path, ext):  # noqa: F811
    from panepilot import metaextras as mx

    pane = _open(window, qtbot, album)
    out = tmp_path / f"export.{ext}"
    monkeypatch.setattr("panepilot.metacontrol.QFileDialog.getSaveFileName", lambda *a, **k: (str(out), ""))
    window.meta_convert("tag2text")
    text = out.read_text(encoding="utf-8-sig")
    sep = ";" if ext == "csv" else "\t"
    lines = text.splitlines()
    assert lines[0].split(sep)[:2] == ["Dateiname", "Titel"] and len(lines) == 4
    # Datei bearbeiten: Reihenfolge umdrehen, ein Titel neu, ein Feld leer, Kommentar entfernen
    header, *rows = [ln.split(sep) for ln in lines]
    ti = header.index("Titel")
    ki = header.index("Kommentar")
    ii = header.index("Interpret")
    rows[0][ti] = "Hells Bells (Live)"
    rows[1][ii] = ""
    rows[2][ki] = "<entfernen>"
    out.write_text("\n".join(sep.join(r) for r in [header] + rows[::-1]), encoding="utf-8")

    data = mx.read_text_file(str(out), [])
    assert data.header[0] == "filename"
    items = pane.meta_view.target_items()
    left, right = mx.initial_order(data, items)
    assert [data.rows[r][0] for r in right] == [it.record.name for it in left]  # Zuordnung über Dateiname

    monkeypatch.setattr("panepilot.metacontrol.QFileDialog.getOpenFileName", lambda *a, **k: (str(out), ""))
    monkeypatch.setattr(mx.ImportDialog, "exec", lambda dlg: QDialog.DialogCode.Accepted)
    window.meta_convert("text2tag")
    by = {it.record.name: it for it in pane.meta_model.items}
    assert by["song1.mp3"].value("title") == "Hells Bells (Live)"
    assert by["song2.mp3"].value("artist") == "AC/DC"  # leer = unverändert
    assert "comment" not in by["song3.mp3"].pending  # Kommentar war leer – nichts zu löschen
    assert len(pane.meta_model.changed_items()) == 1
    window.meta_discard()
    window.meta_close()


def test_import_plain_list_with_skips(album, window, qtbot, monkeypatch, tmp_path):  # noqa: F811
    from panepilot import metaextras as mx

    pane = _open(window, qtbot, album)
    src = tmp_path / "liste.txt"
    src.write_text("1. Hells Bells\n2. Shoot to Thrill\nkeine Nummer\n", encoding="utf-8")

    def fake_exec(dlg):
        assert dlg.data.header is None
        dlg.fmt_combo.setEditText("%track%. %title%")
        dlg.list_left.setCurrentRow(1)
        dlg._insert_skip("left")  # Datei 2 rutscht nach unten
        assert dlg.left[1] is None
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr("panepilot.metacontrol.QFileDialog.getOpenFileName", lambda *a, **k: (str(src), ""))
    monkeypatch.setattr(mx.ImportDialog, "exec", fake_exec)
    window.meta_convert("text2tag")
    by = {it.record.name: it for it in pane.meta_model.items}
    assert by["song1.mp3"].value("title") == "Hells Bells" and by["song1.mp3"].value("track") == "1"
    assert by["song2.mp3"].mark  # bekommt „keine Nummer“ → passt nicht → rot
    assert not by["song2.mp3"].changed
    window.meta_discard()
    window.meta_close()


# --- Playlist -----------------------------------------------------------------------------------------------
def test_playlist(album, window, qtbot, monkeypatch):  # noqa: F811
    from panepilot import metaextras as mx

    pane = _open(window, qtbot, album)
    target = {}

    def fake_exec(dlg):
        target["path"] = dlg.target()
        assert target["path"].endswith("Back In Black.m3u8") and dlg.relative.isChecked()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(mx.PlaylistDialog, "exec", fake_exec)
    window.meta_convert("playlist")
    text = Path(target["path"]).read_text(encoding="utf-8").splitlines()
    assert text[0] == "#EXTM3U"
    assert text[1].startswith("#EXTINF:") and text[1].endswith(",AC/DC - Hells Bells")
    assert text[2] == "song1.mp3" and len(text) == 7
    absolute = mx.playlist_text(str(album.parent / "x.m3u8"), pane.meta_view.target_items(), False)
    assert str(album / "song1.mp3") in absolute
    relative = mx.playlist_text(str(album.parent / "x.m3u8"), pane.meta_view.target_items(), True)
    assert "Back In Black/song1.mp3" in relative
    window.meta_close()


# --- Prüfsummen-Datei ---------------------------------------------------------------------------------------
def test_parse_checksum_file(tmp_path):
    from panepilot.toolpanes import parse_checksum_file

    h = "a" * 64
    gnu = tmp_path / "x.sha256"
    gnu.write_text(f"{'b' * 64}  andere.iso\n{h} *debian.iso\n")
    assert parse_checksum_file(str(gnu), "debian.iso") == h
    assert parse_checksum_file(str(gnu), "fehlt.iso") is None
    bsd = tmp_path / "x.txt"
    bsd.write_text(f"SHA256 (debian.iso) = {h}\n")
    assert parse_checksum_file(str(bsd), "debian.iso") == h
    sfv = tmp_path / "x.sfv"
    sfv.write_text("; Kommentar\ndebian.iso 1a2b3c4d\n")
    assert parse_checksum_file(str(sfv), "debian.iso") == "1a2b3c4d"
    single = tmp_path / "nur.md5"
    single.write_text("d41d8cd98f00b204e9800998ecf8427e\n")
    assert parse_checksum_file(str(single), "egal.iso") == "d41d8cd98f00b204e9800998ecf8427e"  # 16


def test_checksum_pane_drop(window, tree, qtbot, tmp_path):  # noqa: F811
    import hashlib

    window.sides["left"].panel.view.setFocus()
    window.sides["left"].panel.select_names([], current="eins.txt")
    window.trigger("checksums")
    pane = window.sides["left"].sidebar.widget_for("checksum")
    qtbot.waitUntil(lambda: bool(pane.values), timeout=5000)
    f = tmp_path / "pruef.sha256"
    f.write_text(f"{hashlib.sha256(b'eins').hexdigest()}  eins.txt\n")
    pane.load_checksum_file(str(f))
    assert pane.compare.text() == hashlib.sha256(b"eins").hexdigest()
    assert "SHA-256" in pane.result.text()
    other = tmp_path / "anders.sha256"
    other.write_text(f"{'c' * 64}  anders.txt\n")
    pane.load_checksum_file(str(other))
    assert pane.compare.text() == "" and "anders.sha256" in pane.result.text()
    window.close_tool("left")


# --- Symbolleiste -------------------------------------------------------------------------------------------
def test_toolbar_spacer_and_right(window):  # noqa: F811
    from panepilot.toolbar import RIGHT, ToolbarDialog, clean_items

    assert clean_items(["back", "_:30", ">", "forward", ">", "_:999"]) == ["back", "_:30", ">", "forward", "_:200"]
    dlg = ToolbarDialog(window, ["back", "forward"])
    dlg.chosen.setCurrentRow(0)
    dlg.space_width.setValue(40)
    dlg._add_spacer()
    dlg._add_right()
    assert not dlg.btn_right.isEnabled()
    dlg.chosen.setCurrentRow(1)
    dlg.space_width.setValue(60)  # markierten Abstand ändern
    assert dlg.result_items() == ["back", "_:60", RIGHT, "forward"]
    window.toolbar.set_items(dlg.result_items())
    assert len(window.toolbar.actions()) == 4
    dlg.deleteLater()


def test_checksum_drop_from_own_panel(window, tree, qtbot, tmp_path):  # noqa: F811
    """Ziehen aus dem Dateifenster setzt den Cursor auf die Prüfsummen-Datei – gemeint ist die Datei davor."""
    import hashlib

    sums = tree / "a" / "SHA512SUMS"
    sums.write_text(f"{hashlib.sha512(b'eins').hexdigest()}  eins.txt\n{'0' * 128}  andere.iso\n")
    panel = window.sides["left"].panel
    panel.refresh()
    panel.view.setFocus()
    panel.select_names([], current="eins.txt")
    window.trigger("checksums")
    pane = window.sides["left"].sidebar.widget_for("checksum")
    qtbot.waitUntil(lambda: bool(pane.values), timeout=5000)
    values = dict(pane.values)
    pane.show_file(str(sums))  # Beginn des Ziehens: der Cursor steht auf der Prüfsummen-Datei
    pane.load_checksum_file(str(sums))
    assert pane.path.endswith("eins.txt") and pane.values == values  # nichts neu berechnet (v0.9.5)
    assert pane.compare.text() == hashlib.sha512(b"eins").hexdigest()
    qtbot.waitUntil(lambda: "✔" in pane.result.text(), timeout=10000)
    window.close_tool("left")


def test_checksum_waits_while_mouse_pressed(window, tree, qtbot, monkeypatch):  # noqa: F811
    from PySide6.QtCore import Qt

    import panepilot.toolpanes as tp

    window.sides["left"].panel.view.setFocus()
    window.sides["left"].panel.select_names([], current="eins.txt")
    window.trigger("checksums")
    pane = window.sides["left"].sidebar.widget_for("checksum")
    qtbot.waitUntil(lambda: bool(pane.values), timeout=5000)
    pressed = {"b": Qt.MouseButton.LeftButton}
    monkeypatch.setattr(tp.QApplication, "mouseButtons", staticmethod(lambda: pressed["b"]))
    pane.show_file(str(tree / "a" / "sub" / "tief.txt"))
    qtbot.wait(500)
    assert pane.path.endswith("eins.txt") and pane.values  # Maustaste gedrückt: noch kein Wechsel
    pressed["b"] = Qt.MouseButton.NoButton
    qtbot.waitUntil(lambda: pane.path.endswith("tief.txt"), timeout=3000)
    window.close_tool("left")
