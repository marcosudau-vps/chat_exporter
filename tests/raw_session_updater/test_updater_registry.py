"""Provider-Verzeichnis, Fragment-Regeln und End-to-End mit Codex."""

from __future__ import annotations

import json

from chatexporter.raw_session_updater import operations
from chatexporter.raw_session_updater.config import RawSessionUpdaterConfig
from chatexporter.raw_session_updater.fragments import normalize_failed_files, validate_fragment
from chatexporter.raw_session_updater.registry import CONTRACT_METHODS, KNOWN_SOURCES, call, provider_module


def test_all_providers_offer_the_contract():
    assert KNOWN_SOURCES == ("chatgpt", "opencode", "codex", "claude")
    for source in KNOWN_SOURCES:
        module = provider_module(source)
        for name in CONTRACT_METHODS:
            assert callable(getattr(module, name)), f"{source}.{name}"
        assert callable(getattr(module, "main")), f"{source}.main"
    try:
        provider_module("gibtesnicht")
    except ValueError:
        pass
    else:
        raise AssertionError("unbekannter Provider muss abgewiesen werden")


def test_call_rejects_non_contract_method():
    try:
        call("codex", "main", {})
    except ValueError:
        pass
    else:
        raise AssertionError("nur Vertragsfunktionen duerfen aufgerufen werden")


