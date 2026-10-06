"""Bekannte Fehlerbilder aus dem Lauf 20260924T214820Z (Fehlerreferenz ERR-SYNC-CONN-CLOSED, ERR-SYNC-MEMORY)."""

from __future__ import annotations

import pytest

from chatexporter.providers.chatgpt.api.client import ApiClient, ApiTransportClosedError
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.sync.orchestrator import SyncOrchestrator


def test_driver_connection_loss_is_a_closed_transport():
    """„Connection closed while reading from the driver“: der Playwright-Treiber ist weg -> fatal, kein Weiterfeuern."""
    class Req:
        def get(self, url, **kwargs):
            raise Exception("APIRequestContext.get: Connection closed while reading from the driver")

    class Ctx:
        request = Req()
    with pytest.raises(ApiTransportClosedError):
        ApiClient(Ctx(), "t", base_url="https://chatgpt.com").request("GET", "/backend-api/conversation/x")


def _conversation(cid):
    return {"conversation_id": cid, "title": "T", "create_time": 1789700000.0, "update_time": 1, "current_node": "u",
            "mapping": {"root": {"id": "root", "message": None, "parent": None, "children": ["u"]},
                        "u": {"id": "u", "parent": "root", "children": [], "message": {
                            "id": "u", "author": {"role": "user"}, "content": {"content_type": "text", "parts": ["x"]},
                            "metadata": {}, "recipient": "all"}}}}


class Api:
    def __init__(self, memory_errors=0, ids=("c1",)):
        self.memory_errors, self.ids, self.calls = memory_errors, ids, []

    def iter_scope(self, archived, limit=100):
        if not archived:
            for i, cid in enumerate(self.ids):
                yield {"id": cid, "title": "T", "create_time": 1789700000.0, "update_time": i + 1,
                       "is_archived": False, "is_starred": False, "pinned_time": None}

    def get_conversation(self, cid):
        self.calls.append(cid)
        if self.memory_errors:
            self.memory_errors -= 1
            raise MemoryError()
        return _conversation(cid)

    def get_textdocs(self, cid):
        return []


def _run(tmp_path, api, messages):
    return SyncOrchestrator(conversation_api=api, file_api=None, repository=RawRepository(tmp_path / "raw"),
                            fetch_files=False, progress=messages.append).run(write_manifest=False)


def test_memory_error_while_fetching_is_retried_once_without_double_counting(tmp_path):
    messages: list[str] = []
    api = Api(memory_errors=1)
    stats = _run(tmp_path, api, messages)["stats"]
    assert api.calls == ["c1", "c1"]
    assert stats["fetched"] == 1 and stats["new"] == 1 and stats["fetch_failed"] == 0
    assert any("MemoryError" in m and "neuer Versuch" in m for m in messages)


def test_repeated_memory_error_stays_a_single_failure(tmp_path):
    api = Api(memory_errors=2, ids=("c1", "c2"))
    stats = _run(tmp_path, api, [])["stats"]
    assert stats["fetch_failed"] == 1 and stats["fetched"] == 1, "c1 scheitert zweimal, c2 laeuft weiter"
