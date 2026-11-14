"""Verbindungen zu Servern (v1.3): FTP, FTP über TLS (explizit/implizit) und SFTP.

Alles hier läuft ohne Oberfläche und darf in Hintergrund-Threads benutzt werden – aber eine Verbindung
immer nur von einem Thread zur selben Zeit. Rückfragen (Passwort, Fingerabdruck) stellt die Oberfläche;
dafür werfen die Funktionen hier eigene Ausnahmen (z. B. ``UnknownHostKey``).
"""

from __future__ import annotations

import ftplib
import hashlib
import json
import os
import posixpath
import socket
import ssl
import stat
import time
import uuid
from dataclasses import asdict, dataclass, field, fields

from .config import config_dir

TIMEOUT = 20
CHUNK = 64 * 1024

FTP, SFTP = "ftp", "sftp"
ENC_NONE, ENC_EXPLICIT, ENC_IMPLICIT = "none", "explicit", "implicit"
LOGON_NORMAL, LOGON_ANONYMOUS, LOGON_ASK, LOGON_KEY = "normal", "anonymous", "ask", "key"
CHARSET_AUTO, CHARSET_UTF8, CHARSET_CUSTOM = "auto", "utf8", "custom"
SCHEMES = ("ftp://", "ftps://", "sftp://")



def known_hosts_file():
    return config_dir() / "known_hosts"


def known_certs_file():
    return config_dir() / "known_certificates.json"


# --- Fehler -------------------------------------------------------------------------------------------
class RemoteError(Exception):
    """Fehler bei der Verbindung oder einem Befehl, mit lesbarer Meldung."""


class ConnectionLost(RemoteError):
    """Die Verbindung ist abgerissen (neu verbinden möglich)."""


class AuthFailed(RemoteError):
    """Anmeldung abgelehnt."""


class Cancelled(RemoteError):
    pass


class NoSftp(RemoteError):
    """Der SSH-Server bietet kein SFTP an."""


class UnknownHostKey(RemoteError):
    """Fingerabdruck unbekannt oder geändert – die Oberfläche fragt nach."""

    def __init__(self, host: str, key_type: str, fingerprint: str, changed: bool, key=None) -> None:
        super().__init__(fingerprint)
        self.host, self.key_type, self.fingerprint, self.changed, self.key = host, key_type, fingerprint, changed, key


class UnknownCertificate(RemoteError):
    def __init__(self, host: str, fingerprint: str, changed: bool, subject: str = "") -> None:
        super().__init__(fingerprint)
        self.host, self.fingerprint, self.changed, self.subject = host, fingerprint, changed, subject


# --- Einstellungen eines Servers -----------------------------------------------------------------------
@dataclass
class ServerConfig:
    name: str = ""
    protocol: str = FTP
    host: str = ""
    port: int = 0  # 0 = Vorgabe
    encryption: str = ENC_EXPLICIT
    logon: str = LOGON_NORMAL
    user: str = ""
    keyfile: str = ""
    color: str = ""  # Hintergrundfarbe (#rrggbb) oder leer
    comment: str = ""
    remote_dir: str = ""
    local_dir: str = ""
    passive: bool = True
    charset: str = CHARSET_AUTO
    custom_charset: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def default_port(self) -> int:
        if self.protocol == SFTP:
            return 22
        return 990 if self.encryption == ENC_IMPLICIT else 21

    def real_port(self) -> int:
        return self.port or self.default_port()

    def scheme(self) -> str:
        if self.protocol == SFTP:
            return "sftp"
        return "ftp" if self.encryption == ENC_NONE else "ftps"

    def login_user(self) -> str:
        return "anonymous" if self.logon == LOGON_ANONYMOUS and self.protocol == FTP else self.user

    def base_uri(self) -> str:
        user = self.login_user()
        host = f"[{self.host}]" if ":" in self.host else self.host
        port = f":{self.real_port()}" if self.real_port() != self.default_port() else ""
        return f"{self.scheme()}://{user + '@' if user else ''}{host}{port}"

    def needs_password(self) -> bool:
        return self.logon in (LOGON_NORMAL, LOGON_ASK)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ServerConfig:
        names = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in data.items() if k in names})
        try:
            cfg.port = int(cfg.port or 0)
        except (TypeError, ValueError):
            cfg.port = 0
        cfg.passive = bool(cfg.passive)
        return cfg

    def copy(self, **changes) -> ServerConfig:
        data = self.to_dict()
        data.update(changes)
        return ServerConfig.from_dict(data)


