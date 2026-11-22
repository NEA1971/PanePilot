"""Tests for 2.3: update settings, mouse wheel guard, archive checkbox, Jellyfin-style IDs."""

import datetime as dt
import os

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (QApplication, QComboBox, QListWidget, QScrollArea, QSpinBox, QVBoxLayout,
                               QWidget)

from test_mainwindow import window  # noqa: F401


# --- Updates ---------------------------------------------------------------------------------------------
def test_update_modes(window):  # noqa: F811
    from panepilot import updatecheck as uc
    from panepilot.settingsdialog import SettingsDialog

    s = window.settings
    assert uc.check_mode(s) == uc.NEVER and not uc.due_today(s)  # Vorgabe wie bisher: aus
    dlg = SettingsDialog(window)
    assert dlg.update_mode["never"].isChecked() and dlg.update_old["ask"].isChecked()
    dlg.update_mode["start"].setChecked(True)
    dlg.update_old["trash"].setChecked(True)
    dlg.accept()
    assert uc.check_mode(s) == uc.START and s.get("update_old_policy") == "trash"
    s.set("update_last_check", dt.date.today().isoformat())
    assert uc.due_today(s)  # bei jedem Start – auch wenn heute schon geprüft
    uc.set_check_mode(s, uc.DAILY)
    assert not uc.due_today(s) and s.get("update_check") is True
    assert SettingsDialog(window).update_mode["daily"].isChecked()


def _old_file(window, tmp_path, monkeypatch, policy):
    old, new = tmp_path / "PanePilot-1.AppImage", tmp_path / "PanePilot-2.AppImage"
    old.write_bytes(b"a")
    new.write_bytes(b"b")
    monkeypatch.setenv("APPIMAGE", str(new))
    window.settings.set("update_old_file", {"old": str(old), "new": str(new)})
    window.settings.set("update_old_policy", policy)
    return old


def test_old_file_policy(window, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import dialogs, fileops
    from panepilot import updatecheck as uc

    asked, trashed = [], []
    monkeypatch.setattr(dialogs, "confirm", lambda *a, **k: asked.append(1) or False)
    monkeypatch.setattr(fileops, "move_to_trash", trashed.append)
    old = _old_file(window, tmp_path, monkeypatch, "keep")
    uc.offer_old_file_removal(window)
    assert not asked and not trashed and window.settings.get("update_old_file") is None
    old = _old_file(window, tmp_path, monkeypatch, "trash")
    uc.offer_old_file_removal(window)
    assert not asked and trashed == [str(old)]
    _old_file(window, tmp_path, monkeypatch, "ask")
    uc.offer_old_file_removal(window)
    assert asked == [1] and len(trashed) == 1


def test_old_file_hidden_for_packages(window, monkeypatch, tmp_path):  # noqa: F811
    from test_v2000 import _fake_package

    from panepilot.settingsdialog import SettingsDialog

    assert not SettingsDialog(window).old_box.isHidden()
    _fake_package(monkeypatch, tmp_path, "deb")
    assert SettingsDialog(window).old_box.isHidden()


# --- Mausrad ----------------------------------------------------------------------------------------------
def _wheel(widget, dy=-120, modifiers=Qt.KeyboardModifier.NoModifier):
    pos = QPointF(widget.rect().center())
    ev = QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)


def _page(window):  # noqa: F811
    area = QScrollArea()
    inner = QWidget()
    lay = QVBoxLayout(inner)
    combo = QComboBox(inner)
    combo.addItems(["eins", "zwei", "< entfernen >"])
    spin = QSpinBox(inner)
    lst = QListWidget(inner)
    lst.addItems([f"Zeile {i}" for i in range(60)])
    lst.setFixedHeight(80)
    short = QListWidget(inner)
    short.addItems(["a"])
    short.setFixedHeight(80)
    lay.addWidget(combo)
    lay.addWidget(spin)
    lay.addWidget(lst)
    lay.addWidget(short)
    lay.addWidget(QWidget(inner), 1)
    inner.setMinimumHeight(1500)
    area.setWidget(inner)
    area.setWidgetResizable(True)
    area.resize(300, 300)
    area.show()
    QApplication.processEvents()
    return area, combo, spin, lst, short


