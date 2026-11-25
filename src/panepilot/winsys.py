"""Windows-Anbindung (v3.0): alles, was unter Windows über die System-Schnittstellen läuft.

Nur Standardbibliothek (ctypes, winreg) – keine Zusatzpakete. Unter Linux lässt sich das Modul importieren,
die Funktionen liefern dort leere bzw. neutrale Ergebnisse; die reinen Hilfen (z. B. ``parse_recycle_info``,
``attr_text``) sind überall testbar.
"""

from __future__ import annotations

import ctypes
import os
import struct
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

IS_WINDOWS = sys.platform.startswith("win")

# Dateiattribute (winnt.h)
READONLY, HIDDEN, SYSTEM, DIRECTORY, ARCHIVE = 0x1, 0x2, 0x4, 0x10, 0x20
EDITABLE_ATTRS = (READONLY, HIDDEN, ARCHIVE, SYSTEM)
ATTR_LETTERS = ((READONLY, "R"), (HIDDEN, "H"), (SYSTEM, "S"), (ARCHIVE, "A"))
INVALID_ATTRS = 0xFFFFFFFF

# Laufwerksarten (GetDriveTypeW)
DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_CDROM, DRIVE_RAMDISK = 2, 3, 4, 5, 6


def _wapi():
    return ctypes.windll if IS_WINDOWS else None  # type: ignore[attr-defined]


# --- Attribute ---------------------------------------------------------------------------------------------------
def attr_text(attrs: int) -> str:
    """Spalte „Attribute“ (L-4020): z. B. 'RHA'."""
    return "".join(ch for bit, ch in ATTR_LETTERS if attrs & bit)


def get_attrs(path: str) -> int:
    if not IS_WINDOWS:
        return 0
    try:
        return int(getattr(os.lstat(path), "st_file_attributes", 0))
    except OSError:
        return 0


def set_attrs(path: str, attrs: int) -> None:
    """Setzt Schreibgeschützt/Versteckt/Archiv/System; andere Bits bleiben, wie sie sind."""
    if not IS_WINDOWS:
        raise OSError("only on Windows")
    current = get_attrs(path)
    keep = current & ~(READONLY | HIDDEN | ARCHIVE | SYSTEM) & ~DIRECTORY
    value = keep | (attrs & (READONLY | HIDDEN | ARCHIVE | SYSTEM))
    if value == 0:
        value = 0x80  # FILE_ATTRIBUTE_NORMAL
    if not _wapi().kernel32.SetFileAttributesW(ctypes.c_wchar_p(path), ctypes.c_uint32(value)):
        raise ctypes.WinError()  # type: ignore[attr-defined]


def is_hidden(attrs: int) -> bool:
    return bool(attrs & HIDDEN)


def is_protected_system(attrs: int) -> bool:
    """Geschützte Systemdatei (L-4022): versteckt UND System, z. B. NTUSER.DAT, pagefile.sys."""
    return bool(attrs & HIDDEN) and bool(attrs & SYSTEM)


# --- Pfade für die Zwischenablage (L-4030) ----------------------------------------------------------------------
def short_path(path: str) -> str:
    """8.3-Kurzform, z. B. C:\\PROGRA~1\\…; ohne Kurzname der Pfad selbst."""
    if not IS_WINDOWS:
        return path
    buf = ctypes.create_unicode_buffer(32768)
    n = _wapi().kernel32.GetShortPathNameW(ctypes.c_wchar_p(path), buf, 32768)
    return buf.value if 0 < n < 32768 else path


def web_path(path: str) -> str:
    return path.replace("\\", "/")


def unc_path(path: str) -> str:
    """UNC-Form für Netzlaufwerke (Z:\\x → \\\\server\\freigabe\\x); lokale Pfade bleiben."""
    if path.startswith("\\\\") or not IS_WINDOWS:
        return path
    drive = os.path.splitdrive(path)[0]
    if not drive:
        return path
    buf = ctypes.create_unicode_buffer(1024)
    size = ctypes.c_uint32(1024)
    try:
        rc = _wapi().mpr.WNetGetConnectionW(ctypes.c_wchar_p(drive), buf, ctypes.byref(size))
    except (AttributeError, OSError):
        return path
    if rc != 0 or not buf.value:
        return path
    return buf.value.rstrip("\\") + path[len(drive):]