def is_remote_uri(text: str) -> bool:
    return isinstance(text, str) and text.startswith(SCHEMES)


def split_uri(uri: str) -> tuple[str, str]:
    """(Basis wie „sftp://user@host“, Pfad wie „/Download“)."""
    head, sep, rest = uri.partition("://")
    slash = rest.find("/")
    if slash < 0:
        return uri, "/"
    return f"{head}{sep}{rest[:slash]}", rest[slash:] or "/"


@dataclass
class RemoteItem:
    name: str
    is_dir: bool
    size: int = 0
    mtime: float = 0.0
    mode: int = 0
    is_link: bool = False
    uid: int = -1
    gid: int = -1


# --- Bekannte Fingerabdrücke (TLS) -------------------------------------------------------------------
def _load_certs() -> dict:
    try:
        data = json.loads(known_certs_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def trust_certificate(host_key: str, fingerprint: str) -> None:
    data = _load_certs()
    data[host_key] = fingerprint
    known_certs_file().parent.mkdir(parents=True, exist_ok=True)
    known_certs_file().write_text(json.dumps(data, indent=2), encoding="utf-8")


def _cert_fingerprint(der: bytes) -> str:
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def trust_host_key(err: UnknownHostKey) -> None:
    """SFTP: Schlüssel des Servers in die eigene known_hosts-Datei übernehmen (ersetzt einen alten)."""
    import paramiko

    keys = paramiko.HostKeys()
    if known_hosts_file().exists():
        keys.load(str(known_hosts_file()))
    if err.host in keys:
        del keys[err.host]
    keys.add(err.host, err.key.get_name(), err.key)
    known_hosts_file().parent.mkdir(parents=True, exist_ok=True)
    keys.save(str(known_hosts_file()))


def _check_host_key(host_entry: str, key) -> None:
    import base64

    import paramiko

    keys = paramiko.HostKeys()
    if known_hosts_file().exists():
        try:
            keys.load(str(known_hosts_file()))
        except (OSError, paramiko.SSHException):
            pass
    known = keys.lookup(host_entry)
    fp = "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
    if known is not None and key.get_name() in known:
        if known[key.get_name()] == key:
            return
        raise UnknownHostKey(host_entry, key.get_name(), fp, True, key)
    if known:  # anderer Schlüsseltyp bekannt → ebenfalls „geändert“
        raise UnknownHostKey(host_entry, key.get_name(), fp, True, key)
    raise UnknownHostKey(host_entry, key.get_name(), fp, False, key)


# --- Verbindung ---------------------------------------------------------------------------------------
class Connection:
    """Gemeinsame Schnittstelle für FTP und SFTP."""

    def __init__(self, cfg: ServerConfig) -> None:
        self.cfg = cfg

    @staticmethod
    def open(cfg: ServerConfig, password: str = "", passphrase: str = "") -> Connection:
        conn = SftpConnection(cfg) if cfg.protocol == SFTP else FtpConnection(cfg)
        conn.connect(password, passphrase)
        return conn

    # Pfade sind POSIX-Pfade auf dem Server
    def connect(self, password: str, passphrase: str = "") -> None:
        raise NotImplementedError

    def home(self) -> str:
        raise NotImplementedError

    def listdir(self, path: str) -> list[RemoteItem]:
        raise NotImplementedError

    def stat(self, path: str) -> RemoteItem | None:
        parent, name = posixpath.split(path.rstrip("/") or "/")
        if not name:
            return RemoteItem("/", True)
        for item in self.listdir(parent or "/"):
            if item.name == name:
                return item
        return None

    def mkdir(self, path: str) -> None:
        raise NotImplementedError

    def rename(self, old: str, new: str) -> None:
        raise NotImplementedError

    def remove(self, path: str) -> None:
        raise NotImplementedError

    def rmdir(self, path: str) -> None:
        raise NotImplementedError

    def download(self, remote: str, local_fh, progress=lambda n: None, cancel=lambda: False) -> None:
        raise NotImplementedError

    def upload(self, local_fh, remote: str, progress=lambda n: None, cancel=lambda: False) -> None:
        raise NotImplementedError

    def set_mtime(self, path: str, mtime: float) -> None:
        pass

    def close(self) -> None:
        pass

    def alive(self) -> bool:
        return True

    # Hilfen
    def makedirs(self, path: str) -> None:
        parts = [p for p in path.split("/") if p]
        cur = ""
        for p in parts:
            cur = f"{cur}/{p}"
            item = self.stat(cur)
            if item is None:
                self.mkdir(cur)
            elif not item.is_dir:
                raise RemoteError(f"{cur}: not a folder")

    def remove_tree(self, path: str, cancel=lambda: False) -> None:
        for item in self.listdir(path):
            if cancel():
                raise Cancelled()
            child = posixpath.join(path, item.name)
            if item.is_dir and not item.is_link:
                self.remove_tree(child, cancel)
            else:
                self.remove(child)
        self.rmdir(path)


def _ftp_error(exc: Exception) -> RemoteError:
    if isinstance(exc, ftplib.error_perm):
        text = str(exc)
        if text.startswith("530"):
            return AuthFailed(text)
        return RemoteError(text)
    if isinstance(exc, (EOFError, ConnectionError, BrokenPipeError, socket.timeout, TimeoutError)):
        return ConnectionLost(str(exc) or type(exc).__name__)
    if isinstance(exc, ftplib.Error):
        return RemoteError(str(exc))
    if isinstance(exc, OSError):
        return ConnectionLost(exc.strerror or str(exc))
    return RemoteError(str(exc))


class _FTP_TLS(ftplib.FTP_TLS):
    """FTP über TLS mit Wiederverwendung der TLS-Sitzung für Datenverbindungen (verlangen viele Server)."""

    implicit = False

    def connect(self, host="", port=0, timeout=-999, source_address=None):
        if not self.implicit:
            return super().connect(host, port, timeout, source_address)
        if host:
            self.host = host
        if port > 0:
            self.port = port
        if timeout != -999:
            self.timeout = timeout
        self.sock = socket.create_connection((self.host, self.port), self.timeout, source_address=source_address)
        self.af = self.sock.family
        self.sock = self.context.wrap_socket(self.sock, server_hostname=self.host)
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

    def login(self, user="", passwd="", acct="", secure=True):
        if self.implicit:
            return ftplib.FTP.login(self, user, passwd, acct)
        return super().login(user, passwd, acct, secure)

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self.host, session=self.sock.session)
        return conn, size


