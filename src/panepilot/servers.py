"""Serverliste (v1.3): Ordner und Server in ``servers.json``, Passwörter im Schlüsselbund des Systems.

Die Datei enthält keine Passwörter. Diese liegen im Schlüsselbund (Secret Service, unter GNOME der
GNOME-Schlüsselbund) – gebunden an den angemeldeten Nutzer. Ohne Schlüsselbund fragt PanePilot beim
Verbinden nach dem Passwort.
"""

from __future__ import annotations

import base64
import copy
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .config import load_json, save_json
from .remotefs import (CHARSET_AUTO, CHARSET_CUSTOM, CHARSET_UTF8, ENC_EXPLICIT, ENC_IMPLICIT, ENC_NONE, FTP,
                       LOGON_ANONYMOUS, LOGON_ASK, LOGON_KEY, LOGON_NORMAL, SFTP, ServerConfig)

SERVERS_FILE = "servers.json"
SECRET_APP = "PanePilot"


# --- Baum aus Ordnern und Servern ---------------------------------------------------------------------
@dataclass
class Node:
    name: str
    server: ServerConfig | None = None  # None = Ordner
    children: list[Node] = field(default_factory=list)

    @property
    def is_folder(self) -> bool:
        return self.server is None

    def to_dict(self) -> dict:
        if self.server is not None:
            return {"type": "server", **self.server.to_dict()}
        return {"type": "folder", "name": self.name, "children": [c.to_dict() for c in self.children]}

    @staticmethod
    def from_dict(data: dict) -> Node | None:
        if not isinstance(data, dict):
            return None
        if data.get("type") == "server":
            cfg = ServerConfig.from_dict({k: v for k, v in data.items() if k != "type"})
            return Node(cfg.name, cfg)
        node = Node(str(data.get("name", "")))
        node.children = [n for n in (Node.from_dict(c) for c in data.get("children") or []) if n is not None]
        return node


class ServerStore:
    """Alle Server; ``root`` ist ein unsichtbarer Ordner."""

    def __init__(self) -> None:
        self.root = Node("")
        self.load()

    def load(self) -> None:
        data = load_json(SERVERS_FILE, {})
        items = data.get("items") if isinstance(data, dict) else None
        self.root = Node("", children=[n for n in (Node.from_dict(c) for c in items or []) if n is not None])

    def save(self) -> None:
        save_json(SERVERS_FILE, {"version": 1, "items": [c.to_dict() for c in self.root.children]})

    def servers(self) -> list[ServerConfig]:
        out = []

        def walk(node: Node) -> None:
            for c in node.children:
                if c.server is not None:
                    out.append(c.server)
                else:
                    walk(c)
        walk(self.root)
        return out

    def by_id(self, server_id: str) -> ServerConfig | None:
        return next((s for s in self.servers() if s.id == server_id), None)

    def find(self, server_id: str) -> tuple[Node, Node] | None:
        """(Elternordner, Knoten) eines Servers."""
        def walk(parent: Node):
            for c in parent.children:
                if c.server is not None and c.server.id == server_id:
                    return parent, c
                if c.server is None:
                    hit = walk(c)
                    if hit:
                        return hit
            return None
        return walk(self.root)

    def update(self, cfg: ServerConfig) -> None:
        hit = self.find(cfg.id)
        if hit:
            hit[1].server = cfg
            hit[1].name = cfg.name

    def add(self, cfg: ServerConfig, folder: Node | None = None) -> None:
        (folder or self.root).children.append(Node(cfg.name, cfg))

    def remove(self, server_id: str) -> None:
        hit = self.find(server_id)
        if hit:
            hit[0].children.remove(hit[1])

    def unique_name(self, folder: Node, name: str) -> str:
        names = {c.name for c in folder.children}
        if name not in names:
            return name
        n = 2
        while f"{name} ({n})" in names:
            n += 1
        return f"{name} ({n})"

    def duplicate(self, server_id: str) -> ServerConfig | None:
        hit = self.find(server_id)
        if not hit:
            return None
        parent, node = hit
        import uuid

        cfg = node.server.copy(id=uuid.uuid4().hex, name=self.unique_name(parent, node.server.name))
        parent.children.insert(parent.children.index(node) + 1, Node(cfg.name, cfg))
        return cfg


