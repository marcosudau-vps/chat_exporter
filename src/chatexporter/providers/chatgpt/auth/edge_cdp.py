from __future__ import annotations
import logging
import os
import subprocess
import json
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from chatexporter.providers.chatgpt.config.models import BrowserConfig
from chatexporter.providers.chatgpt.auth.browsers import (CDP_SIGNATURES, LABELS, common_executables,
                                                          find_executable, profile_in_use)


COMMON_EDGE_PATHS = common_executables("edge")


#: Leere Startseiten, die beim Oeffnen von ChatGPT wiederverwendet werden (kein zusaetzlicher Tab).
BLANK_PAGES = ("about:blank", "chrome://newtab/", "edge://newtab/", "chrome://new-tab-page/")

#: Edge meldet ein neues Profil sonst still mit dem Microsoft-Konto von Windows an und holt per
#: Synchronisierung Daten und Erweiterungen (gemessen 2026-10-04: Konto verbunden, 11 Erweiterungen,
#: Fenster „Wir synchronisieren Ihre Daten …“). Mit dieser Option und ``--disable-sync``: kein Konto,
#: keine Synchronisierung, nur die 3 eingebauten Erweiterungen. ``msEdgeImplicitSignin`` wirkte nicht.
IMPLICIT_SIGNIN_OFF = {"edge": ("--disable-features=msImplicitSignin",)}


#: Fenster "offscreen": weit ausserhalb jedes Bildschirms (Windows legt minimierte Fenster selbst
#: bei -32000 ab). Gemessen 2026-10-04 (lokale Nachbildung der Anmeldung, Edge): kein Aufblitzen beim
#: Start, Anmeldung in rund 2 s; minimiert rund 6 s, die Optionen gegen das Bremsen
#: (--disable-background-timer-throttling usw.) aenderten daran nichts.
OFFSCREEN = -32000
#: Lage, an der das Fenster gezeigt wird, wenn der Benutzer etwas tun muss.
VISIBLE_BOUNDS = {"left": 80, "top": 60, "width": 1200, "height": 900}


class BrowserLaunchError(RuntimeError):
    """Browser konnte nicht gestartet oder nicht per CDP erreicht werden."""


def detect_browser_executable(kind: str, configured: Path | None = None) -> Path:
    found = find_executable(kind, configured)
    if found is None:
        if configured is not None:
            raise FileNotFoundError(f"Browser-Programm nicht gefunden: {configured}")
        raise FileNotFoundError(f"{LABELS.get(kind, kind)} nicht gefunden. "
                                "providers.chatgpt.browser.executable setzen.")
    return found


def detect_edge_executable(configured: Path | None = None) -> Path:
    return detect_browser_executable("edge", configured)


def _cdp_version(endpoint: str) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(endpoint.rstrip("/") + "/json/version", timeout=0.35) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _cdp_endpoint_reachable(endpoint: str) -> bool:
    return _cdp_version(endpoint) is not None


def _assert_endpoint(endpoint: str, kind: str = "edge") -> None:
    """Der CDP-Port muss zum erwarteten Browser gehoeren (sonst ist er fremd belegt)."""
    version = _cdp_version(endpoint)
    if version is None:
        raise BrowserLaunchError(f"CDP-Endpunkt nicht erreichbar: {endpoint}")
    browser_name = str(version.get("Browser") or "")
    signatures = CDP_SIGNATURES.get(kind, ("Edg/",))
    if kind != "edge" and browser_name.startswith("Edg/"):
        raise BrowserLaunchError(f"CDP-Port {endpoint} ist von Edge belegt, erwartet: {LABELS.get(kind, kind)}")
    if not browser_name.startswith(signatures):
        raise BrowserLaunchError(f"CDP-Port {endpoint} ist von einem anderen Browser belegt: "
                                 f"{browser_name or 'unbekannt'}")


_assert_edge_endpoint = _assert_endpoint


