import re
from pathlib import Path

from panepilot.actions import ACTION_DEFS
from panepilot.i18n import all_keys, t
from panepilot.sidebars import SIDEBARS

SRC = Path(__file__).resolve().parents[1] / "src" / "panepilot"


def used_keys():
    keys = set()
    for py in SRC.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        keys.update(re.findall(r'\bt\(\s*"([a-z_]+\.[a-z_.0-9]+)"', text))
        # bedingte Schlüssel wie t("title.move" if move else "title.copy")
        keys.update(re.findall(r'"((?:title|dialog|button|error|size|conflict|mount|sidebar|tree|fav_edit|color|drives|fkeys|open_with|column|trash|tooltip|menu|action|about)\.[a-z_0-9]+)"', text))
    keys.update(a.text_key for a in ACTION_DEFS)
    keys.update(s.text_key for s in SIDEBARS)
    from panepilot.favorites import FAV_COLORS, STYLE_FLAGS

    keys.update(f"color.{k}" for k, _ in FAV_COLORS)
    keys.update(f"fav_edit.{f}" for f in STYLE_FLAGS)
    keys.update({"menu.sidebar_left", "menu.sidebar_right", "column.name", "column.size", "column.date", "column.type"})
    return keys


def test_all_used_keys_exist_in_german():
    missing = sorted(used_keys() - all_keys("de"))
    assert not missing, f"Fehlende Texte in de.json: {missing}"


def test_placeholders_are_filled():
    assert t("status.counts", dirs=2, files=3) == "2 Ordner, 3 Dateien"
    assert t("gibt.es.nicht") == "gibt.es.nicht"
