"""Storage: Formaterkennung, Anlage, Konfigurationsebene, Schutz alter Ordner, Sperre, Aufraeumen."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import chatexporter.config as shared_config
from chatexporter.config import storage as st


def _legacy(root: Path) -> Path:
    (root / "runtime" / "runs").mkdir(parents=True)
    (root / "raw_storage" / "chatgpt").mkdir(parents=True)
    return root


def _snapshot(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


# -- Formaterkennung --------------------------------------------------------------------------

def test_detect_formats(tmp_path):
    assert st.detect(tmp_path / "fehlt")[0] == st.FORMAT_EMPTY
    (tmp_path / "fremd").mkdir()
    (tmp_path / "fremd" / "notiz.txt").write_text("x", encoding="utf-8")
    # Entscheidung des Benutzers 2026-10-05: ein nicht leerer Ordner wird nicht ungefragt zum Storage.
    assert st.detect(tmp_path / "fremd") == (st.FORMAT_FOREIGN, "Ordner ist nicht leer und kein Storage "
                                                                "(enthaelt notiz.txt)")
    (tmp_path / "nur_system").mkdir()
    (tmp_path / "nur_system" / "desktop.ini").write_text("x", encoding="utf-8")
    (tmp_path / "nur_system" / "Thumbs.db").write_text("x", encoding="utf-8")
    assert st.detect(tmp_path / "nur_system")[0] == st.FORMAT_EMPTY, "Systemdateien zaehlen nicht"
    (tmp_path / "leer").mkdir()
    assert st.detect(tmp_path / "leer")[0] == st.FORMAT_EMPTY
    assert st.detect(_legacy(tmp_path / "alt"))[0] == st.FORMAT_LEGACY
    v1 = st.Storage(tmp_path / "neu")
    st.ensure(v1)
    assert st.detect(v1.root) == (st.FORMAT_CURRENT, ".storage/storage.yaml mit storage_schema 2")
    assert st.FORMAT_LEGACY == "storage-schema-1" and st.FORMAT_CURRENT == "storage-schema-2"


@pytest.mark.parametrize("build,reason", [
    (lambda r: (r / ".storage").mkdir(parents=True), "ohne gueltige"),
    (lambda r: ((r / ".storage").mkdir(parents=True), (r / ".storage" / "storage.yaml").write_text("storage_schema: 2\n")),
     "ohne gueltige"),
    (lambda r: (r / "runtime").mkdir(parents=True), "ohne die erwarteten Marker"),
    (lambda r: (r / "raw_storage").mkdir(parents=True), "raw_storage/ ohne"),
])
def test_unclear_formats_are_refused_without_changes(tmp_path, build, reason):
    root = tmp_path / "x"
    build(root)
    before = _snapshot(root)
    fmt, why = st.detect(root)
    assert fmt == st.FORMAT_UNCLEAR and reason in why
    with pytest.raises(st.StorageError, match="nichts wurde veraendert"):
        st.ensure(st.Storage(root))
    assert _snapshot(root) == before


def test_both_meta_and_runtime_is_unclear(tmp_path):
    root = tmp_path / "beides"
    st.ensure(st.Storage(root))
    (root / "runtime").mkdir()
    assert st.detect(root)[0] == st.FORMAT_UNCLEAR


def test_newer_schema_is_refused(tmp_path):
    storage = st.Storage(tmp_path / "s")
    st.write_identity(storage, st.Identity("abc", "s", 99, "2026-01-01T00:00:00Z"))
    fmt, why = st.detect(storage.root)
    assert fmt == st.FORMAT_UNCLEAR and "Storage-Schema 99" in why


def test_ensure_creates_marker_once(tmp_path):
    storage = st.Storage(tmp_path / "s")
    identity = st.ensure(storage)
    assert len(identity.id) == 32 and identity.name == "s" and identity.storage_schema == st.STORAGE_SCHEMA == 2
    data = yaml.safe_load(storage.marker.read_text(encoding="utf-8"))
    assert data["id"] == identity.id and data["created_at"].endswith("Z")
    assert st.ensure(storage) == identity, "zweiter Aufruf liest nur"
    with pytest.raises(st.StorageError, match="storage migrate"):
        st.ensure(st.Storage(_legacy(tmp_path / "alt")))


# -- Konfiguration ------------------------------------------------------------------------------

def test_default_storage_and_layering(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("exporter:\n  formats: [json]\nlogging:\n  retention: 7d\n", encoding="utf-8")
    loaded = shared_config.load(cfg)
    storage = shared_config.storage_of(loaded)
    assert storage.root == tmp_path / "storages" / "default"
    assert storage.marker.is_file() and storage.config_file.is_file(), "Storage samt Vorlage angelegt"
    assert "Storage-Konfiguration" in storage.config_file.read_text(encoding="utf-8")
    assert loaded.get("storage.data_root") == str(storage.root)
    storage.config_file.write_text("exporter:\n  formats: [markdown]\n  root: ausgaben\n"
                                   "storage:\n  root: woanders\n", encoding="utf-8")
    storage.env_file.write_text("CHATEXPORTER_LOG_RETENTION=1d\n", encoding="utf-8")
    loaded = shared_config.load(cfg)
    assert (loaded.get("exporter.formats"), loaded.origin("exporter.formats")) == (["markdown"], "storage")
    assert (loaded.get("logging.retention"), loaded.origin("logging.retention")) == ("1d", "storage .env")
    assert shared_config.storage_of(loaded).root == storage.root, "storage.root gilt nur global"
    assert shared_config.resolve_path(loaded, loaded.get("exporter.root"), "exporter.root") == \
        storage.root / "ausgaben", "relativ zum Storage"
    from chatexporter.exporter.config import load_exporter_config
    exporter = load_exporter_config(cfg)
    assert exporter.export_root == storage.root / "ausgaben" and exporter.formats == ("markdown",)


def test_storage_option_and_legacy_data_root(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("storage:\n  data_root: daten\n", encoding="utf-8")
    assert shared_config.storage_of(shared_config.load(cfg)).root == tmp_path / "daten", "aelterer Name"
    with shared_config.overrides([f"storage.root={tmp_path / 'zwei'}"]):
        assert shared_config.storage_of(shared_config.load(cfg)).root == tmp_path / "zwei"
    from chatexporter.cli.main import split_global_options
    _config, sets, rest = split_global_options(["--storage", str(tmp_path / "drei"), "status"])
    assert sets == [f"storage.root={(tmp_path / 'drei').resolve()}"] and rest == ["status"]


def test_legacy_folder_is_never_touched(tmp_path, capsys):
    root = _legacy(tmp_path / "data")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"storage:\n  data_root: {root}\n", encoding="utf-8")
    before = _snapshot(root)
    loaded = shared_config.load(cfg)
    assert loaded.scope is None and shared_config.storage_status(loaded)["format"] == st.FORMAT_LEGACY
    from chatexporter.cli import main as main_mod
    assert main_mod.main(["--config", str(cfg), "status"]) == 2
    assert main_mod.main(["--config", str(cfg), "update", "--source", "codex"]) == 2
    assert "storage migrate" in capsys.readouterr().err
    assert _snapshot(root) == before, "kein .storage, kein Log, keine Dateien"
    assert main_mod.main(["--config", str(cfg), "config", "get", "storage.root"]) == 0


# -- Sperre und Aufraeumen ------------------------------------------------------------------------

def test_lock_allows_one_writer(tmp_path):
    storage = st.Storage(tmp_path / "s")
    st.ensure(storage)
    with st.storage_lock(storage, "chatexporter update"):
        assert (storage.meta / "lock.json").is_file()
        with pytest.raises(st.StorageBusy, match="chatexporter update"):
            with st.storage_lock(storage, "chatexporter export"):
                pass
    assert not (storage.meta / "lock.json").exists()
    with st.storage_lock(storage, "danach wieder frei"):
        pass


def test_lock_is_held_while_a_writing_command_runs(tmp_path, monkeypatch, capsys):
    from chatexporter.cli import main as main_mod
    cfg = tmp_path / "config.yaml"
    cfg.write_text("", encoding="utf-8")
    storage = shared_config.storage_of(shared_config.load(cfg))
    with st.storage_lock(storage, "anderer Lauf"):
        assert main_mod.main(["--config", str(cfg), "index"]) == 2
        assert "belegt" in capsys.readouterr().err
        assert main_mod.main(["--config", str(cfg), "check"]) in (0, 1), "lesend: ohne Sperre"


def test_needs_lock():
    from chatexporter.cli.main import needs_lock
    assert needs_lock("update", []) and needs_lock("export", ["md"]) and not needs_lock("check", [])
    assert needs_lock("chatgpt", ["--config", "c.yaml", "update"])
    assert not needs_lock("chatgpt", ["--config", "c.yaml", "doctor"])
    assert not needs_lock("chatgpt", ["browser-setup", "--neu"])
    assert needs_lock("codex", ["--data-root", "x", "cleanup", "--dry-run"])
    assert not needs_lock("task", ["list"]) and not needs_lock("chatgpt", [])


def test_cleanup_staging_removes_only_empty_folders(tmp_path):
    storage = st.Storage(tmp_path / "s")
    st.ensure(storage)
    (storage.staging / "exports" / "leer").mkdir(parents=True)
    (storage.staging / "runs").mkdir(parents=True)
    (storage.staging / "runs" / "rest.tmp").write_text("x", encoding="utf-8")
    (storage.status_dir / ".staging").mkdir(parents=True)
    assert st.cleanup_staging(storage) == 3
    assert (storage.staging / "runs" / "rest.tmp").is_file() and not (storage.staging / "exports").exists()
    assert not (storage.status_dir / ".staging").exists() and storage.status_dir.is_dir()


def test_foreign_folder_is_never_turned_into_a_storage(tmp_path):
    root = tmp_path / "Dokumente"
    (root / "Urlaub").mkdir(parents=True)
    (root / "brief.docx").write_text("x", encoding="utf-8")
    before = _snapshot(root)
    with pytest.raises(st.StorageError, match="leeren oder neuen Ordner"):
        st.ensure(st.Storage(root))
    assert _snapshot(root) == before, "nichts angelegt"
    with pytest.raises(st.StorageError, match="keine Migration"):
        st.migrate(root)


def test_foreign_storage_option_is_refused_by_commands(tmp_path, capsys):
    from chatexporter.cli.main import main
    root = tmp_path / "Dokumente"
    root.mkdir()
    (root / "brief.docx").write_text("x", encoding="utf-8")
    assert main(["--storage", str(root), "status"]) == 2
    assert "nicht leer und kein Storage" in capsys.readouterr().err
    assert sorted(p.name for p in root.iterdir()) == ["brief.docx"]
