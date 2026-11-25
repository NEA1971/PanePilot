"""Gespeicherte Abgleiche und Aktion nach dem Beenden (v1.16, L-1620 ff., L-1630 ff.)."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field

from . import folderdiff as fd
from .config import config_dir

FILE_NAME = "sync_profiles.json"

# Aktion nach dem Beenden
AFTER_NONE, AFTER_COMMAND, AFTER_SUSPEND, AFTER_SHUTDOWN = "none", "command", "suspend", "shutdown"
WHEN_ALWAYS, WHEN_OK = "always", "ok"
COUNTDOWN = 30  # Sekunden vor Bereitschaft/Herunterfahren


@dataclass
class After:
    kind: str = AFTER_NONE
    command: str = ""
    when: str = WHEN_OK

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict | None) -> "After":
        a = cls()
        for k in ("kind", "command", "when"):
            v = (d or {}).get(k)
            if isinstance(v, str):
                setattr(a, k, v)
        if a.kind not in (AFTER_NONE, AFTER_COMMAND, AFTER_SUSPEND, AFTER_SHUTDOWN):
            a.kind = AFTER_NONE
        if a.when not in (WHEN_ALWAYS, WHEN_OK):
            a.when = WHEN_OK
        return a

    def due(self, result: fd.Result) -> bool:
        """L-1631: nach Abbruch nie; sonst immer bzw. nur ohne Fehler."""
        if self.kind == AFTER_NONE or result.cancelled:
            return False
        if self.kind == AFTER_COMMAND and not self.command.strip():
            return False
        return self.when == WHEN_ALWAYS or not result.errors


# Ergebnis des letzten Laufs (v1.19, L-1900)
RESULT_OK, RESULT_ERRORS, RESULT_CANCELLED = "ok", "errors", "cancelled"
LAST_ERRORS = 5  # so viele Fehlermeldungen werden gemerkt


@dataclass
class LastRun:
    at: str = ""  # ISO-Zeit (lokal)
    result: str = RESULT_OK
    copied: int = 0
    overwritten: int = 0
    deleted: int = 0
    failed: int = 0
    errors: list = field(default_factory=list)  # ["relativer Pfad: Meldung", …]

    @property
    def ok(self) -> bool:
        return self.result == RESULT_OK

    def to_dict(self) -> dict:
        return {"at": self.at, "result": self.result, "copied": self.copied, "overwritten": self.overwritten,
                "deleted": self.deleted, "failed": self.failed, "errors": list(self.errors)}

    @classmethod
    def from_dict(cls, d) -> "LastRun | None":
        if not isinstance(d, dict) or not isinstance(d.get("at"), str) or not d["at"]:
            return None
        r = cls(d["at"])
        if d.get("result") in (RESULT_OK, RESULT_ERRORS, RESULT_CANCELLED):
            r.result = d["result"]
        for k in ("copied", "overwritten", "deleted", "failed"):
            v = d.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                setattr(r, k, v)
        r.errors = [str(e) for e in (d.get("errors") or []) if isinstance(e, str)][:LAST_ERRORS]
        return r

    @classmethod
    def from_result(cls, result: fd.Result, when=None) -> "LastRun":
        import datetime

        when = when or datetime.datetime.now()
        kind = RESULT_CANCELLED if result.cancelled else RESULT_ERRORS if result.errors else RESULT_OK
        errors = [f"{rel}: {msg}" if rel else str(msg) for rel, msg in result.errors[:LAST_ERRORS]]
        return cls(when.isoformat(timespec="seconds"), kind, result.copied, result.overwritten, result.deleted,
                   result.failed, errors)


@dataclass
class Profile:
    name: str
    left: str
    right: str
    options: fd.Options = field(default_factory=fd.Options)
    after: After = field(default_factory=After)
    last: LastRun | None = None

    def to_dict(self) -> dict:
        d = {"name": self.name, "left": self.left, "right": self.right, "options": self.options.to_dict(),
             "after": self.after.to_dict()}
        if self.last is not None:
            d["last"] = self.last.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Profile | None":
        if not isinstance(d, dict) or not isinstance(d.get("name"), str) or not d["name"].strip():
            return None
        return cls(d["name"].strip(), str(d.get("left") or ""), str(d.get("right") or ""),
                   fd.Options.from_dict(d.get("options")), After.from_dict(d.get("after")),
                   LastRun.from_dict(d.get("last")))


def _path() -> str:
    return os.path.join(str(config_dir()), FILE_NAME)


def load() -> list[Profile]:
    try:
        with open(_path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = [p for p in (Profile.from_dict(d) for d in (data.get("profiles") if isinstance(data, dict) else []) or [])
           if p is not None]
    return sorted(out, key=lambda p: p.name.lower())


def save(profiles: list[Profile]) -> None:
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "profiles": [p.to_dict() for p in profiles]}, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def put(profile: Profile, old_name: str | None = None) -> list[Profile]:
    """Speichern bzw. ersetzen (gleicher Name, Groß-/Kleinschreibung egal)."""
    names = {profile.name.lower()} | ({old_name.lower()} if old_name else set())
    old = load()
    if profile.last is None:  # beim erneuten Speichern bleibt der letzte Lauf erhalten
        for key in ((old_name or "").lower(), profile.name.lower()):
            prev = next((p for p in old if p.name.lower() == key), None)
            if prev is not None and prev.last is not None:
                profile.last = prev.last
                break
    profiles = [p for p in old if p.name.lower() not in names] + [profile]
    save(profiles)
    return load()


def record_run(name: str, result: fd.Result) -> LastRun | None:
    """L-1900: letzten Lauf am gespeicherten Abgleich merken."""
    profiles = load()
    prof = next((p for p in profiles if p.name.lower() == name.lower()), None)
    if prof is None:
        return None
    prof.last = LastRun.from_result(result)
    save(profiles)
    return prof.last


def remove(name: str) -> list[Profile]:
    save([p for p in load() if p.name.lower() != name.lower()])
    return load()


# --- Aktion nach dem Beenden ------------------------------------------------------------------------------
def script_env(left: str, right: str, result: fd.Result, profile: str = "") -> dict:
    """L-1633: Angaben für das Skript."""
    env = clean_env()
    env.update({
        "PANEPILOT_LEFT": left,
        "PANEPILOT_RIGHT": right,
        "PANEPILOT_RESULT": "errors" if result.errors else "ok",
        "PANEPILOT_COPIED": str(result.copied + result.overwritten),
        "PANEPILOT_DELETED": str(result.deleted),
        "PANEPILOT_FAILED": str(result.failed),
        "PANEPILOT_PROFILE": profile or "",
    })
    return env


def clean_env() -> dict:
    """Umgebung ohne die Bibliothekspfade des AppImage (sonst stürzen gestartete Programme ab)."""
    try:
        from .util import child_environment

        qenv = child_environment()
        return {k: qenv.value(k) for k in qenv.keys()}
    except Exception:  # noqa: BLE001
        return dict(os.environ)


def run_command(command: str, env: dict, timeout: int = 3600) -> tuple[int, str]:
    """Im Hintergrund ohne Terminal (L-1634); liefert Rückgabewert und die letzten Zeilen der Ausgabe."""
    import sys

    args, shell = (windows_command(command) if sys.platform.startswith("win") else (command, True))
    try:
        proc = subprocess.run(args, shell=shell, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout, cwd=os.path.expanduser("~"))
    except subprocess.TimeoutExpired as exc:
        out = (exc.output or b"").decode("utf-8", "replace") if isinstance(exc.output, bytes) else (exc.output or "")
        return -1, _tail(out + "\ntimeout")
    except OSError as exc:
        return -1, str(exc)
    return proc.returncode, _tail(proc.stdout.decode("utf-8", "replace"))


def windows_command(command: str):
    """v3.1 (L-4121): .ps1 über PowerShell, .bat/.cmd und alles andere über cmd. Liefert (args, shell)."""
    from .winsys import split_command

    parts = split_command(command) or [command]
    first = parts[0].lower()
    if first.endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", *parts], False
    return command, True  # .bat/.cmd und alles andere: shell=True = cmd.exe /c


def _tail(text: str, lines: int = 8) -> str:
    return "\n".join([ln for ln in text.strip().splitlines()][-lines:])


def power_command(kind: str) -> list[str]:
    """Bereitschaft bzw. Herunterfahren (Linux über systemd, Windows über die Systembefehle)."""
    import sys

    if sys.platform.startswith("win"):
        return ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"] if kind == AFTER_SUSPEND else \
            ["shutdown", "/s", "/t", "0"]
    return ["systemctl", "suspend"] if kind == AFTER_SUSPEND else ["systemctl", "poweroff"]


def power(kind: str) -> str:
    """Führt Bereitschaft/Herunterfahren aus; liefert eine Fehlermeldung oder „“."""
    import sys

    if sys.platform.startswith("win") and kind == AFTER_SUSPEND:
        # v3.1 (L-4120): Standby direkt über die Energieverwaltung (rundll32 landet sonst ggf. im Ruhezustand)
        import ctypes

        try:
            ok = ctypes.WinDLL("powrprof").SetSuspendState(False, False, False)
        except OSError as exc:
            return str(exc)
        return "" if ok else ctypes.FormatError().strip()
    try:
        proc = subprocess.run(power_command(kind), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=60, env=clean_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    return "" if proc.returncode == 0 else _tail(proc.stdout.decode("utf-8", "replace")) or str(proc.returncode)
