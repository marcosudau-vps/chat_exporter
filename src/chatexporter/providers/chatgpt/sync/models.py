from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SyncAction(str, Enum):
    FETCH_FULL = "FETCH_FULL"
    #: Conversation-JSON ist vollstaendig, nur Dateien fehlen noch. Spart den
    #: teuren Conversation-Abruf -- relevant, weil das Request-Budget knapp ist.
    FETCH_FILES_ONLY = "FETCH_FILES_ONLY"
    SKIP = "SKIP"
    MISSING_REMOTE = "MISSING_REMOTE"
    #: Bewusst aussortiert (siehe storage/quarantine.py).
    QUARANTINED = "QUARANTINED"
    #: Nach manueller Pruefung bewusst ausgeschlossen (sync/exclusions.py).
    EXCLUDED = "EXCLUDED"


@dataclass(slots=True)
class PlanItem:
    conversation_id: str
    action: SyncAction
    remote_summary: dict[str, Any] | None = None
    reason: str = ""


@dataclass(slots=True)
class SyncStats:
    remote_total: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    missing_remote: int = 0
    fetched: int = 0
    fetch_failed: int = 0
    file_refs_queued: int = 0
    files_materialized: int = 0
    files_cached: int = 0
    files_failed: int = 0
    files_unavailable: int = 0
    files_only_runs: int = 0
    rate_limit_hits: int = 0
    rate_limit_wait_seconds: float = 0.0
    quarantined_skipped: int = 0
    quarantined_new: int = 0
    quarantine_reviews: int = 0
    excluded_skipped: int = 0
    #: Grenzpruefung an der Aenderungsgrenze (Detailabruf, Turn-Ebene).
    verified_unchanged: int = 0
    verify_mismatches: int = 0
    verify_requests: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    verify_events: list[dict[str, Any]] = field(default_factory=list)
    rate_limit_events: list[dict[str, Any]] = field(default_factory=list)
    quarantine_events: list[dict[str, Any]] = field(default_factory=list)
