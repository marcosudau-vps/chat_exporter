"""chatexporter.config: Suche, Home, aeltere Abschnitte, CLI-Werte, Spiegel, Befehle."""

from __future__ import annotations

import json
import sys

import pytest
import yaml

import chatexporter.config as shared_config
from chatexporter.config import cli as config_cli
from chatexporter.config.schema import SCHEMA
from chatexporter.cli import main as main_mod


def test_every_setting_has_description_and_example_or_default():
    for setting in SCHEMA:
        assert setting.description, setting.path
        assert setting.default is not None or setting.example is not None, setting.path


def test_template_contains_every_setting_and_is_fully_commented():
    text = shared_config.manager().template()
    assert yaml.safe_load(text) is None
    for setting in SCHEMA:
        assert f"{setting.parts[-1]}:" in text, setting.path
    assert "BEISPIEL" in text and "config set" in text


def test_lookup_explicit_env_and_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATEXPORTER_CONFIG", str(tmp_path / "env.yaml"))
    assert shared_config.locate(tmp_path / "x.yaml") == (tmp_path / "x.yaml").resolve()
    assert shared_config.locate() == (tmp_path / "env.yaml").resolve()
    monkeypatch.delenv("CHATEXPORTER_CONFIG")
    monkeypatch.setenv("CHATEXPORTER_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    assert shared_config.home() == tmp_path / "home"
    assert shared_config.locate() == (tmp_path / "home" / "config.yaml").resolve()


def test_development_lookup_skips_code_folders_and_frozen_skips_it(tmp_path, monkeypatch):
    monkeypatch.delenv("CHATEXPORTER_CONFIG")
    monkeypatch.setenv("CHATEXPORTER_HOME", str(tmp_path / "home"))
    code = tmp_path / "workspace" / "code"
    (code / "src" / "chatexporter").mkdir(parents=True)
    (code / "config.yaml").write_text("{}\n", encoding="utf-8")
    (tmp_path / "workspace" / "config.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.chdir(code)
    assert shared_config.locate() == tmp_path / "workspace" / "config.yaml"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert shared_config.locate() == (tmp_path / "home" / "config.yaml").resolve(), \
        "das installierte Programm nutzt immer das Home-Verzeichnis"


def test_default_home_is_dot_chatexporter(monkeypatch):
    monkeypatch.delenv("CHATEXPORTER_HOME")
    assert shared_config.home().name == ".chatexporter"


def test_missing_config_is_created_and_defaults_apply(tmp_path, capsys):
    target = tmp_path / "neu" / "config.yaml"
    loaded = shared_config.load(target)
    assert loaded.created and target.is_file()
    assert "Vorlage angelegt" in capsys.readouterr().err
    assert loaded.get("storage.root") == "storages/default" and loaded.origin("storage.root") == "default"
    assert loaded.get("storage.data_root") == str(target.parent / "storages" / "default"), "wirksame Storage-Wurzel"
    target.unlink()
    shared_config.load(target)
    assert target.is_file(), "wird bei jedem Fehlen neu angelegt"


def test_legacy_top_level_sections_belong_to_chatgpt(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("sync:\n  listing_mode: full\nbrowser:\n  cdp_port: 9300\n", encoding="utf-8")
    loaded = shared_config.load(cfg)
    assert loaded.get("providers.chatgpt.sync.listing_mode") == "full"
    assert loaded.get("providers.chatgpt.browser.cdp_port") == 9300
    cfg.write_text("sync:\n  listing_mode: full\nproviders:\n  chatgpt:\n    sync:\n      listing_mode: recent\n",
                   encoding="utf-8")
    assert shared_config.load(cfg).get("providers.chatgpt.sync.listing_mode") == "recent"


def test_cli_overrides_win_for_every_layer(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("providers:\n  chatgpt:\n    sync:\n      listing_mode: full\n", encoding="utf-8")
    monkeypatch.setenv("CHATEXPORTER_LISTING_MODE", "recent")
    from chatexporter.providers.chatgpt.config.loader import load_config
    assert load_config(cfg).sync.listing_mode == "recent"
    with shared_config.overrides(["providers.chatgpt.sync.listing_mode=auto", "exporter.formats=json"]):
        assert load_config(cfg).sync.listing_mode == "auto"
        from chatexporter.exporter.config import load_exporter_config
        assert load_exporter_config(cfg).formats == ("json",)
    assert load_config(cfg).sync.listing_mode == "recent"
    assert shared_config.cli_overrides() == []


def test_generic_environment_names(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("CHATEXPORTER__PROVIDERS__CHATGPT__SYNC__RECENT_MAX_PAGES", "7")
    monkeypatch.setenv("CHATEXPORTER__TASK_SCHEDULER__DEFAULTS__WAKE_TO_RUN", "true")
    loaded = shared_config.load(cfg)
    assert loaded.get("providers.chatgpt.sync.recent_max_pages") == 7
    assert loaded.get("task_scheduler.defaults.wake_to_run") is True


def test_registry_mirror_switch(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(shared_config.RegistryMirror, "write", lambda self, v, m: calls.append(v))
    mirror = shared_config._SwitchableRegistryMirror("x", "y")
    monkeypatch.setenv("CHATEXPORTER_REGISTRY_MIRROR", "off")
    mirror.write({"a": 1}, {})
    assert calls == []
    monkeypatch.setenv("CHATEXPORTER_REGISTRY_MIRROR", "on")
    mirror.write({"a": 1}, {})
    assert calls == [{"a": 1}]


def test_registry_location_is_fixed():
    assert shared_config.REGISTRY_VALUES_KEY == r"Software\ChatExporter\config\Current"


# -- chatexporter config ...  ----------------------------------------------------------

@pytest.fixture
def run(tmp_path, capsys):
    cfg = tmp_path / "config.yaml"

    def go(*argv, answers=()):
        feed = iter(answers)
        lines: list[str] = []

        def ask(prompt):
            try:
                return next(feed)
            except StopIteration:
                raise EOFError from None
        code = config_cli.main(["--config", str(cfg), *argv], say=lines.append, ask=ask)
        return code, "\n".join(lines), capsys.readouterr().err
    go.cfg = cfg
    return go


def test_config_get_set_reset_cycle(run):
    code, out, _ = run("get", "providers.chatgpt.sync.listing_mode")
    assert code == 0 and out.splitlines()[0] == "auto" and "default" in out
    code, out, _ = run("set", "providers.chatgpt.sync.listing_mode", "full")
    assert code == 0 and "Gesetzt" in out
    code, out, _ = run("get", "providers.chatgpt.sync.listing_mode", "--json")
    assert json.loads(out) == {"key": "providers.chatgpt.sync.listing_mode", "value": "full", "origin": "storage"}
    storage = shared_config.storage_of(shared_config.load(run.cfg))
    assert "listing_mode: full" in storage.config_file.read_text(encoding="utf-8"), "in die Storage-Datei"
    assert "listing_mode: full" not in run.cfg.read_text(encoding="utf-8")
    code, out, _ = run("reset", "providers.chatgpt.sync.listing_mode")
    assert code == 0 and "auto" in out and "default" in out


def test_config_global_writes_the_global_file(run, capsys):
    cfg = run.cfg
    assert config_cli.main(["--config", str(cfg), "set", "providers.chatgpt.sync.listing_mode", "recent"],
                           scope="global", say=lambda _l: None) == 0
    assert "listing_mode: recent" in cfg.read_text(encoding="utf-8")
    code, out, _ = run("get", "providers.chatgpt.sync.listing_mode", "--json")
    assert json.loads(out)["origin"] == "config"
    run("set", "providers.chatgpt.sync.listing_mode", "full")
    assert json.loads(run("get", "providers.chatgpt.sync.listing_mode", "--json")[1])["origin"] == "storage",         "Storage ist spezifischer als global"
    code, _out, err = run("set", "storage.root", "D:/x")
    assert code == 1 and "config-global" in err, "nur-global-Schluessel im Storage abgelehnt"
    assert config_cli.main(["--config", str(cfg), "set", "storage.root", str(cfg.parent / "zwei")],
                           scope="global", say=lambda _l: None) == 0
    assert shared_config.storage_of(shared_config.load(cfg)).root == cfg.parent / "zwei"


def test_config_set_reports_when_a_higher_layer_wins(run, monkeypatch):
    monkeypatch.setenv("CHATEXPORTER_LISTING_MODE", "recent")
    code, out, _ = run("set", "providers.chatgpt.sync.listing_mode", "full")
    assert code == 0 and "wirksam ist der Wert aus 'env'" in out


def test_config_errors(run):
    assert run("set", "gibt.es.nicht", "1")[0] == 1
    assert run("set", "providers.chatgpt.sync.listing_mode", "bogus")[0] == 1
    assert run("get", "gibt.es.nicht")[0] == 1
    assert run("reset")[0] == 1


def test_config_get_section_list_and_path(run):
    code, out, _ = run("get", "providers.chatgpt.sync")
    assert code == 0 and "listing_mode" in out
    code, out, _ = run("list")
    assert code == 0 and "storage.root = storages/default    [default]" in out
    code, out, _ = run("list", "--json")
    assert any(row["key"] == "logging.dir" for row in json.loads(out))
    code, out, _ = run("path", "--json")
    info = json.loads(out)
    storage = shared_config.storage_of(shared_config.load(run.cfg))
    identity = shared_config.storage_status(shared_config.load(run.cfg))["identity"]
    assert info["config_file"] == str(run.cfg) and info["storage"] == str(storage.root)
    assert info["storage_format"] == "storage-schema-2" and info["state_file"] == str(storage.state_file)
    assert info["registry"].endswith(rf"ChatExporter\Storages\{identity.id}\Config\Current")


def test_config_reset_all_asks_and_restores_the_template(run):
    run("set", "exporter.formats", "json")
    loaded = shared_config.load(run.cfg)
    storage_file = loaded.scope.config_file
    code, out, _ = run("reset", "--all", answers=("n",))
    assert code == 1 and "Abgebrochen" in out
    assert "formats: [json]" in storage_file.read_text(encoding="utf-8")
    code, out, _ = run("reset", "--all", "--yes")
    assert code == 0 and storage_file.read_text(encoding="utf-8") ==         shared_config.manager().scope_template(loaded.scope)
    config_cli.main(["--config", str(run.cfg), "set", "storage.data_root", str(run.cfg.parent / "x")], scope="global",
                    say=lambda _l: None)
    assert config_cli.main(["--config", str(run.cfg), "reset", "--all", "--yes"], scope="global",
                           say=lambda _l: None) == 0
    assert run.cfg.read_text(encoding="utf-8") == shared_config.manager().template()


def test_config_refresh_recreates_a_deleted_file(run):
    run("get", "storage.data_root")
    run.cfg.unlink()
    code, out, _ = run("refresh")
    assert code == 0 and run.cfg.is_file() and "Vorlage neu angelegt" in out


# -- globale Optionen der Bedienschicht ------------------------------------------------------

def test_global_options_before_the_command():
    config, sets, rest = main_mod.split_global_options(
        ["--config", "c.yaml", "--set", "a.b=1", "--set=c.d=2", "--config=d.yaml", "update", "--set", "x=y"])
    assert str(config) == "d.yaml" and sets == ["a.b=1", "c.d=2"] and rest == ["update", "--set", "x=y"]


def test_main_applies_set_values_and_dispatches_config(tmp_path, capsys):
    cfg = tmp_path / "config.yaml"
    assert main_mod.main(["--config", str(cfg), "--set", "logging.enabled=false",
                          "config", "get", "logging.enabled"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "false" and "cli" in out


def test_config_single_entry_point_is_logged(monkeypatch):
    seen, logged = {}, {}
    monkeypatch.setattr(main_mod, "config_cli_main", lambda argv, prog: seen.update(argv=argv, prog=prog) or 0)
    monkeypatch.setattr(main_mod, "run_logged",
                        lambda program, argv, run: logged.update(program=program, argv=argv) or run())
    assert main_mod.config_main(["path"]) == 0
    assert logged == {"program": "chatexporter-config", "argv": ["path"]}
    assert seen == {"argv": ["path"], "prog": "chatexporter-config"}
