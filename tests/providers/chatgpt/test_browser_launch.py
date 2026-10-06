"""CDP-Start und Aufraeumen (EdgeCdpSession) sowie Chrome-for-Testing-Installation."""

from __future__ import annotations

import io
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from chatexporter.providers.chatgpt.auth import chrome_for_testing as cft
from chatexporter.providers.chatgpt.auth import edge_cdp
from chatexporter.providers.chatgpt.auth.edge_cdp import BrowserLaunchError, EdgeCdpSession
from chatexporter.providers.chatgpt.config.models import BrowserConfig


class FakeProcess:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code
        self.terminated = False

    def poll(self):
        return self.exit_code if not self.terminated else 0

    def wait(self, timeout=None):
        if self.exit_code is None and not self.terminated:
            import subprocess
            raise subprocess.TimeoutExpired("x", timeout or 0)
        return self.exit_code

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.terminated = True


@pytest.fixture
def browser(tmp_path):
    exe = tmp_path / "chrome.exe"
    exe.write_text("", encoding="utf-8")
    return replace(BrowserConfig(), kind="chrome", executable=exe, user_data_dir=tmp_path / "profil",
                   connect_timeout_ms=500)


@pytest.mark.parametrize("kind,browser_name,ok", [
    ("edge", "Edg/154.0", True), ("edge", "Chrome/154.0", False),
    ("chrome", "Chrome/154.0", True), ("chrome", "Edg/154.0", False),
    ("chrome_for_testing", "Chrome/150.0", True), ("chrome", "Firefox", False),
])
def test_endpoint_must_belong_to_the_expected_browser(monkeypatch, kind, browser_name, ok):
    monkeypatch.setattr(edge_cdp, "_cdp_version", lambda endpoint: {"Browser": browser_name})
    if ok:
        edge_cdp._assert_endpoint("http://127.0.0.1:9223", kind)
    else:
        with pytest.raises(BrowserLaunchError):
            edge_cdp._assert_endpoint("http://127.0.0.1:9223", kind)


def test_unreachable_endpoint_is_an_error(monkeypatch):
    monkeypatch.setattr(edge_cdp, "_cdp_version", lambda endpoint: None)
    with pytest.raises(BrowserLaunchError, match="nicht erreichbar"):
        edge_cdp._assert_endpoint("http://127.0.0.1:9223", "edge")


def test_profile_in_use_is_never_launched(monkeypatch, browser):
    monkeypatch.setattr(edge_cdp, "_cdp_endpoint_reachable", lambda endpoint: False)
    monkeypatch.setattr(edge_cdp, "profile_in_use", lambda path: True)
    monkeypatch.setattr(edge_cdp.subprocess, "Popen", lambda *a, **k: pytest.fail("darf nicht starten"))
    with pytest.raises(BrowserLaunchError, match="laeuft bereits"):
        EdgeCdpSession(browser).connect()


def test_browser_exiting_early_is_reported(monkeypatch, browser):
    monkeypatch.setattr(edge_cdp, "_cdp_endpoint_reachable", lambda endpoint: False)
    monkeypatch.setattr(edge_cdp, "profile_in_use", lambda path: False)
    monkeypatch.setattr(edge_cdp.subprocess, "Popen", lambda *a, **k: FakeProcess(exit_code=3))
    with pytest.raises(BrowserLaunchError, match="Exitcode 3"):
        EdgeCdpSession(browser).connect()


def test_timeout_terminates_the_started_browser(monkeypatch, browser):
    started = []
    monkeypatch.setattr(edge_cdp, "_cdp_endpoint_reachable", lambda endpoint: False)
    monkeypatch.setattr(edge_cdp, "profile_in_use", lambda path: False)

    def popen(args, **kwargs):
        started.append((args, FakeProcess()))
        return started[-1][1]
    monkeypatch.setattr(edge_cdp.subprocess, "Popen", popen)
    session = EdgeCdpSession(browser)
    with pytest.raises(BrowserLaunchError, match="nicht erreichbar"):
        session.connect()
    args, process = started[0]
    assert process.terminated, "ein selbst gestarteter Browser wird bei Fehlschlag beendet"
    assert session.started_process is None
    assert f"--user-data-dir={browser.user_data_dir}" in args and "--remote-debugging-port=9223" in args
    assert Path(args[0]) == browser.executable


