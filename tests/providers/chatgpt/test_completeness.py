"""Getrennte Vollstaendigkeit fuer Graph und Dateien.

Beschluss: "fertig" darf nicht behauptet werden, solange Dateien fehlen --
Dateien gehoeren zur Conversation und enthalten oft den eigentlichen Prompt.
Gleichzeitig soll nur nachgeholt werden, was tatsaechlich fehlt.
"""
from __future__ import annotations

from chatexporter.providers.chatgpt.config.models import QuarantineConfig
from chatexporter.providers.chatgpt.storage.envelope import files_complete_state
from chatexporter.providers.chatgpt.storage.library import LibraryStore
from chatexporter.providers.chatgpt.storage.quarantine import QuarantineStore
from chatexporter.providers.chatgpt.sync.models import SyncAction
from chatexporter.providers.chatgpt.sync.planner import build_plan


class _Library:
    def __init__(self, materialized):
        self._m = set(materialized)

    def derived_state(self, ref):
        return "MATERIALIZED" if ref.get("id") in self._m else "PENDING"


def test_conversation_without_files_is_immediately_complete():
    assert files_complete_state([], _Library([])) is True
    assert files_complete_state(None, _Library([])) is True


def test_pending_file_keeps_conversation_incomplete():
    refs = [{"id": "file_a"}, {"id": "file_b"}]
    assert files_complete_state(refs, _Library(["file_a"])) is False
    assert files_complete_state(refs, _Library(["file_a", "file_b"])) is True


def test_quarantined_file_does_not_block_completeness(tmp_path):
    """Sonst haelt eine einzelne dauerhaft tote Datei die Conversation
    fuer immer unfertig -- genau dafuer gibt es die Quarantaene."""
    store = QuarantineStore(tmp_path, QuarantineConfig(enabled=True))
    store.data["files"]["file_b"] = {"quarantined": True, "review_after": None}

    refs = [{"id": "file_a"}, {"id": "file_b"}]
    assert files_complete_state(refs, _Library(["file_a"]), store) is True


def _local(**kw):
    base = {"title": "T", "remote_updated_at": 2.0, "is_archived": False,
            "is_starred": None, "pinned_time": None, "raw_integrity_ok": True,
            "json_complete": True, "files_complete": True, "fetch_complete": True}
    base.update(kw)
    return base


def _remote():
    return {"c1": {"id": "c1", "title": "T", "create_time": 1.0, "update_time": 2.0,
                    "is_archived": False, "is_starred": None, "pinned_time": None}}


def test_missing_files_trigger_files_only_not_full_fetch():
    """Der teure Conversation-Abruf waere bei knappem Budget Verschwendung."""
    plan = build_plan(_remote(), {"c1": _local(files_complete=False, fetch_complete=False)})
    assert plan[0].action == SyncAction.FETCH_FILES_ONLY
    assert plan[0].reason == "files_missing"


def test_incomplete_json_triggers_full_fetch():
    plan = build_plan(_remote(), {"c1": _local(json_complete=False, fetch_complete=False)})
    assert plan[0].action == SyncAction.FETCH_FULL


def test_fully_complete_record_is_skipped():
    plan = build_plan(_remote(), {"c1": _local()})
    assert plan[0].action == SyncAction.SKIP


def test_new_conversations_are_planned_before_incomplete_ones():
    """Beschluss Frage 4: zuerst echte Luecken schliessen."""
    remote = {
        "c_incomplete": {"id": "c_incomplete", "title": "T", "create_time": 1.0,
                          "update_time": 2.0, "is_archived": False,
                          "is_starred": None, "pinned_time": None},
        "c_new": {"id": "c_new", "title": "T", "create_time": 1.0, "update_time": 2.0,
                   "is_archived": False, "is_starred": None, "pinned_time": None},
    }
    local = {"c_incomplete": _local(json_complete=False, fetch_complete=False)}
    plan = build_plan(remote, local)
    assert [p.conversation_id for p in plan] == ["c_new", "c_incomplete"]


def test_quarantined_conversation_is_not_planned(tmp_path):
    store = QuarantineStore(tmp_path, QuarantineConfig(enabled=True))
    store.data["conversations"]["c1"] = {"quarantined": True, "review_after": None}
    plan = build_plan(_remote(), {}, store)
    assert plan[0].action == SyncAction.QUARANTINED


def test_library_counts_both_buckets(tmp_path):
    """is_materialized muss Dateien in beiden Bereichen finden."""
    store = LibraryStore(tmp_path)
    audio_dir = store.audio_root / "file_a1"
    audio_dir.mkdir(parents=True)
    (audio_dir / "content.wav").write_bytes(b"RIFF")
    (audio_dir / "metadata.json").write_text('{"size": 4}', encoding="utf-8")
    assert store.is_materialized("file_a1") is True
    assert store.derived_state({"id": "file_a1", "kind": "audio_asset_pointer"}) == "MATERIALIZED"
