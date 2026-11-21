"""Tests for 2.2.1: manual search in the choice dialog and for missing films without review."""

from PySide6.QtWidgets import QDialog

from test_mainwindow import window  # noqa: F401
from test_v093 import _open
from test_v190 import _videos, net  # noqa: F401


def test_auto_mode_asks_for_missing_and_manual_choice(window, tmp_path, net, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import dialogs
    from panepilot import moviedialogs as mdl
    from panepilot import netutil
    from panepilot import tags as tg

    window.settings.set("online_review", "auto_empty")
    pane = _open(window, qtbot, _videos(tmp_path))
    items = {it.record.name: it for it in pane.meta_model.items}
    monkeypatch.setattr(netutil, "run_blocking", lambda parent, fn, text, title: (fn(), None))
    monkeypatch.setattr(dialogs, "show_info", lambda *a: None)
    monkeypatch.setattr(dialogs, "confirm", lambda *a, **k: True)
    seen = {"choice": [], "manual": []}
    manual_values = iter([("Ronin", "1998", "8196"), ("Heat", "1995", "")])

    def choice_exec(self):
        seen["choice"].append([b.text() for b in self.findChildren(__import__("PySide6.QtWidgets").QtWidgets.QPushButton)])
        if len(seen["choice"]) == 1:
            return mdl.ChoiceDialog.MANUAL  # Ronin: keiner passt → manuell (TMDb-Nummer)
        self.list.setCurrentRow(0)  # Heat aus der manuellen Suche: ersten Treffer nehmen
        return QDialog.DialogCode.Accepted

    def manual_exec(self):
        seen["manual"].append(self.windowTitle())
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(mdl.ChoiceDialog, "exec", choice_exec)
    monkeypatch.setattr(mdl.ManualSearchDialog, "exec", manual_exec)
    monkeypatch.setattr(mdl.ManualSearchDialog, "values", lambda self: next(manual_values))
    monkeypatch.setattr(mdl.ReviewDialog, "exec", lambda self: (_ for _ in ()).throw(AssertionError("keine Übersicht")))
    window.meta_convert(cv.ONLINE)
    assert "Manuell suchen …" in seen["choice"][0]
    assert items["Ronin (1998).mp4"].value(tg.EXTRA + "themoviedb") == "8196"
    # „Unbekannt.mp4“ wurde nicht gefunden → manuelle Suche „Nicht gefunden (1/1)“; dort Heat gesucht und gewählt
    assert seen["manual"][0] == "Manuell suchen" and seen["manual"][1] == "Nicht gefunden (1/1)"
    assert items["Unbekannt.mp4"].value(tg.EXTRA + "themoviedb") == "949"


def test_missing_skip_and_cancel(window, tmp_path, net, monkeypatch, qtbot):  # noqa: F811
    from panepilot import convert as cv
    from panepilot import dialogs
    from panepilot import moviedialogs as mdl
    from panepilot import tags as tg

    monkeypatch.setattr(dialogs, "show_info", lambda *a: None)
    monkeypatch.setattr(dialogs, "confirm", lambda *a, **k: True)
    window.settings.set("online_review", "auto_all")
    pane = _open(window, qtbot, _videos(tmp_path))
    items = {it.record.name: it for it in pane.meta_model.items}
    titles = []

    def manual_exec(self):
        titles.append(self.windowTitle())
        return mdl.ManualSearchDialog.SKIP

    monkeypatch.setattr(mdl.ChoiceDialog, "exec", lambda self: mdl.ChoiceDialog.SKIP)
    monkeypatch.setattr(mdl.ManualSearchDialog, "exec", manual_exec)
    window.meta_convert(cv.ONLINE)
    assert titles == ["Nicht gefunden (1/1)"]  # Ronin übersprungen → nicht noch einmal gefragt
    assert not items["Unbekannt.mp4"].value(tg.EXTRA + "themoviedb")
    assert items["Heat (1995).mp4"].value(tg.EXTRA + "themoviedb") == "949"
