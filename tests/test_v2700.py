"""v2.7: Schnellansicht, Auswahl nach Muster, Ordnergrößen, Dateien vergleichen, Datum und Rechte."""

import datetime as dt
import os
import shutil
import stat
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog

from test_mainwindow import window  # noqa: F401

OFFICE = Path(__file__).parent / "data" / "office"


def _key(widget, key, mods=Qt.KeyboardModifier.NoModifier, text=""):
    ev = QKeyEvent(QEvent.Type.KeyPress, key, mods, text)
    QApplication.sendEvent(widget, ev)


# --- Auswahl nach Muster ------------------------------------------------------------------------------------------
def test_pattern_helpers():
    from panepilot import selectpattern as sp

    assert sp.split_patterns(" *.jpg; *.PNG ;; foto ") == ["*.jpg", "*.PNG", "*foto*"]
    assert sp.matches("Urlaub.JPG", ["*.jpg"]) and not sp.matches("a.txt", ["*.jpg"])
    assert sp.ext_pattern("bild.jpeg") == "*.jpeg" and sp.ext_pattern("README") == "*"
    assert sp.ext_pattern(".bashrc") == "*" and sp.ext_pattern("ordner.d", True) == "*"
    assert sp.remember(["a", "b"], "b") == ["b", "a"]


def test_select_pattern_keys(window, tmp_path, monkeypatch, qtbot):  # noqa: F811  L-3710–L-3713
    from panepilot import selectpattern as sp

    folder = tmp_path / "sel"
    (folder / "sub.jpg").mkdir(parents=True)
    for name in ("a.jpg", "b.JPG", "c.png", "d.txt", "e"):
        (folder / name).write_text("x")
    panel = window.sides["left"].panel
    panel.navigate(str(folder))
    panel.select_names([], current="a.jpg")
    panel.view.setFocus()
    seen = []

    def fake_exec(self):
        seen.append((self.windowTitle(), self.combo.currentText(), self.dirs.isChecked()))
        self.combo.setEditText("*.jpg;*.png")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(sp.PatternDialog, "exec", fake_exec)
    _key(panel.view, Qt.Key.Key_Plus, Qt.KeyboardModifier.KeypadModifier, "+")  # Num +
    assert seen[0][1] == "*.jpg" and seen[0][2] is False
    assert sorted(e.name for e in panel.selected_entries()) == ["a.jpg", "b.JPG", "c.png"]
    assert window.settings.get("select_patterns")[0] == "*.jpg;*.png"
    # Num − mit „auch Ordner“
    def fake_minus(self):
        self.combo.setEditText("*.png")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(sp.PatternDialog, "exec", fake_minus)
    _key(panel.view, Qt.Key.Key_Minus, Qt.KeyboardModifier.KeypadModifier, "-")
    assert sorted(e.name for e in panel.selected_entries()) == ["a.jpg", "b.JPG"]
    # Num * kehrt um (ohne „..“)
    _key(panel.view, Qt.Key.Key_Asterisk, Qt.KeyboardModifier.KeypadModifier, "*")
    assert sorted(e.name for e in panel.selected_entries()) == ["c.png", "d.txt", "e", "sub.jpg"]
    # Alt+Num + : gleiche Endung wie die aktuelle Datei
    panel.view.selectionModel().clearSelection()
    panel.select_names([], current="c.png")
    _key(panel.view, Qt.Key.Key_Plus, Qt.KeyboardModifier.KeypadModifier | Qt.KeyboardModifier.AltModifier, "+")
    assert [e.name for e in panel.selected_entries()] == ["c.png"]
    # das „+“ der normalen Tastatur löst nichts aus
    calls = []
    monkeypatch.setattr(sp.PatternDialog, "exec", lambda self: calls.append(1) or QDialog.DialogCode.Rejected)
    _key(panel.view, Qt.Key.Key_Plus, Qt.KeyboardModifier.NoModifier, "+")
    assert calls == []
    # Muster mit Ordnern
    panel.view.selectionModel().clearSelection()
    assert panel.select_pattern(["*.jpg"], True) == 3


