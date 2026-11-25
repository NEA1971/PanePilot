"""v3.1: Windows-Version Teil 2 – FreeCommander-Favoriten, Zusatzprogramme, „Danach“ unter Windows.

Nur synthetische Testdaten.
"""

import json
import os
import sys

import pytest

WIN = sys.platform.startswith("win")
only_windows = pytest.mark.skipif(not WIN, reason="nur unter Windows")

FC_XML = """<?xml version="1.0" encoding="UTF-16"?>
<FreeCommanderXE_favorite_items>
  <category text="Arbeit" id="A" expanded="-1" font_color="536870911" bkg_color="536870911">
    <folder_item text="Projekte" folder_active="D:\\Projekte" folder_inactive="" hotkey_nr="-1" font_color="255"/>
    <category text="Unter" id="B" expanded="0" font_color="16711680">
      <file_item text="" file="D:\\Liste.txt" font_color="536870911"/>
    </category>
  </category>
  <folder_item text="Daten" folder_active="" folder_inactive="\\\\nas\\Daten" font_color="-16777208"/>
  <folder_item text="leer" folder_active="" folder_inactive="" font_color="0"/>
</FreeCommanderXE_favorite_items>
"""


def test_fc_parse_utf16_and_utf8():  # L-4102
    from panepilot import fcimport

    for raw in (FC_XML.encode("utf-16"), FC_XML.replace("UTF-16", "UTF-8").encode("utf-8"),
                b"\xef\xbb\xbf" + FC_XML.replace("UTF-16", "UTF-8").encode("utf-8")):
        data, expanded = fcimport.parse(raw)
        items = data["items"]
        assert [i["name"] for i in items] == ["Arbeit", "Daten"]
        work = items[0]
        assert work["type"] == "group" and expanded == [work["id"]]
        proj, sub = work["children"]
        assert proj["path"] == "D:\\Projekte" and proj["style"] == {"color": "red"}
        assert sub["type"] == "group" and sub["style"] == {"color": "blue"}
        assert sub["children"][0]["name"] == "Liste.txt" and sub["children"][0]["path"] == "D:\\Liste.txt"
        assert items[1]["path"] == "\\\\nas\\Daten" and "style" not in items[1]
        assert fcimport.count(items) == 3


def test_fc_parse_empty_and_invalid():
    from panepilot import fcimport

    data, _ = fcimport.parse(b'<?xml version="1.0"?>\r\n<FreeCommanderXE_favorite_items/>')
    assert data["items"] == []
    with pytest.raises(ValueError):
        fcimport.parse(b"<andere/>")
    with pytest.raises(ValueError):
        fcimport.parse(b"kein xml")


def test_fc_colors_and_names(tmp_path):
    from panepilot import fcimport

    assert fcimport.color_key(536870911) is None and fcimport.color_key(-16777208) is None
    assert fcimport.color_key(255) == "red"  # BGR: Rot
    assert fcimport.color_key(0x00FF00) == "green"
    assert fcimport.color_key(0xFFFFFF) == "white"
    assert fcimport.unique_set_name(["Standard"]) == "FreeCommander"
    assert fcimport.unique_set_name(["freecommander", "FreeCommander 2"]) == "FreeCommander 3"
    for i, name in enumerate(("FreeCommander.fav.xml", "FreeCommander.fav3.xml", "andere.xml")):
        p = tmp_path / name
        p.write_text("x")
        os.utime(p, (1000 + i, 1000 + i * 10))
    os.utime(tmp_path / "andere.xml", (5000, 5000))
    assert fcimport.newest_file(str(tmp_path)).endswith("FreeCommander.fav3.xml")
    assert fcimport.newest_file(str(tmp_path / "fehlt")) is None


def test_fc_import_into_new_set(qapp, tmp_path, monkeypatch):  # L-4100/L-4101
    from panepilot.mainwindow import MainWindow

    src = tmp_path / "FreeCommander.fav2.xml"
    src.write_bytes(FC_XML.encode("utf-16"))
    infos = []
    monkeypatch.setattr("panepilot.mainwindow.show_info", lambda *a, **k: infos.append(a[2]))
    w = MainWindow()
    try:
        before = w.fav_sets.names()
        current = w.fav_set[w.active_side]
        old_items = json.dumps(w.fav_sets.model(current).to_dict())
        w.do_fav_import_fc(str(src))
        assert "FreeCommander" in w.fav_sets.names() and len(w.fav_sets.names()) == len(before) + 1
        assert w.fav_set[w.active_side] == "FreeCommander"
        assert json.dumps(w.fav_sets.model(current).to_dict()) == old_items  # alter Satz unberührt
        names = [n["name"] for n in w.fav_sets.model("FreeCommander").to_dict()["items"]]
        assert names == ["Arbeit", "Daten"] and "3" in infos[-1]
        w.do_fav_import_fc(str(src))
        assert "FreeCommander 2" in w.fav_sets.names()
        w.fav_sets.rename("FreeCommander 2", "Aus FC")  # umbenennbar wie jeder Satz
        assert "Aus FC" in w.fav_sets.names()
    finally:
        w._skip_save_state = True
        w.close()


def test_fc_menu_only_windows(qapp):
    from panepilot.mainwindow import MainWindow

    w = MainWindow()
    try:
        texts = [a for m in w.menuBar().actions() for a in m.menu().actions()]
        assert (w.qactions["fav_import_fc"] in texts) == WIN
    finally:
        w._skip_save_state = True
        w.close()


