"""Rate-Limit als regulaeres Ereignis statt als Fehler.

Grundlage: Forschungsakte 2026-09-21. Alle 37 real gemessenen 429-Antworten
trugen ausnahmslos den Body {"detail": "Too many requests"}. Die Meldung
"API error budget exhausted" stammt dagegen aus dem ChatExporter selbst und
ist KEIN Serversignal.
"""
from __future__ import annotations

import pytest

from chatexporter.providers.chatgpt.api.client import ApiError, RateLimitError
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.sync.orchestrator import SyncOrchestrator


def _summary(cid: str) -> dict:
    return {"id": cid, "title": f"T {cid}", "create_time": 1.0, "update_time": 2.0,
            "is_archived": False, "is_starred": None, "pinned_time": None}


def _conversation(cid: str) -> dict:
    return {"conversation_id": cid, "current_node": "n1",
            "mapping": {"n1": {"id": "n1", "message": {
                "id": "m1", "author": {"role": "user"},
                "content": {"content_type": "text", "parts": ["hi"]},
                "create_time": 1.0}, "parent": None, "children": []}}}


class RateLimitedApi:
    """Liefert nach `ok_count` erfolgreichen Abrufen dauerhaft HTTP 429."""

    def __init__(self, total: int, ok_count: int, detail: str = "Too many requests"):
        self.total = total
        self.ok_count = ok_count
        self.detail = detail
        self.calls = 0

    def iter_scope(self, *, archived: bool, limit: int = 100):
        if archived:
            return
        for i in range(self.total):
            yield _summary(f"c{i}")

    def get_conversation(self, conversation_id: str):
        self.calls += 1
        if self.calls > self.ok_count:
            payload = {"detail": self.detail}
            raise RateLimitError(
                f"HTTP 429 for /backend-api/conversation/{conversation_id}",
                status=429, endpoint="/backend-api/conversation/<id>", payload=payload)
        return _conversation(conversation_id)

    def get_textdocs(self, conversation_id: str):
        return []


class NoFileApi:
    def metadata(self, file_id): raise AssertionError("keine Dateien erwartet")
    def download_ticket(self, file_id, *, gizmo_id=None): raise AssertionError("keine Dateien erwartet")
    def download_bytes(self, url): raise AssertionError("keine Dateien erwartet")


def test_rate_limit_matcher_requires_status_and_detail():
    assert RateLimitError.matches(429, {"detail": "Too many requests"}) is True
    assert RateLimitError.matches(429, {"detail": "TOO MANY REQUESTS"}) is True
    # Ein 429 mit anderer Ursache darf NICHT als Rate-Limit gelten.
    assert RateLimitError.matches(429, {"detail": "Account suspended"}) is False
    assert RateLimitError.matches(429, None) is False
    assert RateLimitError.matches(500, {"detail": "Too many requests"}) is False


def test_rate_limit_does_not_consume_error_budget(tmp_path):
    """Kernforderung: das Limit ist kein Fehler und beendet den Lauf regulaer."""
    api = RateLimitedApi(total=10, ok_count=3)
    repo = RawRepository(tmp_path / "raw")
    messages = []
    result = SyncOrchestrator(
        conversation_api=api, file_api=NoFileApi(), repository=repo, fetch_files=False, max_errors_per_run=5, rate_limit_wait_minutes=0,
        progress=messages.append,
    ).run()

    assert result["aborted"] is False, "Rate-Limit darf keinen Abbruch ausloesen"
    assert result["error_budget"]["api_errors_seen"] == 0, "Rate-Limit darf kein Budget kosten"
    assert result["stats"]["fetched"] == 3
    assert result["rate_limit"]["hits"] == 1
    assert any("[LIMIT ERREICHT]" in m for m in messages)
    assert any("[LIMIT WIEDER VOLL]" in m for m in messages)
    assert result["rate_limit"]["events"][0]["conversations_total"] == 10


