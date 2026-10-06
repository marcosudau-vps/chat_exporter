"""ChatGPT-Provider: Ablage-Layout, Migration, Fragment und Vertragsfunktionen."""

from __future__ import annotations

import json

from chatexporter.providers.chatgpt import contract
from chatexporter.providers.chatgpt.config.models import AppConfig, StorageConfig
from chatexporter.providers.chatgpt.storage.index import validate_fragment
from chatexporter.providers.chatgpt.storage.layout import resolve_store_layout
from chatexporter.providers.chatgpt.storage.migrate_layout import migrate_layout, plan_layout_migration
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository, _date_bucket


def test_date_bucket_day_precision():
    assert _date_bucket(1789700000.0).count("/") == 2
    assert _date_bucket(1789700000.0).startswith("2026/")
    assert _date_bucket(None) == "unknown"
    assert _date_bucket("kein-datum") == "unknown"


def test_layout_defaults_to_legacy(tmp_path):
    cfg = StorageConfig(raw_root=tmp_path / "raw_storage")
    layout = resolve_store_layout(cfg, "chatgpt")
    assert layout.legacy is False
    assert layout.source_root == tmp_path / "raw_storage" / "chatgpt"
    (tmp_path / "raw_storage" / "conversations").mkdir(parents=True)
    legacy = resolve_store_layout(cfg, "chatgpt")
    assert legacy.legacy is True
    assert legacy.source_root == tmp_path / "raw_storage"
    assert legacy.runs_dir == tmp_path / "raw_storage" / "runs"
    assert legacy.index_path == tmp_path / "raw_storage" / "storage_index.json"


def test_layout_detects_namespaced_store(tmp_path):
    (tmp_path / "raw_storage" / "chatgpt" / "conversations").mkdir(parents=True)
    cfg = StorageConfig(raw_root=tmp_path / "raw_storage")
    layout = resolve_store_layout(cfg, "chatgpt")
    assert layout.legacy is False
    assert layout.source_root == tmp_path / "raw_storage" / "chatgpt"
    assert layout.runs_dir == tmp_path / ".storage" / "runs"
    assert layout.index_path == tmp_path / ".storage" / "status_registry" / "storage_index.json"
    assert layout.quarantine_path == tmp_path / ".storage" / "status_registry" / "quarantine.json"


def _legacy_store(tmp_path):
    store = tmp_path / "raw_storage"
    conv = store / "conversations" / "2026-09"
    conv.mkdir(parents=True)
    env = {
        "storage_schema_version": 1, "provider": "chatgpt", "conversation_id": "c1",
        "remote_summary": {"id": "c1", "title": "T", "create_time": 1789700000.0,
                           "update_time": 1789700100.0},
        "acquisition": {"complete": True, "json_complete": True, "files_complete": True,
                        "source": "api"},
        "raw": {"conversation_id": "c1", "title": "T", "current_node": "a1",
                "mapping": {"a1": {"id": "a1", "message": None, "parent": None, "children": []}}},
        "textdocs": [], "file_references": [],
        "integrity": {"raw_payload_sha256": "x"},
    }
    (conv / "c1.json").write_text(json.dumps(env), encoding="utf-8")
    (store / "library" / "files").mkdir(parents=True)
    (store / "storage_index.json").write_text(json.dumps({"schema_version": 1, "conversations": {}}),
                                              encoding="utf-8")
    (store / "runs").mkdir(parents=True)
    (store / "runs" / "sync_old.json").write_text("{}", encoding="utf-8")
    return store


def test_migrate_layout_dry_run_moves_nothing(tmp_path):
    store = _legacy_store(tmp_path)
    report = migrate_layout(store, dry_run=True)
    assert report["migrated"] is False
    assert report["moved_conversations"] == 1
    assert (store / "conversations" / "2026-09" / "c1.json").exists()


def test_migrate_layout_moves_to_namespace_and_runtime(tmp_path):
    store = _legacy_store(tmp_path)
    report = migrate_layout(store)
    assert report["migrated"] is True
    moved = list((store / "chatgpt" / "conversations").rglob("c1.json"))
    assert len(moved) == 1
    assert len(moved[0].relative_to(store / "chatgpt" / "conversations").parts) == 4
    assert not (store / "conversations").exists()
    assert (tmp_path / ".storage" / "runs" / "sync_old.json").exists()
    again = migrate_layout(store)
    assert again["migrated"] is False
    assert again["reason"] == "already-migrated"


def test_plan_layout_migration(tmp_path):
    store = _legacy_store(tmp_path)
    plan = plan_layout_migration(store)
    assert plan["already_migrated"] is False
    assert plan["legacy_conversations"] == 1


def _namespaced_repo(tmp_path):
    store = tmp_path / "raw_storage"
    (store / "chatgpt" / "conversations").mkdir(parents=True)
    cfg = AppConfig()
    cfg.storage = StorageConfig(raw_root=store)
    layout = resolve_store_layout(cfg.storage, "chatgpt")
    repo = RawRepository(layout.source_root, layout.status_root,
                         index_path=layout.index_path, runs_dir=layout.runs_dir,
                         staging_root=layout.staging_root, source="chatgpt")
    return repo, layout, cfg


