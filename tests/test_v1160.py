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


def _items(tree):
    out = []

    def visit(item):
        out.append(item)
        for i in range(item.childCount()):
            visit(item.child(i))

    root = tree.invisibleRootItem()
    for i in range(root.childCount()):
        visit(root.child(i))
    return out


def test_sync_pane(window, trees, monkeypatch, tmp_path):  # noqa: F811
    from panepilot import folderdiff as fd
    from panepilot import netutil
    from panepilot import syncmode as sm
    from panepilot import syncprofiles as sp

    monkeypatch.setattr(sp, "config_dir", lambda: tmp_path / "cfg")
    monkeypatch.setattr(netutil, "run_blocking", lambda parent, fn, text, title: (fn(), None))
    left, right = trees
    pane = sm.SyncPane(window)
    pane.set_paths(left, right)
    assert not pane.btn_start.isEnabled()
    pane.ed_exclude.setText("Thumbs.db")
    assert pane.compare()
    tree = pane.tree
    top = {tree.topLevelItem(i).text(sm.L_NAME) or tree.topLevelItem(i).text(sm.R_NAME): tree.topLevelItem(i)
           for i in range(tree.topLevelItemCount())}
    assert "same.txt" not in top and "newdir" in top and "conflict.txt" in top
    assert "sub" in top and top["sub"].childCount() == 1 and top["sub"].isExpanded()  # Baum, aufgeklappt (L-1804)
    assert top["sub"].child(0).text(sm.L_NAME) == "new.txt" and top["sub"].child(0).text(sm.R_NAME) == ""
    assert top["only_right.txt"].text(sm.L_NAME) == "" and top["only_right.txt"].text(sm.R_NAME) == "only_right.txt"
    assert top["conflict.txt"].data(sm.ACT, sm.ROLE_ICON)[0] == "!"
    assert top["only_left.jpg"].data(sm.ACT, sm.ROLE_ICON)[0] == "→"
    assert top["only_left.jpg"].toolTip(sm.ACT) == "nach rechts kopieren"  # nur Symbol, Text als Tooltip
    assert top["sub"].data(sm.ACT, sm.ROLE_ICON)[0] == "→"
    pane.chk_same.setChecked(True)
    assert sum(1 for it in _items(tree) if it.data(sm.L_NAME, sm.ROLE_ENTRY) >= 0) == len(pane.entries)
    pane.chk_same.setChecked(False)
    assert pane.btn_start.isEnabled()
    # alle markieren und auf „nichts tun“ setzen (L-1615)
    tree.selectAll()
    pane.view.buttons[fd.NONE].click()
    assert all(e.action == fd.NONE for e in pane.entries) and not pane.btn_start.isEnabled()
    top = {tree.topLevelItem(i).text(sm.L_NAME) or tree.topLevelItem(i).text(sm.R_NAME): tree.topLevelItem(i)
           for i in range(tree.topLevelItemCount())}
    # Ordner markieren: gilt für alles darin (L-1805); dann eine Datei darin umstellen → „gemischt“
    _file(f"{left}/sub/second.txt", "x")
    assert pane.compare()
    top = {tree.topLevelItem(i).text(sm.L_NAME) or tree.topLevelItem(i).text(sm.R_NAME): tree.topLevelItem(i)
           for i in range(tree.topLevelItemCount())}
    tree.clearSelection()
    top["sub"].setSelected(True)
    pane.set_selected(fd.NONE)
    assert {e.action for e in pane.entries if e.rel.startswith("sub/")} == {fd.NONE}
    tree.clearSelection()
    top["sub"].child(0).setSelected(True)
    pane.set_selected(fd.TO_RIGHT)
    assert top["sub"].data(sm.ACT, sm.ROLE_ICON)[0] == "•"
    # Aufklappen per „+“/„−“
    top["sub"].setExpanded(False)
    assert not top["sub"].isExpanded()
    tree.clearSelection()
    for e in pane.entries:
        e.action = fd.NONE
    top["only_left.jpg"].setSelected(True)
    pane.set_selected(fd.TO_RIGHT)
    assert pane.btn_start.isEnabled()
    # Abgleich speichern (L-1620)
    monkeypatch.setattr(sm.QInputDialog, "getText", lambda *a, **k: ("Test", True))
    pane.cb_after.setCurrentIndex(pane.cb_after.findData(sp.AFTER_COMMAND))
    out = tmp_path / "res.txt"
    pane.ed_command.setText(f'echo "$PANEPILOT_RESULT" > "{out}"')
    pane.save_profile()
    assert [p.name for p in sp.load()] == ["Test"] and pane.current_profile() == "Test"
    # Starten
    monkeypatch.setattr(sm, "confirm", lambda *a, **k: True)
    infos = []
    monkeypatch.setattr(sm, "show_info", lambda *a: infos.append(a[2]))
    pane.start()
    assert os.path.exists(os.path.join(right, "only_left.jpg"))
    assert out.read_text().strip() == "ok" and "1 kopiert" in infos[0]
    assert window.settings.get("sync_last")["options"]["exclude"] == "Thumbs.db"
    # Doppelklick öffnet die Datei der angeklickten Seite (L-1807)
    opened = []
    monkeypatch.setattr(sm.util, "open_with_default_app", lambda p: opened.append(p))
    item = [it for it in _items(tree) if it.text(sm.R_NAME) == "only_right.txt"][0]
    pane._open(item, sm.R_NAME)
    pane._open(item, sm.L_NAME)  # links gibt es sie nicht
    assert opened == [os.path.join(right, "only_right.txt")]
    # Profil laden
    p2 = sm.SyncPane(window)
    assert p2.load_profile("Test") and p2.ed_left.text() == left and p2.ed_command.text().startswith("echo")
    p2.ed_right.setText(os.path.join(left, "sub"))
    errors = []
    monkeypatch.setattr(sm, "show_error", lambda *a: errors.append(a[2]))
    assert not p2.compare() and errors  # ineinander