def test_non_matching_429_is_treated_as_normal_error(tmp_path):
    """Ein 429 mit abweichendem detail kann andere Gruende haben."""
    api = RateLimitedApi(total=10, ok_count=1, detail="Account suspended")
    repo = RawRepository(tmp_path / "raw")
    result = SyncOrchestrator(
        conversation_api=api, file_api=NoFileApi(), repository=repo, fetch_files=False, max_errors_per_run=3, rate_limit_wait_minutes=0,
    ).run()
    assert result["aborted"] is True
    assert "error budget exhausted" in (result["abort_reason"] or "")
    assert result["rate_limit"]["hits"] == 0


def test_wait_cycle_resumes_after_rate_limit(tmp_path):
    """Bei rate_limit_wait_minutes > 0 wird gewartet und weitergemacht."""
    class RecoveringApi(RateLimitedApi):
        def get_conversation(self, conversation_id):
            self.calls += 1
            # Erste zwei ok, dann ein Limit, danach wieder alles ok.
            if self.calls == 3:
                raise RateLimitError("HTTP 429", status=429, endpoint="/e",
                                      payload={"detail": "Too many requests"})
            return _conversation(conversation_id)

    api = RecoveringApi(total=4, ok_count=99)
    repo = RawRepository(tmp_path / "raw")
    slept: list[float] = []
    result = SyncOrchestrator(
        conversation_api=api, file_api=NoFileApi(), repository=repo, fetch_files=False, rate_limit_wait_minutes=15, max_rate_limit_cycles=5,
        sleep=slept.append,
    ).run()

    assert slept == [15 * 60], "Es muss genau einmal 15 Minuten gewartet worden sein"
    assert result["aborted"] is False
    assert result["stats"]["fetched"] == 4, "nach der Wartezeit muessen alle durchlaufen"
    assert result["rate_limit"]["cycles"] >= 2


def test_max_cycles_stops_endless_waiting(tmp_path):
    api = RateLimitedApi(total=10, ok_count=1)
    repo = RawRepository(tmp_path / "raw")
    slept: list[float] = []
    result = SyncOrchestrator(
        conversation_api=api, file_api=NoFileApi(), repository=repo, fetch_files=False, rate_limit_wait_minutes=5, max_rate_limit_cycles=2,
        sleep=slept.append,
    ).run()
    assert len(slept) <= 2
    assert result["aborted"] is False


def test_rate_limit_stop_is_reported_for_continuation(tmp_path):
    """Grundlage der automatischen Fortsetzung: Stopp, offene Menge, Zeitpunkt."""
    api = RateLimitedApi(total=10, ok_count=3)
    result = SyncOrchestrator(
        conversation_api=api, file_api=NoFileApi(), repository=RawRepository(tmp_path / "raw"),
        fetch_files=False, rate_limit_wait_minutes=0,
    ).run()
    limit = result["rate_limit"]
    assert limit["stopped"] is True and limit["stage"] == "fetch"
    assert limit["open_conversations"] == 7
    assert limit["estimated_full_at"] == limit["events"][-1]["estimated_full_at"]


def test_complete_run_is_not_a_rate_limit_stop(tmp_path):
    api = RateLimitedApi(total=3, ok_count=99)
    result = SyncOrchestrator(
        conversation_api=api, file_api=NoFileApi(), repository=RawRepository(tmp_path / "raw"),
        fetch_files=False, rate_limit_wait_minutes=0,
    ).run()
    assert result["rate_limit"]["stopped"] is False and result["rate_limit"]["open_conversations"] is None


def test_contract_result_carries_the_stop_fields(tmp_path):
    from chatexporter.providers.chatgpt.contract import contract_result
    api = RateLimitedApi(total=5, ok_count=2)
    report = SyncOrchestrator(
        conversation_api=api, file_api=NoFileApi(), repository=RawRepository(tmp_path / "raw"),
        fetch_files=False, rate_limit_wait_minutes=0,
    ).run()
    limit = contract_result(report)["detail"]["rate_limit"]
    assert limit["stopped"] is True and limit["open_conversations"] == 3 and limit["estimated_full_at"]
