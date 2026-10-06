"""Browser auf dem Rechner erkennen: Programme, Standardprofile, Version, Belegung.

Reine Erkennung ohne Seiteneffekte (nichts wird gestartet). Grundlage der
automatischen Profilsuche in ``browser_setup.py``; Profile, ChatGPT-Cookies und
Profilkopien liegen in ``profiles.py``.
"""

from __future__ import annotations

import os
import re
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

KINDS = ("edge", "chrome", "chrome_for_testing")
LABELS = {"edge": "Microsoft Edge", "chrome": "Google Chrome", "chrome_for_testing": "Chrome for Testing"}
#: Kennung im CDP-Endpunkt ``/json/version`` (Feld ``Browser``).
CDP_SIGNATURES = {"edge": ("Edg/",), "chrome": ("Chrome/",), "chrome_for_testing": ("Chrome/",)}
#: Ab dieser Hauptversion ignoriert Chrome die Fernsteuerung (CDP) fuer das
#: Standard-Datenverzeichnis (Sicherheitsaenderung von Chrome 136).
CHROME_DEFAULT_PROFILE_CDP_LIMIT = 136

_VERSION_DIR = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    return Path(value) if value else None


def common_executables(kind: str) -> list[Path]:
    program_files = [p for p in (_env_path("PROGRAMFILES(X86)"), _env_path("PROGRAMFILES"),
                                 Path(r"C:\Program Files (x86)"), Path(r"C:\Program Files")) if p]
    local = _env_path("LOCALAPPDATA")
    if kind == "edge":
        out = [base / "Microsoft" / "Edge" / "Application" / "msedge.exe" for base in program_files]
        if local:
            out.append(local / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    elif kind == "chrome":
        out = [base / "Google" / "Chrome" / "Application" / "chrome.exe" for base in program_files]
        if local:
            out.append(local / "Google" / "Chrome" / "Application" / "chrome.exe")
    else:
        out = []
    seen: list[Path] = []
    for path in out:
        if path not in seen:
            seen.append(path)
    return seen


def _app_path(exe_name: str) -> Path | None:
    """Eintrag ``App Paths`` der Registry (HKCU, dann HKLM)."""
    if sys.platform != "win32":
        return None
    import winreg
    sub = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, sub) as key:
                value = winreg.QueryValueEx(key, None)[0]
        except OSError:
            continue
        if value:
            path = Path(str(value).strip('"'))
            if path.is_file():
                return path
    return None


def find_executable(kind: str, configured: Path | None = None) -> Path | None:
    """Programmdatei eines installierten Browsers (oder der angegebene Pfad)."""
    if configured is not None:
        return configured if Path(configured).is_file() else None
    for path in common_executables(kind):
        if path.is_file():
            return path
    if kind in ("edge", "chrome"):
        return _app_path("msedge.exe" if kind == "edge" else "chrome.exe")
    return None


def default_user_data_dir(kind: str) -> Path | None:
    local = _env_path("LOCALAPPDATA")
    if local is None:
        return None
    if kind == "edge":
        return local / "Microsoft" / "Edge" / "User Data"
    if kind == "chrome":
        return local / "Google" / "Chrome" / "User Data"
    return None


def is_default_user_data_dir(path: Path) -> bool:
    try:
        resolved = os.path.normcase(str(Path(path).expanduser().resolve()))
    except OSError:
        return False
    for kind in ("edge", "chrome"):
        default = default_user_data_dir(kind)
        if default is not None and resolved == os.path.normcase(str(default.resolve())):
            return True
    return False


def browser_version(executable: Path) -> tuple[int, ...] | None:
    """Version aus dem Versionsordner neben dem Programm (``Application/<x.y.z.w>``)."""
    folder = Path(executable).parent
    try:
        versions = [tuple(int(p) for p in entry.name.split("."))
                    for entry in folder.iterdir() if entry.is_dir() and _VERSION_DIR.match(entry.name)]
    except OSError:
        return None
    return max(versions) if versions else None


def profile_in_use(user_data_dir: Path) -> bool:
    """Laeuft ein Browser mit diesem Datenverzeichnis? (Windows: ``lockfile`` ist exklusiv geoeffnet)."""
    lock = Path(user_data_dir) / "lockfile"
    if sys.platform != "win32" or not lock.exists():
        return False
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    generic_read, open_existing, normal = 0x80000000, 3, 0x80
    handle = kernel32.CreateFileW(str(lock), generic_read, 0, None, open_existing, normal, None)
    if handle == wintypes.HANDLE(-1).value:
        return ctypes.get_last_error() in (32, 33)   # Freigabe-/Sperrverletzung = in Benutzung
    kernel32.CloseHandle(handle)
    return False


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        return probe.connect_ex((host, port)) != 0


