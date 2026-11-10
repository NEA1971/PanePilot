import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Jeder Test bekommt eigene Konfigurations- und Papierkorb-Ordner."""
    cfg = tmp_path / "config"
    monkeypatch.setenv("PANEPILOT_CONFIG_DIR", str(cfg))
    (tmp_path / "data").mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    # Keine echten Laufwerke des Testrechners verwenden
    (tmp_path / "fstab").write_text("")
    (tmp_path / "mounts").write_text("")
    monkeypatch.setenv("PANEPILOT_FSTAB", str(tmp_path / "fstab"))
    monkeypatch.setenv("PANEPILOT_MOUNTS", str(tmp_path / "mounts"))
    from panepilot import i18n

    # Tests laufen auf Deutsch, unabhängig von der Sprache des Testrechners
    monkeypatch.setattr(i18n, "system_language", lambda: "de")
    i18n.load_language("de")
    return cfg


@pytest.fixture
def tree(tmp_path):
    """Kleiner Beispiel-Dateibaum."""
    base = tmp_path / "files"
    (base / "a" / "sub").mkdir(parents=True)
    (base / "b").mkdir()
    (base / "a" / "eins.txt").write_text("eins")
    (base / "a" / "sub" / "tief.txt").write_text("tief" * 100)
    (base / "a" / ".versteckt").write_text("x")
    (base / "b" / "zwei.txt").write_text("zwei")
    return base


@pytest.fixture(autouse=True)
def no_unexpected_dialogs(monkeypatch):
    """Ein unerwarteter modaler Dialog würde den Testlauf blockieren – stattdessen Fehler."""
    from PySide6.QtWidgets import QDialog, QMessageBox

    def fail(self, *args):
        raise AssertionError(f"Unerwarteter Dialog: {type(self).__name__} – {self.windowTitle()}")

    monkeypatch.setattr(QDialog, "exec", fail)
    monkeypatch.setattr(QMessageBox, "exec", fail)
