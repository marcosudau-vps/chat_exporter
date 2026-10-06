"""Tests fuer die manuelle Ausnahmen-Liste (sync/exclusions.py)."""
from __future__ import annotations

from chatexporter.providers.chatgpt.config.loader import load_config
from chatexporter.providers.chatgpt.storage.envelope import files_complete_state
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.sync.exclusions import ManualExclusions
from chatexporter.providers.chatgpt.sync.models import SyncAction
from chatexporter.providers.chatgpt.sync.orchestrator import SyncOrchestrator
from chatexporter.providers.chatgpt.sync.planner import build_plan


def _summary(cid):
    return {"id": cid, "title": "T", "create_time": 1.0, "update_time": 2.0,
            "is_archived": False, "is_starred": None, "pinned_time": None}


def test_loader_parses_manual_exclusions(tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "sync:\n"
        "  manual_exclusions:\n"
        "    conversations:\n"
        "      - id: c1\n"
        "        reason: 'weil'\n"
        "    files:\n"
        "      - id: file_x\n",
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.sync.manual_exclusions.conversations == {"c1": "weil"}
    assert cfg.sync.manual_exclusions.files == {"file_x": ""}


def test_planner_marks_excluded_conversation():
    plan = build_plan({"c1": _summary("c1")}, {},
                      exclusions=ManualExclusions(conversations={"c1": "weil"}))
    assert plan[0].action == SyncAction.EXCLUDED
    assert plan[0].reason == "manually_excluded"


class PendingLibrary:
    def derived_state(self, ref):
        return "PENDING"


def test_excluded_file_counts_as_closed():
    refs = [{"id": "file_a"}]
    assert files_complete_state(refs, PendingLibrary()) is False
    assert files_complete_state(refs, PendingLibrary(), None,
                                ManualExclusions(files={"file_a": "weil"})) is True


class NeverFetchConversations:
    def iter_scope(self, *, archived, limit=100):
        if archived:
            return
        yield _summary("c1")

    def get_conversation(self, conversation_id):
        raise AssertionError("ausgeschlossene Conversation darf nicht abgerufen werden")

    def get_textdocs(self, conversation_id):
        return []


class NoFiles:
    def metadata(self, file_id): raise AssertionError("kein Dateizugriff erwartet")
    def download_ticket(self, file_id, *, gizmo_id=None): raise AssertionError("kein Dateizugriff erwartet")
    def download_bytes(self, url): raise AssertionError("kein Dateizugriff erwartet")


def test_orchestrator_skips_excluded_conversation(tmp_path):
    repo = RawRepository(tmp_path / "raw")
    result = SyncOrchestrator(
        conversation_api=NeverFetchConversations(), file_api=NoFiles(), repository=repo,
        exclusions=ManualExclusions(conversations={"c1": "weil"}),
    ).run()
    assert result["stats"]["fetched"] == 0
    assert result["stats"]["excluded_skipped"] == 1
    assert (result.get("exclusions") or {}).get("conversations") == 1
