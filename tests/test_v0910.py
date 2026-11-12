"""Tests für v0.9.10: Sprachdateien, neues Einstellungsfenster, neue Knöpfe."""

import datetime as dt
import json

from PySide6.QtWidgets import QApplication, QFileDialog

from test_mainwindow import window  # noqa: F401


# --- Sprachdateien (J-100 ff.) -------------------------------------------------------------------------
def test_bundled_language_keeps_only_changes():
    from panepilot import i18n

    original = i18n.read_bundled("de")
    i18n.save_user_language("de", "Deutsch", "", {"menu.file": "&Akten", "menu.edit": original["menu.edit"]})
    info = i18n.languages()["de"]
    assert info.user and not info.own and info.name == "Deutsch"
    assert i18n.read_user("de") == {"menu.file": "&Akten"}  # nur die Änderung steht in der Datei
    merged = i18n.read_language("de")
    assert merged["menu.file"] == "&Akten" and merged["menu.edit"] == original["menu.edit"]
    assert len(merged) == len(original)  # neue Texte späterer Versionen kämen weiter an
    assert i18n.remove_user_language("de")
    assert not i18n.languages()["de"].user
    assert i18n.read_language("de")["menu.file"] == original["menu.file"]


def test_export_and_import(tmp_path):
    from panepilot import i18n
    from panepilot.settingsdialog import next_language_export_name

    i18n.save_user_language("frk", "Fränkisch", "de", {"menu.file": "Dadei!"})
    folder = i18n.user_folder()
    name = next_language_export_name(folder, "frk", dt.date(2026, 11, 9))
    assert name == "PanePilot_Sprache-frk_2026-11-09a.json"
    i18n.export_language("frk", folder / name)
    assert next_language_export_name(folder, "frk", dt.date(2026, 11, 9)).endswith("09b.json")
    data = json.loads((folder / name).read_text(encoding="utf-8"))
    assert data["_meta"]["code"] == "frk" and data["menu.file"] == "Dadei!"
    assert len(data) - 1 == len(i18n.read_bundled("de"))  # vollständig
    # Ein Export im Sprachordner wird nicht als Sprache geladen
    assert i18n.languages()["frk"].path.name == "frk.json"
    # Import: falsche Platzhalter und unbekannte Texte werden gemeldet, nicht übernommen
    data["status.counts"] = "kaputt"
    data["gibt.es.nicht"] = "x"
    src = tmp_path / "PanePilot_Sprache-frk_2026-11-09a.json"
    src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    res = i18n.read_import(src)
    assert res.code == "frk" and res.bad_placeholders == ["status.counts"] and res.unknown == 1
    assert res.strings["menu.file"] == "Dadei!" and "status.counts" not in res.strings
    bad = tmp_path / "x.json"
    bad.write_text("{kein json", encoding="utf-8")
    try:
        i18n.read_import(bad)
        raise AssertionError("ValueError erwartet")
    except ValueError:
        pass


def test_settings_language_buttons(window, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import i18n
    from panepilot.settingsdialog import SettingsDialog

    infos = []
    monkeypatch.setattr("panepilot.dialogs.show_info", lambda *a, **k: infos.append(a[2]))
    monkeypatch.setattr("panepilot.settingsdialog.confirm", lambda *a, **k: True)
    dlg = SettingsDialog(window)
    dlg.lang_box.setCurrentIndex(dlg.lang_box.findData("en"))
    assert dlg.btn_lang_edit.isEnabled() and dlg.btn_lang_export.isEnabled()
    assert not dlg.btn_lang_reset.isEnabled()  # keine eigenen Änderungen
    # Export in den vorgeschlagenen Ordner
    target = tmp_path / "en.json"
    seen = {}

    def fake_save(parent, title, path, filt):
        seen["path"] = path
        return str(target), filt
    monkeypatch.setattr(QFileDialog, "getSaveFileName", fake_save)
    dlg._export_language()
    assert "Sprachen" in seen["path"] and "PanePilot_Sprache-en_" in seen["path"]
    assert json.loads(target.read_text(encoding="utf-8"))["_meta"]["code"] == "en"
    # Import einer geänderten Datei als Änderung an Englisch
    data = json.loads(target.read_text(encoding="utf-8"))
    data["menu.file"] = "&Files"
    target.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(target), ""))
    dlg._import_language()
    assert i18n.read_user("en") == {"menu.file": "&Files"}
    assert dlg.btn_lang_reset.isEnabled() and dlg.btn_lang_reset.text() == "Auf Original zurücksetzen"
    dlg._reset_language()
    assert not i18n.languages()["en"].user
    # Eigene Sprache: Knopf heißt „Sprache löschen“
    i18n.save_user_language("bar", "Boarisch", "de", {"menu.file": "Dadei"})
    dlg._refresh_languages("bar")
    assert dlg.btn_lang_reset.text() == "Sprache löschen"
    dlg._reset_language()
    assert "bar" not in i18n.languages()
    assert dlg.lang_box.currentData() == "system"
    dlg.reject()


