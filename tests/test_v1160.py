"""Tests for 1.16: compare and synchronize folders, saved synchronizations, action after finishing."""

import os

import pytest
from PySide6.QtWidgets import QDialog

from test_mainwindow import window  # noqa: F401

T0 = 1_700_000_000.0


def _file(path, text, mtime=T0):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.utime(path, (mtime, mtime))


@pytest.fixture
def trees(tmp_path):
    left, right = str(tmp_path / "L"), str(tmp_path / "R")
    _file(f"{left}/same.txt", "abc")
    _file(f"{right}/same.txt", "abc", T0 + 1)  # 1 s Abweichung zählt nicht (L-1601)
    _file(f"{left}/newer_left.txt", "neu!!", T0 + 100)
    _file(f"{right}/newer_left.txt", "alt", T0)
    _file(f"{left}/newer_right.txt", "alt", T0)
    _file(f"{right}/newer_right.txt", "neu!!", T0 + 100)
    _file(f"{left}/only_left.jpg", "L")
    _file(f"{right}/only_right.txt", "R")
    _file(f"{left}/dst.txt", "x", T0)
    _file(f"{right}/dst.txt", "x", T0 + 3600)  # Sommerzeit
    _file(f"{left}/conflict.txt", "aaa", T0)
    _file(f"{right}/conflict.txt", "bbbbbb", T0)
    _file(f"{left}/sub/deep.txt", "d")
    _file(f"{right}/sub/deep.txt", "d")
    _file(f"{left}/sub/new.txt", "n")
    _file(f"{left}/newdir/a.txt", "a")
    _file(f"{left}/newdir/b.txt", "bb")
    _file(f"{right}/olddir/c.txt", "c")
    _file(f"{left}/Thumbs.db", "t")
    return left, right


def _by(entries):
    return {e.rel: e for e in entries}


def test_scan_and_actions(trees):
    from panepilot import folderdiff as fd

    left, right = trees
    e = _by(fd.scan(left, right, fd.Options(exclude="Thumbs.db")))
    assert "Thumbs.db" not in e  # Filter (L-1613)
    assert e["same.txt"].status == fd.SAME and e["sub/deep.txt"].status == fd.SAME
    assert e["newer_left.txt"].status == fd.LEFT_NEWER and e["newer_left.txt"].action == fd.TO_RIGHT
    assert e["newer_right.txt"].status == fd.RIGHT_NEWER and e["newer_right.txt"].action == fd.NONE  # nicht spiegeln
    assert e["only_left.jpg"].action == fd.TO_RIGHT and e["only_right.txt"].action == fd.NONE
    assert e["dst.txt"].status == fd.RIGHT_NEWER
    assert e["conflict.txt"].status == fd.CONFLICT and e["conflict.txt"].action == fd.NONE  # L-1617
    assert e["sub/new.txt"].action == fd.TO_RIGHT
    assert e["newdir"].is_dir and e["newdir"].left.files == 2 and e["newdir"].left.size == 3
    assert e["olddir"].status == fd.RIGHT_ONLY
    m = _by(fd.scan(left, right, fd.Options(mirror=True, dst=True)))
    assert m["dst.txt"].status == fd.SAME  # 1 Stunde ignoriert
    assert m["newer_right.txt"].action == fd.TO_RIGHT and m["only_right.txt"].action == fd.DEL_RIGHT
    assert m["olddir"].action == fd.DEL_RIGHT
    b = _by(fd.scan(left, right, fd.Options(direction=fd.BOTH, mirror=True)))
    assert b["newer_right.txt"].action == fd.TO_LEFT and b["only_right.txt"].action == fd.TO_LEFT  # nicht löschen
    r = _by(fd.scan(left, right, fd.Options(direction=fd.RL)))
    assert r["only_right.txt"].action == fd.TO_LEFT and r["only_left.jpg"].action == fd.NONE
    flat = _by(fd.scan(left, right, fd.Options(subdirs=False)))
    assert "sub/new.txt" not in flat and "newdir" not in flat
    inc = _by(fd.scan(left, right, fd.Options(include="*.jpg")))
    assert set(k for k in inc if "/" not in k and not inc[k].is_dir) == {"only_left.jpg"}


def test_content_and_set_action(trees, tmp_path):
    from panepilot import folderdiff as fd

    left, right = trees
    _file(f"{right}/same.txt", "xyz", T0)  # gleiche Größe und Zeit, anderer Inhalt
    e = _by(fd.scan(left, right, fd.Options()))
    assert e["same.txt"].status == fd.SAME
    e = _by(fd.scan(left, right, fd.Options(content=True)))
    assert e["same.txt"].status == fd.CONFLICT
    sel = [e["only_left.jpg"], e["only_right.txt"], e["conflict.txt"]]
    assert fd.set_action(sel, fd.TO_RIGHT) == 2  # „nur rechts“ kann nicht nach rechts (L-1615)
    assert e["only_right.txt"].action == fd.NONE and e["conflict.txt"].action == fd.TO_RIGHT
    assert fd.overwrites(e["conflict.txt"]) and not fd.overwrites(e["only_left.jpg"])
    assert fd.set_action(sel, fd.NONE) == 3