# --- Laufwerke (L-4012) ----------------------------------------------------------------------------------------
@dataclass
class Drive:
    root: str  # 'C:\\'
    label: str = ""
    kind: int = DRIVE_FIXED
    remote: str = ""  # bei Netzlaufwerken \\\\server\\freigabe

    @property
    def title(self) -> str:
        letter = self.root.rstrip("\\")
        name = self.label or (self.remote.rsplit("\\", 1)[-1] if self.remote else "")
        return f"{name} ({letter})" if name else letter


def drives() -> list[Drive]:
    from .platform import windows_drives

    out = []
    for root in windows_drives():
        d = Drive(root)
        if IS_WINDOWS:
            k32 = _wapi().kernel32
            d.kind = int(k32.GetDriveTypeW(ctypes.c_wchar_p(root)))
            if d.kind == DRIVE_REMOTE:
                d.remote = unc_path(root).rstrip("\\")
            if d.kind not in (DRIVE_REMOVABLE, DRIVE_CDROM) or os.path.exists(root):
                name = ctypes.create_unicode_buffer(261)
                old = k32.SetErrorMode(1)  # keine „Kein Datenträger“-Fenster
                try:
                    if k32.GetVolumeInformationW(ctypes.c_wchar_p(root), name, 261, None, None, None, None, 0):
                        d.label = name.value
                finally:
                    k32.SetErrorMode(old)
        out.append(d)
    return out


def connect_network_drive(hwnd: int = 0) -> bool:
    """L-4013: Windows-Fenster „Netzlaufwerk verbinden“; True, wenn verbunden wurde."""
    if not IS_WINDOWS:
        return False
    rc = _wapi().mpr.WNetConnectionDialog(ctypes.c_void_p(hwnd), 1)  # RESOURCETYPE_DISK
    return rc == 0


def disconnect_network_drive(hwnd: int = 0) -> bool:
    if not IS_WINDOWS:
        return False
    return _wapi().mpr.WNetDisconnectDialog(ctypes.c_void_p(hwnd), 1) == 0


# --- Papierkorb (L-4010) -----------------------------------------------------------------------------------------
_EPOCH_DIFF = 11644473600  # Sekunden zwischen 1601 und 1970


def filetime_to_ts(ft: int) -> float:
    return ft / 10_000_000 - _EPOCH_DIFF if ft else 0.0


@dataclass
class RecycleInfo:
    original: str
    size: int
    deleted: float


def parse_recycle_info(data: bytes) -> RecycleInfo | None:
    """$I-Datei: Version 1 (Vista–8.1, fester Pfad) oder 2 (Windows 10/11, Pfad mit Länge)."""
    if len(data) < 24:
        return None
    version, size, ft = struct.unpack_from("<qqq", data, 0)
    if version == 1:
        raw = data[24:24 + 520]
    elif version == 2:
        if len(data) < 28:
            return None
        (chars,) = struct.unpack_from("<I", data, 24)
        raw = data[28:28 + 2 * chars]
    else:
        return None
    try:
        path = raw.decode("utf-16-le").split("\x00", 1)[0]
    except UnicodeDecodeError:
        return None
    if not path:
        return None
    return RecycleInfo(path, max(size, 0), filetime_to_ts(ft))


