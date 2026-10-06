"""Bedienschicht: Befehle, Menü und installierte Einstiegspunkte."""

from __future__ import annotations

import tomllib
from importlib import import_module
from pathlib import Path

from chatexporter.cli import main as main_mod
from chatexporter.cli.menu import ITEMS, run_menu

ROOT = Path(__file__).resolve().parents[2]


def test_every_pyproject_entry_point_resolves():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert "chatexporter" in scripts
    for name, target in scripts.items():
        module_name, func = target.split(":")
        assert callable(getattr(import_module(module_name), func)), name


def test_help_and_version(capsys):
    assert main_mod.main(["--help"]) == 0
    assert "update" in capsys.readouterr().out
    assert main_mod.main(["--version"]) == 0


def test_unknown_command_returns_2(capsys):
    assert main_mod.dispatch(["gibtesnicht"]) == 2


def test_updater_command_status_runs_against_empty_store(tmp_path, capsys):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"storage:\n  data_root: {tmp_path / 'data'}\nraw_session_updater:\n  sources: [chatgpt]\n",
                   encoding="utf-8")
    assert main_mod.main(["--config", str(cfg), "status"]) == 0
    assert (tmp_path / "data" / ".storage" / "OVERVIEW.md").exists()
    assert (tmp_path / "data" / ".storage" / "storage.yaml").is_file(), "leerer Ordner wird Storage"


def test_single_updater_entry_point(tmp_path, capsys):
    from chatexporter.raw_session_updater.cli import check_main
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"storage:\n  data_root: {tmp_path / 'data'}\nraw_session_updater:\n  sources: [chatgpt]\n",
                   encoding="utf-8")
    assert check_main(["--config", str(cfg)]) == 0


def test_provider_command_gets_shared_config(tmp_path, monkeypatch):
    seen = {}

    def fake_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(main_mod, "_provider_main", lambda source: fake_main)
    cfg = tmp_path / "config.yaml"
    cfg.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("CHATEXPORTER_CONFIG", str(cfg))
    assert main_mod.dispatch(["codex", "stats"]) == 0
    assert seen["argv"] == ["--config", str(cfg), "stats"]
    assert main_mod.dispatch(["codex", "--config", "x.yaml", "stats"]) == 0
    assert seen["argv"] == ["--config", "x.yaml", "stats"]


def _scripted(answers):
    it = iter(answers)

    def ask(_prompt):
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return ask


def test_menu_translates_choices_into_commands():
    calls = []

    def dispatch(argv, config):
        calls.append(argv)
        return 0

    out = []
    code = run_menu(ask=_scripted(["1", "", "2", "", "3", "1", "", "", "3", "1", "2", "",
                                   "8", "n", "0"]),
                    say=out.append, dispatch=dispatch)
    assert code == 0
    assert calls == [["update"],
                     ["update", "--listing-mode", "full"],
                     ["update", "--source", "chatgpt", "--listing-mode", "auto"],
                     ["update", "--source", "chatgpt", "--listing-mode", "recent"]]
    assert any("Abgebrochen" in line for line in out), "Aufräumen ohne Bestätigung läuft nicht"
    assert any("Befehl: chatexporter update --listing-mode full" in line for line in out)


def test_menu_runs_commands_in_fresh_process(monkeypatch, tmp_path):
    """Ein lange offenes Menue soll nie veralteten Code ausfuehren."""
    import subprocess
    from chatexporter.cli import menu
    seen = {}

    class FakeProc:
        def __init__(self, cmd):
            seen["cmd"] = cmd
        def wait(self):
            return 7

    monkeypatch.setattr(subprocess, "Popen", FakeProc)
    assert menu.run_in_subprocess(["update", "--listing-mode", "full"], tmp_path / "c.yaml") == 7
    assert seen["cmd"][1:3] == ["-m", "chatexporter"]
    assert seen["cmd"][3:] == ["--config", str(tmp_path / "c.yaml"), "update", "--listing-mode", "full"]


def test_menu_items_are_valid_commands():
    for item in ITEMS.values():
        if item.argv:
            assert item.argv[0] in (*main_mod.UPDATER_COMMANDS, *main_mod.PROVIDER_CLIS, "export", "task", "config", "setup"), item


