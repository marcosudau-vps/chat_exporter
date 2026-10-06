"""layered_config: Schema, Quellen, Zusammenfuehren, Vorlage, Bearbeiten, Manager, Spiegel."""

from __future__ import annotations

import json
import sys

import pytest
import yaml

from layered_config import (ConfigError, ConfigManager, Layer, MemoryMirror, RegistryMirror, Schema,
                            Setting, resolve)
from layered_config.sources import environment_layer, flatten, overrides_layer, unflatten
from layered_config.template import dump_value, render_template
from layered_config.yaml_edit import set_value, unset_value

SCHEMA = Schema([
    Setting("app.name", "demo", "str", "Name"),
    Setting("app.port", 8080, "int", "Port", env=("DEMO_PORT",)),
    Setting("app.debug", False, "bool", "Debug"),
    Setting("app.tags", ["a"], "list", "Tags"),
    Setting("app.mode", "auto", "str", "Modus", choices=("auto", "full")),
    Setting("paths.data", None, "path", "Daten", example="D:/BEISPIEL/daten"),
    Setting("paths.env_file", ".env", "path", "env"),
    Setting("secret.token", None, "str", "Token", secret=True),
    Setting("deep.a.b", 1, "int", "tief"),
    Setting("plan.trigger", {"type": "daily"}, "dict", "Trigger"),
], sections={"app": "Anwendung"})


# -- Schema / Umwandlung ----------------------------------------------------------

@pytest.mark.parametrize("path,raw,expected", [
    ("app.port", "9000", 9000), ("app.port", 7, 7),
    ("app.debug", "ja", True), ("app.debug", "off", False), ("app.debug", 1, True),
    ("app.tags", "x, y", ["x", "y"]), ("app.tags", "[x, y]", ["x", "y"]), ("app.tags", ["z"], ["z"]),
    ("app.mode", "FULL", "full"), ("plan.trigger", "{type: weekly}", {"type": "weekly"}),
])
def test_coerce(path, raw, expected):
    assert SCHEMA.get(path).coerce(raw) == expected


@pytest.mark.parametrize("path,raw", [
    ("app.port", "abc"), ("app.port", True), ("app.debug", "vielleicht"), ("app.mode", "bogus"),
    ("app.tags", 5), ("plan.trigger", "kein objekt"), ("app.name", {"a": 1}),
])
def test_coerce_rejects(path, raw):
    with pytest.raises(ConfigError, match=path):
        SCHEMA.get(path).coerce(raw)


def test_schema_rejects_inconsistent_definitions():
    with pytest.raises(ValueError):
        Schema([Setting("a", 1, "int"), Setting("a", 2, "int")])
    with pytest.raises(ValueError):
        Schema([Setting("a", 1, "int"), Setting("a.b", 2, "int")])
    with pytest.raises(ValueError):
        Setting("x", type="gibtesnicht")


# -- Quellen und Zusammenfuehren --------------------------------------------------------

def test_flatten_and_unflatten_roundtrip():
    doc = {"app": {"name": "x", "tags": ["q"]}, "plan": {"trigger": {"type": "weekly", "at": "06:00"}},
           "unbekannt": {"tief": {"wert": 1}}, "deep": None}
    flat = flatten(doc, SCHEMA)
    assert flat["plan.trigger"] == {"type": "weekly", "at": "06:00"}   # dict-Einstellung bleibt ganz
    assert flat["unbekannt.tief.wert"] == 1
    assert "deep" not in flat                                          # None-Abschnitt = leer
    assert unflatten(flat)["app"] == {"name": "x", "tags": ["q"]}


def test_environment_layer_named_and_generic():
    env = {"DEMO_PORT": "1", "DEMO__APP__PORT": "2", "DEMO__APP__DEBUG": "true",
           "DEMO__APP__TAGS": "[x, y]", "ANDERES": "z", "DEMO__PATHS__ENV_FILE": "x"}
    layer = environment_layer(env, SCHEMA, prefix="DEMO", name="env", exclude=("paths.env_file",))
    assert layer.values == {"app.port": "1", "app.debug": "true", "app.tags": ["x", "y"]}