def test_new_actions_no_buttons_but_menu(window):  # noqa: F811
    from panepilot.toolbar import available_actions

    avail = available_actions()
    assert "quick_view" in avail
    for aid in ("select_add", "select_remove", "select_invert", "select_same_ext", "folder_size",
                "folder_sizes_all", "compare_files", "change_date"):
        assert aid not in avail
    edit_menu = [m for m in window.menuBar().actions() if m.menu() and window.qactions["select_add"] in
                 m.menu().actions()]
    assert edit_menu


# --- Ordnergrößen -----------------------------------------------------------------------------------------------
def test_folder_sizes(window, tree, qtbot):  # noqa: F811  L-3720–L-3723
    from panepilot.filemodel import COL_SIZE

    panel = window.sides["left"].panel
    panel.navigate(str(tree))
    panel.select_names([], current="a")
    panel.view.setFocus()
    _key(panel.view, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " ")
    row = panel.model.row_of("a")
    qtbot.waitUntil(lambda: panel.model.entry(row).dir_size >= 0, timeout=5000)
    assert panel.model.entry(row).dir_size == len("eins") + len("tief" * 100) + 1
    assert panel.model.index(row, COL_SIZE).data() != ""
    assert panel.model.entry(panel.model.row_of("b")).dir_size == -1  # nur berechnen, was gewählt ist
    assert panel.current_entry().name == "a"  # kein Weiterspringen
    assert not panel.selected_entries()  # keine Markierung
    window.trigger("folder_sizes_all")
    qtbot.waitUntil(lambda: panel.model.entry(panel.model.row_of("b")).dir_size == 4, timeout=5000)
    qtbot.waitUntil(lambda: not panel.size_job_running(), timeout=5000)
    panel.select_names(["a", "b"])
    assert "409 B" in panel.status.text() or "409" in panel.status.text()
    panel.refresh()  # automatisches Neueinlesen behält die Werte
    assert panel.model.entry(panel.model.row_of("b")).dir_size == 4
    window.do_refresh()  # „Aktualisieren“ verwirft sie
    assert panel.model.entry(panel.model.row_of("b")).dir_size == -1


def test_folder_size_cancel(window, tree, qtbot, monkeypatch):  # noqa: F811
    from panepilot import dirsize

    panel = window.sides["left"].panel
    panel.navigate(str(tree))
    stop_seen = []

    def slow(path, stop=lambda: False):
        while not stop():
            QApplication.processEvents()
            import time

            time.sleep(0.01)
        stop_seen.append(path)
        return None

    monkeypatch.setattr(dirsize, "folder_size", slow)
    assert panel.calc_folder_sizes()
    assert panel.size_job_running() and "Esc" in panel.status.text()
    panel.view.setFocus()
    _key(panel.view, Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: bool(stop_seen), timeout=5000)
    assert not panel.size_job_running()


# --- Datum und Rechte -------------------------------------------------------------------------------------------
def test_date_from_name():
    from panepilot.datechange import date_from_name

    assert date_from_name("IMG_20240512_143012.jpg") == dt.datetime(2024, 5, 12, 14, 30, 12)
    assert date_from_name("Scan 2023-01-02 07.08.09.pdf") == dt.datetime(2023, 1, 2, 7, 8, 9)
    assert date_from_name("Bericht_2022-11-30.docx") == dt.datetime(2022, 11, 30)
    assert date_from_name("VID20210101.mp4") == dt.datetime(2021, 1, 1)
    assert date_from_name("Rechnung 12345678.pdf") is None  # kein gültiges Datum
    assert date_from_name("datei.txt") is None


