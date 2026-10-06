"""Updater-Konfiguration aus der gemeinsamen config.yaml."""

from __future__ import annotations

import pytest

from chatexporter.raw_session_updater.config import load_updater_config
from chatexporter.raw_session_updater.registry import KNOWN_SOURCES


def test_data_root_and_defaults(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(f"storage:\n  data_root: {tmp_path / 'data'}\n", encoding="utf-8")
    cfg = load_updater_config(p)
    assert cfg.config_file == p
    assert cfg.store_root == tmp_path / "data" / "raw_storage"
    assert cfg.runtime_root == tmp_path / "data" / ".storage"
    assert cfg.status_root == tmp_path / "data" / ".storage" / "status_registry"
    assert cfg.index_path == cfg.status_root / "storage_index.json"
    assert cfg.sources == KNOWN_SOURCES


def test_sources_and_provider_sections(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("storage:\n  raw_root: raw\nraw_session_updater:\n  sources: [opencode, codex]\n"
                 "providers:\n  codex:\n    source_root: C:/x\n", encoding="utf-8")
    cfg = load_updater_config(p)
    assert cfg.store_root == tmp_path / "raw"
    assert cfg.sources == ("opencode", "codex")
    assert cfg.provider_sections["codex"]["source_root"] == "C:/x"
    # nicht gesetzte Werte (None) werden nicht weitergereicht
    assert "db_path" not in cfg.provider_sections["opencode"]


def test_unknown_source_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("raw_session_updater:\n  sources: [chatgpt, gibtesnicht]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_updater_config(p)


def test_env_beats_yaml(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("storage:\n  raw_root: raw\nraw_session_updater:\n  sources: [codex]\n", encoding="utf-8")
    monkeypatch.setenv("CHATEXPORTER_RAW_ROOT", str(tmp_path / "env_raw"))
    monkeypatch.setenv("CHATEXPORTER_SOURCES", "claude,codex")
    cfg = load_updater_config(p)
    assert cfg.store_root == tmp_path / "env_raw"
    assert cfg.sources == ("claude", "codex")


def test_discovery_skips_config_inside_code_folder(tmp_path, monkeypatch):
    """Regression 2026-10-01: Start aus ChatExporter_Gen4_pre-5/ nahm dessen
    alte config.yaml statt workspace/config.yaml."""
    from chatexporter.raw_session_updater.config import discover_config
    from chatexporter.providers.chatgpt.config.loader import discover_config as chatgpt_discover
    workspace = tmp_path / "workspace"
    old = workspace / "ChatExporter_Gen4_pre-5"
    (old / "src" / "chatexporter").mkdir(parents=True)
    (old / "config.yaml").write_text("{}\n", encoding="utf-8")
    (workspace / "config.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.delenv("CHATEXPORTER_CONFIG", raising=False)
    assert discover_config(start=old) == workspace / "config.yaml"
    assert chatgpt_discover(start=old) == workspace / "config.yaml"
    plain = tmp_path / "anderswo"
    plain.mkdir()
    (plain / "config.yaml").write_text("{}\n", encoding="utf-8")
    assert discover_config(start=plain) == plain / "config.yaml", "normale Ordner unveraendert"


def test_program_banner_names_code_location():
    from chatexporter.raw_session_updater.config import program_banner, program_info
    info = program_info()
    assert info["code"].endswith("chatexporter") and info["python"]
    assert any(info["code"] in line for line in program_banner())


def test_updater_and_chatgpt_resolve_same_paths(tmp_path):
    """Raw Session Updater und ChatGPT-Provider lesen dieselbe config.yaml unabhaengig --
    sie muessen zu denselben Ablagepfaden kommen."""
    from chatexporter.providers.chatgpt.config.loader import load_config
    from chatexporter.providers.chatgpt.storage.layout import resolve_store_layout
    for storage in (f"  data_root: {tmp_path / 'data'}\n",
                    "  raw_root: ./raw\n",
                    "  raw_root: ./raw\n  runtime_root: ./rt\n  status_root: ./st\n"):
        p = tmp_path / "config.yaml"
        p.write_text("storage:\n" + storage, encoding="utf-8")
        updater = load_updater_config(p)
        layout = resolve_store_layout(load_config(p).storage, "chatgpt")
        assert updater.store_root == layout.store_root
        assert updater.runtime_root == layout.runtime_root
        assert updater.status_root == layout.status_root
        assert updater.index_path == layout.index_path
        assert updater.runs_dir == layout.runs_dir