def _commit_one(repo, simple_raw, summary):
    from chatexporter.providers.chatgpt.fetch.conversation_fetcher import FetchedConversation
    from chatexporter.providers.chatgpt.fetch.validator import validate_conversation_graph
    from chatexporter.providers.chatgpt.storage.envelope import build_envelope
    fetched = FetchedConversation(raw=simple_raw, textdocs=[], file_references=[],
                                  tool_references=[],
                                  validation=validate_conversation_graph(simple_raw),
                                  supplemental_errors=[])
    repo.commit(build_envelope(summary, fetched, library=repo.library))


def test_fragment_is_valid_and_bad_fragment_rejected(tmp_path, simple_raw, summary):
    repo, _layout, _cfg = _namespaced_repo(tmp_path)
    _commit_one(repo, simple_raw, summary)
    fragment = repo.index.build_fragment()
    assert fragment["source"] == "chatgpt"
    assert fragment["candidates"] == 1
    assert fragment["indexed"] == 1
    assert fragment["coverage_percent"] == 100.0
    validate_fragment(fragment)
    bad = dict(fragment)
    bad["entries"] = {"c1": {"unvollstaendig": True}}
    try:
        validate_fragment(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("ungueltiges Fragment muss abgewiesen werden")


def test_contract_accepts_updater_mapping(tmp_path, simple_raw, summary):
    """Der Raw Session Updater uebergibt nur ein Mapping; der Provider baut seine Config selbst."""
    repo, layout, _cfg = _namespaced_repo(tmp_path)
    _commit_one(repo, simple_raw, summary)
    mapping = {"source": "chatgpt", "config_file": None,
               "raw_root": layout.store_root, "runtime_root": layout.runtime_root,
               "status_root": layout.status_root}
    fragment = contract.recreate_index(mapping)
    assert fragment["indexed"] == 1
    snap = contract.state_n_stats(mapping)
    assert snap["sessions_total"] == 1
    assert contract.check_storage_health(mapping)["ok"] is True
    assert contract.cleanup_storage(mapping, dry_run=True)["dry_run"] is True


def test_health_check_on_fresh_store_creates_no_stray_folders(tmp_path):
    """Leerer Bestand = Provider-Layout (wie resolve_store_layout), nicht Legacy:
    frueher legte die Pruefung dabei `raw_storage/library/` an."""
    store = tmp_path / "raw_storage"
    mapping = {"config_file": None, "raw_root": store, "runtime_root": tmp_path / ".storage",
               "status_root": tmp_path / ".storage" / "status_registry"}
    report = contract.check_storage_health(mapping)
    assert report["ok"] is True
    assert not (store / "library").exists()
    assert not (store / "conversations").exists()


def test_contract_result_maps_run_report():
    run_report = {"aborted": False, "started_at": "2026-09-29T00:00:00Z",
                  "listing": {"mode": "recent", "pages": 1},
                  "stats": {"remote_total": 10, "new": 1, "changed": 0, "unchanged": 9,
                            "missing_remote": 0, "fetched": 1, "fetch_failed": 0,
                            "files_materialized": 2, "files_cached": 1, "files_failed": 0,
                            "files_unavailable": 0, "errors": []}}
    result = contract.contract_result(run_report)
    assert result["ok"] is True
    assert result["exit_code"] == 0
    assert result["stats"]["sessions_total"] == 10
    assert result["stats"]["sessions_fetched"] == 1
    assert result["stats"]["files_materialized"] == 2
    assert result["detail"]["listing"]["mode"] == "recent"
    aborted = contract.contract_result({**run_report, "aborted": True})
    assert aborted["ok"] is False and aborted["exit_code"] == 2


def test_verify_finds_runtime_staging_leftover_in_new_layout(tmp_path, simple_raw, summary):
    from chatexporter.providers.chatgpt.storage.integrity import verify_store
    repo, layout, _cfg = _namespaced_repo(tmp_path)
    _commit_one(repo, simple_raw, summary)
    leftover = layout.staging_root / "leftover.tmp"
    leftover.parent.mkdir(parents=True, exist_ok=True)
    leftover.write_text("x", encoding="utf-8")
    report = verify_store(layout.store_root, layout.status_root, source="chatgpt",
                          runtime_root=layout.runtime_root, index_path=layout.index_path)
    assert any(i.code == "store.staging-leftover" for i in report.warnings)
    leftover.unlink()
    clean = verify_store(layout.store_root, layout.status_root, source="chatgpt",
                         runtime_root=layout.runtime_root, index_path=layout.index_path)
    assert clean.ok


def test_standalone_run_manifest_is_schema_4(tmp_path):
    from chatexporter.providers.chatgpt.operations import write_run_manifest
    _repo, layout, _cfg = _namespaced_repo(tmp_path)
    result = contract.contract_result({"aborted": False, "stats": {"fetched": 2}})
    manifest, path = write_run_manifest(layout, result, started="2026-09-30T00:00:00Z")
    assert path.parent == layout.runs_dir and path.name.startswith("sync_")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["schema_version"] == 4
    assert stored["totals"]["sessions_fetched"] == 2
    assert set(stored["sources"]) == {"chatgpt"}
