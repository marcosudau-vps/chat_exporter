"""Aufgabenverwaltung mit Ersatz-PyTaskManager (kein Windows noetig)."""

from __future__ import annotations

from datetime import datetime

import pytest

from chatexporter.task_scheduler.service import (RECORD_KEY, SCHEDULABLE_COMMANDS, TaskServiceError,
                                                 _fmt_time, build_trigger, describe_trigger,
                                                 normalize_trigger, parse_command, parse_days)


# -- Eingaben -----------------------------------------------------------------

def test_parse_command_string_and_list():
    assert parse_command("update --source chatgpt --non-interactive") == \
        ["update", "--source", "chatgpt", "--non-interactive"]
    assert parse_command(["check", "--deep"]) == ["check", "--deep"]


def test_parse_command_keeps_windows_paths_and_strips_quotes():
    assert parse_command('export --export-root "D:\\mein ordner\\x"') == \
        ["export", "--export-root", "D:\\mein ordner\\x"]


@pytest.mark.parametrize("bad", ["", "   ", "task list", "rm -rf", "--help", "gibtesnicht"])
def test_parse_command_rejects(bad):
    with pytest.raises(TaskServiceError):
        parse_command(bad)


def test_schedulable_commands_match_the_cli():
    from chatexporter.cli import main as main_mod
    cli_commands = {*main_mod.UPDATER_COMMANDS, *main_mod.PROVIDER_CLIS, "export", "config"}
    assert set(SCHEDULABLE_COMMANDS) == cli_commands


def test_build_trigger_kinds():
    assert build_trigger() is None
    assert build_trigger(daily="3:00") == {"type": "daily", "at": "03:00", "every": 1}
    assert build_trigger(daily="23:59", every=2) == {"type": "daily", "at": "23:59", "every": 2}
    assert build_trigger(weekly="06:30", days="Mo, MI,freitag") == \
        {"type": "weekly", "at": "06:30", "days": ["mo", "mi", "fr"], "every": 1}
    assert build_trigger(once="2030-01-02 03:04") == {"type": "once", "when": "2030-01-02 03:04"}
    assert build_trigger(logon=True, delay=30) == {"type": "logon", "delay_seconds": 30}
    assert build_trigger(startup=True) == {"type": "startup", "delay_seconds": 0}


@pytest.mark.parametrize("kwargs", [
    {"daily": "25:00"}, {"daily": "3"}, {"daily": "03:60"},
    {"weekly": "06:00"},                              # Tage fehlen
    {"weekly": "06:00", "days": "xx"},
    {"daily": "03:00", "weekly": "04:00", "days": "mo"},   # zwei Trigger
    {"daily": "03:00", "days": "mo"},                 # --days nur mit weekly
    {"days": "mo"}, {"every": 2}, {"delay": 5},       # Zusatzoptionen ohne Trigger
    {"daily": "03:00", "every": 0},
    {"logon": True, "every": 2}, {"daily": "03:00", "delay": 5},
    {"once": "morgen"}, {"once": "2030-01-02 03:04", "every": 2},
    {"logon": True, "delay": -1},
])
def test_build_trigger_rejects(kwargs):
    with pytest.raises(TaskServiceError):
        build_trigger(**kwargs)


def test_parse_days_dedupes_and_normalizes():
    assert parse_days(["Montag", "mo", "wed"]) == ["mo", "mi"]
    with pytest.raises(TaskServiceError):
        parse_days("")


def test_normalize_trigger_roundtrip_and_errors():
    for spec in ({"type": "daily", "at": "03:00"}, {"type": "weekly", "at": "06:00", "days": ["mo"]},
                 {"type": "once", "when": "2030-01-02 03:04"}, {"type": "logon"}, {"type": "startup"}):
        assert normalize_trigger(spec)["type"] == spec["type"]
    with pytest.raises(TaskServiceError):
        normalize_trigger({"type": "monatlich"})


def test_describe_trigger():
    assert describe_trigger(None) == "-"
    assert describe_trigger({"type": "daily", "at": "03:00", "every": 1}) == "taeglich 03:00"
    assert describe_trigger({"type": "daily", "at": "03:00", "every": 2}) == "alle 2 Tage 03:00"
    assert describe_trigger({"type": "weekly", "at": "06:30", "days": ["mo", "mi"], "every": 1}) == \
        "woechentlich mo,mi 06:30"
    assert describe_trigger({"type": "once", "when": "2030-01-02 03:04"}) == "einmalig 2030-01-02 03:04"
    assert describe_trigger({"type": "logon", "delay_seconds": 30}) == "bei Anmeldung (+30s)"
    assert describe_trigger({"type": "startup", "delay_seconds": 0}) == "bei Systemstart"