def test_overrides_layer():
    assert overrides_layer(["app.port=5", "app.tags=[a, b]", "app.name= mit = zeichen"]).values == \
        {"app.port": "5", "app.tags": ["a", "b"], "app.name": " mit = zeichen"}
    with pytest.raises(ConfigError):
        overrides_layer(["ohne_gleich"])
    with pytest.raises(ConfigError):
        overrides_layer(["=wert"])


def test_resolve_precedence_and_origins():
    resolved = resolve(SCHEMA, [
        Layer("config", {"app.port": 1, "app.name": "aus-datei", "fremd.x": 3}),
        Layer(".env", {"app.port": "2"}),
        Layer("env", {"app.port": "3", "app.debug": "1"}),
        Layer("cli", {"app.port": "4"}),
    ])
    assert resolved.get("app.port") == 4 and resolved.origin("app.port") == "cli"
    assert resolved.get("app.name") == "aus-datei" and resolved.origin("app.name") == "config"
    assert resolved.get("app.debug") is True and resolved.origin("app.debug") == "env"
    assert resolved.get("app.mode") == "auto" and resolved.origin("app.mode") == "default"
    assert resolved.get("fremd.x") == 3                                  # unbekannt bleibt erhalten
    assert resolved.section("app")["port"] == 4
    assert resolved.document["deep"] == {"a": {"b": 1}}


def test_resolve_strict_and_section_errors():
    with pytest.raises(ConfigError, match="Unbekannte"):
        resolve(SCHEMA, [Layer("cli", {"fremd": 1})], strict=True)
    with pytest.raises(ConfigError, match="Abschnitt"):
        resolve(SCHEMA, [Layer("cli", {"app": 1})])


# -- Vorlage ------------------------------------------------------------------------------

def test_template_is_complete_commented_and_marks_examples():
    text = render_template(SCHEMA, header=["Titel"], env_prefix="DEMO")
    assert yaml.safe_load(text) is None, "jede Zeile ist auskommentiert"
    for setting in SCHEMA:
        assert f"{setting.parts[-1]}:" in text
    assert "#   port: 8080" in text                       # echter Standard
    assert "#   data: D:/BEISPIEL/daten" in text          # Beispielwert
    assert "BEISPIEL – kein Standardwert" in text
    assert "geheim" in text                               # Secret nur angedeutet
    assert "DEMO__APP__PORT" in text and "DEMO_PORT" in text
    assert "## Titel" in text and "Anwendung" in text
    # Jede Zeile einzeln aktivierbar: alle Zeilen entkommentiert = gueltiges YAML mit allen Werten
    active = "\n".join(line[2:] if line.startswith("# ") else line for line in text.splitlines()
                       if not line.startswith("##"))
    loaded = yaml.safe_load(active)
    assert loaded["app"]["port"] == 8080 and loaded["deep"]["a"]["b"] == 1


def test_dump_value():
    assert dump_value(["a", "b"]) == "[a, b]"
    assert dump_value(True) == "true" and dump_value(5) == "5"
    # Werte bleiben beim Zurueklesen gleich (auch solche, die YAML sonst umdeuten wuerde)
    for value in ("3:30", "03:00", "true", "1e3", "", "a: b", ["x", "3:30"], {"at": "6:00"}, None, 1.5):
        assert yaml.safe_load(dump_value(value)) == value, value


# -- Bearbeiten ------------------------------------------------------------------------------

def _active(text):
    return yaml.safe_load(text) or {}


def test_set_activates_template_line_with_parents():
    text = render_template(SCHEMA)
    out = set_value(text, "deep.a.b", "5")
    assert _active(out) == {"deep": {"a": {"b": 5}}}
    out = set_value(out, "app.port", "9")
    assert _active(out) == {"deep": {"a": {"b": 5}}, "app": {"port": 9}}
    out = set_value(out, "app.port", "10")                     # vorhandene aktive Zeile
    assert _active(out)["app"]["port"] == 10 and out.count("port: 10") == 1