def user_sid() -> str:
    """SID des angemeldeten Benutzers (S-1-5-21-…), leer, wenn unbekannt."""
    if not IS_WINDOWS:
        return ""
    from ctypes import wintypes

    advapi, k32 = ctypes.WinDLL("advapi32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(k32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        return ""
    try:
        size = wintypes.DWORD(0)
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        buf = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
            return ""
        sid_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
        text = ctypes.c_void_p()
        if not advapi.ConvertSidToStringSidW(ctypes.c_void_p(sid_ptr), ctypes.byref(text)):
            return ""
        try:
            return ctypes.wstring_at(text.value) if text.value else ""
        finally:
            k32.LocalFree(text)
    finally:
        k32.CloseHandle(token)


def recycle_dirs(sid: str | None = None) -> list[str]:
    """Die eigenen Papierkorb-Ordner aller Laufwerke (X:\\$Recycle.Bin\\<SID>)."""
    sid = user_sid() if sid is None else sid
    out = []
    for d in drives():
        if d.kind == DRIVE_REMOTE:
            continue  # Netzlaufwerke haben keinen Windows-Papierkorb
        folder = os.path.join(d.root, "$Recycle.Bin", sid) if sid else ""
        if folder and os.path.isdir(folder):
            out.append(folder)
    return out


def empty_recycle_bin() -> bool:
    if not IS_WINDOWS:
        return False
    flags = 0x1 | 0x2 | 0x4  # ohne Rückfrage, ohne Fortschritt, ohne Ton
    return _wapi().shell32.SHEmptyRecycleBinW(None, None, flags) in (0, -2147418113)  # S_OK / E_UNEXPECTED (leer)


# --- Passwörter: Windows-Anmeldeinformationsverwaltung (L-4023) -----------------------------------------------
class _CREDENTIAL(ctypes.Structure):
    _fields_ = [("Flags", ctypes.c_uint32), ("Type", ctypes.c_uint32), ("TargetName", ctypes.c_wchar_p),
                ("Comment", ctypes.c_wchar_p), ("LastWritten", ctypes.c_uint64),
                ("CredentialBlobSize", ctypes.c_uint32), ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
                ("Persist", ctypes.c_uint32), ("AttributeCount", ctypes.c_uint32), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", ctypes.c_wchar_p), ("UserName", ctypes.c_wchar_p)]


CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE = 1, 2


def cred_target(app: str, server_id: str, kind: str) -> str:
    return f"{app}:{kind}:{server_id}"


def _advapi():
    lib = ctypes.WinDLL("advapi32", use_last_error=True)
    lib.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), ctypes.c_uint32]
    lib.CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
                              ctypes.POINTER(ctypes.POINTER(_CREDENTIAL))]
    lib.CredDeleteW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32]
    lib.CredFree.argtypes = [ctypes.c_void_p]
    return lib


def cred_write(target: str, secret: str, label: str) -> bool:
    if not IS_WINDOWS:
        return False
    blob = secret.encode("utf-16-le")
    buf = ctypes.create_string_buffer(blob, len(blob) or 1)  # bleibt bis nach dem Aufruf erhalten
    cred = _CREDENTIAL()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.Comment = label
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = "PanePilot"
    return bool(_advapi().CredWriteW(ctypes.byref(cred), 0))


def cred_read(target: str) -> str | None:
    if not IS_WINDOWS:
        return None
    lib = _advapi()
    ptr = ctypes.POINTER(_CREDENTIAL)()
    if not lib.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(ptr)):
        return None
    try:
        cred = ptr.contents
        raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize) if cred.CredentialBlobSize else b""
        return raw.decode("utf-16-le")
    finally:
        lib.CredFree(ptr)


def cred_delete(target: str) -> None:
    if IS_WINDOWS:
        _advapi().CredDeleteW(target, CRED_TYPE_GENERIC, 0)


# --- „Öffnen mit“ (L-4011) -----------------------------------------------------------------------------------------
@dataclass
class WinApp:
    name: str
    command: str  # z. B. "C:\\Prog\\x.exe" "%1"
    exe: str = ""
    key: str = ""  # ProgID oder Applications\\x.exe (zum Entdoppeln)
    extra: dict = field(default_factory=dict)

    def qicon(self):
        from PySide6.QtCore import QFileInfo
        from PySide6.QtWidgets import QFileIconProvider

        if self.exe and os.path.exists(self.exe):
            return QFileIconProvider().icon(QFileInfo(self.exe))
        from PySide6.QtGui import QIcon

        return QIcon()


