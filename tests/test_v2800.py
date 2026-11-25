"""v2.8: In Archive schreiben; echte Konflikterkennung bei gespeicherten Abgleichen."""

import os
import shutil
import tarfile
import time
import zipfile

import pytest
from PySide6.QtCore import Qt

from test_mainwindow import window  # noqa: F401
from test_v2200 import _make_tgz, _make_zip

has_7z = pytest.mark.skipif(not (shutil.which("7z") or shutil.which("7zz") or shutil.which("7za")),
                            reason="7-Zip fehlt")


def _names(path):
    if str(path).endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            return sorted(z.namelist())
    with tarfile.open(path) as tf:
        return sorted(m.name + ("/" if m.isdir() else "") for m in tf.getmembers())


# --- Backend ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["zip", "tgz"])
def test_apply_add_delete_rename_mkdir(tmp_path, kind):  # L-3800–L-3802
    from panepilot import archivefs as af
    from panepilot import archivewrite as aw

    if kind == "zip":
        arc = _make_zip(tmp_path / "a.zip")
    else:
        arc = _make_tgz(tmp_path / "a.tar.gz", tmp_path / "src")
    (tmp_path / "neu.txt").write_text("NEU")
    (tmp_path / "ordner" / "x").mkdir(parents=True)
    (tmp_path / "ordner" / "x" / "y.txt").write_text("Y")
    os.chmod(arc, 0o640)
    aw.apply(af.read_index(str(arc)), aw.Plan(add=[(str(tmp_path / "neu.txt"), "neu.txt"),
                                                   (str(tmp_path / "ordner"), "tief/ordner")]))
    names = _names(arc)
    assert "neu.txt" in names and "tief/ordner/x/y.txt" in names
    aw.apply(af.read_index(str(arc)), aw.Plan(mkdir=["leer2/innen"]))
    first = "Urlaub" if kind == "zip" else "doc"
    aw.apply(af.read_index(str(arc)), aw.Plan(rename=[(first, "Umbenannt")]))
    aw.apply(af.read_index(str(arc)), aw.Plan(delete=["neu.txt", "tief"]))
    idx = af.read_index(str(arc))
    assert idx.item("neu.txt") is None and idx.item("tief") is None
    assert idx.item("leer2/innen") is not None and idx.item(first) is None and idx.item("Umbenannt").is_dir
    assert oct(os.stat(arc).st_mode & 0o777) == "0o640"  # Rechte bleiben
    assert not [n for n in os.listdir(tmp_path) if n.endswith(".pp-tmp")]
    # Ersetzen einer vorhandenen Datei: nur einmal im Archiv, mit neuem Inhalt
    (tmp_path / "b.txt").write_text("ERSATZ")
    (tmp_path / "readme.txt").write_text("ERSATZ")
    name = "readme.txt" if kind == "zip" else "b.txt"
    aw.apply(af.read_index(str(arc)), aw.Plan(add=[(str(tmp_path / name), name)]))
    assert _names(arc).count(name) == 1
    if kind == "zip":
        with zipfile.ZipFile(arc) as z:
            assert z.read("readme.txt") == b"ERSATZ"
            assert "../boese.txt" not in z.namelist()  # Pfade nach außen fallen weg


def test_failure_keeps_original(tmp_path, monkeypatch):  # L-3802
    from panepilot import archivefs as af
    from panepilot import archives as ar
    from panepilot import archivewrite as aw

    arc = _make_zip(tmp_path / "a.zip")
    before = arc.read_bytes()
    (tmp_path / "gross.bin").write_bytes(b"x" * 3_000_000)
    calls = {"n": 0}

    def cancel():
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(ar.Cancelled):
        aw.apply(af.read_index(str(arc)), aw.Plan(add=[(str(tmp_path / "gross.bin"), "gross.bin")]),
                 cancelled=cancel)
    assert arc.read_bytes() == before and not [n for n in os.listdir(tmp_path) if n.endswith(".pp-tmp")]
    (tmp_path / "x.rar").write_bytes(b"Rar!")
    idx = af.ArchiveIndex(str(tmp_path / "x.rar"), ar.RAR)
    assert "RAR" in aw.writable(idx)
    monkeypatch.setattr(ar, "seven_zip", lambda: None)
    enc = af.ArchiveIndex(str(arc), ar.ZIP, encrypted=True)
    assert "7-Zip" in aw.writable(enc)


