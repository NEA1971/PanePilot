"""Zentrale Aktionen und Tastenbelegung.

Jede Funktion des Programms ist eine benannte Aktion. Menüs, Kontextmenüs und
die Tastatur greifen alle auf diese Liste zu – später auch Symbolleiste/Ribbon
und der Einstellungsdialog.

Die Standardbelegung orientiert sich an FreeCommander. Eigene Belegungen
können in ``keymap.json`` im Konfigurationsordner hinterlegt werden, z. B.::

    {"copy": ["F5"], "same_path": ["Ctrl+E", "Ctrl+Shift+E"]}

Der *Bereich* (scope) legt fest, wo eine Taste wirkt:

* ``window``    – überall im Hauptfenster (außer beim Bearbeiten von Text)
* ``list``      – nur wenn die Dateiliste den Fokus hat
* ``favorites`` – nur wenn die Favoritenleiste den Fokus hat
* ``tree``      – nur wenn die Baumansicht den Fokus hat
* ``always``    – überall, auch beim Bearbeiten der Pfadleiste
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QKeySequence

from .config import KEYMAP_FILE, load_json


@dataclass(frozen=True)
class ActionDef:
    id: str
    text_key: str
    keys: tuple[str, ...]
    scope: str


ACTION_DEFS: tuple[ActionDef, ...] = (
    # Panels
    ActionDef("switch_panel", "action.switch_panel", ("Tab",), "always"),
    ActionDef("same_path", "action.same_path", ("Ctrl+E",), "window"),
    ActionDef("swap_panels", "action.swap_panels", ("Ctrl+U",), "window"),
    # Dateioperationen
    # F1–F12 werden über die F-Tasten-Leiste belegt (FKEY_DEFAULTS), nicht hier.
    ActionDef("copy", "action.copy", (), "window"),
    ActionDef("move", "action.move", (), "window"),
    ActionDef("copy_direct", "action.copy_direct", (), "window"),
    ActionDef("move_direct", "action.move_direct", (), "window"),
    ActionDef("new_folder", "action.new_folder", (), "window"),
    ActionDef("new_textfile", "action.new_textfile", (), "window"),  # Standard: Umschalt+F4 (F-645)
    ActionDef("open_terminal", "action.open_terminal", (), "window"),  # v1.1
    ActionDef("dir_list", "action.dir_list", (), "window"),  # v1.1
    ActionDef("edit_text", "action.edit_text", (), "window"),
    ActionDef("open_with_other", "action.open_with_other", (), "window"),
    ActionDef("rename", "action.rename", (), "window"),
    ActionDef("multi_rename", "action.multi_rename", ("Ctrl+M",), "window"),
    ActionDef("meta_wizard", "action.meta_wizard", ("Ctrl+T",), "window"),
    ActionDef("rename_undo", "action.rename_undo", (), "window"),
    ActionDef("search", "action.search", ("Ctrl+F",), "window"),
    ActionDef("checksums", "action.checksums", (), "window"),
    ActionDef("properties", "action.properties", ("Alt+Return",), "window"),
    ActionDef("settings_dialog", "action.settings_dialog", (), "window"),
    ActionDef("backup_now", "action.backup_now", (), "window"),
    ActionDef("backup_restore", "action.backup_restore", (), "window"),
    ActionDef("compress", "action.compress", (), "window"),
    ActionDef("extract_here", "action.extract_here", (), "window"),
    ActionDef("extract_subfolder", "action.extract_subfolder", (), "window"),
    ActionDef("extract_to", "action.extract_to", (), "window"),
    ActionDef("delete", "action.delete", ("Del",), "list"),
    ActionDef("delete_permanent", "action.delete_permanent", ("Shift+Del",), "list"),
    ActionDef("open", "action.open", ("Return", "Enter"), "list"),
    ActionDef("tree_open", "action.open", ("Return", "Enter"), "tree"),
    ActionDef("select_all", "action.select_all", ("Ctrl+A",), "list"),
    ActionDef("clip_copy", "action.clip_copy", ("Ctrl+C",), "list"),
    ActionDef("clip_cut", "action.clip_cut", ("Ctrl+X",), "list"),
    ActionDef("clip_paste", "action.clip_paste", ("Ctrl+V",), "list"),
    # Navigation
    ActionDef("go_up", "action.go_up", ("Backspace",), "list"),
    ActionDef("back", "action.back", ("Alt+Left",), "window"),
    ActionDef("forward", "action.forward", ("Alt+Right",), "window"),
    ActionDef("edit_path", "action.edit_path", ("Ctrl+L",), "window"),
    ActionDef("refresh", "action.refresh", ("Ctrl+R",), "window"),
    # Ansicht
    ActionDef("toggle_hidden", "action.toggle_hidden", ("Ctrl+H",), "window"),
    ActionDef("toggle_sidebar", "action.toggle_sidebar", ("Alt+F",), "window"),
    ActionDef("toggle_buttonbar", "action.toggle_buttonbar", (), "window"),
    ActionDef("toggle_fkeybar", "action.toggle_fkeybar", (), "window"),
    ActionDef("toggle_toolbar", "action.toggle_toolbar", (), "window"),
    ActionDef("filter_define", "action.filter_define", (), "window"),
    ActionDef("filter_toggle", "action.filter_toggle", (), "window"),
    # Favoriten
    ActionDef("add_favorite", "action.add_favorite", ("Ctrl+B",), "window"),
    ActionDef("fav_new_group", "action.fav_new_group", (), "window"),
    ActionDef("fav_open", "action.fav_open", ("Return", "Enter"), "favorites"),
    ActionDef("fav_edit", "action.fav_edit", (), "window"),
    ActionDef("fav_rename", "action.fav_rename", ("F2",), "favorites"),
    ActionDef("fav_delete", "action.fav_delete", ("Del",), "favorites"),
    # Papierkorb
    ActionDef("open_trash", "action.open_trash", (), "window"),
    ActionDef("trash_restore", "action.trash_restore", (), "window"),
    ActionDef("trash_purge", "action.trash_purge", (), "window"),
    ActionDef("trash_empty", "action.trash_empty", (), "window"),
    # Ansicht
    ActionDef("toggle_single", "action.toggle_single", (), "window"),
    # Programm
    ActionDef("help", "action.help", (), "always"),  # Standard: F1 (F-Tasten-Leiste)
    ActionDef("help_online", "action.help_online", (), "window"),
    ActionDef("donate", "action.donate", (), "window"),
    ActionDef("about", "action.about", (), "window"),
    ActionDef("quit", "action.quit", ("Ctrl+Q",), "always"),
)

ACTIONS_BY_ID = {a.id: a for a in ACTION_DEFS}

FKEYS = tuple(f"F{i}" for i in range(1, 13))
# Schichten der F-Tasten (F-640): normal, Umschalt, Strg, Alt – als Präfix der Tastenbezeichnung
LAYERS = ("", "Shift+", "Ctrl+", "Alt+")
ALL_FKEYS = tuple(layer + key for layer in LAYERS for key in FKEYS)
# Von GNOME (Mutter) abgefangene Kombinationen – kommen per Tastatur nicht an (F-644)
GNOME_RESERVED = frozenset({"Alt+F1", "Alt+F2", "Alt+F4", "Alt+F5", "Alt+F6", "Alt+F7", "Alt+F8", "Alt+F10"})

# Startbelegung der F-Tasten (nach FreeCommander). None = frei.
FKEY_DEFAULTS: dict[str, str | None] = {k: None for k in ALL_FKEYS}
FKEY_DEFAULTS.update({
    "F1": "help", "F2": "rename", "F4": "edit_text", "F5": "copy", "F6": "move", "F7": "new_folder", "F8": "delete",
    "Shift+F4": "new_textfile",
})


def split_fkey(key: str) -> tuple[str, str]:
    """'Shift+F5' → ('Shift+', 'F5')."""
    for layer in LAYERS[1:]:
        if key.startswith(layer):
            return layer, key[len(layer):]
    return "", key

# Diese Aktionen sind an eine bestimmte Ansicht gebunden und nicht auf F-Tasten legbar.
NOT_ASSIGNABLE = {"fav_open", "fav_rename", "fav_delete", "tree_open", "open", "switch_panel"}


def normalize(key: str) -> str:
    """Einheitliche Schreibweise, z. B. 'ctrl+e' → 'Ctrl+E'."""
    return QKeySequence(key).toString(QKeySequence.SequenceFormat.PortableText)


class KeyMap:
    def __init__(self, overrides: dict | None = None) -> None:
        if overrides is None:
            overrides = load_json(KEYMAP_FILE, {})
        self._keys: dict[str, tuple[str, ...]] = {}
        for action in ACTION_DEFS:
            keys = action.keys
            custom = overrides.get(action.id) if isinstance(overrides, dict) else None
            if isinstance(custom, list) and all(isinstance(k, str) for k in custom):
                keys = tuple(custom)
            self._keys[action.id] = tuple(n for n in (normalize(k) for k in keys) if n)

    def keys_for(self, action_id: str) -> tuple[str, ...]:
        return self._keys.get(action_id, ())

    def display(self, action_id: str) -> str:
        keys = self.keys_for(action_id)
        if not keys:
            return ""
        return QKeySequence(keys[0]).toString(QKeySequence.SequenceFormat.NativeText)

    def actions_for_key(self, key: str) -> list[ActionDef]:
        return [ACTIONS_BY_ID[aid] for aid, keys in self._keys.items() if key in keys]