def test_set_keeps_inline_comments_and_appends_missing_keys():
    text = "app:\n  port: 1        # mein Kommentar\n\nanderes: 1\n"
    out = set_value(text, "app.port", "2")
    assert "  port: 2        # mein Kommentar" in out
    out = set_value(out, "app.debug", "true")                  # neu unter vorhandenem Abschnitt
    out = set_value(out, "plan.trigger", "{type: weekly}")     # neuer Abschnitt am Ende
    assert _active(out) == {"app": {"port": 2, "debug": True}, "anderes": 1, "plan": {"trigger": {"type": "weekly"}}}


def test_set_uses_active_parent_elsewhere_instead_of_commented_template():
    text = "app:\n  name: x\n\n# app:\n#   port: 8080\n"
    out = set_value(text, "app.port", "9")
    assert _active(out) == {"app": {"name": "x", "port": 9}}


def test_set_value_replaces_a_block_with_a_scalar():
    text = "plan:\n  trigger:\n    type: daily\n    at: '03:00'\n"
    out = set_value(text, "plan.trigger", "{type: weekly}")
    assert _active(out) == {"plan": {"trigger": {"type": "weekly"}}}


def test_set_rejects_child_of_scalar():
    with pytest.raises(ConfigError):
        set_value("app: 5\n", "app.port", "1")


def test_unset_comments_out_line_and_block():
    text = "app:\n  port: 1\n  name: x\nplan:\n  trigger:\n    type: daily\n"
    out, changed = unset_value(text, "app.port")
    assert changed and _active(out) == {"app": {"name": "x"}, "plan": {"trigger": {"type": "daily"}}}
    out, changed = unset_value(out, "plan.trigger")
    assert changed and _active(out) == {"app": {"name": "x"}, "plan": None}
    out2, changed = unset_value(out, "app.gibtesnicht")
    assert not changed and out2 == out


# -- Manager ---------------------------------------------------------------------------------

@pytest.fixture
def mgr(tmp_path):
    mirror = MemoryMirror()
    manager = ConfigManager(SCHEMA, env_prefix="DEMO", home=lambda: tmp_path / "home",
                            config_env="DEMO_CONFIG", env_file_setting="paths.env_file",
                            mirror=mirror, header=["Demo"], notice=lambda _m: None)
    return manager, mirror


def test_manager_creates_missing_file_in_home(mgr, tmp_path):
    manager, mirror = mgr
    loaded = manager.load(environ={})
    assert loaded.created and loaded.config_file == tmp_path / "home" / "config.yaml"
    assert loaded.get("app.port") == 8080 and loaded.origin("app.port") == "default"
    assert mirror.values["app.port"] == 8080 and "secret.token" not in mirror.values
    assert mirror.meta["config_file"] == str(loaded.config_file)
    again = manager.load(environ={})
    assert not again.created and mirror.writes == 1, "unveraenderter Zustand wird nicht erneut gespiegelt"
    manager.refresh(environ={})
    assert mirror.writes == 2, "refresh spiegelt immer"


def test_manager_lookup_order(mgr, tmp_path):
    manager, _ = mgr
    explicit = tmp_path / "x.yaml"
    assert manager.locate(explicit, {"DEMO_CONFIG": str(tmp_path / "env.yaml")}) == explicit
    assert manager.locate(None, {"DEMO_CONFIG": str(tmp_path / "env.yaml")}) == tmp_path / "env.yaml"
    found = tmp_path / "gefunden.yaml"
    manager.discover = lambda: found
    assert manager.locate(None, {}) == found


def test_manager_dotenv_and_precedence(mgr, tmp_path):
    manager, _ = mgr
    cfg = tmp_path / "c.yaml"
    cfg.write_text("app:\n  port: 1\n  name: datei\n", encoding="utf-8")
    (tmp_path / ".env").write_text("DEMO_PORT=2\nDEMO__APP__DEBUG=true\nDEMO__PATHS__ENV_FILE=nein\n", encoding="utf-8")
    loaded = manager.load(cfg, environ={})
    assert (loaded.get("app.port"), loaded.origin("app.port")) == (2, ".env")
    assert loaded.get("app.debug") is True and loaded.env_file == tmp_path / ".env"
    assert loaded.get("paths.env_file") == ".env", "die .env kann ihren eigenen Pfad nicht setzen"
    loaded = manager.load(cfg, ["app.port=4"], environ={"DEMO_PORT": "3"})
    assert (loaded.get("app.port"), loaded.origin("app.port")) == (4, "cli")
    loaded = manager.load(cfg, environ={"DEMO_PORT": "3"})
    assert (loaded.get("app.port"), loaded.origin("app.port")) == (3, "env")


