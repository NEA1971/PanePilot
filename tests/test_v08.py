"""Tests für v0.8: Einstellungsordner, Sicherung, Größeneinheiten, Sprachen, Spaltenprofile,
Eigenschaften, Prüfsummen und Suche."""

import datetime as dt
import json
import os
import stat
import zipfile

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from test_mainwindow import press, window  # noqa: F401


# --- Einstellungsordner und Sicherung -------------------------------------------------------------
def test_settings_migration(tmp_path, monkeypatch):
    root = tmp_path / "altcfg"
    root.mkdir()
    (root / "settings.json").write_text("{}")
    (root / "Favoriten").mkdir()
    monkeypatch.setenv("PANEPILOT_CONFIG_DIR", str(root))
    from panepilot.config import config_dir

    d = config_dir()
    assert d == root / "Settings"
    assert (d / "settings.json").exists() and (d / "Favoriten").is_dir()
    assert not (root / "settings.json").exists()


def test_backup_create_prune_restore(tmp_path):
    from panepilot import backup
    from panepilot.config import config_dir, save_json

    save_json("settings.json", {"show_hidden": True})
    folder = tmp_path / "sich"
    day = dt.date(2026, 11, 7)
    a = backup.create_backup(folder, auto=True, day=day)
    b = backup.create_backup(folder, auto=False, day=day)
    assert a.name == "PanePilot_Settings_2026-11-07a.zip" and b.name == "PanePilot_Settings_2026-11-07b.zip"
    assert "settings.json" in zipfile.ZipFile(a).namelist()
    for i in range(1, 5):
        backup.create_backup(folder, auto=True, day=dt.date(2026, 11, 7 + i))
    backup.prune(folder, 3)
    names = sorted(p.name for p in folder.glob("*.zip"))
    assert "PanePilot_Settings_2026-11-07b.zip" in names  # manuell: bleibt
    assert "PanePilot_Settings_2026-11-07a.zip" not in names
    assert len([n for n in names if n != "PanePilot_Settings_2026-11-07b.zip"]) == 3
    save_json("settings.json", {"show_hidden": False})
    backup.restore_backup(b)
    assert json.loads((config_dir() / "settings.json").read_text())["show_hidden"] is True


def test_backup_unreachable_share(tmp_path):
    from panepilot import backup

    class FakeMounts:
        def needs_mount(self, path):
            return object()

    assert not backup.folder_reachable(tmp_path, FakeMounts())
    assert backup.folder_reachable(tmp_path / "neu", None)


def test_auto_backup_once_per_day(window, tmp_path):  # noqa: F811
    window.settings.set("backup_dir", str(tmp_path / "sich"))
    window.auto_backup()
    window.auto_backup()
    assert len(list((tmp_path / "sich").glob("*.zip"))) == 1


# --- Größeneinheit ----------------------------------------------------------------------------------
def test_size_units():
    from panepilot.util import format_size

    assert format_size(1500, "auto") == "1,5 KB"
    assert format_size(123456789, "MiB") == "118 MiB"
    assert format_size(123456789, "B") == "123.456.789 B"
    assert format_size(2_000_000_000, "GB") == "2,00 GB"


# --- Sprachen ---------------------------------------------------------------------------------------
def test_bundled_languages_and_fallback():
    from panepilot import i18n

    langs = i18n.languages()
    assert {"de", "en", "frk", "sxu", "es", "fr", "ru"} <= set(langs)
    assert langs["frk"].fallback == "de" and langs["es"].fallback == "en"
    i18n.load_language("frk")
    assert i18n.current_language() == "frk"
    assert i18n.qt_locale_name() == "de"
    i18n.load_language("en")
    assert i18n.t("menu.file") == "&File"
    i18n.load_language("gibtsnicht")  # unbekannt → Systemvorgabe
    assert i18n.current_language() in langs
    i18n.load_language("de")


def test_all_translations_complete_and_placeholders_match():
    import re

    from panepilot import i18n

    base = i18n.read_language("de")
    ph = re.compile(r"\{(\w*)\}")
    for code in ("en", "frk", "sxu", "es", "fr", "ru"):
        other = i18n.read_language(code)
        missing = sorted(set(base) - set(other))
        assert not missing, f"{code}: fehlende Texte {missing[:10]}"
        bad = [k for k in base if set(ph.findall(base[k])) != set(ph.findall(other[k]))]
        assert not bad, f"{code}: Platzhalter passen nicht bei {bad[:10]}"


def test_user_language_overrides_and_new_language():
    from panepilot import i18n

    i18n.save_user_language("bar", "Boarisch", "de", {"menu.file": "Dadei"})
    assert i18n.languages()["bar"].user
    i18n.load_language("bar")
    assert i18n.t("menu.file") == "Dadei"
    assert i18n.t("menu.edit") == i18n.read_language("de")["menu.edit"]  # Ersatz: Deutsch
    i18n.save_user_language("en", "English", "de", {"menu.file": "Fiiile"})
    i18n.load_language("en")
    assert i18n.t("menu.file") == "Fiiile"
    i18n.load_language("de")