def test_quick_compare(trees):
    from panepilot import folderdiff as fd

    left, right = trees
    lnames, rnames = fd.quick_compare(left, right)
    assert sorted(lnames) == ["Thumbs.db", "conflict.txt", "newer_left.txt", "only_left.jpg"]
    assert sorted(rnames) == ["conflict.txt", "dst.txt", "newer_right.txt", "only_right.txt"]


def test_execute(trees):
    from panepilot import folderdiff as fd

    left, right = trees
    opts = fd.Options(mirror=True, exclude="Thumbs.db")
    entries = fd.scan(left, right, opts)
    trashed = []

    def trash(p):
        trashed.append(os.path.relpath(p, right))
        import shutil

        shutil.rmtree(p) if os.path.isdir(p) else os.unlink(p)

    steps = []
    res = fd.execute(entries, left, right, opts, trash, lambda d, tot, rel: steps.append(rel))
    assert not res.errors and not res.cancelled
    assert sorted(trashed) == ["olddir", "only_right.txt"]
    assert res.deleted == 2 and res.copied == 4 and res.overwritten == 3  # only_left, sub/new, newdir (2) | 3 neuere
    after = _by(fd.scan(left, right, opts))
    assert all(e.status == fd.SAME for k, e in after.items() if k != "conflict.txt")
    assert open(os.path.join(right, "newer_left.txt")).read() == "neu!!"
    assert os.path.getmtime(os.path.join(right, "newdir", "b.txt")) == T0  # Zeit bleibt
    assert not os.path.exists(os.path.join(right, "Thumbs.db"))
    assert not [n for n in os.listdir(right) if n.endswith(".panepilot-sync")]


def test_execute_errors_and_cancel(trees, monkeypatch):
    import threading

    from panepilot import folderdiff as fd

    left, right = trees
    cancel = threading.Event()
    cancel.set()
    res = fd.execute(fd.scan(left, right, fd.Options()), left, right, fd.Options(), lambda p: None, cancel=cancel)
    assert res.cancelled and res.copied == 0
    entries = fd.scan(left, right, fd.Options())
    os.makedirs(os.path.join(right, "only_left.jpg"))  # inzwischen steht ein Ordner im Weg
    res = fd.execute(entries, left, right, fd.Options(), lambda p: None)
    assert [rel for rel, _m in res.errors] == ["only_left.jpg"] and res.copied > 0


def test_profiles_and_after(tmp_path, monkeypatch):
    from panepilot import folderdiff as fd
    from panepilot import syncprofiles as sp

    monkeypatch.setattr(sp, "config_dir", lambda: tmp_path / "cfg")
    assert sp.load() == []
    p = sp.Profile("Fotos → NAS", "/a", "/b", fd.Options(direction=fd.BOTH, exclude="*.tmp"),
                   sp.After(sp.AFTER_COMMAND, "echo hi", sp.WHEN_ALWAYS))
    sp.put(p)
    sp.put(sp.Profile("Andere", "/c", "/d"))
    names = [x.name for x in sp.load()]
    assert names == ["Andere", "Fotos → NAS"]
    got = sp.load()[1]
    assert got.options.direction == fd.BOTH and got.options.exclude == "*.tmp" and got.after.command == "echo hi"
    got.name = "Fotos"
    sp.put(got, old_name="Fotos → NAS")
    assert [x.name for x in sp.load()] == ["Andere", "Fotos"]
    sp.remove("andere")
    assert [x.name for x in sp.load()] == ["Fotos"]
    ok, bad, stop = fd.Result(copied=1), fd.Result(errors=[("x", "e")]), fd.Result(cancelled=True)
    a = sp.After(sp.AFTER_COMMAND, "true", sp.WHEN_OK)
    assert a.due(ok) and not a.due(bad) and not a.due(stop)  # L-1631
    assert sp.After(sp.AFTER_SHUTDOWN, "", sp.WHEN_ALWAYS).due(bad)
    assert not sp.After(sp.AFTER_COMMAND, " ", sp.WHEN_ALWAYS).due(ok)
    out = tmp_path / "out.txt"
    env = sp.script_env("/a", "/b", fd.Result(copied=2, overwritten=1, deleted=4), "Fotos")
    code, text = sp.run_command(f'echo "$PANEPILOT_RESULT $PANEPILOT_COPIED $PANEPILOT_DELETED $PANEPILOT_PROFILE" '
                                f'> "{out}"; echo fertig', env)
    assert code == 0 and text == "fertig" and out.read_text().strip() == "ok 3 4 Fotos"
    code, text = sp.run_command("echo kaputt; exit 3", env)
    assert code == 3 and text == "kaputt"
    assert sp.power_command(sp.AFTER_SUSPEND) == ["systemctl", "suspend"]
    assert sp.power_command(sp.AFTER_SHUTDOWN) == ["systemctl", "poweroff"]


