"""Tests for 1.18.3: meta wizard row menu starts with “Open” and “Open with”."""

import os
import shutil

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import QApplication

from test_mainwindow import window  # noqa: F401
from test_v093 import _open
from test_v1130 import VIDEO


def test_meta_menu_open(window, tmp_path, qtbot, monkeypatch):  # noqa: F811
    from panepilot import util

    folder = tmp_path / "F"
    folder.mkdir()
    shutil.copy(os.path.join(VIDEO, "clip.mp4"), folder / "clip.mp4")
    pane = _open(window, qtbot, folder)
    pane.meta_view.select_items(list(pane.meta_model.items))
    opened = []
    monkeypatch.setattr(util, "open_with_default_app", lambda p: opened.append(p) or True)
    seen = []

    def grab():
        menu = QApplication.activePopupWidget()
        if menu:
            acts = menu.actions()
            seen.append([a.text() if not a.isSeparator() else "---" for a in acts])
            acts[0].trigger()
            menu.close()

    QTimer.singleShot(100, grab)
    window._meta_row_menu(QPoint(10, 10))
    assert seen and seen[0][0] == "Öffnen" and seen[0][1] == "Öffnen mit" and seen[0][2] == "---"
    assert opened == [str(folder / "clip.mp4")]
    window.meta_close()