def test_fmt_time_hides_never_and_zone():
    assert _fmt_time(None) is None
    assert _fmt_time(datetime(1999, 11, 30)) is None
    assert _fmt_time(datetime(2030, 1, 2, 3, 4, 5)) == "2030-01-02T03:04:05"


# -- create ---------------------------------------------------------------------

def test_create_with_defaults(service, fake, config):
    view = service.create("Taeglicher Lauf")
    payload = fake.payloads[-1]
    assert payload["name"] == "Taeglicher Lauf" and payload["owner"] == config.owner
    assert payload["executable"] == str(config.python)
    assert config.storage_root is not None and config.owner.startswith("chatexporter-")
    assert payload["arguments"] == ["-m", "chatexporter", "--config", str(config.config_file),
                                    "--storage", str(config.storage_root), "update", "--non-interactive"]
    assert payload["working_directory"] == str(config.base)
    assert payload["trigger"] == {"type": "daily", "at": "03:00", "every": 1}
    assert payload["enabled"] is True
    assert payload["max_runtime_minutes"] == 360 and payload["multiple_instances"] == "ignore_new"
    assert payload["start_when_available"] is True and payload["wake_to_run"] is False
    assert payload["description"] == "ChatExporter: update --non-interactive"
    record = payload["metadata"][RECORD_KEY]
    assert record["command"] == ["update", "--non-interactive"]
    assert record["storage"] == str(config.storage_root)
    assert view["slug"] == "taeglicher-lauf"
    assert view["command"] == "update --non-interactive"
    assert view["trigger"] == "taeglich 03:00"
    assert view["state"] == "ready" and view["enabled"] is True


def test_create_with_explicit_values(service, fake):
    view = service.create("Index", slug="idx", command="index", trigger=build_trigger(weekly="05:00", days="so"),
                          description="nur sonntags", enabled=False,
                          settings={"max_runtime_minutes": 10, "wake_to_run": True, "hidden": None})
    payload = fake.payloads[-1]
    assert payload["slug"] == "idx" and payload["enabled"] is False
    assert payload["trigger"]["type"] == "weekly"
    assert payload["max_runtime_minutes"] == 10 and payload["wake_to_run"] is True
    assert payload["hidden"] is False          # None = Standardwert aus der Config
    assert payload["description"] == "nur sonntags"
    assert view["state"] == "disabled" and view["trigger"] == "woechentlich so 05:00"


def test_create_uses_configured_defaults(tmp_path, fake):
    from chatexporter.task_scheduler.config import load_config
    from chatexporter.task_scheduler.service import TaskService
    (tmp_path / "config.yaml").write_text(
        "task_scheduler:\n  defaults:\n    command: status\n    trigger: {type: logon}\n"
        "    wake_to_run: true\n", encoding="utf-8")
    service = TaskService(load_config(tmp_path / "config.yaml"), manager=fake)
    view = service.create("Beim Start")
    assert view["command"] == "status" and view["trigger"] == "bei Anmeldung"
    assert fake.payloads[-1]["wake_to_run"] is True


def test_create_rejects_bad_input(service, fake):
    for kwargs in ({"name": ""}, {"name": "  "}, {"name": "x", "command": "task list"},
                   {"name": "x", "settings": {"unbekannt": 1}},
                   {"name": "x", "settings": {"multiple_instances": "chaos"}},
                   {"name": "x", "settings": {"max_runtime_minutes": 0}}):
        with pytest.raises(TaskServiceError):
            service.create(**kwargs)
    assert fake.payloads == []


def test_create_duplicate_is_an_error(service):
    service.create("Eins")
    with pytest.raises(TaskServiceError, match="existiert bereits"):
        service.create("Eins")


# -- get / list --------------------------------------------------------------------

def test_get_by_slug_name_and_id(service):
    created = service.create("Mein Lauf")
    assert service.get("mein-lauf")["task_id"] == created["task_id"]
    assert service.get("Mein Lauf")["task_id"] == created["task_id"]
    assert service.get(created["task_id"])["slug"] == "mein-lauf"
    with pytest.raises(TaskServiceError, match="nicht gefunden"):
        service.get("gibtesnicht")


