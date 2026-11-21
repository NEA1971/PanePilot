"""Tests for 2.1.2: settings dialog – wheel guard and remembered size."""

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from test_mainwindow import window  # noqa: F401


def _wheel(widget, dy=-120):
    pos = QPointF(widget.rect().center())
    ev = QWheelEvent(pos, QPointF(widget.mapToGlobal(pos.toPoint())), QPoint(0, 0), QPoint(0, dy),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)


def test_wheel_does_not_change_unfocused_slider(window):  # noqa: F811
    from panepilot.settingsdialog import SettingsDialog

    dlg = SettingsDialog(window)
    dlg.show()
    QApplication.processEvents()
    slider = dlg.scale_slider
    before = slider.value()
    _wheel(slider)
    assert slider.value() == before and dlg.scale_value() == 100
    combo = dlg.unit_box
    idx = combo.currentIndex()
    _wheel(combo)
    assert combo.currentIndex() == idx
    slider.setFocus()
    QApplication.processEvents()
    if slider.hasFocus():  # offscreen: Fokus nur bei aktivem Fenster
        _wheel(slider)
        assert slider.value() != before
    dlg.reject()


def test_settings_size_remembered(window, monkeypatch):  # noqa: F811
    from panepilot.settingsdialog import SettingsDialog

    monkeypatch.setattr(window, "screen", lambda: None)  # offscreen-Bildschirm ist zu klein

    window.settings.set("settings_size", None)
    dlg = SettingsDialog(window)
    assert (dlg.width(), dlg.height()) == SettingsDialog.DEFAULT_SIZE
    dlg.resize(1050, 700)
    dlg.reject()
    assert window.settings.get("settings_size") == [1050, 700]
    dlg = SettingsDialog(window)
    assert (dlg.width(), dlg.height()) == (1050, 700)
    dlg.reject()
    window.settings.set("settings_size", "quatsch")
    assert SettingsDialog(window).width() == 990
