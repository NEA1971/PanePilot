"""Kleine Test-Server für FTP (pyftpdlib) und SFTP (paramiko) auf einem lokalen Ordner."""

from __future__ import annotations

import os
import socket
import threading

USER, PASSWORD = "alice", "geheim"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- FTP ------------------------------------------------------------------------------------------------
class FtpTestServer:
    def __init__(self, root: str, tls: bool = False, certfile: str | None = None) -> None:
        from pyftpdlib.authorizers import DummyAuthorizer
        from pyftpdlib.handlers import FTPHandler
        from pyftpdlib.servers import ThreadedFTPServer

        auth = DummyAuthorizer()
        auth.add_user(USER, PASSWORD, root, perm="elradfmwMT")
        if tls:
            from pyftpdlib.handlers import TLS_FTPHandler

            handler = type("H", (TLS_FTPHandler,), {})
            handler.certfile = certfile
            handler.tls_control_required = True
            handler.tls_data_required = True
        else:
            handler = type("H", (FTPHandler,), {})
        handler.authorizer = auth
        handler.passive_ports = None
        self.port = free_port()
        from pyftpdlib.ioloop import IOLoop

        # eigene IOLoop je Server – sonst beendet das Schließen eines Servers auch den nächsten
        self.server = ThreadedFTPServer(("127.0.0.1", self.port), handler, ioloop=IOLoop())
        self.server._exit = threading.Event()  # pyftpdlib teilt das Ereignis sonst zwischen allen Servern
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"timeout": 0.2, "handle_exit": False}, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.close_all()


def make_cert(folder: str) -> str:
    """Selbst ausgestelltes Zertifikat (wie bei einer Handy-App)."""
    import datetime as dt

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=30))
            .sign(key, hashes.SHA256()))
    path = os.path.join(folder, "cert.pem")
    with open(path, "wb") as fh:
        fh.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                   serialization.NoEncryption()))
        fh.write(cert.public_bytes(serialization.Encoding.PEM))
    return path


# --- SFTP -----------------------------------------------------------------------------------------------
def _sftp_classes(root: str):
    import paramiko
    from paramiko import SFTPAttributes, SFTPHandle, SFTPServer, SFTPServerInterface

    class Handle(SFTPHandle):
        def stat(self):
            try:
                return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)

        def chattr(self, attr):
            return paramiko.SFTP_OK

    class SftpIf(SFTPServerInterface):
        def _real(self, path):
            return os.path.join(root, self.canonicalize(path).lstrip("/"))

        def canonicalize(self, path):
            if not path.startswith("/"):
                path = "/" + path
            return os.path.normpath(path).replace("\\", "/") if path not in ("/.", "/") else "/"

        def list_folder(self, path):
            real = self._real(path)
            try:
                out = []
                for name in os.listdir(real):
                    attr = SFTPAttributes.from_stat(os.lstat(os.path.join(real, name)))
                    attr.filename = name
                    out.append(attr)
                return out
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)

        def stat(self, path):
            try:
                return SFTPAttributes.from_stat(os.stat(self._real(path)))
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)

        lstat = stat

        def open(self, path, flags, attr):
            real = self._real(path)
            try:
                binary = getattr(os, "O_BINARY", 0)
                fd = os.open(real, flags | binary, 0o644)
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)
            if flags & os.O_WRONLY:
                mode = "ab" if flags & os.O_APPEND else "wb"
            elif flags & os.O_RDWR:
                mode = "a+b" if flags & os.O_APPEND else "r+b"
            else:
                mode = "rb"
            fobj = os.fdopen(fd, mode)
            h = Handle(flags)
            h.filename = real
            h.readfile = fobj
            h.writefile = fobj
            return h

        def remove(self, path):
            try:
                os.remove(self._real(path))
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK

        def rename(self, old, new):
            try:
                os.rename(self._real(old), self._real(new))
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK

        def mkdir(self, path, attr):
            try:
                os.mkdir(self._real(path))
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK

        def rmdir(self, path):
            try:
                os.rmdir(self._real(path))
            except OSError as e:
                return SFTPServer.convert_errno(e.errno)
            return paramiko.SFTP_OK

        def chattr(self, path, attr):
            if attr.st_mtime is not None:
                os.utime(self._real(path), (attr.st_atime or attr.st_mtime, attr.st_mtime))
            return paramiko.SFTP_OK

    class Server(paramiko.ServerInterface):
        def check_auth_password(self, username, password):
            ok = username == USER and password == PASSWORD
            return paramiko.AUTH_SUCCESSFUL if ok else paramiko.AUTH_FAILED

        def check_channel_request(self, kind, chanid):
            return paramiko.OPEN_SUCCEEDED

        def get_allowed_auths(self, username):
            return "password"

    return Server, SftpIf


class SftpTestServer:
    def __init__(self, root: str, host_key=None) -> None:
        import paramiko

        self.root = root
        self.key = host_key or paramiko.Ed25519Key.from_private_key_file(_ed25519_file(root))
        self.port = free_port()
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", self.port))
        self.sock.listen(5)
        self.sock.settimeout(0.2)
        self._stop = False
        self.transports = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        import paramiko

        Server, SftpIf = _sftp_classes(self.root)
        while not self._stop:
            try:
                client, _addr = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            t = paramiko.Transport(client)
            t.add_server_key(self.key)
            t.set_subsystem_handler("sftp", paramiko.SFTPServer, SftpIf)
            try:
                t.start_server(server=Server())
            except Exception:  # noqa: BLE001
                continue
            self.transports.append(t)

    def close(self) -> None:
        self._stop = True
        for t in self.transports:
            t.close()
        self.sock.close()


_KEY_CACHE: dict[str, str] = {}


def _ed25519_file(root: str) -> str:
    """Ein fester Ed25519-Schlüssel für den Test-Server (außerhalb des freigegebenen Ordners)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    path = os.path.join(os.path.dirname(root), "hostkey")
    if not os.path.exists(path):
        key = ed25519.Ed25519PrivateKey.generate()
        with open(path, "wb") as fh:
            fh.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                       serialization.NoEncryption()))
    return path
