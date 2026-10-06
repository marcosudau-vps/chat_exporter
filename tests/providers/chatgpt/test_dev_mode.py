"""Entwicklungsmodus: nur die ausschlaggebenden Werte aendern sich, die Logik nicht."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from chatexporter.config.dev import DEV
from chatexporter.providers.chatgpt.api.client import RateLimitError
from chatexporter.providers.chatgpt.api.conversations import ConversationApi
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.sync.orchestrator import SyncOrchestrator


def _conversation(cid: str) -> dict:
    return {"conversation_id": cid, "title": cid, "current_node": "n1", "update_time": 2.0,
            "mapping": {"n1": {"id": "n1", "parent": None, "children": [], "message": {
                "id": "m1", "author": {"role": "user"}, "content": {"content_type": "text", "parts": ["hi"]},
                "create_time": 1.0}}}}


class FakeClient:
    """Server mit ``total`` aktiven Konversationen; zaehlt die Anfragen."""

    def __init__(self, total: int):
        self.total = total
        self.listing_calls = 0
        self.detail_calls = 0

    def get_json(self, path, params=None):
        if path == "/backend-api/conversations":
            self.listing_calls += 1
            if params.get("is_archived"):
                return {"items": []}
            offset, limit = params["offset"], params["limit"]
            ids = range(offset, min(offset + limit, self.total))
            return {"items": [{"id": f"c{i:03d}", "title": f"c{i:03d}", "create_time": 1.0,
                               "update_time": 2.0, "is_archived": False} for i in ids]}
        if path.endswith("/textdocs"):
            return []
        self.detail_calls += 1
        return _conversation(path.rsplit("/", 1)[-1])


def test_listing_page_cap():
    api = ConversationApi(FakeClient(total=50))
    assert len(list(api.iter_scope(archived=False, limit=5))) == 50
    api.max_pages = 3
    assert len(list(api.iter_scope(archived=False, limit=5))) == 15


def test_simulated_rate_limit_looks_like_the_server():
    api = ConversationApi(FakeClient(total=10))
    api.fetch_budget = 2
    api.get_conversation("c000")
    api.get_conversation("c001")
    with pytest.raises(RateLimitError) as exc:
        api.get_conversation("c002")
    assert RateLimitError.matches(exc.value.status, exc.value.payload)
    assert api.client.detail_calls == 2, "die simulierte Antwort kostet keine Anfrage"


def test_full_flow_in_dev_mode(tmp_path):
    client = FakeClient(total=40)
    api = ConversationApi(client)
    api.max_pages = DEV.listing_max_pages
    api.fetch_budget = DEV.conversation_fetches
    repo = RawRepository(tmp_path / "raw")
    # Ein lokaler Eintrag, der im gekuerzten Listing fehlt, darf nicht als geloescht gelten.
    repo.index.conversations["c039"] = {"json_complete": True, "remote_updated_at": 2.0}
    started = datetime.now(timezone.utc)
    report = SyncOrchestrator(conversation_api=api, file_api=None, repository=repo, listing_limit=4,
                              listing_mode="full", fetch_files=False, verify_boundary=False,
                              rate_limit_wait_minutes=0, refill_minutes=DEV.refill_minutes,
                              partial_full_listing=True).run(write_manifest=False)
    assert client.listing_calls == DEV.listing_max_pages + 1            # 3 Seiten aktiv + 1 archiviert
    assert report["stats"]["remote_total"] == 12
    assert report["stats"]["fetched"] == DEV.conversation_fetches
    assert report["stats"]["missing_remote"] == 0
    limit = report["rate_limit"]
    assert limit["stopped"] is True and limit["open_conversations"] == 12 - DEV.conversation_fetches
    full_at = datetime.fromisoformat(limit["estimated_full_at"].replace("Z", "+00:00"))
    assert started + timedelta(minutes=4) < full_at < started + timedelta(minutes=6)
    assert report["aborted"] is False and report["error_budget"]["api_errors_seen"] == 0


def test_without_dev_mode_nothing_changes(tmp_path):
    client = FakeClient(total=12)
    report = SyncOrchestrator(conversation_api=ConversationApi(client), file_api=None,
                              repository=RawRepository(tmp_path / "raw"), listing_limit=4, listing_mode="full",
                              fetch_files=False, verify_boundary=False).run(write_manifest=False)
    assert report["stats"]["fetched"] == 12 and report["rate_limit"]["stopped"] is False


def test_dev_mode_is_read_from_the_config(tmp_path):
    from chatexporter.providers.chatgpt.config.loader import load_config
    cfg = tmp_path / "config.yaml"
    cfg.write_text("dev_mode: true\n", encoding="utf-8")
    assert load_config(cfg).dev_mode is True
    cfg.write_text("{}\n", encoding="utf-8")
    assert load_config(cfg).dev_mode is False


def test_continuation_uses_the_short_dev_delay(tmp_path):
    from chatexporter.cli import continuation
    now = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
    manifest = {"sources": {"chatgpt": {"ok": True, "detail": {"aborted": False, "rate_limit": {
        "stopped": True, "estimated_full_at": "2026-10-03T15:30:00Z"}}}}}
    decision = continuation.decide(manifest, margin_minutes=10, now=now,
                                   fixed_delay_minutes=DEV.continuation_delay_minutes)
    assert decision["chatgpt"]["at_utc"] == now + timedelta(minutes=5)



def test_dev_settings_are_configurable(tmp_path):
    """Testablauf 2026-10-05: z. B. 5 Listing-Seiten zu je 10 Eintraegen, ohne simuliertes Rate-Limit."""
    from chatexporter.config.dev import banner
    from chatexporter.providers.chatgpt.config.loader import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("dev_mode: true\ndev:\n  listing_max_pages: 5\n  conversation_fetches: 0\n"
                        "providers:\n  chatgpt:\n    sync:\n      listing_limit: 10\n", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.dev_mode and cfg.dev_settings.listing_max_pages == 5 and cfg.dev_settings.conversation_fetches == 0
    assert cfg.sync.listing_limit == 10
    assert cfg.dev_settings.continuation_delay_minutes == DEV.continuation_delay_minutes, "Rest bleibt Standard"
    assert "5 Listing-Seiten" in banner(cfg.dev_settings) and "ohne simuliertes Rate-Limit" in banner(cfg.dev_settings)


def test_dev_settings_never_go_below_their_minimum(tmp_path):
    from chatexporter.providers.chatgpt.config.loader import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("dev:\n  listing_max_pages: 0\n  conversation_fetches: -3\n", encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.dev_settings.listing_max_pages == 1 and cfg.dev_settings.conversation_fetches == 0
