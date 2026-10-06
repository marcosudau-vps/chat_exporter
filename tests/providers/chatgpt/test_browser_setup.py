"""Browser-/Profilsuche: Reihenfolge, Profilkopie, Ueberspringen, Aufraeumen, Anmeldung, Download, Merken."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest

from chatexporter.providers.chatgpt.auth import browsers
from chatexporter.providers.chatgpt.auth.browser_setup import BrowserSetup, BrowserSetupError
from chatexporter.providers.chatgpt.auth.browsers import BrowserCandidate, build_candidates
from chatexporter.providers.chatgpt.auth.chrome_for_testing import Release
from chatexporter.providers.chatgpt.auth.profiles import BrowserProfile
from chatexporter.providers.chatgpt.auth.session import ReauthenticationRequired
from chatexporter.providers.chatgpt.config.models import AppConfig, BrowserConfig


# -- Bausteine ------------------------------------------------------------------------

class FakeSession:
    def __init__(self, config, log, fail=None):
        self.config, self.log, self.fail = config, log, fail
        self.abandoned = self.closed = False

    def connect(self):
        self.log.append(("connect", self.config.kind, str(self.config.user_data_dir), self.config.cdp_port))
        if self.fail:
            raise self.fail
        return self

    def abandon(self):
        self.abandoned = True
        self.log.append(("abandon", self.config.kind, str(self.config.user_data_dir)))

    def close(self):
        self.closed = True


class FakeBroker:
    def __init__(self, session, logged_in, log):
        self.session, self.logged_in, self.log = session, logged_in, log

    def acquire(self, interactive):
        self.log.append(("acquire", str(self.session.config.user_data_dir), interactive))
        if self.logged_in(self.session.config) or interactive:
            return f"auth:{self.session.config.user_data_dir}"
        raise ReauthenticationRequired("keine Sitzung")


def _cfg(tmp_path, *, configured=False, **browser) -> AppConfig:
    cfg = AppConfig(config_file=tmp_path / "config.yaml")
    cfg.browser = replace(BrowserConfig(), user_data_dir=tmp_path / "konfiguriert",
                          user_data_dir_configured=configured, browser_root=tmp_path / "browser", **browser)
    return cfg


def _cands(tmp_path, *keys):
    edge_profile = BrowserProfile("edge", tmp_path / "EdgeUD", "Default", "Privat", True, "Sitzungs-Cookie")
    table = {
        "edge-copy": BrowserCandidate("edge-Default-kopieren", "edge", Path("msedge.exe"),
                                      tmp_path / "b" / "profiles" / "2026-10-03_00-00-00_Default",
                                      copy_from=edge_profile),
        "edge-existing": BrowserCandidate("2026-10-01_00-00-00_Profile_1", "edge", Path("msedge.exe"),
                                          tmp_path / "p" / "2026-10-01_00-00-00_Profile_1", copy_name="Arbeit"),
        "edge-profile": BrowserCandidate("edge-profile", "edge", Path("msedge.exe"), tmp_path / "p" / "edge"),
        "chrome-profile": BrowserCandidate("chrome-profile", "chrome", Path("chrome.exe"), tmp_path / "p" / "chrome"),
        "chrome-for-testing": BrowserCandidate("chrome-for-testing", "chrome_for_testing", None,
                                               tmp_path / "p" / "cft", download=True),
    }
    return [table[k] for k in keys]


def _setup(tmp_path, cfg, cands, *, interactive=False, fail=(), logged_in=lambda c: True,
           in_use=(), answers=(), release=None, install=None, endpoint_busy=False, persist_error=None,
           cookies=(True, "Sitzungs-Cookie"), copy_error=None, close_error=None):
    log, said, persisted = [], [], []
    feed = iter(answers)
    in_use = list(in_use)

    def session_factory(config):
        failure = None
        for key, exc in fail:
            if str(config.user_data_dir).endswith(key):
                failure = exc
        return FakeSession(config, log, failure)

    def persist(values):
        if persist_error:
            raise persist_error
        persisted.append(values)

    def ask(prompt):
        log.append(("ask", prompt))
        return next(feed)

    class Closed:
        processes, forced = [], False

        def reopen(self, say):
            log.append(("reopen",))
            in_use.extend(["EdgeUD"])
            return "started"

    def close_browser(user_data_dir, executable, say, in_use=None):
        log.append(("close", str(user_data_dir)))
        if close_error:
            raise close_error
        in_use_list.clear()
        return Closed()

    in_use_list = in_use

    def copy(profile, target, say, in_use):
        log.append(("copy", str(profile.path), str(target)))
        if copy_error:
            raise copy_error
        return target

    setup = BrowserSetup(
        cfg, interactive=interactive, say=said.append, ask=ask, session_factory=session_factory,
        broker_factory=lambda s: FakeBroker(s, logged_in, log), candidates=lambda: cands, persist=persist,
        latest_release=(lambda url: release) if release else (lambda url: (_ for _ in ()).throw(OSError("offline"))),
        install=install or (lambda root, rel: (_ for _ in ()).throw(AssertionError("kein Download erwartet"))),
        endpoint_reachable=lambda endpoint: endpoint_busy and endpoint.endswith(":9223"),
        find_free_port=lambda host, start: start + 7,
        profile_in_use=lambda path: any(str(path).endswith(k) for k in in_use),
        cookie_status=lambda path: cookies, copy=copy, close_browser=close_browser,
        trace=lambda event, data: log.append(("trace", event)))
    return setup, log, said, persisted


# -- Reihenfolge der Wege ------------------------------------------------------------

def test_candidate_order_and_availability(tmp_path):
    exes = {"edge": tmp_path / "msedge.exe", "chrome": tmp_path / "chrome.exe"}
    edge_profiles = [BrowserProfile("edge", tmp_path / "EdgeUD", "Default", "Privat", True),
                     BrowserProfile("edge", tmp_path / "EdgeUD", "Profile 1", "Arbeit", None),
                     BrowserProfile("edge", tmp_path / "EdgeUD", "Profile 2", "Leer", False)]
    chrome_profiles = [BrowserProfile("chrome", tmp_path / "ChromeUD", "Default", "Ich", True)]
    found = {"edge": edge_profiles, "chrome": chrome_profiles}
    root = tmp_path / "b" / "profiles"
    newest = root / "2026-10-03_05-00-00_Profile_1"
    older = root / "2026-10-01_05-00-00_Profile_1"
    source = {"kind": "edge", "name": "Arbeit", "source": str(tmp_path / "EdgeUD" / "Profile 1")}
    cands = build_candidates(tmp_path / "b", find=exes.get, profiles=found.get,
                             copies=lambda r: [(newest, source), (older, source), (tmp_path / "x", {"kind": "opera"})])
    assert [c.key for c in cands] == ["2026-10-03_05-00-00_Profile_1", "edge-Default-kopieren",
                                      "chrome-Default-kopieren", "edge-profile", "chrome-profile",
                                      "chrome-for-testing"], "je Quelle nur die neueste Kopie; kopiert wird nur, was fehlt"
    assert cands[0].copy_name == "Arbeit" and cands[0].copy_from is None and cands[0].user_data_dir == newest
    assert cands[1].copy_from is edge_profiles[0], "Profil ohne ChatGPT-Cookies wird nicht kopiert"
    assert "Kopie von Profil 'Privat' anlegen" in cands[1].label
    assert cands[1].user_data_dir.parent == root and cands[1].user_data_dir.name.endswith("_Default")
    assert "kopie" not in cands[1].user_data_dir.name.lower()
    only_edge = build_candidates(tmp_path / "b", find=lambda k: exes["edge"] if k == "edge" else None,
                                 profiles=lambda k: [], copies=lambda root: [])
    assert [c.key for c in only_edge] == ["edge-profile", "chrome-for-testing"]
    nothing = build_candidates(tmp_path / "b", find=lambda k: None, profiles=found.get, copies=lambda r: [])
    assert [(c.key, c.download) for c in nothing] == [("chrome-for-testing", True)]
    cft = build_candidates(tmp_path / "b", installed_cft=tmp_path / "cft.exe", find=lambda k: None,
                           profiles=lambda k: [], copies=lambda r: [])
    assert cft[0].download is False and cft[0].executable == tmp_path / "cft.exe"
    assert cft[0].user_data_dir == tmp_path / "b" / "profiles" / "chrome_for_testing"


# -- fester Pfad --------------------------------------------------------------------------

def test_configured_profile_is_used_without_search(tmp_path):
    cfg = _cfg(tmp_path, configured=True)
    setup, log, said, persisted = _setup(tmp_path, cfg, _cands(tmp_path, "edge-existing"))
    session, auth, choice = setup.open()
    assert choice.mode == "configured" and choice.user_data_dir == str(tmp_path / "konfiguriert")
    assert [e[0] for e in log if e[0] != "trace"] == ["connect", "acquire"] and persisted == []


def test_configured_profile_without_login_fails_and_cleans_up(tmp_path):
    cfg = _cfg(tmp_path, configured=True)
    setup, log, _, _ = _setup(tmp_path, cfg, [], logged_in=lambda c: False)
    with pytest.raises(ReauthenticationRequired):
        setup.open()
    assert log[-1][0] == "abandon"


# -- automatische Suche ------------------------------------------------------------------------

def test_first_working_way_wins_and_is_remembered(tmp_path):
    cfg = _cfg(tmp_path)
    cands = _cands(tmp_path, "edge-existing", "edge-profile", "chrome-profile")
    setup, log, said, persisted = _setup(
        tmp_path, cfg, cands, fail=(("Profile_1", RuntimeError("CDP-Endpunkt wurde nicht erreichbar")),),
        logged_in=lambda c: not str(c.user_data_dir).endswith("edge"))
    session, auth, choice = setup.open()
    assert choice.mode == "search" and choice.kind == "chrome" and choice.user_data_dir.endswith("chrome")
    reasons = {a.key: (a.ok, a.reason) for a in choice.attempts}
    assert "Start/CDP fehlgeschlagen" in reasons["2026-10-01_00-00-00_Profile_1"][1]
    assert "keine ChatGPT-Anmeldung" in reasons["edge-profile"][1]
    assert reasons["chrome-profile"] == (True, "")
    assert persisted == [{"providers.chatgpt.browser.user_data_dir": choice.user_data_dir,
                          "providers.chatgpt.browser.kind": "chrome",
                          "providers.chatgpt.browser.executable": "chrome.exe"}]
    assert choice.persisted and any("nicht verwendet" in s for s in said)
    assert ("abandon", "edge", str(tmp_path / "p" / "edge")) in log, "Browser ohne Anmeldung wird beendet"
    events = [e[1] for e in log if e[0] == "trace"]
    assert events[0] == "candidates" and events[-1] == "chosen" and events.count("skipped") == 2


def test_existing_copy_is_used_directly(tmp_path):
    setup, log, _, persisted = _setup(tmp_path, _cfg(tmp_path), _cands(tmp_path, "edge-existing", "edge-profile"))
    _, _, choice = setup.open()
    assert choice.user_data_dir.endswith("2026-10-01_00-00-00_Profile_1") and not any(e[0] == "copy" for e in log)


# -- Profilkopie ------------------------------------------------------------------------------

def test_copy_needs_interaction(tmp_path):
    setup, log, _, _ = _setup(tmp_path, _cfg(tmp_path), _cands(tmp_path, "edge-copy", "edge-profile"))
    _, _, choice = setup.open()
    assert "nur bei interaktivem Start" in choice.attempts[0].reason
    assert not any(e[0] in ("copy", "ask") for e in log)


def test_copy_with_open_browser_closes_and_reopens_it(tmp_path):
    setup, log, said, persisted = _setup(tmp_path, _cfg(tmp_path), _cands(tmp_path, "edge-copy"),
                                         interactive=True, in_use=("EdgeUD",), answers=("",))
    _, _, choice = setup.open()
    asks = [e[1] for e in log if e[0] == "ask"]
    assert len(asks) == 1 and "[J/n]" in asks[0], "nur bestaetigen oder ueberspringen"
    assert any("Setup schliesst Microsoft Edge" in s for s in said)
    steps = [e[0] for e in log if e[0] in ("close", "copy", "reopen", "connect")]
    assert steps == ["close", "copy", "reopen", "connect"], "erst schliessen, kopieren, wieder oeffnen, dann CDP"
    copy_entry = next(e for e in log if e[0] == "copy")
    target = Path(copy_entry[2])
    assert target.parent == tmp_path / "b" / "profiles"
    assert re.fullmatch(r"\d{4}-\d\d-\d\d_\d\d-\d\d-\d\d_Default", target.name)
    assert choice.user_data_dir == str(target)
    assert persisted[0]["providers.chatgpt.browser.user_data_dir"] == str(target)
    events = [e[1] for e in log if e[0] == "trace"]
    assert events.index("copy_offer") < events.index("copy_browser_closed") < events.index("copy_done") \
        < events.index("copy_browser_reopened") < events.index("launch") < events.index("auth_ok")


def test_copy_with_closed_browser_needs_only_confirmation(tmp_path):
    setup, log, _, _ = _setup(tmp_path, _cfg(tmp_path), _cands(tmp_path, "edge-copy", "edge-profile"),
                              interactive=True, answers=("n",))
    _, _, choice = setup.open()
    assert choice.attempts[0].reason == "Profilkopie abgelehnt"
    assert not any(e[0] in ("copy", "close") for e in log)
    assert choice.user_data_dir.endswith("edge")


def test_browser_that_cannot_be_closed_is_skipped(tmp_path):
    setup, log, _, _ = _setup(tmp_path, _cfg(tmp_path), _cands(tmp_path, "edge-copy", "edge-profile"),
                              interactive=True, in_use=("EdgeUD",), answers=("j",),
                              close_error=OSError("haengt"))
    _, _, choice = setup.open()
    assert "liess sich nicht schliessen" in choice.attempts[0].reason and "haengt" in choice.attempts[0].reason
    assert not any(e[0] == "copy" for e in log) and choice.user_data_dir.endswith("edge")


def test_browser_is_reopened_even_if_the_copy_fails(tmp_path):
    setup, log, _, _ = _setup(tmp_path, _cfg(tmp_path), _cands(tmp_path, "edge-copy", "edge-profile"),
                              interactive=True, in_use=("EdgeUD",), answers=("j",), copy_error=OSError("Platte voll"))
    _, _, choice = setup.open()
    assert "Kopie fehlgeschlagen" in choice.attempts[0].reason
    assert [e[0] for e in log if e[0] in ("close", "copy", "reopen")] == ["close", "copy", "reopen"]


def test_copy_skipped_without_chatgpt_cookies_after_closing(tmp_path):
    setup, log, _, _ = _setup(tmp_path, _cfg(tmp_path), _cands(tmp_path, "edge-copy", "edge-profile"),
                              interactive=True, answers=("j",), cookies=(False, "keine ChatGPT-Cookies"))
    _, _, choice = setup.open()
    assert "keine ChatGPT-Anmeldung im Profil" in choice.attempts[0].reason
    assert not any(e[0] == "copy" for e in log)


def test_copy_failure_moves_on(tmp_path):
    setup, log, _, _ = _setup(tmp_path, _cfg(tmp_path), _cands(tmp_path, "edge-copy", "edge-profile"),
                              interactive=True, answers=("j",), copy_error=OSError("Platte voll"))
    _, _, choice = setup.open()
    assert "Kopie fehlgeschlagen" in choice.attempts[0].reason and "Platte voll" in choice.attempts[0].reason
    assert choice.user_data_dir.endswith("edge")


def test_interactive_asks_for_login_in_the_first_working_profile(tmp_path):
    cfg = _cfg(tmp_path)
    setup, log, said, _ = _setup(tmp_path, cfg, _cands(tmp_path, "edge-existing", "edge-profile"),
                                 interactive=True, logged_in=lambda c: False)
    _, auth, choice = setup.open()
    copy = str(tmp_path / "p" / "2026-10-01_00-00-00_Profile_1")
    assert choice.user_data_dir == copy and ("acquire", copy, True) in log


def test_all_ways_fail_with_all_reasons(tmp_path):
    cfg = _cfg(tmp_path)
    setup, log, _, persisted = _setup(tmp_path, cfg, _cands(tmp_path, "edge-profile", "chrome-for-testing"),
                                      fail=(("edge", OSError("kaputt")),))
    with pytest.raises(BrowserSetupError) as exc:
        setup.open()
    text = str(exc.value)
    assert "kaputt" in text and "Download nur bei interaktivem Start" in text
    assert [a.ok for a in exc.value.attempts] == [False, False] and persisted == []


def test_busy_cdp_port_uses_a_free_port_and_remembers_it(tmp_path):
    cfg = _cfg(tmp_path)
    setup, log, said, persisted = _setup(tmp_path, cfg, _cands(tmp_path, "edge-profile"), endpoint_busy=True)
    _, _, choice = setup.open()
    assert choice.cdp_port == 9223 + 1 + 7
    assert [e for e in log if e[0] == "connect"][0][3] == choice.cdp_port
    assert persisted[0]["providers.chatgpt.browser.cdp_port"] == choice.cdp_port


def test_persist_failure_does_not_stop_the_run(tmp_path):
    cfg = _cfg(tmp_path)
    setup, _, said, _ = _setup(tmp_path, cfg, _cands(tmp_path, "edge-profile"), persist_error=OSError("schreibgeschuetzt"))
    session, auth, choice = setup.open()
    assert not choice.persisted and "schreibgeschuetzt" in choice.persist_error
    assert any("nicht eingetragen" in s for s in said)


def test_keyboard_interrupt_during_login_cleans_up(tmp_path):
    cfg = _cfg(tmp_path)

    class InterruptBroker:
        def __init__(self, session):
            self.session = session

        def acquire(self, interactive):
            raise KeyboardInterrupt

    setup, log, _, _ = _setup(tmp_path, cfg, _cands(tmp_path, "edge-profile"), interactive=True)
    setup.broker_factory = InterruptBroker
    with pytest.raises(KeyboardInterrupt):
        setup.open()
    assert log[-1][0] == "abandon"


# -- Chrome for Testing ------------------------------------------------------------------------

def test_download_requires_interaction_permission_and_confirmation(tmp_path):
    release = Release("150.0.1.2", "https://example.invalid/chrome.zip")
    for kwargs, expected in (({"interactive": False}, "nur bei interaktivem Start"),
                             ({"interactive": True, "answers": ("n",)}, "abgelehnt")):
        setup, log, _, _ = _setup(tmp_path, _cfg(tmp_path), _cands(tmp_path, "chrome-for-testing"),
                                  release=release, **kwargs)
        with pytest.raises(BrowserSetupError) as exc:
            setup.open()
        assert expected in str(exc.value)
    setup, log, _, _ = _setup(tmp_path, _cfg(tmp_path, allow_download=False),
                              _cands(tmp_path, "chrome-for-testing"), interactive=True, answers=("j",),
                              release=release)
    with pytest.raises(BrowserSetupError, match="abgeschaltet"):
        setup.open()


def test_download_after_confirmation_is_used(tmp_path):
    release = Release("150.0.1.2", "https://example.invalid/chrome.zip")
    installed = []

    def install(root, rel):
        installed.append((root, rel.version))
        return tmp_path / "cft" / "chrome.exe"

    setup, log, _, persisted = _setup(tmp_path, _cfg(tmp_path), _cands(tmp_path, "chrome-for-testing"),
                                      interactive=True, answers=("j",), release=release, install=install)
    _, _, choice = setup.open()
    assert installed == [(tmp_path / "browser", "150.0.1.2")]
    assert choice.kind == "chrome_for_testing" and choice.executable == str(tmp_path / "cft" / "chrome.exe")
    assert any(e[0] == "ask" and "150.0.1.2" in e[1] for e in log)


def test_download_failures_are_reported(tmp_path):
    release = Release("150.0.1.2", "https://example.invalid/chrome.zip")
    setup, _, _, _ = _setup(tmp_path, _cfg(tmp_path), _cands(tmp_path, "chrome-for-testing"),
                            interactive=True, answers=("j",), release=release,
                            install=lambda root, rel: (_ for _ in ()).throw(OSError("Netz weg")))
    with pytest.raises(BrowserSetupError, match="Netz weg"):
        setup.open()
    setup, _, _, _ = _setup(tmp_path, _cfg(tmp_path), _cands(tmp_path, "chrome-for-testing"), interactive=True)
    with pytest.raises(BrowserSetupError, match="Versionsliste"):
        setup.open()


# -- Erkennung auf dem Rechner -------------------------------------------------------------------

def test_browser_version_and_default_dir_detection(tmp_path, monkeypatch):
    app = tmp_path / "Application"
    for name in ("120.0.1.2", "154.0.8037.97", "SetupMetrics"):
        (app / name).mkdir(parents=True)
    assert browsers.browser_version(app / "chrome.exe") == (154, 0, 8037, 97)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "la"))
    assert browsers.default_user_data_dir("edge") == tmp_path / "la" / "Microsoft" / "Edge" / "User Data"
    (tmp_path / "la" / "Google" / "Chrome" / "User Data").mkdir(parents=True)
    assert browsers.is_default_user_data_dir(tmp_path / "la" / "Google" / "Chrome" / "User Data")
    assert not browsers.is_default_user_data_dir(tmp_path / "eigen")
    assert browsers.find_executable("chrome", tmp_path / "fehlt.exe") is None


def test_find_free_port():
    assert browsers.find_free_port("127.0.0.1", 9000, span=5, is_free=lambda h, p: p == 9003) == 9003
    assert browsers.find_free_port("127.0.0.1", 9000, span=3, is_free=lambda h, p: False) is None


@pytest.mark.skipif(not hasattr(__import__("sys"), "getwindowsversion"), reason="nur Windows")
def test_profile_in_use_detects_an_exclusively_opened_lockfile(tmp_path):
    import ctypes
    from ctypes import wintypes
    assert browsers.profile_in_use(tmp_path) is False                  # keine lockfile
    lock = tmp_path / "lockfile"
    lock.write_text("", encoding="utf-8")
    assert browsers.profile_in_use(tmp_path) is False                  # vorhanden, aber frei
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                     wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    handle = kernel32.CreateFileW(str(lock), 0x40000000, 0, None, 3, 0x80, None)   # exklusiv wie Chromium
    try:
        assert browsers.profile_in_use(tmp_path) is True
    finally:
        kernel32.CloseHandle(handle)
    assert browsers.profile_in_use(tmp_path) is False


def test_downloads_use_the_system_certificate_store(monkeypatch):
    """Frisches Windows: Pruefung ueber den Windows-Zertifikatsspeicher (truststore), sonst Standard."""
    import ssl
    import sys
    from chatexporter.providers.chatgpt.auth import chrome_for_testing as cft
    truststore = pytest.importorskip("truststore")
    assert isinstance(cft.ssl_context(), truststore.SSLContext)
    monkeypatch.setitem(sys.modules, "truststore", None)          # nicht installiert
    context = cft.ssl_context()
    assert isinstance(context, ssl.SSLContext) and context.verify_mode == ssl.CERT_REQUIRED