def test_editor_for_german(window):  # noqa: F811
    from panepilot import i18n
    from panepilot.settingsdialog import LanguageEditor

    ed = LanguageEditor(window, "de")  # Deutsch ist jetzt bearbeitbar
    assert ed.bundled
    assert ed.table.horizontalHeaderItem(1).text() == "Original"
    row = next(r for r in range(ed.table.rowCount()) if ed.table.item(r, 0).text() == "menu.file")
    assert ed.table.item(row, 2).text() == ed.table.item(row, 1).text()  # vorbelegt mit dem Original
    ed.table.item(row, 2).setText("&Akte")
    assert "1 von" in ed.counter.text()
    ed.only_missing.setChecked(True)
    assert sum(not ed.table.isRowHidden(r) for r in range(ed.table.rowCount())) == 1
    ed.accept()
    assert i18n.read_user("de") == {"menu.file": "&Akte"}
    # Zurück zum Original-Text → eigene Datei verschwindet
    ed = LanguageEditor(window, "de")
    row = next(r for r in range(ed.table.rowCount()) if ed.table.item(r, 0).text() == "menu.file")
    ed.table.item(row, 2).setText("")  # leer = Original
    ed.accept()
    assert not i18n.languages()["de"].user


# --- Einstellungsfenster (J-120 ff.) ---------------------------------------------------------------------
def test_settings_layout_and_display_toggles(window):  # noqa: F811
    from panepilot.settingsdialog import SettingsDialog

    dlg = SettingsDialog(window)
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == ["Allgemein", "Dateiansicht", "Meta-Wizard"]
    general = dlg.pages["general"]
    assert [general.nav.item(i).text() for i in range(general.nav.count())] == ["Sprache", "Sicherung", "Darstellung", "Updates"]
    assert [g.title() for g in dlg.pages["view"].groups] == ["Größeneinheit", "Spalten"]
    assert [g.title() for g in dlg.pages["meta"].groups] == ["ReplayGain"]
    dlg.resize(900, 500)
    dlg.show()
    QApplication.processEvents()
    general.nav.setCurrentRow(1)
    QApplication.processEvents()
    assert general.scroll.verticalScrollBar().value() > 0
    # Darstellung: gleiche Wirkung wie im Menü „Ansicht“
    was = window.qactions["toggle_fkeybar"].isChecked()
    assert dlg.display_boxes["toggle_fkeybar"].isChecked() == was
    dlg.display_boxes["toggle_fkeybar"].setChecked(not was)
    dlg.accept()
    assert window.qactions["toggle_fkeybar"].isChecked() == (not was)
    assert window.fkey_bar.isVisibleTo(window) == (not was)


def test_settings_menu_in_file_menu(window):  # noqa: F811
    bar = window.menuBar()
    titles = [a.text() for a in bar.actions()]
    assert "Einstellungen" not in titles
    file_menu = window.settings_menu.parentWidget()
    assert file_menu.title() == "&Datei"
    entries = [a.text() for a in file_menu.actions() if not a.isSeparator()]
    assert entries[-2:] == ["Einstellungen", window.qactions["quit"].text()]
    sub = [a.text() for a in window.settings_menu.actions() if not a.isSeparator()]
    assert sub[0] == "Sprache" and window.qactions["settings_dialog"].text() in sub


# --- Knöpfe (J-140) --------------------------------------------------------------------------------------
def test_new_icons(qapp):
    from panepilot import toolicons as ti

    for aid in ("search", "checksums", "multi_rename", "rename_undo", "settings_dialog"):
        assert not ti.action_icon(aid).isNull(), aid
    assert ti.action_icon("checksums").cacheKey() != ti.action_icon("multi_rename").cacheKey()
