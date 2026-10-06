"""Zustand des Storages: Werte (Registry bzw. Speicher), Update-Zaehler, erster Abruf, state.yaml."""

from __future__ import annotations

import sys
import uuid

import pytest
import yaml

import chatexporter.config as shared_config
from chatexporter.cli import storage_state
from chatexporter.config import state as state_mod


def _manifest(*, stopped=False, open_conversations=0, fetched=0, ok=True, partial=False):
    detail = {"rate_limit": {"stopped": stopped, "open_conversations": open_conversations}}
    return {"finished_at": "2026-10-03T10:00:00Z", "partial": partial, "sources": {
        "chatgpt": {"ok": ok, "finished_at": "2026-10-03T09:59:00Z", "detail": detail,
                    "stats": {"sessions_total": 120, "files_total": 7, "sessions_fetched": fetched}},
        "codex": {"ok": True, "stats": {"sessions_total": 5, "files_total": 0}}}}


def test_update_values_count_and_estimate_the_first_fetch():
    first = storage_state.update_values(_manifest(stopped=True, open_conversations=400, fetched=200), {})
    assert first["storage.update_counter"] == 1 and first["storage.update_last"] == "2026-10-03T10:00:00Z"
    assert first["storage.first_fetch.completed"] is False
    assert first["storage.first_fetch.parts_completed"] == 1
    assert first["storage.first_fetch.parts_total"] == 3, "1 erledigt + 400/200 Schaetzung"
    assert first["providers.chatgpt.total_sessions"] == 120 and first["providers.codex.total_sessions"] == 5
    assert first["providers.chatgpt.update_last"] == "2026-10-03T09:59:00Z"
    second = storage_state.update_values(_manifest(), first)
    assert second["storage.update_counter"] == 2 and second["storage.update_last_result"] == "ok"
    assert second["storage.first_fetch.completed"] is True and second["storage.first_fetch.parts_total"] == 2
    assert second["storage.first_fetch.completed_at"] == "2026-10-03T10:00:00Z"
    third = storage_state.update_values(_manifest(ok=False), {**first, **second})
    assert "storage.first_fetch.parts_completed" not in third, "nach dem ersten vollstaendigen Abruf fest"
    assert third["storage.update_last_result"] == "teilweise"


def test_state_file_after_commands(tmp_path, monkeypatch):
    from chatexporter.cli import main as main_mod
    cfg = tmp_path / "config.yaml"
    cfg.write_text("exporter:\n  formats: [json]\n", encoding="utf-8")
    assert main_mod.main(["--config", str(cfg), "status"]) == 0
    storage = shared_config.storage_of(shared_config.load(cfg))
    doc = yaml.safe_load(storage.state_file.read_text(encoding="utf-8"))
    identity = shared_config.storage_status(shared_config.load(cfg))["identity"]
    assert doc["storage"]["id"] == identity.id and doc["storage"]["root"] == str(storage.root)
    assert doc["state"]["storage"]["last_command"].endswith("status")
    assert doc["state"]["storage"]["last_command_exit"] == 0
    assert doc["state"]["providers"]["chatgpt"]["enabled"] is True
    assert doc["config"]["exporter.formats"] == {"value": ["json"], "origin": "config"}
    assert doc["config"]["storage.root"]["origin"] == "default"
    assert doc["paths"]["state_file"] == str(storage.state_file)
    # Konfiguration im Storage aendern -> state.yaml zeigt die neue Herkunft
    assert main_mod.main(["--config", str(cfg), "config", "set", "exporter.formats", "markdown"]) == 0
    doc = yaml.safe_load(storage.state_file.read_text(encoding="utf-8"))
    assert doc["config"]["exporter.formats"] == {"value": ["markdown"], "origin": "storage"}


def test_secrets_are_masked(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("exporter:\n  root: GEHEIM\n", encoding="utf-8")
    monkeypatch.setattr(shared_config.SCHEMA, "secrets", lambda: {"exporter.root", "exporter.sources"})
    loaded = shared_config.load(cfg)
    status = shared_config.storage_status(loaded)
    text = state_mod.render(loaded, status["storage"], status["identity"], {}, version="x")
    assert "GEHEIM" not in text and "(gesetzt)" in text


def test_next_scheduled_comes_from_update_tasks(tmp_path):
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1] / "task_scheduler"))
    from fakes import FakeManager
    from chatexporter.task_scheduler.service import TaskService

    class Clock(FakeManager):
        def _info(self, task_id):
            info = super()._info(task_id)
            info.next_run_time = {"tsk_000000000001": "2026-10-04 03:00:00",
                                  "tsk_000000000002": "2026-10-03 12:00:00"}.get(task_id)
            return info

    fake = Clock()
    cfg = tmp_path / "config.yaml"
    cfg.write_text("", encoding="utf-8")
    factory = lambda c: TaskService(c, manager=fake)  # noqa: E731
    factory(None if False else __import__("chatexporter.task_scheduler.config", fromlist=["x"]).load_config(cfg))
    service = factory(__import__("chatexporter.task_scheduler.config", fromlist=["x"]).load_config(cfg))
    service.create("Taeglich", command="update --non-interactive")
    service.create("Export", command="export")
    assert storage_state.next_scheduled(cfg, factory) == "2026-10-04 03:00:00", "nur update-Aufgaben"
    path = storage_state.after_command(cfg, "task", 0, service_factory=factory)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["state"]["storage"]["update_next_scheduled_at"] == "2026-10-04 03:00:00"


@pytest.mark.skipif(sys.platform != "win32", reason="nur Windows")
def test_registry_state_roundtrip():
    from chatexporter.cli.uninstall import delete_registry_tree
    key = rf"Software\ChatExporterPytest\{uuid.uuid4().hex}"
    store = state_mod.RegistryState(key)
    try:
        assert store.read() == {}
        store.update({"storage.update_counter": 3, "storage.first_fetch.completed": False,
                      "providers.chatgpt.update_last": "2026-10-03T10:00:00Z", "storage.leer": None})
        store.write_info({"Path": "D:/x", "Name": "x"})
        assert store.read() == {"storage.update_counter": 3, "storage.first_fetch.completed": False,
                                "providers.chatgpt.update_last": "2026-10-03T10:00:00Z", "storage.leer": None}
        store.update({"storage.update_counter": 4})
        assert store.read()["storage.update_counter"] == 4
    finally:
        delete_registry_tree(r"Software\ChatExporterPytest")