def test_fragment_validator_accepts_all_provider_shapes():
    chatgpt_entry = {
        "conversation_id": "c1", "source": "chatgpt", "kind": "conversation",
        "relative_path": "conversations/2026/09/30/c1.json",
        "json_complete": True, "files_complete": True,
        "acquisition_source": "api", "file_unavailable_count": 0,
    }
    opencode_entry = {"source": "opencode", "kind": "session", "session_id": "ses_abc",
                      "relative_path": "sessions/2026/09/30/ses_abc.json"}
    codex_file_entry = {"source": "codex", "kind": "artifact",
                        "relative_path": "sessions/2026/09/30/notes.md"}
    base = {"fragment_schema_version": 1, "generated_at": "2026-09-30T00:00:00Z",
            "candidates": 1, "indexed": 1, "coverage_percent": 100.0,
            "failed_files": [], "file_refs": {}}
    assert validate_fragment({**base, "source": "chatgpt", "entries": {"c1": chatgpt_entry}})
    assert validate_fragment({**base, "source": "opencode",
                              "entries": {"opencode:session:ses_abc": opencode_entry}})
    assert validate_fragment({**base, "source": "codex",
                              "entries": {"codex:artifact:2026/09/30/notes.md": codex_file_entry}})
    bad = {**base, "source": "opencode", "entries": {"fremd:session:x": opencode_entry}}
    try:
        validate_fragment(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("fremder Key-Prefix muss abgewiesen werden")


def test_updater_and_chatgpt_fragment_rules_are_identical():
    """Die Regeln existieren bewusst zweimal (Raw Session Updater und ChatGPT sind
    voneinander unabhaengig) -- sie duerfen aber nicht auseinanderlaufen."""
    from chatexporter.providers.chatgpt.storage import index as chatgpt_index
    samples = [
        {"source": "chatgpt", "failed_files": ["conversations/x.json"]},
        {"source": "codex", "failed_files": [{"file": "codex/a", "error": "e"}]},
    ]
    for sample in samples:
        assert (normalize_failed_files(sample, sample["source"])
                == chatgpt_index.normalize_failed_files(sample, sample["source"]))
    ok = {"fragment_schema_version": 1, "source": "fake", "candidates": 0, "indexed": 0,
          "coverage_percent": 100.0, "failed_files": [], "entries": {}, "file_refs": {}}
    for mutate in ({}, {"fragment_schema_version": 2}, {"entries": []}, {"coverage_percent": None},
                   {"entries": {"k": {"source": "fake", "kind": "s", "relative_path": "p"}}}):
        candidate = {**ok, **mutate}
        outcomes = []
        for validator in (validate_fragment, chatgpt_index.validate_fragment):
            try:
                validator(json.loads(json.dumps(candidate)))
                outcomes.append(True)
            except ValueError:
                outcomes.append(False)
        assert outcomes[0] == outcomes[1], mutate


def test_normalize_failed_files_accepts_strings_and_objects():
    fragment = {"source": "chatgpt", "failed_files": [
        "conversations/2026/09/30/c1.json",
        {"source": "opencode", "file": "opencode/sessions/x.json", "error": "kaputt"},
    ]}
    out = normalize_failed_files(fragment, "chatgpt")
    assert out[0] == {"source": "chatgpt", "file": "chatgpt/conversations/2026/09/30/c1.json",
                      "error": "unparseable"}
    assert out[1]["source"] == "opencode"


UUID = "019f37ed-1f7f-71f2-bb3c-461e7a4549d0"


def _codex_fixture(tmp_path):
    src = tmp_path / "codex-src" / "sessions" / "2026" / "09" / "30"
    src.mkdir(parents=True)
    (src / f"rollout-2026-09-30T10-00-00-{UUID}.jsonl").write_text(
        json.dumps({"type": "session_meta", "payload": {"id": UUID}}) + "\n"
        + json.dumps({"type": "message", "payload": {"text": "hi"}}) + "\n",
        encoding="utf-8")
    return tmp_path / "codex-src"


def test_codex_provider_end_to_end_synthetic(tmp_path):
    from chatexporter.providers import codex
    mapping = {"raw_root": tmp_path / "store", "runtime_root": tmp_path / "runtime",
               "source_root": _codex_fixture(tmp_path)}
    updated = codex.update(mapping)
    assert updated["ok"] is True and updated["stats"]["sessions_new"] == 1
    assert [(i["kind"], i["action"]) for i in updated["items"]["fetched"]] == [("session", "new")]
    assert codex.update(mapping)["items"]["fetched"] == [], "unveraendert = nicht aufgefuehrt"
    fragment = codex.recreate_index(mapping)
    validate_fragment(fragment)
    assert fragment["indexed"] == 1
    assert codex.check_storage_health(mapping)["ok"] is True
    assert codex.state_n_stats(mapping)["sessions_total"] == 1


def test_updater_update_with_codex_section(tmp_path):
    store = tmp_path / "store"
    (store / "codex").mkdir(parents=True)
    cfg = RawSessionUpdaterConfig(config_file=None, store_root=store, runtime_root=tmp_path / "runtime",
                        status_root=tmp_path / "runtime" / "status_registry",
                        sources=("codex",),
                        provider_sections={"codex": {"source_root": _codex_fixture(tmp_path)}})
    manifest, code = operations.update(cfg)
    assert code == 0
    assert manifest["schema_version"] == 4 and manifest["partial"] is False
    assert manifest["totals"]["sessions_fetched"] == 1
    section = manifest["sources"]["codex"]
    assert section["ok"] is True
    assert len(section["items"]["fetched"]) == 1, "Laufbericht nennt, was geholt wurde"
    assert section["started_at"] and section["finished_at"] and "duration_seconds" in section
    index, code = operations.rebuild_index(cfg)
    assert code == 0 and index["entries"] == 1


def test_provider_mapping_paths_cannot_be_overridden(tmp_path):
    cfg = RawSessionUpdaterConfig(config_file=tmp_path / "config.yaml", store_root=tmp_path / "raw",
                        runtime_root=tmp_path / "rt", status_root=tmp_path / "rt" / "st",
                        provider_sections={"codex": {"source_root": "/src", "raw_root": "/boese"}})
    mapping = cfg.provider_mapping("codex")
    assert mapping["source_root"] == "/src"
    assert mapping["raw_root"] == tmp_path / "raw"
    assert mapping["data_root"] == tmp_path
    assert mapping["config_file"] == tmp_path / "config.yaml"
    assert cfg.provider_mapping("claude")["source"] == "claude"
