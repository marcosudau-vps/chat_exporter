"""chatexporter storage show/migrate: Umstellung eines Datenordners im alten Format."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

import chatexporter.config as shared_config
from chatexporter.cli import storage_cli
from chatexporter.config import storage as st


def _legacy_tree(root: Path) -> dict[str, str]:
    files = {
        "runtime/runs/sync_1.json": "{}",
        "runtime/status_registry/storage_index.json": '{"conversations": {}}',
        "runtime/.staging/index/rest.tmp": "rest",
        "runtime/logs/commands_x.jsonl": "{}\n",
        "runtime/OVERVIEW.md": "# alt",
        "raw_storage/chatgpt/conversations/2024/01/01/c1.json": '{"id": "c1"}',
        "exports/json/chatgpt/2024-01/c1.json": "{}",
        "notiz.txt": "fremde Datei",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / "runtime" / ".staging" / "runs").mkdir(parents=True)
    (root / "exports" / ".staging").mkdir(parents=True)
    return {rel: hashlib.sha256(text.encode()).hexdigest() for rel, text in files.items()}


def _run(tmp_path, *argv, answers=(), config_text=None):
    cfg = tmp_path / "config.yaml"
    if config_text is not None or not cfg.exists():
        cfg.write_text(config_text or f"storage:\n  data_root: {tmp_path / 'data'}\n", encoding="utf-8")
    lines: list[str] = []
    feed = iter(answers)
    code = storage_cli.main(list(argv), cfg, say=lines.append, ask=lambda _p: next(feed))
    return code, "\n".join(lines)


def test_migrate_dry_run_then_real(tmp_path):
    root = tmp_path / "data"
    hashes = _legacy_tree(root)
    before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
    code, out = _run(tmp_path, "migrate", "--dry-run")
    assert code == 0 and "Probelauf" in out and "umbenennen" in out
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*")) == before, "Probelauf aendert nichts"
    code, out = _run(tmp_path, "migrate", answers=("n",))
    assert code == 1 and (root / "runtime").is_dir()
    code, out = _run(tmp_path, "migrate", answers=("j",))
    assert code == 0 and "jetzt Storage-Schema 2" in out
    assert st.detect(root)[0] == st.FORMAT_CURRENT == "storage-schema-2" and not (root / "runtime").exists()
    meta = root / ".storage"
    assert (meta / "runs" / "sync_1.json").is_file() and (meta / "logs" / "commands_x.jsonl").is_file()
    assert (meta / "status_registry" / "storage_index.json").is_file() and (meta / "OVERVIEW.md").is_file()
    assert (meta / "staging" / "index" / "rest.tmp").read_text(encoding="utf-8") == "rest", "Reste eingeordnet"
    assert not (meta / ".staging").exists() and not (root / "exports" / ".staging").exists()
    assert not (meta / "staging" / "runs").exists(), "leere Ordner entfernt"
    raw = root / "raw_storage" / "chatgpt" / "conversations" / "2024" / "01" / "01" / "c1.json"
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == hashes["raw_storage/chatgpt/conversations/2024/01/01/c1.json"]
    assert (root / "notiz.txt").is_file()
    assert yaml.safe_load((meta / "storage.yaml").read_text(encoding="utf-8"))["storage_schema"] == 2
    code, out = _run(tmp_path, "migrate")
    assert code == 0 and "nichts zu tun" in out
    code, out = _run(tmp_path, "show")
    assert code == 0 and "storage-schema-2" in out


def test_migrate_refuses_unclear_folders(tmp_path):
    root = tmp_path / "data"
    (root / "raw_storage").mkdir(parents=True)
    code, out = _run(tmp_path, "migrate", "--yes")
    assert code == 1 and "nicht eindeutig" in out and not (root / ".storage").exists()


def test_settings_pointing_into_runtime_must_be_fixed(tmp_path):
    root = tmp_path / "data"
    _legacy_tree(root)
    text = f"storage:\n  data_root: {root}\nlogging:\n  dir: data/runtime/logs\n"
    code, out = _run(tmp_path, "migrate", "--yes", config_text=text)
    assert code == 1 and "logging.dir" in out and "--fix-config" in out and (root / "runtime").is_dir()
    code, out = _run(tmp_path, "migrate", "--yes", "--fix-config")
    assert code == 0 and "Zurueckgesetzt in der globalen config.yaml: logging.dir" in out
    lines = (tmp_path / "config.yaml").read_text(encoding="utf-8").splitlines()
    assert "  dir: data/runtime/logs" not in lines, "nur noch auskommentiert"
    loaded = shared_config.load(tmp_path / "config.yaml")
    assert loaded.get("logging.dir") is None and st.detect(root)[0] == st.FORMAT_CURRENT


def test_migrate_through_the_main_command(tmp_path, capsys):
    from chatexporter.cli import main as main_mod
    root = tmp_path / "data"
    _legacy_tree(root)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"storage:\n  data_root: {root}\n", encoding="utf-8")
    assert main_mod.main(["--config", str(cfg), "status"]) == 2, "altes Format gesperrt"
    assert main_mod.main(["--config", str(cfg), "storage", "migrate", "--yes"]) == 0
    assert main_mod.main(["--config", str(cfg), "status"]) == 0
    assert (root / ".storage" / "state.yaml").is_file()


def _interrupt_after_rename(root: Path) -> None:
    """Abbruch der Umstellung nach Schritt 1 nachstellen: runtime/ ist schon .storage/, Marker fehlt."""
    import os
    os.replace(root / "runtime", root / ".storage")


def test_interrupted_migration_is_recognized_and_refused_by_commands(tmp_path):
    root = tmp_path / "data"
    _legacy_tree(root)
    _interrupt_after_rename(root)
    fmt, reason = st.detect(root)
    assert fmt == st.FORMAT_INTERRUPTED and "Umstellung abgebrochen" in reason
    import pytest
    with pytest.raises(st.StorageError, match="Fortsetzen mit: chatexporter storage migrate"):
        st.ensure(st.Storage(root))
    assert not (root / ".storage" / "storage.yaml").exists(), "ensure veraendert nichts"


def test_interrupted_migration_can_be_resumed(tmp_path):
    root = tmp_path / "data"
    hashes = _legacy_tree(root)
    _interrupt_after_rename(root)
    code, out = _run(tmp_path, "migrate", "--dry-run")
    assert code == 0 and "fortgesetzt" in out and "fortsetzen:" in out
    assert st.detect(root)[0] == st.FORMAT_INTERRUPTED, "Probelauf veraendert nichts"
    code, out = _run(tmp_path, "migrate", "--yes")
    assert code == 0, out
    assert st.detect(root)[0] == st.FORMAT_CURRENT
    assert (root / ".storage" / "staging" / "index" / "rest.tmp").read_text(encoding="utf-8") == "rest"
    assert not (root / ".storage" / ".staging").exists() and not (root / "exports" / ".staging").exists()
    import hashlib
    for rel, digest in hashes.items():
        target = root / rel.replace("runtime/.staging/", ".storage/staging/").replace("runtime/", ".storage/")
        assert hashlib.sha256(target.read_text(encoding="utf-8").encode()).hexdigest() == digest, rel
    code, out = _run(tmp_path, "migrate", "--yes")
    assert code == 0 and "nichts zu tun" in out, "zweiter Aufruf: bereits fertig"