# --- Passwörter im Schlüsselbund --------------------------------------------------------------------------
class _Keyring:
    available: bool | None = None


def _collection(conn):
    import secretstorage

    col = secretstorage.get_default_collection(conn)
    if col.is_locked():
        col.unlock()
    if col.is_locked():
        raise RuntimeError("locked")
    return col


def _with_collection(fn):
    """fn(Sammlung) mit einer eigenen D-Bus-Verbindung ausführen (danach wieder schließen)."""
    import secretstorage

    conn = secretstorage.dbus_init()
    try:
        return fn(_collection(conn))
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def keyring_available() -> bool:
    if os.environ.get("PANEPILOT_NO_KEYRING"):
        return False
    if _Keyring.available is None:
        try:
            _with_collection(lambda col: None)
            _Keyring.available = True
        except Exception:  # noqa: BLE001 – kein D-Bus, kein Secret Service, Schlüsselbund gesperrt
            _Keyring.available = False
    return _Keyring.available


def _attrs(server_id: str, kind: str) -> dict:
    return {"application": SECRET_APP, "server": server_id, "kind": kind}


def store_secret(server_id: str, secret: str, label: str, kind: str = "password") -> bool:
    """Passwort speichern; False, wenn kein Schlüsselbund verfügbar ist."""
    if not keyring_available():
        return False
    try:
        _with_collection(lambda col: col.create_item(f"PanePilot: {label}", _attrs(server_id, kind),
                                                     secret.encode("utf-8"), replace=True))
        return True
    except Exception:  # noqa: BLE001
        return False


def load_secret(server_id: str, kind: str = "password") -> str | None:
    if not keyring_available():
        return None

    def find(col):
        for item in col.search_items(_attrs(server_id, kind)):
            return item.get_secret().decode("utf-8")
        return None
    try:
        return _with_collection(find)
    except Exception:  # noqa: BLE001
        return None


def delete_secret(server_id: str) -> None:
    if not keyring_available():
        return

    def remove(col):
        for kind in ("password", "passphrase"):
            for item in list(col.search_items(_attrs(server_id, kind))):
                item.delete()
    try:
        _with_collection(remove)
    except Exception:  # noqa: BLE001
        pass


# --- Import aus FileZilla -------------------------------------------------------------------------------
def filezilla_file() -> str:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "filezilla", "sitemanager.xml")


@dataclass
class ImportedServer:
    folder: list[str]  # Ordnerpfad
    cfg: ServerConfig
    password: str = ""


def _text(el, tag: str, default: str = "") -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None and child.text is not None else default