def test_manager_set_reset_with_backup_and_mirror(mgr, tmp_path):
    manager, mirror = mgr
    cfg = tmp_path / "c.yaml"
    manager.load(cfg, environ={})
    loaded = manager.set("app.port", "9100", explicit=cfg, environ={})
    assert loaded.get("app.port") == 9100 and loaded.origin("app.port") == "config"
    assert mirror.values["app.port"] == 9100
    assert list((tmp_path / ".config_backups").glob("c.yaml.*.bak"))
    loaded = manager.reset("app.port", explicit=cfg, environ={})
    assert loaded.get("app.port") == 8080 and loaded.origin("app.port") == "default"
    manager.set("app.tags", "x,y", explicit=cfg, environ={})
    loaded = manager.reset(None, explicit=cfg, environ={})
    assert cfg.read_text(encoding="utf-8") == manager.template()
    assert loaded.get("app.tags") == ["a"]


def test_manager_set_validates_before_writing(mgr, tmp_path):
    manager, mirror = mgr
    cfg = tmp_path / "c.yaml"
    manager.load(cfg, environ={})
    before = cfg.read_text(encoding="utf-8")
    writes = mirror.writes
    for key, value in (("app.port", "abc"), ("app.mode", "bogus"), ("gibt.es.nicht", "1"),
                       ("app", "1"), ("secret.token", "x")):
        with pytest.raises(ConfigError):
            manager.set(key, value, explicit=cfg, environ={})
    assert cfg.read_text(encoding="utf-8") == before
    assert mirror.writes == writes, "nichts angewendet, nichts gespiegelt"


def test_manager_restores_file_if_the_result_is_invalid(mgr, tmp_path):
    manager, mirror = mgr
    cfg = tmp_path / "c.yaml"
    cfg.write_text("app:\n  port: abc\n", encoding="utf-8")      # schon kaputt
    with pytest.raises(ConfigError):
        manager.set("app.name", "x", explicit=cfg, environ={})
    assert cfg.read_text(encoding="utf-8") == "app:\n  port: abc\n"
    assert mirror.values is None


def test_manager_reports_broken_yaml(mgr, tmp_path):
    manager, _ = mgr
    cfg = tmp_path / "c.yaml"
    cfg.write_text("app: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML"):
        manager.load(cfg, environ={})
    cfg.write_text("- liste\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Objekt"):
        manager.load(cfg, environ={})


def test_backups_are_limited(mgr, tmp_path):
    manager, _ = mgr
    manager.backups = 3
    cfg = tmp_path / "c.yaml"
    for port in range(6):
        manager.set("app.port", str(9000 + port), explicit=cfg, environ={})
    assert len(list((tmp_path / ".config_backups").glob("*.bak"))) == 3


@pytest.mark.skipif(sys.platform != "win32", reason="Registry nur unter Windows")
def test_registry_mirror_writes_exact_state():
    import uuid
    root = rf"Software\LayeredConfigTest_{uuid.uuid4().hex[:8]}"
    mirror = RegistryMirror(root + r"\config\Current", root + r"\config")
    try:
        mirror.write({"a.b": "text", "a.n": 5, "a.l": ["x"], "weg": 1}, {"config_file": "f"})
        mirror.write({"a.b": "text", "a.n": 6, "a.l": ["x"]}, {"config_file": "f"})
        values = mirror.read_all()
        assert values == {"a.b": "text", "a.n": "6", "a.l": json.dumps(["x"])}
    finally:
        mirror.delete_tree(root)
    assert mirror.read_all() == {}
