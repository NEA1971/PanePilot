"""Server im Hauptfenster (v1.3): Seitenleiste „Server“, Verbinden, Arbeiten auf dem Server, Übertragungen."""

from __future__ import annotations

import os
import posixpath

from PySide6.QtCore import QEventLoop, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import QDialog, QMenu, QProgressDialog

from . import remotefs as rf
from . import servers as sv
from .dialogs import confirm, show_error, show_info
from .i18n import t

from .sidebars import MODE_SERVERS  # noqa: E402

# Auf dem Server nicht möglich (L-343)
REMOTE_BLOCKED = {"new_textfile", "edit_text", "open_with_other", "multi_rename", "compress", "meta_wizard",
                  "search", "checksums", "extract_here", "extract_subfolder", "extract_to", "open_terminal",
                  "dir_list", "clip_cut", "clip_copy", "clip_paste", "add_favorite", "same_path", "rename_undo"}


class _Task(QThread):
    done = Signal()

    def __init__(self, fn, parent=None) -> None:
        super().__init__(parent)
        self.fn = fn
        self.value = None
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            self.value = self.fn()
        except BaseException as exc:  # noqa: BLE001 – wird im Hauptthread ausgewertet
            self.error = exc


def run_task(parent, fn, text: str, cancel_flag: list | None = None):
    """fn im Hintergrund ausführen, dabei ein Wartefenster zeigen. (Wert, Ausnahme, abgebrochen)."""
    dlg = QProgressDialog(text, t("button.cancel"), 0, 0, parent)
    dlg.setWindowTitle(t("srv.title"))
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    dlg.setMinimumDuration(400)
    task = _Task(fn)
    loop = QEventLoop()
    task.finished.connect(loop.quit)
    state = {"cancel": False}

    def cancel() -> None:
        state["cancel"] = True
        if cancel_flag is not None:
            cancel_flag[0] = True
        loop.quit()
    dlg.canceled.connect(cancel)
    task.start()
    if not task.isFinished():
        loop.exec()
    dlg.canceled.disconnect()
    dlg.close()
    if state["cancel"] and not task.isFinished():
        task.finished.connect(task.deleteLater)
        task.setParent(None)
        _orphans.append(task)
        return None, None, True
    task.wait()
    return task.value, task.error, state["cancel"]


_orphans: list = []  # abgebrochene Abfragen laufen im Hintergrund zu Ende


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, rf.AuthFailed):
        return t("srv.auth_failed", reason=str(exc))
    if isinstance(exc, rf.NoSftp):
        return t("srv.no_sftp")
    if isinstance(exc, OSError) and exc.strerror:
        return exc.strerror
    return str(exc) or type(exc).__name__


class RemoteSession:
    """Eine bestehende Verbindung, angezeigt in einem Dateifenster."""

    def __init__(self, window, side: str, cfg: rf.ServerConfig, conn: rf.Connection, password: str,
                 passphrase: str) -> None:
        self.window, self.side, self.cfg, self.conn = window, side, cfg, conn
        self.password, self.passphrase = password, passphrase
        self.base = cfg.base_uri()

    def path_of(self, uri: str) -> str:
        return uri[len(self.base):] or "/" if uri.startswith(self.base) else uri

    def call(self, fn, text: str | None = None, quiet: bool = False):
        """fn(conn) ausführen; bei abgerissener Verbindung „Neu verbinden“ anbieten. (Wert, Fehlertext)."""
        for attempt in (1, 2):
            value, error, cancelled = run_task(self.window, lambda: fn(self.conn), text or t("srv.working"))
            if cancelled:
                return None, ""
            if error is None:
                return value, None
            if isinstance(error, rf.ConnectionLost) and attempt == 1:
                if confirm(self.window, t("srv.title"), t("srv.lost", name=self.cfg.name, reason=str(error)),
                           yes_key="srv.reconnect"):
                    if self.reconnect():
                        continue
                self.window.remote_disconnect(self.side)
                return None, ""
            if not quiet:
                show_error(self.window, t("srv.title"), describe_error(error))
            return None, describe_error(error)
        return None, ""

    def reconnect(self) -> bool:
        cfg, pw, pp = self.cfg, self.password, self.passphrase
        conn, error, cancelled = run_task(self.window, lambda: rf.Connection.open(cfg, pw, pp),
                                          t("srv.connecting", name=cfg.name))
        if conn is None:
            if error is not None and not cancelled:
                show_error(self.window, t("srv.title"), describe_error(error))
            return False
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass
        self.conn = conn
        return True

    def listdir(self, path: str):
        value, _err = self.call(lambda c: c.listdir(path), t("srv.loading"))
        return value

    def rename_entry(self, entry, new_name: str) -> str | None:
        old = self.path_of(entry.path)
        new = posixpath.join(posixpath.dirname(old), new_name)
        _v, err = self.call(lambda c: c.rename(old, new), quiet=True)
        return err if err is not None else None

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:  # noqa: BLE001
            pass


