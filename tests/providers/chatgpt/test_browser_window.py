"""Browserfenster: verborgen arbeiten, nur zum Eingeben zeigen (``providers.chatgpt.browser.window``)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from chatexporter.providers.chatgpt.auth import edge_cdp
from chatexporter.providers.chatgpt.auth.edge_cdp import (OFFSCREEN, VISIBLE_BOUNDS, BrowserLaunchError,
                                                          EdgeCdpSession)
from chatexporter.providers.chatgpt.config.models import BrowserConfig


class CdpSession:
    def __init__(self, log, fail):
        self.log, self.fail = log, fail

    def send(self, method, params=None):
        if self.fail:
            raise RuntimeError("Fenster nicht gefunden")
        if method == "Target.getTargetInfo":
            return {"targetInfo": {"targetId": "T1"}}
        if method == "Browser.getWindowForTarget":
            return {"windowId": 7}
        self.log.append(params["bounds"])
        return {}

    def detach(self):
        pass


class Browser:
    def __init__(self, log, fail=False):
        self.log, self.fail = log, fail

    def new_browser_cdp_session(self):
        return CdpSession(self.log, self.fail)


class Context:
    def __init__(self, log, fail=False):
        self.log, self.fail = log, fail

    def new_cdp_session(self, page):
        return CdpSession(self.log, self.fail)


class Page:
    def __init__(self, log):
        self.log = log

    def bring_to_front(self):
        self.log.append("nach vorne")


def _session(tmp_path, window="offscreen", *, launched=True, fail=False, leave=True):
    cfg = replace(BrowserConfig(), kind="edge", user_data_dir=tmp_path / "p", window=window,
                  leave_browser_running=leave)
    session = EdgeCdpSession(cfg)
    log: list = []
    session.browser, session.context, session.page = Browser(log, fail), Context(log, fail), Page(log)
    session.launched = launched
    session.hidden = launched and window == "offscreen"
    return session, log


@pytest.mark.parametrize("window, offscreen", [("offscreen", True), ("minimized", False), ("visible", False)])
def test_own_browser_starts_hidden_only_when_set(monkeypatch, tmp_path, window, offscreen):
    started = []
    exe = tmp_path / "msedge.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(edge_cdp, "_cdp_endpoint_reachable", lambda endpoint: False)
    monkeypatch.setattr(edge_cdp, "profile_in_use", lambda path: False)
    monkeypatch.setattr(edge_cdp.subprocess, "Popen", lambda args, **kw: started.append(args) or _Process())
    cfg = replace(BrowserConfig(), kind="edge", executable=exe, user_data_dir=tmp_path / "p", window=window,
                  connect_timeout_ms=300)
    with pytest.raises(BrowserLaunchError):
        EdgeCdpSession(cfg).connect()
    assert (f"--window-position={OFFSCREEN},{OFFSCREEN}" in started[0]) is offscreen
    assert started[0][-1] == "about:blank"


class _Process:
    def poll(self):
        return None

    def wait(self, timeout=None):
        import subprocess
        raise subprocess.TimeoutExpired("x", timeout or 0)

    def terminate(self):
        pass

    def kill(self):
        pass


def test_show_brings_a_hidden_window_onto_the_screen_and_hide_puts_it_back(tmp_path):
    session, log = _session(tmp_path)
    assert session.show_window() and not session.hidden
    assert log == [{"windowState": "normal"}, VISIBLE_BOUNDS, "nach vorne"]
    log.clear()
    assert session.hide_window() and session.hidden
    assert log == [{"windowState": "normal"}, {"left": OFFSCREEN, "top": OFFSCREEN}]


def test_minimized_mode_minimizes_again(tmp_path):
    session, log = _session(tmp_path, "minimized")
    session.hidden = False
    assert session.hide_window() and log == [{"windowState": "minimized"}]


def test_visible_mode_and_foreign_browsers_are_never_hidden(tmp_path):
    session, log = _session(tmp_path, "visible")
    assert not session.hide_window() and log == []
    session, log = _session(tmp_path, launched=False)       # Browser lief schon, nicht von uns gestartet
    assert not session.hide_window() and log == []
    assert session.show_window()                              # zeigen darf man ihn trotzdem
    assert log == [{"windowState": "normal"}, "nach vorne"]


def test_window_problems_never_break_the_run(tmp_path):
    session, log = _session(tmp_path, fail=True)
    assert session.show_window() is False and session.hidden
    assert session.hide_window() is False


def test_browser_left_running_is_never_left_invisible(tmp_path):
    session, log = _session(tmp_path)
    session.close()
    assert log == [{"windowState": "normal"}, VISIBLE_BOUNDS, {"windowState": "minimized"}]
    assert not session.hidden


# -- Anmeldung: Fenster nur zeigen, wenn der Benutzer etwas tun muss -------------------------------------

class _Response:
    def __init__(self, payload):
        self.status, self._payload = 200, payload

    def json(self):
        return self._payload


class _Context:
    def __init__(self):
        self.logged_in = False
        self.request = self

    def get(self, url, **kwargs):
        if url.endswith("/api/auth/session"):
            return _Response({"accessToken": "tok", "user": {"id": "user-1", "email": "n@example.org"}}
                             if self.logged_in else {})
        return _Response({"id": "user-1", "email": "n@example.org", "name": "N"})


class _Cdp:
    def __init__(self):
        self.context = _Context()
        self.events: list[str] = []

    def ensure_chatgpt_page(self):
        return object()

    def show_window(self):
        self.events.append("zeigen")
        return True

    def hide_window(self):
        self.events.append("verbergen")
        return True


def test_manual_login_shows_the_window_and_hides_it_afterwards(monkeypatch):
    from chatexporter.providers.chatgpt.auth.broker import AuthBroker
    cdp = _Cdp()

    def user_logs_in(prompt=""):
        cdp.events.append("Benutzer meldet sich an")
        cdp.context.logged_in = True
        return ""
    monkeypatch.setattr("builtins.input", user_logs_in)
    AuthBroker(cdp, "https://chatgpt.com", 1000).acquire(interactive=True)
    assert cdp.events == ["zeigen", "Benutzer meldet sich an", "verbergen"]


def test_valid_session_never_shows_the_window():
    from chatexporter.providers.chatgpt.auth.broker import AuthBroker
    cdp = _Cdp()
    cdp.context.logged_in = True
    AuthBroker(cdp, "https://chatgpt.com", 1000).acquire(interactive=True)
    assert cdp.events == []
