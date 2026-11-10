"""Spenden und Spender-Code (v0.9.11).

PanePilot ist kostenlos. Nach 30 Tagen erscheint einmal täglich beim ersten Start ein Hinweis
mit der Bitte um Unterstützung über Ko-fi. Wer gespendet hat, bekommt vom Maintainer einen
persönlichen Code, der an seinen Namen gebunden ist. Damit verschwindet der Hinweis, und im
Über-Fenster steht „Registriert für <Name>“.

Der Code ist eine Ed25519-Signatur des Namens. Erzeugen kann ihn nur, wer den geheimen
Schlüssel hat (nicht im Repository). PanePilot prüft ihn ohne Internet mit dem öffentlichen
Schlüssel unten. Weil der Quellcode offen ist, ist das kein Kopierschutz, sondern eine Bitte.
"""

from __future__ import annotations

import base64
import datetime as dt
import re
import unicodedata

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout)

from . import ed25519
from .i18n import t

PROJECT_URL = "https://github.com/NEA1971/PanePilot"
ISSUES_URL = PROJECT_URL + "/issues"
HELP_ONLINE_URL = PROJECT_URL + "/tree/main/src/panepilot/help"
KOFI_URL = "https://ko-fi.com/panepilot"
PUBLIC_KEY = bytes.fromhex("9cdf3fccffb4787a61d3768bf6b46126d964e878498bb008b519f5ea4171213c")
NAG_AFTER_DAYS = 30
CODE_PREFIX = "PP1"
_DOMAIN = b"PanePilot-Spender-v1:"


# --- Code ------------------------------------------------------------------------------------------
def normalize_name(name: str) -> str:
    """Leerzeichen zusammenfassen, Unicode vereinheitlichen; Groß-/Kleinschreibung egal."""
    return " ".join(unicodedata.normalize("NFC", name or "").split())


def _message(name: str) -> bytes:
    return _DOMAIN + normalize_name(name).casefold().encode("utf-8")


def format_code(signature: bytes) -> str:
    raw = base64.b32encode(signature).decode("ascii").rstrip("=")
    return CODE_PREFIX + "-" + "-".join(raw[i:i + 8] for i in range(0, len(raw), 8))


def parse_code(code: str) -> bytes | None:
    text = re.sub(r"[\s\-]", "", code or "").upper()
    if text.startswith(CODE_PREFIX):
        text = text[len(CODE_PREFIX):]
    if not text:
        return None
    try:
        sig = base64.b32decode(text + "=" * (-len(text) % 8))
    except (ValueError, base64.binascii.Error):
        return None
    return sig if len(sig) == 64 else None


def make_code(secret: bytes, name: str) -> str:
    """Für das Code-Werkzeug und die Tests."""
    return format_code(ed25519.sign(secret, _message(name)))


def verify_code(name: str, code: str, public: bytes | None = None) -> bool:
    if not normalize_name(name):
        return False
    sig = parse_code(code)
    return sig is not None and ed25519.verify(public or PUBLIC_KEY, _message(name), sig)


# --- Zustand in den Einstellungen ----------------------------------------------------------------------
def registered_name(settings) -> str | None:
    name, code = settings.get("donor_name") or "", settings.get("donor_code") or ""
    return normalize_name(name) if name and verify_code(name, code) else None


def ensure_first_start(settings, today: dt.date | None = None) -> None:
    if not settings.get("first_start"):
        settings.set("first_start", (today or dt.date.today()).isoformat())


def should_nag(settings, today: dt.date | None = None) -> bool:
    """Hinweis nach 30 Tagen einmal täglich (erster Start des Tages), nie für Spender."""
    today = today or dt.date.today()
    if registered_name(settings):
        return False
    try:
        first = dt.date.fromisoformat(settings.get("first_start") or "")
    except ValueError:
        return False
    if (today - first).days < NAG_AFTER_DAYS:
        return False
    return settings.get("donate_last_shown") != today.isoformat()


# --- Fenster --------------------------------------------------------------------------------------
class DonorCodeDialog(QDialog):
    def __init__(self, parent, settings) -> None:
        super().__init__(parent)
        from .dialogs import free_window

        free_window(self)
        self.settings = settings
        self.setWindowTitle(t("donate.code_title"))
        self.setMinimumWidth(560)
        self.name_edit = QLineEdit(settings.get("donor_name") or "", self)
        self.code_edit = QLineEdit(settings.get("donor_code") or "", self)
        self.code_edit.setPlaceholderText("PP1-…")
        self.error = QLabel(self)
        self.error.setStyleSheet("color: #D32F2F;")
        self.error.setWordWrap(True)
        hint = QLabel(t("donate.code_hint"), self)
        hint.setWordWrap(True)
        form = QFormLayout()
        form.addRow(t("donate.code_name"), self.name_edit)
        form.addRow(t("donate.code_code"), self.code_edit)
        box = QDialogButtonBox(self)
        box.addButton(t("button.ok"), QDialogButtonBox.ButtonRole.AcceptRole).setDefault(True)
        box.addButton(t("button.cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(self.error)
        layout.addWidget(box)

    def accept(self) -> None:
        name, code = normalize_name(self.name_edit.text()), self.code_edit.text().strip()
        if not verify_code(name, code):
            self.error.setText(t("donate.code_wrong"))
            return
        self.settings.set("donor_name", name)
        self.settings.set("donor_code", code)
        super().accept()


class DonateDialog(QDialog):
    """Bitte um Unterstützung (beim Start und über Hilfe ▸ PanePilot unterstützen)."""

    def __init__(self, parent, settings) -> None:
        super().__init__(parent)
        from .dialogs import free_window

        free_window(self)
        self.settings = settings
        self.setWindowTitle(t("donate.title"))
        self.setMinimumWidth(520)
        text = QLabel(t("donate.text", url=KOFI_URL), self)
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)
        text.setOpenExternalLinks(False)
        text.linkActivated.connect(lambda _url: self.support())
        self.btn_support = QPushButton(t("donate.support"), self)
        self.btn_support.setDefault(True)
        self.btn_code = QPushButton(t("donate.have_code"), self)
        self.btn_later = QPushButton(t("donate.later"), self)
        self.btn_support.clicked.connect(self.support)
        self.btn_code.clicked.connect(self.enter_code)
        self.btn_later.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_support)
        buttons.addWidget(self.btn_code)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_later)
        layout = QVBoxLayout(self)
        layout.addWidget(text)
        layout.addSpacing(8)
        layout.addLayout(buttons)

    def support(self) -> None:
        from . import util

        util.open_url(KOFI_URL)
        self.accept()

    def enter_code(self) -> None:
        if DonorCodeDialog(self, self.settings).exec() == QDialog.DialogCode.Accepted:
            from .dialogs import show_info

            show_info(self, t("donate.code_title"), t("donate.thanks", name=registered_name(self.settings) or ""))
            self.accept()
