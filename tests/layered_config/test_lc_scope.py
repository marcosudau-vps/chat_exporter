"""layered_config: zusaetzliche Scope-Ebene (Datei + .env), nur-global-Einstellungen, Bearbeiten je Ebene."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from layered_config import ConfigError, ConfigManager, MemoryMirror, Schema, Scope, Setting

SCHEMA = Schema([
    Setting("app.port", 8080, "int", "Port"),
    Setting("app.name", "demo", "str", "Name"),
    Setting("paths.data", None, "path", "Daten", example="D:/x"),
    Setting("paths.scope", "scopes/standard", "path", "Ort des Scopes", global_only=True),
    Setting("paths.env_file", ".env", "path", "env", global_only=True),
    Setting("secret.token", None, "str", "Token", secret=True),
], sections={"app": "Anwendung", "paths": "Pfade"})


def _manager(tmp_path, *, base_mirror=None, scope_mirror=None, notices=None):
    def scope(resolved, base: Path):
        folder = Path(resolved.get("paths.scope"))
        folder = folder if folder.is_absolute() else base / folder
        return Scope("scope", folder / "meta" / "config.yaml", folder / "meta" / ".env", folder,
                     scope_mirror, ("Scope-Konfiguration",))

    return ConfigManager(SCHEMA, env_prefix="DEMO", home=lambda: tmp_path / "home",
                         env_file_setting="paths.env_file", mirror=base_mirror,
                         notice=(notices.append if notices is not None else (lambda m: None)), scope=scope)


def test_scope_is_more_specific_than_the_base(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("app:\n  port: 1\n  name: global\n", encoding="utf-8")
    (home / ".env").write_text("DEMO__APP__NAME=global-env\n", encoding="utf-8")
    manager = _manager(tmp_path)
    loaded = manager.load(environ={})
    assert loaded.scope_created and loaded.scope.config_file.is_file()
    template = loaded.scope.config_file.read_text(encoding="utf-8")
    assert "Scope-Konfiguration" in template and "paths.scope" not in template and "scope:" not in template
    assert (loaded.get("app.port"), loaded.origin("app.port")) == (1, "config")
    assert (loaded.get("app.name"), loaded.origin("app.name")) == ("global-env", ".env")
    meta = loaded.scope.config_file.parent
    (meta / "config.yaml").write_text("app:\n  port: 2\n  name: scope\npaths:\n  data: daten\n", encoding="utf-8")
    loaded = manager.load(environ={})
    assert (loaded.get("app.port"), loaded.origin("app.port")) == (2, "scope")
    assert (loaded.get("app.name"), loaded.origin("app.name")) == ("scope", "scope")
    (meta / ".env").write_text("DEMO__APP__PORT=3\n", encoding="utf-8")
    loaded = manager.load(environ={"DEMO__APP__NAME": "prozess"}, overrides=["app.port=4"])
    assert (loaded.get("app.port"), loaded.origin("app.port")) == (4, "cli")
    assert loaded.origin("app.name") == "env"
    assert manager.load(environ={}).origin("app.port") == "scope .env"
    assert loaded.base_for("paths.data") == home / "scopes" / "standard", "relativ zum Scope-Ordner"
    assert loaded.base_for("app.port") == home


def test_global_only_settings_are_ignored_in_the_scope(tmp_path):
    notices: list[str] = []
    manager = _manager(tmp_path, notices=notices)
    loaded = manager.load(environ={})
    loaded.scope.config_file.write_text("paths:\n  scope: anderswo\n  env_file: x\n", encoding="utf-8")
    loaded = manager.load(environ={})
    assert loaded.get("paths.scope") == "scopes/standard" and loaded.origin("paths.scope") == "default"
    assert any("nur global" in n and "paths.scope" in n for n in notices)


def test_scope_location_can_come_from_cli(tmp_path):
    manager = _manager(tmp_path)
    loaded = manager.load(environ={}, overrides=[f"paths.scope={tmp_path / 'woanders'}"])
    assert loaded.scope.folder == tmp_path / "woanders" and loaded.scope.config_file.is_file()


def test_edit_targets_and_mirrors(tmp_path):
    base_mirror, scope_mirror = MemoryMirror(), MemoryMirror()
    manager = _manager(tmp_path, base_mirror=base_mirror, scope_mirror=scope_mirror)
    loaded = manager.set("app.port", 7, environ={}, target="scope")
    assert yaml.safe_load(loaded.scope.config_file.read_text(encoding="utf-8")) == {"app": {"port": 7}}
    assert loaded.origin("app.port") == "scope"
    assert scope_mirror.values["app.port"] == 7 and base_mirror.writes == 0, "Spiegel des Scopes"
    assert "scope_config_file" in scope_mirror.meta
    loaded = manager.set("app.port", 5, environ={})
    assert loaded.get("app.port") == 7, "Scope bleibt spezifischer"
    assert yaml.safe_load((tmp_path / "home" / "config.yaml").read_text(encoding="utf-8"))["app"]["port"] == 5
    with pytest.raises(ConfigError, match="nur global"):
        manager.set("paths.scope", "x", environ={}, target="scope")
    manager.set("paths.scope", str(tmp_path / "zwei"), environ={})
    assert manager.load(environ={}).scope.folder == tmp_path / "zwei"
    manager.set_many({"app.name": "n", "app.port": 9}, environ={}, target="scope")
    loaded = manager.reset("app.port", environ={}, target="scope")
    assert loaded.get("app.port") == 5 and loaded.get("app.name") == "n"
    loaded = manager.reset(None, environ={}, target="scope")
    assert loaded.get("app.name") == "demo" and "paths.scope" not in loaded.scope.config_file.read_text(encoding="utf-8")


def test_invalid_scope_edit_is_rolled_back(tmp_path):
    manager = _manager(tmp_path)
    loaded = manager.load(environ={})
    before = loaded.scope.config_file.read_text(encoding="utf-8")
    with pytest.raises(ConfigError):
        manager.set("app.port", "keine zahl", environ={}, target="scope")
    assert loaded.scope.config_file.read_text(encoding="utf-8") == before


def test_without_scope_nothing_changes(tmp_path):
    manager = ConfigManager(SCHEMA, env_prefix="DEMO", home=lambda: tmp_path / "home")
    loaded = manager.load(environ={})
    assert loaded.scope is None and loaded.base_for("app.port") == tmp_path / "home"
    with pytest.raises(ConfigError, match="Keine Scope-Ebene"):
        manager.set("app.port", 1, environ={}, target="scope")
