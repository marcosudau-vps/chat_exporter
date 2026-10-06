"""Updater-Operationen mit echtem ChatGPT-Provider und Stub-Providern."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from chatexporter.raw_session_updater import operations, registry
from chatexporter.raw_session_updater.config import RawSessionUpdaterConfig
from chatexporter.raw_session_updater.manifest import build_run_manifest


def _updater_cfg(tmp_path, sources=("chatgpt",), sections=None):
    store = tmp_path / "raw_storage"
    runtime = tmp_path / ".storage"
    return RawSessionUpdaterConfig(config_file=None, store_root=store, runtime_root=runtime,
                         status_root=runtime / "status_registry", sources=tuple(sources),
                         provider_sections=dict(sections or {}))


def _chatgpt_store(tmp_path, simple_raw, summary):
    from chatexporter.providers.chatgpt.config.models import StorageConfig
    from chatexporter.providers.chatgpt.fetch.conversation_fetcher import FetchedConversation
    from chatexporter.providers.chatgpt.fetch.validator import validate_conversation_graph
    from chatexporter.providers.chatgpt.storage.envelope import build_envelope
    from chatexporter.providers.chatgpt.storage.layout import resolve_store_layout
    from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
    store = tmp_path / "raw_storage"
    (store / "chatgpt" / "conversations").mkdir(parents=True)
    layout = resolve_store_layout(StorageConfig(raw_root=store), "chatgpt")
    repo = RawRepository(layout.source_root, layout.status_root,
                         index_path=layout.index_path, runs_dir=layout.runs_dir,
                         staging_root=layout.staging_root, source="chatgpt")
    fetched = FetchedConversation(raw=simple_raw, textdocs=[], file_references=[],
                                  tool_references=[],
                                  validation=validate_conversation_graph(simple_raw),
                                  supplemental_errors=[])
    repo.commit(build_envelope(summary, fetched, library=repo.library))
    return repo, layout


def _stub_provider(monkeypatch, name, **functions):
    module = types.ModuleType(name)
    for fn_name, fn in functions.items():
        setattr(module, fn_name, fn)
    monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(registry.PROVIDER_MODULES, name.split("_")[0], name)
    return module


def test_run_manifest_v4_totals():
    manifest = build_run_manifest(
        {"chatgpt": {"ok": True, "stats": {"sessions_fetched": 1, "files_materialized": 2},
                     "errors": []},
         "codex": {"ok": False, "stats": {"sessions_fetched": 3}, "errors": [{"e": 1}]}},
        started="2026-09-29T00:00:00Z")
    assert manifest["schema_version"] == 4
    assert manifest["partial"] is True
    assert manifest["totals"]["sessions_fetched"] == 4
    assert manifest["totals"]["files_materialized"] == 2
    assert manifest["errors"] == [{"e": 1}]


def test_rebuild_index_with_real_chatgpt_provider(tmp_path, simple_raw, summary):
    _repo, layout = _chatgpt_store(tmp_path, simple_raw, summary)
    layout.index_path.unlink()
    cfg = _updater_cfg(tmp_path)
    assert cfg.index_path == layout.index_path, "Raw Session Updater und Provider teilen denselben Gesamtindex"
    report, code = operations.rebuild_index(cfg)
    assert code == 0 and report["committed"] is True
    assert report["entries"] == 1 and report["coverage_percent"] == 100.0
    stored = json.loads(layout.index_path.read_text(encoding="utf-8"))
    assert stored["conversations"]["c1"]["source"] == "chatgpt"
    assert cfg.file_index_path.exists()


def test_status_writes_overview(tmp_path, simple_raw, summary):
    _chatgpt_store(tmp_path, simple_raw, summary)
    report, code = operations.status(_updater_cfg(tmp_path))
    assert code == 0
    assert report["sources"]["chatgpt"]["sessions_total"] == 1
    overview = tmp_path / ".storage" / "OVERVIEW.md"
    assert "chatgpt" in overview.read_text(encoding="utf-8")


def test_cleanup_dry_run_and_real(tmp_path, simple_raw, summary):
    _repo, layout = _chatgpt_store(tmp_path, simple_raw, summary)
    residue = layout.source_root / "library" / "files" / "file_alt_rest"
    residue.mkdir(parents=True, exist_ok=True)
    cfg = _updater_cfg(tmp_path)
    dry, code = operations.cleanup(cfg, dry_run=True)
    assert code == 0 and dry["sources"]["chatgpt"]["empty_library_dirs_removed"] == 1
    assert residue.exists()
    real, code = operations.cleanup(cfg, dry_run=False)
    assert code == 0 and not residue.exists()


def test_check_health_flags_unknown_store_dir(tmp_path, simple_raw, summary):
    _chatgpt_store(tmp_path, simple_raw, summary)
    cfg = _updater_cfg(tmp_path)
    report, code = operations.check_health(cfg)
    assert code == 0 and report["sources"]["chatgpt"]["ok"] is True
    (cfg.store_root / "fremd").mkdir()
    report, code = operations.check_health(cfg)
    assert code == 1
    assert report["global_issues"][0]["code"] == "store.unexpected-source-dir"


def test_update_calls_only_active_sources_and_filters_options(tmp_path, monkeypatch):
    calls = []

    def fake_update(cfg, *, listing_mode=None):
        calls.append(("fake", cfg["source"], listing_mode, cfg["raw_root"]))
        return {"ok": True, "stats": {"sessions_total": 5, "sessions_fetched": 2}, "errors": []}

    def lean_update(cfg):
        calls.append(("lean", cfg["source"]))
        return {"ok": True, "stats": {"sessions_fetched": 1}, "errors": []}

    _stub_provider(monkeypatch, "fake_provider", update=fake_update)
    _stub_provider(monkeypatch, "lean_provider", update=lean_update)
    cfg = _updater_cfg(tmp_path, sources=("fake", "lean"))
    manifest, code = operations.update(cfg, listing_mode="recent", no_files=True)
    assert code == 0
    assert calls == [("fake", "fake", "recent", cfg.store_root), ("lean", "lean")]
    assert manifest["totals"]["sessions_fetched"] == 3
    assert set(manifest["sources"]) == {"fake", "lean"}
    run_path = Path(manifest["run_manifest"])
    assert run_path.parent == cfg.runs_dir and run_path.exists()


def test_update_marks_partial_when_provider_raises(tmp_path, monkeypatch):
    def broken_update(cfg):
        raise RuntimeError("kaputt")

    _stub_provider(monkeypatch, "broken_provider", update=broken_update)
    manifest, code = operations.update(_updater_cfg(tmp_path, sources=("broken",)))
    assert code == 2
    assert manifest["partial"] is True
    assert "kaputt" in manifest["errors"][0]["error"]


def test_interrupt_ends_only_current_source_and_report_is_written(tmp_path, monkeypatch):
    def interrupted(cfg):
        raise KeyboardInterrupt

    def fine(cfg):
        return {"ok": True, "stats": {"sessions_new": 1, "sessions_fetched": 1}, "errors": [],
                "items": {"fetched": [{"id": "s1", "kind": "session", "action": "new"}],
                          "failed": []}}

    _stub_provider(monkeypatch, "stop_provider", update=interrupted)
    _stub_provider(monkeypatch, "next_provider", update=fine)
    messages = []
    cfg = _updater_cfg(tmp_path, sources=("stop", "next"))
    manifest, code = operations.update(cfg, progress=messages.append)
    assert code == 2 and manifest["partial"] is True
    assert manifest["sources"]["stop"]["detail"]["abort_stage"] == "interrupted"
    assert manifest["sources"]["next"]["ok"] is True, "naechste Quelle lief weiter"
    assert Path(manifest["run_manifest"]).exists()
    assert any("--- Quelle next: ok" in m and "gespeichert 1" in m for m in messages)
    assert any("gespeichert: s1 (new)" in m for m in messages)
    assert any("--- Quelle stop: NICHT ok" in m for m in messages)


def test_update_rejects_unknown_source(tmp_path):
    with pytest.raises(ValueError):
        operations.update(_updater_cfg(tmp_path), sources=["gibtesnicht"])


def test_merge_two_sources_and_reject_duplicates(tmp_path, simple_raw, summary, monkeypatch):
    _repo, layout = _chatgpt_store(tmp_path, simple_raw, summary)
    fragment = {
        "fragment_schema_version": 1, "source": "fake",
        "generated_at": "2026-09-30T00:00:00Z", "candidates": 1, "indexed": 1,
        "coverage_percent": 100.0, "failed_files": [],
        "entries": {"fake:session:s1": {"source": "fake", "kind": "session",
                                        "relative_path": "sessions/s1.json", "session_id": "s1"}},
        "file_refs": {},
    }
    _stub_provider(monkeypatch, "fake_provider", recreate_index=lambda cfg: json.loads(json.dumps(fragment)))
    cfg = _updater_cfg(tmp_path, sources=("chatgpt", "fake"))
    report, code = operations.rebuild_index(cfg)
    assert code == 0 and report["entries"] == 2
    stored = json.loads(layout.index_path.read_text(encoding="utf-8"))
    assert set(stored["conversations"]) == {"c1", "fake:session:s1"}
    assert set(stored["coverage"]["sources"]) == {"chatgpt", "fake"}

    before = layout.index_path.read_text(encoding="utf-8")
    duplicate = {**fragment, "entries": {"c1": {"source": "fake", "kind": "session",
                                                 "relative_path": "x.json", "session_id": "c1"}}}
    _stub_provider(monkeypatch, "fake_provider", recreate_index=lambda cfg: json.loads(json.dumps(duplicate)))
    report, code = operations.rebuild_index(cfg)
    assert code == 2 and report["committed"] is False
    assert layout.index_path.read_text(encoding="utf-8") == before