class RemoteMixin:
    """Wird in MainWindow eingemischt."""

    # --- Grundlagen ---------------------------------------------------------------------------------------
    def _init_remote(self) -> None:
        self.server_store = sv.ServerStore()
        self.remote_sessions: dict[str, RemoteSession] = {}
        self.server_models: dict[str, object] = {}
        self._transfers = None

    @property
    def transfers(self):
        if self._transfers is None:
            from .transfers import TransferManager

            self._transfers = TransferManager(self, self.settings)
            self._transfers.job_done.connect(lambda _job: self._refresh_after_transfer())
        return self._transfers

    def _refresh_after_transfer(self) -> None:
        for s in self.sides.values():
            s.panel.refresh()

    def _make_server_view(self, side: str):
        from .serverui import ServerModel, ServerView

        model = ServerModel(self.icons.folder(), self)
        model.populate(self.server_store)
        model.connected = {s.cfg.id for s in self.remote_sessions.values()}
        model.refresh_states()
        view = ServerView(model)
        view.setObjectName(f"servers_{side}")
        view.connect_requested.connect(lambda sid, s=side: self.remote_connect(s, sid))
        view.focus_entered.connect(lambda s=side: self.set_active_side(s))
        view.customContextMenuRequested.connect(lambda pos, s=side, v=view: self._server_context_menu(s, v, pos))
        view.dropped.connect(lambda m=model: self._server_tree_dropped(m))
        self.server_models[side] = model
        return self._pane(side, view, t("sidebar.servers_title"))

    def server_view(self, side: str):
        from .serverui import ServerView
        from .sidebars import SidebarPane

        w = self.sides[side].sidebar._widgets.get(MODE_SERVERS)
        w = w.view if isinstance(w, SidebarPane) else w
        return w if isinstance(w, ServerView) else None

    def _refresh_server_views(self) -> None:
        connected = {s.cfg.id for s in self.remote_sessions.values()}
        for side, model in self.server_models.items():
            model.connected = connected
            model.populate(self.server_store)
            view = self.server_view(side)
            if view is not None:
                view.expandAll()

    def _server_tree_dropped(self, model) -> None:
        self.server_store.root = model.to_tree()
        self.server_store.save()
        self._refresh_server_views()

    # --- Verbinden ---------------------------------------------------------------------------------------
    def _ask_secret(self, cfg: rf.ServerConfig, passphrase: bool, offer_save: bool) -> tuple[str | None, bool]:
        from .serverui import PasswordDialog

        dlg = PasswordDialog(self, cfg, passphrase, offer_save)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None, False
        return dlg.edit.text(), dlg.save.isVisible() and dlg.save.isChecked()

    def remote_connect(self, side: str, server_id: str) -> bool:
        from .serverui import confirm_host_key

        cfg = self.server_store.by_id(server_id)
        if cfg is None:
            return False
        if not cfg.host:
            show_error(self, t("srv.title"), t("srv.no_host", name=cfg.name))
            return False
        panel = self.sides[side].panel
        if panel.locked:
            return False
        current = self.remote_sessions.get(side)
        if current is not None and current.cfg.id == cfg.id:
            self.set_active_side(side)
            panel.view.setFocus()
            return True
        password = passphrase = ""
        save_password = False
        if cfg.logon == rf.LOGON_NORMAL:
            password = sv.load_secret(cfg.id) or ""
            if not password:
                password, save_password = self._ask_secret(cfg, False, True)
                if password is None:
                    return False
        elif cfg.logon == rf.LOGON_ASK:
            password, _s = self._ask_secret(cfg, False, False)
            if password is None:
                return False
        elif cfg.logon == rf.LOGON_KEY:
            passphrase = sv.load_secret(cfg.id, "passphrase") or ""
        conn = None
        for _attempt in range(4):
            conn, error, cancelled = run_task(self, lambda: rf.Connection.open(cfg, password, passphrase),
                                              t("srv.connecting", name=cfg.name))
            if cancelled:
                return False
            if conn is not None:
                break
            if isinstance(error, (rf.UnknownHostKey, rf.UnknownCertificate)):
                if not confirm_host_key(self, error):
                    return False
                if isinstance(error, rf.UnknownHostKey):
                    rf.trust_host_key(error)
                else:
                    rf.trust_certificate(error.host, error.fingerprint)
                continue
            if isinstance(error, rf.AuthFailed) and cfg.logon in (rf.LOGON_NORMAL, rf.LOGON_ASK, rf.LOGON_KEY):
                show_error(self, t("srv.title"), describe_error(error))
                is_key = cfg.logon == rf.LOGON_KEY
                value, save = self._ask_secret(cfg, is_key, cfg.logon != rf.LOGON_ASK)
                if value is None:
                    return False
                if is_key:
                    passphrase = value
                else:
                    password = value
                save_password = save
                continue
            show_error(self, t("srv.title"), t("srv.connect_failed", name=cfg.name, reason=describe_error(error)))
            return False
        if conn is None:
            return False
        if save_password:
            kind = "passphrase" if cfg.logon == rf.LOGON_KEY else "password"
            sv.store_secret(cfg.id, passphrase if kind == "passphrase" else password, cfg.name, kind)
        session = RemoteSession(self, side, cfg, conn, password, passphrase)
        start = cfg.remote_dir.strip() or None
        if start is None:
            start, _e = session.call(lambda c: c.home(), quiet=True)
            start = start or "/"
        if current is not None:
            panel.close_remote(navigate_away=False)
        self.remote_sessions[side] = session
        if not panel.attach_remote(session, start if start.startswith("/") else "/" + start):
            self.remote_sessions.pop(side, None)
            session.close()
            self._refresh_server_views()
            return False
        self.set_active_side(side)
        panel.view.setFocus()
        other = self.sides[self._other_of(side)].panel
        if cfg.local_dir and os.path.isdir(cfg.local_dir) and not other.in_remote and not other.locked:
            other.navigate(cfg.local_dir)
        self._refresh_server_views()
        return True

    def _other_of(self, side: str) -> str:
        return "right" if side == "left" else "left"

    def _on_remote_closed(self, side: str, session) -> None:
        if self.remote_sessions.get(side) is session:
            self.remote_sessions.pop(side, None)
        session.close()
        self._refresh_server_views()

    def remote_disconnect(self, side: str) -> None:
        panel = self.sides[side].panel
        if panel.remote is not None:
            panel.close_remote()

    def remote_disconnect_all(self) -> None:
        for side in list(self.remote_sessions):
            panel = self.sides[side].panel
            session = panel.remote
            if session is not None:
                panel.remote = None
                self._on_remote_closed(side, session)

    # --- Kontextmenü der Seitenleiste (L-313) ---------------------------------------------------------------
    def _server_context_menu(self, side: str, view, pos) -> None:
        from .serverui import ID_ROLE

        self.set_active_side(side)
        idx = view.indexAt(pos)
        menu = QMenu(self)
        sid = idx.data(ID_ROLE) if idx.isValid() else None
        is_folder = idx.isValid() and not sid
        if sid:
            connected = any(s.cfg.id == sid for s in self.remote_sessions.values())
            menu.addAction(t("srv.connect")).triggered.connect(lambda _c=False: self.remote_connect(side, sid))
            act = menu.addAction(t("srv.disconnect"))
            act.setEnabled(connected)
            act.triggered.connect(lambda _c=False: self._disconnect_server(sid))
            menu.addSeparator()
            menu.addAction(t("srv.edit")).triggered.connect(lambda _c=False: self.do_server_manager(select_id=sid))
            menu.addAction(t("srv.copy")).triggered.connect(lambda _c=False: self._server_copy(sid))
            menu.addAction(t("srv.rename")).triggered.connect(lambda _c=False: self._server_rename(view, idx))
            menu.addAction(t("srv.delete")).triggered.connect(lambda _c=False: self._server_delete(view, idx))
            menu.addSeparator()
        elif is_folder:
            pass
        folder_path = view.model().node_path(idx) if is_folder else (
            view.model().node_path(idx.parent()) if idx.isValid() else [])
        menu.addAction(t("srv.new_server") + " …").triggered.connect(
            lambda _c=False: self.do_server_manager(new_in_folder=folder_path))
        menu.addAction(t("srv.new_folder")).triggered.connect(lambda _c=False: self._server_new_folder(folder_path))
        if is_folder:
            menu.addAction(t("srv.rename")).triggered.connect(lambda _c=False: self._server_rename(view, idx))
            act = menu.addAction(t("srv.delete"))
            act.setEnabled(not view.model().itemFromIndex(idx).hasChildren())
            act.triggered.connect(lambda _c=False: self._server_delete(view, idx))
        self._sidebar_switch_actions(menu, side, MODE_SERVERS)
        menu.exec(view.viewport().mapToGlobal(pos))

    def _node_at(self, model, idx) -> tuple[sv.Node, sv.Node] | None:
        """(Elternordner, Knoten) im Speicher für einen Eintrag der Seitenleiste."""
        node, parent = self.server_store.root, None
        for r in model.node_path(idx):
            if r >= len(node.children):
                return None
            parent, node = node, node.children[r]
        return (parent, node) if parent is not None else None

    def _folder_at(self, path: list[int]) -> sv.Node:
        node = self.server_store.root
        for r in path:
            if r < len(node.children) and node.children[r].is_folder:
                node = node.children[r]
        return node

    def _disconnect_server(self, sid: str) -> None:
        for side, s in list(self.remote_sessions.items()):
            if s.cfg.id == sid:
                self.remote_disconnect(side)

    def _server_copy(self, sid: str) -> None:
        cfg = self.server_store.duplicate(sid)
        if cfg is None:
            return
        old = self.server_store.by_id(sid)
        kind = "passphrase" if old.logon == rf.LOGON_KEY else "password"
        secret = sv.load_secret(sid, kind)
        if secret:
            sv.store_secret(cfg.id, secret, cfg.name, kind)
        self.server_store.save()
        self._refresh_server_views()

    def _server_rename(self, view, idx) -> None:
        from .dialogs import ask_text

        hit = self._node_at(view.model(), idx)
        if hit is None:
            return
        node = hit[1]
        name = ask_text(self, t("srv.rename"), t("srv.new_name"), node.name)
        if not name or not name.strip():
            return
        node.name = name.strip()
        if node.server is not None:
            node.server.name = node.name
        self.server_store.save()
        self._refresh_server_views()

    def _server_delete(self, view, idx) -> None:
        hit = self._node_at(view.model(), idx)
        if hit is None:
            return
        parent, node = hit
        if node.is_folder and node.children:
            return
        if not confirm(self, t("srv.delete"), t("srv.delete_confirm", name=node.name), yes_key="button.delete",
                       default_yes=False):
            return
        if node.server is not None:
            self._disconnect_server(node.server.id)
            sv.delete_secret(node.server.id)
        parent.children.remove(node)
        self.server_store.save()
        self._refresh_server_views()

    def _server_new_folder(self, path: list[int]) -> None:
        from .dialogs import ask_text

        name = ask_text(self, t("srv.new_folder"), t("srv.folder_name"), t("srv.new_folder_name"))
        if not name or not name.strip():
            return
        self._folder_at(path).children.append(sv.Node(name.strip()))
        self.server_store.save()
        self._refresh_server_views()

    def do_server_manager(self, select_id: str | None = None, new_in_folder: list[int] | None = None) -> None:
        from .serverui import ServerManagerDialog

        dlg = ServerManagerDialog(self, self.server_store, self.icons.folder(), select_id, new_in_folder)
        result = dlg.exec()
        if result == QDialog.DialogCode.Rejected:
            return
        # Geänderte Server: bestehende Sitzungen behalten ihre Einstellungen bis zum Neuverbinden
        self._refresh_server_views()
        if result == ServerManagerDialog.CONNECT and dlg.chosen:
            self.remote_connect(self.active_side, dlg.chosen)

    # --- Einstellungen: FileZilla-Import (L-350) -------------------------------------------------------------
    def import_filezilla(self, parent=None) -> None:
        from .serverui import ImportDialog

        parent = parent or self
        path = sv.filezilla_file()
        if not os.path.isfile(path):
            show_info(parent, t("srv.import_title"), t("srv.import_missing", path=path))
            return
        try:
            items = sv.parse_filezilla(path)
        except (OSError, ValueError) as exc:
            show_error(parent, t("srv.import_title"), t("srv.import_failed", reason=str(exc)))
            return
        if not items:
            show_info(parent, t("srv.import_title"), t("srv.import_empty"))
            return
        dlg = ImportDialog(parent, items, self.icons.folder())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        added, skipped, no_keyring = sv.import_servers(self.server_store, dlg.selected())
        self._refresh_server_views()
        text = t("srv.import_done", n=added)
        if skipped:
            text += "\n" + t("srv.import_skipped", n=skipped)
        if no_keyring:
            text += "\n" + t("srv.import_no_keyring_count", n=no_keyring)
        show_info(parent, t("srv.import_title"), text)

    # --- Arbeiten auf dem Server ----------------------------------------------------------------------------
    def _session_of(self, panel) -> RemoteSession | None:
        return panel.remote if panel.in_remote else None

    def remote_new_folder(self, panel, name: str) -> None:
        session = self._session_of(panel)
        path = posixpath.join(session.path_of(panel.current_path), name)
        _v, err = session.call(lambda c: c.mkdir(path))
        if err is None:
            panel.refresh()
            panel.select_names([name], current=name)
            panel.view.setFocus()

    def remote_delete(self, panel, entries) -> None:
        session = self._session_of(panel)
        what = t("dialog.one_item", name=entries[0].name) if len(entries) == 1 else t("dialog.n_items", n=len(entries))
        if not confirm(self, t("title.delete"), t("srv.delete_files_confirm", what=what),
                       yes_key="button.delete", default_yes=False, warning=True):
            return
        self._remember_cursor_after_delete(entries)
        flag = [False]
        items = [(session.path_of(e.path), e.is_dir and not e.is_link) for e in entries]

        def work(conn) -> None:
            for path, is_dir in items:
                if flag[0]:
                    raise rf.Cancelled()
                if is_dir:
                    conn.remove_tree(path, lambda: flag[0])
                else:
                    conn.remove(path)
        value, error, cancelled = run_task(self, lambda: work(session.conn), t("srv.deleting"), flag)
        if error is not None and not isinstance(error, rf.Cancelled):
            show_error(self, t("title.delete"), describe_error(error))
        panel.refresh()
        name = panel.property("cursor_after_delete")
        if name:
            panel.select_names([], current=name)

    def remote_properties(self, panel) -> None:
        from datetime import datetime

        from .util import format_size

        entries = panel.target_entries()
        if not entries:
            show_info(self, t("srv.properties"), t("srv.properties_folder", uri=panel.current_path))
            return
        lines = []
        for e in entries[:20]:
            when = datetime.fromtimestamp(e.mtime).strftime("%d.%m.%Y %H:%M") if e.mtime else "–"
            size = t("type.folder") if e.is_dir else format_size(e.size)
            lines.append(t("srv.properties_line", name=e.name, size=size, date=when))
        if len(entries) > 20:
            lines.append("…")
        lines.append("")
        lines.append(panel.current_path)
        show_info(self, t("srv.properties"), "\n".join(lines))

    def remote_open(self, panel, entry) -> None:
        """Doppelklick: in einen temporären Ordner laden und mit dem Standardprogramm öffnen (L-342)."""
        import tempfile

        from .util import open_with_default_app

        session = self._session_of(panel)
        if session is None:
            return
        folder = tempfile.mkdtemp(prefix="PanePilot-")
        target = os.path.join(folder, entry.name)
        path = session.path_of(entry.path)
        flag = [False]

        def work(conn) -> None:
            with open(target, "wb") as fh:
                conn.download(path, fh, cancel=lambda: flag[0])
        value, error, cancelled = run_task(self, lambda: work(session.conn), t("srv.opening", name=entry.name), flag)
        if cancelled or error is not None:
            try:
                os.remove(target)
            except OSError:
                pass
            if error is not None and not isinstance(error, rf.Cancelled):
                show_error(self, t("title.open"), describe_error(error))
                if isinstance(error, rf.ConnectionLost):
                    session.reconnect()
            elif cancelled:
                session.reconnect()  # FTP: Verbindung nach Abbruch nicht mehr sauber
            return
        if not open_with_default_app(target):
            show_error(self, t("title.open"), t("error.open_failed", path=target))

    # --- Übertragungen ------------------------------------------------------------------------------------------
    def remote_transfer(self, move: bool, ask: bool = True) -> bool:
        """F5/F6 mit einem Server-Fenster. True, wenn erledigt (oder abgelehnt)."""
        src, dst = self.active, self.other
        if not src.in_remote and not dst.in_remote:
            return False
        entries = src.target_entries()
        if not entries:
            return True
        if src.in_remote and dst.in_remote:
            show_info(self, t("srv.title"), t("srv.no_server_to_server"))
            return True
        if dst.in_trash or dst.search_mode or src.search_mode:
            show_info(self, t("srv.title"), t("srv.transfer_target_invalid"))
            return True
        target = dst.current_path
        if ask and self.settings.get("confirm_copy_move"):
            from .dialogs import CopyMoveDialog

            dlg = CopyMoveDialog(self, move, [e.name for e in entries], target)
            if dlg.exec() != dlg.DialogCode.Accepted:
                return True
            target = dlg.target()
        if src.in_remote:
            if not os.path.isdir(target):
                show_error(self, t("title.copy"), t("error.target_missing", path=target))
                return True
            self.start_download(src.remote, [(e.path, e.is_dir) for e in entries], target, move)
        else:
            session = dst.remote
            if not (target == session.base or target.startswith(session.base + "/")):
                show_error(self, t("title.copy"), t("error.target_missing", path=target))
                return True
            self.start_upload(session, [(e.path, e.is_dir) for e in entries], target, move)
        return True

    def start_download(self, session: RemoteSession, items: list[tuple[str, bool]], target: str, move: bool) -> None:
        from .transfers import DOWN, Job

        sources = [(session.path_of(p), d) for p, d in items]
        self.transfers.add(Job(session.cfg, session.password, session.passphrase, DOWN, sources, target, move))

    def start_upload(self, session: RemoteSession, items: list[tuple[str, bool]], target_uri: str, move: bool) -> None:
        from .transfers import UP, Job

        self.transfers.add(Job(session.cfg, session.password, session.passphrase, UP, items,
                               session.path_of(target_uri), move))

    def remote_drop(self, paths: list[str], target_uri: str, action) -> None:
        """Lokale Dateien auf ein Server-Fenster gezogen → hochladen."""
        session = next((s for s in self.remote_sessions.values()
                        if target_uri == s.base or target_uri.startswith(s.base + "/")), None)
        if session is None:
            return
        move = action == Qt.DropAction.MoveAction
        self.start_upload(session, [(p, os.path.isdir(p) and not os.path.islink(p)) for p in paths], target_uri, move)

    def remote_drop_from_server(self, payload: dict, target: str, action) -> None:
        """Aus einem Server-Fenster gezogen → herunterladen (oder ablehnen)."""
        session = self.remote_sessions.get(payload.get("side", ""))
        if session is None:
            return
        if rf.is_remote_uri(target):
            show_info(self, t("srv.title"), t("srv.no_server_to_server"))
            return
        if not os.path.isdir(target):
            return
        move = action == Qt.DropAction.MoveAction
        dirs = payload.get("dirs") or [False] * len(payload["paths"])
        self.start_download(session, list(zip(payload["paths"], dirs)), target, move)

    def remote_file_menu(self, side: str, pos) -> None:
        """Kontextmenü im Server-Fenster."""
        a = self.qactions
        menu = QMenu(self)
        panel = self.sides[side].panel
        entries = panel.target_entries()
        menu.addAction(a["open"])
        menu.addSeparator()
        if entries:
            for aid in ("copy", "move"):
                menu.addAction(a[aid])
            menu.addSeparator()
            menu.addAction(a["rename"])
            menu.addAction(t("srv.delete_files")).triggered.connect(lambda _c=False: self.trigger("delete_permanent"))
            menu.addSeparator()
        menu.addAction(a["new_folder"])
        menu.addAction(a["refresh"])
        menu.addSeparator()
        menu.addAction(a["properties"])
        menu.addSeparator()
        menu.addAction(t("srv.disconnect")).triggered.connect(lambda _c=False: self.remote_disconnect(side))
        menu.exec(pos)

    def transfers_busy(self) -> bool:
        return self._transfers is not None and self._transfers.busy()

    def shutdown_remote(self) -> None:
        if self._transfers is not None:
            self._transfers.shutdown()
        self.remote_disconnect_all()


def _later(fn) -> None:
    QTimer.singleShot(0, fn)
