"""Kleine Hilfen für Internet-Abfragen (v1.2: Update-Suche, MusicBrainz).

PanePilot geht nur ins Internet, wenn der Nutzer es auslöst bzw. eingeschaltet hat. Übertragen
wird nur, was für die Abfrage nötig ist; als Kennung dient „PanePilot/<Version> (<Projektseite>)“.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from PySide6.QtCore import QThread, Signal

from . import __version__

PROJECT_URL = "https://github.com/NEA1971/PanePilot"
USER_AGENT = f"PanePilot/{__version__} ( {PROJECT_URL} )"
TIMEOUT = 20


class NetError(Exception):
    """Netzwerk- oder Serverfehler mit lesbarer Meldung."""


_CA_FILES = ("/etc/ssl/certs/ca-certificates.crt", "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/ca-bundle.pem",
             "/etc/ssl/cert.pem")
_context = None


def ssl_context():
    """Zertifikate des Systems verwenden – auch wenn das gebündelte Python sie an anderer Stelle sucht."""
    global _context
    if _context is None:
        import os
        import ssl

        ctx = ssl.create_default_context()
        if not ctx.get_ca_certs() and not ctx.cert_store_stats().get("x509_ca"):
            for path in _CA_FILES:
                if os.path.isfile(path):
                    try:
                        ctx.load_verify_locations(cafile=path)
                        break
                    except (OSError, ssl.SSLError):
                        continue
        _context = ctx
    return _context


def _request(url: str, accept: str | None = None) -> urllib.request.Request:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    return urllib.request.Request(url, headers=headers)


def get_bytes(url: str, accept: str | None = None, allow_404: bool = False) -> bytes | None:
    try:
        with urllib.request.urlopen(_request(url, accept), timeout=TIMEOUT, context=ssl_context()) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        if allow_404 and exc.code == 404:
            return None
        raise NetError(f"HTTP {exc.code} {exc.reason}") from exc
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise NetError(str(reason)) from exc


def get_json(url: str):
    data = get_bytes(url, "application/json")
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise NetError(f"JSON: {exc}") from exc


def download(url: str, target: str, progress=lambda done, total: None, cancel=lambda: False) -> None:
    """Lädt url nach target (über target.part, erst am Ende umbenannt)."""
    import os

    part = target + ".part"
    try:
        with urllib.request.urlopen(_request(url), timeout=TIMEOUT, context=ssl_context()) as resp, open(part, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if cancel():
                    raise NetError("cancelled")
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                progress(done, total)
        if total and os.path.getsize(part) != total:
            raise NetError("incomplete")
        os.replace(part, target)
    except (urllib.error.URLError, OSError, NetError) as exc:
        try:
            os.remove(part)
        except OSError:
            pass
        if isinstance(exc, NetError):
            raise
        raise NetError(str(getattr(exc, "reason", exc))) from exc


class Task(QThread):
    """Führt eine Funktion im Hintergrund aus und meldet Ergebnis bzw. Fehler."""

    result = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None) -> None:
        super().__init__(parent)
        self.fn = fn

    def run(self) -> None:
        try:
            value = self.fn()
        except NetError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 – unerwartete Antwort des Servers
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.result.emit(value)


def run_blocking(parent, fn, text: str, title: str):
    """Führt fn im Hintergrund aus, zeigt dabei ein Warte-Fenster. Liefert (Ergebnis, Fehlertext)."""
    from PySide6.QtCore import QEventLoop

    from .dialogs import WaitDialog

    dlg = WaitDialog(parent, title, text, delay=300)
    task = Task(fn)
    out: dict = {}
    task.result.connect(lambda v: out.__setitem__("value", v))
    task.failed.connect(lambda e: out.__setitem__("error", e))
    loop = QEventLoop()
    task.finished.connect(loop.quit)
    dlg.canceled.connect(loop.quit)
    task.start()
    if not task.isFinished():
        loop.exec()
    cancelled = dlg.wasCanceled() and not task.isFinished()
    dlg.finish()
    if cancelled:
        task.result.disconnect()
        task.failed.disconnect()
        _running.append(task)
        task.finished.connect(lambda: _running.remove(task) if task in _running else None)
        return None, None
    task.wait()
    task.deleteLater()
    return out.get("value"), out.get("error")


_running: list = []  # abgebrochene Abfragen laufen im Hintergrund zu Ende
