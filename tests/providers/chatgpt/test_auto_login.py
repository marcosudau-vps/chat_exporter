"""Automatische Anmeldung: Einmalcode, Zugangsdaten-Quellen, Zustandsautomat, Sperrschutz, Broker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import two_factor_tools as tft
from chatexporter.providers.chatgpt.auth import auto_login, totp
from chatexporter.providers.chatgpt.auth.auto_login import AutoLogin, LoginResult, make_auto_login
from chatexporter.providers.chatgpt.config.models import AppConfig, AuthConfig

SECRET = "JBSWY3DPEHPK3PXP"


def _auth(**kw) -> AuthConfig:
    values = {"username": "nutzer@example.org", "password": "pw-test", "totp_secret": SECRET}
    values.update(kw)
    return AuthConfig(**values)


# -- Einmalcode -------------------------------------------------------------------------------

def test_code_from_base32_otpauth_and_reference(monkeypatch):
    expected = tft.get_totp_code_from_secret_data(tft.create_secret_data(SECRET), 0, timestamp=1_000_000)
    assert totp.current_code(_auth(), min_remain_seconds=0, timestamp=1_000_000).code == expected
    uri = f"otpauth://totp/ChatGPT:nutzer?secret={SECRET}&issuer=ChatGPT"
    assert totp.current_code(_auth(totp_secret=uri), min_remain_seconds=0, timestamp=1_000_000).code == expected
    seen = {}

    def fake_lookup(reference, min_remain, *, timestamp=None, details=False):
        seen["ref"] = reference
        return {"code": "123456", "remain_seconds": 20}

    monkeypatch.setattr(tft, "get_totp_code", fake_lookup)
    code = totp.current_code(_auth(totp_secret=None, totp_reference="chatgpt-konto"))
    assert code.code == "123456" and seen["ref"] == "chatgpt-konto", "Kennung hat Vorrang, Secret bleibt im Speicher"
    assert "123456" not in repr(code)


def test_code_errors_never_contain_the_secret():
    with pytest.raises(totp.OneTimeCodeError, match="Kein 2FA-Secret"):
        totp.current_code(_auth(totp_secret=None))
    with pytest.raises(totp.OneTimeCodeError) as exc:
        totp.current_code(_auth(totp_secret="kein!gültiges#secret"))
    assert "kein!gültiges#secret" not in str(exc.value)


# -- Zugangsdaten nur aus .env/Umgebung -------------------------------------------------------------

def test_credentials_only_from_env_or_dotenv(tmp_path, monkeypatch):
    from chatexporter.providers.chatgpt.config.loader import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("providers:\n  chatgpt:\n    auth:\n      password: aus-der-yaml\n", encoding="utf-8")
    (tmp_path / ".env").write_text("CHATGPT_USERNAME=nutzer@example.org\nCHATGPT_2FA_SECRET=" + SECRET + "\n",
                                   encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.auth.username == "nutzer@example.org" and cfg.auth.totp_secret == SECRET
    assert cfg.auth.password is None and "stammt aus 'config'" in cfg.auth.problems[0]
    assert not cfg.auth.enabled, "auto: ohne Passwort nicht aktiv"
    monkeypatch.setenv("CHATGPT_PASSWORD", "pw-aus-umgebung")
    cfg = load_config(cfg_file)
    assert cfg.auth.password == "pw-aus-umgebung" and cfg.auth.enabled
    assert "pw-aus-umgebung" not in repr(cfg.auth) and "nutzer@example.org" not in repr(cfg)


def test_credentials_from_the_storage_dotenv_but_never_from_the_storage_config(tmp_path):
    """Storage-Ebene (pre-6): ``<storage>/.storage/.env`` ist erlaubt, ``.storage/config.yaml`` nicht."""
    import chatexporter.config as shared_config
    from chatexporter.providers.chatgpt.config.loader import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("logging:\n  retention: 7d\n", encoding="utf-8")
    storage = shared_config.storage_of(shared_config.load(cfg_file))
    storage.env_file.write_text("CHATGPT_USERNAME=nutzer@example.org\n", encoding="utf-8")
    storage.config_file.write_text("providers:\n  chatgpt:\n    auth:\n      password: aus-storage-yaml\n",
                                   encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.auth.username == "nutzer@example.org", "aus 'storage .env' angenommen"
    assert cfg.auth.password is None and "stammt aus 'storage'" in cfg.auth.problems[0]


def test_block_file_lives_in_the_storage_admin_area(tmp_path):
    import chatexporter.config as shared_config
    from chatexporter.providers.chatgpt.auth.auto_login import default_block_file
    from chatexporter.providers.chatgpt.config.loader import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("logging:\n  retention: 7d\n", encoding="utf-8")
    storage = shared_config.storage_of(shared_config.load(cfg_file))
    assert default_block_file(load_config(cfg_file)) == storage.meta / "auth" / "auto_login_block.json"
    cfg = load_config(cfg_file)
    cfg.storage.runtime_root = None                     # Ausweichweg: neben raw_storage, nie "runtime"
    assert default_block_file(cfg) == storage.meta / "auth" / "auto_login_block.json"


def test_config_cli_masks_secrets(tmp_path, monkeypatch, capsys):
    from chatexporter.config import cli as config_cli
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("CHATGPT_PASSWORD", "streng-geheim")
    lines: list[str] = []
    assert config_cli.main(["--config", str(cfg_file), "list"], say=lines.append) == 0
    assert config_cli.main(["--config", str(cfg_file), "get", "providers.chatgpt.auth"], say=lines.append) == 0
    assert config_cli.main(["--config", str(cfg_file), "get", "providers.chatgpt.auth.password", "--json"],
                           say=lines.append) == 0
    text = "\n".join(lines)
    assert "streng-geheim" not in text and config_cli.SECRET_SHOWN in text


# -- Zustandsautomat mit Ersatz-Seite -----------------------------------------------------------------

class FakeLocator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    def count(self):
        return 1 if self.selector in self.page.visible() else 0

    def nth(self, index):
        return self

    def is_visible(self):
        return self.selector in self.page.visible()

    def fill(self, value):
        self.page.filled[self.selector] = value

    def click(self):
        self.page.click(self.selector)

    def press(self, key):
        self.page.click("ENTER:" + self.selector)

    def inner_text(self):
        return self.page.texts.get(self.selector, "")

    def press_sequentially(self, text):
        self.page.typed.append(self.selector)
        if self.selector in self.page.lose and len(self.page.typed) % 2 == 0:
            return                                    # Zeichen geht verloren (Test des Rueckfalls)
        self.page.filled[self.selector] = self.page.filled.get(self.selector, "") + text

    def input_value(self):
        return self.page.filled.get(self.selector, "")

    def evaluate(self, script):
        # Adresse des Dokuments, zu dem das Feld gehoert (Standard: die Seite selbst).
        return self.page.element_urls.get(self.selector, self.page.url)


class FakePage:
    """Simuliert chatgpt.com + auth.openai.com wie in der Aufzeichnung des Benutzers."""

    SCREENS = {
        "home": ("https://chatgpt.com/", {"button[data-login-button]"}),
        "email": ("https://chatgpt.com/", {"button[data-login-button]", "input#mobile-auth-email",
                                           'form[data-octane-auth-email-form] button[type="submit"]'}),
        "password": ("https://auth.openai.com/log-in/password",
                     {'input[name="current-password"]', 'button[name="intent"][value="validate"]'}),
        "password_error": ("https://auth.openai.com/log-in/password",
                           {'input[name="current-password"]', 'button[name="intent"][value="validate"]',
                            '[role="alert"]'}),
        "mfa": ("https://auth.openai.com/mfa-challenge/6aa46adc", {'input[autocomplete="one-time-code"]',
                                                                    'button[name="intent"][value="verify"]'}),
        "email_code": ("https://auth.openai.com/email-verification", {'input[autocomplete="one-time-code"]'}),
        "challenge": ("https://chatgpt.com/", set()),
        "done": ("https://chatgpt.com/", set()),
        "blank": ("about:blank", set()),
    }

    def __init__(self, *, password="pw-test", code="654321", start="home", challenge_at=None, mfa_delay=0,
                 lose=()):
        self.screen = start
        #: Anzahl Abfragen, die die Code-Seite nach dem Abschicken noch sichtbar bleibt (wie live).
        self.mfa_delay, self.pending = mfa_delay, 0
        self.password, self.code, self.challenge_at = password, code, challenge_at
        self.filled: dict[str, str] = {}
        self.clicks: list[str] = []
        self.gotos: list[str] = []
        self.texts = {'[role="alert"]': "Falsches Passwort"}
        self.element_urls: dict[str, str] = {}
        self.typed: list[str] = []
        self.waits: list[int] = []
        self.lose = set(lose)
        #: Adressen, die page.url noch liefert, obwohl schon die neue Seite geladen ist (Seitenwechsel).
        self.stale_urls: list[str] = []
        self.lag_after_email = False

    @property
    def url(self):
        if self.stale_urls:
            return self.stale_urls.pop(0)
        return self.SCREENS[self._tick()][0]

    def _tick(self):
        if self.stale_urls:
            return None
        if self.pending:
            self.pending -= 1
            if not self.pending:
                self.screen = "done"
        return self.screen

    def title(self):
        return "Just a moment..." if self.screen == "challenge" else "ChatGPT"

    def visible(self):
        return self.SCREENS[self.screen][1]

    def locator(self, selector):
        return FakeLocator(self, selector)

    def goto(self, url, **kwargs):
        self.gotos.append(url)
        self.screen = "home"

    def wait_for_timeout(self, ms):
        self.waits.append(ms)

    def click(self, selector):
        self.clicks.append(selector)
        if self.screen == "home" and selector == "button[data-login-button]":
            self.screen = "email"
        elif self.screen == "email" and "submit" in selector:
            self.screen = self.challenge_at or "password"
            if self.lag_after_email:
                self.stale_urls = ["https://chatgpt.com/"]   # naechste Abfrage: noch die alte Adresse
        elif self.screen in ("password", "password_error") and "validate" in selector:
            ok = self.filled.get('input[name="current-password"]') == self.password
            self.screen = "mfa" if ok else "password_error"
            if ok and getattr(self, "lag_after_password", False):
                # naechste Abfrage: noch die Passwortseite, das Codefeld ist aber schon da
                self.stale_urls = ["https://auth.openai.com/log-in/password"]
        elif self.screen == "mfa" and "verify" in selector:
            if self.filled.get('input[autocomplete="one-time-code"]') == self.code:
                if self.mfa_delay:
                    self.pending = self.mfa_delay
                else:
                    self.screen = "done"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


def _login(page, *, auth=None, code="654321", timeout=200, codes=None, clock=None, **options):
    said, events = [], []
    supply = iter(codes) if codes else None
    login = AutoLogin(page, auth or _auth(), is_logged_in=lambda: page.screen == "done", say=said.append,
                      trace=lambda e, d: events.append((e, d)),
                      code_source=lambda: totp.OneTimeCode(next(supply) if supply else code, 25),
                      clock=clock or Clock(), **options)
    return login.run(timeout), said, events


def test_full_flow_like_the_recording():
    page = FakePage()
    result, said, events = _login(page)
    assert result.ok and result.reason == "angemeldet"
    assert result.steps == ["login_button", "email", "password", "mfa", "chatgpt"]
    assert page.filled == {"input#mobile-auth-email": "nutzer@example.org",
                           'input[name="current-password"]': "pw-test",
                           'input[autocomplete="one-time-code"]': "654321"}
    text = "\n".join(said) + json.dumps(events)
    for secret in ("nutzer@example.org", "pw-test", "654321"):
        assert secret not in text, "keine Zugangsdaten/Codes in Ausgaben"


def test_wrong_password_stops_after_one_attempt():
    page = FakePage(password="anderes")
    result, _, _ = _login(page)
    assert not result.ok and result.rejected and "Falsches Passwort" in result.reason
    assert page.clicks.count('button[name="intent"][value="validate"]') == 1


def test_challenge_is_never_bypassed():
    page = FakePage(challenge_at="challenge")
    result, _, _ = _login(page)
    assert not result.ok and result.needs_user and "Sicherheitspruefung" in result.reason
    assert 'input[name="current-password"]' not in page.filled


def test_email_code_is_handed_to_the_user():
    page = FakePage(start="email_code")
    result, _, _ = _login(page)
    assert result.needs_user and "Code per E-Mail" in result.reason and not page.filled


@pytest.mark.parametrize("url", [
    "https://evil.example/log-in/password",            # fremde Seite
    "https://chatgpt.com/log-in/password",             # ChatGPT selbst fragt nie nach dem Passwort
    "http://auth.openai.com/log-in/password",          # ohne https
    "https://login.auth.openai.com/log-in/password",   # Subdomain
    "https://auth.openai.com.evil.example/log-in",     # aehnlicher Name
])
def test_password_is_only_entered_on_the_real_login_page(url):
    """Nach der E-Mail landet der Ablauf auf einer Passwortseite mit falscher Adresse."""
    page = FakePage()
    page.SCREENS = {**FakePage.SCREENS, "password": (url, FakePage.SCREENS["password"][1])}
    result, said, _ = _login(page)
    assert not result.ok and result.needs_user and "nicht erwarteten Seite" in result.reason
    assert 'input[name="current-password"]' not in page.filled, "Passwort nie eingetragen"
    assert not any("validate" in c for c in page.clicks)
    assert result.steps[-1] == "foreign"


def test_email_and_code_are_not_entered_on_foreign_pages():
    page = FakePage()
    page.SCREENS = {**FakePage.SCREENS, "email": ("https://chatgpt.example/", FakePage.SCREENS["email"][1])}
    result, _, _ = _login(page)
    assert not result.ok and "nicht erwarteten Seite" in result.reason and page.filled == {}
    page = FakePage()
    page.SCREENS = {**FakePage.SCREENS, "mfa": ("https://evil.example/mfa-challenge/1", FakePage.SCREENS["mfa"][1])}
    result, _, _ = _login(page)
    assert not result.ok and "nicht erwarteten Seite" in result.reason
    assert 'input[autocomplete="one-time-code"]' not in page.filled, "Einmalcode nie eingetragen"


def test_field_from_a_foreign_frame_is_never_filled():
    """Seite stimmt, das Feld gehoert aber zu einem fremden Dokument (z. B. eingebetteter Rahmen)."""
    page = FakePage(start="password")
    page.element_urls['input[name="current-password"]'] = "https://evil.example/frame"
    result, _, events = _login(page)
    assert not result.ok and result.needs_user and "evil.example" in result.reason
    assert page.filled == {}
    assert ("login_foreign_page", {"state": "password", "where": "evil.example"}) in events


def test_visited_pages_are_reported_without_query():
    page = FakePage()
    result, _, _ = _login(page)
    assert result.pages == ["chatgpt.com/", "auth.openai.com/log-in/password",
                            "auth.openai.com/mfa-challenge/6aa46adc", "chatgpt.com/"]


def test_wrong_one_time_code_is_tried_twice_at_most_and_with_a_new_code():
    page = FakePage(code="111111")
    result, _, _ = _login(page, codes=["999999", "999999", "888888"])
    assert not result.ok and result.rejected and "zweimal" in result.reason
    assert page.clicks.count('button[name="intent"][value="verify"]') == 2
    assert page.filled['input[autocomplete="one-time-code"]'] == "888888", "Wiederholung nie mit demselben Code"


def test_slow_code_page_gets_the_code_only_once():
    """Live 2026-10-04: Die Code-Seite blieb nach dem Klick noch kurz sichtbar -> Code doppelt abgeschickt."""
    page = FakePage(mfa_delay=4)
    result, said, _ = _login(page)
    assert result.ok
    assert page.clicks.count('button[name="intent"][value="verify"]') == 1
    assert sum("Einmalcode" in line for line in said) == 1


def test_blank_page_navigates_to_chatgpt_and_timeout_is_reported():
    page = FakePage(start="blank")
    result, _, _ = _login(page)
    assert result.ok and page.gotos == ["https://chatgpt.com/"]
    stuck = FakePage(start="home")
    stuck.click = lambda selector: None          # Dialog oeffnet sich nie
    result, _, _ = _login(stuck, timeout=60)
    assert not result.ok and "Anmeldedialog" in result.reason


# -- Einstieg, Sperrschutz ----------------------------------------------------------------------------

class Session:
    def __init__(self, page):
        self.page = page

    def ensure_chatgpt_page(self):
        return self.page


def _cfg(tmp_path, **auth) -> AppConfig:
    cfg = AppConfig()
    cfg.auth = _auth(**auth)
    cfg.storage.runtime_root = tmp_path / "runtime"
    return cfg


def test_make_auto_login_modes(tmp_path, monkeypatch):
    assert make_auto_login(_cfg(tmp_path, auto_login="off"), Session(None)) is None
    assert make_auto_login(_cfg(tmp_path, username=None, password=None), Session(None)) is None, "auto ohne Daten"
    run = make_auto_login(_cfg(tmp_path, auto_login="on", username=None, password=None), Session(None))
    assert "Zugangsdaten fehlen" in run(lambda: False).reason


def test_rejected_credentials_are_not_retried_until_changed(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    block = auto_login.default_block_file(cfg)
    attempts = []

    def fake_run(self, timeout):
        attempts.append(1)
        return LoginResult(False, "Anmeldeseite meldet: Falsches Passwort", rejected=True)

    monkeypatch.setattr(AutoLogin, "run", fake_run)
    run = make_auto_login(cfg, Session(FakePage()), block_file=block, say=lambda m: None)
    assert run(lambda: False).rejected and block.is_file()
    stored = json.loads(block.read_text(encoding="utf-8"))
    assert set(stored) == {"fingerprint", "reason", "at"} and "pw-test" not in block.read_text(encoding="utf-8")
    second = run(lambda: False)
    assert "zuletzt abgelehnt" in second.reason and len(attempts) == 1, "kein zweiter Versuch"
    forced = make_auto_login(cfg, Session(FakePage()), block_file=block, say=lambda m: None, force=True)
    forced(lambda: False)
    assert len(attempts) == 2, "chatgpt login versucht trotzdem"
    cfg.auth.password = "neues-passwort"
    monkeypatch.setattr(AutoLogin, "run", lambda self, timeout: LoginResult(True, "angemeldet"))
    assert make_auto_login(cfg, Session(FakePage()), block_file=block, say=lambda m: None)(lambda: True).ok
    assert not block.exists(), "Erfolg hebt den Vermerk auf"


# -- AuthBroker -------------------------------------------------------------------------------------------

class Response:
    def __init__(self, status, payload):
        self.status, self._payload = status, payload

    def json(self):
        return self._payload

    def text(self):
        return json.dumps(self._payload)


class Context:
    def __init__(self):
        self.logged_in = False
        self.request = self

    def get(self, url, **kwargs):
        if url.endswith("/api/auth/session"):
            return Response(200, {"accessToken": "tok", "user": {"id": "user-1", "email": "n@example.org"}}
                            if self.logged_in else {})
        return Response(200, {"id": "user-1", "email": "n@example.org", "name": "N"})


class Cdp:
    def __init__(self):
        self.context = Context()

    def ensure_chatgpt_page(self):
        return object()


def test_broker_logs_in_automatically_also_without_interaction():
    from chatexporter.providers.chatgpt.auth.broker import AuthBroker
    from chatexporter.providers.chatgpt.auth.session import ReauthenticationRequired
    cdp = Cdp()

    def auto(is_logged_in):
        cdp.context.logged_in = True
        return LoginResult(True, "angemeldet") if is_logged_in() else LoginResult(False, "nein")

    session = AuthBroker(cdp, "https://chatgpt.com", 1000, auto_login=auto).acquire(interactive=False)
    assert session.access_token == "tok"
    failing = AuthBroker(Cdp(), "https://chatgpt.com", 1000,
                         auto_login=lambda ok: LoginResult(False, "Sicherheitspruefung", needs_user=True))
    with pytest.raises(ReauthenticationRequired, match="Automatische Anmeldung: Sicherheitspruefung"):
        failing.acquire(interactive=False)
    assert failing.auto_login_result.needs_user


# -- menschliches Vorgehen, schrittweise Anmeldung ----------------------------------------------------

def test_human_pace_pauses_before_each_step_and_types_character_by_character():
    page = FakePage()
    result, _, _ = _login(page)
    assert result.ok
    assert page.typed.count("input#mobile-auth-email") == len("nutzer@example.org")
    assert page.typed.count('input[name="current-password"]') == len("pw-test")
    assert page.typed.count('input[autocomplete="one-time-code"]') == 6
    assert sum(ms >= 1500 for ms in page.waits) >= 4, "Pause vor jedem der vier Schritte"
    assert all(60 <= ms <= 180 for ms in page.waits if ms < 300), "Tastenabstaende zufaellig, aber kurz"
    assert page.filled["input#mobile-auth-email"] == "nutzer@example.org"


def test_without_human_pace_values_are_set_at_once():
    page = FakePage()
    result, _, _ = _login(page, human=False)
    assert result.ok and page.typed == [] and not any(ms >= 1500 for ms in page.waits)


def test_typing_falls_back_when_characters_get_lost():
    page = FakePage(lose=("input#mobile-auth-email",))
    result, said, events = _login(page)
    assert result.ok and page.filled["input#mobile-auth-email"] == "nutzer@example.org"
    assert ("login_typing_fallback", {}) in events
    assert "nutzer@example.org" not in json.dumps(events) + "\n".join(said)


def test_step_by_step_asks_before_every_step_and_shows_where():
    page = FakePage()
    asked: list[tuple[str, str]] = []
    result, _, _ = _login(page, confirm=lambda state, text: asked.append((state, text)) or True)
    assert result.ok
    assert [state for state, _ in asked] == ["login_button", "email", "password", "mfa"]
    assert "https://auth.openai.com/log-in/password" in asked[2][1] and "Passwort eintippen" in asked[2][1]
    joined = "\n".join(text for _, text in asked)
    for secret in ("nutzer@example.org", "pw-test", "654321"):
        assert secret not in joined


def test_step_by_step_abort_enters_nothing_more():
    page = FakePage()
    result, _, _ = _login(page, confirm=lambda state, text: state != "password")
    assert not result.ok and result.needs_user and "abgebrochen" in result.reason
    assert 'input[name="current-password"]' not in page.filled


def test_waiting_for_the_user_does_not_count_against_the_timeout():
    page = FakePage()
    clock = Clock()

    def slow_user(state, text):
        clock.now += 500                               # Benutzer laesst sich Zeit
        return True
    result, _, _ = _login(page, timeout=200, clock=clock, confirm=slow_user)
    assert result.ok


def test_page_change_between_reading_the_address_and_finding_the_field_is_no_foreign_page():
    """Live 2026-10-05 (--schrittweise): page.url noch chatgpt.com, Passwortfeld schon von
    auth.openai.com -> faelschlich "nicht erwartete Seite". Ein Seitenwechsel ist kein fremder Host."""
    page = FakePage()
    page.lag_after_email = True
    result, _, _ = _login(page)
    assert result.ok, result.reason
    assert "foreign" not in result.steps
    assert page.filled['input[name="current-password"]'] == "pw-test"


def test_code_page_reached_during_a_page_change_is_not_mistaken_for_an_email_code():
    """Live 2026-10-05 (Gesamttest): Adresse noch .../log-in/password, Codefeld schon von
    .../mfa-challenge/... -> faelschlich "Code per E-Mail" und Abbruch. Ein Seitenwechsel ist kein
    anderer Code-Typ; entschieden wird erst, wenn Adresse und Feld zur selben Seite gehoeren."""
    page = FakePage()
    page.lag_after_password = True
    result, said, _ = _login(page)
    assert result.ok, result.reason
    assert "code_other" not in result.steps
    assert page.filled['input[autocomplete="one-time-code"]'] == "654321"


def test_real_email_code_page_is_still_handed_to_the_user():
    page = FakePage(start="email_code")
    result, _, _ = _login(page)
    assert result.needs_user and "Code per E-Mail" in result.reason and not page.filled