def test_date_dialog_and_apply(window, tmp_path, monkeypatch, qtbot):  # noqa: F811  L-3740, L-3741
    from panepilot import datechange as dc

    folder = tmp_path / "dat"
    (folder / "inner").mkdir(parents=True)
    (folder / "IMG_20240512_143012.jpg").write_bytes(b"kein echtes jpg")
    (folder / "ohne.txt").write_text("x")
    (folder / "inner" / "x_20200101.txt").write_text("y")
    panel = window.sides["left"].panel
    panel.navigate(str(tmp_path))
    panel.select_names(["dat"])

    def run(self):
        assert not self.recursive.isHidden()
        self.radios[dc.NAME].setChecked(True)
        assert self.summary.text().startswith("0 ")  # Ordner selbst haben kein Datum im Namen
        self.recursive.setChecked(True)
        news = {os.path.basename(c.path): c.new for c in self.changes}
        assert news["ohne.txt"] is None and news["IMG_20240512_143012.jpg"] is not None
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dc.DateDialog, "exec", run)
    window.trigger("change_date")
    assert dt.datetime.fromtimestamp(os.stat(folder / "IMG_20240512_143012.jpg").st_mtime) == \
        dt.datetime(2024, 5, 12, 14, 30, 12)
    assert dt.datetime.fromtimestamp(os.stat(folder / "inner" / "x_20200101.txt").st_mtime).year == 2020
    # festes Datum auf eine Datei
    changes = dc.plan([str(folder / "ohne.txt")], dc.FIXED, dt.datetime(2001, 2, 3, 4, 5, 6))
    assert dc.apply(changes) == []
    assert dt.datetime.fromtimestamp(os.stat(folder / "ohne.txt").st_mtime) == dt.datetime(2001, 2, 3, 4, 5, 6)


def test_date_taken_photo(tmp_path, monkeypatch):
    from panepilot import datechange as dc
    from panepilot import tags

    photo = tmp_path / "foto.jpg"
    photo.write_bytes(b"x")
    rec = tags.TagRecord(str(photo))
    rec.fields["datetaken"] = "2019-07-01 08:09:10"
    monkeypatch.setattr(tags, "read_file", lambda path: rec)
    assert dc.date_taken(str(photo)) == dt.datetime(2019, 7, 1, 8, 9, 10)
    assert dc.date_taken(str(tmp_path / "text.txt")) is None
    (ch,) = dc.plan([str(photo)], dc.TAKEN)
    assert ch.new == dt.datetime(2019, 7, 1, 8, 9, 10).timestamp()


def test_permissions_recursive(qapp, tmp_path):  # L-3743
    from panepilot.propdialog import LEVEL_READ, PropertiesDialog

    top = tmp_path / "rechte"
    (top / "unten").mkdir(parents=True)
    (top / "datei.txt").write_text("x")
    (top / "unten" / "skript.sh").write_text("x")
    os.chmod(top / "unten" / "skript.sh", 0o755)
    os.chmod(top / "datei.txt", 0o666)
    dlg = PropertiesDialog(None, [str(top)])
    assert not dlg.recursive_box.isHidden()
    dlg.level_boxes[3].setCurrentIndex(LEVEL_READ)
    dlg.level_boxes[0].setCurrentIndex(LEVEL_READ)
    dlg.recursive_box.setChecked(True)
    assert dlg.apply_button.isEnabled()
    dlg.apply_permissions()
    mode = lambda p: stat.S_IMODE(os.stat(p).st_mode)  # noqa: E731
    assert mode(top / "datei.txt") == 0o644
    assert mode(top / "unten") & 0o055 == 0o055  # Ordner: r-x für Gruppe/Andere
    assert mode(top / "unten" / "skript.sh") & 0o100  # Ausführbarkeit der Datei bleibt
    files = PropertiesDialog(None, [str(top / "datei.txt")])
    assert files.recursive_box.isHidden()
    dlg.close()
    files.close()