class FtpConnection(Connection):
    def __init__(self, cfg: ServerConfig) -> None:
        super().__init__(cfg)
        self.ftp: ftplib.FTP | None = None
        self._mlsd = True

    def _encoding(self) -> str:
        if self.cfg.charset == CHARSET_CUSTOM and self.cfg.custom_charset.strip():
            return self.cfg.custom_charset.strip()
        return "utf-8"

    def _make(self, verify: bool) -> ftplib.FTP:
        if self.cfg.encryption == ENC_NONE:
            ftp = ftplib.FTP(timeout=TIMEOUT, encoding=self._encoding())
        else:
            from .netutil import ssl_context

            if verify:
                ctx = ssl_context()  # Zertifizierungsstellen des Systems
            else:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            cls = type("_FTPS", (_FTP_TLS,), {"implicit": self.cfg.encryption == ENC_IMPLICIT})
            ftp = cls(context=ctx, timeout=TIMEOUT, encoding=self._encoding())
        return ftp

    def _host_key(self) -> str:
        return f"{self.cfg.host}:{self.cfg.real_port()}"

    def connect(self, password: str, passphrase: str = "") -> None:
        user = self.cfg.login_user() or "anonymous"
        if self.cfg.logon == LOGON_ANONYMOUS:
            password = password or "anonymous@"
        ftp = None
        try:
            if self.cfg.encryption == ENC_NONE:
                ftp = self._make(False)
                ftp.connect(self.cfg.host, self.cfg.real_port())
            else:
                ftp = self._connect_tls()
            ftp.login(user, password)
            if self.cfg.encryption != ENC_NONE:
                ftp.prot_p()
            ftp.set_pasv(bool(self.cfg.passive))
            if self.cfg.charset != CHARSET_CUSTOM:
                try:
                    ftp.sendcmd("OPTS UTF8 ON")
                except ftplib.Error:
                    pass
            try:
                ftp.voidcmd("TYPE I")
            except ftplib.Error:
                pass
        except (RemoteError, UnknownCertificate):
            self._quiet_close(ftp)
            raise
        except Exception as exc:  # noqa: BLE001
            self._quiet_close(ftp)
            err = _ftp_error(exc)
            raise (AuthFailed(str(exc)) if isinstance(err, AuthFailed) else err) from exc
        self.ftp = ftp

    def _connect_tls(self) -> ftplib.FTP:
        """Erst mit Prüfung über die bekannten Zertifizierungsstellen, sonst über den gemerkten Fingerabdruck."""
        ftp = self._make(True)
        try:
            ftp.connect(self.cfg.host, self.cfg.real_port())
            if not ftp.implicit:
                ftp.auth()
            return ftp
        except ssl.SSLCertVerificationError:
            self._quiet_close(ftp)
        except ssl.SSLError as exc:
            self._quiet_close(ftp)
            if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
                raise RemoteError(f"TLS: {exc}") from exc
        ftp = self._make(False)
        ftp.connect(self.cfg.host, self.cfg.real_port())
        if not ftp.implicit:
            ftp.auth()
        der = ftp.sock.getpeercert(binary_form=True) or b""
        fp = _cert_fingerprint(der)
        known = _load_certs().get(self._host_key())
        if known != fp:
            self._quiet_close(ftp)
            raise UnknownCertificate(self._host_key(), fp, known is not None)
        return ftp

    @staticmethod
    def _quiet_close(ftp) -> None:
        if ftp is None:
            return
        try:
            ftp.close()
        except Exception:  # noqa: BLE001
            pass

    def _call(self, fn, *args):
        if self.ftp is None:
            raise ConnectionLost("not connected")
        try:
            return fn(*args)
        except RemoteError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise _ftp_error(exc) from exc

    def home(self) -> str:
        return self._call(self.ftp.pwd) or "/"

    def alive(self) -> bool:
        try:
            self._call(self.ftp.voidcmd, "NOOP")
            return True
        except RemoteError:
            return False

    def listdir(self, path: str) -> list[RemoteItem]:
        if self._mlsd:
            try:
                return self._call(self._list_mlsd, path)
            except RemoteError as exc:
                if isinstance(exc, ConnectionLost) or str(exc)[:3] not in ("500", "501", "502", "504"):
                    raise
                self._mlsd = False
        return self._call(self._list_plain, path)

    def _list_mlsd(self, path: str) -> list[RemoteItem]:
        items = []
        for name, facts in self.ftp.mlsd(path or "/"):
            kind = facts.get("type", "").lower()
            if kind in ("cdir", "pdir") or name in (".", ".."):
                continue
            is_dir = kind == "dir"
            mode = 0
            if "unix.mode" in facts:
                try:
                    mode = int(facts["unix.mode"], 8)
                except ValueError:
                    mode = 0
            mode |= stat.S_IFDIR if is_dir else stat.S_IFREG
            items.append(RemoteItem(name, is_dir, 0 if is_dir else int(facts.get("size", 0) or 0),
                                    _parse_mdtm(facts.get("modify", "")), mode, "slink" in kind))
        return items

    def _list_plain(self, path: str) -> list[RemoteItem]:
        lines: list[str] = []
        self.ftp.retrlines(f"LIST -a {path}" if path else "LIST -a", lines.append)
        items = [it for it in (parse_list_line(ln) for ln in lines) if it is not None]
        if not items and lines:  # Server ohne „-a“
            lines.clear()
            self.ftp.retrlines(f"LIST {path}", lines.append)
            items = [it for it in (parse_list_line(ln) for ln in lines) if it is not None]
        return [it for it in items if it.name not in (".", "..")]

    def mkdir(self, path: str) -> None:
        self._call(self.ftp.mkd, path)

    def rename(self, old: str, new: str) -> None:
        self._call(self.ftp.rename, old, new)

    def remove(self, path: str) -> None:
        self._call(self.ftp.delete, path)

    def rmdir(self, path: str) -> None:
        self._call(self.ftp.rmd, path)

    def download(self, remote: str, local_fh, progress=lambda n: None, cancel=lambda: False) -> None:
        def chunk(data: bytes) -> None:
            if cancel():
                raise Cancelled()
            local_fh.write(data)
            progress(len(data))
        try:
            self._call(self.ftp.retrbinary, f"RETR {remote}", chunk, CHUNK)
        except Cancelled:
            self._abort()
            raise

    def upload(self, local_fh, remote: str, progress=lambda n: None, cancel=lambda: False) -> None:
        def chunk(data: bytes) -> None:
            if cancel():
                raise Cancelled()
            progress(len(data))
        try:
            self._call(self.ftp.storbinary, f"STOR {remote}", local_fh, CHUNK, chunk)
        except Cancelled:
            self._abort()
            raise

    def _abort(self) -> None:
        """Nach einem Abbruch mitten in der Übertragung ist die Steuerverbindung nicht mehr sauber."""
        self._quiet_close(self.ftp)
        self.ftp = None

    def set_mtime(self, path: str, mtime: float) -> None:
        stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime(mtime))
        try:
            self._call(self.ftp.sendcmd, f"MFMT {stamp} {path}")
        except RemoteError:
            pass

    def close(self) -> None:
        if self.ftp is not None:
            try:
                self.ftp.quit()
            except Exception:  # noqa: BLE001
                self._quiet_close(self.ftp)
            self.ftp = None