def split_command(command: str) -> list[str]:
    """Befehlszeile aus der Registry in Teile zerlegen (Anführungszeichen beachten)."""
    parts, cur, quoted = [], "", False
    for ch in command.strip():
        if ch == '"':
            quoted = not quoted
            continue
        if ch.isspace() and not quoted:
            if cur:
                parts.append(cur)
                cur = ""
            continue
        cur += ch
    if cur:
        parts.append(cur)
    return parts


def build_args(command: str, files: list[str]) -> list[list[str]]:
    """Programm-Aufrufe: %1/%L/%V je Datei, %* für alle; ohne Platzhalter wird die Datei angehängt."""
    parts = [os.path.expandvars(p) for p in split_command(command)]
    if not parts:
        return []
    if any("%*" in p for p in parts):
        out = []
        for p in parts:
            if p == "%*":
                out.extend(files)
            else:
                out.append(p.replace("%*", " ".join(files)))
        return [out]
    calls = []
    for f in files:
        args, used = [], False
        for p in parts:
            q = p
            for ph in ("%1", "%L", "%l", "%V", "%v"):
                if ph in q:
                    q = q.replace(ph, f)
                    used = True
            if q.startswith("%") and len(q) == 2 and q[1].isdigit():
                continue  # %2 … ohne Wert weglassen
            args.append(q)
        if not used:
            args.append(f)
        calls.append(args)
    return calls


def _reg_value(root, path: str, name: str = "") -> str:
    import winreg

    try:
        with winreg.OpenKey(root, path) as key:
            value, _kind = winreg.QueryValueEx(key, name)
            return str(value) if value is not None else ""
    except OSError:
        return ""


def _reg_names(root, path: str, values: bool = False) -> list[str]:
    import winreg

    out = []
    try:
        with winreg.OpenKey(root, path) as key:
            i = 0
            while True:
                try:
                    name = winreg.EnumValue(key, i)[0] if values else winreg.EnumKey(key, i)
                except OSError:
                    break
                out.append(name)
                i += 1
    except OSError:
        pass
    return out


def _friendly(name_or_ref: str) -> str:
    """'@%SystemRoot%\\system32\\shell32.dll,-22072' → lesbarer Text (SHLoadIndirectString)."""
    if not name_or_ref.startswith("@") or not IS_WINDOWS:
        return name_or_ref
    buf = ctypes.create_unicode_buffer(512)
    if _wapi().shlwapi.SHLoadIndirectString(ctypes.c_wchar_p(name_or_ref), buf, 512, None) == 0:
        return buf.value
    return ""


def _exe_of(command: str) -> str:
    parts = split_command(command)
    return os.path.expandvars(parts[0]) if parts else ""


def _app_from_progid(progid: str) -> WinApp | None:
    import winreg

    hkcr = winreg.HKEY_CLASSES_ROOT
    command = _reg_value(hkcr, rf"{progid}\shell\open\command")
    if not command:
        verb = _reg_value(hkcr, rf"{progid}\shell")
        if verb:
            command = _reg_value(hkcr, rf"{progid}\shell\{verb}\command")
    if not command:
        return None
    exe = _exe_of(command)
    name = (_friendly(_reg_value(hkcr, rf"{progid}\Application", "ApplicationName"))
            or _friendly(_reg_value(hkcr, progid, "FriendlyTypeName")) or "")
    if not name or name == progid:
        name = _exe_display_name(exe) or progid
    return WinApp(name, command, exe, progid)


def _app_from_exe(exe_name: str) -> WinApp | None:
    import winreg

    hkcr = winreg.HKEY_CLASSES_ROOT
    base = rf"Applications\{exe_name}"
    command = _reg_value(hkcr, rf"{base}\shell\open\command") or _reg_value(hkcr, rf"{base}\shell\edit\command")
    if not command:
        return None
    exe = _exe_of(command)
    name = _friendly(_reg_value(hkcr, base, "FriendlyAppName")) or _exe_display_name(exe) or exe_name
    return WinApp(name, command, exe, base)