@has_7z
def test_7z_backend(tmp_path):  # L-3800, L-3804
    from panepilot import archivefs as af
    from panepilot import archives as ar
    from panepilot import archivewrite as aw

    src = tmp_path / "src"
    (src / "d").mkdir(parents=True)
    (src / "d" / "a.txt").write_text("A")
    arc = tmp_path / "t.7z"
    subprocess_run([ar.seven_zip(), "a", "-pgeheim", str(arc), "d"], src)
    idx = af.read_index(str(arc), "geheim")
    idx.password = "geheim"
    (tmp_path / "b.txt").write_text("B")
    aw.apply(idx, aw.Plan(add=[(str(tmp_path / "b.txt"), "d/b.txt")]))
    aw.apply(af.read_index(str(arc), "geheim"), aw.Plan(rename=[("d", "e")]))
    new = af.read_index(str(arc), "geheim")
    assert new.item("e/b.txt") is not None and new.item("e/a.txt") is not None and new.item("d") is None
    assert new.item("e/b.txt").encrypted
    # verschlüsseltes ZIP (AES) über 7-Zip mit dem eingegebenen Passwort
    zarc = tmp_path / "geheim.zip"
    subprocess_run([ar.seven_zip(), "a", "-tzip", "-pgeheim", "-mem=AES256", str(zarc), "d"], src)
    zidx = af.read_index(str(zarc))
    assert zidx.encrypted and aw.engine(zidx) == "7z"
    zidx.password = "geheim"
    aw.apply(zidx, aw.Plan(add=[(str(tmp_path / "b.txt"), "b.txt")], delete=["d/a.txt"]))
    z2 = af.read_index(str(zarc))
    assert z2.item("b.txt") is not None and z2.item("b.txt").encrypted and z2.item("d/a.txt") is None


def subprocess_run(args, cwd):
    import subprocess

    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


# --- Bedienung ------------------------------------------------------------------------------------------------
@pytest.fixture
def arc_panels(window, tree):  # noqa: F811
    arc = _make_zip(tree / "a" / "Fotos.zip")
    window.settings.set("confirm_copy_move", False)
    left, right = window.sides["left"].panel, window.sides["right"].panel
    left.navigate(str(arc))
    right.navigate(str(tree / "b"))
    assert left.in_archive
    return arc, left, right


def test_copy_and_move_into_archive(window, tree, arc_panels, qtbot, monkeypatch):  # noqa: F811  L-3801, L-3803
    arc, left, right = arc_panels
    (tree / "b" / "neu.txt").write_text("neu")
    (tree / "b" / "readme.txt").write_text("anders")
    right.refresh()
    window.set_active_side("right")
    right.select_names(["neu.txt"], current="neu.txt")
    window.trigger("copy")  # F5 ins Archiv
    assert "neu.txt" in _names(arc) and (tree / "b" / "neu.txt").exists()
    assert "neu.txt" in [e.name for e in left.model.entries()]  # Fenster mit dem Archiv neu gelesen
    # gleicher Name: dieselbe Rückfrage wie beim Kopieren
    from panepilot import dialogs
    from panepilot.fileops import ConflictDecision

    asked = []

    def fake_exec(self):
        asked.append(self.findChildren(type(self.name_edit))[0].text())
        self.decision = ConflictDecision("rename", "readme-2.txt")
        return 1

    monkeypatch.setattr(dialogs.ConflictDialog, "exec", fake_exec)
    right.select_names(["readme.txt"], current="readme.txt")
    window.trigger("copy")
    assert asked == ["readme-2.txt"]
    with zipfile.ZipFile(arc) as z:
        assert z.read("readme.txt") == b"hallo" and z.read("readme-2.txt") == b"anders"
    # F6 hinein: Original in den Papierkorb
    trashed = []
    monkeypatch.setattr(window.ops, "start", lambda kind, paths, *a, **k: trashed.append((kind, paths)))
    right.select_names(["neu.txt"], current="neu.txt")
    monkeypatch.setattr(dialogs.ConflictDialog, "exec",
                        lambda self: setattr(self, "decision", ConflictDecision("overwrite")) or 1)
    window.trigger("move")
    assert trashed and trashed[0][0] == "trash" and trashed[0][1] == [str(tree / "b" / "neu.txt")]