# --- Dokumente ---------------------------------------------------------------------------------------------------
def test_officetext_formats():
    from panepilot import officetext as ot

    for name in ("t.docx", "t.odt"):
        doc = ot.extract(str(OFFICE / name))
        assert doc.kind == "text" and doc.text.splitlines() == ["Überschrift", "Erster Absatz\tmit Tab.",
                                                               "Zweiter Absatz"]
    for name in ("t.xlsx", "t.ods"):
        doc = ot.extract(str(OFFICE / name))
        assert [n for n, _r in doc.sheets] == ["Kosten", "Notizen"]
        rows = doc.sheets[0][1]
        assert rows[0] == ["Posten", "Betrag"] and rows[1] == ["Server", "1200.5"]
        assert doc.sheets[1][1][4] == ["", "", "spät"]
    assert ot.extract(str(OFFICE / "t.ods")).sheets[0][1][2] == ["Doppelt", "2401"]  # Formel als Ergebnis
    for name in ("t.pptx", "t.odp"):
        assert ot.extract(str(OFFICE / name)).slides == ["Folie Eins\nPunkt A", "Folie Zwei"]
    assert "Zweiter Absatz" in ot.extract(str(OFFICE / "t.pdf")).slides[0]
    text = ot.as_text(ot.extract(str(OFFICE / "t.xlsx")))
    assert "[Kosten]\nPosten\tBetrag" in text


def test_officetext_row_limit(tmp_path):
    from panepilot import officetext as ot

    import zipfile

    content = ('<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
               'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
               'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:spreadsheet>'
               '<table:table table:name="T"><table:table-row table:number-rows-repeated="1048576">'
               '<table:table-cell table:number-columns-repeated="16384"/></table:table-row>'
               '</table:table></office:spreadsheet></office:body></office:document-content>')
    path = tmp_path / "leer.ods"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("content.xml", content)
    doc = ot.extract(str(path))
    assert doc.sheets == [("T", [])] and not doc.truncated


# --- Schnellansicht ----------------------------------------------------------------------------------------------
def test_decode_and_classify(tmp_path):
    from panepilot import quickview as qv

    assert qv.decode_text("Grüße".encode("cp1252")) == "Grüße"
    assert qv.decode_text("Grüße".encode("utf-8")) == "Grüße"
    assert qv.decode_text("﻿Hallo".encode("utf-8")) == "Hallo"
    (tmp_path / "a.txt").write_text("hallo")
    (tmp_path / "b.bin").write_bytes(bytes(range(256)) * 4)
    (tmp_path / "c.log").write_text("zeile\n" * 3)
    assert qv.classify(str(tmp_path / "a.txt")) == "text"
    assert qv.classify(str(tmp_path / "c.log")) == "text"
    assert qv.classify(str(tmp_path / "b.bin")) == "other"
    assert qv.classify(str(tmp_path)) == "dir"
    assert qv.classify(str(OFFICE / "t.ods")) == "office"
    assert qv.classify(str(OFFICE / "t.pdf")) == "pdf"


