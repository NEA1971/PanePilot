"""Ordnergrößen im Hintergrund berechnen (v2.7, L-3720 ff.)."""

from __future__ import annotations

import os
import stat

from PySide6.QtCore import QThread, Signal


def folder_size(path: str, stop=lambda: False) -> int | None:
    """Summe aller Dateigrößen unter path (symbolische Links nicht verfolgt); None bei Abbruch."""
    total = 0
    stack = [path]
    while stack:
        if stop():
            return None
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        stack.append(entry.path)
                    else:
                        total += st.st_size
        except OSError:
            continue
    return total


class DirSizeThread(QThread):
    """Berechnet die Ordner nacheinander und meldet jeden sofort (result: Pfad, Bytes)."""

    result = Signal(str, object)

    def __init__(self, paths: list[str], parent=None) -> None:
        super().__init__(parent)
        self.paths = list(paths)
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        for path in self.paths:
            if self._stop:
                return
            size = folder_size(path, lambda: self._stop)
            if size is None:
                return
            self.result.emit(path, size)