def _exe_display_name(exe: str) -> str:
    """Produktname aus der Programmdatei (FileDescription), sonst der Dateiname ohne .exe."""
    if not exe:
        return ""
    if IS_WINDOWS and os.path.exists(exe):
        try:
            ver = _wapi().version
            size = ver.GetFileVersionInfoSizeW(ctypes.c_wchar_p(exe), None)
            if size:
                buf = ctypes.create_string_buffer(size)
                if ver.GetFileVersionInfoW(ctypes.c_wchar_p(exe), 0, size, buf):
                    lp = ctypes.c_void_p()
                    n = ctypes.c_uint()
                    if ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(lp), ctypes.byref(n)) \
                            and n.value >= 4:
                        lang, cp = struct.unpack("<HH", ctypes.string_at(lp, 4))
                        sub = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\FileDescription"
                        if ver.VerQueryValueW(buf, sub, ctypes.byref(lp), ctypes.byref(n)) and n.value:
                            text = ctypes.wstring_at(lp, n.value).rstrip("\x00").strip()
                            if text:
                                return text
        except (AttributeError, OSError):
            pass
    return os.path.splitext(os.path.basename(exe))[0]


def apps_for(path: str, limit: int = 15) -> list[WinApp]:
    """Für den Dateityp registrierte Programme: Standard zuerst, dann „Öffnen mit“-Listen."""
    if not IS_WINDOWS:
        return []
    import winreg

    ext = os.path.splitext(path)[1].lower()
    if not ext:
        return []
    hkcr, hkcu = winreg.HKEY_CLASSES_ROOT, winreg.HKEY_CURRENT_USER
    exts = rf"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\{ext}"
    progids: list[str] = []
    user_choice = _reg_value(hkcu, rf"{exts}\UserChoice", "ProgId")
    for p in [user_choice, _reg_value(hkcr, ext)] + _reg_names(hkcr, rf"{ext}\OpenWithProgids", values=True) \
            + _reg_names(hkcu, rf"{exts}\OpenWithProgids", values=True):
        if p and p not in progids:
            progids.append(p)
    exes: list[str] = []
    mru = _reg_value(hkcu, rf"{exts}\OpenWithList", "MRUList")
    for letter in mru:
        e = _reg_value(hkcu, rf"{exts}\OpenWithList", letter)
        if e and e.lower() not in [x.lower() for x in exes]:
            exes.append(e)
    for e in _reg_names(hkcr, rf"{ext}\OpenWithList"):
        if e.lower() not in [x.lower() for x in exes]:
            exes.append(e)
    out: list[WinApp] = []
    seen: set[str] = set()
    for app in [_app_from_progid(p) for p in progids] + [_app_from_exe(e) for e in exes]:
        if app is None:
            continue
        key = (app.exe or app.command).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(app)
        if len(out) >= limit:
            break
    return out


def launch(app: WinApp, files: list[str]) -> bool:
    import subprocess

    ok = True
    for args in build_args(app.command, files):
        try:
            subprocess.Popen(args, cwd=os.path.dirname(files[0]) or None,
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        except OSError:
            ok = False
    return ok


def open_as_dialog(path: str) -> bool:
    """„Andere App …“: das Windows-Fenster „Öffnen mit“."""
    import subprocess

    try:
        subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", path])
        return True
    except OSError:
        return False


# --- Terminal (L-4024) ---------------------------------------------------------------------------------------------
def terminal_command(choice: str, folder: str, custom: str = "") -> list[str] | None:
    """Aufruf für „Terminal hier öffnen“; None, wenn nichts passt."""
    import shutil

    if choice == "custom":
        if not custom.strip():
            return None
        return [p.replace("{folder}", folder) for p in split_command(custom)]
    wt = shutil.which("wt") or shutil.which("wt.exe")
    pwsh = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
    if choice in ("auto", "wt") and wt:
        return [wt, "-d", folder]
    if choice == "wt":
        return None
    if choice == "cmd":
        return ["cmd.exe", "/K", "cd", "/d", folder]
    return [pwsh, "-NoExit", "-Command", f"Set-Location -LiteralPath '{folder.replace(chr(39), chr(39) * 2)}'"]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
