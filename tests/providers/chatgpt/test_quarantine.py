"""Quarantaene: die Sicherungen gegen Fehlklassifikation sind der Kern.

Eine Quarantaene bedeutet, dass ein Datensatz nicht mehr abgerufen wird.
Diese Tests pruefen vor allem, wann sie NICHT ausgeloest werden darf.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from chatexporter.providers.chatgpt.config.models import QuarantineConfig
from chatexporter.providers.chatgpt.storage.quarantine import QuarantineStore


def _store(tmp_path, **kw):
    cfg = QuarantineConfig(enabled=True, min_failed_runs=3, min_age_hours=24,
                            review_after_days=30, **kw)
    return QuarantineStore(tmp_path, cfg)


def _fail(store, run_id, *, now, status=500, detail="Request timeout",
          server_responded=True, run_had_success=True, cid="c1"):
    return store.record_failure("conversation", cid, status=status, detail=detail,
                                 run_id=run_id, server_responded=server_responded,
                                 run_had_success=run_had_success, now=now)


def test_disabled_store_never_quarantines(tmp_path):
    cfg = QuarantineConfig(enabled=False)
    store = QuarantineStore(tmp_path, cfg)
    t0 = datetime.now(timezone.utc)
    for i in range(10):
        assert _fail(store, f"run{i}", now=t0 + timedelta(hours=i * 10)) is False
    assert store.is_quarantined("conversation", "c1") is False


def test_requires_multiple_separate_runs(tmp_path):
    store = _store(tmp_path)
    t0 = datetime.now(timezone.utc)
    # Zehn Versuche im SELBEN Lauf duerfen nicht reichen.
    for _ in range(10):
        assert _fail(store, "run-A", now=t0 + timedelta(days=5)) is False
    assert store.is_quarantined("conversation", "c1") is False


def test_requires_time_spread(tmp_path):
    store = _store(tmp_path)
    t0 = datetime.now(timezone.utc)
    # Drei getrennte Laeufe, aber alle innerhalb einer Stunde: eine kurze
    # Serverstoerung darf nicht zur Aussortierung fuehren.
    assert _fail(store, "r1", now=t0) is False
    assert _fail(store, "r2", now=t0 + timedelta(minutes=20)) is False
    assert _fail(store, "r3", now=t0 + timedelta(minutes=40)) is False
    assert store.is_quarantined("conversation", "c1") is False


def test_network_problem_never_quarantines(tmp_path):
    """Entscheidender Ausschluss: wenn im Lauf NICHTS funktioniert hat,
    deutet das auf Netzwerk/Session hin, nicht auf einen kaputten Datensatz."""
    store = _store(tmp_path)
    t0 = datetime.now(timezone.utc)
    for i in range(5):
        assert _fail(store, f"r{i}", now=t0 + timedelta(days=i),
                      run_had_success=False) is False
    assert store.is_quarantined("conversation", "c1") is False


def test_transport_failure_never_quarantines(tmp_path):
    """Ohne echte Serverantwort (Verbindungsabbruch, Client-Timeout) zaehlt nichts."""
    store = _store(tmp_path)
    t0 = datetime.now(timezone.utc)
    for i in range(5):
        assert _fail(store, f"r{i}", now=t0 + timedelta(days=i),
                      server_responded=False) is False
    assert store.is_quarantined("conversation", "c1") is False


def test_rate_limit_and_auth_never_quarantine(tmp_path):
    store = _store(tmp_path)
    t0 = datetime.now(timezone.utc)
    for status in (429, 401, 403, 404):
        for i in range(5):
            assert _fail(store, f"r{status}-{i}", now=t0 + timedelta(days=i),
                          status=status, detail="egal", cid=f"c{status}") is False
        assert store.is_quarantined("conversation", f"c{status}") is False


def test_changing_error_signature_restarts_counting(tmp_path):
    """Wechselt die Fehlermeldung, ist es kein stabiler Defekt."""
    store = _store(tmp_path)
    t0 = datetime.now(timezone.utc)
    _fail(store, "r1", now=t0, detail="Request timeout")
    _fail(store, "r2", now=t0 + timedelta(days=1), detail="Internal error")
    assert _fail(store, "r3", now=t0 + timedelta(days=2), detail="Internal error") is False
    assert store.is_quarantined("conversation", "c1") is False


def test_stable_server_side_failure_does_quarantine(tmp_path):
    """Der reale Fall: gleiche Serverantwort, drei Laeufe, ueber Tage verteilt."""
    store = _store(tmp_path)
    t0 = datetime.now(timezone.utc)
    assert _fail(store, "r1", now=t0) is False
    assert _fail(store, "r2", now=t0 + timedelta(days=1)) is False
    assert _fail(store, "r3", now=t0 + timedelta(days=2)) is True
    assert store.is_quarantined("conversation", "c1") is True

    entry = store.entry("conversation", "c1")
    assert entry["http_status"] == 500
    assert entry["detail"] == "Request timeout"
    assert len(entry["failed_runs"]) == 3
    assert entry["review_after"] > entry["quarantined_at"]


def test_quarantine_expires_for_review(tmp_path):
    store = _store(tmp_path)
    t0 = datetime.now(timezone.utc)
    _fail(store, "r1", now=t0)
    _fail(store, "r2", now=t0 + timedelta(days=1))
    _fail(store, "r3", now=t0 + timedelta(days=2))

    # Kurz vor Ablauf weiterhin aktiv ...
    assert store.is_quarantined("conversation", "c1",
                                 now=t0 + timedelta(days=20)) is True
    # ... danach faellig zur erneuten Pruefung.
    later = t0 + timedelta(days=40)
    assert store.is_quarantined("conversation", "c1", now=later) is False
    assert "c1" in store.due_for_review("conversation", now=later)


def test_survives_roundtrip_to_disk(tmp_path):
    store = _store(tmp_path)
    t0 = datetime.now(timezone.utc)
    _fail(store, "r1", now=t0)
    _fail(store, "r2", now=t0 + timedelta(days=1))
    _fail(store, "r3", now=t0 + timedelta(days=2))
    store.save()

    reloaded = _store(tmp_path)
    assert reloaded.is_quarantined("conversation", "c1") is True
    assert reloaded.summary()["conversations"] == 1
