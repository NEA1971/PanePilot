"""Tests for 1.17: import from / export to FreeFileSync (.ffs_gui, .ffs_batch)."""

import os

from PySide6.QtWidgets import QDialog  # noqa: F401

from test_mainwindow import window  # noqa: F401

MIRROR = """<?xml version="1.0" encoding="utf-8"?>
<FreeFileSync XmlType="GUI" XmlFormat="23">
    <Notes/>
    <Compare>
        <Variant>TimeAndSize</Variant>
        <Symlinks>Exclude</Symlinks>
        <IgnoreTimeShift/>
    </Compare>
    <Synchronize>
        <Differences LeftOnly="right" LeftNewer="right" RightNewer="right" RightOnly="right"/>
        <DeletionPolicy>RecycleBin</DeletionPolicy>
        <VersioningFolder Style="Replace"/>
    </Synchronize>
    <Filter>
        <Include>
            <Item>*</Item>
        </Include>
        <Exclude>
            <Item>*/.Trash-*/</Item>
            <Item>*/.recycle/</Item>
        </Exclude>
        <SizeMin Unit="None">0</SizeMin>
        <SizeMax Unit="None">0</SizeMax>
        <TimeSpan Type="None">0</TimeSpan>
    </Filter>
    <FolderPairs>
        <Pair>
            <Left>/home/alice/.config/app</Left>
            <Right>/mnt/nas/Backup/app</Right>
        </Pair>
    </FolderPairs>
    <Errors Ignore="false" Retry="0" Delay="5"/>
    <PostSyncCommand Condition="Completion">sh /opt/scripts/after.sh</PostSyncCommand>
    <LogFolder/>
    <EmailNotification Condition="Always"/>
    <GridViewType>Action</GridViewType>
</FreeFileSync>
"""

UPDATE = MIRROR.replace(
    '<Differences LeftOnly="right" LeftNewer="right" RightNewer="right" RightOnly="right"/>',
    '<Changes><Left Create="right" Update="right" Delete="none"/>'
    '<Right Create="none" Update="none" Delete="none"/></Changes>').replace(
    '<PostSyncCommand Condition="Completion">sh /opt/scripts/after.sh</PostSyncCommand>',
    '<PostSyncCommand Condition="Completion"/>')

TWOWAY_BATCH = """<?xml version="1.0" encoding="utf-8"?>
<FreeFileSync XmlType="BATCH" XmlFormat="23">
    <Compare><Variant>Content</Variant><IgnoreTimeShift>1</IgnoreTimeShift></Compare>
    <Synchronize>
        <Changes><Left Create="right" Update="right" Delete="right"/>
                 <Right Create="left" Update="left" Delete="left"/></Changes>
        <DeletionPolicy>Permanent</DeletionPolicy>
    </Synchronize>
    <Filter>
        <Include><Item>*.jpg</Item><Item>/Fotos/</Item></Include>
        <Exclude><Item>/Cache/</Item><Item>Thumbs.db</Item></Exclude>
        <SizeMin Unit="MB">5</SizeMin>
    </Filter>
    <FolderPairs>
        <Pair><Left>/home/alice/A</Left><Right>/home/alice/B</Right></Pair>
        <Pair><Left>/home/alice/C</Left><Right>sftp://server/D</Right></Pair>
    </FolderPairs>
    <PostSyncCommand Condition="Errors">notify-send fehler</PostSyncCommand>
    <Batch><ProgressDialog Minimized="false" AutoClose="false"/></Batch>
</FreeFileSync>
"""

OLD_VARIANT = """<?xml version="1.0" encoding="utf-8"?>
<FreeFileSync XmlType="GUI" XmlFormat="10">
    <Compare><Variant>Size</Variant></Compare>
    <Synchronize><Variant>Update</Variant></Synchronize>
    <FolderPairs><Pair><Left>/a</Left><Right>/b</Right></Pair></FolderPairs>
</FreeFileSync>
"""


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_import_mirror_and_update(window, tmp_path):  # noqa: F811
    from panepilot import folderdiff as fd
    from panepilot import ffsconvert as ffs
    from panepilot import syncprofiles as sp

    profs, notes = ffs.parse(_write(tmp_path, "Backup_App.ffs_gui", MIRROR))
    assert notes == [] and len(profs) == 1
    p = profs[0]
    assert (p.name, p.left, p.right) == ("Backup_App", "/home/alice/.config/app", "/mnt/nas/Backup/app")
    o = p.options
    assert (o.direction, o.mirror, o.content, o.dst, o.include, o.exclude) == \
        (fd.LR, True, False, False, "*", ".Trash-*; .recycle")
    assert (p.after.kind, p.after.command, p.after.when) == (sp.AFTER_COMMAND, "sh /opt/scripts/after.sh",
                                                             sp.WHEN_ALWAYS)
    profs, notes = ffs.parse(_write(tmp_path, "Upd.ffs_gui", UPDATE))
    assert notes == [] and profs[0].options.direction == fd.LR and not profs[0].options.mirror
    assert profs[0].after.kind == sp.AFTER_NONE