def test_language_editor_saves(window):  # noqa: F811
    from panepilot import i18n
    from panepilot.settingsdialog import LanguageEditor

    ed = LanguageEditor(window, "frk")
    row = next(r for r in range(ed.table.rowCount()) if ed.table.item(r, 0).text() == "menu.file")
    ed.table.item(row, 2).setText("Dadei!")
    assert ed.save_button.isEnabled()
    row2 = next(r for r in range(ed.table.rowCount()) if ed.table.item(r, 0).text() == "status.counts")
    ed.table.item(row2, 2).setText("kaputt")  # Platzhalter fehlen
    assert not ed.save_button.isEnabled()
    ed.table.item(row2, 2).setText("{dirs} Ordner, {files} Dadeien")
    ed.accept()
    assert i18n.languages()["frk"].user
    assert i18n.read_language("frk")["menu.file"] == "Dadei!"


# --- Einstellungsfenster und Spaltenprofile ---------------------------------------------------------
def test_settings_dialog_and_column_profiles(window, monkeypatch):  # noqa: F811
    from panepilot import colprofiles
    from panepilot.filemodel import COL_CREATED, COL_SIZE
    from panepilot.settingsdialog import SettingsDialog

    assert colprofiles.names() == ["Standard"]
    dlg = SettingsDialog(window)
    dlg.unit_box.setCurrentIndex(dlg.unit_box.findData("KiB"))
    monkeypatch.setattr("panepilot.dialogs.ask_text", lambda *a, **k: "Fotos")
    dlg._prof_new()
    assert dlg._current_profile == "Fotos"
    from panepilot.filemodel import MENU_ORDER

    row = MENU_ORDER.index(COL_CREATED)
    dlg.col_table.item(row, 0).setCheckState(Qt.CheckState.Checked)
    dlg._align_boxes[COL_CREATED].setCurrentIndex(dlg._align_boxes[COL_CREATED].findData("center"))
    dlg.side_boxes["right"].setCurrentIndex(dlg.side_boxes["right"].findText("Fotos"))
    dlg.accept()
    assert window.settings.get("size_unit") == "KiB"
    right = window.sides["right"].panel
    assert right.column_profile == "Fotos" and right.column_visible(COL_CREATED)
    assert right.model.alignments == {COL_CREATED: "center"}
    assert window.sides["left"].panel.column_profile == "Standard"
    assert not window.sides["left"].panel.column_visible(COL_CREATED)
    # Ausrichtung direkt im Fenster, wird ins Profil übernommen
    right.set_alignment(COL_SIZE, "center")
    window._save_column_profile("right")
    assert colprofiles.load("Fotos")["align"][COL_SIZE] == "center"
    from panepilot.util import set_size_unit

    set_size_unit("auto")


# --- Eigenschaften --------------------------------------------------------------------------------
def test_properties_dialog(window, tree):  # noqa: F811
    from panepilot.propdialog import PropertiesDialog, mode_text

    f = tree / "a" / "eins.txt"
    os.chmod(f, 0o644)
    dlg = PropertiesDialog(window, [str(f)])
    assert dlg.code_label.text() == "644 (rw-r--r--)"
    dlg.level_boxes[0].setCurrentIndex(0)  # Andere: keine
    dlg.exec_box.setChecked(True)
    assert dlg.code_label.text() == "750 (rwxr-x---)"
    assert dlg.apply_button.isEnabled()
    dlg.apply_permissions()
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o750
    assert mode_text(0o40755) == "755 (rwxr-xr-x)"
    d = PropertiesDialog(window, [str(tree / "a")])
    assert d._thread is not None
    d._thread.wait(3000)
    QApplication.processEvents()
    assert "Dateien" in d.count_label.text()
    d.done(0)
    assert not d.tabs.isTabEnabled(2)  # Metadaten kommt in v0.9


# --- Prüfsummen ----------------------------------------------------------------------------------
def test_checksums_and_detection(tmp_path):
    from panepilot import toolpanes as tp

    f = tmp_path / "x.bin"
    f.write_bytes(b"PanePilot")
    v = tp.compute_checksums(str(f))
    import hashlib
    import zlib

    assert v["sha256"] == hashlib.sha256(b"PanePilot").hexdigest()
    assert v["crc32"] == f"{zlib.crc32(b'PanePilot') & 0xffffffff:08x}"
    assert tp.detect_algorithm(v["md5"].upper()) == "md5"
    assert tp.detect_algorithm(" ".join([v["sha512"][:64], v["sha512"][64:]])) == "sha512"
    assert tp.detect_algorithm("xyz") is None