def test_export_command_is_dispatched_with_the_shared_config(tmp_path, monkeypatch):
    seen = {}

    def fake_export(argv, prog="chatexporter export"):
        seen["argv"], seen["prog"] = argv, prog
        return 0

    monkeypatch.setattr(main_mod, "export_cli_main", fake_export)
    assert main_mod.dispatch(["export", "--format", "json"], tmp_path / "c.yaml") == 0
    assert seen == {"argv": ["--format", "json", "--config", str(tmp_path / "c.yaml")],
                    "prog": "chatexporter export"}


def test_export_single_entry_point_is_logged(monkeypatch):
    seen, logged = {}, {}
    monkeypatch.setattr(main_mod, "export_cli_main", lambda argv, prog: seen.update(argv=argv, prog=prog) or 0)
    monkeypatch.setattr(main_mod, "run_logged",
                        lambda program, argv, run: logged.update(program=program, argv=argv) or run())
    assert main_mod.export_main(["--format", "json"]) == 0
    assert logged == {"program": "chatexporter-export", "argv": ["--format", "json"]}
    assert seen == {"argv": ["--format", "json"], "prog": "chatexporter-export"}


def test_export_menu_item_runs_the_export_command():
    calls = []
    feed = iter(["10", "", "0"])
    run_menu(ask=lambda prompt: next(feed), say=lambda line: None,
             dispatch=lambda argv, cfg: calls.append(tuple(argv)) or 0)
    assert calls == [("export",)]


def test_task_command_is_dispatched_with_the_shared_config(tmp_path, monkeypatch):
    seen = {}

    def fake_task(argv, prog="chatexporter task"):
        seen["argv"], seen["prog"] = argv, prog
        return 0

    monkeypatch.setattr(main_mod, "task_cli_main", fake_task)
    assert main_mod.dispatch(["task", "list"], tmp_path / "c.yaml") == 0
    assert seen == {"argv": ["--config", str(tmp_path / "c.yaml"), "list"], "prog": "chatexporter task"}
    main_mod.dispatch(["task", "list", "--config", "x.yaml"], tmp_path / "c.yaml")
    assert seen["argv"] == ["list", "--config", "x.yaml"]


def test_task_single_entry_point_is_logged(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(main_mod, "task_cli_main", lambda argv, prog: seen.update(argv=argv, prog=prog) or 0)
    logged = {}
    monkeypatch.setattr(main_mod, "run_logged",
                        lambda program, argv, run: logged.update(program=program, argv=argv) or run())
    assert main_mod.task_main(["list"]) == 0
    assert logged == {"program": "chatexporter-task", "argv": ["list"]}
    assert seen == {"argv": ["list"], "prog": "chatexporter-task"}


def test_usage_lists_the_task_command(capsys):
    assert main_mod.main(["--help"]) == 0
    assert "task" in capsys.readouterr().out


def test_task_menu_items_build_task_commands():
    answers = iter(["Nachtlauf", "02:15", "check --deep", "", "meinlauf", "j", "x", "", "0"])
    said, run_calls = [], []
    inputs = {"13": ["Nachtlauf", "02:15", "check --deep"], "16": ["meinlauf", "j"], "14": ["pa"]}
    for key, expect in (
        ("13", ("task", "create", "Nachtlauf", "--daily", "02:15", "--command", "check --deep")),
        ("16", ("task", "delete", "meinlauf", "--yes")),
        ("14", ("task", "pause", "pa")),
        ("12", ("task", "list")),
    ):
        feed = iter([key, *inputs.get(key, []), "", "0"])
        calls = []
        run_menu(ask=lambda prompt, feed=feed: next(feed), say=lambda line: None,
                 dispatch=lambda argv, cfg, calls=calls: calls.append(tuple(argv)) or 0)
        assert calls == [expect], key


def test_task_menu_cancel_runs_nothing():
    for key, extra in (("13", [""]), ("14", [""]), ("16", ["x", "n"])):
        feed = iter([key, *extra, "0"])
        calls = []
        run_menu(ask=lambda prompt, feed=feed: next(feed), say=lambda line: None,
                 dispatch=lambda argv, cfg, calls=calls: calls.append(argv) or 0)
        assert calls == [], key
