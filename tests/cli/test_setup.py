"""Ersteinrichtung ``chatexporter setup`` und ``chatgpt browser-setup``."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "task_scheduler"))

from fakes import FakeManager  # noqa: E402

from chatexporter.cli.setup import run_setup  # noqa: E402
from chatexporter.task_scheduler.service import TaskService  # noqa: E402


def _run(tmp_path, answers, *, config_text="", provider_code=0):
    cfg = tmp_path / "config.yaml"
    if config_text is not None:
        cfg.write_text(config_text, encoding="utf-8")
    feed, said, calls, asked = iter(answers), [], [], []
    fake = FakeManager()

    def ask(prompt):
        asked.append(prompt)
        try:
            return next(feed)
        except StopIteration:
            raise EOFError from None

    def provider(source, args, config):
        calls.append((source, args, config))
        return provider_code

    code = run_setup([], cfg, say=said.append, ask=ask, provider=provider,
                     service_factory=lambda config: TaskService(config, manager=fake))
    return code, "\n".join(said), calls, asked, fake


def test_fresh_setup_runs_all_steps(tmp_path):
    code, out, calls, asked, fake = _run(tmp_path, ("", ""), config_text=None)
    assert code == 0
    assert (tmp_path / "config.yaml").is_file(), "fehlende config.yaml wird als Vorlage angelegt"
    assert calls == [("chatgpt", ["browser-setup"], tmp_path / "config.yaml")]
    payload = fake.payloads[-1]
    assert payload["slug"] == "taeglich" and payload["trigger"]["at"] == "03:00"
    assert payload["arguments"][-2:] == ["update", "--non-interactive"]
    assert "taeglich 03:00" in out and "Fertig" in out


def test_everything_can_be_declined(tmp_path):
    code, out, calls, asked, fake = _run(tmp_path, ("n", "n"))
    assert code == 0 and calls == [] and fake.payloads == []
    assert "nicht eingerichtet" in out


def test_configured_profile_check_renew_skip(tmp_path):
    text = "providers:\n  chatgpt:\n    browser:\n      user_data_dir: C:/profil\n"
    for answer, expected in (("", ["browser-setup"]), ("n", ["browser-setup", "--neu"]), ("u", None)):
        _, out, calls, _, _ = _run(tmp_path, (answer, "n"), config_text=text)
        assert (calls[0][1] if calls else None) == expected
        assert "C:/profil" in out or "C:\\profil" in out


def test_chatgpt_inactive_skips_browser(tmp_path):
    _, out, calls, _, _ = _run(tmp_path, ("n",), config_text="raw_session_updater:\n  sources: [codex]\n")
    assert calls == [] and "ChatGPT nicht aktiv" in out


def test_existing_task_time_is_changed_or_kept(tmp_path):
    fake = FakeManager()
    cfg = tmp_path / "config.yaml"
    cfg.write_text("", encoding="utf-8")
    factory = lambda config: TaskService(config, manager=fake)  # noqa: E731
    for answers in (("u", "05:15"), ("u", "")):
        said = []
        feed = iter(answers)
        assert run_setup([], cfg, say=said.append, ask=lambda p: next(feed),
                         provider=lambda *a: 0, service_factory=factory) == 0
    created = [p for p in fake.payloads if p.get("slug") == "taeglich"]
    assert len(created) == 1 and created[0]["trigger"]["at"] == "05:15"
    assert "unveraendert" in "\n".join(said)


def test_invalid_time_is_asked_again_and_failures_give_exit_1(tmp_path):
    code, out, _, asked, fake = _run(tmp_path, ("n", "25:00", "6:30"), provider_code=0)
    assert code == 0 and "Bitte HH:MM" in out and fake.payloads[-1]["trigger"]["at"] == "06:30" and "taeglich 06:30" in out
    code, out, *_ = _run(tmp_path, ("", "n"), provider_code=1)
    assert code == 1 and "fehlgeschlagen" in out


def test_waits_for_enter_only_in_its_own_window(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("", encoding="utf-8")
    for own, expected_prompts in ((True, 3), (False, 2)):
        asked, fake = [], FakeManager()

        def ask(prompt):
            asked.append(prompt)
            return "n"

        assert run_setup([], cfg, say=lambda _l: None, ask=ask, provider=lambda *a: 0,
                         service_factory=lambda c: TaskService(c, manager=fake), own_console=lambda: own) == 0
        assert len(asked) == expected_prompts
        assert ("schliesst dieses Fenster" in asked[-1]) is own


def test_unexpected_error_is_shown_before_the_window_closes(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("", encoding="utf-8")
    said, asked = [], []

    def broken_provider(*args):
        raise RuntimeError("kaputt")

    code = run_setup([], cfg, say=said.append, ask=lambda p: asked.append(p) or "", provider=broken_provider,
                     service_factory=lambda c: TaskService(c, manager=FakeManager()), own_console=lambda: True)
    assert code == 1 and any("FEHLER bei der Einrichtung: RuntimeError: kaputt" in s for s in said)
    assert "schliesst dieses Fenster" in asked[-1]


def test_help_and_unknown_option(tmp_path, capsys):
    said = []
    assert run_setup(["-h"], None, say=said.append) == 0 and "Ersteinrichtung" in said[0]
    assert run_setup(["--quatsch"], None, say=said.append) == 2


# -- chatgpt browser-setup ---------------------------------------------------------------

def test_browser_setup_operation(tmp_path):
    from chatexporter.providers.chatgpt import operations
    from chatexporter.providers.chatgpt.auth.browser_setup import Attempt, BrowserChoice, BrowserSetupError
    from chatexporter.providers.chatgpt.config.models import AppConfig

    class Session:
        launched = True
        abandoned = closed = False

        def abandon(self):
            self.abandoned = True

        def close(self):
            self.closed = True

    session, seen = Session(), {}

    def opener(cfg, *, interactive, say, counter, ask):
        seen["configured"], seen["interactive"] = cfg.browser.user_data_dir_configured, interactive
        return session, object(), BrowserChoice("search", "edge", "msedge.exe", "D:/kopie", 9223,
                                                [Attempt("edge-kopie-Default", "Edge", True)])

    report, code = operations.browser_setup(AppConfig(), renew=True, opener=opener)
    assert code == 0 and report["browser"]["user_data_dir"] == "D:/kopie"
    assert seen == {"configured": False, "interactive": True}
    assert session.abandoned, "fuer die Einrichtung gestarteter Browser wird geschlossen"

    def failing(cfg, **kwargs):
        raise BrowserSetupError("nichts gefunden", [Attempt("edge-profile", "Edge", False, "kaputt")])

    report, code = operations.browser_setup(AppConfig(), opener=failing)
    assert code == 1 and report["attempts"][0]["reason"] == "kaputt"
    report, code = operations.browser_setup(AppConfig(), opener=lambda cfg, **k: (_ for _ in ()).throw(OSError("x")))
    assert code == 1 and "OSError" in report["error"]
