"""Automatische Fortsetzung nach einem Rate-Limit-Stopp."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from chatexporter.cli import continuation
from chatexporter.task_scheduler.service import TaskService

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "task_scheduler"))
from fakes import FakeManager  # noqa: E402

NOW = datetime(2026, 10, 3, 1, 0, tzinfo=timezone.utc)


def manifest(*, stopped=False, ok=True, aborted=False, open_count=150, full_at="2026-10-03T04:30:00Z", source="chatgpt"):
    return {"sources": {source: {"ok": ok, "detail": {
        "aborted": aborted,
        "rate_limit": {"stopped": stopped, "open_conversations": open_count if stopped else None,
                       "estimated_full_at": full_at if stopped else None}}}}}


@pytest.fixture
def env(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("{}\n", encoding="utf-8")
    fake = FakeManager()
    lines: list[str] = []

    def run(m, now=NOW):
        return continuation.after_update(m, cfg, say=lines.append, now=now,
                                         service_factory=lambda c: TaskService(c, manager=fake))
    return cfg, fake, lines, run


def test_decide():
    d = continuation.decide(manifest(stopped=True), margin_minutes=10, now=NOW)
    assert d["chatgpt"]["action"] == "schedule"
    assert d["chatgpt"]["at_utc"] == datetime(2026, 10, 3, 4, 40, tzinfo=timezone.utc)
    assert continuation.decide(manifest(), margin_minutes=10, now=NOW) == {"chatgpt": {"action": "finish"}}
    assert continuation.decide(manifest(aborted=True), margin_minutes=10, now=NOW) == {}
    assert continuation.decide(manifest(ok=False), margin_minutes=10, now=NOW) == {}
    past = continuation.decide(manifest(stopped=True, full_at="2026-10-02T00:00:00Z"), margin_minutes=5, now=NOW)
    assert past["chatgpt"]["at_utc"] == datetime(2026, 10, 3, 1, 5, tzinfo=timezone.utc), "nie in der Vergangenheit"
    unknown = continuation.decide(manifest(stopped=True, full_at=None), margin_minutes=0, now=NOW)
    assert unknown["chatgpt"]["at_utc"] == NOW


def test_schedule_then_reschedule_then_finish(env):
    cfg, fake, lines, run = env
    result = run(manifest(stopped=True))
    payload = fake.payloads[-1]
    expected_local = datetime(2026, 10, 3, 4, 40, tzinfo=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    assert payload["slug"] == "fortsetzung-chatgpt"
    assert payload["trigger"] == {"type": "once", "when": expected_local}
    assert payload["arguments"][-5:] == ["update", "--source", "chatgpt", "--listing-mode", "full"] or \
        payload["arguments"][-6:] == ["update", "--source", "chatgpt", "--listing-mode", "full", "--non-interactive"]
    assert result == {"continuation_chatgpt": f"geplant {expected_local}"}
    assert any("150 Konversationen offen" in line for line in lines)

    run(manifest(stopped=True, full_at="2026-10-03T08:00:00Z"))
    assert len(fake.entries) == 1, "dieselbe Aufgabe wird neu terminiert, keine zweite"
    assert fake.payloads[-1]["trigger"]["when"].endswith(
        datetime(2026, 10, 3, 8, 10, tzinfo=timezone.utc).astimezone().strftime("%H:%M"))

    result = run(manifest())
    assert fake.entries == {} and result == {"continuation_chatgpt": "abgeschlossen"}


def test_paused_continuation_is_resumed_when_rescheduled(env):
    cfg, fake, lines, run = env
    run(manifest(stopped=True))
    task_id = next(iter(fake.entries))
    fake.enabled[task_id] = False
    run(manifest(stopped=True))
    assert fake.enabled[task_id] is True


def test_nothing_to_do_and_disabled(env, tmp_path):
    cfg, fake, lines, run = env
    assert run(manifest()) == {} and fake.payloads == []        # fertig, aber keine Aufgabe vorhanden
    cfg.write_text("task_scheduler:\n  continuation:\n    enabled: false\n", encoding="utf-8")
    assert run(manifest(stopped=True)) == {"continuation": "aus"} and fake.payloads == []


def test_errors_never_break_the_update(env):
    cfg, fake, lines, run = env
    result = continuation.after_update(manifest(stopped=True), cfg, say=lines.append, now=NOW,
                                       service_factory=lambda c: (_ for _ in ()).throw(RuntimeError("pywin32 fehlt")))
    assert "pywin32 fehlt" in result["continuation_error"]
    assert any("nicht geplant" in line for line in lines)


def test_updater_command_calls_the_hook_and_prints_its_result(tmp_path, monkeypatch, capsys):
    from chatexporter.raw_session_updater import cli as updater_cli
    cfg = tmp_path / "config.yaml"
    cfg.write_text("{}\n", encoding="utf-8")
    fake_manifest = {"run_manifest": "x.json", "partial": False, "totals": {}, "sources": {}}
    monkeypatch.setattr(updater_cli.operations, "update", lambda *a, **k: (fake_manifest, 0))
    seen = []

    def hook(m, config_file):
        seen.append((m, config_file))
        return {"continuation_chatgpt": "geplant 2026-10-03 06:40"}
    assert updater_cli.main(["update", "--config", str(cfg)], after_update=hook) == 0
    out = capsys.readouterr().out
    report = json.loads(out[out.rindex("{\n"):])
    assert seen and seen[0][1] == cfg.resolve()
    assert report["continuation_chatgpt"] == "geplant 2026-10-03 06:40"


def test_main_wires_the_hook(monkeypatch):
    from chatexporter.cli import main as main_mod
    seen = {}
    monkeypatch.setattr(main_mod, "updater_main", lambda argv, **kw: seen.update(argv=argv, **kw) or 0)
    main_mod.dispatch(["update", "--source", "chatgpt"])
    assert seen["after_update"] is main_mod._after_update