def test_missing_program_is_reported(monkeypatch, browser, tmp_path):
    monkeypatch.setattr(edge_cdp, "_cdp_endpoint_reachable", lambda endpoint: False)
    missing = replace(browser, executable=tmp_path / "fehlt.exe")
    with pytest.raises(FileNotFoundError, match="fehlt.exe"):
        EdgeCdpSession(missing).connect()


def test_no_launch_when_disabled(monkeypatch, browser):
    monkeypatch.setattr(edge_cdp, "_cdp_endpoint_reachable", lambda endpoint: False)
    with pytest.raises(BrowserLaunchError, match="launch_if_needed"):
        EdgeCdpSession(replace(browser, launch_if_needed=False)).connect()


def test_abandon_is_safe_without_anything_started(browser):
    session = EdgeCdpSession(browser)
    session.abandon()
    assert session.started_process is None


# -- Chrome for Testing --------------------------------------------------------------------

def test_latest_release_parsing():
    data = {"channels": {"Stable": {"version": "150.0.1.2", "downloads": {"chrome": [
        {"platform": "linux64", "url": "https://x/linux.zip"},
        {"platform": "win64", "url": "https://x/win64.zip"}]}}}}
    assert cft.latest_release("u", fetch=lambda url: data) == cft.Release("150.0.1.2", "https://x/win64.zip")
    with pytest.raises(cft.ChromeForTestingError, match="unvollstaendig"):
        cft.latest_release("u", fetch=lambda url: {"channels": {}})
    with pytest.raises(cft.ChromeForTestingError, match="nicht abrufbar"):
        cft.latest_release("u", fetch=lambda url: (_ for _ in ()).throw(OSError("offline")))


def _zip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buffer.getvalue()


def _downloader(payload: bytes):
    def download(url, target, progress):
        target.write_bytes(payload)
    return download


def test_install_extracts_atomically_and_reuses(tmp_path, monkeypatch):
    monkeypatch.setattr(cft, "MIN_ZIP_BYTES", 0)
    release = cft.Release("150.0.1.2", "https://x/win64.zip")
    payload = _zip({"chrome-win64/chrome.exe": b"exe", "chrome-win64/other.dll": b"dll"})
    exe = cft.install(tmp_path, release, download=_downloader(payload))
    assert exe == tmp_path / "chrome-for-testing" / "150.0.1.2" / "chrome-win64" / "chrome.exe" and exe.is_file()
    assert not list((tmp_path / "chrome-for-testing").glob(".*.partial"))
    assert not list((tmp_path / "chrome-for-testing" / ".download").iterdir()), "Archiv wird entfernt"
    assert cft.install(tmp_path, release, download=lambda *a: pytest.fail("kein zweiter Download")) == exe
    assert cft.installed_executable(tmp_path) == exe


@pytest.mark.parametrize("payload,message", [
    (b"kein zip", "kein ZIP"),
    (_zip({"chrome-win64/readme.txt": b"x"}), "fehlt im Archiv"),
    (_zip({"../boese.exe": b"x"}), "unzulaessige Pfade"),
])
def test_install_rejects_broken_downloads(tmp_path, monkeypatch, payload, message):
    monkeypatch.setattr(cft, "MIN_ZIP_BYTES", 0)
    with pytest.raises(cft.ChromeForTestingError, match=message):
        cft.install(tmp_path, cft.Release("1.2.3.4", "https://x"), download=_downloader(payload))
    assert cft.installed_executable(tmp_path) is None
    assert not (tmp_path / "chrome-for-testing" / "1.2.3.4").exists()


def test_install_rejects_too_small_download(tmp_path):
    with pytest.raises(cft.ChromeForTestingError, match="zu klein"):
        cft.install(tmp_path, cft.Release("1.2.3.4", "https://x"), download=_downloader(b"x"))


def test_installed_executable_picks_the_newest(tmp_path):
    for version in ("120.0.0.1", "150.0.0.1", ".partial", "kaputt"):
        exe = tmp_path / "chrome-for-testing" / version / "chrome-win64" / "chrome.exe"
        exe.parent.mkdir(parents=True)
        exe.write_text("", encoding="utf-8")
    assert cft.installed_executable(tmp_path).parts[-3] == "150.0.0.1"


