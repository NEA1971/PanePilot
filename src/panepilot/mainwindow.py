"""Hauptfenster: zwei Panels mit Seitenleisten, Menüs, Tastatursteuerung."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QKeyCombination, QMimeData, QObject, QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QVBoxLayout,
    QWidget,
    QLineEdit,
    QMainWindow,
    QMenu,
    QSplitter,
)

from . import __version__
from .actions import (ACTION_DEFS, ACTIONS_BY_ID, ALL_FKEYS, FKEY_DEFAULTS, FKEYS, GNOME_RESERVED, LAYERS,
                      NOT_ASSIGNABLE, KeyMap, split_fkey)
from . import apps as desktop_apps
from .bars import ButtonBar, FKeyBar, layer_from_modifiers
from .toolbar import MainToolBar, ToolbarDialog
from .config import STATE_FILE, Settings, config_dir, load_json, save_json
from . import archives
from .dialogs import AboutDialog, CompressDialog, CopyMoveDialog, ExtractToDialog, FavoriteEditDialog, OpenWithDialog, ask_text, confirm, show_error, show_info
from .favorites import FAV_COLORS, FavNode, FavoritesModel, FavoritesView
from .foldertree import FolderTreeView
from .filepanel import FilePanel, FileView
from .filemodel import COLUMN_COUNT
from .fileops import COMPRESS, COPY, DELETE, EXTRACT, MOVE, PURGE, RESTORE, TRASH
from .trash import TRASH_URI, Trash, is_trash_uri
from .i18n import t
from .icons import IconProvider, app_icon
from .operations import OperationController
from .mounts import MountManager
from .metacontrol import META_ALLOWED, MODE_META, MetaWizardMixin
from .favsets import FavoriteSets
from .sidebars import MODE_FAVORITES, MODE_OFF, MODE_TREE, SIDEBARS, SidebarHost, SidebarPane

MODE_RENAME = "rename"  # Seitenleiste „Mehrfach umbenennen“ – nicht im Menü wählbar
MODE_SEARCH = "search"  # Werkzeug-Seitenleisten (F-800), ebenfalls nicht im Menü
MODE_CHECKSUM = "checksum"
from .util import nearest_existing_dir, open_with_default_app, unique_name
from .platform import IS_WINDOWS, WINDOWS_DISABLED_ACTIONS

SIDES = ("left", "right")
GNOME_CLIP = "x-special/gnome-copied-files"
KDE_CUT = "application/x-kde-cutselection"

STYLE = """
#panelHeader { border-radius: 4px; }
#panelHeader[active="true"] { background: palette(highlight); }
#panelHeader[filtered="true"] #pathEdit { color: #D32F2F; font-weight: bold; }
#sidebarTitle { border-bottom: 1px solid palette(mid); }
#sidebarTitleButton { font-weight: bold; padding: 2px 4px; }
#sidebarClose { padding: 0px 4px; }
#panelStatus { padding: 1px 4px; }
"""

MODIFIER_KEYS = {
    Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
    Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock, Qt.Key.Key_NumLock, Qt.Key.Key_unknown,
}


class EmptyHintFavoritesView(FavoritesView):
    """Zeigt einen Hinweis, solange noch keine Favoriten angelegt sind."""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.model().rowCount() == 0:
            painter = QPainter(self.viewport())
            painter.setPen(self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))
            rect = self.viewport().rect().adjusted(8, 8, -8, -8)
            painter.drawText(rect, Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, t("favorites.empty_hint"))
            painter.end()


@dataclass
class Side:
    name: str
    panel: FilePanel
    sidebar: SidebarHost
    splitter: QSplitter


class KeyFilter(QObject):
    """Leitet Tastendrücke über die zentrale Tastenbelegung an die Aktionen weiter."""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window = window

    def _resolve(self, event) -> str | None:
        key = event.key()
        if key in MODIFIER_KEYS or key == 0:
            return None
        focus = QApplication.focusWidget()
        if focus is None or focus.window() is not self.window:
            return None
        if self.window.meta_mode is not None:
            return None  # Meta-Wizard: Tasten gehören den Feldern und der Titelliste (Strg+S über eigenes Kürzel)
        if QApplication.activePopupWidget() is not None or QApplication.activeModalWidget() is not None:
            return None
        in_edit = isinstance(focus, QLineEdit)
        if in_edit and focus.objectName() != "pathEdit":
            return None  # Umbenennen in der Liste o. Ä.: alle Tasten dem Eingabefeld überlassen
        in_list = isinstance(focus, FileView)
        in_fav = isinstance(focus, FavoritesView)
        in_tree = isinstance(focus, FolderTreeView)
        if in_fav and focus.state() == focus.State.EditingState:
            return None
        mods = event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        seq = QKeySequence(QKeyCombination(mods, Qt.Key(key))).toString(QKeySequence.SequenceFormat.PortableText)
        # F-Tasten aller Schichten: Belegung der F-Leiste hat Vorrang (F-646)
        if not in_edit and seq in ALL_FKEYS and self.window.fkey_action(seq):
            return self.window.fkey_action(seq)
        for action in self.window.keymap.actions_for_key(seq):
            if action.scope == "always":
                return action.id
            if action.scope == "window" and not in_edit:
                return action.id
            if action.scope == "list" and in_list:
                return action.id
            if action.scope == "favorites" and in_fav:
                return action.id
            if action.scope == "tree" and in_tree:
                return action.id
        return None

    def eventFilter(self, obj, event) -> bool:
        etype = event.type()
        if (etype == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape
                and self.window.rename_mode is not None and QApplication.activeModalWidget() is None
                and QApplication.activePopupWidget() is None):
            focus = QApplication.focusWidget()
            if focus is not None and focus.window() is self.window:
                self.window.leave_rename_mode()  # Esc = Abbrechen (F-704)
                return True
        if (etype == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape
                and self.window.meta_mode is not None and QApplication.activeModalWidget() is None
                and QApplication.activePopupWidget() is None):
            focus = QApplication.focusWidget()
            if focus is not None and focus.window() is self.window:
                self.window.meta_close()  # Esc = Schließen mit Rückfrage (F-925)
                return True
        if etype in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and event.key() in (
            Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt
        ):
            # F-Leiste zeigt die Schicht der gehaltenen Zusatztaste (F-641)
            mods = QApplication.queryKeyboardModifiers()
            self.window.fkey_bar.set_layer(layer_from_modifiers(mods))
        elif etype == QEvent.Type.ApplicationStateChange or (
            etype == QEvent.Type.WindowDeactivate and obj is self.window
        ):
            self.window.fkey_bar.set_layer("")
        if etype == QEvent.Type.MouseButtonPress and event.button() in (
            Qt.MouseButton.BackButton, Qt.MouseButton.ForwardButton
        ):
            # Maus-Seitentasten blättern im Verlauf des Panels unter dem Mauszeiger (F-251)
            side = self.window.side_of_widget(obj)
            if side is not None:
                panel = self.window.sides[side].panel
                self.window.set_active_side(side)
                if event.button() == Qt.MouseButton.BackButton:
                    panel.back()
                else:
                    panel.forward()
                return True
            return False
        if etype == QEvent.Type.ShortcutOverride:
            if self._resolve(event):
                event.accept()
                return True
            return False
        if etype == QEvent.Type.KeyPress:
            if obj is not QApplication.focusWidget():
                return False
            action_id = self._resolve(event)
            if action_id:
                self.window.trigger(action_id)
                return True
        return False


class MainWindow(MetaWizardMixin, QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings()
        self.keymap = KeyMap()
        self.icons = IconProvider()
        self.setWindowIcon(app_icon())
        self.setStyleSheet(STYLE)
        self.mounts = MountManager(self)
        self.icons.mounts = self.mounts
        self.trash = Trash(self._trash_mount_points, self._trash_network_mount_points)
        self._trash_full = None
        self._network_trash_full = False
        self.fav_sets = FavoriteSets(self.icons, parent=self)
        self.fav_set: dict[str, str] = {s: self.fav_sets.resolve(None) for s in SIDES}
        self.fav_sets.changed.connect(self._update_fav_titles)
        self.fav_sets.renamed.connect(self._on_fav_set_renamed)
        self.fav_sets.removed.connect(self._on_fav_set_removed)
        self.last_sidebar_mode: dict[str, str] = {s: MODE_FAVORITES for s in SIDES}
        self.ops = OperationController(self)
        self.ops.finished.connect(self._on_operation_finished)
        self.active_side = "left"
        self.rename_mode = None  # dict mit dem vorherigen Zustand, solange „Mehrfach umbenennen“ läuft
        self.tool_mode: dict[str, dict] = {}  # Seite → {"mode", "sidebar", "inner"} für Suche/Prüfsummen
        self._search_thread = None
        self.last_rename = None  # (Ordner, [(alt, neu)]) für „Rückgängig“ (F-733)

        stored = self.settings.get("fkeys")
        self.fkeys: dict[str, str | None] = dict(FKEY_DEFAULTS)
        if isinstance(stored, dict):
            for k, v in stored.items():
                if k in ALL_FKEYS and (v is None or v in ACTIONS_BY_ID):
                    self.fkeys[k] = v

        self.outer = QSplitter(Qt.Orientation.Horizontal)
        self.outer.setChildrenCollapsible(False)
        self.sides: dict[str, Side] = {}
        self.button_bar = ButtonBar()
        self.button_bar.triggered.connect(self.trigger)
        self.button_bar.trash_clicked.connect(self.do_open_trash)
        self.button_bar.trash_dropped.connect(self._trash_paths)
        self.button_bar.trash_menu.connect(self._trash_button_menu)
        self.single_mode = False
        for name in SIDES:
            self.sides[name] = self._build_side(name)
        self.outer.addWidget(self.sides["left"].splitter)
        self.outer.addWidget(self.button_bar)
        self.outer.addWidget(self.sides["right"].splitter)
        self.outer.setStretchFactor(0, 1)
        self.outer.setStretchFactor(1, 0)
        self.outer.setStretchFactor(2, 1)
        self.fkey_bar = FKeyBar()
        self.fkey_bar.triggered.connect(lambda key: self.trigger(self.fkeys.get(key) or ""))
        self.fkey_bar.assign_requested.connect(self._assign_fkey_menu)
        central = QWidget(self)
        vbox = QVBoxLayout(central)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(2)
        vbox.addWidget(self.outer, 1)
        vbox.addWidget(self.fkey_bar)
        self.setCentralWidget(central)

        self.qactions: dict[str, QAction] = {}
        self._create_actions()
        self._create_menus()
        self._create_toolbar()

        self.key_filter = KeyFilter(self)
        QApplication.instance().installEventFilter(self.key_filter)
        QApplication.instance().focusChanged.connect(self._on_focus_changed)

        self.mounts.changed.connect(self._on_mounts_changed)
        self._trash_timer = QTimer(self)
        self._trash_timer.setInterval(2000)
        self._trash_timer.timeout.connect(self.update_trash_state)
        self._trash_timer.start()
        self._restore_state()
        self._init_column_profiles()
        self.update_network_trash_state()
        self._update_nav_actions()

    # --- Aufbau --------------------------------------------------------------------------
    def _build_side(self, name: str) -> Side:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        sidebar = SidebarHost({
            MODE_FAVORITES: lambda n=name: self._make_favorites_view(n),
            MODE_TREE: lambda n=name: self._make_tree_view(n),
            MODE_RENAME: lambda n=name: self._make_rename_pane(n),
            MODE_SEARCH: lambda n=name: self._make_search_pane(n),
            MODE_CHECKSUM: lambda n=name: self._make_checksum_pane(n),
            MODE_META: lambda n=name: self._make_meta_pane(n),
        })
        panel = FilePanel(name, self.icons)
        panel.mounts = self.mounts
        panel.trash = self.trash
        self._apply_panel_options(panel)
        splitter.addWidget(sidebar)
        splitter.addWidget(panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        panel.focus_entered.connect(lambda n=name: self.set_active_side(n))
        panel.path_changed.connect(lambda p, n=name: self._on_panel_path_changed(n, p))
        panel.context_menu_requested.connect(lambda pos, n=name: self._file_context_menu(n, pos))
        panel.drop_requested.connect(self._on_drop)
        panel.open_file_requested.connect(self._open_file)
        panel.message.connect(lambda title, text: show_error(self, title, text))
        panel.filter_changed.connect(lambda n=name: self._on_filter_changed(n))
        panel.model.modelReset.connect(lambda n=name: self._on_filter_changed(n))
        return Side(name, panel, sidebar, splitter)

    def _make_favorites_view(self, side: str) -> SidebarPane:
        view = EmptyHintFavoritesView(self.fav_sets.model(self.fav_set[side]))
        view.setObjectName(f"favorites_{side}")
        view.open_link.connect(lambda node, s=side, v=view: self._open_favorite(s, node, v.fav_model))
        view.focus_entered.connect(lambda s=side: self.set_active_side(s))
        view.customContextMenuRequested.connect(lambda pos, s=side, v=view: self._favorites_context_menu(s, v, pos))
        pane = self._pane(side, view, "")
        for w in (pane.title_bar, pane.title_button):
            w.customContextMenuRequested.connect(
                lambda pos, s=side, src=w: self._fav_title_menu(s, src.mapToGlobal(pos)))
        self._update_fav_title(side, pane)
        return pane

    def _pane(self, side: str, view, title: str) -> SidebarPane:
        pane = SidebarPane(view, title)
        pane.setObjectName(f"pane_{view.objectName()}")
        pane.close_button.setToolTip(t("sidebar.close"))
        pane.close_button.clicked.connect(lambda _c=False, s=side: self.set_sidebar_mode(s, MODE_OFF))
        return pane

    # --- Werkzeug-Seitenleisten: Suche und Prüfsummen (F-800 ff.) ---------------------------------
    def _open_tool(self, side: str, mode: str):
        s = self.sides[side]
        current = self.tool_mode.get(side)
        if current and current["mode"] == mode:
            return s.sidebar.widget_for(mode)
        if current:
            self.close_tool(side)
        self.tool_mode[side] = {"mode": mode, "sidebar": s.sidebar.mode, "inner": s.splitter.sizes()}
        s.sidebar.set_mode(mode)
        total = sum(s.splitter.sizes())
        if s.splitter.sizes()[0] < 360:
            s.splitter.setSizes([360, max(total - 360, 200)])
        return s.sidebar.widget_for(mode)

    def close_tool(self, side: str, navigate_back: bool = True) -> None:
        state = self.tool_mode.pop(side, None)
        if state is None:
            return
        s = self.sides[side]
        pane = s.sidebar.widget_for(state["mode"])
        if state["mode"] == MODE_SEARCH:
            self._stop_search()
            self.settings.set("search_last", pane.options().to_dict())
            if navigate_back and s.panel.search_mode:
                s.panel.navigate(s.panel.model.search_base)
        elif state["mode"] == MODE_CHECKSUM:
            pane.stop()
            for other in self.sides.values():
                try:
                    other.panel.view.selectionModel().currentChanged.disconnect(self._checksum_cursor_changed)
                except (RuntimeError, TypeError):
                    pass
        s.sidebar.set_mode(state["sidebar"])
        s.splitter.setSizes(state["inner"])
        s.panel.view.setFocus()

    # Suche
    def _make_search_pane(self, side: str):
        from .toolpanes import SearchPane

        pane = SearchPane()
        pane.close_clicked.connect(lambda s=side: self.close_tool(s))
        pane.start_clicked.connect(lambda s=side: self.start_search(s))
        pane.stop_clicked.connect(self._stop_search)
        pane.save_profile_clicked.connect(lambda s=side: self._save_search_profile(s))
        pane.delete_profile_clicked.connect(lambda s=side: self._delete_search_profile(s))
        return pane

    def do_search(self) -> None:
        from .search import SearchOptions

        side = self.active_side
        panel = self.active
        if panel.in_trash:
            return
        fresh = self.tool_mode.get(side, {}).get("mode") != MODE_SEARCH
        pane = self._open_tool(side, MODE_SEARCH)
        if fresh:
            last = SearchOptions.from_dict(self.settings.get("search_last"))
            last.network = False  # Netzfreigaben nur bewusst je Suche oder über ein Profil (F-880)
            pane.set_options(last)
        base = panel.model.search_base if panel.search_mode else panel.current_path
        pane.base_label.setText(t("search.in", path=base))
        pane.name.setFocus()
        pane.name.selectAll()

    def start_search(self, side: str) -> None:
        from .search import SearchThread

        s = self.sides[side]
        pane = s.sidebar.widget_for(MODE_SEARCH)
        opts = pane.options()
        if opts.error():
            return
        self._stop_search()
        self.settings.set("search_last", opts.to_dict())
        panel = s.panel
        base = panel.model.search_base if panel.search_mode else panel.current_path
        panel.show_search_results(base)
        pane.base_label.setText(t("search.in", path=base))
        exclude = set() if opts.network else self.mounts.network_mount_points()
        thread = SearchThread(base, opts, self, exclude=exclude)
        self._search_thread = thread
        self._search_side = side
        self._search_count = 0
        thread.found.connect(lambda paths, p=panel: self._search_found(p, paths))
        thread.progress.connect(lambda folder, n, pn=pane, b=base: pn.summary.setText(
            t("search.running", folder=os.path.relpath(folder, b) if folder != b else ".", n=self._search_count)))
        thread.finished_search.connect(lambda complete, skipped, p=panel, pn=pane: self._search_done(p, pn, complete, skipped))
        pane.set_running(True)
        pane.summary.setToolTip("")
        thread.start()

    def _search_found(self, panel, paths: list[str]) -> None:
        from .filemodel import entry_from_path

        entries = [e for e in (entry_from_path(p, self.icons) for p in paths) if e is not None]
        self._search_count += len(entries)
        panel.add_search_results(entries)

    def _search_done(self, panel, pane, complete: bool, skipped: list[str]) -> None:
        self._search_thread = None
        pane.set_running(False)
        panel.finish_search()
        text = t("search.done" if complete else "search.stopped", n=self._search_count)
        if skipped:
            # Hinweis auf übersprungene große Dateien (A-3)
            text += "\n" + t("search.skipped", n=len(skipped))
            pane.summary.setToolTip("\n".join(skipped[:30]) + ("\n…" if len(skipped) > 30 else ""))
        pane.summary.setText(text)

    def _stop_search(self) -> None:
        thread = self._search_thread
        if thread is not None:
            thread.stop()
            thread.wait(5000)
            QApplication.processEvents()
        self._search_thread = None

    def jump_to_found_folder(self) -> None:
        panel = self.active
        entry = panel.current_entry()
        if entry is None or not panel.search_mode:
            return
        side = self.active_side
        folder, name = os.path.dirname(entry.path), entry.name
        self.close_tool(side, navigate_back=False)
        panel.navigate(folder, select_name=name)

    def _save_search_profile(self, side: str) -> None:
        pane = self.sides[side].sidebar.widget_for(MODE_SEARCH)
        name = ask_text(self, t("rename.profile_save_title"), t("rename.profile_name"),
                        pane.current_profile() or t("rename.profile_default"))
        if not name or not name.strip():
            return
        name = name.strip()
        if any(c in name for c in '/\\:*?"<>|') or name.startswith("."):
            show_error(self, t("rename.profile_save_title"), t("favsets.error_chars", name=name))
            return
        pane.save_profile(name)

    def _delete_search_profile(self, side: str) -> None:
        pane = self.sides[side].sidebar.widget_for(MODE_SEARCH)
        name = pane.current_profile()
        if not name or not confirm(self, t("rename.profile_delete_title"), t("rename.profile_delete_confirm", name=name),
                                   yes_key="button.delete"):
            return
        try:
            pane.delete_profile(name)
        except OSError as exc:
            show_error(self, t("rename.profile_delete_title"), exc.strerror or str(exc))

    # Prüfsummen
    def _make_checksum_pane(self, side: str):
        from .toolpanes import ChecksumPane

        pane = ChecksumPane()
        pane.close_clicked.connect(lambda s=side: self.close_tool(s))
        return pane

    def do_checksums(self) -> None:
        side = self.active_side
        panel = self.active
        if panel.in_trash:
            return
        fresh = self.tool_mode.get(side, {}).get("mode") != MODE_CHECKSUM
        pane = self._open_tool(side, MODE_CHECKSUM)
        if fresh:
            # Beide Fenster beobachten: die Prüfsummen folgen dem aktiven Fenster (v0.8.1)
            for s in self.sides.values():
                s.panel.view.selectionModel().currentChanged.connect(self._checksum_cursor_changed)
        self._checksum_side = side
        self._checksum_cursor_changed()
        pane.compare.setFocus()

    def _checksum_cursor_changed(self, *_args) -> None:
        source = getattr(self, "_checksum_side", self.active_side)
        if source not in self.sides or not self.sides[source].panel.isVisible():
            source = self.active_side
        panel = self.sides[source].panel
        for side, state in self.tool_mode.items():
            if state["mode"] != MODE_CHECKSUM:
                continue
            pane = self.sides[side].sidebar.widget_for(MODE_CHECKSUM)
            e = None if panel.in_trash else panel.current_entry()
            if e is None or e.is_parent:
                pane.show_file(None)
            else:
                pane.show_file(e.path, e.is_dir)

    # --- Eigenschaften (F-870 ff.) ------------------------------------------------------------
    def do_properties(self) -> None:
        from .propdialog import PropertiesDialog

        panel = self.active
        entries = [e for e in panel.target_entries() if not e.is_parent]
        paths = [e.path for e in entries] or ([panel.current_path] if not panel.in_trash else [])
        if not paths:
            return
        dlg = PropertiesDialog(self, paths, read_only=panel.in_trash)
        dlg.exec()
        panel.refresh()
        if dlg.edit_in_meta:
            self.do_meta_wizard(paths)

    # --- Einstellungen, Sprache, Sicherung (F-840 ff.) ------------------------------------------
    def _fill_language_menu(self) -> None:
        from .i18n import SYSTEM, languages

        menu = self.language_menu
        menu.clear()
        group = QActionGroup(menu)
        current = self.settings.get("language") or SYSTEM
        entries = [(SYSTEM, t("settings.lang_system"))] + [
            (code, info.name) for code, info in sorted(languages().items(), key=lambda kv: kv[1].name.casefold())]
        for code, name in entries:
            act = menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(code == current)
            group.addAction(act)
            act.triggered.connect(lambda _c=False, c=code: self.change_language(c))

    def change_language(self, code: str) -> None:
        if code == (self.settings.get("language") or "system"):
            return
        self.settings.set("language", code)
        if confirm(self, t("settings.lang_changed_title"), t("settings.lang_changed"), yes_key="button.restart_now"):
            self.restart()

    def restart(self) -> None:
        """PanePilot neu starten (Sprache, Wiederherstellen)."""
        import sys

        from PySide6.QtCore import QProcess

        from .util import child_environment

        appimage = os.environ.get("APPIMAGE")
        if appimage:
            program, args = appimage, []
        elif getattr(sys, "frozen", False):
            program, args = sys.executable, sys.argv[1:]
        else:
            program, args = sys.executable, ["-m", "panepilot"] + sys.argv[1:]
        proc = QProcess()
        proc.setProgram(program)
        proc.setArguments(args)
        proc.setProcessEnvironment(child_environment())
        proc.startDetached()
        self.close()
        QApplication.quit()

    def do_settings_dialog(self) -> None:
        from .settingsdialog import SettingsDialog

        SettingsDialog(self).exec()

    def open_backup_settings(self) -> None:
        """Einstellungen → Reiter „Sicherung“ (dort liegt die Liste der Sicherungen)."""
        from .settingsdialog import SettingsDialog

        dlg = SettingsDialog(self)
        dlg.tabs.setCurrentIndex(dlg.tabs.count() - 1)
        dlg.exec()

    def apply_settings(self, assign: dict[str, str], language: str) -> None:
        """Nach „OK“ im Einstellungsfenster."""
        from . import colprofiles as cp
        from .util import set_size_unit

        set_size_unit(str(self.settings.get("size_unit")))
        names = cp.names()
        for side in SIDES:
            panel = self.sides[side].panel
            name = assign.get(side) if assign.get(side) in names else panel.column_profile
            if name not in names and names:
                name = cp.DEFAULT_PROFILE if cp.DEFAULT_PROFILE in names else names[0]
            if name:
                panel.apply_profile(name, cp.load(name))
            panel.refresh()
        if language and language != (self.settings.get("language") or "system"):
            self.change_language(language)

    def _backup_folder(self):
        from .backup import backup_folder

        return backup_folder(self.settings.get("backup_dir") or "")

    def auto_backup(self) -> None:
        """Beim ersten Start eines Tages (F-852)."""
        import datetime as _dt

        from . import backup

        today = _dt.date.today().isoformat()
        if self.settings.get("last_auto_backup") == today:
            return
        folder = self._backup_folder()
        if not backup.folder_reachable(folder, self.mounts):
            self._auto_backup_failed(today, t("backup.unreachable", folder=str(folder)),
                                     t("backup.reason_unreachable", folder=str(folder)))
            return
        try:
            backup.create_backup(folder, auto=True)
            backup.prune(folder, int(self.settings.get("backup_keep") or 30))
            self.settings.set("last_auto_backup", today)
            if self.settings.get("backup_last_error"):
                self.settings.set("backup_last_error", {})
        except OSError as exc:
            reason = exc.strerror or str(exc)
            self._auto_backup_failed(today, t("backup.failed", reason=reason), reason)

    def _auto_backup_failed(self, today: str, message: str, reason: str) -> None:
        """Hinweis in der Statuszeile (1 Minute) und Vermerk für den Reiter „Sicherung“ (v0.8.1)."""
        self.statusBar().showMessage(message, 60000)
        self.settings.set("backup_last_error", {"date": today, "reason": reason})

    def do_backup_now(self, parent=None) -> None:
        from . import backup

        parent = parent or self
        folder = self._backup_folder()
        if not backup.folder_reachable(folder, self.mounts):
            show_error(parent, t("title.backup"), t("backup.unreachable", folder=str(folder)))
            return
        try:
            path = backup.create_backup(folder, auto=False)
        except OSError as exc:
            show_error(parent, t("title.backup"), t("backup.failed", reason=exc.strerror or str(exc)))
            return
        show_info(parent, t("title.backup"), t("backup.done", path=str(path)))

    def do_backup_restore(self) -> None:
        self.open_backup_settings()

    def do_restore_backup(self, path: str, parent=None) -> None:
        """Gewählte Sicherung einspielen (F-855): vorher den aktuellen Stand sichern, dann neu starten."""
        import zipfile

        from . import backup

        parent = parent or self
        if not confirm(parent, t("title.settings_restore"), t("backup.restore_confirm", name=os.path.basename(path)),
                       yes_key="button.restore_now"):
            return
        folder = self._backup_folder()
        try:
            backup.check_zip(Path(path))
            if backup.folder_reachable(folder, self.mounts):
                backup.create_backup(folder, auto=False)
            self._skip_save_state = True
            self.settings.frozen = True
            backup.restore_backup(Path(path))
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            self._skip_save_state = False
            self.settings.frozen = False
            show_error(parent, t("title.settings_restore"), t("backup.restore_failed", reason=str(exc)))
            return
        self.restart()

    # --- Spaltenprofile (F-842) --------------------------------------------------------------
    def _init_column_profiles(self) -> None:
        from . import colprofiles as cp

        state = load_json(STATE_FILE, {})
        assign: dict[str, str] = {}
        if not cp.names():
            # Einmalig: heutige Spalten werden zum Profil „Standard“ (rechts ggf. eigenes Profil)
            left, right = self.sides["left"].panel, self.sides["right"].panel
            cp.save(cp.DEFAULT_PROFILE, left.profile_data())
            assign = {"left": cp.DEFAULT_PROFILE, "right": cp.DEFAULT_PROFILE}
            if right.column_signature() != left.column_signature():
                cp.save(t("colprof.right_default"), right.profile_data())
                assign["right"] = t("colprof.right_default")
        names = cp.names()
        for side in SIDES:
            panel = self.sides[side].panel
            st = state.get(side, {}) if isinstance(state, dict) else {}
            wanted = assign.get(side) or (st.get("column_profile") if isinstance(st, dict) else None)
            name = wanted if wanted in names else (cp.DEFAULT_PROFILE if cp.DEFAULT_PROFILE in names else names[0])
            panel.apply_profile(name, cp.load(name))
            panel.columns_changed.connect(lambda s=side: self._save_column_profile(s))
            panel.profile_chosen.connect(lambda n, s=side: self.set_column_profile(s, n))
            panel.new_profile_requested.connect(lambda s=side: self.new_column_profile(s))

    def _save_column_profile(self, side: str) -> None:
        from . import colprofiles as cp

        panel = self.sides[side].panel
        name = panel.column_profile
        if not name:
            return
        data = panel.profile_data()
        cp.save(name, data)
        other = self.sides[SIDES[1] if side == SIDES[0] else SIDES[0]].panel
        if other.column_profile == name:
            other.apply_profile(name, data)  # gleiches Profil → gleiche Spalten

    def set_column_profile(self, side: str, name: str) -> None:
        from . import colprofiles as cp

        if name in cp.names():
            self.sides[side].panel.apply_profile(name, cp.load(name))

    def new_column_profile(self, side: str) -> None:
        from . import colprofiles as cp

        name = ask_text(self, t("colprof.new_title"), t("colprof.name_prompt"), t("colprof.new_default"))
        if not name:
            return
        name = name.strip()
        err = cp.name_error(name)
        if err:
            show_error(self, t("colprof.new_title"), t(err, name=name))
            return
        panel = self.sides[side].panel
        cp.save(name, panel.profile_data())
        panel.column_profile = name

    # --- Favoritensätze (F-620 ff.) ---------------------------------------------------------
    @property
    def fav_model(self):
        """Modell des Favoritensatzes im aktiven Panel."""
        return self.fav_sets.model(self.fav_set[self.active_side])

    def _fav_pane(self, side: str) -> SidebarPane | None:
        w = self.sides[side].sidebar._widgets.get(MODE_FAVORITES)
        return w if isinstance(w, SidebarPane) else None

    def _update_fav_title(self, side: str, pane: SidebarPane | None = None) -> None:
        pane = pane or self._fav_pane(side)
        if pane is None:
            return
        names = self.fav_sets.names()
        menu = None
        if len(names) > 1:
            menu = QMenu(pane.title_button)
            for name in names:
                act = menu.addAction(name)
                act.setCheckable(True)
                act.setChecked(name == self.fav_set[side])
                act.triggered.connect(lambda _c=False, s=side, n=name: self.switch_fav_set(s, n))
        old = pane.title_button.menu()
        pane.set_title(self.fav_set[side], menu)
        if old is not None:
            old.deleteLater()
        pane.title_button.setToolTip(t("favsets.title_tip"))

    def _update_fav_titles(self) -> None:
        for side in SIDES:
            self._update_fav_title(side)

    def switch_fav_set(self, side: str, name: str) -> None:
        self.fav_set[side] = name
        pane = self._fav_pane(side)
        if pane is not None:
            pane.view.setModel(self.fav_sets.model(name))
        self._update_fav_title(side)

    def _on_fav_set_renamed(self, old: str, new: str) -> None:
        for side in SIDES:
            if self.fav_set[side] == old:
                self.fav_set[side] = new

    def _on_fav_set_removed(self, name: str) -> None:
        for side in SIDES:
            if self.fav_set[side] == name:
                self.switch_fav_set(side, self.fav_sets.resolve(None))

    def _fav_title_menu(self, side: str, global_pos) -> None:
        self.set_active_side(side)
        menu = QMenu(self)
        menu.addAction(t("favsets.new")).triggered.connect(lambda: self.new_fav_set(side))
        menu.addAction(t("favsets.rename")).triggered.connect(lambda: self.rename_fav_set(side))
        delete = menu.addAction(t("favsets.delete"))
        delete.setEnabled(len(self.fav_sets.names()) > 1)
        delete.triggered.connect(lambda: self.delete_fav_set(side))
        menu.exec(global_pos)

    def _ask_set_name(self, title_key: str, default: str, ignore: str | None = None) -> str | None:
        name = default
        while True:
            name = ask_text(self, t(title_key), t("favsets.name_prompt"), name)
            if not name:
                return None
            err = self.fav_sets.name_error(name, ignore)
            if err is None:
                return name.strip()
            show_error(self, t(title_key), t(err, name=name))

    def new_fav_set(self, side: str) -> None:
        name = self._ask_set_name("favsets.new_title", t("favsets.new_default"))
        if name is None:
            return
        try:
            self.fav_sets.create(name)
        except OSError as exc:
            show_error(self, t("favsets.new_title"), exc.strerror or str(exc))
            return
        self.switch_fav_set(side, name)

    def rename_fav_set(self, side: str) -> None:
        old = self.fav_set[side]
        name = self._ask_set_name("favsets.rename_title", old, ignore=old)
        if name is None or name == old:
            return
        try:
            self.fav_sets.rename(old, name)
        except OSError as exc:
            show_error(self, t("favsets.rename_title"), exc.strerror or str(exc))

    def delete_fav_set(self, side: str) -> None:
        name = self.fav_set[side]
        if len(self.fav_sets.names()) <= 1:
            return
        n = len(self.fav_sets.model(name).root.children)
        if not confirm(self, t("favsets.delete_title"), t("favsets.delete_confirm", name=name, n=n),
                       yes_key="button.delete"):
            return
        try:
            self.fav_sets.delete(name)
        except OSError as exc:
            show_error(self, t("favsets.delete_title"), exc.strerror or str(exc))

    def _make_tree_view(self, side: str) -> FolderTreeView:
        view = FolderTreeView(self.icons, self.mounts)
        view.setObjectName(f"tree_{side}")
        view.tree_model.show_hidden = bool(self.settings.get("show_hidden"))
        view.reload()
        view.open_path.connect(lambda path, s=side: self._open_tree_path(s, path))
        view.focus_entered.connect(lambda s=side: self.set_active_side(s))
        view.drop_requested.connect(self._on_drop)
        view.disk_clicked.connect(self._on_disk_clicked)
        view.customContextMenuRequested.connect(lambda pos, s=side, v=view: self._tree_context_menu(s, v, pos))
        return self._pane(side, view, t("sidebar.tree_title"))

    def tree_view(self, side: str) -> FolderTreeView | None:
        w = self.sides[side].sidebar.current_module()
        w = w.view if isinstance(w, SidebarPane) else w
        return w if isinstance(w, FolderTreeView) else None

    def _on_panel_path_changed(self, side: str, path: str) -> None:
        tool = self.tool_mode.get(side)
        if tool and tool["mode"] == MODE_SEARCH and not self.sides[side].panel.search_mode:
            self.close_tool(side, navigate_back=False)  # Ordner gewechselt → Suche schließen (F-818)
        if side == self.active_side:
            self._update_title()
            self._update_nav_actions()
        tree = self.tree_view(side)
        if tree is not None:
            tree.select_path(path)

    def _open_tree_path(self, side: str, path: str) -> None:
        self.set_active_side(side)
        self.sides[side].panel.navigate(path)

    def side_of_widget(self, widget) -> str | None:
        for name, s in self.sides.items():
            if widget is s.splitter or s.splitter.isAncestorOf(widget):
                return name
        return None

    def _on_mounts_changed(self) -> None:
        for m in self.fav_sets.loaded_models():
            m.refresh_states()
        for s in self.sides.values():
            s.panel.view.viewport().update()
            if s.panel.in_trash:
                s.panel.refresh()  # Freigabe ein-/ausgehängt: deren Papierkorb kommt hinzu/fällt weg
        self.update_network_trash_state()

    def _apply_panel_options(self, panel: FilePanel) -> None:
        panel.set_options(
            bool(self.settings.get("show_hidden")),
            bool(self.settings.get("dirs_first")),
            bool(self.settings.get("show_parent_entry")),
        )

    def _create_actions(self) -> None:
        for adef in ACTION_DEFS:
            act = QAction(t(adef.text_key), self)
            keys = self.keymap.keys_for(adef.id)
            if keys:
                # Nur zur Anzeige im Menü – ausgelöst wird zentral über den KeyFilter.
                act.setShortcuts([QKeySequence(k) for k in keys])
                act.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
            act.triggered.connect(lambda _checked=False, aid=adef.id: self.trigger(aid))
            self.qactions[adef.id] = act
        hidden = self.qactions["toggle_hidden"]
        hidden.setCheckable(True)
        hidden.setChecked(bool(self.settings.get("show_hidden")))
        self.qactions["toggle_single"].setCheckable(True)
        self.qactions["filter_toggle"].setCheckable(True)
        self.qactions["rename_undo"].setEnabled(False)
        for aid, key in (("toggle_buttonbar", "show_buttonbar"), ("toggle_fkeybar", "show_fkeybar"),
                         ("toggle_toolbar", "show_toolbar")):
            self.qactions[aid].setCheckable(True)
            self.qactions[aid].setChecked(bool(self.settings.get(key)))
        self.button_bar.setVisible(bool(self.settings.get("show_buttonbar")))
        self.fkey_bar.setVisible(bool(self.settings.get("show_fkeybar")))
        self._refresh_fkey_display()
        if IS_WINDOWS:
            # Windows-Vorschau: noch nicht umgesetzte Funktionen ausgrauen
            for aid in WINDOWS_DISABLED_ACTIONS:
                self.qactions[aid].setEnabled(False)
            self.button_bar.trash_button.setEnabled(False)

    def _create_menus(self) -> None:
        mb = self.menuBar()
        a = self.qactions

        m = mb.addMenu(t("menu.file"))
        for aid in ("open", "edit_text", "open_with_other", None, "new_folder", "new_textfile", "rename",
                    "multi_rename", "rename_undo", None, "search", "checksums", "properties", None,
                    "copy", "move", None, "delete", "delete_permanent", None):
            m.addSeparator() if aid is None else m.addAction(a[aid])
        # Einstellungen als Untermenü direkt über „Beenden“ (v0.9.10, vorher eigenes Menü)
        sm = m.addMenu(t("menu.settings"))
        self.settings_menu = sm
        self.language_menu = sm.addMenu(t("menu.language"))
        self.language_menu.aboutToShow.connect(self._fill_language_menu)
        sm.addAction(a["settings_dialog"])
        sm.addSeparator()
        sm.addAction(a["backup_now"])
        sm.addAction(a["backup_restore"])
        m.addSeparator()
        m.addAction(a["quit"])

        m = mb.addMenu(t("menu.edit"))
        for aid in ("clip_cut", "clip_copy", "clip_paste", None, "select_all", None, "meta_wizard"):
            m.addSeparator() if aid is None else m.addAction(a[aid])

        m = mb.addMenu(t("menu.view"))
        self.sidebar_menus: dict[str, dict[str, QAction]] = {}
        self.sidebar_submenus: dict[str, QMenu] = {}
        for side in SIDES:
            sub = m.addMenu(t(f"menu.sidebar_{side}"))
            self.sidebar_submenus[side] = sub
            group = QActionGroup(self)
            group.setExclusive(True)
            self.sidebar_menus[side] = {}
            for sdef in SIDEBARS:
                label = t(sdef.text_key) if sdef.available else t("sidebar.coming_soon", name=t(sdef.text_key))
                act = QAction(label, self)
                act.setCheckable(True)
                act.setEnabled(sdef.available)
                act.triggered.connect(lambda _c=False, s=side, mode=sdef.id: self.set_sidebar_mode(s, mode))
                group.addAction(act)
                sub.addAction(act)
                self.sidebar_menus[side][sdef.id] = act
        m.addAction(a["toggle_sidebar"])
        m.addAction(a["toggle_buttonbar"])
        m.addAction(a["toggle_fkeybar"])
        m.addAction(a["toggle_toolbar"])
        m.addAction(a["toggle_single"])
        m.addSeparator()
        m.addAction(a["toggle_hidden"])
        m.addAction(a["filter_define"])
        m.addAction(a["filter_toggle"])
        m.addAction(a["refresh"])

        m = mb.addMenu(t("menu.navigate"))
        for aid in ("back", "forward", "go_up", "edit_path", None, "switch_panel", "same_path", "swap_panels",
                    None, "open_trash", "trash_empty"):
            m.addSeparator() if aid is None else m.addAction(a[aid])

        m = mb.addMenu(t("menu.favorites"))
        for aid in ("add_favorite", "fav_new_group", None, "fav_edit", "fav_rename", "fav_delete"):
            m.addSeparator() if aid is None else m.addAction(a[aid])

        m = mb.addMenu(t("menu.help"))
        for aid in ("help", "help_online", None, "donate", None, "about"):
            m.addSeparator() if aid is None else m.addAction(a[aid])

    # --- Seiten / Fokus ---------------------------------------------------------------------
    @property
    def active(self) -> FilePanel:
        return self.sides[self.active_side].panel

    @property
    def other(self) -> FilePanel:
        return self.sides[self.other_side].panel

    @property
    def other_side(self) -> str:
        return "right" if self.active_side == "left" else "left"

    def set_active_side(self, side: str) -> None:
        self.active_side = side
        self.button_bar.set_direction(side == "left")
        for name, s in self.sides.items():
            s.panel.set_active(name == side)
        self._update_title()
        self._update_nav_actions()

    def _on_focus_changed(self, _old, new) -> None:
        if new is None:
            return
        for name, s in self.sides.items():
            if s.splitter.isAncestorOf(new):
                if name != self.active_side:
                    self.set_active_side(name)
                # Prüfsummen folgen dem Dateifenster, das zuletzt den Fokus hatte –
                # ein Klick ins Vergleichsfeld der Seitenleiste ändert die Quelle nicht
                if s.panel.isAncestorOf(new) and getattr(self, "_checksum_side", None) != name:
                    self._checksum_side = name
                    if any(st["mode"] == MODE_CHECKSUM for st in self.tool_mode.values()):
                        self._checksum_cursor_changed()
                return

    def _update_title(self) -> None:
        path = self.active.current_path
        if is_trash_uri(path):
            path = t("trash.title")
        self.setWindowTitle(f"{path} – PanePilot" if path else "PanePilot")

    def favorites_view(self, side: str) -> FavoritesView | None:
        host = self.sides[side].sidebar
        if host.mode == MODE_FAVORITES:
            w = host.current_module()
            w = w.view if isinstance(w, SidebarPane) else w
            return w if isinstance(w, FavoritesView) else None
        return None

    def set_sidebar_mode(self, side: str, mode: str) -> None:
        host = self.sides[side].sidebar
        old_view = self.favorites_view(side)
        expanded = old_view.expanded_ids() if old_view else None
        host.set_mode(mode)
        if mode != MODE_OFF:
            self.last_sidebar_mode[side] = mode
        new_view = self.favorites_view(side)
        if new_view is not None and expanded is not None:
            new_view.restore_expanded(expanded)
        tree = self.tree_view(side)
        if tree is not None:
            tree.select_path(self.sides[side].panel.current_path)
        if side in getattr(self, "sidebar_menus", {}) and mode in self.sidebar_menus[side]:
            self.sidebar_menus[side][mode].setChecked(True)

    # --- Aktionen ------------------------------------------------------------------------------
    # Im Papierkorb nicht sinnvoll (F-410)
    TRASH_BLOCKED = {"new_folder", "new_textfile", "rename", "move", "move_direct", "clip_cut", "clip_paste",
                     "edit_text", "open_with_other", "filter_define", "filter_toggle", "multi_rename", "compress",
                     "meta_wizard", "search", "checksums", "extract_here", "extract_subfolder", "extract_to"}
    # In der Ein-Fenster-Ansicht gibt es kein zweites Panel (F-441)
    SINGLE_BLOCKED = {"switch_panel", "same_path", "swap_panels", "copy", "move", "copy_direct", "move_direct"}

    # Während „Mehrfach umbenennen“ erlaubt (F-703, F-706)
    RENAME_ALLOWED = {"filter_define", "filter_toggle", "quit", "about", "help", "help_online", "donate"}

    def trigger(self, action_id: str) -> None:
        if not action_id:
            return
        if self.rename_mode is not None and action_id not in self.RENAME_ALLOWED:
            return
        if self.meta_mode is not None and action_id not in META_ALLOWED:
            return
        if self.single_mode and action_id in self.SINGLE_BLOCKED:
            return
        if self.active.in_trash and action_id in self.TRASH_BLOCKED:
            return
        if IS_WINDOWS and action_id in WINDOWS_DISABLED_ACTIONS:
            return
        if action_id in ("copy", "move", "copy_direct", "move_direct") and self.other.in_trash and not self.active.in_trash:
            show_info(self, t("trash.title"), t("trash.no_copy_into"))
            return
        handler = getattr(self, f"do_{action_id}", None)
        if handler is not None:
            handler()

    def do_switch_panel(self) -> None:
        side = self.other_side
        self.set_active_side(side)
        self.sides[side].panel.view.setFocus()

    def do_same_path(self) -> None:
        self.other.navigate(self.active.current_path)

    def do_swap_panels(self) -> None:
        left, right = self.sides["left"].panel, self.sides["right"].panel
        lp, rp = left.current_path, right.current_path
        lh, rh = left.history_state(), right.history_state()
        left.navigate(rp, add_history=False)
        right.navigate(lp, add_history=False)
        left.set_history_state(*rh)
        right.set_history_state(*lh)
        self._update_nav_actions()

    def _copy_or_move(self, move: bool, ask: bool = True) -> None:
        entries = self.active.target_entries()
        if not entries:
            return
        target = self.other.current_path
        if ask and self.settings.get("confirm_copy_move"):
            dlg = CopyMoveDialog(self, move, [e.name for e in entries], target)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return
            target = dlg.target()
        if not os.path.isdir(target):
            show_error(self, t("title.move" if move else "title.copy"), t("error.target_missing", path=target))
            return
        self.ops.start(MOVE if move else COPY, [e.path for e in entries], target)

    def do_copy(self) -> None:
        self._copy_or_move(False)

    def do_move(self) -> None:
        self._copy_or_move(True)

    def do_copy_direct(self) -> None:
        """Knopfleiste: ohne Rückfrage (F-323)."""
        self._copy_or_move(False, ask=False)

    def do_move_direct(self) -> None:
        self._copy_or_move(True, ask=False)

    def do_new_textfile(self) -> None:
        """Leere Textdatei anlegen und gleich umbenennen lassen (F-310 ff.)."""
        panel = self.active
        name = unique_name(panel.current_path, t("dialog.new_textfile_default") + ".txt")
        path = os.path.join(panel.current_path, name)
        try:
            with open(path, "x", encoding="utf-8"):
                pass
        except OSError as exc:
            show_error(self, t("title.new_textfile"), t("error.create_failed", name=name, reason=exc.strerror or str(exc)))
            return
        panel.refresh()
        panel.select_names([name], current=name)
        panel.view.setFocus()
        panel.start_rename()

    def _selected_files(self) -> list[str]:
        return [e.path for e in self.active.target_entries() if not e.is_dir]

    def do_edit_text(self) -> None:
        """F4: Datei(en) im Standard-Texteditor öffnen."""
        files = self._selected_files()
        if not files:
            return
        if IS_WINDOWS:
            # Windows-Vorschau: Editor von Windows (je Datei ein Fenster)
            from PySide6.QtCore import QProcess

            ok = True
            for f in files:
                res = QProcess.startDetached("notepad.exe", [f])
                ok = ok and bool(res[0] if isinstance(res, tuple) else res)
            if not ok:
                show_error(self, t("title.open"), t("error.no_text_editor"))
            return
        editor = desktop_apps.default_text_editor()
        if editor is None or not desktop_apps.launch(editor, files):
            show_error(self, t("title.open"), t("error.no_text_editor"))

    def do_open_with_other(self) -> None:
        files = self._selected_files()
        if not files:
            return
        mime = desktop_apps.mime_of(files[0])
        label = os.path.basename(files[0]) if len(files) == 1 else t("dialog.n_items", n=len(files))
        dlg = OpenWithDialog(self, desktop_apps.all_apps(), label)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        app = dlg.selected_app()
        if app is None:
            return
        if dlg.make_default.isChecked() and not desktop_apps.set_default_app(app, mime):
            show_error(self, t("title.open_with"), t("error.set_default_failed", app=app.name))
        self._launch_app(app, files)

    def _launch_app(self, app, files: list[str]) -> None:
        if not desktop_apps.launch(app, files):
            show_error(self, t("title.open"), t("error.launch_failed", app=app.name))

    def _open_with_menu(self, menu: QMenu) -> None:
        files = self._selected_files()
        if not files:
            return
        sub = menu.addMenu(t("menu.open_with"))
        if IS_WINDOWS:
            sub.setEnabled(False)  # Windows-Vorschau: noch nicht umgesetzt
            return
        for app in desktop_apps.apps_for(desktop_apps.mime_of(files[0]))[:15]:
            act = sub.addAction(app.qicon(), app.name)
            act.triggered.connect(lambda _c=False, a=app, f=files: self._launch_app(a, f))
        if sub.actions():
            sub.addSeparator()
        sub.addAction(self.qactions["open_with_other"])

    def do_toggle_buttonbar(self) -> None:
        if self.single_mode:
            return
        show = not self.button_bar.isVisible()
        self.button_bar.setVisible(show)
        self.settings.set("show_buttonbar", show)
        self.qactions["toggle_buttonbar"].setChecked(show)

    def do_toggle_fkeybar(self) -> None:
        show = not self.fkey_bar.isVisible()
        self.fkey_bar.setVisible(show)
        self.settings.set("show_fkeybar", show)
        self.qactions["toggle_fkeybar"].setChecked(show)

    # --- F-Tasten ------------------------------------------------------------------------
    def fkey_action(self, key: str) -> str | None:
        return self.fkeys.get(key)

    def _refresh_fkey_display(self) -> None:
        def short(aid: str) -> str:
            text = t(f"short.{aid}")
            return text if text != f"short.{aid}" else t(ACTIONS_BY_ID[aid].text_key).rstrip(" …")

        labels = {k: (short(a) if a else None) for k, a in self.fkeys.items()}
        tips = {}
        for k, a in self.fkeys.items():
            tip = t(ACTIONS_BY_ID[a].text_key) if a else t("fkeys.free_tip")
            if k in GNOME_RESERVED:
                tip += "\n" + t("fkeys.gnome_reserved")
            tips[k] = tip
        self.fkey_bar.set_labels(labels, tips)
        self._update_fkey_enabled()
        by_action: dict[str, list[str]] = {}
        for k, a in self.fkeys.items():
            if a:
                by_action.setdefault(a, []).append(k)
        for adef in ACTION_DEFS:
            keys = list(by_action.get(adef.id, [])) + list(self.keymap.keys_for(adef.id))
            act = self.qactions[adef.id]
            act.setShortcuts([QKeySequence(k) for k in keys])
            act.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        tips = {}
        for aid in ButtonBar.BUTTONS:
            base = {"copy_direct": "copy", "move_direct": "move"}.get(aid, aid)
            keys = by_action.get(base, []) + list(self.keymap.keys_for(base))
            text = t(ACTIONS_BY_ID[aid].text_key)
            tips[aid] = f"{text} ({keys[0]})" if keys else text
        self.button_bar.set_tooltips(tips)
        if getattr(self, "toolbar", None) is not None:
            self.toolbar.set_items(self.toolbar.items)  # Infotexte mit aktuellen Tasten

    def _update_fkey_enabled(self) -> None:
        on = getattr(self, "single_mode", False)
        self.fkey_bar.set_disabled({k for k, a in self.fkeys.items() if on and a in self.SINGLE_BLOCKED})

    @staticmethod
    def fkey_display(key: str) -> str:
        """'Shift+F5' → 'Umschalt+F5' (Menütexte)."""
        layer, base = split_fkey(key)
        return t(f"fkeys.layer.{layer.rstrip('+') or 'none'}", key=base)

    def _assign_fkey_menu(self, key: str, pos) -> None:
        menu = QMenu(self)
        layer, base = split_fkey(key)
        # Schicht umschalten, falls man die Zusatztaste beim Rechtsklick vergessen hat (F-643)
        for lay in LAYERS:
            act = menu.addAction(self.fkey_display(lay + base))
            act.setCheckable(True)
            act.setChecked(lay == layer)
            act.triggered.connect(lambda _c=False, k=lay + base: QTimer.singleShot(0, lambda: self._assign_fkey_menu(k, pos)))
        menu.addSection(t("fkeys.assign", key=self.fkey_display(key)))
        if key in GNOME_RESERVED:
            hint = menu.addAction(t("fkeys.gnome_reserved"))
            hint.setEnabled(False)
        current = self.fkeys.get(key)
        none_act = menu.addAction(t("fkeys.none"))
        none_act.setCheckable(True)
        none_act.setChecked(current is None)
        none_act.triggered.connect(lambda _c=False: self.set_fkey(key, None))
        menu.addSeparator()
        for adef in sorted((a for a in ACTION_DEFS if a.id not in NOT_ASSIGNABLE), key=lambda a: t(a.text_key).casefold()):
            act = menu.addAction(t(adef.text_key))
            act.setCheckable(True)
            act.setChecked(adef.id == current)
            act.triggered.connect(lambda _c=False, aid=adef.id: self.set_fkey(key, aid))
        menu.exec(pos)

    def set_fkey(self, key: str, action_id: str | None) -> None:
        self.fkeys[key] = action_id
        overrides = {k: v for k, v in self.fkeys.items() if FKEY_DEFAULTS.get(k) != v}
        self.settings.set("fkeys", overrides)
        self._refresh_fkey_display()

    def do_new_folder(self) -> None:
        panel = self.active
        name = ask_text(self, t("title.new_folder"), t("dialog.new_folder_name"), t("dialog.new_folder_default"))
        if not name:
            return
        if "/" in name or name in (".", ".."):
            show_error(self, t("title.new_folder"), t("error.invalid_name", name=name))
            return
        path = os.path.join(panel.current_path, name)
        try:
            os.mkdir(path)
        except FileExistsError:
            show_error(self, t("title.new_folder"), t("error.name_exists", name=name))
            return
        except OSError as exc:
            show_error(self, t("title.new_folder"), t("error.mkdir_failed", name=name, reason=exc.strerror or str(exc)))
            return
        panel.refresh()
        panel.select_names([name], current=name)
        panel.view.setFocus()

    def do_rename(self) -> None:
        self.active.start_rename()

    def do_delete(self) -> None:
        if self.active.in_trash:
            self.do_trash_purge()  # im Papierkorb gibt es nur endgültiges Löschen
            return
        entries = self.active.target_entries()
        if not entries:
            return
        if self.settings.get("confirm_trash"):
            text = (t("dialog.trash_confirm_one", name=entries[0].name) if len(entries) == 1
                    else t("dialog.trash_confirm", n=len(entries)))
            if not confirm(self, t("title.trash"), text):
                return
        self._remember_cursor_after_delete(entries)
        self.ops.start(TRASH, [e.path for e in entries])

    def do_delete_permanent(self) -> None:
        if self.active.in_trash:
            self.do_trash_purge()
            return
        entries = self.active.target_entries()
        if not entries:
            return
        what = t("dialog.one_item", name=entries[0].name) if len(entries) == 1 else t("dialog.n_items", n=len(entries))
        key = "dialog.delete_confirm_one" if len(entries) == 1 else "dialog.delete_confirm"
        if not confirm(self, t("title.delete"), t(key, what=what),
                       yes_key="button.delete", default_yes=False, warning=True):
            return
        self._remember_cursor_after_delete(entries)
        self.ops.start(DELETE, [e.path for e in entries])

    def _remember_cursor_after_delete(self, entries) -> None:
        """Nach dem Löschen den Cursor auf den nächsten verbleibenden Eintrag setzen."""
        panel = self.active
        names = {e.name for e in entries}
        rows = [panel.model.row_of(n) for n in names]
        start = max(rows) + 1 if rows else 0
        following = None
        for e in panel.model.entries()[start:]:
            if e.name not in names:
                following = e.name
                break
        if following is None:
            for e in reversed(panel.model.entries()[: min(rows) if rows else 0]):
                if e.name not in names:
                    following = e.name
                    break
        panel.setProperty("cursor_after_delete", following)

    def do_open(self) -> None:
        self.active.open_current()

    def do_select_all(self) -> None:
        self.active.select_all()

    def do_go_up(self) -> None:
        self.active.go_up()

    # --- Symbolleiste (F-550 ff.) ---------------------------------------------------------
    def _create_toolbar(self) -> None:
        def key_text(aid: str) -> str:
            seqs = self.qactions[aid].shortcuts()
            return seqs[0].toString(QKeySequence.SequenceFormat.NativeText) if seqs else ""

        self.toolbar = MainToolBar(self, self.qactions, key_text, self._fill_history_menu)
        self.toolbar.customize_requested.connect(self.customize_toolbar)
        self.toolbar.rebuilt.connect(self._update_filter_ui)
        self.toolbar.hide_requested.connect(lambda: self.set_toolbar_visible(False))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.toolbar)
        self.toolbar.set_items(self.settings.get("toolbar"))
        self.toolbar.setVisible(bool(self.settings.get("show_toolbar")))

    def _fill_history_menu(self, aid: str, menu: QMenu) -> None:
        menu.clear()
        panel = self.active
        if aid == "filter_toggle":
            self._fill_filter_menu(menu)
            return
        for index, path in panel.history_entries(forward=aid == "forward")[:20]:
            label = t("trash.title") if is_trash_uri(path) else path
            act = menu.addAction(label)
            act.triggered.connect(lambda _c=False, i=index, p=panel: p.go_history(i))
        if menu.isEmpty():
            menu.addAction(t("toolbar.history_empty")).setEnabled(False)

    # --- Filter (F-600 ff.) --------------------------------------------------------------
    def _recent_filters(self):
        from .filters import recent_specs

        return recent_specs(self.settings.get("recent_filters"))

    def _fill_filter_menu(self, menu: QMenu) -> None:
        panel = self.active
        menu.addAction(self.qactions["filter_define"])
        off = menu.addAction(t("filter.off"))
        off.setEnabled(panel.filter_active)
        off.triggered.connect(lambda: self._apply_filter(None, False))
        recent = self._recent_filters()
        if recent:
            menu.addSection(t("filter.recent"))
            for spec in recent:
                act = menu.addAction(spec.label() + ("   (RegEx)" if spec.regex else ""))
                act.setCheckable(True)
                act.setChecked(panel.filter_active and panel.filter_spec == spec)
                act.triggered.connect(lambda _c=False, s=spec: self._apply_filter(s, True))
        if self.active.in_trash:
            for act in menu.actions():
                act.setEnabled(False)

    def _apply_filter(self, spec, active: bool) -> None:
        from .filters import add_recent

        panel = self.active
        if panel.in_trash or panel.search_mode:
            return
        panel.set_filter(spec, active)
        if spec is not None and active:
            self.settings.set("recent_filters", add_recent(self.settings.get("recent_filters"), spec))

    def do_filter_define(self) -> None:
        from .dialogs import FilterDialog

        panel = self.active
        dlg = FilterDialog(self, panel.filter_spec, self._recent_filters())
        if dlg.exec() != dlg.DialogCode.Accepted:
            self._update_filter_ui()
            return
        self._apply_filter(dlg.spec(), True)

    def do_filter_toggle(self) -> None:
        panel = self.active
        if panel.filter_spec is None:
            self.do_filter_define()
            return
        self._apply_filter(panel.filter_spec, not panel.filter_active)

    def _on_filter_changed(self, side: str) -> None:
        if side == self.active_side:
            self._update_filter_ui()

    def _update_filter_ui(self) -> None:
        """Knopf eingerastet + roter Trichter, wenn im aktiven Panel ein Filter wirkt (F-605 ff.)."""
        if getattr(self, "toolbar", None) is None:
            return
        from .toolicons import icon_filter

        panel = self.active
        on = panel.filter_active and not panel.in_trash
        self.qactions["filter_toggle"].setChecked(on)
        if on:
            shown, total = panel.filter_counts()
            tip = t("filter.tip_on", pattern=panel.filter_spec.label(), shown=shown, total=total)
        else:
            tip = t("filter.tip_off")
        self.toolbar.set_action_look("filter_toggle", icon_filter(on), tip)

    def _update_nav_actions(self) -> None:
        self._update_filter_ui()
        panel = self.active
        self.qactions["back"].setEnabled(panel.can_go_back())
        self.qactions["forward"].setEnabled(panel.can_go_forward())

    def customize_toolbar(self) -> None:
        dlg = ToolbarDialog(self, self.toolbar.items)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        items = dlg.result_items()
        self.toolbar.set_items(items)
        self.settings.set("toolbar", items)

    def set_toolbar_visible(self, show: bool) -> None:
        self.toolbar.setVisible(show)
        self.settings.set("show_toolbar", show)
        self.qactions["toggle_toolbar"].setChecked(show)

    def do_toggle_toolbar(self) -> None:
        self.set_toolbar_visible(not self.toolbar.isVisible())

    def do_back(self) -> None:
        self.active.back()

    def do_forward(self) -> None:
        self.active.forward()

    def do_edit_path(self) -> None:
        self.active.edit_path()

    def _trees(self) -> list[FolderTreeView]:
        trees = []
        for s in self.sides.values():
            w = s.sidebar._widgets.get(MODE_TREE)
            if isinstance(w, FolderTreeView):
                trees.append(w)
        return trees

    def do_refresh(self) -> None:
        self.mounts.reload()
        for s in self.sides.values():
            s.panel.refresh()
        for tree in self._trees():
            tree.reload()
        for m in self.fav_sets.loaded_models():
            m.layoutChanged.emit()

    def do_toggle_hidden(self) -> None:
        show = not bool(self.settings.get("show_hidden"))
        self.settings.set("show_hidden", show)
        self.qactions["toggle_hidden"].setChecked(show)
        for s in self.sides.values():
            self._apply_panel_options(s.panel)
            s.panel.refresh()
        for tree in self._trees():
            tree.reload(show_hidden=show)

    def do_toggle_sidebar(self) -> None:
        """Alt+F: Seitenleiste des aktiven Panels aus – bzw. mit der zuletzt genutzten Ansicht ein (F-241)."""
        side = self.active_side
        if self.sides[side].sidebar.mode == MODE_OFF:
            self.set_sidebar_mode(side, self.last_sidebar_mode.get(side, MODE_FAVORITES))
        else:
            self.set_sidebar_mode(side, MODE_OFF)

    def do_tree_open(self) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, FolderTreeView):
            focus.activate_current()

    # --- Laufwerke ---------------------------------------------------------------------------
    def _mount_actions(self, menu: QMenu, path: str | None) -> None:
        """„Einbinden“/„Aushängen“, wenn path ein bekannter Einhängepunkt ist bzw. darin liegt."""
        if not path:
            return
        entry = self.mounts.entry_containing(path)
        if entry is None or not (entry.user_mountable or not entry.in_fstab):
            return
        menu.addSeparator()
        if entry.mounted:
            act = menu.addAction(t("mount.unmount", name=entry.label))
            act.triggered.connect(lambda _c=False, e=entry: self.unmount_entry(e))
        else:
            act = menu.addAction(t("mount.mount", name=entry.label))
            act.triggered.connect(lambda _c=False, e=entry: self.mount_entry(e))
        if self.mounts.is_busy(entry.mount_point):
            act.setEnabled(False)
        self._disk_actions(menu, self.mounts.disk_for(entry), separator=False)

    def _disk_actions(self, menu: QMenu, disk, separator: bool = True) -> None:
        """„Sicher entfernen“ (USB) bzw. „Auswerfen“ (ISO-Abbild)."""
        if disk is None or disk.kind not in ("usb", "image"):
            return
        if separator:
            menu.addSeparator()
        if disk.kind == "usb":
            act = menu.addAction(t("drives.safely_remove", name=disk.label))
            act.triggered.connect(lambda _c=False, d=disk: self.safely_remove(d))
        else:
            act = menu.addAction(t("drives.eject", name=disk.label))
            act.triggered.connect(lambda _c=False, d=disk: self.eject_image(d))
        act.setEnabled(not self.mounts.is_busy(disk.device))

    def _leave_disk(self, disk) -> None:
        for entry in disk.entries:
            mp = entry.mount_point
            if mp == "/":
                continue
            outside = os.path.dirname(mp.rstrip(os.sep)) or os.sep
            for s in self.sides.values():
                cur = s.panel.current_path
                if cur == mp or cur.startswith(mp.rstrip(os.sep) + os.sep):
                    s.panel.navigate(outside, select_name=os.path.basename(mp))

    def safely_remove(self, disk) -> None:
        self._leave_disk(disk)

        def done(ok: bool, output: str) -> None:
            if ok:
                show_info(self, t("title.safely_remove"), t("drives.removed", name=disk.label))
            else:
                show_error(self, t("title.safely_remove"), t("drives.remove_failed", name=disk.label,
                                                            reason=output or t("mount.unknown_error")))
        self.mounts.safely_remove(disk, done)

    def eject_image(self, disk) -> None:
        self._leave_disk(disk)

        def done(ok: bool, output: str) -> None:
            if not ok:
                show_error(self, t("title.eject"), t("drives.eject_failed", name=disk.label,
                                                    reason=output or t("mount.unknown_error")))
        self.mounts.eject_image(disk, done)

    def _on_disk_clicked(self, disk) -> None:
        if disk is None:
            return
        if disk.kind == "optical" and not disk.entries:
            if disk.has_medium:
                def done(ok: bool, output: str) -> None:
                    if not ok:
                        show_error(self, t("title.mount"), t("mount.failed", name=disk.label,
                                                             reason=output or t("mount.unknown_error")))
                self.mounts.mount_device(disk.device, done)
            else:
                show_info(self, disk.label, t("drives.no_medium"))

    def mount_entry(self, entry) -> None:
        def done(ok: bool, output: str) -> None:
            if not ok:
                show_error(self, t("title.mount"), t("mount.failed", name=entry.label,
                                                     reason=output or t("mount.unknown_error")))
        self.mounts.mount(entry, done)

    def unmount_entry(self, entry) -> None:
        mp = entry.mount_point
        outside = os.path.dirname(mp.rstrip(os.sep)) or os.sep
        for s in self.sides.values():
            cur = s.panel.current_path
            if cur == mp or cur.startswith(mp.rstrip(os.sep) + os.sep):
                s.panel.navigate(outside, select_name=os.path.basename(mp))

        def done(ok: bool, output: str) -> None:
            if not ok:
                show_error(self, t("title.unmount"), t("mount.unmount_failed", name=entry.label,
                                                       reason=output or t("mount.unknown_error")))
            for s in self.sides.values():
                s.panel.refresh()
        self.mounts.unmount(entry, done)

    def do_about(self) -> None:
        from .about import AboutDialog as NewAboutDialog

        NewAboutDialog(self, str(config_dir())).exec()

    # --- Hilfe und Spenden (v0.9.11) --------------------------------------------------------------
    def help_topic(self) -> str:
        """Welche Hilfeseite F1 öffnet: die zur gerade aktiven Funktion."""
        if self.meta_mode is not None:
            return "metawizard"
        if self.rename_mode is not None:
            return "rename"
        modes = [self.tool_mode.get(self.active_side, {}).get("mode")]
        modes += [st.get("mode") for side, st in self.tool_mode.items() if side != self.active_side]
        for mode in modes:
            if mode == MODE_SEARCH:
                return "search"
            if mode == MODE_CHECKSUM:
                return "checksums"
        return "basics"

    def do_help(self, topic: str | None = None, parent=None) -> None:
        from .helpdialog import HelpDialog

        if parent is not None:
            child = HelpDialog(self, topic or self.help_topic(), parent)
            child.show()
            return
        dlg = getattr(self, "_help_dialog", None)
        if dlg is None or not dlg.isVisible():
            dlg = HelpDialog(self, topic or self.help_topic())
            self._help_dialog = dlg
        else:
            dlg.show_topic(topic or self.help_topic())
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def do_help_online(self) -> None:
        from . import util
        from .donation import HELP_ONLINE_URL
        from .helpdialog import help_language

        util.open_url(f"{HELP_ONLINE_URL}/{help_language()}")

    def do_donate(self) -> None:
        from .donation import DonateDialog

        DonateDialog(self, self.settings).exec()

    def maybe_ask_for_donation(self) -> None:
        """Beim Start: nach 30 Tagen einmal täglich um Unterstützung bitten (nicht bei Spendern)."""
        import datetime as _dt

        from . import donation

        donation.ensure_first_start(self.settings)
        if not donation.should_nag(self.settings):
            return
        if QApplication.activeModalWidget() is not None:
            return
        self.settings.set("donate_last_shown", _dt.date.today().isoformat())
        donation.DonateDialog(self, self.settings).exec()

    def do_quit(self) -> None:
        self.close()

    # --- Zwischenablage ----------------------------------------------------------------------
    def _set_clipboard(self, cut: bool) -> None:
        entries = self.active.target_entries()
        if not entries:
            return
        urls = [QUrl.fromLocalFile(e.path) for e in entries]
        md = QMimeData()
        md.setUrls(urls)
        md.setText("\n".join(e.path for e in entries))
        gnome = ("cut" if cut else "copy") + "\n" + "\n".join(u.toString(QUrl.ComponentFormattingOption.FullyEncoded) for u in urls)
        md.setData(GNOME_CLIP, QByteArray(gnome.encode("utf-8")))
        md.setData(KDE_CUT, QByteArray(b"1" if cut else b"0"))
        QApplication.clipboard().setMimeData(md)

    def do_clip_copy(self) -> None:
        self._set_clipboard(False)

    def do_clip_cut(self) -> None:
        self._set_clipboard(True)

    def do_clip_paste(self) -> None:
        md = QApplication.clipboard().mimeData()
        if md is None:
            return
        cut = False
        paths: list[str] = []
        if md.hasFormat(GNOME_CLIP):
            lines = bytes(md.data(GNOME_CLIP)).decode("utf-8", "replace").splitlines()
            if lines:
                cut = lines[0].strip() == "cut"
                paths = [QUrl(line.strip()).toLocalFile() for line in lines[1:] if line.strip()]
        if not paths and md.hasUrls():
            paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            if md.hasFormat(KDE_CUT):
                cut = bytes(md.data(KDE_CUT)).strip() == b"1"
        paths = [p for p in paths if p and os.path.lexists(p)]
        if not paths:
            return
        self.ops.start(MOVE if cut else COPY, paths, self.active.current_path)
        if cut:
            QApplication.clipboard().clear()

    # --- Favoriten ---------------------------------------------------------------------------
    def _favorites_target_view(self) -> FavoritesView | None:
        """Nur das aktive Panel (F-627) – sonst landen Favoriten in einem Satz, den man nicht sieht."""
        return self.favorites_view(self.active_side)

    def do_add_favorite(self) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, FolderTreeView) and focus.current_path():
            self._add_favorite_paths([focus.current_path()])
            return
        panel = self.active
        entries = panel.selected_entries()
        self._add_favorite_paths([e.path for e in entries] if entries else [panel.current_path])

    def _add_favorite_paths(self, paths: list[str]) -> None:
        view = self._favorites_target_view()
        if view is None:
            show_error(self, t("title.favorite"), t("favorites.no_sidebar"))
            return
        model = view.fav_model
        parent, row = model.insertion_point(view.selected_node())
        last = None
        for p in paths:
            last = model.add_link(p, parent, row)
            row += 1
        if last is not None:
            view.select_node(last)

    def _focused_favorites_view(self) -> FavoritesView | None:
        focus = QApplication.focusWidget()
        if isinstance(focus, FavoritesView):
            return focus
        return self._favorites_target_view()

    def do_fav_new_group(self) -> None:
        view = self._focused_favorites_view()
        if view is None:
            show_error(self, t("title.favorite"), t("favorites.no_sidebar"))
            return
        name = ask_text(self, t("title.new_fav_group"), t("dialog.new_fav_group_name"), t("dialog.new_fav_group_default"))
        if not name:
            return
        parent, row = view.fav_model.insertion_point(view.selected_node())
        node = view.fav_model.add_group(name, parent, row)
        view.select_node(node)

    def do_fav_open(self) -> None:
        view = self._focused_favorites_view()
        if view is not None:
            view.activate_current()

    def do_fav_edit(self) -> None:
        view = self._focused_favorites_view()
        node = view.selected_node() if view else None
        if node is None:
            return
        dlg = FavoriteEditDialog(self, node, FAV_COLORS)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        name, path, style = dlg.values()
        if not node.is_group and path:
            full = os.path.abspath(os.path.expanduser(path))
            if not os.path.exists(full) and self.mounts.needs_mount(full) is None:
                show_info(self, t("title.fav_edit"), t("fav_edit.path_missing", path=full))
        view.fav_model.update_node(node, name or node.name, path, style)

    def do_fav_rename(self) -> None:
        view = self._focused_favorites_view()
        if view is None or view.selected_node() is None:
            return
        view.edit(view.currentIndex())

    def do_fav_delete(self) -> None:
        view = self._focused_favorites_view()
        node = view.selected_node() if view else None
        if node is None:
            return
        if node.is_group and node.children:
            text = t("dialog.fav_delete_group", name=node.name, n=len(node.children))
        elif node.is_group:
            text = t("dialog.fav_delete_empty_group", name=node.name)
        else:
            text = t("dialog.fav_delete_link", name=node.name)
        if confirm(self, t("title.fav_delete"), text, yes_key="button.delete"):
            view.fav_model.remove_node(node)

    def _open_favorite(self, side: str, node: FavNode, model=None) -> None:
        state = (model or self.fav_model).link_state(node)
        if state == "broken":
            show_info(self, t("title.favorite"), t("favorites.missing", name=node.name, path=node.path))
            return
        self.set_active_side(side)
        panel = self.sides[side].panel
        path = node.path

        def open_it() -> None:
            if os.path.isdir(path):
                panel.navigate(path)
            elif os.path.exists(path):
                self._open_file(path)
            else:
                show_info(self, t("title.favorite"), t("favorites.missing", name=node.name, path=path))

        panel.with_mount(path, open_it)

    def _open_file(self, path: str) -> None:
        if not open_with_default_app(path):
            show_error(self, t("title.open"), t("error.open_failed", path=path))

    # --- Kontextmenüs ------------------------------------------------------------------------
    def _file_context_menu(self, side: str, pos: QPoint) -> None:
        self.set_active_side(side)
        menu = QMenu(self)
        a = self.qactions
        if self.sides[side].panel.in_trash:
            # Kontextmenü im Papierkorb (F-408)
            if self.active.target_entries():
                for aid in ("trash_restore", "trash_purge", None, "copy", "clip_copy"):
                    menu.addSeparator() if aid is None else menu.addAction(a[aid])
                menu.addSeparator()
            menu.addAction(a["trash_empty"])
            if self.active.target_entries():
                menu.addSeparator()
                menu.addAction(a["properties"])
            menu.exec(pos)
            return
        menu.addAction(a["open"])
        self._open_with_menu(menu)
        menu.addAction(a["add_favorite"])
        menu.addSeparator()
        if self.active.target_entries():
            menu.addAction(a["compress"])
        self._extract_menu_entries(menu)
        for aid in (None, "clip_cut", "clip_copy", "clip_paste", None,
                    "rename", "multi_rename", "meta_wizard", "delete", "delete_permanent", None, "new_folder",
                    "new_textfile"):
            menu.addSeparator() if aid is None else menu.addAction(a[aid])
        entry = self.sides[side].panel.current_entry()
        if entry is not None and entry.is_dir and not entry.is_parent and self.mounts.entry_for_mount_point(entry.path):
            self._mount_actions(menu, entry.path)
        menu.addSeparator()
        if self.sides[side].panel.search_mode and entry is not None:
            menu.addAction(t("search.jump")).triggered.connect(self.jump_to_found_folder)
        if entry is not None and not entry.is_dir:
            menu.addAction(a["checksums"])
        menu.addAction(a["properties"])
        menu.exec(pos)

    # --- Archive (F-530 ff.) -------------------------------------------------------------
    def _selected_archives(self) -> list[str]:
        return [e.path for e in self.active.target_entries()
                if not e.is_dir and archives.archive_format(e.name) is not None]

    def _extract_menu_entries(self, menu: QMenu) -> None:
        paths = self._selected_archives()
        if not paths:
            return
        usable = [p for p in paths if archives.can_extract(archives.archive_format(os.path.basename(p)))]
        hint = ""
        if not usable:
            hint = archives.missing_hint(archives.archive_format(os.path.basename(paths[0])) or "", False)
            menu.setToolTipsVisible(True)
        if len(paths) == 1:
            sub_text = t("action.extract_subfolder_one", name=archives.archive_stem(os.path.basename(paths[0])))
        else:
            sub_text = t("action.extract_subfolder_many")
        for aid, text in (("extract_here", t("action.extract_here")), ("extract_subfolder", sub_text),
                          ("extract_to", t("action.extract_to"))):
            act = menu.addAction(text)
            act.setEnabled(bool(usable))
            if hint:
                act.setToolTip(hint)
            act.triggered.connect(lambda _c=False, x=aid: self.trigger(x))

    def do_compress(self) -> None:
        panel = self.active
        entries = [e for e in panel.target_entries() if not e.is_parent]
        if not entries:
            return
        folder = panel.current_path
        if len(entries) == 1:
            what = t("dialog.one_item", name=entries[0].name)
            name = entries[0].name
            if entries[0].is_dir:
                stem = name
            elif archives.archive_format(name) is not None:
                stem = archives.archive_stem(name)  # „fotos.tar.gz“ → „fotos“
            else:
                stem = os.path.splitext(name)[0] or name
        else:
            what = t("dialog.n_items", n=len(entries))
            stem = os.path.basename(folder.rstrip(os.sep)) or "Archiv"
        dlg = CompressDialog(self, what, stem, folder)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        stem = dlg.stem()
        if not stem:
            show_error(self, t("title.compress"), t("error.archive_name_empty"))
            return
        if "/" in stem or stem in (".", ".."):
            show_error(self, t("title.compress"), t("error.invalid_name", name=stem))
            return
        fmt = dlg.archive_format()
        archive = os.path.join(folder, archives.unique_archive_name(folder, stem, fmt))
        self.ops.start(COMPRESS, [e.path for e in entries], folder, options={"archive": archive, "format": fmt})

    def _start_extract(self, jobs: list[tuple[str, str]]) -> None:
        jobs = [(a, d) for a, d in jobs if archives.can_extract(archives.archive_format(os.path.basename(a)))]
        if jobs:
            self.ops.start(EXTRACT, [a for a, _d in jobs], self.active.current_path, options={"jobs": jobs})

    def do_extract_here(self) -> None:
        folder = self.active.current_path
        self._start_extract([(a, folder) for a in self._selected_archives()])

    def do_extract_subfolder(self) -> None:
        folder = self.active.current_path
        self._start_extract([(a, os.path.join(folder, archives.archive_stem(os.path.basename(a))))
                             for a in self._selected_archives()])

    def do_extract_to(self) -> None:
        paths = self._selected_archives()
        if not paths:
            return
        other = self.other
        default = other.current_path if not self.single_mode and not other.in_trash else self.active.current_path
        what = t("dialog.one_item", name=os.path.basename(paths[0])) if len(paths) == 1 else t("dialog.n_items", n=len(paths))
        dlg = ExtractToDialog(self, what, default)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        target = dlg.target()
        self._start_extract([(a, target) for a in paths])

    # --- Mehrfach umbenennen (F-700 ff.) ------------------------------------------------------
    def _make_rename_pane(self, side: str):
        from .renamepane import PreviewModel, RenamePane

        pane = RenamePane()
        pane.changed.connect(self._update_rename_preview)
        pane.rename_clicked.connect(self._do_multi_rename)
        pane.cancel_clicked.connect(self.leave_rename_mode)
        pane.save_profile_clicked.connect(self._save_rename_profile)
        pane.delete_profile_clicked.connect(self._delete_rename_profile)
        pane.preview_model = PreviewModel(self.icons, pane)
        return pane

    def _rename_pane(self):
        side = self.rename_mode["side"] if self.rename_mode is not None else self.active_side
        return self.sides[side].sidebar.widget_for(MODE_RENAME)

    def do_multi_rename(self) -> None:
        if self.rename_mode is not None or self.active.in_trash:
            return
        from . import multirename as mr

        side = self.active_side
        s = self.sides[side]
        self.rename_mode = {
            "side": side, "single": self.single_mode, "sidebar": s.sidebar.mode,
            "inner": s.splitter.sizes(),
        }
        if not self.single_mode:
            self.set_single_mode(True)
        pane = self._rename_pane()
        pane.set_options(mr.RenameOptions.from_dict(self.settings.get("multirename_last")))
        s.sidebar.set_mode(MODE_RENAME)
        total = sum(s.splitter.sizes())
        s.splitter.setSizes([400, max(total - 400, 200)])
        s.panel.set_preview_mode(True, pane.preview_model)
        s.panel.model.modelReset.connect(self._update_rename_preview)
        s.panel.model.layoutChanged.connect(self._update_rename_preview)
        # Gesperrte Funktionen sichtbar ausgrauen (F-706)
        self._rename_disabled = [aid for aid, act in self.qactions.items()
                                 if act.isEnabled() and aid not in self.RENAME_ALLOWED]
        for aid in self._rename_disabled:
            self.qactions[aid].setEnabled(False)
        self.fkey_bar.setEnabled(False)
        self._update_rename_preview()
        pane.pattern.setFocus()
        pane.pattern.selectAll()

    def _rename_items(self):
        from . import multirename as mr

        panel = self.sides[self.rename_mode["side"]].panel
        entries = [e for e in panel.model.entries() if not e.is_parent]
        items = [mr.Item(e.name, e.is_dir, e.mtime, e.birth_time()) for e in entries]
        return panel, entries, items

    def _update_rename_preview(self) -> None:
        if self.rename_mode is None:
            return
        from . import multirename as mr

        pane = self._rename_pane()
        panel, entries, items = self._rename_items()
        opts = pane.options()
        error = mr.validate(opts)
        try:
            existing = set(os.listdir(panel.current_path))
        except OSError:
            existing = {e.name for e in entries}
        results = [] if error else mr.compute(items, opts, existing)
        if error:
            results = [mr.Result(i.name, i.name, mr.SAME) for i in items]
        pane.preview_model.set_data(entries, results)
        pane.preview_model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 4)
        changes = sum(1 for r in results if r.status == mr.OK)
        conflicts = sum(1 for r in results if r.status == mr.CONFLICT)
        pane.show_state(error, changes, conflicts, len(results))
        panel._sync_preview_sort_indicator()

    def leave_rename_mode(self, select: list[str] | None = None) -> None:
        state = self.rename_mode
        if state is None:
            return
        pane = self._rename_pane()
        self.settings.set("multirename_last", pane.options().to_dict())
        s = self.sides[state["side"]]
        try:
            s.panel.model.modelReset.disconnect(self._update_rename_preview)
            s.panel.model.layoutChanged.disconnect(self._update_rename_preview)
        except (RuntimeError, TypeError):
            pass
        self.rename_mode = None
        s.panel.set_preview_mode(False)
        s.sidebar.set_mode(state["sidebar"])
        for aid in getattr(self, "_rename_disabled", []):
            self.qactions[aid].setEnabled(True)
        self._rename_disabled = []
        self.fkey_bar.setEnabled(True)
        if not state["single"]:
            self.set_single_mode(False)
        QApplication.processEvents()
        s.splitter.setSizes(state["inner"])
        s.panel.refresh()
        if select:
            s.panel.select_names(select, current=select[0])
        self.qactions["rename_undo"].setEnabled(self.last_rename is not None)
        s.panel.view.setFocus()

    def _do_multi_rename(self) -> None:
        from . import multirename as mr

        if self.rename_mode is None:
            return
        self._update_rename_preview()
        pane = self._rename_pane()
        if not pane.btn_rename.isEnabled():
            return
        panel = self.sides[self.rename_mode["side"]].panel
        folder = panel.current_path
        pairs = [(r.old, r.new) for r in pane.preview_model.results if r.status == mr.OK]
        done, errors = mr.perform(folder, pairs)
        if done:
            self.last_rename = (folder, done)
        self.leave_rename_mode([new for _old, new in done])
        if errors:
            self._show_rename_errors(folder, errors)

    def _show_rename_errors(self, folder: str, errors: list[tuple[str, str]]) -> None:
        from .dialogs import ErrorListDialog

        lines = [(os.path.join(folder, name), t("rename.err_exists_now") if reason == "exists" else reason)
                 for name, reason in errors]
        dlg = ErrorListDialog(self, t("rename.title"), t("rename.errors_intro"), lines)
        dlg.exec()

    def do_rename_undo(self) -> None:
        from . import multirename as mr

        if self.last_rename is None:
            return
        folder, done = self.last_rename
        pairs = [(new, old) for old, new in done]
        undone, errors = mr.perform(folder, pairs)
        self.last_rename = None
        self.qactions["rename_undo"].setEnabled(False)
        for s in self.sides.values():
            if os.path.normpath(s.panel.current_path) == os.path.normpath(folder):
                s.panel.refresh()
                if undone:
                    s.panel.select_names([old for _n, old in undone], current=undone[0][1])
        if errors:
            self._show_rename_errors(folder, errors)

    def _save_rename_profile(self) -> None:
        from .renamepane import profile_names, save_profile

        pane = self._rename_pane()
        name = ask_text(self, t("rename.profile_save_title"), t("rename.profile_name"),
                        pane.current_profile() or t("rename.profile_default"))
        if not name:
            return
        name = name.strip()
        if any(c in name for c in '/\\:*?"<>|') or name.startswith(".") or not name:
            show_error(self, t("rename.profile_save_title"), t("favsets.error_chars", name=name))
            return
        if name in profile_names() and name != pane.current_profile():
            if not confirm(self, t("rename.profile_save_title"), t("rename.profile_overwrite", name=name)):
                return
        save_profile(name, pane.options())
        pane.refresh_profiles(select=name)

    def _delete_rename_profile(self) -> None:
        from .renamepane import delete_profile

        pane = self._rename_pane()
        name = pane.current_profile()
        if not name or not confirm(self, t("rename.profile_delete_title"), t("rename.profile_delete_confirm", name=name),
                                   yes_key="button.delete"):
            return
        try:
            delete_profile(name)
        except OSError as exc:
            show_error(self, t("rename.profile_delete_title"), exc.strerror or str(exc))
        pane.refresh_profiles(select="")

    def _sidebar_switch_actions(self, menu: QMenu, side: str, current: str) -> None:
        """Umschaltung der Seitenleiste im Kontextmenü (F-240)."""
        menu.addSeparator()
        for mode, key in ((MODE_FAVORITES, "sidebar.switch_favorites"), (MODE_TREE, "sidebar.switch_tree")):
            if mode != current:
                act = menu.addAction(t(key))
                act.triggered.connect(lambda _c=False, m=mode: self.set_sidebar_mode(side, m))
        act = menu.addAction(t("sidebar.hide"))
        act.triggered.connect(lambda _c=False: self.set_sidebar_mode(side, MODE_OFF))

    def _tree_context_menu(self, side: str, view: FolderTreeView, pos: QPoint) -> None:
        self.set_active_side(side)
        idx = view.indexAt(pos)
        path = view.path_of(idx) if idx.isValid() else None
        menu = QMenu(self)
        if path:
            act = menu.addAction(t("action.open"))
            act.triggered.connect(lambda _c=False: self._open_tree_path(side, path))
            act = menu.addAction(t("action.add_favorite"))
            act.triggered.connect(lambda _c=False: self._add_favorite_paths([path]))
            self._mount_actions(menu, path if self.mounts.entry_for_mount_point(path) else None)
        elif idx.isValid() and view.disk_of(idx) is not None:
            self._disk_actions(menu, view.disk_of(idx), separator=False)
        self._sidebar_switch_actions(menu, side, MODE_TREE)
        menu.exec(view.viewport().mapToGlobal(pos))

    def _favorites_context_menu(self, side: str, view: FavoritesView, pos: QPoint) -> None:
        self.set_active_side(side)
        idx = view.indexAt(pos)
        if idx.isValid():
            view.setCurrentIndex(idx)
        else:
            view.clearSelection()
        view.setFocus()
        menu = QMenu(self)
        a = self.qactions
        items = (("fav_open", None, "fav_edit", "fav_rename", "fav_new_group", "fav_delete")
                 if idx.isValid() else ("fav_new_group",))
        for aid in items:
            menu.addSeparator() if aid is None else menu.addAction(a[aid])
        if idx.isValid():
            node = view.fav_model.node(idx)
            if not node.is_group and self.mounts.entry_for_mount_point(node.path):
                self._mount_actions(menu, node.path)
        self._sidebar_switch_actions(menu, side, MODE_FAVORITES)
        menu.exec(view.viewport().mapToGlobal(pos))

    # --- Drag & Drop / Operationen ---------------------------------------------------------------
    def _on_drop(self, paths: list[str], target: str, action) -> None:
        if is_trash_uri(target):
            self._trash_paths(paths)
            return
        kind = MOVE if action == Qt.DropAction.MoveAction else COPY
        if kind == MOVE and any(self._in_trash_dir(p) for p in paths):
            kind = COPY  # aus dem Papierkorb nur kopieren (F-409)
        self.ops.start(kind, paths, target)

    # --- Papierkorb ------------------------------------------------------------------------
    def _trash_mount_points(self) -> list[str]:
        return [e.mount_point for d in self.mounts.disks() for e in d.entries if e.mounted and e.mount_point != "/"]

    def _trash_network_mount_points(self) -> list[str]:
        """Eingehängte Netzfreigaben – auch dort legt das Löschen einen Papierkorb an."""
        from .mounts import KIND_NETWORK

        return [e.mount_point for e in self.mounts.entries(KIND_NETWORK) if e.mounted]

    def _in_trash_dir(self, path: str) -> bool:
        return any(path.startswith(d.rstrip("/") + "/") for d in self.trash.files_dirs())

    def _trash_paths(self, paths: list[str]) -> None:
        paths = [p for p in paths if not self._in_trash_dir(p)]
        if paths:
            self.ops.start(TRASH, paths)

    def update_network_trash_state(self) -> None:
        """Papierkörbe auf Netzfreigaben nur bei Anlass prüfen, nicht alle 2 Sekunden."""
        self._network_trash_full = not self.trash.is_empty(network=True, local=False)
        self.update_trash_state()

    def update_trash_state(self) -> None:
        full = self._network_trash_full or not self.trash.is_empty(network=False)
        if full == self._trash_full:
            return
        self._trash_full = full
        self.button_bar.set_trash_full(full)
        for tree in self._trees():
            tree.tree_model.set_trash_full(full)

    def do_open_trash(self) -> None:
        self.update_network_trash_state()
        self.active.navigate(TRASH_URI)
        self.active.view.setFocus()

    def _trash_selection(self):
        panel = self.active
        if not panel.in_trash:
            return [], {}
        entries = panel.target_entries()
        info = {e.path: (e.original_path, e.info_path) for e in entries}
        return [e.path for e in entries], info

    def do_trash_restore(self) -> None:
        sources, info = self._trash_selection()
        if sources:
            self.ops.start(RESTORE, sources, trash_info=info)

    def do_trash_purge(self) -> None:
        sources, info = self._trash_selection()
        if not sources:
            return
        names = [os.path.basename(info[s][0]) for s in sources]
        what = t("dialog.one_item", name=names[0]) if len(names) == 1 else t("dialog.n_items", n=len(names))
        key = "dialog.trash_purge_confirm_one" if len(names) == 1 else "dialog.trash_purge_confirm"
        if confirm(self, t("title.delete"), t(key, what=what),
                   yes_key="button.delete", default_yes=False, warning=True):
            self.ops.start(PURGE, sources, trash_info=info)

    def do_trash_empty(self) -> None:
        items = self.trash.items()
        if not items:
            show_info(self, t("trash.title"), t("trash.already_empty"))
            return
        if confirm(self, t("title.trash_empty"), t("dialog.trash_empty_confirm", n=len(items)),
                   yes_key="button.empty_trash", default_yes=False, warning=True):
            self.ops.start(PURGE, [i.file_path for i in items],
                           trash_info={i.file_path: (i.original_path, i.info_path) for i in items})

    def _trash_button_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction(self.qactions["open_trash"])
        menu.addAction(self.qactions["trash_empty"])
        menu.exec(pos)

    # --- Ein-Fenster-Ansicht ----------------------------------------------------------------
    def do_toggle_single(self) -> None:
        self.set_single_mode(not self.single_mode)

    def set_single_mode(self, on: bool) -> None:
        self.single_mode = on
        other = self.sides[self.other_side].splitter
        other.setVisible(not on)
        self.button_bar.setVisible(not on and bool(self.settings.get("show_buttonbar")))
        self.qactions["toggle_single"].setChecked(on)
        # Menü „Ansicht“: in der Ein-Fenster-Ansicht nur eine „Seitenleiste“ (ohne links/rechts)
        for side, sub in self.sidebar_submenus.items():
            sub.menuAction().setVisible(not on or side == self.active_side)
            sub.setTitle(t("menu.sidebar") if on else t(f"menu.sidebar_{side}"))
        self.qactions["toggle_sidebar"].setText(t("action.toggle_sidebar_single") if on else t("action.toggle_sidebar"))
        self.qactions["toggle_buttonbar"].setEnabled(not on)
        for aid in self.SINGLE_BLOCKED:
            self.qactions[aid].setEnabled(not on)
        self._update_fkey_enabled()
        self.active.view.setFocus()

    def _on_operation_finished(self, kind: str, target: str, created: list[str]) -> None:
        for s in self.sides.values():
            panel = s.panel
            follow = panel.property("cursor_after_delete")
            panel.refresh()
            if kind in (TRASH, DELETE) and follow:
                panel.select_names([], current=follow)
                panel.setProperty("cursor_after_delete", None)
            if kind in (COPY, MOVE, COMPRESS, EXTRACT) and created and os.path.normpath(panel.current_path) == os.path.normpath(target):
                panel.select_names(created, current=created[0])
        for m in self.fav_sets.loaded_models():
            m.layoutChanged.emit()
        self.update_network_trash_state()

    # --- Zustand ----------------------------------------------------------------------------
    def _restore_state(self) -> None:
        state = load_json(STATE_FILE, {})
        if not isinstance(state, dict):
            state = {}
        geometry = state.get("geometry")
        if isinstance(geometry, str):
            self.restoreGeometry(QByteArray.fromHex(geometry.encode()))
        else:
            self.resize(1280, 780)
        sides_state = state.get("sides", {}) if isinstance(state.get("sides"), dict) else {}
        home = str(Path.home())
        for name in SIDES:
            s = self.sides[name]
            st = sides_state.get(name, {}) if isinstance(sides_state.get(name), dict) else {}
            available = {d.id for d in SIDEBARS if d.available}
            last = st.get("last_sidebar", MODE_FAVORITES)
            self.last_sidebar_mode[name] = last if last in available and last != MODE_OFF else MODE_FAVORITES
            mode = st.get("sidebar", MODE_FAVORITES)
            if mode not in available:
                mode = MODE_FAVORITES
            self.fav_set[name] = self.fav_sets.resolve(st.get("fav_set"))
            self.set_sidebar_mode(name, mode)
            header = st.get("header")
            columns = st.get("columns")
            if isinstance(header, str):
                cols = st.get("header_columns", 10)
                s.panel.restore_header_state(header, cols if isinstance(cols, int) else 10)
            elif isinstance(columns, list):
                s.panel.set_column_widths(columns)
            sort = st.get("sort")
            if isinstance(sort, list) and len(sort) == 2:
                try:
                    s.panel.set_sort_state(int(sort[0]), int(sort[1]))
                except (TypeError, ValueError):
                    pass
            path = st.get("path") if isinstance(st.get("path"), str) else home
            if self.mounts.needs_mount(path) is not None:
                # Ausgehängte Freigabe nicht von selbst einhängen (F-500): persönlicher Ordner
                s.panel.navigate(home)
            else:
                s.panel.navigate(nearest_existing_dir(path))
            history = st.get("history")
            if isinstance(history, list) and all(isinstance(h, str) for h in history):
                pos = st.get("history_pos", len(history) - 1)
                s.panel.set_history_state(history, pos if isinstance(pos, int) else len(history) - 1)
            inner = st.get("inner")
            if isinstance(inner, list) and len(inner) == 2:
                s.splitter.setSizes([int(x) for x in inner])
            else:
                s.splitter.setSizes([200, 440])
            pane = self._fav_pane(name)
            if pane is not None:
                pane.view.restore_expanded(st.get("expanded", []))
        outer = state.get("outer")
        if isinstance(outer, list) and len(outer) == 3:
            self.outer.setSizes([int(x) for x in outer])
        elif isinstance(outer, list) and len(outer) == 2:  # Zustand aus v0.2
            self.outer.setSizes([int(outer[0]), 36, int(outer[1])])
        else:
            self.outer.setSizes([640, 36, 640])
        active = state.get("active", "left")
        self.set_active_side(active if active in SIDES else "left")
        if state.get("single") is True:
            self.set_single_mode(True)
        self.active.view.setFocus()

    def save_state(self) -> None:
        sides_state = {}
        for name, s in self.sides.items():
            history, pos = s.panel.history_state()
            pane = self._fav_pane(name)
            view = pane.view if pane is not None else None
            col, order = s.panel.sort_state()
            sides_state[name] = {
                "path": s.panel.current_path,
                "sort": [col, order],
                "header": s.panel.header_state(),
                "header_columns": COLUMN_COUNT,
                "sidebar": s.sidebar.mode,
                "last_sidebar": self.last_sidebar_mode.get(name, MODE_FAVORITES),
                "fav_set": self.fav_set[name],
                "column_profile": s.panel.column_profile,
                "inner": s.splitter.sizes(),
                "expanded": view.expanded_ids() if isinstance(view, FavoritesView) else [],
                "history": history[-20:],
                "history_pos": max(-1, pos - max(0, len(history) - 20)),
            }
        state = {
            "version": 1,
            "geometry": bytes(self.saveGeometry().toHex()).decode(),
            "outer": self.outer.sizes(),
            "active": self.active_side,
            "single": self.single_mode,
            "sides": sides_state,
        }
        try:
            save_json(STATE_FILE, state)
        except OSError:
            pass

    def closeEvent(self, event) -> None:
        if self.rename_mode is not None:
            self.leave_rename_mode()
        if self.meta_mode is not None and not self.meta_close(then=self.close):
            event.ignore()
            return
        skip = getattr(self, "_skip_save_state", False)  # nach „Wiederherstellen“ nichts überschreiben
        self._stop_search()
        for side in list(self.tool_mode):
            self.close_tool(side)
        for side in SIDES:  # noch nicht gespeicherte Spaltenänderungen ins Profil
            panel = self.sides[side].panel
            if panel._columns_timer.isActive() and not skip:
                panel._columns_timer.stop()
                self._save_column_profile(side)
        if self.ops.is_busy():
            if not confirm(self, t("title.quit"), t("dialog.quit_running"), yes_key="button.quit", default_yes=False):
                event.ignore()
                return
            self.ops.wait_all()
        if not skip:
            self.save_state()
        QApplication.instance().removeEventFilter(self.key_filter)
        super().closeEvent(event)

