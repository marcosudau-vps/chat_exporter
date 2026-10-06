"""Kommandozeile der Zeitplanung mit Ersatz-PyTaskManager."""

from __future__ import annotations

import json
import re

import pytest

from chatexporter.task_scheduler import cli
from chatexporter.task_scheduler.config import TaskSetupError
from chatexporter.task_scheduler.service import TaskService


@pytest.fixture
def run(workspace, fake, capsys):
    """Fuehrt ``task <argv>`` aus; Rueckgabe: (Exitcode, stdout, stderr)."""
    def go(*argv: str, answers: tuple[str, ...] = ()):
        feed = iter(answers)

        def ask(prompt: str) -> str:
            try:
                return next(feed)
            except StopIteration:
                raise EOFError from None

        lines: list[str] = []
        code = cli.main(["--config", str(workspace / "config.yaml"), *argv], say=lines.append, ask=ask,
                        service_factory=lambda config: TaskService(config, manager=fake))
        captured = capsys.readouterr()
        return code, "\n".join(lines), captured.err
    return go


def test_no_command_prints_help(workspace, capsys):
    assert cli.main(["--config", str(workspace / "config.yaml")]) == 2
    assert "create" in capsys.readouterr().out


def test_all_commands_are_registered():
    parser = cli.build_parser()
    help_text = parser.format_help()
    for name in cli.COMMANDS:
        assert name in help_text


def test_create_get_list_roundtrip(run):
    code, out, _ = run("create", "Nachtlauf", "--daily", "02:30", "--command", "update --source codex")
    assert code == 0
    assert "Aufgabe angelegt: nachtlauf" in out and "taeglich 02:30" in out
    assert "update --source codex" in out

    code, out, _ = run("get", "nachtlauf")
    assert code == 0 and "Kurzname:" in out and "nachtlauf" in out
    assert re.search(r"Zustand:\s+ready", out)

    code, out, _ = run("list")
    assert code == 0 and "KURZNAME" in out and "nachtlauf" in out and "update --source codex" in out


def test_create_defaults_come_from_config(run, fake):
    code, out, _ = run("create", "Standard")
    assert code == 0 and "update --non-interactive" in out and "taeglich 03:00" in out


def test_create_paused_and_settings(run, fake):
    code, out, _ = run("create", "Pausiert", "--paused", "--weekly", "06:00", "--days", "mo,fr",
                       "--max-runtime", "15", "--wake-to-run", "--no-allow-on-battery",
                       "--multiple-instances", "queue", "--hidden")
    assert code == 0 and "disabled" in out
    payload = fake.payloads[-1]
    assert payload["enabled"] is False and payload["max_runtime_minutes"] == 15.0
    assert payload["wake_to_run"] is True and payload["allow_on_battery"] is False
    assert payload["multiple_instances"] == "queue" and payload["hidden"] is True
    assert payload["trigger"]["days"] == ["mo", "fr"]


def test_json_output(run):
    code, out, _ = run("create", "Json", "--json")
    assert code == 0 and json.loads(out)["slug"] == "json"
    code, out, _ = run("get", "json", "--json")
    assert json.loads(out)["command"] == "update --non-interactive"
    code, out, _ = run("list", "--json")
    assert [v["slug"] for v in json.loads(out)] == ["json"]


def test_update_pause_resume(run):
    run("create", "Lauf")
    code, out, _ = run("update", "lauf", "--daily", "07:45", "--name", "Lauf neu", "--command", "check")
    assert code == 0 and "Aufgabe geaendert" in out and "taeglich 07:45" in out and "Lauf neu" in out
    code, out, _ = run("pause", "lauf")
    assert code == 0 and "pausiert" in out and "disabled" in out
    code, out, _ = run("resume", "lauf")
    assert code == 0 and "fortgesetzt" in out and "ready" in out


