"""Hauptfenster-Teil für „Ordner synchronisieren“ als Seitenleiste mit Vergleichsansicht (v1.18, L-1800 ff.)."""

from __future__ import annotations

import os

from PySide6.QtCore import QTimer

from .i18n import t

MODE_SYNC = "sync"  # Seitenleiste „Synchronisieren“ – nicht im Menü wählbar
SYNC_ALLOWED = {"quit", "about", "help", "help_online", "check_updates", "donate", "sync_folders",
                "sync_start", "sync_delete_right"}
SYNC_FKEYS = {"F1": "help", "F5": "sync_start", "F8": "sync_delete_right"}  # L-1806


class SyncMixin:
    sync_mode = None  # dict mit dem vorherigen Zustand, solange die Vergleichsansicht offen ist

    def _make_sync_pane(self, side: str):
        from .syncmode import SyncPane

        pane = SyncPane(self)
        pane.close_clicked.connect(self.leave_sync_mode)
        return pane

    def sync_pane(self):
        side = self.sync_mode["side"] if self.sync_mode is not None else "left"
        return self.sides[side].sidebar.widget_for(MODE_SYNC)

    def _sync_folders(self) -> tuple[str, str]:
        """Linker und rechter Ordner, sofern es lokale Ordner sind (L-1619)."""
        out = []
        for side in ("left", "right"):
            p = self.sides[side].panel
            ok = not p.in_trash and not p.search_mode and p.remote is None and os.path.isdir(p.current_path or "")
            out.append(p.current_path if ok else "")
        return out[0], out[1]

    def do_sync_folders(self, profile: str | None = None) -> None:
        """L-1800: Vergleichsansicht im Hauptfenster."""
        if self.sync_mode is not None:
            if profile and self.sync_pane().load_profile(profile):
                QTimer.singleShot(0, self.sync_pane().compare)
            return
        if self.meta_mode is not None or self.rename_mode is not None:
            return
        left, right = self._sync_folders()
        for other in list(getattr(self, "tool_mode", {}) or {}):
            self.close_tool(other)
        self.set_active_side("left")
        s = self.sides["left"]
        self.sync_mode = {"side": "left", "single": self.single_mode, "sidebar": s.sidebar.mode,
                          "inner": self._bar_sizes(s.name), "path_visible": s.panel.path_edit.isVisible()}
        if not self.single_mode:
            self.set_single_mode(True)
        s.sidebar.set_mode(MODE_SYNC)
        pane = self.sync_pane()
        pane.set_paths(left, right)
        self._widen_bar(s.name, 380, 300)
        s.panel.set_custom_view(pane.view)
        s.panel.path_edit.setVisible(False)
        self._sync_disabled = [aid for aid, act in self.qactions.items()
                               if act.isEnabled() and aid not in SYNC_ALLOWED]
        for aid in self._sync_disabled:
            self.qactions[aid].setEnabled(False)
        labels = {"F1": t("action.help").rstrip(" …"), "F5": t("sync.start"), "F8": t("sync.set_del_right")}
        self.fkey_bar.set_labels(labels, {"F5": t("sync.start"), "F8": t("sync.set_del_right")})
        self.fkey_bar.set_disabled({k for k in self.fkey_bar.buttons if k not in SYNC_FKEYS})
        self.fkey_bar.set_layer("")
        if profile and pane.load_profile(profile):
            QTimer.singleShot(0, pane.compare)
        pane.view.tree.setFocus()

    def leave_sync_mode(self) -> None:
        state = self.sync_mode
        if state is None:
            return
        pane = self.sync_pane()
        pane.remember()
        s = self.sides[state["side"]]
        self.sync_mode = None
        s.panel.set_custom_view(None)
        s.panel.path_edit.setVisible(state["path_visible"])
        s.sidebar.set_mode(state["sidebar"])
        for aid in getattr(self, "_sync_disabled", []):
            self.qactions[aid].setEnabled(True)
        self._sync_disabled = []
        self._refresh_fkey_display()
        if not state["single"]:
            self.set_single_mode(False)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        self._restore_bar(s.name, state["inner"])
        self.do_refresh()
        self._update_nav_actions()
        s.panel.focus_view()

    def do_sync_start(self) -> None:
        if self.sync_mode is not None:
            self.sync_pane().start()

    def do_sync_delete_right(self) -> None:
        from . import folderdiff as fd

        if self.sync_mode is not None:
            self.sync_pane().set_selected(fd.DEL_RIGHT)

    def _fill_sync_menu(self) -> None:
        from . import syncprofiles as sp

        self.sync_menu.clear()
        profiles = sp.load()
        if not profiles:
            act = self.sync_menu.addAction(t("menu.sync_profiles_none"))
            act.setEnabled(False)
        from .syncmode import last_run_date, last_run_tooltip
        from .toolicons import last_run_icon

        self.sync_menu.setToolTipsVisible(True)
        for p in profiles:
            # L-1901: Ergebnis des letzten Laufs hinter dem Namen
            text = p.name if p.last is None else f"{p.name}\t{last_run_date(p.last)}"
            act = self.sync_menu.addAction(last_run_icon(p.last), text)
            if p.last is not None:
                act.setToolTip(last_run_tooltip(p.last))
            act.triggered.connect(lambda _c=False, n=p.name: self.do_sync_folders(n))
