"""Dialog „Ordner synchronisieren …“ (v1.16, L-1610 ff.)."""

from __future__ import annotations

import os
import threading
from datetime import datetime

from PySide6.QtCore import QEventLoop, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QLineEdit, QMenu, QProgressDialog, QPushButton, QRadioButton, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from . import folderdiff as fd
from . import syncprofiles as sp
from . import util
from .dialogs import confirm, free_window, show_error, show_info
from .i18n import t

ROLE = Qt.ItemDataRole.UserRole + 1
COL_FILE, COL_LEFT, COL_ACTION, COL_RIGHT = range(4)
STATUS_KEYS = {fd.SAME: "sync.status_same", fd.LEFT_ONLY: "sync.status_left_only",
               fd.RIGHT_ONLY: "sync.status_right_only", fd.LEFT_NEWER: "sync.status_left_newer",
               fd.RIGHT_NEWER: "sync.status_right_newer", fd.CONFLICT: "sync.status_conflict"}
ACTIONS = (fd.TO_RIGHT, fd.TO_LEFT, fd.DEL_RIGHT, fd.DEL_LEFT, fd.NONE)


def side_text(side: fd.Side | None) -> str:
    if side is None:
        return "—"
    if side.is_dir:
        return t("sync.folder_files", n=side.files, size=util.format_size(side.size))
    return f"{util.format_size(side.size)} · {datetime.fromtimestamp(side.mtime).strftime('%d.%m.%Y %H:%M')}"


def action_text(e: fd.Entry) -> str:
    if e.action == fd.TO_RIGHT:
        text = t("sync.act_over_right") if fd.overwrites(e) else t("sync.act_copy_right")
    elif e.action == fd.TO_LEFT:
        text = t("sync.act_over_left") if fd.overwrites(e) else t("sync.act_copy_left")
    elif e.action == fd.DEL_RIGHT:
        text = t("sync.act_del_right")
    elif e.action == fd.DEL_LEFT:
        text = t("sync.act_del_left")
    else:
        text = t("sync.act_none")
    if e.status == fd.CONFLICT:
        text = t("sync.conflict") + " – " + text
    return text


def menu_label(action: str) -> str:
    return {fd.TO_RIGHT: t("sync.set_right"), fd.TO_LEFT: t("sync.set_left"), fd.DEL_RIGHT: t("sync.set_del_right"),
            fd.DEL_LEFT: t("sync.set_del_left"), fd.NONE: t("sync.set_none")}[action]


