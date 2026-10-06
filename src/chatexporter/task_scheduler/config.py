"""Konfiguration der Zeitplanung (Abschnitt ``task_scheduler``).

Die Werte kommen aus der gemeinsamen Konfiguration ``chatexporter.config``
(Vorrang: CLI-Werte > Umgebung > ``.env`` > config.yaml > Standard). Hier
werden nur Pfade abgeleitet (State-Dateien, Interpreter, Script).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import chatexporter.config as shared_config

#: Standardwerte fuer neue Aufgaben; die wirksamen Werte stehen im Schema
#: (``task_scheduler.defaults.*``) und koennen dort ueberschrieben werden.
DEFAULT_TASK_DEFAULTS: dict[str, Any] = {
    "command": "update --non-interactive",
    "trigger": {"type": "daily", "at": "03:00", "every": 1},
    "description": "",
    "max_runtime_minutes": 360,
    "start_when_available": True,
    "allow_on_battery": True,
    "wake_to_run": False,
    "multiple_instances": "ignore_new",
    "hidden": False,
}

DEFAULT_FOLDER = "\\ChatExporter"
DEFAULT_OWNER = "chatexporter"


class TaskSetupError(RuntimeError):
    """Konfiguration oder Umgebung reichen nicht aus (Exitcode 2)."""


def discover_config(explicit: Path | None = None) -> Path:
    return shared_config.locate(explicit)


def is_frozen() -> bool:
    """Laeuft das Programm als gebaute Datei (PyInstaller) statt aus Python?"""
    return bool(getattr(sys, "frozen", False))


def default_manager_script() -> Path:
    """``<Codeordner>/tools/task_scheduler/scheduler_manager.py``; im gebauten
    Programm die mitgelieferte Kopie (``<Programm>/_internal/tools/...``)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "tools" / "task_scheduler" / \
            "scheduler_manager.py"
    return Path(__file__).resolve().parents[3] / "tools" / "task_scheduler" / "scheduler_manager.py"


#: Argumente vor dem eigentlichen Befehl: Python braucht ``-m chatexporter``,
#: das gebaute Programm ``chatexporter.exe`` nicht.
MODULE_ARGS = ("-m", "chatexporter")


@dataclass(slots=True)
class TaskSchedulerConfig:
    config_file: Path
    #: Ordner der config.yaml (= Arbeitsordner der geplanten Befehle).
    base: Path
    manager_script: Path
    folder: str = DEFAULT_FOLDER
    owner: str = DEFAULT_OWNER
    local_state_file: Path | None = None
    global_state_file: Path | None = None
    python: Path = field(default_factory=lambda: Path(sys.executable))
    defaults: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_TASK_DEFAULTS))
    #: Argumente zwischen Programm und ``--config`` (siehe ``MODULE_ARGS``).
    launcher_args: tuple[str, ...] = MODULE_ARGS
    #: Storage, auf dem die Aufgaben laufen (``--storage`` im Befehl); None = kein Storage.
    storage_root: Path | None = None


def _venv_python(loaded: shared_config.Loaded) -> Path:
    venv = shared_config.resolve_path(loaded, loaded.get("bootstrap.venv_path"))
    if venv is not None:
        candidate = venv / "Scripts" / "python.exe"
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


def load_config(config_path: Path | None = None, *,
                overrides: Mapping[str, Any] | None = None) -> TaskSchedulerConfig:
    """Laedt die Zeitplan-Konfiguration aus der gemeinsamen Konfiguration."""
    try:
        loaded = shared_config.load(config_path)
    except (shared_config.ConfigError, OSError) as exc:
        raise TaskSetupError(f"Konfiguration nicht ladbar: {exc}") from None
    section = loaded.resolved.section("task_scheduler")
    path = lambda value: shared_config.resolve_path(loaded, value)  # noqa: E731

    defaults = dict(DEFAULT_TASK_DEFAULTS)
    configured = section.get("defaults") or {}
    if not isinstance(configured, dict):
        raise TaskSetupError("task_scheduler.defaults muss ein Abschnitt sein")
    defaults.update({k: v for k, v in configured.items() if v is not None})

    data_root = path(loaded.get("storage.data_root")) or loaded.base / "data"
    state = path(section.get("state_file"))
    script = path(section.get("manager_script"))
    python = path(section.get("python"))
    global_state = path(section.get("global_state_file"))
    folder = str(section.get("folder") or DEFAULT_FOLDER)
    owner = str(section.get("owner") or DEFAULT_OWNER)
    status = shared_config.storage_status(loaded)
    identity = status["identity"]
    if identity is not None and loaded.origin("task_scheduler.owner") == "default":
        # Aufgaben gehoeren einem Storage: eigene Eigentuemer-Kennung je Storage.
        owner = storage_owner(identity.id)

    for key, value in (overrides or {}).items():
        if value is None:
            continue
        if key == "folder":
            folder = str(value)
        elif key == "owner":
            owner = str(value)
        elif key == "state_file":
            state = Path(value).expanduser().resolve()
        elif key == "global_state_file":
            global_state = Path(value).expanduser().resolve()
        elif key == "python":
            python = Path(value).expanduser().resolve()
        elif key == "manager_script":
            script = Path(value).expanduser().resolve()

    launcher_args = MODULE_ARGS
    if python is None and is_frozen():
        # Gebautes Programm: Aufgaben rufen chatexporter.exe direkt auf.
        python, launcher_args = Path(sys.executable), ()
    return TaskSchedulerConfig(
        config_file=loaded.config_file, base=loaded.base,
        manager_script=script or default_manager_script(),
        folder=folder, owner=owner,
        local_state_file=state or data_root / ".storage" / "tasks_sched.json",
        global_state_file=global_state,
        python=python or _venv_python(loaded),
        defaults=defaults, launcher_args=launcher_args,
        storage_root=status["storage"].root if identity is not None else None)


def storage_owner(storage_id: str) -> str:
    """Eigentuemer-Kennung der Aufgaben eines Storages (``chatexporter-<8 Zeichen der ID>``)."""
    return f"{DEFAULT_OWNER}-{storage_id[:8]}"
