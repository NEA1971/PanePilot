from panepilot.apps import DesktopApp, apps_for, build_commands, parse_desktop_file


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_parse_and_hidden_entries(tmp_path):
    ok = write(tmp_path / "a.desktop", "[Desktop Entry]\nType=Application\nName=Editor\nName[de]=Texteditor\n"
               "Exec=editor %F\nIcon=accessories-text-editor\nMimeType=text/plain;\n")
    hidden = write(tmp_path / "b.desktop", "[Desktop Entry]\nType=Application\nName=X\nExec=x\nNoDisplay=true\n")
    app = parse_desktop_file(str(ok), "a.desktop")
    assert app.mime_types == ["text/plain"] and app.exec == "editor %F"
    assert parse_desktop_file(str(hidden), "b.desktop") is None


def test_build_commands_field_codes():
    multi = DesktopApp("m.desktop", "M", "prog --new %U")
    assert build_commands(multi, ["/a b.txt", "/c.txt"]) == [["prog", "--new", "file:///a%20b.txt", "file:///c.txt"]]
    single = DesktopApp("s.desktop", "S", "viewer %f")
    assert build_commands(single, ["/a", "/b"]) == [["viewer", "/a"], ["viewer", "/b"]]
    plain = DesktopApp("p.desktop", "P", "'my prog' -x")
    assert build_commands(plain, ["/a"]) == [["my prog", "-x", "/a"]]


def test_apps_for_matches_type_and_parents(tmp_path, monkeypatch):
    data = tmp_path / "share"
    write(data / "applications" / "ed.desktop", "[Desktop Entry]\nType=Application\nName=Ed\nExec=ed %f\nMimeType=text/plain;\n")
    write(data / "applications" / "img.desktop", "[Desktop Entry]\nType=Application\nName=Img\nExec=img %f\nMimeType=image/png;\n")
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "leer"))
    names = [a.name for a in apps_for("text/x-python")]  # Python-Quelltext ist eine Art text/plain
    assert names == ["Ed"]


def test_file_uri_is_encoded():
    """v0.9.8: Leerzeichen und Sonderzeichen müssen kodiert sein, sonst findet z. B. VLC den Ordner nicht."""
    from panepilot.apps import file_uri

    assert file_uri("/media/x/1999 - Californication/Californication.m3u8") == \
        "file:///media/x/1999%20-%20Californication/Californication.m3u8"
    assert file_uri("/m/Für #1.mp3") == "file:///m/F%C3%BCr%20%231.mp3"


def test_open_default_prefers_gio(monkeypatch, tmp_path):
    import panepilot.util as util

    calls = []
    monkeypatch.setattr(util, "_start_detached", lambda prog, args, wd: calls.append((prog, args)) or True)
    f = tmp_path / "a b.m3u8"
    f.write_text("#EXTM3U\n")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/gio" if name == "gio" else None)
    assert util.open_with_default_app(str(f))
    assert calls[-1] == ("gio", ["open", str(f)])
    monkeypatch.setattr("shutil.which", lambda name: None)
    util.open_with_default_app(str(f))
    assert calls[-1] == ("xdg-open", [str(f)])