def test_dialog(window, trees, monkeypatch, tmp_path):  # noqa: F811
    from panepilot import folderdiff as fd
    from panepilot import netutil
    from panepilot import syncdialog as sd
    from panepilot import syncprofiles as sp

    monkeypatch.setattr(sp, "config_dir", lambda: tmp_path / "cfg")
    monkeypatch.setattr(netutil, "run_blocking", lambda parent, fn, text, title: (fn(), None))
    left, right = trees
    dlg = sd.SyncDialog(window, left, right)
    assert not dlg.btn_start.isEnabled()
    dlg.ed_exclude.setText("Thumbs.db")
    assert dlg.compare()
    shown = [dlg.tree.topLevelItem(i).text(0) for i in range(dlg.tree.topLevelItemCount())]
    assert "same.txt" not in shown and "newdir/" in shown and "conflict.txt" in shown
    dlg.chk_same.setChecked(True)
    assert dlg.tree.topLevelItemCount() == len(dlg.entries)
    dlg.chk_same.setChecked(False)
    assert dlg.btn_start.isEnabled()
    # alle markieren und auf „nichts tun“ setzen (L-1615)
    dlg.tree.selectAll()
    dlg.set_selected(fd.NONE)
    assert all(e.action == fd.NONE for e in dlg.entries) and not dlg.btn_start.isEnabled()
    item = [dlg.tree.topLevelItem(i) for i in range(dlg.tree.topLevelItemCount())
            if dlg.tree.topLevelItem(i).text(0) == "only_left.jpg"][0]
    dlg.tree.clearSelection()
    item.setSelected(True)
    dlg.set_selected(fd.TO_RIGHT)
    assert item.text(2) == "→ kopieren" and dlg.btn_start.isEnabled()
    # Abgleich speichern (L-1620)
    monkeypatch.setattr(sd.QInputDialog, "getText", lambda *a, **k: ("Test", True))
    dlg.cb_after.setCurrentIndex(dlg.cb_after.findData(sp.AFTER_COMMAND))
    out = tmp_path / "res.txt"
    dlg.ed_command.setText(f'echo "$PANEPILOT_RESULT" > "{out}"')
    dlg.save_profile()
    assert [p.name for p in sp.load()] == ["Test"] and dlg.current_profile() == "Test"
    # Starten
    monkeypatch.setattr(sd, "confirm", lambda *a, **k: True)
    infos = []
    monkeypatch.setattr(sd, "show_info", lambda *a: infos.append(a[2]))
    dlg.start()
    assert os.path.exists(os.path.join(right, "only_left.jpg"))
    assert not os.path.exists(os.path.join(right, "newer_left.txt.x"))
    assert out.read_text().strip() == "ok" and "1 kopiert" in infos[0]
    assert window.settings.get("sync_last")["options"]["exclude"] == "Thumbs.db"
    # Profil laden in neuem Dialog
    d2 = sd.SyncDialog(window, "", "", "Test")
    assert d2.ed_left.text() == left and d2.ed_command.text().startswith("echo")
    d2.ed_right.setText(os.path.join(left, "sub"))
    errors = []
    monkeypatch.setattr(sd, "show_error", lambda *a: errors.append(a[2]))
    assert not d2.compare() and errors  # ineinander


def test_countdown(window, monkeypatch):  # noqa: F811
    from panepilot import syncdialog as sd
    from panepilot import syncprofiles as sp

    d = sd.CountdownDialog(window, sp.AFTER_SHUTDOWN, 2)
    assert "2" in d.label.text()
    d._tick()
    assert "1" in d.label.text()
    d._tick()
    assert d.result() == QDialog.DialogCode.Accepted


def test_main_window(window, trees, monkeypatch, qtbot, tmp_path):  # noqa: F811
    from panepilot import syncprofiles as sp

    left, right = trees
    window.sides["left"].panel.navigate(left)
    window.sides["right"].panel.navigate(right)
    qtbot.waitUntil(lambda: window.sides["left"].panel.model.rowCount() > 0 and
                    window.sides["right"].panel.model.rowCount() > 0, timeout=5000)
    window.do_compare_folders()
    sel = sorted(e.name for e in window.sides["left"].panel.selected_entries())
    assert sel == ["Thumbs.db", "conflict.txt", "newer_left.txt", "only_left.jpg"]
    assert "4" in window.statusBar().currentMessage()
    assert "compare_folders" in window.qactions and window.qactions["sync_folders"].shortcut().toString()
    monkeypatch.setattr(sp, "config_dir", lambda: tmp_path / "cfg")
    window._fill_sync_menu()
    assert [a.text() for a in window.sync_menu.actions()] == ["(noch keine gespeichert)"]
    sp.put(sp.Profile("Fotos", trees[0], trees[1]))
    window._fill_sync_menu()
    assert [a.text() for a in window.sync_menu.actions()] == ["Fotos"]