def test_quick_view_flow(window, tmp_path, qtbot, monkeypatch):  # noqa: F811  L-3700–L-3704
    folder = tmp_path / "qv"
    folder.mkdir()
    (folder / "notiz.txt").write_text("Hallo Schnellansicht")
    img = QImage(40, 20, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    img.save(str(folder / "bild.png"))
    for name in ("t.ods", "t.pptx", "t.pdf"):
        shutil.copy(OFFICE / name, folder / name)
    (folder / "daten.bin").write_bytes(bytes(range(256)))
    (folder / "unter").mkdir()
    (folder / "unter" / "x").write_text("1")
    left = window.sides["left"].panel
    right = window.sides["right"].panel
    left.navigate(str(folder))
    left.select_names([], current="notiz.txt")
    left.view.setFocus()
    assert "quick_view" in window.toolbar.items
    window.trigger("quick_view")
    assert window.quick_view_side == "right" and window.qactions["quick_view"].isChecked()
    view = window._quick_view
    assert right._custom_view is view and window.active_side == "left"
    qtbot.waitUntil(lambda: view.stack.currentWidget() is view.text, timeout=5000)
    assert view.text.toPlainText() == "Hallo Schnellansicht" and view.title.text() == "notiz.txt"

    def show(name, widget, timeout=8000):
        left.select_names([], current=name)
        qtbot.waitUntil(lambda: view.path.endswith(name) and view.stack.currentWidget() is widget, timeout=timeout)

    show("bild.png", view.image)
    assert view.note.text() == "40 × 20"
    show("t.ods", view.sheets)
    assert [view.sheets.tabText(i) for i in range(view.sheets.count())] == ["Kosten", "Notizen"]
    assert view.sheets.widget(0).item(1, 0).text() == "Server"
    show("t.pptx", view.text)
    assert "Folie Zwei" in view.text.toPlainText()
    show("t.pdf", view.pdf)
    assert len(view.pdf.pages) == 1
    show("daten.bin", view.info)
    show("unter", view.info)
    assert "1" in view.info.text.text()
    # Esc schließt
    left.view.setFocus()
    _key(left.view, Qt.Key.Key_Escape)
    assert window.quick_view_side is None and right._custom_view is None
    assert not window.qactions["quick_view"].isChecked()
    assert right.view.isVisible()
    # Knopf noch einmal → an, noch einmal → aus
    window.trigger("quick_view")
    assert window.quick_view_side == "right"
    window.trigger("quick_view")
    assert window.quick_view_side is None
    # Ein-Fenster-Ansicht schließt sie
    window.trigger("quick_view")
    window.set_single_mode(True)
    assert window.quick_view_side is None
    window.set_single_mode(False)
    infos = []
    monkeypatch.setattr("panepilot.mainwindow.show_info", lambda *a: infos.append(a[2]))
    window.set_single_mode(True)
    window.trigger("quick_view")
    assert infos and window.quick_view_side is None and not window.qactions["quick_view"].isChecked()
    window.set_single_mode(False)


def test_quick_view_replaced_by_other_view(window, qtbot):  # noqa: F811
    from PySide6.QtWidgets import QLabel

    window.trigger("quick_view")
    right = window.sides["right"].panel
    right.set_custom_view(None)  # z. B. eine andere Ansicht übernimmt das Fenster
    assert window.quick_view_side is None and not window.qactions["quick_view"].isChecked()
    right.set_custom_view(QLabel("x"))
    right.set_custom_view(None)


def test_toolbar_migration(qtbot, tree):
    from panepilot.config import Settings

    s = Settings()
    s.set("toolbar", ["back", "view_mode", "refresh"])
    s.set("toolbar_quick_view_added", False)
    from panepilot.app import create_app
    from panepilot.mainwindow import MainWindow

    create_app([])
    w = MainWindow()
    qtbot.addWidget(w)
    assert w.toolbar.items == ["back", "view_mode", "quick_view", "refresh"]
    w.customize_toolbar = None
    w.close()
    w2 = MainWindow()
    qtbot.addWidget(w2)
    assert w2.toolbar.items.count("quick_view") == 1


# --- Dateien vergleichen -----------------------------------------------------------------------------------------
def test_align_and_blocks():
    from panepilot.filecompare import align, blocks

    rows = align(["a", "b", "c", "d"], ["a", "B", "c", "d", "e"])
    assert [(r.tag, r.left, r.right) for r in rows] == [("equal", "a", "a"), ("replace", "b", "B"),
                                                        ("equal", "c", "c"), ("equal", "d", "d"),
                                                        ("insert", None, "e")]
    assert blocks(rows) == [1, 4]


def test_first_difference(tmp_path):
    from panepilot.filecompare import first_difference

    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    a.write_bytes(b"\x00\x01\x02\x03")
    b.write_bytes(b"\x00\x01\x02\x03")
    c.write_bytes(b"\x00\x01\x09")
    assert first_difference(str(a), str(b)) is None
    assert first_difference(str(a), str(c)) == 2
    c.write_bytes(b"\x00\x01")
    assert first_difference(str(a), str(c)) == 2


def test_compare_files_selection(window, tmp_path, monkeypatch, qtbot):  # noqa: F811  L-3730–L-3733
    from panepilot import filecompare as fc

    one, two = tmp_path / "eins", tmp_path / "zwei"
    one.mkdir()
    two.mkdir()
    (one / "a.txt").write_text("zeile 1\nzeile 2\nzeile 3\n")
    (one / "b.txt").write_text("zeile 1\nZEILE 2\nzeile 3\nneu\n")
    (two / "c.bin").write_bytes(b"\x00\x01\x02")
    (one / "d.bin").write_bytes(b"\x00\x01\x05")
    left, right = window.sides["left"].panel, window.sides["right"].panel
    left.navigate(str(one))
    right.navigate(str(two))
    infos = []
    monkeypatch.setattr("panepilot.mainwindow.show_info", lambda *a: infos.append(a[2]))
    monkeypatch.setattr("panepilot.dialogs.show_info", lambda *a: infos.append(a[2]))
    shown = []
    real = fc.DiffDialog

    class Spy(real):
        def show(self):
            shown.append(self)

    monkeypatch.setattr(fc, "DiffDialog", Spy)
    left.select_names(["a.txt", "b.txt", "d.bin"])
    window.set_active_side("left")
    window.trigger("compare_files")
    assert infos[-1].startswith("Bitte genau zwei")
    left.select_names(["a.txt", "b.txt"])
    window.trigger("compare_files")
    dlg = shown[-1]
    assert dlg.summary.text() == "Unterschied 1 von 2"
    assert dlg.left.textCursor().blockNumber() == 1
    dlg.jump(1)
    assert dlg.right.textCursor().blockNumber() == 3
    assert "ZEILE 2" in dlg.right.toPlainText() and dlg.left.toPlainText().splitlines()[3].strip().endswith("│")
    dlg.close()
    # je eine links und rechts: Byte-Vergleich
    left.select_names(["d.bin"])
    right.select_names(["c.bin"])
    window.trigger("compare_files")
    assert "Byte 2" in infos[-1]
    # Dokumente über den Text
    shutil.copy(OFFICE / "t.docx", one / "t.docx")
    shutil.copy(OFFICE / "t.odt", two / "t.odt")
    left.refresh()
    right.refresh()
    left.select_names(["t.docx"])
    right.select_names(["t.odt"])
    window.trigger("compare_files")
    assert shown[-1].summary.text() == "Kein Unterschied im Text."
    shown[-1].close()


def test_sync_double_click_opens_compare(window, tmp_path, monkeypatch, qtbot):  # noqa: F811  L-3734
    from panepilot import filecompare, folderdiff as fd

    calls = []
    monkeypatch.setattr(filecompare, "compare", lambda parent, a, b: calls.append((a, b)))
    a, b = tmp_path / "L", tmp_path / "R"
    a.mkdir()
    b.mkdir()
    (a / "x.txt").write_text("alt")
    (b / "x.txt").write_text("neu und länger")
    window.sides["left"].panel.navigate(str(a))
    window.sides["right"].panel.navigate(str(b))
    window.do_sync_folders()
    pane = window.sync_pane()
    pane.compare()
    item = None
    it = pane.view.tree.topLevelItem(0)
    for i in range(pane.view.tree.topLevelItemCount()):
        it = pane.view.tree.topLevelItem(i)
        if it.data(0, Qt.ItemDataRole.DisplayRole) and "x.txt" in str(it.text(0)) + str(it.text(it.columnCount() - 1)):
            item = it
    assert item is not None
    pane._open(item, 0)
    assert calls and calls[0][0].endswith("x.txt") and calls[0][1].endswith("x.txt")
    window.leave_sync_mode()
    assert fd.SAME
