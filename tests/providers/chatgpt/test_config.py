import os
from pathlib import Path
from chatexporter.providers.chatgpt.config.loader import load_config


def test_relative_paths_resolve_against_config(tmp_path, monkeypatch):
    monkeypatch.delenv("CHATEXPORTER_RAW_ROOT", raising=False)
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("storage:\n  raw_root: data\n", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.storage.raw_root == (tmp_path / "data").resolve()


def test_listing_limit_clamped_to_100(tmp_path):
    p=tmp_path/'c.yaml'; p.write_text('sync:\n  listing_limit: 999\n',encoding='utf-8')
    assert load_config(p).sync.listing_limit == 100


def test_max_errors_per_run_defaults_to_five_and_clamps_to_one(tmp_path):
    p = tmp_path / 'c.yaml'
    p.write_text('sync:\n  max_errors_per_run: 0\n', encoding='utf-8')
    assert load_config(p).sync.max_errors_per_run == 1

    p2 = tmp_path / 'd.yaml'
    p2.write_text('sync: {}\n', encoding='utf-8')
    assert load_config(p2).sync.max_errors_per_run == 5


def test_bootstrap_paths_can_live_outside_version_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("CHATEXPORTER_VENV_PATH", raising=False)
    monkeypatch.delenv("CHATEXPORTER_ENV_FILE", raising=False)
    version = tmp_path / "ChatExporter_Gen4_pre-4"
    version.mkdir()
    cfg_file = version / "config.yaml"
    cfg_file.write_text(
        "bootstrap:\n  venv_path: ../.venv\n  env_file: ../.env\n",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.bootstrap.venv_path == (tmp_path / ".venv").resolve()
    assert cfg.bootstrap.env_file == (tmp_path / ".env").resolve()


def test_configured_external_dotenv_overrides_yaml_without_mutating_process_env(tmp_path, monkeypatch):
    for key in ("CHATEXPORTER_RAW_ROOT", "CHATEXPORTER_ENV_FILE"):
        monkeypatch.delenv(key, raising=False)
    version = tmp_path / "ChatExporter_Gen4_pre-4"
    version.mkdir()
    data = tmp_path / "data"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"CHATEXPORTER_RAW_ROOT={data / 'raw_from_env'}\n"
        "",
        encoding="utf-8",
    )
    cfg_file = version / "config.yaml"
    cfg_file.write_text(
        "bootstrap:\n  env_file: ../.env\n"
        "storage:\n  raw_root: ./raw_from_yaml\n"
        "",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.storage.raw_root == (data / "raw_from_env").resolve()
    assert "CHATEXPORTER_RAW_ROOT" not in os.environ


def test_real_environment_beats_configured_dotenv(tmp_path, monkeypatch):
    version = tmp_path / "version"
    version.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_text("CHATEXPORTER_RAW_ROOT=from_dotenv\n", encoding="utf-8")
    cfg_file = version / "config.yaml"
    cfg_file.write_text("bootstrap:\n  env_file: ../.env\n", encoding="utf-8")
    process_root = tmp_path / "from_process"
    monkeypatch.setenv("CHATEXPORTER_RAW_ROOT", str(process_root))
    cfg = load_config(cfg_file)
    assert cfg.storage.raw_root == process_root.resolve()


def test_external_env_can_override_sync_settings(tmp_path, monkeypatch):
    for key in ("CHATEXPORTER_FETCH_FILES", "CHATEXPORTER_MAX_ERRORS_PER_RUN"):
        monkeypatch.delenv(key, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CHATEXPORTER_FETCH_FILES=false\n"
        "CHATEXPORTER_MAX_ERRORS_PER_RUN=3\n"
        "",
        encoding="utf-8",
    )
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("bootstrap:\n  env_file: ./.env\n", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.sync.fetch_files is False
    assert cfg.sync.max_errors_per_run == 3
