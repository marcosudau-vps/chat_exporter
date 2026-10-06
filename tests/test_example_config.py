"""config.example.yaml und .env.example sind gueltig und werden von allen Schichten geladen."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def example(tmp_path):
    target = tmp_path / "config.yaml"
    shutil.copy(ROOT / "config.example.yaml", target)
    return target


def test_example_config_loads_in_every_layer(example):
    from chatexporter.exporter.config import load_exporter_config
    from chatexporter.providers.chatgpt.config.loader import load_config
    from chatexporter.raw_session_updater.config import load_updater_config
    from chatexporter.task_scheduler.config import load_config as load_task_config

    updater = load_updater_config(example)
    assert updater.sources == ("chatgpt", "opencode", "codex", "claude")
    assert updater.data_root == (example.parent / "storages" / "default").resolve()
    exporter = load_exporter_config(example)
    assert exporter.formats == ("markdown", "json") and exporter.export_root == example.parent / "storages" / "default" / "exports"
    chatgpt = load_config(example)
    assert chatgpt.sync.listing_mode == "auto"
    assert chatgpt.sync.manual_exclusions.conversations == {}
    tasks = load_task_config(example)
    assert tasks.folder == "\\ChatExporter" and tasks.defaults["command"] == "update --non-interactive"


def test_example_config_contains_no_personal_values():
    text = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
    for forbidden in ("marco", "P:\\", "P:/", "6aa4942f"):
        assert forbidden not in text


def test_env_example_has_no_active_values():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    assert all(line.startswith("#") or not line.strip() for line in lines), "nur auskommentierte Beispiele"


def test_example_config_is_the_generated_template():
    import chatexporter.config as shared_config
    assert (ROOT / "config.example.yaml").read_text(encoding="utf-8") == shared_config.manager().template(), \
        "config.example.yaml neu erzeugen: chatexporter config reset --all --config config.example.yaml --yes"