def test_tools_find(tmp_path, monkeypatch):  # L-4110
    from panepilot import tools

    monkeypatch.setattr(tools.shutil, "which", lambda name: None)
    monkeypatch.setattr(tools, "IS_WINDOWS", True)
    pf = tmp_path / "Programme"
    (pf / "7-Zip").mkdir(parents=True)
    (pf / "7-Zip" / "7z.exe").write_text("")
    (pf / "MKVToolNix").mkdir()
    (pf / "MKVToolNix" / "mkvmerge.exe").write_text("")
    ff = tmp_path / "local" / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg_x" / "ffmpeg-7.1-full" / "bin"
    ff.mkdir(parents=True)
    (ff / "ffprobe.exe").write_text("")
    (pf / "ExifTool").mkdir()
    (pf / "ExifTool" / "exiftool(-k).exe").write_text("")
    monkeypatch.setenv("ProgramFiles", str(pf))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "x86"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    tools.configure({})
    assert tools.find("7z") == os.path.join(str(pf), "7-Zip", "7z.exe")
    assert tools.find("mkvmerge").endswith("mkvmerge.exe")
    assert tools.find("ffprobe") == str(ff / "ffprobe.exe")
    assert tools.find("exiftool").endswith("exiftool(-k).exe")
    assert tools.find("mkvextract") is None
    own = tmp_path / "eigen.exe"
    own.write_text("")
    tools.configure({"mkvextract": str(own), "ffmpeg": str(tmp_path / "gibtsnicht")})
    assert tools.find("mkvextract") == str(own) and tools.find("ffmpeg") is None
    tools.configure({})


def test_tools_used_by_modules(monkeypatch, tmp_path):  # L-4113: alle Video-/Archivfunktionen fragen tools
    from panepilot import archives, mkvtracks, phototags, replaygain, tools, videotags

    fake = str(tmp_path / "x")
    monkeypatch.setattr(tools, "find", lambda name: f"{fake}-{name}")
    assert videotags.ffprobe().endswith("ffprobe") and videotags.mkvpropedit().endswith("mkvpropedit")
    assert phototags.exiftool().endswith("exiftool") and mkvtracks.mkvmerge().endswith("mkvmerge")
    assert archives.seven_zip().endswith("7z")
    assert replaygain.ffmpeg_path().endswith("ffmpeg") if hasattr(replaygain, "ffmpeg_path") else True


def test_settings_tools_page(qapp, tmp_path, monkeypatch):  # L-4111
    from panepilot import tools
    from panepilot.mainwindow import MainWindow
    from panepilot.settingsdialog import SettingsDialog

    w = MainWindow()
    try:
        dlg = SettingsDialog(w)
        assert "tools" in dlg.pages and set(dlg.tool_edits) == set(tools.TOOLS)
        own = tmp_path / "mein-ffmpeg"
        own.write_text("")
        dlg.tool_edits["ffmpeg"].setText(str(own))
        assert dlg.tool_status["ffmpeg"].text() and dlg.tool_status["ffmpeg"].toolTip() == str(own)
        dlg.tool_edits["mkvmerge"].setText(str(tmp_path / "fehlt"))
        assert not dlg.tool_status["mkvmerge"].toolTip()
        dlg.accept()
        assert w.settings.get("tool_paths")["ffmpeg"] == str(own)
        assert tools.find("ffmpeg") == str(own)
    finally:
        tools.configure({})
        w._skip_save_state = True
        w.close()


def test_windows_script_command():  # L-4121
    from panepilot import syncprofiles as sp

    args, shell = sp.windows_command('"C:\\Meine Skripte\\fertig.ps1" -Laut')
    assert not shell and args[:5] == ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    assert args[5:] == ["C:\\Meine Skripte\\fertig.ps1", "-Laut"]
    assert sp.windows_command("C:\\x\\fertig.bat") == ("C:\\x\\fertig.bat", True)
    assert sp.windows_command("echo %PANEPILOT_RESULT%") == ("echo %PANEPILOT_RESULT%", True)


def test_power_command_windows(monkeypatch):  # L-4120
    from panepilot import syncprofiles as sp

    monkeypatch.setattr(sys, "platform", "win32")
    assert sp.power_command(sp.AFTER_SHUTDOWN) == ["shutdown", "/s", "/t", "0"]


# --- nur Windows -------------------------------------------------------------------------------------------------
@only_windows
def test_win_script_env(tmp_path):
    from panepilot import syncprofiles as sp

    script = tmp_path / "s.bat"
    script.write_text("@echo %PANEPILOT_RESULT% %PANEPILOT_COPIED%\r\n")
    env = dict(os.environ, PANEPILOT_RESULT="ok", PANEPILOT_COPIED="3")
    code, out = sp.run_command(str(script), env, timeout=60)
    assert code == 0 and "ok 3" in out
    ps = tmp_path / "s.ps1"
    ps.write_text("Write-Output \"PS $env:PANEPILOT_RESULT\"\r\n")
    code, out = sp.run_command(str(ps), env, timeout=120)
    assert code == 0 and "PS ok" in out


@only_windows
def test_win_subprocess_defaults():
    import subprocess

    from panepilot import tools

    tools.install_windows_subprocess_defaults()
    proc = subprocess.run(["cmd.exe", "/c", "echo", "hallo"], capture_output=True, text=True)
    assert proc.returncode == 0 and "hallo" in proc.stdout
