"""Ende-zu-Ende: automatische Anmeldung mit echtem Browser gegen eine LOKALE Nachbildung.

Die Nachbildung (127.0.0.1) hat dieselbe Struktur und dieselben Attribute wie die
vom Benutzer aufgezeichneten Seiten (Button „Anmelden“ mit Dialog, E-Mail-Formular,
Passwortseite, mfa-challenge-Seite). Es werden keine echten Zugangsdaten verwendet
und keine fremden Seiten aufgerufen. Benoetigt Microsoft Edge (Playwright-Kanal
``msedge``); sonst uebersprungen.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

import two_factor_tools as tft
from chatexporter.providers.chatgpt.auth import totp
from chatexporter.providers.chatgpt.auth.auto_login import AutoLogin
from chatexporter.providers.chatgpt.config.models import AuthConfig

SECRET = "JBSWY3DPEHPK3PXP"
PASSWORD = "pw-lokal-test"

HOME_OUT = """<!doctype html><title>ChatGPT</title>
<header data-desktop-header><button data-login-button data-mobile-auth-entry-action="login" type="button"
  onclick="document.getElementById('d').showModal()">Anmelden</button></header>
<dialog id="d"><form data-octane-auth-email-form action="/log-in/password" method="get" novalidate>
<label for="mobile-auth-email">E-Mail-Adresse</label>
<input id="mobile-auth-email" name="login_hint" type="email" autocomplete="email">
<p id="mobile-auth-email-error" role="alert" hidden><span>Ungültige E-Mail-Adresse.</span></p>
<button type="submit">Weiter</button></form></dialog>"""
HOME_IN = "<!doctype html><title>ChatGPT</title><main><textarea id='prompt-textarea'></textarea></main>"
PASSWORD_PAGE = """<!doctype html><title>Passwort</title>{error}
<form method="post" action="/log-in/password"><input type="hidden" name="email" value="{email}">
<input name="current-password" type="password" autocomplete="current-password webauthn" placeholder="Passwort">
<button type="submit" name="intent" value="validate">Weiter</button></form>"""
MFA_PAGE = """<!doctype html><title>Einmalkennung</title>{error}
<form method="post" action="/mfa-challenge/6aa46adc"><input name="code" autocomplete="one-time-code"
 inputmode="numeric" maxlength="6" placeholder="Einmalkennung" type="text">
<button type="submit" name="intent" value="verify">Weiter</button></form>"""


class Site(BaseHTTPRequestHandler):
    log: list[str] = []

    def log_message(self, *args):
        pass

    def _send(self, body: str, status: int = 200, headers: dict | None = None):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, where: str, cookie: str | None = None):
        headers = {"Location": where}
        if cookie:
            headers["Set-Cookie"] = cookie
        self._send("", 302, headers)

    def do_GET(self):
        parts = urlsplit(self.path)
        Site.log.append(f"GET {parts.path}")
        if parts.path == "/":
            self._send(HOME_IN if "session=ok" in (self.headers.get("Cookie") or "") else HOME_OUT)
        elif parts.path == "/log-in/password":
            email = parse_qs(parts.query).get("login_hint", [""])[0]
            self._send(PASSWORD_PAGE.format(error="", email=email))
        elif parts.path.startswith("/mfa-challenge/"):
            self._send(MFA_PAGE.format(error=""))
        else:
            self._send("nicht gefunden", 404)

    def do_POST(self):
        parts = urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        Site.log.append(f"POST {parts.path}")
        if parts.path == "/log-in/password":
            if form.get("current-password", [""])[0] == PASSWORD:
                self._redirect("/mfa-challenge/6aa46adc")
            else:
                self._send(PASSWORD_PAGE.format(error='<div role="alert">Falsche E-Mail-Adresse oder falsches '
                                                      'Passwort</div>', email=""))
        elif parts.path.startswith("/mfa-challenge/"):
            secret = tft.create_secret_data(SECRET)
            now = time.time()
            valid = {tft.get_totp_code_from_secret_data(secret, 0, timestamp=now + shift) for shift in (-30, 0, 30)}
            if form.get("code", [""])[0] in valid:
                self._redirect("/", cookie="session=ok; Path=/")
            else:
                self._send(MFA_PAGE.format(error='<div role="alert">Ungültiger Code</div>'))


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            instance = p.chromium.launch(channel="msedge", headless=True)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Edge fuer Playwright nicht startbar: {exc}")
        yield instance
        instance.close()


def _run(browser, site, password, auth_host="127.0.0.1", human=False):
    context = browser.new_context()
    page = context.new_page()
    page.goto(site + "/")

    def logged_in():
        return any(c["name"] == "session" and c["value"] == "ok" for c in context.cookies())

    auth = AuthConfig(username="nutzer@example.org", password=password, totp_secret=SECRET)
    said: list[str] = []
    result = AutoLogin(page, auth, base_url=site, is_logged_in=logged_in, say=said.append, poll_ms=300,
                       code_source=lambda: totp.current_code(auth, min_remain_seconds=3),
                       app_hosts=("127.0.0.1",), auth_hosts=(auth_host,), require_https=False, human=human).run(90)
    context.close()
    return result, said


def test_login_with_a_real_browser(browser, site):
    Site.log.clear()
    result, said = _run(browser, site, PASSWORD, human=True)        # echtes Tippen, echte Pausen
    assert result.ok, result
    assert result.steps[:4] == ["login_button", "email", "password", "mfa"]
    assert "POST /log-in/password" in Site.log and "POST /mfa-challenge/6aa46adc" in Site.log
    assert not any(PASSWORD in line or "nutzer@example.org" in line for line in said)


def test_wrong_password_with_a_real_browser(browser, site):
    Site.log.clear()
    result, _ = _run(browser, site, "falsch")
    assert not result.ok and result.rejected and "falsches Passwort" in result.reason
    assert Site.log.count("POST /log-in/password") == 1, "Passwort nur einmal abgeschickt"


def test_password_is_not_entered_when_the_login_page_is_not_the_expected_one(browser, site):
    """Echter Browser: Die Passwortseite liegt auf einem anderen Host als erwartet -> nichts eintragen."""
    Site.log.clear()
    result, said = _run(browser, site, PASSWORD, auth_host="auth.example.invalid")
    assert not result.ok and result.needs_user and "nicht erwarteten Seite" in result.reason
    assert "POST /log-in/password" not in Site.log, "Passwort nie abgeschickt"