def test_new_folder_rename_delete_in_archive(window, arc_panels, monkeypatch):  # noqa: F811  L-3801
    arc, left, _right = arc_panels
    window.set_active_side("left")
    monkeypatch.setattr("panepilot.mainwindow.ask_text", lambda *a, **k: "Neu")
    window.trigger("new_folder")
    assert "Neu/" in _names(arc) and left.current_entry().name == "Neu"
    left.select_names(["readme.txt"], current="readme.txt")
    monkeypatch.setattr("panepilot.dialogs.ask_text", lambda *a, **k: "liesmich.txt")
    window.trigger("rename")
    assert "liesmich.txt" in _names(arc) and "readme.txt" not in _names(arc)
    asked = []
    monkeypatch.setattr("panepilot.dialogs.confirm", lambda parent, title, text, **k: asked.append(text) or True)
    left.select_names(["Urlaub", "liesmich.txt"])
    window.trigger("delete")  # F8 → endgültig, mit Rückfrage
    assert asked and "endgültig" in asked[0] and "Papierkorb" in asked[0]
    names = _names(arc)
    assert not [n for n in names if n.startswith("Urlaub")] and "liesmich.txt" not in names
    assert sorted(e.name for e in left.model.entries() if not e.is_parent) == ["Neu", "leer"]


def test_move_out_of_archive(window, tree, arc_panels, qtbot):  # noqa: F811  L-3801
    arc, left, _right = arc_panels
    window.set_active_side("left")
    left.select_names(["readme.txt"], current="readme.txt")
    window.trigger("move")  # F6 heraus = entpacken, dann im Archiv löschen
    qtbot.waitUntil(lambda: "readme.txt" not in _names(arc), timeout=5000)
    assert (tree / "b" / "readme.txt").read_text() == "hallo"


def test_drop_into_archive(window, tree, arc_panels):  # noqa: F811
    arc, left, _right = arc_panels
    (tree / "b" / "gezogen.txt").write_text("g")
    window._on_drop([str(tree / "b" / "gezogen.txt")], str(arc) + "/Urlaub", Qt.DropAction.CopyAction)
    assert "Urlaub/gezogen.txt" in _names(arc)


def test_rar_stays_read_only(window, tree, monkeypatch):  # noqa: F811
    from panepilot import archivefs as af
    from panepilot import archives as ar

    infos = []
    monkeypatch.setattr("panepilot.archivecontrol.show_info", lambda *a: infos.append(a[2]))
    idx = af.ArchiveIndex(str(tree / "x.rar"), ar.RAR)
    assert not window._archive_writable(idx) and "RAR" in infos[-1]


def test_writeback(window, tree, arc_panels, monkeypatch):  # noqa: F811  L-3805
    import panepilot.util as util

    arc, left, _right = arc_panels
    opened = []
    monkeypatch.setattr(util, "open_with_default_app", lambda p: opened.append(p) or True)
    window.set_active_side("left")
    left.select_names(["readme.txt"], current="readme.txt")
    window.archive_open(left, left.current_entry())
    path = opened[0]
    answers = []
    monkeypatch.setattr("panepilot.dialogs.confirm", lambda parent, title, text, **k: answers.append(text) or
                        len(answers) > 1)
    window._check_writeback()
    assert answers == []  # nichts geändert, nichts gefragt
    with open(path, "w") as fh:
        fh.write("geändert")
    os.utime(path, (time.time() + 5, time.time() + 5))
    window._check_writeback()  # Nein
    with zipfile.ZipFile(arc) as z:
        assert z.read("readme.txt") == b"hallo"
    window._check_writeback()
    assert len(answers) == 1  # bis zur nächsten Änderung keine neue Frage
    os.utime(path, (time.time() + 10, time.time() + 10))
    window._check_writeback()  # Ja
    with zipfile.ZipFile(arc) as z:
        assert z.read("readme.txt") == "geändert".encode()
    assert "readme.txt" in answers[-1] and "Fotos.zip" in answers[-1]


