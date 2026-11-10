import os

from panepilot.fileops import COPY, DELETE, MOVE, TRASH, ConflictDecision, OperationEngine


def run(kind, sources, target="", answer=None, **kw):
    asked = []

    def ask(src, dst, same, suggestion):
        asked.append((src, dst, same, suggestion))
        return answer(src, dst, same, suggestion) if answer else ConflictDecision("skip")

    engine = OperationEngine(kind, [str(s) for s in sources], str(target), ask_conflict=ask, **kw)
    return engine.run(), asked


def test_copy_file_and_folder(tree):
    res, asked = run(COPY, [tree / "a"], tree / "b")
    assert not res.errors and not asked
    assert (tree / "b" / "a" / "sub" / "tief.txt").read_text() == "tief" * 100
    assert (tree / "a" / "eins.txt").exists()  # Original bleibt
    assert res.created == ["a"]


def test_move_folder(tree):
    res, _ = run(MOVE, [tree / "a"], tree / "b")
    assert not res.errors
    assert not (tree / "a").exists()
    assert (tree / "b" / "a" / "eins.txt").exists()


def test_conflict_skip_keeps_target(tree):
    (tree / "b" / "eins.txt").write_text("alt")
    res, asked = run(COPY, [tree / "a" / "eins.txt"], tree / "b", answer=lambda *a: ConflictDecision("skip"))
    assert len(asked) == 1 and res.skipped == 1
    assert (tree / "b" / "eins.txt").read_text() == "alt"


def test_conflict_overwrite(tree):
    (tree / "b" / "eins.txt").write_text("alt")
    run(COPY, [tree / "a" / "eins.txt"], tree / "b", answer=lambda *a: ConflictDecision("overwrite"))
    assert (tree / "b" / "eins.txt").read_text() == "eins"


def test_conflict_rename_with_given_name(tree):
    (tree / "b" / "eins.txt").write_text("alt")
    res, _ = run(COPY, [tree / "a" / "eins.txt"], tree / "b", answer=lambda *a: ConflictDecision("rename", "neu.txt"))
    assert (tree / "b" / "neu.txt").read_text() == "eins"
    assert (tree / "b" / "eins.txt").read_text() == "alt"
    assert res.created == ["neu.txt"]


def test_apply_all_is_remembered(tree):
    for name in ("eins.txt",):
        (tree / "b" / name).write_text("alt")
    (tree / "a" / "zwei.txt").write_text("neu2")
    (tree / "b" / "zwei.txt").write_text("alt2")
    res, asked = run(
        COPY,
        [tree / "a" / "eins.txt", tree / "a" / "zwei.txt"],
        tree / "b",
        answer=lambda *a: ConflictDecision("overwrite", apply_all=True),
    )
    assert len(asked) == 1
    assert (tree / "b" / "zwei.txt").read_text() == "neu2"


def test_copy_into_same_folder_never_overwrites_itself(tree):
    res, asked = run(COPY, [tree / "a" / "eins.txt"], tree / "a", answer=lambda *a: ConflictDecision("overwrite"))
    assert asked[0][2] is True  # gleiche Datei erkannt
    assert (tree / "a" / "eins.txt").read_text() == "eins"
    assert (tree / "a" / "eins (2).txt").read_text() == "eins"


def test_folder_into_itself_is_refused(tree):
    res, _ = run(COPY, [tree / "a"], tree / "a" / "sub")
    assert res.errors and not (tree / "a" / "sub" / "a").exists()


def test_merge_existing_folder(tree):
    (tree / "b" / "a").mkdir()
    (tree / "b" / "a" / "alt.txt").write_text("bleibt")
    res, asked = run(COPY, [tree / "a"], tree / "b")
    assert not asked
    assert (tree / "b" / "a" / "alt.txt").exists() and (tree / "b" / "a" / "eins.txt").exists()


def test_cancel_removes_partial_file(tree):
    big = tree / "a" / "gross.bin"
    big.write_bytes(os.urandom(3 * 1024 * 1024))
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 2

    res, _ = run(COPY, [big], tree / "b", is_cancelled=cancelled)
    assert res.cancelled
    assert not (tree / "b" / "gross.bin").exists()


def test_trash_and_delete(tree):
    trashed = []
    res, _ = run(TRASH, [tree / "a" / "eins.txt"], trash=lambda p: trashed.append(p))
    assert trashed == [str(tree / "a" / "eins.txt")] and not res.errors
    res, _ = run(DELETE, [tree / "b"])
    assert not (tree / "b").exists()


def test_symlink_copied_as_link(tree):
    os.symlink(tree / "a" / "eins.txt", tree / "a" / "link.txt")
    run(COPY, [tree / "a" / "link.txt"], tree / "b")
    assert os.path.islink(tree / "b" / "link.txt")


def test_purge_read_only_folder(tmp_path):
    """Fehler 0.5.1: Schreibgeschützter Ordner im Papierkorb ließ sich nicht leeren."""
    from panepilot.fileops import PURGE

    d = tmp_path / "ro"
    (d / "innen").mkdir(parents=True)
    (d / "innen" / "x.txt").write_text("x")
    os.chmod(d / "innen", 0o555)
    os.chmod(d, 0o555)
    res, _ = run(PURGE, [d])
    assert not res.errors
    assert not d.exists()