def test_import_batch_with_notes(window, tmp_path):  # noqa: F811
    from panepilot import folderdiff as fd
    from panepilot import ffsconvert as ffs
    from panepilot import syncprofiles as sp

    profs, notes = ffs.parse(_write(tmp_path, "Zwei.ffs_batch", TWOWAY_BATCH))
    assert [p.name for p in profs] == ["Zwei", "Zwei (2)"]
    o = profs[0].options
    assert o.direction == fd.BOTH and o.content and o.dst
    assert o.include == "*.jpg" and o.exclude == "Cache; Thumbs.db"
    assert profs[0].after.when == sp.WHEN_ALWAYS
    text = "\n".join(notes)
    for part in ("Datenbank", "Fotos", "/Cache/", "Größen", "Fehlern", "sftp://server/D", "2 Ordnerpaare"):
        assert part in text, part
    profs, notes = ffs.parse(_write(tmp_path, "Alt.ffs_gui", OLD_VARIANT))
    assert profs[0].options.direction == fd.LR and not profs[0].options.mirror
    assert any("Größe" in n for n in notes)
    try:
        ffs.parse(_write(tmp_path, "x.ffs_gui", "<Other/>"))
        raise AssertionError
    except ValueError:
        pass


def test_export_roundtrip(window, tmp_path):  # noqa: F811
    import xml.etree.ElementTree as ET

    from panepilot import folderdiff as fd
    from panepilot import ffsconvert as ffs
    from panepilot import syncprofiles as sp

    for direction, mirror in ((fd.LR, True), (fd.LR, False), (fd.RL, True), (fd.RL, False), (fd.BOTH, False)):
        p = sp.Profile("Fotos → NAS", "/home/alice/Bilder", "/mnt/nas/Bilder",
                       fd.Options(direction, True, True, False, mirror, "*.jpg; *.png", "Thumbs.db; .Trash-*"),
                       sp.After(sp.AFTER_COMMAND, "sh run.sh", sp.WHEN_OK))
        path = str(tmp_path / (ffs.safe_file_name(p.name) + ".ffs_gui"))
        ffs.save(p, path)
        root = ET.parse(path).getroot()
        assert root.get("XmlFormat") == "23" and (root.findtext("Compare/IgnoreTimeShift") or "") == ""  # leer
        assert [i.text for i in root.findall("Filter/Exclude/Item")] == ["*/Thumbs.db", "*/.Trash-*"]
        back, _notes = ffs.parse(path)
        b = back[0]
        assert (b.left, b.right) == (p.left, p.right)
        assert (b.options.direction, b.options.mirror) == (direction, mirror)
        assert b.options.include == "*.jpg; *.png" and b.options.exclude == "Thumbs.db; .Trash-*"
        assert (b.after.command, b.after.when) == ("sh run.sh", sp.WHEN_OK)
    assert ffs.safe_file_name("Fotos → NAS") == "Fotos → NAS" and ffs.safe_file_name('a/b:c') == "a_b_c"
    assert ffs.export_notes(p)  # Sommerzeit steht nicht in der Datei


def test_dialog_import_export(window, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import netutil
    from panepilot import syncdialog as sd
    from panepilot import syncprofiles as sp

    monkeypatch.setattr(sp, "config_dir", lambda: tmp_path / "cfg")
    monkeypatch.setattr(netutil, "run_blocking", lambda parent, fn, text, title: (fn(), None))
    a = _write(tmp_path, "Backup_App.ffs_gui", MIRROR)
    b = _write(tmp_path, "Upd.ffs_gui", UPDATE)
    dlg = sd.SyncDialog(window, "", "")
    monkeypatch.setattr(sd.QFileDialog, "getOpenFileNames", lambda *x, **k: ([a, b], ""))
    infos, asked = [], []
    monkeypatch.setattr(sd, "show_info", lambda *x: infos.append(x[2]))
    monkeypatch.setattr(sd, "confirm", lambda *x, **k: asked.append(x[2]) or False)
    dlg.import_ffs()
    assert [p.name for p in sp.load()] == ["Backup_App", "Upd"] and "2 Abgleiche" in infos[-1]
    assert dlg.current_profile() == "Upd" and dlg.ed_left.text() == "/home/alice/.config/app"
    dlg.import_ffs()  # gleiche Namen: Rückfrage, „nein“ → übersprungen
    assert len(asked) == 2 and "übersprungen" in infos[-1]
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(sd.QFileDialog, "getExistingDirectory", lambda *x, **k: str(out))
    dlg.export_all_ffs()
    assert sorted(os.listdir(out)) == ["Backup_App.ffs_gui", "Upd.ffs_gui"]
    dlg.export_all_ffs()  # vorhandene Dateien: Rückfrage, „nein“ → nichts
    assert len(asked) == 3
    single = str(tmp_path / "einzeln")
    monkeypatch.setattr(sd.QFileDialog, "getSaveFileName", lambda *x, **k: (single, ""))
    dlg.export_ffs()
    assert os.path.exists(single + ".ffs_gui")
