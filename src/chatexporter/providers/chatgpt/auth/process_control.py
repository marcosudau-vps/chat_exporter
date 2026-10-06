"""Browser gezielt schliessen und wieder oeffnen (Windows Restart Manager).

Fuer die Profilkopie muss der Browser, der GENAU dieses Datenverzeichnis
benutzt, geschlossen sein. Der Restart Manager liefert die Prozesse, die die
Sperrdatei ``<User Data>/lockfile`` offen halten, und schliesst nur diese:
erst regulaer (wie beim Abmelden von Windows), bei Bedarf erzwungen. Andere
Browser-Instanzen mit eigenem Datenverzeichnis (z. B. ein per CDP gesteuertes
Profil) bleiben unberuehrt. Danach startet der Restart Manager die Browser
wieder, die sich dafuer registriert haben; sonst (Edge/Chrome tun das nicht)
wird das Browser-Programm mit ``--restore-last-session`` gestartet, damit die
zuvor offenen Tabs wiederkommen, und – falls es nicht das Standard-
Datenverzeichnis ist – mit ``--user-data-dir``.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ERROR_MORE_DATA = 234
RM_FORCE_SHUTDOWN = 0x1


@dataclass(frozen=True)
class HoldingProcess:
    pid: int
    name: str
    restartable: bool


class RestartManagerError(OSError):
    pass


def _api():
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", FILETIME)]

    class RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [("Process", RM_UNIQUE_PROCESS), ("strAppName", wintypes.WCHAR * 256),
                    ("strServiceShortName", wintypes.WCHAR * 64), ("ApplicationType", ctypes.c_int),
                    ("AppStatus", wintypes.ULONG), ("TSSessionId", wintypes.DWORD),
                    ("bRestartable", wintypes.BOOL)]

    rm = ctypes.WinDLL("rstrtmgr")
    rm.RmStartSession.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR]
    rm.RmRegisterResources.argtypes = [wintypes.DWORD, wintypes.UINT, ctypes.POINTER(wintypes.LPCWSTR),
                                       wintypes.UINT, ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p]
    rm.RmGetList.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT),
                             ctypes.POINTER(RM_PROCESS_INFO), ctypes.POINTER(wintypes.DWORD)]
    rm.RmShutdown.argtypes = [wintypes.DWORD, wintypes.ULONG, ctypes.c_void_p]
    rm.RmRestart.argtypes = [wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    rm.RmEndSession.argtypes = [wintypes.DWORD]
    for func in (rm.RmStartSession, rm.RmRegisterResources, rm.RmGetList, rm.RmShutdown, rm.RmRestart,
                 rm.RmEndSession):
        func.restype = wintypes.DWORD
    return ctypes, wintypes, rm, RM_PROCESS_INFO


class RestartManagerSession:
    """Eine Restart-Manager-Sitzung fuer eine Datei (Kontextmanager)."""

    def __init__(self, path: Path):
        if sys.platform != "win32":
            raise RestartManagerError("Restart Manager gibt es nur unter Windows")
        self.ctypes, self.wintypes, self.rm, self._info = _api()
        self.handle = self.wintypes.DWORD()
        key = self.ctypes.create_unicode_buffer(33)
        self._check(self.rm.RmStartSession(self.ctypes.byref(self.handle), 0, key), "RmStartSession")
        files = (self.wintypes.LPCWSTR * 1)(str(path))
        self._check(self.rm.RmRegisterResources(self.handle, 1, files, 0, None, 0, None), "RmRegisterResources")

    @staticmethod
    def _check(code: int, what: str) -> None:
        if code:
            raise RestartManagerError(code, f"{what} fehlgeschlagen (Fehler {code})")

    def processes(self) -> list[HoldingProcess]:
        ctypes, wintypes = self.ctypes, self.wintypes
        needed, count, reasons = wintypes.UINT(0), wintypes.UINT(0), wintypes.DWORD(0)
        for _attempt in range(5):
            buffer = (self._info * max(needed.value, 1))()
            count.value = len(buffer)
            code = self.rm.RmGetList(self.handle, ctypes.byref(needed), ctypes.byref(count), buffer,
                                     ctypes.byref(reasons))
            if code == ERROR_MORE_DATA:
                continue
            self._check(code, "RmGetList")
            return [HoldingProcess(int(buffer[i].Process.dwProcessId), buffer[i].strAppName,
                                   bool(buffer[i].bRestartable)) for i in range(count.value)]
        raise RestartManagerError(ERROR_MORE_DATA, "RmGetList: Liste aendert sich staendig")

    def shutdown(self, *, force: bool = False) -> None:
        self._check(self.rm.RmShutdown(self.handle, RM_FORCE_SHUTDOWN if force else 0, None), "RmShutdown")

    def restart(self) -> None:
        self._check(self.rm.RmRestart(self.handle, 0, None), "RmRestart")

    def close(self) -> None:
        if self.handle is not None:
            self.rm.RmEndSession(self.handle)
            self.handle = None

    def __enter__(self) -> "RestartManagerSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


@dataclass
class ClosedBrowser:
    """Ergebnis von ``close_browser``: wieder oeffnen mit ``reopen()``."""

    session: RestartManagerSession | None
    executable: Path | None
    processes: list[HoldingProcess] = field(default_factory=list)
    forced: bool = False
    user_data_dir: Path | None = None
    launcher: Callable[[list[str]], None] | None = None

    def reopen_command(self) -> list[str]:
        from chatexporter.providers.chatgpt.auth.browsers import is_default_user_data_dir
        command = [str(self.executable), "--restore-last-session"]
        if self.user_data_dir is not None and not is_default_user_data_dir(self.user_data_dir):
            command.append(f"--user-data-dir={self.user_data_dir}")
        return command

    def reopen(self, say: Callable[[str], None] = lambda _m: None) -> str:
        """Browser wieder starten. Rueckgabe: wie (``restart``/``started``/``none``)."""
        how = "none"
        try:
            if self.session is not None and any(p.restartable for p in self.processes):
                self.session.restart()
                how = "restart"
        except OSError as exc:
            say(f"  Wiederherstellen ueber den Restart Manager nicht moeglich ({exc}).")
        if how == "none" and self.executable is not None and self.processes:
            (self.launcher or _launch_detached)(self.reopen_command())
            how = "started"
        if self.session is not None:
            self.session.close()
        return how


def _launch_detached(command: list[str]) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(command, close_fds=True, creationflags=flags)


def close_browser(user_data_dir: Path, executable: Path | None, *, say: Callable[[str], None] = lambda _m: None,
                  in_use: Callable[[Path], bool] | None = None, graceful_seconds: float = 20.0,
                  force_seconds: float = 10.0, graceful: bool = True) -> ClosedBrowser:
    """Schliesst genau die Prozesse, die ``<user_data_dir>/lockfile`` halten.

    Erst regulaer, nach ``graceful_seconds`` erzwungen (``graceful=False``: sofort erzwungen). Wirft ``RestartManagerError``,
    wenn das Datenverzeichnis danach noch in Benutzung ist.
    """
    if in_use is None:
        from chatexporter.providers.chatgpt.auth.browsers import profile_in_use as in_use
    lock = Path(user_data_dir) / "lockfile"
    if not in_use(user_data_dir):
        return ClosedBrowser(None, executable, user_data_dir=Path(user_data_dir))
    session = RestartManagerSession(lock)
    try:
        holders = session.processes()
        say("  Schliesse: " + (", ".join(f"{p.name} (PID {p.pid})" for p in holders) or "unbekannter Prozess"))
        forced = False
        if graceful:
            try:
                session.shutdown(force=False)
            except RestartManagerError as exc:
                say(f"  Regulaeres Schliessen nicht vollstaendig ({exc}); warte ...")
        if not graceful or not _wait_free(user_data_dir, in_use, graceful_seconds):
            say("  Browser reagiert nicht – wird beendet.")
            forced = True
            session.shutdown(force=True)
            if not _wait_free(user_data_dir, in_use, force_seconds):
                raise RestartManagerError(0, "Browser liess sich nicht schliessen")
        return ClosedBrowser(session, executable, holders, forced, user_data_dir=Path(user_data_dir))
    except BaseException:
        session.close()
        raise


def _wait_free(user_data_dir: Path, in_use: Callable[[Path], bool], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not in_use(user_data_dir):
            return True
        time.sleep(0.5)
    return not in_use(user_data_dir)
