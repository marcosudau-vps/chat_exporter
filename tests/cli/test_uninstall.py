"""Deinstallation ``chatexporter uninstall``."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "task_scheduler"))

from fakes import FakeManager  # noqa: E402

from chatexporter.cli.uninstall import SILENT_ARGS, run_uninstall  # noqa: E402
from chatexporter.task_scheduler.service import TaskService  # noqa: E402


def _run(argv, *, frozen, program_dir=None, answers=(), tmp_path=None, fake=None, registry=True):
    cfg = None
    if tmp_path is not None:
        cfg = tmp_path / "config.yaml"
        cfg.write_text("", encoding="utf-8")
    said, launched, deleted = [], [], []
    feed = iter(answers)

    def ask(prompt):
        try:
            return next(feed)
        except StopIteration:
            raise EOFError from None

    def delete_registry():
        deleted.append(True)
        return registry

    code = run_uninstall(list(argv), cfg, say=said.append, ask=ask, frozen=frozen, program_dir=program_dir,
                         launch=launched.append,
                         service_factory=(lambda c: TaskService(c, manager=fake)) if fake else None,
                         delete_registry=delete_registry)
    return code, "\n".join(said), launched, deleted


def test_installed_program_starts_the_uninstaller(tmp_path):
    program = tmp_path / "ChatExporter"
    program.mkdir()
    (program / "unins000.exe").write_bytes(b"")
    code, out, launched, deleted = _run([], frozen=True, program_dir=program, tmp_path=tmp_path)
    assert code == 0 and launched == [[str(program / "unins000.exe")]]
    assert deleted == [], "Registry und Aufgaben entfernt der Installer selbst"
    assert "Erhalten bleiben" in out
    code, _, launched, _ = _run(["--silent", "--yes"], frozen=True, program_dir=program, tmp_path=tmp_path)
    assert launched == [[str(program / "unins000.exe"), *SILENT_ARGS]]
    code, out, launched, _ = _run(["--silent"], frozen=True, program_dir=program, answers=("n",), tmp_path=tmp_path)
    assert code == 1 and launched == [] and "Abgebrochen" in out


def test_installed_program_without_uninstaller(tmp_path):
    code, out, launched, _ = _run([], frozen=True, program_dir=tmp_path)
    assert code == 2 and launched == [] and "Keine Deinstallation" in out


def test_source_mode_removes_tasks_and_registry(tmp_path):
    fake = FakeManager()
    cfg = tmp_path / "config.yaml"
    cfg.write_text("", encoding="utf-8")
    from chatexporter.task_scheduler.config import load_config
    service = TaskService(load_config(cfg), manager=fake)
    service.create("Eins")
    service.create("Zwei")
    code, out, launched, deleted = _run([], frozen=False, answers=("n",), tmp_path=tmp_path, fake=fake)
    assert code == 1 and deleted == [] and len(service.list()) == 2
    code, out, launched, deleted = _run(["--yes"], frozen=False, tmp_path=tmp_path, fake=fake)
    assert code == 0 and deleted == [True] and service.list() == []
    assert "eins" in out and "zwei" in out and "pip uninstall" in out and launched == []


def test_options(tmp_path):
    assert _run(["-h"], frozen=False)[0] == 0
    assert _run(["--quatsch"], frozen=False)[0] == 2


def test_remove_tasks_covers_all_known_storages(tmp_path, monkeypatch):
    from chatexporter.cli import uninstall
    from chatexporter.config.storage import Storage, ensure
    one, two, old = tmp_path / "eins", tmp_path / "zwei", tmp_path / "alt"
    ensure(Storage(one))
    ensure(Storage(two))
    (old / "runtime" / "runs").mkdir(parents=True)
    (old / "raw_storage").mkdir()
    monkeypatch.setattr(uninstall, "known_storages", lambda config: [one, two, old])
    seen = []

    class Service:
        def __init__(self, config):
            seen.append((config.storage_root, config.owner))

        def delete_all(self):
            return [{"slug": "taeglich"}]

    cfg = tmp_path / "config.yaml"
    cfg.write_text("", encoding="utf-8")
    said = []
    code = uninstall.run_uninstall(["--remove-tasks", "--yes"], cfg, say=said.append, service_factory=Service)
    assert code == 0 and [root for root, _owner in seen] == [one, two], "altes Format wird uebersprungen"
    assert seen[0][1] != seen[1][1], "Eigentuemer je Storage"
    assert sum("taeglich" in line for line in said) == 2
