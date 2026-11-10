import os
import tarfile
import zipfile

import pytest

from panepilot import archives
from panepilot.fileops import COMPRESS, EXTRACT, ConflictDecision, OperationEngine


def run(kind, sources, target, options, answer=None, cancel=None):
    asked = []

    def ask(src, dst, same, suggestion):
        asked.append((src, dst))
        return answer(src, dst) if answer else ConflictDecision("skip")

    engine = OperationEngine(kind, [str(s) for s in sources], str(target), ask_conflict=ask,
                             is_cancelled=cancel, options=options)
    return engine.run(), asked


@pytest.fixture
def data(tmp_path):
    src = tmp_path / "quelle"
    (src / "ordner" / "unter").mkdir(parents=True)
    (src / "ordner" / "leer").mkdir()
    (src / "ordner" / "a.txt").write_text("A" * 5000)
    (src / "ordner" / "unter" / "b.txt").write_text("B")
    (src / "einzeln.txt").write_text("E")
    return src


def test_detection():
    assert archives.archive_format("x.ZIP") == "zip"
    assert archives.archive_format("x.tar.gz") == "tar.gz"
    assert archives.archive_format("x.tgz") == "tar.gz"
    assert archives.archive_format("x.txt") is None
    assert archives.archive_format(".zip") is None
    assert archives.archive_stem("fotos.tar.gz") == "fotos"
    assert archives.archive_stem("fotos.7z") == "fotos"


def test_unique_archive_name(tmp_path):
    assert archives.unique_archive_name(str(tmp_path), "Name", "zip") == "Name.zip"
    (tmp_path / "Name.zip").write_text("")
    (tmp_path / "Name (2).zip").write_text("")
    assert archives.unique_archive_name(str(tmp_path), "Name", "zip") == "Name (3).zip"
    assert archives.unique_archive_name(str(tmp_path), "Name", "tar.gz") == "Name.tar.gz"


@pytest.mark.parametrize("fmt", ["zip", "tar", "tar.gz", "tar.bz2", "tar.xz"])
def test_roundtrip(data, tmp_path, fmt):
    archive = tmp_path / ("paket" + archives.FORMAT_EXT[fmt])
    res, _ = run(COMPRESS, [data / "ordner", data / "einzeln.txt"], data, {"archive": str(archive), "format": fmt})
    assert not res.errors and res.created == [archive.name]
    out = tmp_path / "ziel"
    out.mkdir()
    res, asked = run(EXTRACT, [archive], out, {"jobs": [(str(archive), str(out))]})
    assert not res.errors and not asked
    assert (out / "ordner" / "a.txt").read_text() == "A" * 5000
    assert (out / "ordner" / "unter" / "b.txt").read_text() == "B"
    assert (out / "ordner" / "leer").is_dir()
    assert (out / "einzeln.txt").read_text() == "E"
    assert sorted(res.created) == ["einzeln.txt", "ordner"]
    assert not [n for n in os.listdir(out) if n.startswith(".panepilot")]  # Hilfsordner ist weg


def test_extract_into_subfolder_and_conflict(data, tmp_path):
    archive = tmp_path / "paket.zip"
    run(COMPRESS, [data / "einzeln.txt"], data, {"archive": str(archive), "format": "zip"})
    dest = tmp_path / "paket"
    res, _ = run(EXTRACT, [archive], tmp_path, {"jobs": [(str(archive), str(dest))]})
    assert res.created == ["paket"]
    assert (dest / "einzeln.txt").read_text() == "E"
    (dest / "einzeln.txt").write_text("geändert")
    res, asked = run(EXTRACT, [archive], tmp_path, {"jobs": [(str(archive), str(dest))]},
                     answer=lambda s, d: ConflictDecision("overwrite"))
    assert len(asked) == 1
    assert (dest / "einzeln.txt").read_text() == "E"


def test_zip_with_outside_paths(tmp_path):
    archive = tmp_path / "boese.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../draussen.txt", "x")
        zf.writestr("/absolut.txt", "x")
        zf.writestr("gut/ok.txt", "ok")
    out = tmp_path / "ziel"
    res, _ = run(EXTRACT, [archive], out, {"jobs": [(str(archive), str(out))]})
    assert (out / "gut" / "ok.txt").read_text() == "ok"
    assert not (tmp_path / "draussen.txt").exists()
    assert len(res.errors) == 2


def test_tar_with_escaping_link(tmp_path):
    archive = tmp_path / "boese.tar"
    with tarfile.open(archive, "w") as tar:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    out = tmp_path / "ziel"
    res, _ = run(EXTRACT, [archive], out, {"jobs": [(str(archive), str(out))]})
    assert not os.path.lexists(out / "link")
    assert res.errors


def test_cancel_removes_partial_archive(data, tmp_path):
    archive = tmp_path / "abbruch.zip"
    res, _ = run(COMPRESS, [data / "ordner"], data, {"archive": str(archive), "format": "zip"}, cancel=lambda: True)
    assert res.cancelled
    assert not archive.exists()


def test_damaged_archive(tmp_path):
    archive = tmp_path / "kaputt.zip"
    archive.write_text("kein zip")
    out = tmp_path / "kaputt"
    res, _ = run(EXTRACT, [archive], tmp_path, {"jobs": [(str(archive), str(out))]})
    assert res.errors
    assert not out.exists()  # leerer Zielordner wird wieder entfernt


@pytest.mark.skipif(archives.seven_zip() is None, reason="kein 7-Zip installiert")
def test_7z_roundtrip(data, tmp_path):
    archive = tmp_path / "paket.7z"
    res, _ = run(COMPRESS, [data / "ordner"], data, {"archive": str(archive), "format": "7z"})
    assert not res.errors and archive.exists()
    out = tmp_path / "ziel"
    res, _ = run(EXTRACT, [archive], out, {"jobs": [(str(archive), str(out))]})
    assert not res.errors
    assert (out / "ordner" / "unter" / "b.txt").read_text() == "B"


def test_missing_tools_are_reported(monkeypatch):
    monkeypatch.setattr(archives.shutil, "which", lambda prog: None)
    assert not archives.can_create("7z") and not archives.can_create("rar")
    assert not archives.can_extract("rar")
    assert archives.can_create("zip") and archives.can_extract("tar.xz")
    assert "7zip" in archives.missing_hint("7z", True)


def test_external_tool_progress_and_failure(tmp_path):
    script = tmp_path / "fake7z"
    script.write_text("#!/bin/sh\nprintf '  10%%\\b\\b\\b\\b  55%%'\necho kaputt >&2\nexit 2\n")
    script.chmod(0o755)
    got, errors = [], []
    ctx = archives._Ctx(progress=lambda n, name: got.append(n), is_cancelled=lambda: False,
                        error=lambda p, r: errors.append(r))
    with pytest.raises(archives.ArchiveError, match="kaputt"):
        archives._run_tool([str(script)], str(tmp_path), 1000, "x", ctx)
    assert sum(got) == 1000 and got[0] in (100, 550)


def test_external_tool_cancel(tmp_path):
    script = tmp_path / "slow"
    script.write_text("#!/bin/sh\nsleep 30\n")
    script.chmod(0o755)
    ctx = archives._Ctx(progress=lambda n, name: None, is_cancelled=lambda: True, error=lambda p, r: None)
    with pytest.raises(archives.Cancelled):
        archives._run_tool([str(script)], str(tmp_path), 10, "x", ctx)
