"""Echte Windows-Aufgaben (Integrationstest).

Legt Aufgaben in einem eigenen, nur fuer diesen Test angelegten Ordner der
Windows-Aufgabenplanung an und raeumt sie danach wieder ab. Uebersprungen ohne
Windows oder pywin32. Die Nutzer-Aufgaben (Ordner ``\\ChatExporter``) bleiben unberuehrt.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from chatexporter.task_scheduler.config import load_config
from chatexporter.task_scheduler.service import RECORD_KEY, TaskService, build_trigger

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="nur unter Windows")

try:
    import win32com.client  # noqa: F401
except ImportError:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason="pywin32 nicht installiert")


@pytest.fixture
def real(tmp_path):
    folder = f"\\ChatExporterPytest_{uuid.uuid4().hex[:8]}"
    (tmp_path / "config.yaml").write_text(
        f"storage:\n  data_root: {(tmp_path / 'data').as_posix()}\n"
        f"task_scheduler:\n  folder: '{folder}'\n  owner: pytest\n"
        f"  state_file: {(tmp_path / 'local.json').as_posix()}\n"
        f"  global_state_file: {(tmp_path / 'global.json').as_posix()}\n"
        f"  python: {Path(sys.executable).as_posix()}\n", encoding="utf-8")
    service = TaskService(load_config(tmp_path / "config.yaml"))
    yield service
    try:
        for view in service.list():
            service.delete(view["task_id"])
        service.manager.scheduler.delete_folder()
    except Exception as exc:  # noqa: BLE001  Aufraeumen darf den Test nicht verdecken
        print(f"Aufraeumen unvollstaendig: {exc}")


def _definition(service, task_id):
    return service.manager.scheduler.get_task(task_id).Definition


def test_lifecycle_against_the_real_scheduler(real, tmp_path):
    scheduler = real.manager.scheduler
    created = real.create("Integrationstest", command="status --source codex",
                          trigger=build_trigger(daily="04:20"), description="pytest")
    task_id = created["task_id"]
    assert scheduler.task_exists(task_id)
    assert created["state"] == "ready" and created["next_run"] is not None
    assert created["last_run"] is None

    # So steht der Befehl in der Windows-Aufgabe.
    action = _definition(real, task_id).Actions.Item(1)
    assert Path(action.Path) == Path(sys.executable)
    assert action.Arguments.startswith("-m chatexporter --config ")
    assert action.Arguments.endswith("status --source codex")
    assert Path(action.WorkingDirectory) == tmp_path
    assert _definition(real, task_id).Triggers.Count == 1

    # State: global und lokal, mit gespeichertem Plan.
    for state in ("global.json", "local.json"):
        data = json.loads((tmp_path / state).read_text(encoding="utf-8"))
        assert data["tasks"][task_id]["metadata"][RECORD_KEY]["command"] == ["status", "--source", "codex"]

    assert [v["slug"] for v in real.list()] == ["integrationstest"]
    assert real.get("integrationstest")["task_id"] == task_id

    # update: gleiche Identitaet, neuer Zeitplan/Befehl.
    updated = real.update(task_id, trigger=build_trigger(weekly="06:30", days="mo,do"),
                          command="check", settings={"max_runtime_minutes": 12})
    assert updated["task_id"] == task_id and updated["trigger"] == "woechentlich mo,do 06:30"
    assert _definition(real, task_id).Actions.Item(1).Arguments.endswith("check")
    assert _definition(real, task_id).Triggers.Count == 1
    assert len(real.list()) == 1

    # pause / resume wirken in Windows.
    assert real.pause(task_id)["enabled"] is False
    assert not scheduler.get_task(task_id).Enabled
    assert real.update(task_id, description="noch pausiert")["enabled"] is False
    assert real.resume(task_id)["enabled"] is True
    assert scheduler.get_task(task_id).Enabled

    # delete: Windows und beide State-Dateien.
    real.delete(task_id)
    assert not scheduler.task_exists(task_id)
    assert real.list() == []
    for state in ("global.json", "local.json"):
        assert task_id not in json.loads((tmp_path / state).read_text(encoding="utf-8"))["tasks"]


def test_create_paused_is_disabled_in_windows(real):
    created = real.create("Pausiert", enabled=False)
    assert created["enabled"] is False and created["state"] == "disabled"
    assert not real.manager.scheduler.get_task(created["task_id"]).Enabled


def test_errors_are_translated(real):
    real.create("Eins")
    from chatexporter.task_scheduler.service import TaskServiceError
    with pytest.raises(TaskServiceError, match="existiert bereits"):
        real.create("Eins")
    with pytest.raises(TaskServiceError, match="nicht gefunden"):
        real.get("gibtesnicht")
    with pytest.raises(TaskServiceError, match="nicht gefunden"):
        real.pause("gibtesnicht")


@pytest.fixture
def keep_registry_mirror():
    """Der geplante Prozess laeuft ohne Test-Umgebung und spiegelt deshalb in die
    echte Registry; vorher sichern, danach exakt wiederherstellen."""
    import winreg
    keys = (r"Software\ChatExporter\config\Current", r"Software\ChatExporter\config")

    def snapshot(path):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
                values, index = {}, 0
                while True:
                    try:
                        name, value, kind = winreg.EnumValue(key, index)
                    except OSError:
                        return values
                    values[name] = (value, kind)
                    index += 1
        except OSError:
            return None

    saved = {path: snapshot(path) for path in keys}
    yield
    for path, values in saved.items():
        current = snapshot(path)
        if values is None:
            if current is not None:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE) as key:
                    for name in current:
                        winreg.DeleteValue(key, name)
            continue
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_WRITE) as key:
            for name in (current or {}):
                if name not in values:
                    winreg.DeleteValue(key, name)
            for name, (value, kind) in values.items():
                winreg.SetValueEx(key, name, 0, kind, value)


def test_the_scheduled_command_really_runs(real, tmp_path, keep_registry_mirror):
    """Aufgabe starten und pruefen, dass ``chatexporter ... status`` lief."""
    probe = subprocess.run([sys.executable, "-c", "import chatexporter"], cwd=tmp_path,
                           capture_output=True)
    if probe.returncode != 0:
        pytest.skip("chatexporter ist im Test-Interpreter nicht installiert (pip install -e)")

    created = real.create("Lauftest", command="status", trigger=build_trigger(once="2099-01-01 03:00"))
    real.manager.run(created["task_id"])

    overview = tmp_path / "data" / ".storage" / "OVERVIEW.md"
    deadline = time.monotonic() + 90
    view = created
    while time.monotonic() < deadline:
        view = real.get(created["task_id"])
        if overview.exists() and view["state"] == "ready" and view["last_run"] is not None:
            break
        time.sleep(1)
    assert overview.exists(), f"der geplante Befehl hat nicht gelaufen: {view}"
    assert view["last_result"] == 0, view

    logs = list((tmp_path / "data" / ".storage" / "logs").glob("commands_*.jsonl"))
    assert logs, "der geplante Lauf muss im Befehlsprotokoll stehen"
    records = [json.loads(line) for log in logs for line in log.read_text(encoding="utf-8").splitlines()]
    assert any(r.get("command", "").endswith("status") and r.get("exit_code") == 0 for r in records)


def test_continuation_creates_a_real_one_time_task(real, tmp_path):
    """Die automatische Fortsetzung legt eine echte einmalige Aufgabe an und entfernt sie danach."""
    from chatexporter.cli import continuation
    stopped = {"sources": {"chatgpt": {"ok": True, "detail": {"aborted": False, "rate_limit": {
        "stopped": True, "open_conversations": 42, "estimated_full_at": "2099-01-01T03:00:00Z"}}}}}
    lines = []
    result = continuation.after_update(stopped, real.config.config_file, say=lines.append,
                                       service_factory=lambda cfg: real)
    view = real.get("fortsetzung-chatgpt")
    assert result["continuation_chatgpt"].startswith("geplant 2099-01-01")
    assert view["exists"] and view["trigger"].startswith("einmalig 2099-01-01")
    assert view["command"] == "update --source chatgpt --listing-mode full --non-interactive"
    assert real.manager.scheduler.get_task(view["task_id"]).Definition.Triggers.Count == 1
    done = {"sources": {"chatgpt": {"ok": True, "detail": {"aborted": False, "rate_limit": {"stopped": False}}}}}
    assert continuation.after_update(done, real.config.config_file, say=lines.append,
                                     service_factory=lambda cfg: real) == {"continuation_chatgpt": "abgeschlossen"}
    assert not real.manager.scheduler.task_exists(view["task_id"])


def test_deleted_global_state_does_not_hide_tasks(real, tmp_path):
    """Echte Aufgabenplanung: Ist der globale State geloescht, finden list, Kurzname
    und delete --all die Aufgabe trotzdem (lokaler State + Windows)."""
    created = real.create("Taeglicher Abruf", slug="taeglich", command="status",
                          trigger=build_trigger(daily="05:10"))
    (tmp_path / "global.json").unlink()
    assert [v["task_id"] for v in real.list()] == [created["task_id"]]
    assert real.get("taeglich")["task_id"] == created["task_id"]
    removed = real.delete_all()
    assert [v["task_id"] for v in removed] == [created["task_id"]]
    assert not real.manager.scheduler.task_exists(created["task_id"])