def test_wheel_guard(window):  # noqa: F811
    area, combo, spin, lst, short = _page(window)
    page = area.verticalScrollBar()
    # zugeklappte Auswahlliste: Wert bleibt, die Seite rollt
    _wheel(combo)
    assert combo.currentIndex() == 0 and page.value() > 0
    assert combo.focusPolicy() == Qt.FocusPolicy.StrongFocus  # das Rad gibt keinen Fokus
    page.setValue(0)
    _wheel(spin)
    assert spin.value() == 0 and page.value() > 0
    # innere Liste rollt nur sich selbst – auch am Ende nicht weiter
    page.setValue(0)
    bar = lst.verticalScrollBar()
    for _ in range(80):
        _wheel(lst.viewport())
    assert bar.value() == bar.maximum() and page.value() == 0
    for _ in range(3):
        _wheel(lst.verticalScrollBar())
    assert page.value() == 0
    # Liste ohne Rollbalken: dann rollt die Seite
    _wheel(short.viewport())
    assert page.value() > 0
    # Strg+Rad unverändert durchgereicht
    page.setValue(0)
    _wheel(lst.viewport(), modifiers=Qt.KeyboardModifier.ControlModifier)
    area.close()


def test_meta_fieldbox_wheel(window):  # noqa: F811
    from panepilot.metawizard import FieldBox

    area = QScrollArea()
    box = FieldBox("title")
    box.addItems(["Alt", "< entfernen >"])
    area.setWidget(box)
    area.show()
    QApplication.processEvents()
    seen = []
    box.activated.connect(seen.append)
    _wheel(box)
    assert box.currentIndex() == 0 and not seen  # kein „< entfernen >“ mehr durchs Rollen
    area.close()


# --- Archive ----------------------------------------------------------------------------------------------
def test_archive_checkbox(window):  # noqa: F811
    from panepilot.settingsdialog import SettingsDialog

    window.settings.set("archive_open", "app")  # Wahl aus 2.2 wird übernommen
    dlg = SettingsDialog(window)
    assert dlg.archive_app.isChecked()
    dlg.archive_app.setChecked(False)
    dlg.accept()
    assert window.settings.get("archive_open") == "panepilot"
    assert window.sides["left"].panel.open_archives_inside


# --- Kennungen wie Jellyfin -------------------------------------------------------------------------------
def test_ids_from_name():
    from panepilot import moviedb as md

    assert md.all_ids_from_name("Alien (1979) [imdbid-tt0078748]") == ("tt0078748", "", "")
    assert md.all_ids_from_name("Heat (1995) (tmdbid-949)") == ("", "949", "")
    assert md.all_ids_from_name("Columbo {tmdb-873} [tvdb-73584] (imdb-tt1466074)") == ("tt1466074", "873", "73584")
    assert md.all_ids_from_name("Film [tt0407362]") == ("", "", "")  # bloße Nummer wie bei Jellyfin nicht
    assert md.title_year("Heat (1995) (tmdbid-949).mkv") == ("Heat", "1995")
    assert md.title_year("Heat (tmdbid-949).mkv") == ("Heat", "")


def test_episode_ids(tmp_path):
    from panepilot import moviedb as md

    ref = md.episode_ref(str(tmp_path / "Columbo (1971) [imdbid-tt0066626]" / "Staffel 1" / "Columbo S01E02.mkv"))
    assert (ref.series, ref.season, ref.episode, ref.imdb, ref.tmdb) == ("Columbo", 1, 2, "tt0066626", "")
    ref = md.episode_ref(str(tmp_path / "Columbo" / "Season 01 [tvdbid-73584]" / "S01E01.mkv"))
    assert ref.tvdb == "73584" and ref.series == "Columbo"
    ref = md.episode_ref(str(tmp_path / "Columbo" / "Columbo S01E03 [imdbid-tt0065189].mkv"))
    assert ref.imdb == "tt0065189"
    ref = md.episode_ref(str(tmp_path / "Columbo {tmdbid-873}" / "Columbo S01E01 [imdbid-tt0065189].mkv"))
    assert ref.tmdb == "873" and ref.imdb == "tt0065189"