class SyncDialog(QDialog):
    def __init__(self, parent, left: str = "", right: str = "", profile: str | None = None) -> None:
        super().__init__(parent)
        free_window(self)
        self.window_ = parent
        self.settings = getattr(parent, "settings", None)
        self.entries: list[fd.Entry] = []
        self.scanned: tuple[str, str] | None = None
        self.setWindowTitle(t("sync.title"))
        self.resize(1080, 720)
        lay = QVBoxLayout(self)

        # gespeicherte Abgleiche (L-1621)
        row = QHBoxLayout()
        row.addWidget(QLabel(t("sync.profile"), self))
        self.cb_profile = QComboBox(self)
        self.cb_profile.setMinimumWidth(200)
        row.addWidget(self.cb_profile)
        for text, slot in ((t("sync.profile_save"), self.save_profile),
                           (t("sync.profile_rename"), self.rename_profile),
                           (t("sync.profile_delete"), self.delete_profile)):
            b = QPushButton(text, self)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addSpacing(12)
        for text, slot in ((t("ffs.import"), self.import_ffs), (t("ffs.export"), self.export_ffs),
                           (t("ffs.export_all"), self.export_all_ffs)):  # v1.17 (L-1700, L-1710 ff.)
            b = QPushButton(text, self)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        grid = QGridLayout()
        self.ed_left, self.ed_right = QLineEdit(left, self), QLineEdit(right, self)
        for r, (label, edit) in enumerate(((t("sync.left"), self.ed_left), (t("sync.right"), self.ed_right))):
            grid.addWidget(QLabel(label, self), r, 0)
            grid.addWidget(edit, r, 1)
            pick = QToolButton(self)
            pick.setText("…")
            pick.clicked.connect(lambda _c=False, e=edit: self._pick_dir(e))
            grid.addWidget(pick, r, 2)
        swap = QToolButton(self)
        swap.setText("⇅")
        swap.setToolTip(t("sync.swap"))
        swap.clicked.connect(self._swap)
        grid.addWidget(swap, 0, 3, 2, 1)
        lay.addLayout(grid)

        opts = QGroupBox(t("sync.options"), self)
        og = QGridLayout(opts)
        self.rb_lr = QRadioButton(t("sync.dir_lr"), opts)
        self.rb_rl = QRadioButton(t("sync.dir_rl"), opts)
        self.rb_both = QRadioButton(t("sync.dir_both"), opts)
        self.dir_group = QButtonGroup(self)
        for i, rb in enumerate((self.rb_lr, self.rb_rl, self.rb_both)):
            self.dir_group.addButton(rb)
            og.addWidget(rb, 0, i)
        self.chk_subdirs = QCheckBox(t("sync.subdirs"), opts)
        self.chk_mirror = QCheckBox(t("sync.mirror"), opts)
        self.chk_mirror.setToolTip(t("sync.mirror_tip"))
        self.chk_dst = QCheckBox(t("sync.dst"), opts)
        self.chk_dst.setToolTip(t("sync.dst_tip"))
        self.chk_content = QCheckBox(t("sync.content"), opts)
        self.chk_content.setToolTip(t("sync.content_tip"))
        og.addWidget(self.chk_subdirs, 1, 0)
        og.addWidget(self.chk_mirror, 1, 1, 1, 2)
        og.addWidget(self.chk_dst, 2, 0)
        og.addWidget(self.chk_content, 2, 1, 1, 2)
        self.ed_include = QLineEdit(opts)
        self.ed_include.setPlaceholderText("*")
        self.ed_exclude = QLineEdit(opts)
        self.ed_exclude.setPlaceholderText("Thumbs.db; .DS_Store; *.tmp")
        og.addWidget(QLabel(t("sync.include"), opts), 3, 0)
        og.addWidget(self.ed_include, 3, 1, 1, 2)
        og.addWidget(QLabel(t("sync.exclude"), opts), 4, 0)
        og.addWidget(self.ed_exclude, 4, 1, 1, 2)
        lay.addWidget(opts)

        row = QHBoxLayout()
        self.btn_compare = QPushButton(t("sync.compare"), self)
        self.btn_compare.clicked.connect(self.compare)
        row.addWidget(self.btn_compare)
        self.chk_same = QCheckBox(t("sync.show_same"), self)
        self.chk_same.toggled.connect(lambda _on: self.fill())
        row.addWidget(self.chk_same)
        row.addStretch(1)
        lay.addLayout(row)

        self.tree = QTreeWidget(self)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setHeaderLabels([t("sync.col_file"), t("sync.col_left"), t("sync.col_action"), t("sync.col_right")])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        head = self.tree.header()
        head.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        head.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        for col, w in ((COL_LEFT, 220), (COL_ACTION, 200), (COL_RIGHT, 220)):
            self.tree.setColumnWidth(col, w)
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()  # L-1615: Aktion für die markierten Zeilen
        row.addWidget(QLabel(t("sync.for_selected"), self))
        for action in ACTIONS:
            b = QPushButton(menu_label(action), self)
            b.clicked.connect(lambda _c=False, a=action: self.set_selected(a))
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.summary = QLabel("", self)
        lay.addWidget(self.summary)

        after = QGroupBox(t("sync.after"), self)  # L-1630 ff.
        ag = QHBoxLayout(after)
        self.cb_after = QComboBox(after)
        for kind, key in ((sp.AFTER_NONE, "sync.after_none"), (sp.AFTER_COMMAND, "sync.after_command"),
                          (sp.AFTER_SUSPEND, "sync.after_suspend"), (sp.AFTER_SHUTDOWN, "sync.after_shutdown")):
            self.cb_after.addItem(t(key), kind)
        ag.addWidget(self.cb_after)
        self.ed_command = QLineEdit(after)
        self.ed_command.setPlaceholderText(t("sync.command_placeholder"))
        self.ed_command.setToolTip(t("sync.command_tip"))
        ag.addWidget(self.ed_command, 1)
        self.btn_command = QToolButton(after)
        self.btn_command.setText("…")
        self.btn_command.clicked.connect(self._pick_command)
        ag.addWidget(self.btn_command)
        self.cb_when = QComboBox(after)
        self.cb_when.addItem(t("sync.when_ok"), sp.WHEN_OK)
        self.cb_when.addItem(t("sync.when_always"), sp.WHEN_ALWAYS)
        ag.addWidget(self.cb_when)
        self.cb_after.currentIndexChanged.connect(lambda _i: self._after_changed())
        lay.addWidget(after)

        box = QDialogButtonBox(self)
        self.btn_start = box.addButton(t("sync.start"), QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_start.clicked.connect(self.start)
        box.addButton(t("button.close"), QDialogButtonBox.ButtonRole.RejectRole)
        box.rejected.connect(self.reject)
        lay.addWidget(box)

        last = (self.settings.get("sync_last") if self.settings is not None else None) or {}
        self.set_options(fd.Options.from_dict(last.get("options")), sp.After.from_dict(last.get("after")))
        self._fill_profiles(profile)
        self.cb_profile.activated.connect(lambda _i: self._load_profile(self.cb_profile.currentData()))
        if profile:
            self._load_profile(profile)
        self._update_buttons()

    # --- Einstellungen ------------------------------------------------------------------------------------
    def options(self) -> fd.Options:
        direction = fd.RL if self.rb_rl.isChecked() else fd.BOTH if self.rb_both.isChecked() else fd.LR
        return fd.Options(direction, self.chk_subdirs.isChecked(), self.chk_dst.isChecked(),
                          self.chk_content.isChecked(), self.chk_mirror.isChecked(),
                          self.ed_include.text().strip() or "*", self.ed_exclude.text().strip())

    def after(self) -> sp.After:
        return sp.After(self.cb_after.currentData(), self.ed_command.text().strip(), self.cb_when.currentData())

    def set_options(self, o: fd.Options, a: sp.After) -> None:
        {fd.LR: self.rb_lr, fd.RL: self.rb_rl, fd.BOTH: self.rb_both}[o.direction].setChecked(True)
        self.chk_subdirs.setChecked(o.subdirs)
        self.chk_mirror.setChecked(o.mirror)
        self.chk_dst.setChecked(o.dst)
        self.chk_content.setChecked(o.content)
        self.ed_include.setText("" if o.include == "*" else o.include)
        self.ed_exclude.setText(o.exclude)
        self.cb_after.setCurrentIndex(max(self.cb_after.findData(a.kind), 0))
        self.ed_command.setText(a.command)
        self.cb_when.setCurrentIndex(max(self.cb_when.findData(a.when), 0))
        self._after_changed()

    def _remember(self) -> None:
        if self.settings is not None:
            self.settings.set("sync_last", {"options": self.options().to_dict(), "after": self.after().to_dict()})

    def _after_changed(self) -> None:
        cmd = self.cb_after.currentData() == sp.AFTER_COMMAND
        self.ed_command.setEnabled(cmd)
        self.btn_command.setEnabled(cmd)
        self.cb_when.setEnabled(self.cb_after.currentData() != sp.AFTER_NONE)

    def _pick_dir(self, edit: QLineEdit) -> None:
        path = QFileDialog.getExistingDirectory(self, t("sync.pick_folder"), edit.text() or os.path.expanduser("~"))
        if path:
            edit.setText(path)

    def _pick_command(self) -> None:
        path, _f = QFileDialog.getOpenFileName(self, t("sync.after_command"), os.path.expanduser("~"))
        if path:
            self.ed_command.setText(f'"{path}"' if " " in path else path)

    def _swap(self) -> None:
        a, b = self.ed_left.text(), self.ed_right.text()
        self.ed_left.setText(b)
        self.ed_right.setText(a)
        self.entries, self.scanned = [], None
        self.fill()

    # --- gespeicherte Abgleiche ---------------------------------------------------------------------------
    def _fill_profiles(self, current: str | None = None) -> None:
        self.cb_profile.clear()
        self.cb_profile.addItem(t("sync.profile_none"), None)
        for p in sp.load():
            self.cb_profile.addItem(p.name, p.name)
        i = self.cb_profile.findData(current) if current else 0
        self.cb_profile.setCurrentIndex(max(i, 0))

    def current_profile(self) -> str | None:
        return self.cb_profile.currentData()

    def _load_profile(self, name: str | None) -> None:
        if not name:
            return
        prof = next((p for p in sp.load() if p.name == name), None)
        if prof is None:
            return
        self.ed_left.setText(prof.left)
        self.ed_right.setText(prof.right)
        self.set_options(prof.options, prof.after)
        self.entries, self.scanned = [], None
        self.fill()

    def save_profile(self) -> None:
        name = self.current_profile() or ""
        name, ok = QInputDialog.getText(self, t("sync.profile_save"), t("sync.profile_name"), text=name)
        name = name.strip()
        if not ok or not name:
            return
        sp.put(sp.Profile(name, self.ed_left.text().strip(), self.ed_right.text().strip(), self.options(),
                          self.after()))
        self._fill_profiles(name)
        self._notify_profiles()

    def rename_profile(self) -> None:
        old = self.current_profile()
        if not old:
            return
        name, ok = QInputDialog.getText(self, t("sync.profile_rename"), t("sync.profile_name"), text=old)
        name = name.strip()
        if not ok or not name or name == old:
            return
        prof = next((p for p in sp.load() if p.name == old), None)
        if prof is None:
            return
        prof.name = name
        sp.put(prof, old_name=old)
        self._fill_profiles(name)
        self._notify_profiles()

    def delete_profile(self) -> None:
        name = self.current_profile()
        if not name or not confirm(self, t("sync.profile_delete"), t("sync.profile_delete_q", name=name)):
            return
        sp.remove(name)
        self._fill_profiles(None)
        self._notify_profiles()

    # --- FreeFileSync (v1.17) -----------------------------------------------------------------------------
    def import_ffs(self) -> None:
        from . import ffsconvert as ffs

        paths, _f = QFileDialog.getOpenFileNames(self, t("ffs.import"), os.path.expanduser("~"),
                                                 t("ffs.filter"))
        if not paths:
            return
        existing = {p.name.lower() for p in sp.load()}
        done, lines, last = [], [], None
        for path in paths:
            name = os.path.basename(path)
            try:
                profiles, notes = ffs.parse(path)
            except ValueError as exc:
                lines.append(f"✕ {name}: {exc}")
                continue
            if not profiles:
                lines.append(f"✕ {name}: {t('ffs.no_pairs')}")
                continue
            for prof in profiles:
                if prof.name.lower() in existing and not confirm(
                        self, t("ffs.import"), t("ffs.replace_q", name=prof.name)):
                    lines.append(f"– {prof.name}: {t('ffs.skipped')}")
                    continue
                sp.put(prof)
                existing.add(prof.name.lower())
                done.append(prof.name)
                last = prof.name
                lines.append(f"✓ {prof.name}")
            lines += [f"    • {n}" for n in notes]
        if last:
            self._fill_profiles(last)
            self._load_profile(last)
            self._notify_profiles()
        show_info(self, t("ffs.import"), t("ffs.import_done", n=len(done)) + "\n\n" + "\n".join(lines))

    def _profile_now(self) -> sp.Profile:
        """Der aktuell eingestellte Abgleich (auch ungespeichert)."""
        return sp.Profile(self.current_profile() or "PanePilot", self.ed_left.text().strip(),
                          self.ed_right.text().strip(), self.options(), self.after())

    def export_ffs(self) -> None:
        from . import ffsconvert as ffs

        prof = self._profile_now()
        start = os.path.join(os.path.expanduser("~"), ffs.safe_file_name(prof.name) + ".ffs_gui")
        path, _f = QFileDialog.getSaveFileName(self, t("ffs.export"), start, t("ffs.filter_gui"))
        if not path:
            return
        if not path.lower().endswith(".ffs_gui"):
            path += ".ffs_gui"
        try:
            ffs.save(prof, path)
        except OSError as exc:
            show_error(self, t("ffs.export"), str(exc))
            return
        notes = ffs.export_notes(prof)
        show_info(self, t("ffs.export"), "\n".join([t("ffs.export_done", path=path)] + [f"• {n}" for n in notes]))

    def export_all_ffs(self) -> None:
        from . import ffsconvert as ffs

        profiles = sp.load()
        if not profiles:
            show_info(self, t("ffs.export_all"), t("menu.sync_profiles_none"))
            return
        folder = QFileDialog.getExistingDirectory(self, t("ffs.export_all"), os.path.expanduser("~"))
        if not folder:
            return
        targets = [(p, os.path.join(folder, ffs.safe_file_name(p.name) + ".ffs_gui")) for p in profiles]
        clash = [os.path.basename(path) for _p, path in targets if os.path.exists(path)]
        if clash and not confirm(self, t("ffs.export_all"), t("ffs.overwrite_q", n=len(clash),
                                                               names=", ".join(clash[:5]))):
            return
        errors, notes = [], []
        for prof, path in targets:
            try:
                ffs.save(prof, path)
            except OSError as exc:
                errors.append(f"{prof.name}: {exc}")
            notes += [f"• {prof.name}: {n}" for n in ffs.export_notes(prof)]
        text = t("ffs.export_all_done", n=len(targets) - len(errors), folder=folder)
        (show_error if errors else show_info)(self, t("ffs.export_all"), "\n".join([text] + errors + notes))

    def _notify_profiles(self) -> None:
        fn = getattr(self.window_, "sync_profiles_changed", None)
        if callable(fn):
            fn()

    # --- Vergleichen --------------------------------------------------------------------------------------
    def _paths(self) -> tuple[str, str] | None:
        left, right = os.path.expanduser(self.ed_left.text().strip()), os.path.expanduser(self.ed_right.text().strip())
        for p in (left, right):
            if not p or not os.path.isdir(p):
                show_error(self, t("sync.title"), t("sync.no_folder", path=p or "–"))
                return None
        a, b = os.path.realpath(left), os.path.realpath(right)
        if a == b or util.is_inside(a, b) or util.is_inside(b, a):
            show_error(self, t("sync.title"), t("sync.nested"))
            return None
        return left, right

    def compare(self) -> bool:
        from . import netutil

        paths = self._paths()
        if paths is None:
            return False
        opts = self.options()
        self._remember()
        entries, error = netutil.run_blocking(self, lambda: fd.scan(paths[0], paths[1], opts),
                                              t("sync.comparing"), t("sync.title"))
        if error:
            show_error(self, t("sync.title"), error)
            return False
        if entries is None:
            return False
        self.entries, self.scanned = entries, paths
        self.fill()
        return True

    def visible_entries(self) -> list[fd.Entry]:
        same = self.chk_same.isChecked()
        return [e for e in self.entries if same or e.status != fd.SAME]

    def fill(self) -> None:
        self.tree.clear()
        for i, e in enumerate(self.entries):
            if e.status == fd.SAME and not self.chk_same.isChecked():
                continue
            item = QTreeWidgetItem(self.tree)
            item.setData(COL_FILE, ROLE, i)
            item.setText(COL_FILE, e.rel + ("/" if e.is_dir else ""))
            item.setToolTip(COL_FILE, t(STATUS_KEYS[e.status]))
            item.setText(COL_LEFT, side_text(e.left))
            item.setText(COL_RIGHT, side_text(e.right))
            self._show_action(item, e)
            if e.status == fd.SAME:
                for c in range(4):
                    item.setForeground(c, self.palette().placeholderText())
        self._update_buttons()

    def _show_action(self, item: QTreeWidgetItem, e: fd.Entry) -> None:
        item.setText(COL_ACTION, action_text(e))
        font = item.font(COL_ACTION)
        font.setBold(e.action != fd.NONE)
        item.setFont(COL_ACTION, font)

    def _selected_entries(self) -> list[tuple[QTreeWidgetItem, fd.Entry]]:
        return [(it, self.entries[it.data(COL_FILE, ROLE)]) for it in self.tree.selectedItems()]

    def set_selected(self, action: str) -> None:
        """L-1615: Aktion für alle markierten Zeilen; wo sie nicht passt, bleibt die alte."""
        for item, e in self._selected_entries():
            if fd.set_action([e], action):
                self._show_action(item, e)
        self._update_buttons()

    def _menu(self, pos) -> None:
        if not self.tree.selectedItems():
            return
        menu = QMenu(self)
        for action in ACTIONS:
            menu.addAction(menu_label(action)).triggered.connect(lambda _c=False, a=action: self.set_selected(a))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _update_buttons(self) -> None:
        c = fd.summary_counts(self.entries)
        n = c["to_right"] + c["to_left"] + c["delete"]
        self.btn_start.setEnabled(n > 0 and self.scanned is not None)
        if self.scanned is None:
            self.summary.setText(t("sync.hint_compare"))
        else:
            diff = sum(1 for e in self.entries if e.status != fd.SAME)
            self.summary.setText(t("sync.summary", diff=diff, right=c["to_right"], left=c["to_left"],
                                   delete=c["delete"], conflict=c["conflict"], size=util.format_size(c["bytes"])))

    # --- Starten ------------------------------------------------------------------------------------------
    def start(self) -> None:
        if self.scanned is None:
            return
        left, right = self.scanned
        c = fd.summary_counts(self.entries)
        text = t("sync.confirm", right=c["to_right"], left=c["to_left"], size=util.format_size(c["bytes"]))
        if c["delete"]:
            text += "\n\n" + t("sync.confirm_delete", n=c["delete"])
        if not confirm(self, t("sync.title"), text):
            return
        self._remember()
        result = self.run(left, right)
        self.finish(left, right, result)

    def run(self, left: str, right: str) -> fd.Result:
        from .fileops import move_to_trash

        cancel = threading.Event()
        entries, opts = self.entries, self.options()

        class Worker(QThread):
            step = Signal(float, float, str)

            def run(self):
                self.result = fd.execute(entries, left, right, opts, move_to_trash,
                                         lambda d, tot, rel: self.step.emit(float(d), float(tot), rel), cancel)

        dlg = QProgressDialog(t("sync.running"), t("button.cancel"), 0, 1000, self)
        dlg.setWindowTitle(t("sync.title"))
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(400)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        worker = Worker()
        worker.step.connect(lambda d, tot, rel: (dlg.setValue(int(1000 * d / max(tot, 1))),
                                                 dlg.setLabelText(t("sync.running_file", name=rel))))
        dlg.canceled.connect(cancel.set)
        loop = QEventLoop()
        worker.finished.connect(loop.quit)
        worker.start()
        if not worker.isFinished():
            loop.exec()
        worker.wait()
        dlg.close()
        return worker.result

    def finish(self, left: str, right: str, result: fd.Result) -> None:
        lines = [t("sync.done", copied=result.copied, over=result.overwritten, deleted=result.deleted,
                   failed=result.failed)]
        if result.cancelled:
            lines.append(t("sync.cancelled"))
        for rel, msg in result.errors[:15]:
            lines.append(f"• {rel}: {msg}")
        if len(result.errors) > 15:
            lines.append("…")
        after = self.after()
        if after.due(result) and after.kind == sp.AFTER_COMMAND:  # L-1633/L-1634
            from . import netutil

            env = sp.script_env(left, right, result, self.current_profile() or "")
            value, error = netutil.run_blocking(self, lambda: sp.run_command(after.command, env),
                                                t("sync.script_running"), t("sync.title"))
            code, out = value if value else (-1, error or "")
            if code != 0:
                lines.append("")
                lines.append(t("sync.script_failed", code=code))
                if out:
                    lines.append(out)
            else:
                lines.append(t("sync.script_ok"))
        refresh = getattr(self.window_, "do_refresh", None)
        if callable(refresh):
            refresh()
        (show_error if result.errors else show_info)(self, t("sync.title"), "\n".join(lines))
        if after.due(result) and after.kind in (sp.AFTER_SUSPEND, sp.AFTER_SHUTDOWN):  # L-1630
            if CountdownDialog(self, after.kind).exec() == QDialog.DialogCode.Accepted:
                problem = sp.power(after.kind)
                if problem:
                    show_error(self, t("sync.title"), t("sync.power_failed", reason=problem))
        self.compare()

    def reject(self) -> None:
        self._remember()
        super().reject()


class CountdownDialog(QDialog):
    """30 Sekunden bis zur Bereitschaft bzw. zum Herunterfahren, mit „Abbrechen“ (L-1630)."""

    def __init__(self, parent, kind: str, seconds: int = sp.COUNTDOWN) -> None:
        super().__init__(parent)
        self.kind, self.left = kind, seconds
        self.setWindowTitle(t("sync.title"))
        lay = QVBoxLayout(self)
        self.label = QLabel(self)
        lay.addWidget(self.label)
        box = QDialogButtonBox(self)
        box.addButton(t("sync.countdown_now"), QDialogButtonBox.ButtonRole.AcceptRole)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole).setDefault(True)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._show()

    def _show(self) -> None:
        key = "sync.countdown_suspend" if self.kind == sp.AFTER_SUSPEND else "sync.countdown_shutdown"
        self.label.setText(t(key, n=self.left))

    def _tick(self) -> None:
        self.left -= 1
        if self.left <= 0:
            self.timer.stop()
            self.accept()
        else:
            self._show()
