"""Tests für v0.9.11: Spender-Code, Spenden-Hinweis, Über-Fenster, Hilfe."""

import datetime as dt

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from test_mainwindow import window  # noqa: F401

SECRET = bytes(range(32))  # Test-Schlüssel – der echte liegt nur beim Maintainer


@pytest.fixture
def test_key(monkeypatch):
    from panepilot import donation, ed25519

    monkeypatch.setattr(donation, "PUBLIC_KEY", ed25519.public_key(SECRET))
    return donation


# --- Ed25519 / Code (K-100 ff.) ---------------------------------------------------------------------
def test_ed25519_rfc8032_vector():
    from panepilot import ed25519

    # RFC 8032, Abschnitt 7.1, Test 1
    secret = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    assert ed25519.public_key(secret).hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    sig = ed25519.sign(secret, b"")
    assert sig.hex().startswith("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155")
    assert ed25519.verify(ed25519.public_key(secret), b"", sig)
    assert not ed25519.verify(ed25519.public_key(secret), b"x", sig)


def test_code_bound_to_name(test_key):
    d = test_key
    code = d.make_code(SECRET, "Max Mustermann")
    assert code.startswith("PP1-")
    assert d.verify_code("Max Mustermann", code)
    assert d.verify_code("  max   MUSTERMANN ", code)  # Groß/klein und Leerzeichen egal
    assert d.verify_code("Max Mustermann", code.lower().replace("-", " "))  # Eingabe tolerant
    assert not d.verify_code("Max Musterfrau", code)
    assert not d.verify_code("", code)
    assert not d.verify_code("Max Mustermann", code[:-3])
    # Echter öffentlicher Schlüssel: Test-Codes gelten dort nicht
    assert not d.verify_code("Max Mustermann", code, public=bytes.fromhex(
        "9cdf3fccffb4787a61d3768bf6b46126d964e878498bb008b519f5ea4171213c"))


def test_nag_schedule(window, test_key):  # noqa: F811
    d = test_key
    s = window.settings
    day0 = dt.date(2026, 11, 10)
    d.ensure_first_start(s, day0)
    assert s.get("first_start") == "2026-11-10"
    assert not d.should_nag(s, day0 + dt.timedelta(days=29))  # erste 30 Tage nicht
    assert d.should_nag(s, day0 + dt.timedelta(days=30))
    s.set("donate_last_shown", (day0 + dt.timedelta(days=30)).isoformat())
    assert not d.should_nag(s, day0 + dt.timedelta(days=30))  # einmal am Tag
    assert d.should_nag(s, day0 + dt.timedelta(days=31))  # danach täglich
    s.set("donor_name", "Max Mustermann")
    s.set("donor_code", d.make_code(SECRET, "Max Mustermann"))
    assert d.registered_name(s) == "Max Mustermann"
    assert not d.should_nag(s, day0 + dt.timedelta(days=40))  # Spender: nie


def test_startup_nag_once_per_day(window, test_key, monkeypatch):  # noqa: F811
    d = test_key
    shown = []
    monkeypatch.setattr(d.DonateDialog, "exec", lambda dlg: shown.append(1) or QDialog.DialogCode.Rejected)
    window.settings.set("first_start", (dt.date.today() - dt.timedelta(days=45)).isoformat())
    window.maybe_ask_for_donation()
    window.maybe_ask_for_donation()
    assert shown == [1]
    window.settings.set("first_start", "")
    window.settings.set("donate_last_shown", "")
    window.maybe_ask_for_donation()  # erster Start: nur Datum merken
    assert shown == [1] and window.settings.get("first_start") == dt.date.today().isoformat()


def test_code_dialog_and_about(window, test_key, monkeypatch):  # noqa: F811
    d = test_key
    from panepilot.about import AboutDialog

    opened = []
    monkeypatch.setattr("panepilot.util.open_url", lambda url: opened.append(url) or True)
    dlg = d.DonorCodeDialog(window, window.settings)
    dlg.name_edit.setText("Erika Musterfrau")
    dlg.code_edit.setText("PP1-FALSCH")
    dlg.accept()
    assert dlg.error.text() and window.settings.get("donor_code") == ""
    dlg.code_edit.setText(d.make_code(SECRET, "Erika Musterfrau"))
    dlg.accept()
    assert dlg.result() == QDialog.DialogCode.Accepted
    about = AboutDialog(window, "/tmp/x")
    assert "Erika Musterfrau" in about.donor_label.text()
    assert not about.btn_code.isVisibleTo(about)
    assert [about.tabs.tabText(i) for i in range(3)] == ["Über", "Danksagungen", "System"]
    about.btn_support.click()
    assert opened == [d.KOFI_URL]
    about.copy_system_info()
    text = QApplication.clipboard().text()
    assert text.startswith("PanePilot ") and "PySide6" in text and "/tmp/x" in text


def test_donate_dialog_support_button(window, monkeypatch):  # noqa: F811
    from panepilot import donation

    opened = []
    monkeypatch.setattr("panepilot.util.open_url", lambda url: opened.append(url) or True)
    dlg = donation.DonateDialog(window, window.settings)
    dlg.btn_support.click()
    assert opened == ["https://ko-fi.com/panepilot"]


# --- Hilfe (K-140 ff.) ---------------------------------------------------------------------------------
def test_help_pages_exist_for_all_topics():
    from panepilot.helpdialog import HELP_LANGUAGES, TOPICS, topic_markdown

    for lang in HELP_LANGUAGES:
        for topic in TOPICS:
            if topic != "shortcuts":
                assert topic_markdown(topic, lang).startswith("# "), (lang, topic)


def test_help_dialog_and_f1_context(window, qtbot):  # noqa: F811
    from panepilot.actions import FKEY_DEFAULTS

    assert FKEY_DEFAULTS["F1"] == "help"
    assert window.help_topic() == "basics"
    window.trigger("help")
    dlg = window._help_dialog
    qtbot.addWidget(dlg)
    assert dlg.topic == "basics" and "Bedienung" in dlg.view.toPlainText()
    dlg.show_topic("shortcuts")
    text = dlg.view.toPlainText()
    assert "Tastenkürzel" in text and "Strg+F" in text.replace("Ctrl+F", "Strg+F")
    # Link auf eine andere Seite
    from PySide6.QtCore import QUrl

    dlg._link(QUrl("rename.md"))
    assert dlg.topic == "rename"
    window.trigger("checksums")
    assert window.help_topic() == "checksums"
    dlg.close()


def test_help_menu_entries(window):  # noqa: F811
    help_menu = window.qactions["about"].associatedObjects()
    entries = []
    for obj in help_menu:
        if hasattr(obj, "title") and obj.title() == "&Hilfe":
            entries = [a.text() for a in obj.actions() if not a.isSeparator()]
    assert entries == ["Hilfe …", "Online-Hilfe (GitHub)", "Nach Updates suchen …", "☕ PanePilot unterstützen …", "Über PanePilot"]