def test_find_external(monkeypatch):
    from panepilot import moviedb as md

    svc = md.Tmdb("x" * 32)
    answers = {
        ("tt0066626", "imdb_id"): {"tv_results": [{"id": 873}]},
        ("tt0065189", "imdb_id"): {"tv_episode_results": [{"id": 1, "show_id": 873}]},
        ("73584", "tvdb_id"): {"tv_results": [{"id": 873}]},
        ("81189", "tvdb_id"): {"movie_results": [{"id": 348}]},
    }
    monkeypatch.setattr(svc, "_get", lambda path, **p: answers.get((path.rsplit("/", 1)[-1], p["external_source"]), {}))
    assert svc.find_external("tt0066626", "imdb_id", tv=True) == "873"
    assert svc.find_external("tt0065189", "imdb_id", tv=True) == "873"  # Kennung einer Folge → Serie
    assert svc.find_external("73584", "tvdb_id", tv=True) == "873"
    assert svc.find_external("81189", "tvdb_id") == "348" and svc.find_external("1", "tvdb_id") == ""


def test_movie_ids_from_folder(tmp_path):
    from panepilot import moviedialogs as mdl

    class Rec:
        def __init__(self, path):
            self.path, self.name = path, os.path.basename(path)

    class Item:
        def __init__(self, path):
            self.record = Rec(path)
            self.display_name = self.record.name

        def value(self, key):
            return ""

        def readonly(self, key):
            return False

    job = mdl.make_job(Item(str(tmp_path / "Alien (1979) [imdbid-tt0078748]" / "Alien.mkv")))
    assert job.imdb == "tt0078748" and job.title == "Alien"
    job = mdl.make_job(Item(str(tmp_path / "Filme {tmdb-1}" / "Heat (1995) (tmdbid-949).mkv")))
    assert job.tmdb == "949"  # die Datei geht vor
    job = mdl.make_job(Item(str(tmp_path / "X [tvdbid-81189]" / "X.mkv")))
    assert job.tvdb == "81189" and not job.imdb and not job.tmdb


def test_series_lookup_by_imdb(monkeypatch):
    from panepilot import moviedb as md
    from panepilot import moviedialogs as mdl

    svc = md.Tmdb("x" * 32)
    calls = []
    monkeypatch.setattr(svc, "find_external", lambda ident, src, tv=False: calls.append((ident, src, tv)) or "873")
    monkeypatch.setattr(svc, "search_tv", lambda *a: (_ for _ in ()).throw(AssertionError("keine Suche")))
    monkeypatch.setattr(svc, "episode", lambda tv, s, e: md.Movie(md.SOURCE_TMDB, tmdb=tv, title=f"{s}/{e}"))
    group = mdl.SeriesGroup("Columbo", "", "", imdb="tt0066626")
    job = mdl.Job(item=None, title="Columbo", ep=md.EpisodeRef("Columbo", "", 1, 2), group=group)
    mdl.LookupThread(svc, [job])._episode(job)
    assert group.tmdb == "873" and job.movie.title == "1/2" and calls == [("tt0066626", "imdb_id", True)]


def test_wheel_guard_accepts_at_end(window):  # noqa: F811
    """Echte (spontane) Mausrad-Ereignisse reicht Qt an das übergeordnete Fenster weiter, wenn sie nicht
    angenommen sind – am Ende der Liste muss das Ereignis daher als erledigt markiert sein (2.3.1)."""
    area, combo, spin, lst, short = _page(window)
    bar = lst.verticalScrollBar()
    bar.setValue(bar.maximum())
    pos = QPointF(lst.viewport().rect().center())
    ev = QWheelEvent(pos, QPointF(lst.viewport().mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, -120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    ev.ignore()
    QApplication.sendEvent(lst.viewport(), ev)
    assert ev.isAccepted() and bar.value() == bar.maximum()
    ev2 = QWheelEvent(QPointF(5, 5), QPointF(combo.mapToGlobal(QPoint(5, 5))), QPoint(0, 0), QPoint(0, -120),
                      Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
    ev2.ignore()
    QApplication.sendEvent(combo, ev2)
    assert ev2.isAccepted() and combo.currentIndex() == 0
    area.close()
