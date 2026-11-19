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


@dataclass
class Profile:
    name: str
    left: str
    right: str
    options: fd.Options = field(default_factory=fd.Options)
    after: After = field(default_factory=After)

    def to_dict(self) -> dict:
        return {"name": self.name, "left": self.left, "right": self.right, "options": self.options.to_dict(),
                "after": self.after.to_dict()}

    @classmethod
    def from_dict(cls, d: dict) -> "Profile | None":
        if not isinstance(d, dict) or not isinstance(d.get("name"), str) or not d["name"].strip():
            return None
        return cls(d["name"].strip(), str(d.get("left") or ""), str(d.get("right") or ""),
                   fd.Options.from_dict(d.get("options")), After.from_dict(d.get("after")))


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
    profiles = [p for p in load() if p.name.lower() not in names] + [profile]
    save(profiles)
    return load()


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
    try:
        proc = subprocess.run(command, shell=True, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=timeout, cwd=os.path.expanduser("~"))
    except subprocess.TimeoutExpired as exc:
        out = (exc.output or b"").decode("utf-8", "replace") if isinstance(exc.output, bytes) else (exc.output or "")
        return -1, _tail(out + "\ntimeout")
    except OSError as exc:
        return -1, str(exc)
    return proc.returncode, _tail(proc.stdout.decode("utf-8", "replace"))


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
    try:
        proc = subprocess.run(power_command(kind), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=60, env=clean_env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    return "" if proc.returncode == 0 else _tail(proc.stdout.decode("utf-8", "replace")) or str(proc.returncode)