def test_sync_mode_in_window(window, trees, monkeypatch, tmp_path, qtbot):  # noqa: F811
    from panepilot import folderdiff as fd
    from panepilot import netutil
    from panepilot import syncmode as sm
    from panepilot import syncprofiles as sp
    from panepilot.synccontrol import MODE_SYNC

    monkeypatch.setattr(sp, "config_dir", lambda: tmp_path / "cfg")
    monkeypatch.setattr(netutil, "run_blocking", lambda parent, fn, text, title: (fn(), None))
    left, right = trees
    window.sides["left"].panel.navigate(left)
    window.sides["right"].panel.navigate(right)
    single = window.single_mode
    window.do_sync_folders()
    assert window.sync_mode is not None and window.sides["left"].sidebar.mode == MODE_SYNC
    pane = window.sync_pane()
    assert (pane.ed_left.text(), pane.ed_right.text()) == (left, right)
    assert pane.view.isVisibleTo(window) and window.single_mode
    assert not window.qactions["copy"].isEnabled()
    assert window.fkey_action("F5") == "sync_start" and window.fkey_action("F8") == "sync_delete_right"
    assert "F2" in window.fkey_bar._disabled and "F5" not in window.fkey_bar._disabled  # L-1806
    assert pane.compare()
    pane.tree.selectAll()
    window.trigger("sync_delete_right")  # F8
    assert any(e.action == fd.DEL_RIGHT for e in pane.entries)
    window.trigger("copy")  # gesperrt
    called = []
    monkeypatch.setattr(sm.SyncPane, "start", lambda self: called.append(1))
    window.trigger(window.fkey_action("F5"))
    assert called == [1]
    window.leave_sync_mode()
    assert window.sync_mode is None and window.qactions["copy"].isEnabled() and window.single_mode == single
    assert window.fkey_action("F5") == window.fkeys.get("F5")
    # gespeicherter Abgleich über das Menü: Ansicht öffnet sich und vergleicht sofort
    sp.put(sp.Profile("Fotos", left, right))
    window.do_sync_folders("Fotos")
    qtbot.waitUntil(lambda: window.sync_pane().scanned is not None, timeout=3000)
    assert window.sync_pane().current_profile() == "Fotos"
    window.leave_sync_mode()


def test_countdown(window, monkeypatch):  # noqa: F811
    from panepilot import syncmode as sd
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
