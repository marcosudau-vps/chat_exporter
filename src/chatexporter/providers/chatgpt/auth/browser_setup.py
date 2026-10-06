"""Browser und Profil fuer ChatGPT bestimmen, anmelden, Ergebnis merken.

Ist ``providers.chatgpt.browser.user_data_dir`` gesetzt, wird genau dieses
Profil verwendet (fester Pfad). Sonst werden die Wege der Reihe nach versucht;
der erste, der funktioniert UND eine ChatGPT-Anmeldung hat, gewinnt
(``browsers.build_candidates``):

1. vorhandene Profilkopie (Edge, Chrome)
2. Kopie eines Edge-/Chrome-Profils mit ChatGPT-Cookies anlegen – nur interaktiv
   und nach Bestaetigung; ein geoeffneter Browser wird dafuer automatisch
   geschlossen und danach wieder geoeffnet (``process_control``)
3. Edge, dann Chrome mit eigenem, leerem Profil
4. Chrome for Testing (vorhanden oder nach Rueckfrage herunterladen), eigenes Profil

Mit einer Kopie laeuft der Abruf, waehrend der normale Browser offen ist; das
Standardprofil selbst wird nie ferngesteuert.

„Funktioniert“ heisst: Browser startet (oder laeuft schon) und ist per CDP
erreichbar. Fehlt in einem Profil die ChatGPT-Anmeldung, wird bei einem
interaktiven Start zur Anmeldung aufgefordert; ohne Interaktion gilt der Weg als
gescheitert und es geht mit dem naechsten weiter. Der gewaehlte Weg wird in die
Konfiguration eingetragen (``user_data_dir``, ``kind``, ``executable``, ggf.
``cdp_port``) und beim naechsten Lauf direkt verwendet.

Jeder Versuch wird protokolliert (Konsole und Laufbericht ``browser``). Ueber
``trace(ereignis, daten)`` laesst sich der Ablauf zusaetzlich beobachten
(Entwicklungswerkzeug ``tools/browser_flow_lab.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

from chatexporter.providers.chatgpt.auth import browsers
from chatexporter.providers.chatgpt.auth import chrome_for_testing as cft
from chatexporter.providers.chatgpt.auth import process_control, profiles
from chatexporter.providers.chatgpt.auth.edge_cdp import EdgeCdpSession, _cdp_endpoint_reachable
from chatexporter.providers.chatgpt.auth.session import AuthSession, ReauthenticationRequired
from chatexporter.providers.chatgpt.config.models import AppConfig, BrowserConfig

Say = Callable[[str], None]
Ask = Callable[[str], str]
Trace = Callable[[str, dict], None]


def _no_trace(event: str, data: dict) -> None:
    return None


class BrowserSetupError(RuntimeError):
    """Kein Weg hat funktioniert; ``attempts`` enthaelt alle Gruende."""

    def __init__(self, message: str, attempts: list["Attempt"]):
        super().__init__(message)
        self.attempts = attempts


@dataclass
class Attempt:
    key: str
    label: str
    ok: bool
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "ok": self.ok, "reason": self.reason}


@dataclass
class BrowserChoice:
    mode: str                       # "configured" | "search"
    kind: str
    executable: str | None
    user_data_dir: str
    cdp_port: int
    attempts: list[Attempt] = field(default_factory=list)
    persisted: bool = False
    persist_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "kind": self.kind, "executable": self.executable,
                "user_data_dir": self.user_data_dir, "cdp_port": self.cdp_port,
                "persisted": self.persisted, "persist_error": self.persist_error,
                "attempts": [a.as_dict() for a in self.attempts]}


def _yes(answer: str) -> bool:
    return answer.strip().lower() in ("j", "ja", "y", "yes")


def _short(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    return f"{type(exc).__name__}: {text}"[:300]


class BrowserSetup:
    """Fuehrt die Suche aus. Alle Seiteneffekte sind einsetzbar (Tests)."""

    def __init__(self, cfg: AppConfig, *, interactive: bool, say: Say, ask: Ask = input,
                 session_factory: Callable[[BrowserConfig], Any] = EdgeCdpSession,
                 broker_factory: Callable[[Any], Any] | None = None,
                 candidates: Callable[[], list[browsers.BrowserCandidate]] | None = None,
                 persist: Callable[[dict[str, Any]], None] | None = None,
                 latest_release: Callable[[str], cft.Release] | None = None,
                 install: Callable[[Path, cft.Release], Path] | None = None,
                 endpoint_reachable: Callable[[str], bool] = _cdp_endpoint_reachable,
                 find_free_port: Callable[[str, int], int | None] = browsers.find_free_port,
                 profile_in_use: Callable[[Path], bool] = browsers.profile_in_use,
                 cookie_status: Callable[[Path], tuple[bool | None, str]] = profiles.chatgpt_cookie_status,
                 copy: Callable[..., Path] = profiles.copy_profile,
                 close_browser: Callable[..., Any] = process_control.close_browser,
                 trace: Trace = _no_trace) -> None:
        self.cfg = cfg
        self.interactive = interactive
        self.say = say
        self.ask = ask
        self.session_factory = session_factory
        self.broker_factory = broker_factory
        self.root = cfg.browser.browser_root or Path(cfg.browser.user_data_dir).parent / "browser"
        self.candidates = candidates or (lambda: browsers.build_candidates(
            self.root, installed_cft=cft.installed_executable(self.root)))
        self.persist = persist if persist is not None else self._persist_to_config
        self.latest_release = latest_release or (lambda url: cft.latest_release(url))
        self.install = install or (lambda root, release: cft.install(root, release, progress=self.say))
        self.endpoint_reachable = endpoint_reachable
        self.find_free_port = find_free_port
        self.profile_in_use = profile_in_use
        self.cookie_status = cookie_status
        self.copy = copy
        self.close_browser = close_browser
        self.trace = trace

    # -- oeffentlicher Ablauf -------------------------------------------------------
    def open(self) -> tuple[Any, AuthSession, BrowserChoice]:
        """Verbundene Sitzung, gueltige ChatGPT-Anmeldung und die getroffene Wahl."""
        if self.cfg.browser.user_data_dir_configured:
            return self._open_configured()
        return self._search()

    # -- fester Pfad --------------------------------------------------------------------
    def _open_configured(self):
        browser = self.cfg.browser
        label = f"{browsers.LABELS.get(browser.kind, browser.kind)} (konfiguriertes Profil)"
        self.say(f"Browser: {label} – {browser.user_data_dir}")
        self.trace("configured", {"kind": browser.kind, "user_data_dir": str(browser.user_data_dir),
                                  "executable": str(browser.executable) if browser.executable else None,
                                  "cdp_port": browser.cdp_port})
        session = self.session_factory(browser).connect()
        self.trace("connected", {"cdp_port": browser.cdp_port, "launched": getattr(session, "launched", None)})
        try:
            auth = self._broker(session).acquire(interactive=self.interactive)
        except BaseException:
            session.abandon()
            raise
        self.trace("auth_ok", {"label": label})
        choice = BrowserChoice("configured", browser.kind, str(browser.executable) if browser.executable else None,
                               str(browser.user_data_dir), browser.cdp_port,
                               [Attempt("configured", label, True)])
        return session, auth, choice

    # -- automatische Suche -------------------------------------------------------------
    def _search(self):
        browser = self.cfg.browser
        port = browser.cdp_port
        if self.endpoint_reachable(browser.cdp_endpoint):
            free = self.find_free_port(browser.cdp_host, port + 1)
            if free is None:
                raise BrowserSetupError(f"CDP-Port {port} ist belegt und kein freier Port gefunden", [])
            self.say(f"Browser-Suche: CDP-Port {port} ist bereits belegt, verwende Port {free}.")
            port = free
        attempts: list[Attempt] = []
        self.say("Browser-Suche: kein festes Profil konfiguriert, pruefe die moeglichen Wege ...")
        candidates = self.candidates()
        self.trace("candidates", {"candidates": browsers.describe(candidates), "cdp_port": port})
        for candidate in candidates:
            attempt = Attempt(candidate.key, candidate.label, False)
            attempts.append(attempt)
            self.trace("candidate", {"key": candidate.key, "label": candidate.label,
                                     "user_data_dir": str(candidate.user_data_dir)})
            result = self._try(candidate, port, attempt)
            if result is None:
                self.say(f"  - {candidate.label}: nicht verwendet – {attempt.reason}")
                self.trace("skipped", {"key": candidate.key, "reason": attempt.reason})
                continue
            session, auth, used = result
            attempt.ok = True
            self.say(f"  + {candidate.label}: verwendet ({used.user_data_dir})")
            choice = BrowserChoice("search", used.kind, str(used.executable) if used.executable else None,
                                   str(used.user_data_dir), used.cdp_port, attempts)
            self._remember(choice, port_changed=used.cdp_port != browser.cdp_port)
            self.trace("chosen", choice.as_dict())
            return session, auth, choice
        lines = "; ".join(f"{a.label}: {a.reason}" for a in attempts)
        self.trace("failed", {"attempts": [a.as_dict() for a in attempts]})
        raise BrowserSetupError(f"Kein Browser-Weg hat funktioniert ({lines})", attempts)

    def _try(self, candidate: browsers.BrowserCandidate, port: int, attempt: Attempt):
        executable = candidate.executable
        user_data_dir = Path(candidate.user_data_dir)
        if candidate.copy_from is not None:
            copied = self._make_copy(candidate, attempt)
            if copied is None:
                return None
            user_data_dir = copied
        if candidate.download:
            executable = self._obtain_chrome_for_testing(attempt)
            if executable is None:
                return None
        if self.endpoint_reachable(f"http://{self.cfg.browser.cdp_host}:{port}"):
            # z. B. ein Browser aus einem vorherigen Versuch, der sich nicht beenden liess
            free = self.find_free_port(self.cfg.browser.cdp_host, port + 1)
            if free is None:
                attempt.reason = f"CDP-Port {port} belegt, kein freier Port gefunden"
                return None
            self.say(f"  CDP-Port {port} belegt, verwende {free}.")
            port = free
        config = replace(self.cfg.browser, kind=candidate.kind, executable=executable,
                         user_data_dir=user_data_dir, cdp_port=port,
                         user_data_dir_configured=False, launch_if_needed=True)
        self.trace("launch", {"kind": candidate.kind, "executable": str(executable) if executable else None,
                              "user_data_dir": str(user_data_dir), "cdp_port": port})
        try:
            session = self.session_factory(config).connect()
        except Exception as exc:  # noqa: BLE001  jeder Startfehler fuehrt zum naechsten Weg
            attempt.reason = f"Start/CDP fehlgeschlagen: {_short(exc)}"
            return None
        self.trace("connected", {"cdp_port": port, "launched": getattr(session, "launched", None)})
        try:
            auth = self._login(session, candidate)
        except KeyboardInterrupt:
            session.abandon()
            raise
        except Exception as exc:  # noqa: BLE001
            session.abandon()
            attempt.reason = f"Anmeldung nicht pruefbar: {_short(exc)}"
            return None
        if auth is None:
            session.abandon()
            attempt.reason = "keine ChatGPT-Anmeldung in diesem Profil (Anmeldung nur bei interaktivem Start)"
            return None
        self.trace("auth_ok", {"label": candidate.label})
        return session, auth, config

    # -- Profilkopie -----------------------------------------------------------------------
    def _make_copy(self, candidate: browsers.BrowserCandidate, attempt: Attempt) -> Path | None:
        """Kopie des Browser-Profils anlegen: nur interaktiv und nach Bestaetigung.

        Ist der Browser mit diesem Profil geoeffnet, schliesst Setup ihn selbst
        (nur die Prozesse dieses Datenverzeichnisses), kopiert und oeffnet ihn
        danach wieder. Rueckgabe: Pfad der Kopie oder ``None``.
        """
        profile = candidate.copy_from
        name = browsers.LABELS.get(candidate.kind, candidate.kind)
        if not self.interactive:
            attempt.reason = ("Profilkopie nur bei interaktivem Start (der Browser wird dafuer kurz "
                              "geschlossen)")
            return None
        in_use = self.profile_in_use(profile.user_data_dir)
        self.trace("copy_offer", {"profile": profile.label, "source": str(profile.path),
                                  "target_folder": str(Path(candidate.user_data_dir).parent),
                                  "browser_open": in_use, "chatgpt": profile.chatgpt, "detail": profile.detail})
        self.say(f"  Gefunden: {profile.label} – {profile.detail or 'ChatGPT-Anmeldung moeglich'}.")
        self.say(f"  Damit der Abruf auch bei geoeffnetem {name} laeuft, wird EINMALIG eine Kopie dieses "
                 f"Profils angelegt (unter {Path(candidate.user_data_dir).parent}).")
        if in_use:
            self.say(f"  {name} ist geoeffnet. Setup schliesst {name} dafuer kurz und oeffnet ihn danach "
                     f"wieder; offene Tabs werden wiederhergestellt.")
        prompt = "  Kopie jetzt anlegen? [J/n] (n = diesen Weg ueberspringen) "
        if self._ask(prompt).strip().lower() in ("n", "nein", "no"):
            attempt.reason = "Profilkopie abgelehnt"
            return None
        closed = None
        if in_use:
            self.say(f"  Schliesse {name} ...")
            try:
                closed = self.close_browser(profile.user_data_dir, candidate.executable, say=self.say,
                                            in_use=self.profile_in_use)
            except Exception as exc:  # noqa: BLE001
                attempt.reason = f"{name} liess sich nicht schliessen: {_short(exc)}"
                self.trace("copy_close_failed", {"error": attempt.reason})
                return None
            self.trace("copy_browser_closed", {"processes": [f"{p.name} (PID {p.pid})" for p in closed.processes],
                                               "forced": closed.forced})
        try:
            status, detail = self.cookie_status(profile.path)
            self.trace("copy_cookie_check", {"chatgpt": status, "detail": detail})
            if status is False:
                attempt.reason = f"keine ChatGPT-Anmeldung im Profil ({detail})"
                return None
            target = profiles.copy_target(Path(candidate.user_data_dir).parent.parent, profile)
            try:
                self.copy(profile, target, say=self.say, in_use=self.profile_in_use)
            except Exception as exc:  # noqa: BLE001
                attempt.reason = f"Kopie fehlgeschlagen: {_short(exc)}"
                return None
            self.trace("copy_done", {"target": str(target)})
            return target
        finally:
            if closed is not None:
                how = closed.reopen(say=self.say)
                self.trace("copy_browser_reopened", {"how": how})
                if how != "none":
                    self.say(f"  {name} wurde wieder geoeffnet.")

    def _ask(self, prompt: str) -> str:
        try:
            return self.ask(prompt)
        except EOFError:
            return ""

    def _login(self, session: Any, candidate: browsers.BrowserCandidate) -> AuthSession | None:
        broker = self._broker(session)
        if not self.interactive:
            try:
                return broker.acquire(interactive=False)
            except ReauthenticationRequired:
                return None
        self.say(f"  Pruefe ChatGPT-Anmeldung in: {candidate.label}")
        return broker.acquire(interactive=True)

    def _broker(self, session: Any):
        if self.broker_factory is not None:
            return self.broker_factory(session)
        return auth_broker(self.cfg, session, say=self.say, trace=self.trace)

    def _obtain_chrome_for_testing(self, attempt: Attempt) -> Path | None:
        browser = self.cfg.browser
        if not browser.allow_download:
            attempt.reason = "Download abgeschaltet (providers.chatgpt.browser.allow_download)"
            return None
        if not self.interactive:
            attempt.reason = "Download nur bei interaktivem Start (mit Bestaetigung)"
            return None
        try:
            release = self.latest_release(browser.chrome_for_testing_url)
        except Exception as exc:  # noqa: BLE001
            attempt.reason = f"Versionsliste nicht abrufbar: {_short(exc)}"
            return None
        answer = self._ask(f"Chrome for Testing {release.version} herunterladen (ca. 150 MB) und ein "
                           f"eigenes Profil anlegen? [j/N] ")
        if not _yes(answer):
            attempt.reason = "Download abgelehnt"
            return None
        try:
            return self.install(self.root, release)
        except Exception as exc:  # noqa: BLE001
            attempt.reason = f"Download/Installation fehlgeschlagen: {_short(exc)}"
            return None

    # -- Ergebnis merken ----------------------------------------------------------------------
    def _remember(self, choice: BrowserChoice, *, port_changed: bool) -> None:
        values: dict[str, Any] = {
            "providers.chatgpt.browser.user_data_dir": choice.user_data_dir,
            "providers.chatgpt.browser.kind": choice.kind,
        }
        if choice.executable:
            values["providers.chatgpt.browser.executable"] = choice.executable
        if port_changed:
            values["providers.chatgpt.browser.cdp_port"] = choice.cdp_port
        try:
            self.persist(values)
            choice.persisted = True
            self.say("Browser-Profil in der Konfiguration eingetragen; der naechste Lauf verwendet es direkt.")
        except Exception as exc:  # noqa: BLE001  Merken ist hilfreich, aber nicht lebenswichtig
            choice.persist_error = _short(exc)
            self.say(f"Hinweis: Browser-Profil konnte nicht eingetragen werden ({choice.persist_error}).")

    def _persist_to_config(self, values: dict[str, Any]) -> None:
        import chatexporter.config as shared_config
        shared_config.manager().set_many(values, explicit=self.cfg.config_file)


def auth_broker(cfg: AppConfig, session: Any, *, counter: Any = None, say: Say = print,
                trace: Trace = _no_trace, force_auto_login: bool = False,
                confirm: Callable[[str, str], bool] | None = None) -> Any:
    """AuthBroker mit automatischer Anmeldung, sofern eingerichtet (``providers.chatgpt.auth``)."""
    from chatexporter.providers.chatgpt.auth.auto_login import default_block_file, make_auto_login
    from chatexporter.providers.chatgpt.auth.broker import AuthBroker
    return AuthBroker(session, cfg.api.base_url, cfg.api.request_timeout_ms, counter=counter,
                      auto_login=make_auto_login(cfg, session, say=say, trace=trace,
                                                 block_file=default_block_file(cfg), force=force_auto_login,
                                                 confirm=confirm))


def open_browser(cfg: AppConfig, *, interactive: bool, say: Say, counter: Any = None,
                 ask: Ask = input, trace: Trace = _no_trace) -> tuple[Any, AuthSession, BrowserChoice]:
    """Einstieg fuer den Sync: Sitzung + Anmeldung + Wahl (mit Anfragezaehlung)."""
    setup = BrowserSetup(cfg, interactive=interactive, say=say, ask=ask, trace=trace,
                         broker_factory=lambda s: auth_broker(cfg, s, counter=counter, say=say, trace=trace))
    return setup.open()