def find_free_port(host: str, start: int, span: int = 50,
                   is_free: Callable[[str, int], bool] = port_free) -> int | None:
    for port in range(start, start + span):
        if is_free(host, port):
            return port
    return None


@dataclass(frozen=True)
class BrowserCandidate:
    """Ein moeglicher Weg: Browser-Art, Programm, Datenverzeichnis."""

    key: str
    kind: str
    executable: Path | None
    user_data_dir: Path
    #: Programm muss erst heruntergeladen werden (Chrome for Testing).
    download: bool = False
    #: Profil des installierten Browsers, von dem zuerst eine Kopie anzulegen ist
    #: (``profiles.BrowserProfile``); ``user_data_dir`` ist dann das Kopie-Ziel.
    copy_from: Any = field(default=None, compare=False)
    #: Anzeigename einer bereits vorhandenen Profilkopie.
    copy_name: str | None = None

    @property
    def label(self) -> str:
        if self.copy_from is not None:
            return f"{LABELS[self.kind]} (Kopie von Profil '{self.copy_from.name}' anlegen)"
        if self.copy_name is not None:
            return f"{LABELS[self.kind]} (Profilkopie '{self.copy_name}')"
        return f"{LABELS[self.kind]} (eigenes Profil)"


def build_candidates(browser_root: Path, *, installed_cft: Path | None = None,
                     find: Callable[[str], Path | None] = find_executable,
                     profiles: Callable[[str], list[Any]] | None = None,
                     copies: Callable[[Path], list[tuple[Path, dict]]] | None = None) -> list[BrowserCandidate]:
    """Reihenfolge der Suche (der erste funktionierende Weg gewinnt):

    1. vorhandene Profilkopien (Edge, Chrome; je Quellprofil die neueste),
    2. Kopie eines Edge-/Chrome-Profils anlegen, das ChatGPT-Cookies hat
       (oder dessen Cookies nicht lesbar sind, weil der Browser offen ist),
    3. Edge, dann Chrome mit eigenem, leerem Profil (Anmeldung noetig),
    4. Chrome for Testing (vorhanden oder nach Rueckfrage herunterladen) mit eigenem Profil.

    Standard-Datenverzeichnisse werden nie direkt verwendet: Ein offener Browser
    sperrt sie, und Chrome erlaubt dort ab Version 136 keine Fernsteuerung.
    """
    from chatexporter.providers.chatgpt.auth import profiles as profile_tools
    list_profiles = profiles or profile_tools.list_profiles
    list_copies = copies or profile_tools.existing_copies
    root = Path(browser_root)
    own = root / "profiles"
    out: list[BrowserCandidate] = []
    installed = {kind: find(kind) for kind in ("edge", "chrome")}
    copies = list_copies(root)
    used_sources: list[tuple[str, str]] = []
    for path, info in copies:                       # neueste zuerst; je Quelle nur die neueste
        kind = str(info.get("kind") or "")
        source = (kind, str(info.get("source") or path))
        if installed.get(kind) is None or source in used_sources:
            continue
        used_sources.append(source)
        out.append(BrowserCandidate(path.name, kind, installed[kind], path,
                                    copy_name=str(info.get("name") or info.get("directory") or path.name)))
    for kind in ("edge", "chrome"):
        if installed[kind] is None:
            continue
        for profile in list_profiles(kind):
            if profile.chatgpt is False or profile_tools.copy_of(copies, profile) is not None:
                continue
            # Ziel wird erst beim Kopieren festgelegt (Zeitstempel); hier nur Vorschau.
            out.append(BrowserCandidate(f"{kind}-{profile.directory.replace(' ', '_')}-kopieren", kind,
                                        installed[kind], profile_tools.copy_target(root, profile),
                                        copy_from=profile))
    for kind in ("edge", "chrome"):
        if installed[kind] is not None:
            out.append(BrowserCandidate(f"{kind}-profile", kind, installed[kind], own / kind))
    out.append(BrowserCandidate("chrome-for-testing", "chrome_for_testing", installed_cft,
                                own / "chrome_for_testing", download=installed_cft is None))
    return out


def describe(candidates: Iterable[BrowserCandidate]) -> list[str]:
    return [f"{c.key}: {c.label} – {c.executable or 'Download noetig'} – {c.user_data_dir}" for c in candidates]
