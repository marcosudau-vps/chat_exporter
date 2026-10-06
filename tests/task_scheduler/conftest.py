from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from chatexporter.task_scheduler.config import TaskSchedulerConfig, load_config  # noqa: E402
from chatexporter.task_scheduler.service import TaskService  # noqa: E402
from fakes import FakeManager  # noqa: E402


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Ein Arbeitsordner mit config.yaml (ohne task_scheduler-Abschnitt)."""
    (tmp_path / "config.yaml").write_text(
        f"storage:\n  data_root: {(tmp_path / 'data').as_posix()}\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def config(workspace: Path) -> TaskSchedulerConfig:
    return load_config(workspace / "config.yaml")


@pytest.fixture
def fake() -> FakeManager:
    return FakeManager()


@pytest.fixture
def service(config: TaskSchedulerConfig, fake: FakeManager) -> TaskService:
    return TaskService(config, manager=fake)