# --- Konflikterkennung --------------------------------------------------------------------------------------------
def _w(path, text, when):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)
    os.utime(path, (when, when))


def test_state_two_way(tmp_path):  # L-3810–L-3813
    from panepilot import folderdiff as fd
    from panepilot import syncstate as ss

    left, right = str(tmp_path / "L"), str(tmp_path / "R")
    t0 = time.time() - 10000
    for side in (left, right):
        _w(f"{side}/a.txt", "a", t0)
        _w(f"{side}/b.txt", "b", t0)
        _w(f"{side}/c.txt", "c", t0)
        _w(f"{side}/d/x.txt", "x", t0)
        _w(f"{side}/e.txt", "e", t0)
    opts = fd.Options(direction=fd.BOTH)
    ss.save("Profil", left, right, fd.scan(left, right, opts))
    assert ss.load("Profil", left, "/anders") is None
    # a: links geändert, aber mit älterer Uhrzeit → links gewinnt trotzdem
    _w(f"{left}/a.txt", "a neu", t0 - 5000)
    # b: beide geändert → Konflikt
    _w(f"{left}/b.txt", "b links", t0 + 100)
    _w(f"{right}/b.txt", "b rechts", t0 + 200)
    # c: rechts gelöscht → links auch löschen; d/: links ganz gelöscht → rechts löschen
    os.unlink(f"{right}/c.txt")
    shutil.rmtree(f"{left}/d")
    # e: links gelöscht, rechts geändert → Konflikt
    os.unlink(f"{left}/e.txt")
    _w(f"{right}/e.txt", "e neu", t0 + 300)
    # f: neu seit dem letzten Abgleich → wie bisher
    _w(f"{right}/f.txt", "f", t0)
    entries = fd.scan(left, right, opts)
    n = ss.apply(entries, ss.load("Profil", left, right), opts)
    by = {e.rel: e for e in entries}
    assert (by["a.txt"].status, by["a.txt"].action) == (fd.LEFT_NEWER, fd.TO_RIGHT)
    assert by["a.txt"].since == ("left_changed",)
    assert (by["b.txt"].status, by["b.txt"].action) == (fd.BOTH_CHANGED, fd.NONE)
    assert (by["c.txt"].status, by["c.txt"].action) == (fd.RIGHT_DELETED, fd.DEL_LEFT)
    assert (by["d"].status, by["d"].action) == (fd.LEFT_DELETED, fd.DEL_RIGHT)
    assert (by["d/x.txt"].status, by["d/x.txt"].action) == (fd.LEFT_DELETED, fd.DEL_RIGHT)
    assert (by["e.txt"].status, by["e.txt"].action) == (fd.BOTH_CHANGED, fd.NONE)
    assert (by["f.txt"].status, by["f.txt"].action) == (fd.RIGHT_ONLY, fd.TO_LEFT) and by["f.txt"].since == ()
    assert n == 2 and fd.summary_counts(entries)["conflict"] == 2
    # Ohne Stand (erster Lauf): wie bisher nach der Uhrzeit
    plain = {e.rel: e for e in fd.scan(left, right, opts)}
    assert plain["a.txt"].status == fd.RIGHT_NEWER and plain["c.txt"].action == fd.TO_RIGHT