def test_list(service):
    assert service.list() == []
    service.create("A")
    service.create("B", command="check")
    assert [v["slug"] for v in service.list()] == ["a", "b"]
    assert service.list()[1]["command"] == "check"


# -- update -----------------------------------------------------------------------------

def test_update_changes_only_given_fields_and_keeps_identity(service, fake):
    first = service.create("Lauf", command="update --source chatgpt", description="alt",
                           settings={"max_runtime_minutes": 20})
    updated = service.update("lauf", trigger=build_trigger(daily="05:15"))
    assert updated["task_id"] == first["task_id"] and updated["slug"] == "lauf"
    assert updated["trigger"] == "taeglich 05:15"
    assert updated["command"] == "update --source chatgpt"          # unveraendert
    assert fake.payloads[-1]["max_runtime_minutes"] == 20            # unveraendert
    assert fake.payloads[-1]["description"] == "alt"
    assert fake.payloads[-1]["task_id"] == first["task_id"]
    assert len(fake.entries) == 1


def test_update_command_name_description_settings(service, fake):
    service.create("Lauf")
    view = service.update("lauf", name="Neuer Name", command="check --deep", description="neu",
                          settings={"wake_to_run": True, "multiple_instances": "queue"})
    assert view["name"] == "Neuer Name" and view["slug"] == "lauf"
    assert view["command"] == "check --deep"
    payload = fake.payloads[-1]
    assert payload["arguments"][-2:] == ["check", "--deep"]
    assert payload["wake_to_run"] is True and payload["multiple_instances"] == "queue"
    assert payload["description"] == "neu"
    assert service.get("lauf")["name"] == "Neuer Name"


def test_update_keeps_a_paused_task_paused(service):
    service.create("Lauf")
    service.pause("lauf")
    view = service.update("lauf", command="status")
    assert view["enabled"] is False and view["state"] == "disabled"


def test_update_validates_before_touching_anything(service, fake):
    service.create("Lauf")
    before = len(fake.payloads)
    with pytest.raises(TaskServiceError):
        service.update("lauf", command="task delete x")
    with pytest.raises(TaskServiceError):
        service.update("lauf", settings={"multiple_instances": "chaos"})
    assert len(fake.payloads) == before


def test_update_without_stored_plan_is_refused(service, fake):
    fake.create({"name": "Fremd", "owner": "chatexporter", "metadata": {}})
    with pytest.raises(TaskServiceError, match="keinen gespeicherten Plan"):
        service.update("fremd", command="status")


def test_update_unknown_task(service):
    with pytest.raises(TaskServiceError, match="nicht gefunden"):
        service.update("gibtesnicht", command="status")


# -- pause / resume / delete ---------------------------------------------------------------------

def test_pause_and_resume(service):
    service.create("Lauf")
    paused = service.pause("lauf")
    assert paused["enabled"] is False and paused["state"] == "disabled"
    assert service.get("lauf")["enabled"] is False
    resumed = service.resume("lauf")
    assert resumed["enabled"] is True and resumed["state"] == "ready"
    for action in (service.pause, service.resume):
        with pytest.raises(TaskServiceError):
            action("gibtesnicht")


def test_delete(service, fake):
    created = service.create("Lauf")
    gone = service.delete("lauf")
    assert gone["task_id"] == created["task_id"]
    assert fake.entries == {}
    assert service.list() == []
    with pytest.raises(TaskServiceError):
        service.delete("lauf")


def test_tasks_missing_from_the_global_state_are_still_found(service, fake):
    """Fehlt der Eintrag im globalen PyTaskManager-State (Datei geloescht), steht die
    Aufgabe aber noch lokal und in Windows: list/get/pause/delete --all finden sie."""
    view = service.create("Taeglicher Abruf", slug="taeglich")
    other = service.create("Zweite")
    fake.global_lost.add(view["task_id"])
    assert {v["slug"] for v in service.list()} == {"taeglich", "zweite"}
    assert service.get("taeglich")["task_id"] == view["task_id"]
    assert service.get("Taeglicher Abruf")["task_id"] == view["task_id"]
    assert service.pause("taeglich")["enabled"] is False
    assert service.update("taeglich", command="status")["command"] == "status"
    removed = service.delete_all()
    assert {v["task_id"] for v in removed} == {view["task_id"], other["task_id"]} and fake.entries == {}
