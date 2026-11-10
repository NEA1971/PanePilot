"""Tests für v0.9.6: ReplayGain (EBU R128 mit ffmpeg)."""

import shutil
import subprocess

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from test_mainwindow import window  # noqa: F401

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg fehlt")


def _tone(path, volume: float, seconds: float = 3, codec: list[str] | None = None):
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=1000:duration={seconds}",
           "-af", f"volume={volume}", *(codec or []), str(path)]
    subprocess.run(cmd, check=True)


# --- Rechnen ------------------------------------------------------------------------------------------------
def test_integrated_gating():
    from panepilot import replaygain as rg

    assert rg.integrated([-20.0] * 10) == pytest.approx(-20.0, abs=0.01)
    # Stille und sehr leise Blöcke fallen durch die Gates
    assert rg.integrated([-20.0] * 10 + [-120.0] * 10 + [-40.0] * 5) == pytest.approx(-20.0, abs=0.01)
    assert rg.integrated([-120.0] * 5) == float("-inf")


def test_tag_values_formats():
    from panepilot import replaygain as rg

    m = rg.Measurement(-13.66, 0.933254, [])
    v = rg.tag_values("MP3", m, -14.0, 1.09, -18.0)
    assert v == {"REPLAYGAIN_TRACK_GAIN": "-4.34 dB", "REPLAYGAIN_TRACK_PEAK": "0.933254",
                 "REPLAYGAIN_ALBUM_GAIN": "-4.00 dB", "REPLAYGAIN_ALBUM_PEAK": "1.090000"}
    assert rg.tag_values("MP3", rg.Measurement(-20.0, 0.5, []), None, None, -18.0)["REPLAYGAIN_TRACK_GAIN"] == "+2.00 dB"
    # Opus: R128 bezogen auf −23 LUFS, Q7.8
    assert rg.tag_values("Opus", rg.Measurement(-13.0, 0.9, []), None, None, -18.0) == {"R128_TRACK_GAIN": "-2560"}
    # eigene Ziel-Lautheit
    assert rg.tag_values("FLAC", m, None, None, -23.0)["REPLAYGAIN_TRACK_GAIN"] == "-9.34 dB"


# --- Messen -------------------------------------------------------------------------------------------------
@needs_ffmpeg
def test_measure_tone(tmp_path):
    from panepilot import replaygain as rg

    loud, quiet = tmp_path / "laut.flac", tmp_path / "leise.flac"
    _tone(loud, 0.5)
    _tone(quiet, 0.25)
    a, b = rg.measure(str(loud)), rg.measure(str(quiet))
    assert a.loudness - b.loudness == pytest.approx(6.02, abs=0.2)  # halbe Amplitude = 6 dB
    assert a.peak == pytest.approx(0.5 / 8, abs=0.005)  # lavfi-Sinus hat Amplitude 1/8
    album, peak = rg.album_values([a, b])
    assert b.loudness < album < a.loudness and peak == pytest.approx(a.peak)


@needs_ffmpeg
def test_measure_error(tmp_path):
    from panepilot import replaygain as rg

    bad = tmp_path / "kaputt.mp3"
    bad.write_bytes(b"keine Musik")
    with pytest.raises(ValueError):
        rg.measure(str(bad))


@needs_ffmpeg
def test_replaygain_in_meta_wizard(window, qtbot, tmp_path, monkeypatch):  # noqa: F811
    from panepilot import tags as tg
    from panepilot.metaextras import ReplayGainDialog

    base = tmp_path / "Album"
    base.mkdir()
    files = {"a.mp3": (0.5, ["-c:a", "libmp3lame"]), "b.flac": (0.1, []), "c.opus": (0.3, ["-c:a", "libopus"])}
    for name, (vol, codec) in files.items():
        _tone(base / name, vol, 3, codec)
        rec = tg.read_file(str(base / name))
        tg.write_file(rec, {"album": "Testalbum", "title": name})
    # b.flac hat schon einen (falschen) Titelwert
    rec = tg.read_file(str(base / "b.flac"))
    tg.write_file(rec, {tg.custom_key(rec.kind, "replaygain_track_gain"): "+99.00 dB"})

    window.active.navigate(str(base))
    QApplication.processEvents()
    window.trigger("meta_wizard")
    qtbot.waitUntil(lambda: window.meta_mode is not None and window.meta_mode.get("scan") is None, timeout=10000)
    pane = window._meta_pane()
    monkeypatch.setattr(ReplayGainDialog, "exec", lambda dlg: QDialog.DialogCode.Accepted)
    window.meta_convert("replaygain")
    qtbot.waitUntil(lambda: window.meta_mode.get("rg") is None, timeout=60000)
    by = {it.record.name: it for it in pane.meta_model.items}
    mp3, flac, opus = by["a.mp3"], by["b.flac"], by["c.opus"]
    assert mp3.value("x:REPLAYGAIN_TRACK_GAIN").endswith(" dB") and mp3.value("x:REPLAYGAIN_ALBUM_GAIN")
    assert flac.value("x:replaygain_track_gain") == "+99.00 dB"  # nicht überschrieben (Vorgabe)
    assert flac.value("x:REPLAYGAIN_ALBUM_GAIN")  # Albumwert ergänzt
    assert opus.value("x:R128_TRACK_GAIN").lstrip("-").isdigit() and not opus.value("x:REPLAYGAIN_TRACK_GAIN")
    g_mp3 = float(mp3.value("x:REPLAYGAIN_TRACK_GAIN").split()[0])
    window.meta_save()
    qtbot.waitUntil(lambda: window.meta_mode.get("save") is None, timeout=10000)
    saved = tg.read_file(str(base / "a.mp3"))
    assert tg.find_key(saved, "x:REPLAYGAIN_TRACK_GAIN") is not None
    assert g_mp3 > 0  # der leise Testsinus (Spitze 1/16) liegt unter −18 LUFS → wird angehoben
    window.meta_close()


def test_replaygain_disabled_without_ffmpeg(window, tmp_path, monkeypatch):  # noqa: F811
    import panepilot.replaygain as rg

    monkeypatch.setattr(rg.shutil, "which", lambda name: None)
    pane = window._make_meta_pane("left")
    assert not pane.convert_buttons["replaygain"].isEnabled()
    assert "ffmpeg" in pane.convert_buttons["replaygain"].toolTip()
    pane.deleteLater()


def test_settings_target(window):  # noqa: F811
    from panepilot.settingsdialog import SettingsDialog

    dlg = SettingsDialog(window)
    assert dlg.rg_target.value() == -18.0
    dlg.rg_target.setValue(-23.0)
    dlg.accept()
    assert window.settings.get("replaygain_target") == -23.0