def test_state_one_way_target_changed(tmp_path):  # L-3814
    from panepilot import folderdiff as fd
    from panepilot import syncstate as ss

    left, right = str(tmp_path / "L"), str(tmp_path / "R")
    t0 = time.time() - 10000
    for side in (left, right):
        _w(f"{side}/a.txt", "a", t0)
        _w(f"{side}/b.txt", "b", t0)
    for mirror in (False, True):
        opts = fd.Options(direction=fd.LR, mirror=mirror)
        ss.save("P", left, right, fd.scan(left, right, opts))
        _w(f"{right}/a.txt", "rechts bearbeitet", t0 - 100)  # Ziel geändert (sogar älter)
        _w(f"{left}/b.txt", "b neu", t0 + 50)
        entries = fd.scan(left, right, opts)
        ss.apply(entries, ss.load("P", left, right), opts)
        by = {e.rel: e for e in entries}
        assert (by["a.txt"].status, by["a.txt"].action) == (fd.CONFLICT, fd.NONE)
        assert by["a.txt"].since == ("right_changed",)
        assert by["b.txt"].action == fd.TO_RIGHT
        # Umstellen der Zeile ist möglich
        assert fd.allowed(by["a.txt"], fd.TO_RIGHT)
        _w(f"{right}/a.txt", "a", t0)
        _w(f"{left}/b.txt", "b", t0)


def test_sync_pane_uses_state(window, tmp_path, monkeypatch):  # noqa: F811  L-3810, L-3816
    from panepilot import folderdiff as fd
    from panepilot import netutil
    from panepilot import syncmode as sm
    from panepilot import syncprofiles as sp
    from panepilot import syncstate as ss

    monkeypatch.setattr(netutil, "run_blocking", lambda parent, fn, text, title: (fn(), None))
    left, right = str(tmp_path / "L"), str(tmp_path / "R")
    t0 = time.time() - 10000
    for side in (left, right):
        _w(f"{side}/a.txt", "a", t0)
        _w(f"{side}/b.txt", "b", t0)
    pane = sm.SyncPane(window)
    pane.set_paths(left, right)
    pane.rb_both.setChecked(True)
    monkeypatch.setattr(sm.QInputDialog, "getText", lambda *a, **k: ("Mein Abgleich", True))
    pane.save_profile()
    assert pane.compare()
    _w(f"{left}/c.txt", "c", t0)
    assert pane.compare()
    monkeypatch.setattr(sm, "confirm", lambda *a, **k: True)
    infos = []
    monkeypatch.setattr(sm, "show_info", lambda *a: infos.append(a[2]))
    monkeypatch.setattr(sm, "show_error", lambda *a: infos.append(a[2]))
    pane.start()  # erster Lauf → Stand wird gemerkt
    assert ss.load("Mein Abgleich", left, right) is not None
    _w(f"{left}/b.txt", "b links", t0 + 10)
    _w(f"{right}/b.txt", "b rechts", t0 + 20)
    _w(f"{left}/a.txt", "a neu", t0 - 50)
    assert pane.compare()
    by = {e.rel: e for e in pane.entries}
    assert by["b.txt"].status == fd.BOTH_CHANGED and by["a.txt"].action == fd.TO_RIGHT
    item = [it for it in _items(pane.tree) if it.text(sm.L_NAME) == "b.txt"][0]
    assert "beiden Seiten" in item.toolTip(sm.L_NAME) and "links geändert" in item.toolTip(sm.L_NAME)
    assert item.data(sm.ACT, sm.ROLE_ICON)[0] == "!"
    pane.start()
    assert "1 Konflikte wurden übersprungen" in infos[-1]
    # der übersprungene Konflikt bleibt beim nächsten Mal erkennbar
    assert pane.compare()
    assert {e.rel: e for e in pane.entries}["b.txt"].status == fd.BOTH_CHANGED
    # Umbenennen und Löschen des Abgleichs nehmen den Stand mit
    monkeypatch.setattr(sm.QInputDialog, "getText", lambda *a, **k: ("Neuer Name", True))
    pane.rename_profile()
    assert ss.load("Neuer Name", left, right) is not None and ss.load("Mein Abgleich", left, right) is None
    pane.delete_profile()
    assert ss.load("Neuer Name", left, right) is None
    assert sp.load() == []


def _items(tree):
    out = []

    def walk(item):
        out.append(item)
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i))
    return out