def _parse_mdtm(text: str) -> float:
    import calendar

    text = (text or "").strip()
    if len(text) < 14:
        return 0.0
    try:
        tm = time.strptime(text[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return 0.0
    return float(calendar.timegm(tm))


_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                       "nov", "dec"), 1)}


def parse_list_line(line: str) -> RemoteItem | None:
    """Eine Zeile der LIST-Ausgabe (Unix „ls -l“ oder Windows/DOS) auswerten."""
    import datetime as dt
    import re

    line = line.rstrip("\r\n")
    if not line or line.lower().startswith("total "):
        return None
    m = re.match(r"^(\d\d)-(\d\d)-(\d\d,?\d*)\s+(\d\d):(\d\d)([AP]M)?\s+(<DIR>|\d+)\s+(.+)$", line)
    if m:  # Windows/IIS
        mo, d, y, hh, mi, ampm, size, name = m.groups()
        year = int(y[:2]) + (2000 if int(y[:2]) < 70 else 1900) if len(y) <= 2 else int(y[:4])
        hour = int(hh) % 12 + (12 if ampm == "PM" else 0) if ampm else int(hh)
        try:
            when = dt.datetime(year, int(mo), int(d), hour, int(mi)).timestamp()
        except ValueError:
            when = 0.0
        is_dir = size == "<DIR>"
        return RemoteItem(name, is_dir, 0 if is_dir else int(size), when,
                          stat.S_IFDIR | 0o755 if is_dir else stat.S_IFREG | 0o644)
    parts = line.split(None, 8)
    if len(parts) < 9 or len(parts[0]) < 10:
        return None
    perms, _links, owner, group, size, mon, day, year_or_time, name = parts
    kind = perms[0]
    is_link = kind == "l"
    if is_link and " -> " in name:
        name = name.split(" -> ", 1)[0]
    try:
        month = _MONTHS[mon[:3].lower()]
        if ":" in year_or_time:
            now = dt.datetime.now()
            hh, mm = year_or_time.split(":")
            when = dt.datetime(now.year, month, int(day), int(hh), int(mm))
            if when > now + dt.timedelta(days=2):
                when = when.replace(year=now.year - 1)
        else:
            when = dt.datetime(int(year_or_time), month, int(day))
        mtime = when.timestamp()
    except (KeyError, ValueError):
        mtime = 0.0
    mode = 0
    for i, ch in enumerate(perms[1:10]):
        if ch not in "-":
            mode |= 1 << (8 - i)
    is_dir = kind == "d"
    mode |= stat.S_IFDIR if is_dir else (stat.S_IFLNK if is_link else stat.S_IFREG)
    try:
        nsize = int(size)
    except ValueError:
        nsize = 0
    return RemoteItem(name, is_dir, 0 if is_dir else nsize, mtime, mode, is_link)