def parse_filezilla(path: str) -> list[ImportedServer]:
    """Serverliste aus FileZillas sitemanager.xml lesen (wirft OSError/ValueError bei Fehlern)."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as exc:
        raise ValueError(str(exc)) from exc
    servers = tree.getroot().find("Servers")
    out: list[ImportedServer] = []
    if servers is None:
        return out

    def walk(el, folder: list[str]) -> None:
        for child in el:
            if child.tag == "Folder":
                walk(child, folder + [(child.text or "").strip()])
            elif child.tag == "Server":
                out.append(_server_from_xml(child, folder))
    walk(servers, [])
    return out


def _server_from_xml(el, folder: list[str]) -> ImportedServer:
    proto = int(_text(el, "Protocol", "0") or 0)
    # FileZilla: 0 FTP (TLS, wenn verfügbar), 1 SFTP, 3 FTPS implizit, 4 FTPES explizit, 6 FTP unverschlüsselt
    cfg = ServerConfig(name=_text(el, "Name") or (el.text or "").strip() or _text(el, "Host"))
    cfg.host = _text(el, "Host")
    try:
        cfg.port = int(_text(el, "Port", "0") or 0)
    except ValueError:
        cfg.port = 0
    if proto == 1:
        cfg.protocol = SFTP
    else:
        cfg.protocol = FTP
        cfg.encryption = {3: ENC_IMPLICIT, 6: ENC_NONE}.get(proto, ENC_EXPLICIT)
    logon = int(_text(el, "Logontype", "1") or 1)
    # 0 anonym, 1 normal, 2 Passwort abfragen, 3 interaktiv, 4 Konto, 5 Schlüsseldatei
    cfg.logon = {0: LOGON_ANONYMOUS, 2: LOGON_ASK, 3: LOGON_ASK, 5: LOGON_KEY}.get(logon, LOGON_NORMAL)
    cfg.user = _text(el, "User")
    cfg.keyfile = _text(el, "Keyfile")
    cfg.comment = _text(el, "Comments")
    cfg.local_dir = _text(el, "LocalDir")
    cfg.remote_dir = _filezilla_path(_text(el, "RemoteDir"))
    cfg.passive = _text(el, "PasvMode", "MODE_DEFAULT") != "MODE_ACTIVE"
    enc = _text(el, "EncodingType", "Auto")
    cfg.charset = {"UTF-8": CHARSET_UTF8, "Custom": CHARSET_CUSTOM}.get(enc, CHARSET_AUTO)
    cfg.custom_charset = _text(el, "CustomEncoding")
    color = int(_text(el, "Colour", "0") or 0)
    cfg.color = _FZ_COLORS.get(color, "")
    if cfg.port == cfg.default_port():
        cfg.port = 0
    password = ""
    pw = el.find("Pass")
    if pw is not None and pw.text and cfg.logon == LOGON_NORMAL:
        if pw.get("encoding") == "base64":
            try:
                password = base64.b64decode(pw.text).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                password = ""
        elif pw.get("encoding") != "crypt":  # mit Master-Passwort verschlüsselt: nicht lesbar
            password = pw.text
    return ImportedServer(folder, cfg, password)


# Hintergrundfarben von FileZilla (Nummer → Farbe)
_FZ_COLORS = {1: "#ff8080", 2: "#80ff80", 3: "#8080ff", 4: "#ffff80", 5: "#80ffff", 6: "#ff80ff",
              7: "#ffc080"}


def _filezilla_path(text: str) -> str:
    """FileZilla speichert Pfade als „1 0 4 home 3 dir“ (Typ, Präfixlänge, dann Länge + Teil)."""
    parts = text.split(" ")
    if len(parts) < 2 or not parts[0].isdigit():
        return text
    segs = []
    rest = " ".join(parts[2:])
    while rest:
        num, _, rest = rest.partition(" ")
        if not num.isdigit():
            break
        n = int(num)
        segs.append(rest[:n])
        rest = rest[n + 1:]
    return "/" + "/".join(segs) if segs else "/"


def import_servers(store: ServerStore, items: list[ImportedServer]) -> tuple[int, int, int]:
    """Übernimmt die gewählten Server. (übernommen, übersprungen, Passwörter ohne Schlüsselbund)."""
    added = skipped = no_keyring = 0
    for imp in items:
        folder = store.root
        for name in imp.folder:
            sub = next((c for c in folder.children if c.is_folder and c.name == name), None)
            if sub is None:
                sub = Node(name)
                folder.children.append(sub)
            folder = sub
        if any(c.name == imp.cfg.name for c in folder.children if not c.is_folder):
            skipped += 1
            continue
        cfg = copy.deepcopy(imp.cfg)
        store.add(cfg, folder)
        added += 1
        if imp.password and not store_secret(cfg.id, imp.password, cfg.name):
            no_keyring += 1
    store.save()
    return added, skipped, no_keyring