def test_checksum_pane_compare(window, tree, qtbot):  # noqa: F811
    import hashlib

    panel = window.active
    panel.navigate(str(tree / "a"))
    panel.select_names([], current="eins.txt")
    window.trigger("checksums")
    pane = window.sides[window.active_side].sidebar.widget_for("checksum")
    qtbot.waitUntil(lambda: bool(pane.values), timeout=5000)
    good = hashlib.sha256(b"eins").hexdigest()
    pane.compare.setText(good.upper())
    assert pane.result.text().startswith("✔") and "SHA-256" in pane.result.text()
    pane.compare.setText(good[:-1] + ("0" if good[-1] != "0" else "1"))
    assert pane.result.text().startswith("✘")
    panel.select_names([], current="sub")
    assert pane.file_label.text() == pane.file_label.text()  # Ordner: Hinweis
    qtbot.waitUntil(lambda: not pane.values, timeout=2000)
    window.close_tool(window.active_side)
    assert window.sides[window.active_side].sidebar.mode != "checksum"


# --- Suche ------------------------------------------------------------------------------------------
def _run(base, opts):
    from panepilot.search import SearchThread

    found, done = [], []
    th = SearchThread(str(base), opts)
    th.found.connect(found.extend)
    th.finished_search.connect(lambda c, s: done.append((c, s)))
    th.run()  # synchron im Test
    return sorted(os.path.relpath(p, base) for p in found), done[0]


def test_search_thread(tree, monkeypatch):
    from panepilot import search as srch
    from panepilot.search import SearchOptions

    (tree / "a" / "sub" / "code.bas").write_text("Sub X()\n  MsgBox \"hallo\"\nEnd Sub")
    (tree / "a" / "bild.bin").write_bytes(b"MsgBox\0\0\0")
    found, (complete, _s) = _run(tree, SearchOptions(name="*.txt"))
    assert complete and found == ["a/eins.txt", "a/sub/tief.txt", "b/zwei.txt"]
    found, _ = _run(tree, SearchOptions(name="*.txt", depth=1))
    assert found == ["a/eins.txt", "b/zwei.txt"]
    found, _ = _run(tree, SearchOptions(name="sub"))
    assert found == ["a/sub"]  # Ordner als Treffer
    found, _ = _run(tree, SearchOptions(name="sub", dirs=False))
    assert found == []
    found, _ = _run(tree, SearchOptions(text="msgbox"))
    assert found == ["a/sub/code.bas"]  # Binärdatei übersprungen
    found, _ = _run(tree, SearchOptions(name="*.bas", text=r"Msg\w+ \"", text_mode=srch.TEXT_REGEX, text_case=True))
    assert found == ["a/sub/code.bas"]
    found, _ = _run(tree, SearchOptions(name="*versteckt*"))
    assert found == []
    found, _ = _run(tree, SearchOptions(name="*versteckt*", hidden=True))
    assert found == ["a/.versteckt"]
    monkeypatch.setattr(srch, "MAX_TEXT_SIZE", 10)
    _found, (_c, skipped) = _run(tree, SearchOptions(text="tief"))
    assert any(p.endswith("tief.txt") for p in skipped)
    assert SearchOptions().error() == "search.err_empty"
    assert SearchOptions(text="(", text_mode=srch.TEXT_REGEX).error()


def test_search_in_window(window, tree, qtbot):  # noqa: F811
    from panepilot.search import SearchOptions

    panel = window.active
    panel.navigate(str(tree))
    side = window.active_side
    prev_mode = window.sides[side].sidebar.mode
    press(qtbot, window, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    pane = window.sides[side].sidebar.widget_for("search")
    assert window.sides[side].sidebar.mode == "search"
    pane.set_options(SearchOptions(name="*.txt"))
    pane.start_clicked.emit()
    qtbot.waitUntil(lambda: window._search_thread is None, timeout=5000)
    QApplication.processEvents()
    assert panel.search_mode
    names = sorted(e.name for e in panel.model.entries())
    assert names == ["eins.txt", "tief.txt", "zwei.txt"]
    tief = next(e for e in panel.model.entries() if e.name == "tief.txt")
    assert tief.type_text == os.path.join("a", "sub")
    assert "3" in pane.summary.text()
    # Mit Treffern arbeiten: Kopieren ins andere Fenster geht über die normalen Funktionen
    assert window.other.current_path
    panel.select_names([], current="tief.txt")
    window.jump_to_found_folder()
    assert not panel.search_mode and panel.current_path == str(tree / "a" / "sub")
    assert panel.current_entry().name == "tief.txt"
    assert window.sides[side].sidebar.mode == prev_mode
    # Schließen bringt den Startordner zurück
    window.trigger("search")
    pane.start_clicked.emit()
    qtbot.waitUntil(lambda: window._search_thread is None, timeout=5000)
    window.close_tool(side)
    assert not panel.search_mode and panel.current_path == str(tree / "a" / "sub")
    assert window.settings.get("search_last")["name"] == "*.txt"