class SftpConnection(Connection):
    def __init__(self, cfg: ServerConfig) -> None:
        super().__init__(cfg)
        self.transport = None
        self.sftp = None

    def _host_entry(self) -> str:
        port = self.cfg.real_port()
        return self.cfg.host if port == 22 else f"[{self.cfg.host}]:{port}"

    def connect(self, password: str, passphrase: str = "") -> None:
        import paramiko

        try:
            sock = socket.create_connection((self.cfg.host, self.cfg.real_port()), TIMEOUT)
        except OSError as exc:
            raise ConnectionLost(exc.strerror or str(exc)) from exc
        transport = paramiko.Transport(sock)
        try:
            transport.banner_timeout = TIMEOUT
            transport.start_client(timeout=TIMEOUT)
            _check_host_key(self._host_entry(), transport.get_remote_server_key())
            self._auth(transport, password, passphrase)
            try:
                sftp = paramiko.SFTPClient.from_transport(transport)
            except paramiko.SSHException as exc:
                raise NoSftp(str(exc)) from exc
            if sftp is None:
                raise NoSftp("subsystem")
            sftp.get_channel().settimeout(TIMEOUT * 3)
        except (RemoteError, UnknownHostKey):
            transport.close()
            raise
        except paramiko.AuthenticationException as exc:
            transport.close()
            raise AuthFailed(str(exc)) from exc
        except (paramiko.SSHException, OSError, EOFError) as exc:
            transport.close()
            raise ConnectionLost(str(exc)) from exc
        self.transport, self.sftp = transport, sftp

    def _auth(self, transport, password: str, passphrase: str) -> None:
        import paramiko

        user = self.cfg.user
        if self.cfg.logon == LOGON_KEY:
            try:
                key = paramiko.PKey.from_path(os.path.expanduser(self.cfg.keyfile), passphrase or None)
            except (OSError, paramiko.SSHException, ValueError) as exc:
                raise AuthFailed(f"{self.cfg.keyfile}: {exc}") from exc
            transport.auth_publickey(user, key)
            return
        try:
            transport.auth_password(user, password)
        except paramiko.BadAuthenticationType as exc:
            if "keyboard-interactive" not in exc.allowed_types:
                raise AuthFailed(str(exc)) from exc
            transport.auth_interactive(user, lambda _t, _i, prompts: [password for _p in prompts])

    def _call(self, fn, *args):
        import paramiko

        if self.sftp is None:
            raise ConnectionLost("not connected")
        try:
            return fn(*args)
        except RemoteError:
            raise
        except FileNotFoundError as exc:
            raise RemoteError(exc.strerror or "No such file") from exc
        except PermissionError as exc:
            raise RemoteError(exc.strerror or "Permission denied") from exc
        except IOError as exc:
            if self.transport is None or not self.transport.is_active():
                raise ConnectionLost(str(exc)) from exc
            raise RemoteError(exc.strerror or str(exc)) from exc
        except (paramiko.SSHException, EOFError, socket.timeout) as exc:
            raise ConnectionLost(str(exc)) from exc

    def alive(self) -> bool:
        return self.transport is not None and self.transport.is_active()

    def home(self) -> str:
        return self._call(self.sftp.normalize, ".") or "/"

    def listdir(self, path: str) -> list[RemoteItem]:
        attrs = self._call(self.sftp.listdir_attr, path or "/")
        items = []
        for a in attrs:
            mode = a.st_mode or 0
            is_link = stat.S_ISLNK(mode)
            is_dir = stat.S_ISDIR(mode)
            size = a.st_size or 0
            if is_link:
                try:
                    target = self.sftp.stat(posixpath.join(path, a.filename))
                    is_dir = stat.S_ISDIR(target.st_mode or 0)
                    size = target.st_size or 0
                except (IOError, OSError):
                    pass
            items.append(RemoteItem(a.filename, is_dir, 0 if is_dir else size, float(a.st_mtime or 0), mode,
                                    is_link, a.st_uid if a.st_uid is not None else -1,
                                    a.st_gid if a.st_gid is not None else -1))
        return items

    def stat(self, path: str) -> RemoteItem | None:
        try:
            a = self._call(self.sftp.stat, path)
        except RemoteError as exc:
            if isinstance(exc, ConnectionLost):
                raise
            return None
        is_dir = stat.S_ISDIR(a.st_mode or 0)
        return RemoteItem(posixpath.basename(path), is_dir, 0 if is_dir else a.st_size or 0, float(a.st_mtime or 0),
                          a.st_mode or 0)

    def mkdir(self, path: str) -> None:
        self._call(self.sftp.mkdir, path)

    def rename(self, old: str, new: str) -> None:
        self._call(self.sftp.rename, old, new)

    def remove(self, path: str) -> None:
        self._call(self.sftp.remove, path)

    def rmdir(self, path: str) -> None:
        self._call(self.sftp.rmdir, path)

    def download(self, remote: str, local_fh, progress=lambda n: None, cancel=lambda: False) -> None:
        def run():
            with self.sftp.open(remote, "rb") as fh:
                fh.prefetch()
                while True:
                    if cancel():
                        raise Cancelled()
                    data = fh.read(CHUNK)
                    if not data:
                        break
                    local_fh.write(data)
                    progress(len(data))
        self._call(run)

    def upload(self, local_fh, remote: str, progress=lambda n: None, cancel=lambda: False) -> None:
        def run():
            with self.sftp.open(remote, "wb") as fh:
                fh.set_pipelined(True)
                while True:
                    if cancel():
                        raise Cancelled()
                    data = local_fh.read(CHUNK)
                    if not data:
                        break
                    fh.write(data)
                    progress(len(data))
        self._call(run)

    def set_mtime(self, path: str, mtime: float) -> None:
        try:
            self._call(self.sftp.utime, path, (mtime, mtime))
        except RemoteError:
            pass

    def close(self) -> None:
        for obj in (self.sftp, self.transport):
            try:
                if obj is not None:
                    obj.close()
            except Exception:  # noqa: BLE001
                pass
        self.sftp = self.transport = None
