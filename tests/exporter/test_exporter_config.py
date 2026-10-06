"""Exporter-Konfiguration: Defaults, Vorrang, Fehler."""

from __future__ import annotations

from pathlib import Path

import pytest

from chatexporter.exporter.config import (EXPORTABLE_SOURCES, KNOWN_FORMATS, ExporterConfigError,
                                          discover_config, load_exporter_config)


def _write(folder: Path, text: str) -> Path:
    path = folder / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("CHATEXPORTER_CONFIG", "CHATEXPORTER_ENV_FILE", "CHATEXPORTER_DATA_ROOT",
                 "CHATEXPORTER_RAW_ROOT", "CHATEXPORTER_EXPORT_ROOT", "CHATEXPORTER_EXPORT_FORMATS",
                 "CHATEXPORTER_EXPORT_SOURCES"):
        monkeypatch.delenv(name, raising=False)


def test_data_root_provides_defaults(tmp_path):
    cfg = load_exporter_config(_write(tmp_path, "storage:\n  data_root: data\n"))
    assert cfg.raw_root == (tmp_path / "data" / "raw_storage").resolve()
    assert cfg.export_root == (tmp_path / "data" / "exports").resolve()
    assert cfg.formats == KNOWN_FORMATS == ("markdown", "json")
    assert cfg.sources == EXPORTABLE_SOURCES == ("chatgpt", "opencode", "codex", "claude")
    assert cfg.manifests_dir == cfg.export_root / "manifests"
    assert cfg.staging_dir == cfg.export_root.parent / ".storage" / "staging" / "exports"


def test_section_values_and_relative_paths(tmp_path):
    cfg = load_exporter_config(_write(tmp_path, (
        "storage:\n  data_root: data\n"
        "exporter:\n  root: out\n  formats: [json]\n  sources: [chatgpt]\n")))
    assert cfg.export_root == (tmp_path / "out").resolve()
    assert cfg.formats == ("json",)


def test_explicit_raw_root_beats_data_root(tmp_path):
    cfg = load_exporter_config(_write(tmp_path, "storage:\n  data_root: data\n  raw_root: roh\n"))
    assert cfg.raw_root == (tmp_path / "roh").resolve()
    assert cfg.export_root == (tmp_path / "data" / "exports").resolve()


def test_precedence_cli_over_env_over_config(tmp_path, monkeypatch):
    path = _write(tmp_path, "exporter:\n  root: aus_config\n  formats: [markdown]\n")
    assert load_exporter_config(path).export_root == (tmp_path / "aus_config").resolve()
    monkeypatch.setenv("CHATEXPORTER_EXPORT_ROOT", str(tmp_path / "aus_env"))
    monkeypatch.setenv("CHATEXPORTER_EXPORT_FORMATS", "json, markdown")
    cfg = load_exporter_config(path)
    assert cfg.export_root == tmp_path / "aus_env"
    assert cfg.formats == ("json", "markdown")
    cfg = load_exporter_config(path, overrides={"export_root": tmp_path / "aus_cli", "formats": ["json"],
                                                "raw_root": tmp_path / "cli_raw", "sources": None})
    assert cfg.export_root == (tmp_path / "aus_cli").resolve()
    assert cfg.formats == ("json",)
    assert cfg.raw_root == (tmp_path / "cli_raw").resolve()


def test_dotenv_is_read(tmp_path):
    (tmp_path / ".env").write_text("CHATEXPORTER_EXPORT_FORMATS=json\n", encoding="utf-8")
    assert load_exporter_config(_write(tmp_path, "storage: {}\n")).formats == ("json",)


def test_without_config_file_defaults_are_used(tmp_path):
    cfg = load_exporter_config(tmp_path / "gibtesnicht.yaml")
    assert cfg.formats == KNOWN_FORMATS and cfg.config_file == tmp_path / "gibtesnicht.yaml"


@pytest.mark.parametrize("text", [
    "exporter:\n  formats: [pdf]\n",
    "exporter:\n  sources: [gibtesnicht]\n",
    "exporter:\n  formats: 5\n",
    "exporter: 5\n",
])
def test_invalid_values_are_errors(tmp_path, text):
    with pytest.raises(ExporterConfigError):
        load_exporter_config(_write(tmp_path, text))


def test_discover_uses_the_shared_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATEXPORTER_CONFIG", str(tmp_path / "x.yaml"))
    assert discover_config() == (tmp_path / "x.yaml").resolve()
    assert discover_config(tmp_path / "y.yaml") == (tmp_path / "y.yaml").resolve()


def test_format_aliases(tmp_path):
    cfg = load_exporter_config(_write(tmp_path, "exporter:\n  formats: [md]\n"))
    assert cfg.formats == ("markdown",)