class _ClosedFutureFilter(logging.Filter):
    """Unterdrueckt NUR asyncios Meldung "Future exception was never retrieved"
    fuer TargetClosedError nach dem Trennen der Playwright-Verbindung."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = str(record.msg)
        # Variante 2: die beim Abbruch offene Playwright-Anfrage als Task.
        if message.startswith("Task was destroyed but it is pending!"):
            return "playwright" not in message
        if not message.startswith("Future exception was never retrieved"):
            return True
        exc = record.exc_info[1] if record.exc_info else None
        text = f"{type(exc).__name__}: {exc}" if exc is not None else record.getMessage()
        return not ("TargetClosedError" in text or "has been closed" in text)


def _install_closed_future_filter() -> None:
    logger = logging.getLogger("asyncio")
    if not any(isinstance(f, _ClosedFutureFilter) for f in logger.filters):
        logger.addFilter(_ClosedFutureFilter())


class EdgeCdpSession:
    """Playwright-Verbindung per CDP zu Edge, Chrome oder Chrome for Testing.

    Startet den Browser bei Bedarf selbst; schliesst ihn beim normalen Ende nur,
    wenn ``leave_browser_running`` aus ist. Scheitert der Aufbau, wird ein selbst
    gestarteter Browser immer wieder beendet.
    """
    def __init__(self, config: BrowserConfig):
        self.config = config
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.started_process: subprocess.Popen | None = None
        #: True, sobald wir den Browser selbst gestartet haben (auch wenn der
        #: gestartete Prozess nur ein Zwischenprozess war, der sich neu startet).
        self.launched = False
        #: True, solange wir das Fenster verborgen halten (ausserhalb des Bildschirms oder minimiert).
        self.hidden = False

    @property
    def started_by_us(self) -> bool:
        return self.launched

    def connect(self) -> "EdgeCdpSession":
        endpoint = self.config.cdp_endpoint
        try:
            if not _cdp_endpoint_reachable(endpoint):
                if not self.config.launch_if_needed:
                    raise BrowserLaunchError(f"CDP-Endpunkt nicht erreichbar: {endpoint} "
                                             "(launch_if_needed ist aus)")
                self._launch_browser()
            _assert_endpoint(endpoint, self.config.kind)
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.connect_over_cdp(
                endpoint, timeout=self.config.connect_timeout_ms
            )
            if not self.browser.contexts:
                raise BrowserLaunchError("Per CDP verbunden, aber der Browser liefert keinen BrowserContext")
            self.context = self.browser.contexts[0]
            self.page = self._find_or_open_chatgpt_page()
            if self.launched and self.config.window == "minimized":
                self.hidden = self._set_window({"windowState": "minimized"})
        except BaseException:
            # Nichts halb Geoeffnetes zuruecklassen: Verbindung trennen und einen
            # selbst gestarteten Browser wieder beenden.
            self.abandon()
            raise
        return self

    def abandon(self) -> None:
        """Verbindung trennen und einen von uns gestarteten Browser beenden (Fehlerfall)."""
        if self.launched:
            self._close_launched_browser()
        if self.playwright is not None:
            _install_closed_future_filter()
            try:
                self.playwright.stop()
            except Exception:  # noqa: BLE001
                pass
            self.playwright = None
        self._terminate_started()

    def _close_launched_browser(self) -> None:
        """Einen selbst gestarteten Browser ueber CDP schliessen (``Browser.close``).

        Noetig, weil Edge/Chrome sich beim Start ueber einen Zwischenprozess neu
        starten koennen: der von uns gestartete Prozess ist dann schon beendet,
        der eigentliche Browser laeuft aber weiter. Nur fuer Browser, die wir
        selbst gestartet haben -- nie fuer einen bereits laufenden.
        """
        endpoint = self.config.cdp_endpoint
        if not _cdp_endpoint_reachable(endpoint):
            return
        own = self.playwright is None
        playwright = sync_playwright().start() if own else self.playwright
        try:
            browser = self.browser
            if browser is None or own:
                browser = playwright.chromium.connect_over_cdp(endpoint, timeout=self.config.connect_timeout_ms)
            browser.new_browser_cdp_session().send("Browser.close")
        except Exception:  # noqa: BLE001  der Browser kann beim Schliessen die Verbindung schon trennen
            pass
        finally:
            if own:
                _install_closed_future_filter()
                try:
                    playwright.stop()
                except Exception:  # noqa: BLE001
                    pass
        import time
        for _ in range(40):                      # bis zu ~10 s auf das Ende warten
            if not _cdp_endpoint_reachable(endpoint):
                break
            time.sleep(0.25)
        self.browser = None
        self.context = None
        self.launched = False

    def _terminate_started(self) -> None:
        process = self.started_process
        self.started_process = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:  # noqa: BLE001
            try:
                process.kill()
            except Exception:  # noqa: BLE001
                pass

    def _launch_browser(self) -> None:
        kind = self.config.kind
        configured = self.config.executable or (self.config.edge_executable if kind == "edge" else None)
        exe = detect_browser_executable(kind, configured)
        if profile_in_use(self.config.user_data_dir):
            raise BrowserLaunchError(
                f"{LABELS.get(kind, kind)} laeuft bereits mit dem Profil {self.config.user_data_dir}; "
                "ein zweiter Start mit Fernsteuerung (CDP) ist dann nicht moeglich. "
                "Den Browser schliessen oder ein anderes Profil verwenden.")
        self.config.user_data_dir.mkdir(parents=True, exist_ok=True)
        args = [
            str(exe),
            f"--remote-debugging-address={self.config.cdp_host}",
            f"--remote-debugging-port={self.config.cdp_port}",
            f"--user-data-dir={self.config.user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            # Profil nie mit einem Konto synchronisieren (Daten, Passwoerter, Erweiterungen).
            "--disable-sync",
            *IMPLICIT_SIGNIN_OFF.get(kind, ()),
            # Verborgen starten (kein Aufblitzen); gezeigt wird nur, wenn eine Eingabe noetig ist.
            *((f"--window-position={OFFSCREEN},{OFFSCREEN}",) if self.config.window == "offscreen" else ()),
            # Leer starten, ChatGPT erst nach dem Verbinden oeffnen: Mit ChatGPT als
            # Startseite blieb die CDP-Verbindung bei Chrome for Testing haengen
            # (Playwright connect_over_cdp ohne Antwort; leer gestartet: 0,5 s).
            "about:blank",
        ]
        creationflags = 0
        if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        self.launched = True
        self.hidden = self.config.window == "offscreen"
        self.started_process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._wait_until_cdp_reachable()

    _launch_edge = _launch_browser

    def _wait_until_cdp_reachable(self) -> None:
        # State-based startup wait: success is only the observable CDP endpoint.
        # The bounded process wait is a watchdog/action budget, never a semantic
        # "browser is ready after N ms" assumption.
        assert self.started_process is not None
        slice_seconds = 0.25
        attempts = max(1, self.config.connect_timeout_ms // 250)
        for _ in range(attempts):
            if _cdp_endpoint_reachable(self.config.cdp_endpoint):
                return
            code = self.started_process.poll()
            if code is not None and code != 0:
                raise BrowserLaunchError(f"Browser beendet, bevor CDP erreichbar war (Exitcode {code})")
            if code is None:
                try:
                    self.started_process.wait(timeout=slice_seconds)
                except subprocess.TimeoutExpired:
                    pass
            else:
                # Exitcode 0: Zwischenprozess hat den eigentlichen Browser gestartet;
                # weiter auf den CDP-Endpunkt warten.
                import time
                time.sleep(slice_seconds)
        if not _cdp_endpoint_reachable(self.config.cdp_endpoint):
            raise BrowserLaunchError(f"CDP-Endpunkt wurde nicht erreichbar: {self.config.cdp_endpoint} "
                                     f"(nach {self.config.connect_timeout_ms} ms)")

    # -- Fenster: verborgen arbeiten, nur zum Eingeben zeigen ------------------------------------
    def _set_window(self, bounds: dict[str, Any]) -> bool:
        """Fensterlage/-zustand per CDP setzen. Scheitert nie laut (das Fenster ist nur Komfort)."""
        if self.browser is None or self.context is None or self.page is None:
            return False
        page_session = None
        try:
            page_session = self.context.new_cdp_session(self.page)
            target = page_session.send("Target.getTargetInfo")["targetInfo"]["targetId"]
            browser_session = self.browser.new_browser_cdp_session()
            window = browser_session.send("Browser.getWindowForTarget", {"targetId": target})["windowId"]
            browser_session.send("Browser.setWindowBounds", {"windowId": window, "bounds": bounds})
            return True
        except Exception:  # noqa: BLE001
            return False
        finally:
            if page_session is not None:
                try:
                    page_session.detach()
                except Exception:  # noqa: BLE001
                    pass

    def show_window(self) -> bool:
        """Fenster zeigen, weil der Benutzer etwas tun muss (Anmeldung, Sicherheitspruefung)."""
        ok = self._set_window({"windowState": "normal"})
        if self.hidden:
            ok = self._set_window(dict(VISIBLE_BOUNDS)) and ok
            self.hidden = not ok
        try:
            if self.page is not None:
                self.page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass
        return ok

    def hide_window(self) -> bool:
        """Wieder verbergen – nur einen selbst gestarteten Browser und nur, wenn so eingestellt."""
        if not self.launched or self.config.window not in ("offscreen", "minimized") or self.hidden:
            return False
        if self.config.window == "minimized":
            ok = self._set_window({"windowState": "minimized"})
        else:
            ok = (self._set_window({"windowState": "normal"})
                  and self._set_window({"left": OFFSCREEN, "top": OFFSCREEN}))
        self.hidden = ok
        return ok

    def _park_window(self) -> None:
        """Bleibt der Browser nach dem Lauf offen, nie unsichtbar zuruecklassen: sichtbare Lage, minimiert."""
        if self.hidden and self._set_window({"windowState": "normal"}):
            self._set_window(dict(VISIBLE_BOUNDS))
            self._set_window({"windowState": "minimized"})
            self.hidden = False

    def ensure_chatgpt_page(self):
        self.page = self._find_or_open_chatgpt_page()
        return self.page

    def _find_or_open_chatgpt_page(self):
        assert self.context is not None
        blank = None
        for page in self.context.pages:
            host = (urlsplit(page.url).hostname or "").lower()
            if host == "chatgpt.com" or host.endswith(".chatgpt.com"):
                return page
            if blank is None and page.url in BLANK_PAGES:
                blank = page
        page = blank or self.context.new_page()
        page.goto(self.config.open_url, wait_until="domcontentloaded", timeout=self.config.connect_timeout_ms)
        return page

    def close(self) -> None:
        # Do not call browser.close(): over CDP that can close the real browser.
        if self.config.leave_browser_running and self.launched:
            self._park_window()
        if self.playwright is not None:
            # Nach einem Abbruch (Strg+C) kann noch eine Anfrage offen sein; sie
            # scheitert beim Trennen mit TargetClosedError, und asyncio meldet
            # das spaeter als "Future exception was never retrieved". Das ist
            # erwartbar und harmlos -- nur genau diese Meldung wird unterdrueckt.
            _install_closed_future_filter()
            self.playwright.stop()
            self.playwright = None
        if not self.config.leave_browser_running and self.launched:
            self._close_launched_browser()
            self._terminate_started()

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc, tb):
        self.close()


BrowserCdpSession = EdgeCdpSession
