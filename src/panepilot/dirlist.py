"""Verzeichnisliste als Textdatei (v1.1).

Eingerückte Liste eines Ordners mit Größe und Änderungsdatum. Ordner stehen vor Dateien und zeigen
die Gesamtgröße ihres Inhalts (auch unterhalb der gewählten Tiefe). Die Spalten für Größe und Datum
werden an den längsten Eintrag angepasst, damit die Liste in jeder Tiefe ausgerichtet bleibt.
"""

from __future__ import annotations

import datetime as dt
import os
import stat
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal

INDENT = "    "


@dataclass
class Node:
    name: str
    is_dir: bool
    size: int | None  # None = kein Zugriff
    mtime: float | None
    level: int
    children: list["Node"] = field(default_factory=list)


class Cancelled(Exception):
    pass


def _visible(name: str, hidden: bool) -> bool:
    return hidden or not name.startswith(".")


def scan(root: str, files: bool = True, depth: int = 0, hidden: bool = False, cancel=lambda: False,
         progress=lambda n: None) -> Node:
    """Liest den Ordner ein. depth 0 = unbegrenzt, 1 = nur der Inhalt des Ordners selbst."""
    counter = [0]

    def walk(path: str, name: str, level: int) -> Node:
        if cancel():
            raise Cancelled()
        try:
            st = os.stat(path, follow_symlinks=False)
        except OSError:
            return Node(name, True, None, None, level)
        node = Node(name, True, 0, st.st_mtime, level)
        try:
            with os.scandir(path) as it:
                entries = sorted(it, key=lambda e: e.name.casefold())
        except OSError:
            node.size = None
            return node
        show = depth == 0 or level < depth
        dirs, plain = [], []
        for e in entries:
            if not _visible(e.name, hidden):
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
                est = e.stat(follow_symlinks=False)
            except OSError:
                if show and files:
                    plain.append(Node(e.name, False, None, None, level + 1))
                continue
            if is_dir:
                child = walk(e.path, e.name, level + 1)
                if child.size is not None:
                    node.size += child.size
                if show:
                    dirs.append(child)
            else:
                size = est.st_size if stat.S_ISREG(est.st_mode) else 0
                node.size += size
                counter[0] += 1
                if counter[0] % 500 == 0:
                    progress(counter[0])
                if show and files:
                    plain.append(Node(e.name, False, size, est.st_mtime, level + 1))
        node.children = dirs + plain
        return node

    root = os.path.abspath(root)
    return walk(root, os.path.basename(root.rstrip(os.sep)) or root, 0)


def render(tree: Node, size_text, date_format: str, header: list[str] | None = None) -> str:
    """Text der Liste. size_text(int) formatiert Größen, date_format für strftime."""
    rows: list[tuple[str, str, str]] = []

    def add(node: Node) -> None:
        name = INDENT * node.level + node.name + ("/" if node.is_dir else "")
        size = "?" if node.size is None else size_text(node.size)
        date = "" if node.mtime is None else dt.datetime.fromtimestamp(node.mtime).strftime(date_format)
        rows.append((name, size, date))
        for child in node.children:
            add(child)

    add(tree)
    w_name = max(len(r[0]) for r in rows)
    w_size = max(len(r[1]) for r in rows)
    lines = list(header or [])
    for name, size, date in rows:
        lines.append(f"{name.ljust(w_name)}   {size.rjust(w_size)}   {date}".rstrip())
    return "\n".join(lines) + "\n"


def next_free_name(folder: str, stem: str, day: dt.date, ext: str = ".txt") -> str:
    """<stem>_JJJJ-MM-TTa.txt, bei Belegung b, c, …"""
    for i in range(26 * 27):
        suffix = chr(97 + i) if i < 26 else chr(96 + i // 26) + chr(97 + i % 26)
        name = f"{stem}_{day.isoformat()}{suffix}{ext}"
        if not os.path.exists(os.path.join(folder, name)):
            return name
    return f"{stem}_{day.isoformat()}{ext}"


class DirListThread(QThread):
    """Liest im Hintergrund ein (große Ordner, Netzwerkfreigaben)."""

    progress = Signal(int)
    done = Signal(object)  # Node oder None bei Abbruch
    failed = Signal(str)

    def __init__(self, root: str, files: bool, depth: int, hidden: bool, parent=None) -> None:
        super().__init__(parent)
        self.args = (root, files, depth, hidden)
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        root, files, depth, hidden = self.args
        try:
            tree = scan(root, files, depth, hidden, cancel=lambda: self._cancel, progress=self.progress.emit)
        except Cancelled:
            self.done.emit(None)
            return
        except OSError as exc:
            self.failed.emit(exc.strerror or str(exc))
            return
        self.done.emit(tree)


# --- Fenster ------------------------------------------------------------------------------------------
def options_dialog(parent, folder: str, settings):
    """Einstellungen für die Verzeichnisliste. Liefert dict oder None bei Abbruch."""
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                                   QVBoxLayout)

    from .dialogs import free_window
    from .i18n import t

    last = dict(settings.get("dirlist") or {})
    dlg = QDialog(parent)
    free_window(dlg)
    dlg.setWindowTitle(t("dirlist.title"))
    dlg.setMinimumWidth(460)
    info = QLabel(t("dirlist.folder", folder=folder), dlg)
    info.setWordWrap(True)
    files = QCheckBox(t("dirlist.files"), dlg)
    files.setChecked(bool(last.get("files", True)))
    hidden = QCheckBox(t("dirlist.hidden"), dlg)
    hidden.setChecked(bool(last.get("hidden", False)))
    open_after = QCheckBox(t("dirlist.open_after"), dlg)
    open_after.setChecked(bool(last.get("open", True)))
    depth = QComboBox(dlg)
    depth.addItem(t("dirlist.depth_all"), 0)
    for n in range(1, 11):
        depth.addItem(str(n), n)
    depth.setCurrentIndex(max(depth.findData(int(last.get("depth", 0) or 0)), 0))
    form = QFormLayout()
    form.addRow(t("dirlist.depth"), depth)
    box = QDialogButtonBox(dlg)
    box.addButton(t("dirlist.create"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
    box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
    box.accepted.connect(dlg.accept)
    box.rejected.connect(dlg.reject)
    layout = QVBoxLayout(dlg)
    layout.addWidget(info)
    layout.addLayout(form)
    for w in (files, hidden, open_after):
        layout.addWidget(w)
    layout.addWidget(box)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    result = {"files": files.isChecked(), "depth": depth.currentData(), "hidden": hidden.isChecked(),
              "open": open_after.isChecked()}
    settings.set("dirlist", result)
    return result