def test_launcher_stub_exiting_with_zero_keeps_waiting(monkeypatch, browser):
    """Edge/Chrome starten sich teils ueber einen Zwischenprozess neu (Exitcode 0)."""
    calls = {"n": 0}

    def reachable(endpoint):
        calls["n"] += 1
        return calls["n"] > 4
    monkeypatch.setattr(edge_cdp, "_cdp_endpoint_reachable", reachable)
    monkeypatch.setattr(edge_cdp.time if hasattr(edge_cdp, "time") else __import__("time"), "sleep", lambda s: None)
    session = EdgeCdpSession(replace(browser, connect_timeout_ms=5000))
    session.started_process = FakeProcess(exit_code=0)
    session.launched = True
    session._wait_until_cdp_reachable()          # darf nicht mit "Exitcode 0" scheitern
    assert calls["n"] > 4


def test_close_without_leave_running_closes_a_launched_browser(monkeypatch, browser):
    closed = []
    session = EdgeCdpSession(replace(browser, leave_browser_running=False))
    session.launched = True
    monkeypatch.setattr(session, "_close_launched_browser", lambda: closed.append(True))
    session.close()
    assert closed == [True]
    other = EdgeCdpSession(replace(browser, leave_browser_running=False))
    monkeypatch.setattr(other, "_close_launched_browser", lambda: closed.append("fremd"))
    other.close()
    assert closed == [True], "ein nicht selbst gestarteter Browser wird nie geschlossen"


def test_browser_starts_empty_and_chatgpt_opens_after_connecting(monkeypatch, browser):
    """Mit ChatGPT als Startseite hing die CDP-Verbindung (Chrome for Testing, 2026-10-04);
    deshalb leer starten und die leere Seite danach fuer ChatGPT wiederverwenden."""
    started = []
    monkeypatch.setattr(edge_cdp, "_cdp_endpoint_reachable", lambda endpoint: False)
    monkeypatch.setattr(edge_cdp, "profile_in_use", lambda path: False)

    def popen(args, **kwargs):
        started.append(args)
        return FakeProcess()
    monkeypatch.setattr(edge_cdp.subprocess, "Popen", popen)
    with pytest.raises(BrowserLaunchError):
        EdgeCdpSession(browser).connect()
    assert started[0][-1] == "about:blank" and browser.open_url not in started[0]

    class Page:
        def __init__(self, url):
            self.url, self.visited = url, []

        def goto(self, url, **kwargs):
            self.visited.append(url)
            self.url = url

    class Context:
        def __init__(self, pages):
            self.pages, self.created = pages, []

        def new_page(self):
            page = Page("about:blank")
            self.created.append(page)
            return page

    session = EdgeCdpSession(browser)
    blank = Page("about:blank")
    session.context = Context([blank])
    assert session.ensure_chatgpt_page() is blank and blank.visited == [browser.open_url]
    assert session.context.created == [], "kein zusaetzlicher Tab"
    other = Page("https://example.org/")
    session.context = Context([other])
    page = session.ensure_chatgpt_page()
    assert page is not other and session.context.created == [page]


@pytest.mark.parametrize("kind, implicit", [("edge", True), ("chrome", False), ("chrome_for_testing", False)])
def test_own_browser_never_syncs_with_an_account(monkeypatch, browser, kind, implicit):
    """Edge verband neue Profile still mit dem Microsoft-Konto und holte Erweiterungen (2026-10-04)."""
    started = []
    monkeypatch.setattr(edge_cdp, "_cdp_endpoint_reachable", lambda endpoint: False)
    monkeypatch.setattr(edge_cdp, "profile_in_use", lambda path: False)
    monkeypatch.setattr(edge_cdp.subprocess, "Popen", lambda args, **kw: started.append(args) or FakeProcess())
    with pytest.raises(BrowserLaunchError):
        EdgeCdpSession(replace(browser, kind=kind)).connect()
    assert "--disable-sync" in started[0]
    assert ("--disable-features=msImplicitSignin" in started[0]) is implicit
    assert started[0][-1] == "about:blank"