def test_delete_asks_and_respects_the_answer(run):
    run("create", "Lauf")
    code, out, _ = run("delete", "lauf", answers=("n",))
    assert code == 1 and "Abgebrochen" in out
    assert run("get", "lauf")[0] == 0
    code, out, _ = run("delete", "lauf")                       # keine Eingabe moeglich -> abbrechen
    assert code == 1 and run("get", "lauf")[0] == 0
    code, out, _ = run("delete", "lauf", answers=("j",))
    assert code == 0 and "geloescht" in out
    assert run("get", "lauf")[0] == 1


def test_delete_yes_skips_the_question(run):
    run("create", "Lauf")
    code, out, _ = run("delete", "lauf", "--yes")
    assert code == 0 and "geloescht" in out
    code, out, _ = run("create", "Lauf2", "--json")
    code, out, _ = run("delete", "lauf2", "-y", "--json")
    assert json.loads(out)["slug"] == "lauf2"


def test_delete_all(run):
    code, out, _ = run("delete", "--all", "--yes")
    assert code == 0 and "Keine Aufgaben" in out
    run("create", "Eins")
    run("create", "Zwei")
    code, out, _ = run("delete", "--all", answers=("n",))
    assert code == 1 and len(json.loads(run("list", "--json")[1])) == 2
    code, out, _ = run("delete", "--all", answers=("j",))
    assert code == 0 and "eins" in out and "zwei" in out
    assert json.loads(run("list", "--json")[1]) == []
    assert run("delete", "eins", "--all", "--yes")[0] == 1, "nicht beides zugleich"
    assert run("delete", "--yes")[0] == 1, "ohne Aufgabe und ohne --all"


@pytest.mark.parametrize("argv", [
    ("get", "gibtesnicht"), ("update", "gibtesnicht", "--command", "status"),
    ("pause", "gibtesnicht"), ("resume", "gibtesnicht"), ("delete", "gibtesnicht", "--yes"),
])
def test_unknown_task_is_exit_1(run, argv):
    code, _, err = run(*argv)
    assert code == 1 and "FEHLER" in err


@pytest.mark.parametrize("argv", [
    ("create", "X", "--command", "task list"),
    ("create", "X", "--daily", "25:00"),
    ("create", "X", "--weekly", "06:00"),
    ("create", "X", "--daily", "03:00", "--logon"),
    ("create", "X", "--multiple-instances", "chaos"),
])
def test_invalid_input_is_rejected(run, argv):
    try:
        code, _, err = run(*argv)
    except SystemExit as exc:              # argparse (z. B. ungueltige Auswahl)
        assert exc.code == 2
    else:
        assert code == 1 and "FEHLER" in err


def test_duplicate_create_is_exit_1(run):
    assert run("create", "Lauf")[0] == 0
    code, _, err = run("create", "Lauf")
    assert code == 1 and "existiert bereits" in err


def test_broken_config_is_exit_2(tmp_path, capsys):
    bad = tmp_path / "kaputt.yaml"
    bad.write_text("task_scheduler: [\n", encoding="utf-8")
    code = cli.main(["--config", str(bad), "list"])
    assert code == 2 and "Einrichtung" in capsys.readouterr().err

def test_setup_error_from_service_is_exit_2(workspace, capsys):
    def factory(config):
        raise TaskSetupError("pywin32 fehlt")
    code = cli.main(["--config", str(workspace / "config.yaml"), "list"], service_factory=factory)
    assert code == 2 and "pywin32" in capsys.readouterr().err


def test_global_options_work_before_and_after_the_command(workspace, fake, capsys):
    seen = []

    def factory(config):
        seen.append(config)
        return TaskService(config, manager=fake)

    cfg = str(workspace / "config.yaml")
    assert cli.main(["--config", cfg, "--folder", "\\A", "list"], service_factory=factory, say=lambda s: None) == 0
    assert cli.main(["list", "--config", cfg, "--folder", "\\B", "--owner", "x"],
                    service_factory=factory, say=lambda s: None) == 0
    assert seen[0].folder == "\\A" and seen[1].folder == "\\B" and seen[1].owner == "x"
