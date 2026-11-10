import os

import pytest

from panepilot import multirename as mr
from panepilot.multirename import Item, RenameOptions


def names(items, opts, existing=None, now=0):
    res = mr.compute(items, opts, existing or {i.name for i in items}, now=now)
    return [r.new for r in res], res


FILES = [Item("IMG_0001.JPG", False, mtime=1793000000), Item("IMG_0002.jpg", False, mtime=1793086400),
         Item("Urlaub Fotos", True, mtime=1793000000)]


def test_pattern_counter_date():
    opts = RenameOptions(pattern="Urlaub_[C]_[D]", counter_start=5, counter_step=5, counter_digits=3,
                         date_format="JJJJ-MM-TT")
    new, _ = names(FILES, opts)
    d0 = mr.format_date(1793000000, "JJJJ-MM-TT")
    assert new[0] == f"Urlaub_005_{d0}.JPG"
    assert new[1].startswith("Urlaub_010_") and new[1].endswith(".jpg")
    assert new[2].startswith("Urlaub_015_")  # Ordner: keine Endung
    assert "." not in new[2].replace(d0, "")


def test_substrings_and_ext_pattern():
    opts = RenameOptions(pattern="[N5-]-[N1-3]-[N2]", ext_pattern="jpeg")
    new, _ = names(FILES[:1], opts)
    assert new == ["0001-IMG-M.jpeg"]


def test_search_modes_and_case():
    opts = RenameOptions(search="img_", replace="Foto ", case_mode=mr.CASE_WORDS)
    assert names(FILES[:2], opts)[0] == ["Foto 0001.JPG", "Foto 0002.jpg"]
    opts = RenameOptions(search="I*_", search_mode=mr.SEARCH_WILDCARD, replace="")
    assert names(FILES[:1], opts)[0] == ["0001.JPG"]
    opts = RenameOptions(search=r"IMG_(\d+)", search_mode=mr.SEARCH_REGEX, replace=r"\1_bild")
    assert names(FILES[:1], opts)[0] == ["0001_bild.JPG"]
    opts = RenameOptions(search="0", replace="x", replace_all=False)
    assert names(FILES[:1], opts)[0] == ["IMG_x001.JPG"]
    opts = RenameOptions(search="img", replace="x", search_case=True)
    assert names(FILES[:1], opts)[0] == ["IMG_0001.JPG"]


def test_case_and_extension_option():
    opts = RenameOptions(case_mode=mr.CASE_LOWER)
    assert names(FILES[:1], opts)[0] == ["img_0001.JPG"]  # Endung bleibt
    opts = RenameOptions(case_mode=mr.CASE_LOWER, include_ext=True)
    assert names(FILES[:1], opts)[0] == ["img_0001.jpg"]
    opts = RenameOptions(case_mode=mr.CASE_FIRST)
    assert names([Item("hALLO wELT.txt", False)], opts)[0] == ["Hallo welt.txt"]
    assert mr.change_case("mein_urlaub bild", mr.CASE_WORDS) == "Mein_Urlaub Bild"


def test_conflicts():
    items = [Item("a.txt", False), Item("b.txt", False)]
    new, res = names(items, RenameOptions(pattern="x"))
    assert [r.status for r in res] == [mr.CONFLICT, mr.CONFLICT]
    assert res[0].reason == "rename.err_duplicate"
    _, res = names(items[:1], RenameOptions(pattern="c"), existing={"a.txt", "b.txt", "c.txt"})
    assert res[0].reason == "rename.err_exists"
    _, res = names(items[:1], RenameOptions(pattern="x/y"))
    assert res[0].reason == "rename.err_chars"
    _, res = names(items[:1], RenameOptions(pattern="", ext_pattern=""))
    assert res[0].reason == "rename.err_empty"
    # Ringtausch ist kein Konflikt
    _, res = names(items, RenameOptions(search="a", replace="b"), existing={"a.txt", "b.txt"})
    assert res[0].status == mr.CONFLICT  # a→b, b bleibt b: doppelt
    swap = [Item("a.txt", False), Item("b.txt", False)]
    opts = RenameOptions(search="[ab]", search_mode=mr.SEARCH_REGEX, replace="")
    assert opts and mr.validate(opts) is None
    _, res = names([Item("x", False)], RenameOptions(), existing={"x"})
    assert res[0].status == mr.SAME
    del swap


def test_validate():
    assert mr.validate(RenameOptions(search="(", search_mode=mr.SEARCH_REGEX))
    assert mr.validate(RenameOptions(search="(a)", search_mode=mr.SEARCH_REGEX, replace=r"\2"))
    assert mr.validate(RenameOptions(search="(a)", search_mode=mr.SEARCH_REGEX, replace=r"\1")) is None
    assert mr.validate(RenameOptions(search="(", search_mode=mr.SEARCH_TEXT)) is None


def test_date_sources():
    item = Item("a.txt", False, mtime=1793000000, btime=1700000000)
    assert mr.new_name(item, RenameOptions(pattern="[D]", date_source=mr.DATE_CREATED), 0, 0, None).startswith("2023")
    item.btime = -1
    assert mr.new_name(item, RenameOptions(pattern="[D]", date_source=mr.DATE_CREATED), 0, 0, None).startswith("2026")
    assert mr.format_date(1793000000, "TT.MM.JJ hh-mm-ss").count("-") == 2


def test_options_roundtrip():
    opts = RenameOptions(pattern="x[C]", counter_digits=4, include_ext=True, case_mode=mr.CASE_UPPER)
    assert RenameOptions.from_dict(opts.to_dict()) == opts
    bad = RenameOptions.from_dict({"counter_digits": True, "case_mode": "quatsch", "pattern": 3})
    assert bad == RenameOptions()


def test_perform_swap_and_case_only(tmp_path):
    tmp_path = tmp_path / "r"
    tmp_path.mkdir()
    (tmp_path / "a.txt").write_text("A")
    (tmp_path / "b.txt").write_text("B")
    (tmp_path / "Foto.JPG").write_text("F")
    done, errors = mr.perform(str(tmp_path), [("a.txt", "b.txt"), ("b.txt", "a.txt"), ("Foto.JPG", "foto.jpg")])
    assert not errors and len(done) == 3
    assert (tmp_path / "a.txt").read_text() == "B" and (tmp_path / "b.txt").read_text() == "A"
    assert sorted(os.listdir(tmp_path)) == ["a.txt", "b.txt", "foto.jpg"]


def test_perform_does_not_overwrite(tmp_path):
    tmp_path = tmp_path / "r"
    tmp_path.mkdir()
    (tmp_path / "a.txt").write_text("A")
    (tmp_path / "c.txt").write_text("C")
    done, errors = mr.perform(str(tmp_path), [("a.txt", "c.txt")])
    assert not done and errors[0][0] == "a.txt"
    assert (tmp_path / "a.txt").read_text() == "A" and (tmp_path / "c.txt").read_text() == "C"
    assert sorted(os.listdir(tmp_path)) == ["a.txt", "c.txt"]


def test_replace_first_occurrence_by_default():
    opts = RenameOptions(search=r"_[^-]*-", replace="_-", search_mode=mr.SEARCH_REGEX)
    assert not opts.replace_all
    new, _ = names([Item("PanePilot_Anforderungen-v0.1_2026-11-02a.docx", False)], opts)
    assert new == ["PanePilot_-v0.1_2026-11-02a.docx"]
