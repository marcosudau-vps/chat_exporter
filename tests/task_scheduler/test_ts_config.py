"""Zeitplan-Konfiguration: Defaults, Vorrang, Pfade, Fehler."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import chatexporter.config as shared_config

from chatexporter.task_scheduler import config as cfg_mod
from chatexporter.task_scheduler.backend import load_backend
from chatexporter.task_scheduler.config import (DEFAULT_FOLDER, DEFAULT_OWNER, TaskSetupError,
                                                default_manager_script, discover_config, load_config)


def _write(folder: Path, text: str) -> Path:
    path = folder / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("CHATEXPORTER_CONFIG", "CHATEXPORTER_ENV_FILE", "CHATEXPORTER_DATA_ROOT",
                 "CHATEXPORTER_TASK_FOLDER", "CHATEXPORTER_TASK_OWNER", "CHATEXPORTER_TASK_STATE_FILE",
                 "CHATEXPORTER_TASK_GLOBAL_STATE", "CHATEXPORTER_TASK_PYTHON",
                 "CHATEXPORTER_TASK_MANAGER_SCRIPT", "CHATEXPORTER_TASK_COMMAND"):
        monkeypatch.delenv(name, raising=False)


def test_defaults_without_section(tmp_path):
    cfg = load_config(_write(tmp_path, "storage:\n  data_root: data\n"))
    assert cfg.folder == DEFAULT_FOLDER == "\\ChatExporter"
    identity = shared_config.storage_status(shared_config.load(tmp_path / "config.yaml"))["identity"]
    assert cfg.owner == f"{DEFAULT_OWNER}-{identity.id[:8]}", "Eigentuemer je Storage"
    assert cfg.storage_root == tmp_path / "data"
    assert cfg.base == tmp_path
    assert cfg.local_state_file == tmp_path / "data" / ".storage" / "tasks_sched.json"
    assert cfg.global_state_file is None
    assert cfg.defaults["command"] == "update --non-interactive"
    assert cfg.defaults["trigger"] == {"type": "daily", "at": "03:00", "every": 1}
    assert cfg.manager_script == default_manager_script()
    assert cfg.python == Path(sys.executable)


def test_default_manager_script_is_in_code_folder():
    script = default_manager_script()
    assert script.name == "scheduler_manager.py"
    assert script.is_file(), "tools/task_scheduler/scheduler_manager.py muss im Codeordner liegen"


def test_frozen_program_runs_itself(tmp_path, monkeypatch):
    """Gebautes Programm: Aufgabe startet chatexporter.exe ohne ``-m chatexporter``,
    scheduler_manager.py kommt aus dem mitgelieferten Ordner."""
    exe = tmp_path / "ChatExporter" / "chatexporter.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "_MEIPASS", str(exe.parent / "_internal"), raising=False)
    cfg = load_config(_write(tmp_path, ""))
    assert cfg.python == exe and cfg.launcher_args == ()
    assert cfg.manager_script == exe.parent / "_internal" / "tools" / "task_scheduler" / "scheduler_manager.py"
    from chatexporter.task_scheduler.service import TaskService
    sys.path.insert(0, str(Path(__file__).parent))
    from fakes import FakeManager
    fake = FakeManager()
    TaskService(cfg, manager=fake).create("Lauf")
    assert fake.payloads[-1]["executable"] == str(exe)
    assert fake.payloads[-1]["arguments"][:2] == ["--config", str(cfg.config_file)]
    explicit = load_config(_write(tmp_path, "task_scheduler:\n  python: C:/py/python.exe\n"))
    assert explicit.launcher_args == ("-m", "chatexporter"), "ausdruecklich gesetztes Python bleibt Python"


def test_section_values_and_relative_paths(tmp_path):
    cfg = load_config(_write(tmp_path, (
        "storage:\n  data_root: d\n"
        "task_scheduler:\n  folder: '\\Mein'\n  owner: Ich\n  state_file: state/t.json\n"
        "  global_state_file: g/t.json\n  manager_script: x/m.py\n"
        "  defaults:\n    command: check\n    max_runtime_minutes: 5\n"
        "    trigger: {type: weekly, at: '06:00', days: [mo]}\n")))
    assert cfg.folder == "\\Mein" and cfg.owner == "Ich"
    assert cfg.local_state_file == (tmp_path / "state" / "t.json").resolve()
    assert cfg.global_state_file == (tmp_path / "g" / "t.json").resolve()
    assert cfg.manager_script == (tmp_path / "x" / "m.py").resolve()
    assert cfg.defaults["command"] == "check"
    assert cfg.defaults["max_runtime_minutes"] == 5
    # nicht gesetzte Defaults bleiben erhalten
    assert cfg.defaults["multiple_instances"] == "ignore_new"
    assert cfg.defaults["trigger"]["type"] == "weekly"


def test_precedence_cli_over_env_over_config(tmp_path, monkeypatch):
    path = _write(tmp_path, "task_scheduler:\n  folder: '\\FromConfig'\n  owner: cfgowner\n")
    assert load_config(path).folder == "\\FromConfig"
    monkeypatch.setenv("CHATEXPORTER_TASK_FOLDER", "\\FromEnv")
    monkeypatch.setenv("CHATEXPORTER_TASK_OWNER", "envowner")
    cfg = load_config(path)
    assert (cfg.folder, cfg.owner) == ("\\FromEnv", "envowner")
    cfg = load_config(path, overrides={"folder": "\\FromCli", "owner": None})
    assert (cfg.folder, cfg.owner) == ("\\FromCli", "envowner")


def test_env_overrides_for_paths_and_command(tmp_path, monkeypatch):
    path = _write(tmp_path, "task_scheduler:\n  defaults:\n    command: check\n")
    monkeypatch.setenv("CHATEXPORTER_TASK_STATE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setenv("CHATEXPORTER_TASK_GLOBAL_STATE", str(tmp_path / "g.json"))
    monkeypatch.setenv("CHATEXPORTER_TASK_PYTHON", str(tmp_path / "py.exe"))
    monkeypatch.setenv("CHATEXPORTER_TASK_COMMAND", "status")
    cfg = load_config(path)
    assert cfg.local_state_file == tmp_path / "s.json"
    assert cfg.global_state_file == tmp_path / "g.json"
    assert cfg.python == tmp_path / "py.exe"
    assert cfg.defaults["command"] == "status"


def test_dotenv_is_read(tmp_path):
    (tmp_path / ".env").write_text("CHATEXPORTER_TASK_OWNER=aus-dotenv\n", encoding="utf-8")
    assert load_config(_write(tmp_path, "storage: {}\n")).owner == "aus-dotenv"


def test_python_defaults_to_bootstrap_venv(tmp_path):
    venv = tmp_path / "myvenv" / "Scripts"
    venv.mkdir(parents=True)
    (venv / "python.exe").write_text("", encoding="utf-8")
    cfg = load_config(_write(tmp_path, "bootstrap:\n  venv_path: myvenv\n"))
    assert cfg.python == tmp_path / "myvenv" / "Scripts" / "python.exe"


def test_data_root_env_moves_default_state_file(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATEXPORTER_DATA_ROOT", str(tmp_path / "elsewhere"))
    cfg = load_config(_write(tmp_path, "storage:\n  data_root: data\n"))
    assert cfg.local_state_file == tmp_path / "elsewhere" / ".storage" / "tasks_sched.json"


def test_missing_config_is_created_from_the_template(tmp_path):
    cfg = load_config(tmp_path / "neu.yaml")
    assert (tmp_path / "neu.yaml").is_file() and cfg.folder == DEFAULT_FOLDER


def test_invalid_sections_are_setup_errors(tmp_path):
    with pytest.raises(TaskSetupError):
        load_config(_write(tmp_path, "task_scheduler:\n  defaults: 5\n"))


def test_discover_uses_the_shared_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATEXPORTER_CONFIG", str(tmp_path / "x.yaml"))
    assert discover_config() == (tmp_path / "x.yaml").resolve()
    assert discover_config(tmp_path / "y.yaml") == (tmp_path / "y.yaml").resolve()

def test_backend_missing_script_is_a_setup_error(tmp_path):
    with pytest.raises(TaskSetupError, match="scheduler_manager.py"):
        load_backend(tmp_path / "nichtda.py")


def test_module_has_no_import_side_effects():
    assert cfg_mod.TaskSchedulerConfig.__slots__
