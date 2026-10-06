"""Automatische ChatGPT-Anmeldung im per CDP gesteuerten Browser: E-Mail, Passwort, Einmalcode.

Ablauf (aufgezeichnet vom Benutzer am 2026-10-03, ``ChatExporter/AutomatischerLogin_AblaufImBrowser.md``):

1. ``chatgpt.com``: Button „Anmelden“ (Kopfzeile oder Seitenleiste) oeffnet den Dialog.
2. Dialog: E-Mail in ``input#mobile-auth-email`` (``name=login_hint``), „Weiter“.
3. ``auth.openai.com/log-in/password``: Passwort (``name=current-password``), „Weiter“
   (``button[name=intent][value=validate]``).
4. ``auth.openai.com/mfa-challenge/...``: Einmalcode (``autocomplete=one-time-code``),
   „Weiter“ (``button[name=intent][value=verify]``).
5. Rueckleitung zu ``chatgpt.com`` – die Sitzung wird ueber ``/api/auth/session`` bestaetigt.

Umsetzung als Zustandsautomat: Bei jedem Durchgang wird erkannt, welche Seite
gerade zu sehen ist, und genau der passende Schritt ausgefuehrt. Selektoren
nutzen stabile Attribute (id, name, autocomplete, data-*), keine generierten
CSS-Klassen. Grenzen:

- Sicherheitspruefungen (Cloudflare/Turnstile/Captcha) werden **nie** umgangen:
  Der Automat stoppt und uebergibt an den Benutzer (``needs_user``).
- Ein Code per E-Mail (Geraete-/E-Mail-Bestaetigung) wird nicht automatisiert.
- Das Passwort wird hoechstens einmal je Anmeldung abgeschickt, der Einmalcode
  hoechstens zweimal (Sperrschutz). Meldet die Seite einen Fehler, endet der Versuch.
- Zugangsdaten und Codes erscheinen in keiner Ausgabe; protokolliert werden nur
  Zustandsnamen und Seitenpfade (ohne Query).
- Eingetragen wird nur auf den erwarteten Seiten (``ALLOWED_PAGES``): E-Mail auf
  ``chatgpt.com`` oder ``auth.openai.com``, Passwort und Einmalcode nur auf
  ``auth.openai.com``, immer ueber https, Hostname exakt (keine Subdomains). Geprueft
  wird bei der Erkennung UND unmittelbar vor dem Eintragen am Eingabefeld selbst (das
  Dokument, zu dem es gehoert). Steht ein Anmeldefeld auf einer anderen Seite, endet
  der Versuch sofort, ohne etwas einzutragen.
- Menschliches Tempo (``human``, Standard): vor jedem Schritt eine zufaellige Pause
  (``HUMAN_PAUSE_SECONDS``), Eingaben Zeichen fuer Zeichen mit zufaelligen Abstaenden
  (``HUMAN_KEY_DELAY_MS``), Klick auf das Feld vor dem Tippen. Das ist kein Umgehen von
  Sicherheitspruefungen – diese beenden den Versuch weiterhin sofort.
- Schrittweise (``confirm``, Befehl ``chatgpt login --schrittweise``): vor jedem Schritt
  wird gemeldet, was erkannt wurde und was als Naechstes geschieht; ausgefuehrt wird erst
  nach Bestaetigung.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from chatexporter.providers.chatgpt.auth import totp

Say = Callable[[str], None]
Trace = Callable[[str, dict], None]

LOGIN_BUTTON = ('button[data-login-button]', '[data-mobile-auth-entry-action="login"]',
                'button[data-testid="login-button"]')
EMAIL_INPUT = ('input#mobile-auth-email', 'input[name="login_hint"]', 'input[name="email"]',
               'input[type="email"]', 'input[autocomplete="email"]', 'input[name="username"]')
EMAIL_SUBMIT = ('form[data-octane-auth-email-form] button[type="submit"]', 'button[name="intent"][value="email"]',
                'button[type="submit"]')
PASSWORD_INPUT = ('input[name="current-password"]', 'input[type="password"]')
PASSWORD_SUBMIT = ('button[name="intent"][value="validate"]', 'button[type="submit"]')
CODE_INPUT = ('input[autocomplete="one-time-code"]', 'input[name="code"]')
CODE_SUBMIT = ('button[name="intent"][value="verify"]', 'button[type="submit"]')
CHALLENGE = ('iframe[src*="challenges.cloudflare.com"]', '#challenge-form', '#cf-challenge-running',
             'input[name="cf-turnstile-response"]', 'iframe[src*="hcaptcha.com"]', 'iframe[src*="recaptcha"]')
CHALLENGE_TITLES = ("just a moment", "einen moment", "attention required", "verify you are human")
ERROR_TEXT = ('[role="alert"]', '[data-error-message]', '[aria-live="assertive"]')

MAX_ACTIONS = {"login_button": 3, "email": 2, "password": 1, "mfa": 2}
#: Zufaellige Pause vor jedem Schritt (Sekunden) und zwischen zwei Tastendruecken (Millisekunden).
HUMAN_PAUSE_SECONDS = (1.5, 4.0)
HUMAN_KEY_DELAY_MS = (60, 180)
#: Klartext fuer die schrittweise Anmeldung.
STATE_LABELS = {"login_button": "ChatGPT, nicht angemeldet (Button „Anmelden“)",
                "email": "Feld fuer die E-Mail-Adresse", "password": "Passwortseite",
                "mfa": "Seite fuer den Einmalcode"}
STEP_TEXT = {"login_button": "auf „Anmelden“ klicken",
             "email": "E-Mail-Adresse eintippen und „Weiter“ klicken",
             "password": "Passwort eintippen und „Weiter“ klicken",
             "mfa": "Einmalcode eintippen und „Weiter“ klicken"}
#: Auf welchen Seiten ein Schritt ausgefuehrt werden darf: "app" = ChatGPT, "auth" = Anmeldeseite.
ALLOWED_PAGES = {"login_button": ("app",), "email": ("app", "auth"), "password": ("auth",), "mfa": ("auth",)}
#: Sekunden, die eine Seite nach einem Schritt Zeit bekommt, bevor derselbe Schritt wiederholt wird.
#: Ohne diese Wartezeit wurde der Einmalcode im Live-Test (2026-10-04) zweimal abgeschickt, weil die
#: Seite nach dem ersten Klick noch kurz dieselbe Eingabe zeigte.
RETRY_AFTER_SECONDS = 10


@dataclass
class LoginResult:
    ok: bool
    reason: str = ""
    #: Benutzer muss im Browserfenster selbst weitermachen (Captcha, Code per E-Mail, unbekannte Seite).
    needs_user: bool = False
    #: Anmeldeseite hat die Zugangsdaten abgelehnt (dann nicht wiederholen).
    rejected: bool = False
    steps: list[str] = field(default_factory=list)
    #: Besuchte Seiten (Host und Pfad, ohne Query) – zur Nachvollziehbarkeit.
    pages: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason, "needs_user": self.needs_user,
                "rejected": self.rejected, "steps": list(self.steps), "pages": list(self.pages)}


def _visible(page: Any, selectors: tuple[str, ...]) -> Any | None:
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
            for index in range(min(count, 5)):
                item = locator.nth(index)
                if item.is_visible():
                    return item
        except Exception:  # noqa: BLE001  Seite navigiert gerade
            continue
    return None


def _where(url: str) -> str:
    parts = urlsplit(url or "")
    return f"{parts.netloc}{parts.path}"


class AutoLogin:
    """Fuehrt die Anmeldung auf ``page`` aus. Alle Seiteneffekte sind einsetzbar (Tests)."""

    def __init__(self, page: Any, auth: Any, *, base_url: str = "https://chatgpt.com",
                 is_logged_in: Callable[[], bool], say: Say = print, trace: Trace = lambda e, d: None,
                 code_source: Callable[[], totp.OneTimeCode] | None = None,
                 clock: Callable[[], float] = time.monotonic, poll_ms: int = 700,
                 app_hosts: tuple[str, ...] = ("chatgpt.com",),
                 auth_hosts: tuple[str, ...] = ("auth.openai.com",),
                 require_https: bool = True, human: bool = True, rng: random.Random | None = None,
                 confirm: Callable[[str, str], bool] | None = None) -> None:
        self.page = page
        self.auth = auth
        self.base_url = base_url.rstrip("/")
        self.is_logged_in = is_logged_in
        self.say = say
        self.trace = trace
        self.code_source = code_source or (lambda: totp.current_code(auth, min_remain_seconds=10))
        self.clock = clock
        self.poll_ms = poll_ms
        #: Hosts der App (``chatgpt.com``) und der Anmeldeseiten (``auth.openai.com``); Tests setzen eigene.
        self.app_hosts = tuple(h.lower() for h in app_hosts)
        self.auth_hosts = tuple(h.lower() for h in auth_hosts)
        #: Nur Tests gegen eine lokale Nachbildung (http://127.0.0.1) schalten das ab.
        self.require_https = require_https
        self.human = human
        self.rng = rng or random.Random()
        #: ``(zustand, beschreibung) -> weiter?`` fuer die schrittweise Anmeldung.
        self.confirm = confirm
        #: Zuletzt abgeschickter Einmalcode (nur im Speicher), damit eine Wiederholung einen neuen nimmt.
        self._last_code = ""

    def _is(self, host: str, hosts: tuple[str, ...]) -> bool:
        """Exakter Hostname (ohne Port); Subdomains zaehlen bewusst nicht."""
        return host.split(":")[0].lower() in hosts

    def _allowed(self, state: str, url: str) -> bool:
        """Darf ``state`` auf der Seite ``url`` ausgefuehrt werden? (``ALLOWED_PAGES``)"""
        parts = urlsplit(url or "")
        if self.require_https and parts.scheme != "https":
            return False
        kinds = ALLOWED_PAGES.get(state, ())
        return (("app" in kinds and self._is(parts.netloc, self.app_hosts))
                or ("auth" in kinds and self._is(parts.netloc, self.auth_hosts)))

    def _element_url(self, element: Any) -> str:
        """Adresse des Dokuments, zu dem das Eingabefeld gehoert (nicht nur die der Seite)."""
        try:
            return str(element.evaluate("e => e.ownerDocument.location.href") or "")
        except Exception:  # noqa: BLE001  Feld waehrend der Navigation verschwunden
            return ""

    # -- Erkennung ---------------------------------------------------------------------
    def detect(self) -> tuple[str, Any]:
        page = self.page
        try:
            url = page.url or ""
            title = (page.title() or "").lower()
        except Exception:  # noqa: BLE001
            return "loading", None
        host = urlsplit(url).netloc
        if any(t in title for t in CHALLENGE_TITLES) or _visible(page, CHALLENGE) is not None:
            return "challenge", None
        # Fehlermeldungen nur auf den Anmeldeseiten bzw. im offenen E-Mail-Dialog werten
        # (auf chatgpt.com koennen sonst Hinweis-Toasts wie Fehler aussehen).
        if self._is(host, self.auth_hosts) or (self._is(host, self.app_hosts) and _visible(page, EMAIL_INPUT)):
            error = _visible(page, ERROR_TEXT)
            if error is not None:
                try:
                    text = " ".join((error.inner_text() or "").split())
                except Exception:  # noqa: BLE001
                    text = ""
                if text:
                    return "error", text[:200]
        code = _visible(page, CODE_INPUT)
        if code is not None:
            # Erst entscheiden, wenn Adresse und Feld zur selben Seite gehoeren (Live 2026-10-05:
            # Adresse noch .../log-in/password, Codefeld schon von .../mfa-challenge/... -> faelschlich
            # "Code per E-Mail"). Waehrend eines Seitenwechsels: neu erkennen.
            current, document = self._url(), self._element_url(code)
            if not document or urlsplit(url)[:3] != urlsplit(current)[:3] \
                    or urlsplit(document)[:3] != urlsplit(current)[:3]:
                return "loading", None
            if "mfa" not in urlsplit(current).path:
                return "code_other", code
            return self._checked("mfa", current, code)
        password = _visible(page, PASSWORD_INPUT)
        if password is not None:
            return self._checked("password", url, password)
        email = _visible(page, EMAIL_INPUT)
        if email is not None:
            return self._checked("email", url, email)
        button = _visible(page, LOGIN_BUTTON)
        if button is not None:
            return self._checked("login_button", url, button)
        if self._is(host, self.app_hosts):
            return "chatgpt", None
        if self._is(host, self.auth_hosts):
            return "auth_wait", None             # Anmeldeseite ohne Eingabefeld (Weiterleitung)
        if not host or url.startswith("about:"):
            return "blank", None
        return "unknown", None

    def _checked(self, state: str, url: str, element: Any) -> tuple[str, Any]:
        """Schritt nur auf einer erlaubten Seite; sonst ``foreign`` mit Hostname (nie Zugangsdaten).

        Massgeblich ist das Dokument, zu dem das Feld gehoert, und die jetzt aktuelle Seitenadresse.
        ``url`` wurde vor der Feldsuche gelesen; wechselt die Seite dazwischen (Live 2026-10-05: Adresse
        noch chatgpt.com, Passwortfeld schon von auth.openai.com), passen die Adressen nicht zusammen –
        das ist ein Seitenwechsel (``loading``, erneut erkennen), kein fremder Host.
        """
        def host(u: str) -> str:
            return urlsplit(u or "").netloc.lower()
        document = self._element_url(element)
        current = self._url()
        if not document or host(url) != host(current):
            return "loading", None                       # Seite wechselt gerade
        if host(document) != host(current) and host(document) == host(self._url()):
            return "loading", None                       # Wechsel genau zwischen den beiden Abfragen
        if self._allowed(state, document) and self._allowed(state, current):
            return state, element
        if host(document) != host(current):              # Feld aus einem fremden eingebetteten Rahmen
            url = document
        parts = urlsplit(url or "")
        self.trace("login_foreign_page", {"state": state, "where": parts.netloc})
        return "foreign", f"{state} auf {parts.scheme}://{parts.netloc}"

    # -- Ablauf ------------------------------------------------------------------------------
    def run(self, timeout_seconds: int = 120) -> LoginResult:
        result = LoginResult(False)
        counts: dict[str, int] = {}
        deadline = self.clock() + timeout_seconds
        last_state, state_since, last_probe = "", self.clock(), 0.0
        try:
            host = urlsplit(self.page.url or "").netloc
        except Exception:  # noqa: BLE001
            host = ""
        if not (self._is(host, self.app_hosts) or self._is(host, self.auth_hosts)):
            self._goto(self.base_url + "/")
        while self.clock() < deadline:
            state, element = self.detect()
            now = self.clock()
            where = _where(self._url())
            if where and (not result.pages or result.pages[-1] != where):
                result.pages.append(where)
            if state != last_state:
                result.steps.append(state)
                self.trace("login_state", {"state": state, "where": where})
                last_state, state_since = state, now
            stuck = now - state_since
            if state == "challenge":
                return self._stop(result, "Sicherheitspruefung im Browser (z. B. Captcha) – bitte selbst "
                                          "loesen; sie wird nicht automatisch umgangen", needs_user=True)
            if state == "foreign":
                return self._stop(result, f"Anmeldefeld auf einer nicht erwarteten Seite ({element}) – "
                                          "nichts eingetragen; bitte im Browser pruefen", needs_user=True)
            if state == "error":
                result.rejected = True
                return self._stop(result, f"Anmeldeseite meldet: {element}")
            if state == "code_other":
                return self._stop(result, "Die Anmeldeseite verlangt einen Code per E-Mail oder eine andere "
                                          "Bestaetigung – bitte im Browser selbst abschliessen", needs_user=True)
            if state == "chatgpt":
                if now - last_probe >= 3:
                    last_probe = now
                    if self.is_logged_in():
                        result.ok = True
                        result.reason = "angemeldet"
                        self.say("  Automatische Anmeldung erfolgreich.")
                        return result
                if stuck > 20:
                    return self._stop(result, "ChatGPT geladen, aber keine Sitzung und kein Anmelde-Button "
                                              "erkennbar", needs_user=True)
            elif state in MAX_ACTIONS:
                if counts.get(state, 0) >= MAX_ACTIONS[state]:
                    if stuck > 15:
                        return self._stop(result, self._repeated(state), needs_user=state != "password",
                                          rejected=state in ("password", "mfa"))
                elif counts.get(state, 0) and stuck < RETRY_AFTER_SECONDS:
                    pass                                 # Seite reagiert noch auf den letzten Schritt
                else:
                    counts[state] = counts.get(state, 0) + 1
                    if self.confirm is not None:
                        asked = self.clock()
                        go_on = self.confirm(state, self._describe(state))
                        deadline += self.clock() - asked          # Wartezeit auf den Benutzer zaehlt nicht
                        if not go_on:
                            return self._stop(result, "Schrittweise Anmeldung vom Benutzer abgebrochen",
                                              needs_user=True)
                        fresh, element = self.detect()            # Seite kann sich inzwischen geaendert haben
                        if fresh != state:
                            counts[state] -= 1
                            state_since = self.clock()
                            self._wait(self.poll_ms)
                            continue
                    target = self._element_url(element)
                    if not target:                         # Feld weg: Seite wechselt gerade, neu erkennen
                        counts[state] -= 1
                        self._wait(self.poll_ms)
                        continue
                    if not (self._allowed(state, target) and self._allowed(state, self._url())):
                        parts = urlsplit(target or self._url())
                        self.trace("login_foreign_page", {"state": state, "where": parts.netloc})
                        return self._stop(result, f"Anmeldefeld gehoert zu einer nicht erwarteten Seite "
                                                  f"({state} auf {parts.scheme}://{parts.netloc}) – nichts "
                                                  "eingetragen; bitte im Browser pruefen", needs_user=True)
                    failure = self._act(state, element)
                    if failure:
                        return self._stop(result, failure)
                    state_since = self.clock()
            elif state in ("unknown", "auth_wait") and stuck > 25:
                return self._stop(result, f"Unbekannte Seite ({_where(self._url())})", needs_user=True)
            elif state == "blank" and stuck > 5:
                self._goto(self.base_url + "/")
                state_since = self.clock()
            self._wait(self.poll_ms)
        return self._stop(result, f"Zeitlimit von {timeout_seconds} s erreicht (zuletzt: {last_state})",
                          needs_user=True)

    def _describe(self, state: str) -> str:
        parts = urlsplit(self._url())
        return (f"  Erkannt: {STATE_LABELS.get(state, state)} auf {parts.scheme}://{parts.netloc}{parts.path}\n"
                f"  Naechster Schritt: {STEP_TEXT.get(state, state)}")

    def _pause(self, seconds: tuple[float, float] = HUMAN_PAUSE_SECONDS) -> None:
        if self.human:
            self._wait(int(self.rng.uniform(*seconds) * 1000))

    def _type(self, element: Any, text: str) -> None:
        """Wie ein Mensch tippen; kommt nicht alles an, den Wert direkt setzen (Wert nie ausgeben)."""
        if not self.human:
            element.fill(text)
            return
        element.click()
        element.fill("")
        for char in text:
            element.press_sequentially(char)
            self._wait(int(self.rng.uniform(*HUMAN_KEY_DELAY_MS)))
        try:
            complete = element.input_value() == text
        except Exception:  # noqa: BLE001
            complete = True
        if not complete:
            self.trace("login_typing_fallback", {})
            element.fill(text)

    def _act(self, state: str, element: Any) -> str:
        try:
            self._pause()
            if state == "login_button":
                self.say("  Anmeldung: oeffne den Anmeldedialog ...")
                element.click()
            elif state == "email":
                self._type(element, self.auth.username or "")
                self.say("  Anmeldung: E-Mail-Adresse eingetragen.")
                self._pause((0.4, 1.0))
                self._submit(EMAIL_SUBMIT, element)
            elif state == "password":
                self._type(element, self.auth.password or "")
                self.say("  Anmeldung: Passwort eingetragen.")
                self._pause((0.4, 1.0))
                self._submit(PASSWORD_SUBMIT, element)
            elif state == "mfa":
                try:
                    code = self.code_source()
                except totp.OneTimeCodeError as exc:
                    return str(exc)
                if (code.remain_seconds and code.remain_seconds < 5) or code.code == self._last_code:
                    # Kurz vor Ablauf, oder Wiederholung mit demselben Code: auf den naechsten warten.
                    self._wait(code.remain_seconds * 1000 + 1000)
                    code = self.code_source()
                self._last_code = code.code
                self._type(element, code.code)
                self.say(f"  Anmeldung: Einmalcode eingetragen (noch {code.remain_seconds} s gueltig).")
                self._pause((0.3, 0.8))
                self._submit(CODE_SUBMIT, element)
        except Exception as exc:  # noqa: BLE001  z. B. Element waehrend der Navigation verschwunden
            self.trace("login_action_retry", {"state": state, "error": type(exc).__name__})
        return ""

    def _submit(self, selectors: tuple[str, ...], field_element: Any) -> None:
        button = _visible(self.page, selectors)
        if button is not None:
            button.click()
        else:
            field_element.press("Enter")

    @staticmethod
    def _repeated(state: str) -> str:
        return {"password": "Passwort wurde abgeschickt, die Seite fragt erneut – Passwort pruefen",
                "mfa": "Einmalcode zweimal abgeschickt und nicht angenommen – 2FA-Secret und Uhrzeit pruefen",
                "email": "E-Mail-Schritt kommt nicht weiter",
                "login_button": "Anmeldedialog oeffnet sich nicht"}[state]

    def _stop(self, result: LoginResult, reason: str, *, needs_user: bool = False,
              rejected: bool | None = None) -> LoginResult:
        result.reason = reason
        result.needs_user = needs_user
        if rejected is not None:
            result.rejected = rejected
        self.trace("login_stopped", {"reason": reason, "needs_user": needs_user})
        return result

    def _url(self) -> str:
        try:
            return self.page.url or ""
        except Exception:  # noqa: BLE001
            return ""

    def _goto(self, url: str) -> None:
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:  # noqa: BLE001
            self.trace("login_goto_failed", {"error": type(exc).__name__})

    def _wait(self, ms: int) -> None:
        try:
            self.page.wait_for_timeout(ms)
        except Exception:  # noqa: BLE001
            time.sleep(ms / 1000)


# -- Sperrschutz: abgelehnte Zugangsdaten nicht in jedem Lauf erneut senden --------------------------

def credential_fingerprint(auth: Any) -> str:
    """Kurzer, nicht umkehrbarer Fingerabdruck (12 Hex-Zeichen) – nur zum Wiedererkennen."""
    raw = f"{auth.username or ''}\0{auth.password or ''}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def blocked(block_file: Path | None, auth: Any) -> dict | None:
    if block_file is None or not block_file.is_file():
        return None
    try:
        info = json.loads(block_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return info if info.get("fingerprint") == credential_fingerprint(auth) else None


def write_block(block_file: Path | None, auth: Any, reason: str) -> None:
    if block_file is None:
        return
    block_file.parent.mkdir(parents=True, exist_ok=True)
    tmp = block_file.with_suffix(".tmp")
    tmp.write_text(json.dumps({"fingerprint": credential_fingerprint(auth), "reason": reason,
                               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(block_file)


def clear_block(block_file: Path | None) -> None:
    if block_file is not None:
        block_file.unlink(missing_ok=True)


# -- Einstieg fuer den AuthBroker ------------------------------------------------------------------------

def make_auto_login(cfg: Any, session: Any, *, say: Say = print, trace: Trace = lambda e, d: None,
                    block_file: Path | None = None, force: bool = False,
                    confirm: Callable[[str, str], bool] | None = None):
    """Funktion ``(is_logged_in) -> LoginResult`` fuer den AuthBroker, oder ``None`` (abgeschaltet).

    ``force`` (Befehl ``chatgpt login``): einen Sperrvermerk ignorieren.
    """
    auth = cfg.auth
    for problem in auth.problems:
        say(f"Hinweis: {problem}")
    if not auth.enabled:
        return None

    def run(is_logged_in: Callable[[], bool]) -> LoginResult:
        if not auth.has_credentials:
            return LoginResult(False, "Zugangsdaten fehlen (CHATGPT_USERNAME und CHATGPT_PASSWORD in der .env)")
        if not totp.configured(auth):
            say("Hinweis: kein 2FA-Secret angegeben – verlangt die Seite einen Einmalcode, endet die Anmeldung dort.")
        hit = None if force else blocked(block_file, auth)
        if hit:
            return LoginResult(False, "Diese Zugangsdaten wurden zuletzt abgelehnt ("
                               f"{hit.get('at')}: {hit.get('reason')}); erst nach Aenderung oder mit "
                               "'chatexporter chatgpt login' erneut versucht", rejected=True)
        say("Keine gueltige ChatGPT-Sitzung – automatische Anmeldung ...")
        page = session.ensure_chatgpt_page()
        app_host = (urlsplit(cfg.api.base_url).hostname or "chatgpt.com").lower()
        result = AutoLogin(page, auth, base_url=cfg.api.base_url, is_logged_in=is_logged_in, say=say,
                           trace=trace, app_hosts=(app_host,), confirm=confirm).run(auth.login_timeout_seconds)
        if result.ok:
            clear_block(block_file)
        elif result.rejected:
            write_block(block_file, auth, result.reason)
        return result

    return run


def default_block_file(cfg: Any) -> Path | None:
    """``<storage>/.storage/auth/auto_login_block.json`` (Verwaltungsbereich des Storages)."""
    runtime = cfg.storage.runtime_root or (Path(cfg.storage.raw_root).parent / ".storage")
    return Path(runtime) / "auth" / "auto_login_block.json"
