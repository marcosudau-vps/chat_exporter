"""Listing-Resilienz: 429 und transiente Fehler beim Listing duerfen den Lauf
nicht mehr unprotokolliert abbrechen (Funde 2026-09-29/2026-09-30).

Alle Tests laufen offline gegen Fake-APIs; es werden keine echten Daten geladen.
"""
from chatexporter.providers.chatgpt.api.client import ApiError, ApiTransportClosedError, RateLimitError
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.sync.orchestrator import SyncOrchestrator


def _listing_429():
    return RateLimitError(
        "HTTP 429 for /backend-api/conversations",
        status=429, endpoint="/backend-api/conversations",
        payload={"detail": "Too many requests"})


class FakeFileApi:
    pass


class Listing429Api:
    """Listing scheitert immer mit 429 (Body wie real gemessen)."""

    def __init__(self):
        self.calls = 0

    def iter_scope(self, *, archived, limit=100):
        self.calls += 1
        raise _listing_429()

    def get_conversation(self, cid):
        raise AssertionError("kein Fetch erwartet")

    def get_textdocs(self, cid):
        return []


class FlakyListingApi:
    """Wirft `failures`-mal ECONNRESET und liefert danach ein leeres Listing."""

    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def iter_scope(self, *, archived, limit=100):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("APIRequestContext.get: read ECONNRESET")
        return iter(())

    def get_conversation(self, cid):
        raise AssertionError("kein Fetch erwartet")

    def get_textdocs(self, cid):
        return []


class Listing401Api:
    def iter_scope(self, *, archived, limit=100):
        raise ApiError("HTTP 401 for /backend-api/conversations",
                       status=401, endpoint="/backend-api/conversations")

    def get_conversation(self, cid):
        raise AssertionError("kein Fetch erwartet")

    def get_textdocs(self, cid):
        return []


class TransportClosedListingApi:
    def iter_scope(self, *, archived, limit=100):
        raise ApiTransportClosedError("Target page, context or browser has been closed")

    def get_conversation(self, cid):
        raise AssertionError("kein Fetch erwartet")

    def get_textdocs(self, cid):
        return []


def _run(api, tmp_path, **kwargs):
    repo = RawRepository(tmp_path / "raw")
    messages = []
    sleeps = []
    orch = SyncOrchestrator(
        conversation_api=api, file_api=FakeFileApi(), repository=repo,
        fetch_files=False, rate_limit_wait_minutes=0,
        progress=messages.append, sleep=sleeps.append, **kwargs)
    return orch.run(), messages, sleeps


def test_listing_429_is_regular_end_not_abort(tmp_path):
    """Kernforderung: 429 beim Listing beendet regulaer und wird erfasst."""
    result, messages, sleeps = _run(Listing429Api(), tmp_path)
    assert result["aborted"] is False, "Listing-429 darf keinen Abbruch ausloesen"
    assert result["stats"]["remote_total"] == 0
    assert result["rate_limit"]["hits"] == 1, "429 muss als Rate-Limit gezaehlt werden"
    assert result["rate_limit"]["events"][0]["stage"] == "listing"
    assert result["error_budget"]["api_errors_seen"] == 0, "429 darf kein Budget kosten"
    assert result["stats"]["errors"] == []
    assert sleeps == [], "ohne Wartezeit kein Sleep"
    assert any("Rate-Limit beim Listing" in m for m in messages)


def test_listing_429_retries_after_wait(tmp_path):
    """Mit Wartezeit konfiguriert: warten, Listing wiederholen, fortsetzen."""
    api = Listing429Api()
    calls = {"n": 0}
    real_iter = api.iter_scope

    def flaky(*, archived, limit=100):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_iter(archived=archived, limit=limit)
        return iter(())

    api.iter_scope = flaky
    repo = RawRepository(tmp_path / "raw")
    messages, sleeps = [], []
    result = SyncOrchestrator(
        conversation_api=api, file_api=FakeFileApi(), repository=repo,
        fetch_files=False, rate_limit_wait_minutes=10,
        progress=messages.append, sleep=sleeps.append).run()
    assert result["aborted"] is False
    assert result["rate_limit"]["hits"] == 1
    assert sleeps == [600]
    assert result["rate_limit"]["events"][0]["resumed"] is True


def test_listing_transient_retry_then_success(tmp_path):
    result, messages, sleeps = _run(FlakyListingApi(failures=2), tmp_path)
    assert result["aborted"] is False
    assert result["stats"]["remote_total"] == 0
    assert sleeps == [5.0, 15.0]
    assert any("erneuter Versuch" in m for m in messages)


def test_listing_transient_exhausted_aborts_controlled(tmp_path):
    result, messages, sleeps = _run(FlakyListingApi(failures=99), tmp_path)
    assert result["aborted"] is True
    assert result["abort_stage"] == "bootstrap_or_listing"
    assert len(result["stats"]["errors"]) == 1
    assert sleeps == [5.0, 15.0, 30.0], "genau 3 Wiederholungen, dann Abbruch"


def test_listing_401_aborts_with_clear_reason(tmp_path):
    result, messages, sleeps = _run(Listing401Api(), tmp_path)
    assert result["aborted"] is True
    assert result["abort_stage"] == "listing"
    assert "revalidated" in result["abort_reason"]
    assert sleeps == [], "Auth-Verlust wird nicht wiederholt"


def test_transport_closed_during_listing_no_retry(tmp_path):
    result, messages, sleeps = _run(TransportClosedListingApi(), tmp_path)
    assert result["aborted"] is True
    assert sleeps == [], "toter Browser: kein Retry-Sturm"


def test_non_transient_listing_error_aborts_immediately(tmp_path):
    class BrokenApi(FlakyListingApi):
        def iter_scope(self, *, archived, limit=100):
            raise ValueError("kaputtes Listing-Format")

    result, messages, sleeps = _run(BrokenApi(failures=0), tmp_path)
    assert result["aborted"] is True
    assert sleeps == [], "Programmier-/Formatfehler werden nicht wiederholt"
