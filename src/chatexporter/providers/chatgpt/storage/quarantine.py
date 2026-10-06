"""Quarantaene fuer dauerhaft fehlschlagende Conversations und Dateien.

Warum das vorsichtig gebaut ist
--------------------------------
Eine Quarantaene bedeutet, dass ein Datensatz **nicht mehr abgerufen** wird.
Das darf niemals beilaeufig passieren -- insbesondere nicht wegen eines
Netzwerkproblems, einer abgelaufenen Session oder einer voruebergehenden
Serverstoerung. Deshalb muessen fuer eine Aufnahme **alle** folgenden
Bedingungen gleichzeitig erfuellt sein:

1. **Der Server hat geantwortet.** Nur HTTP-Antworten mit auswertbarem
   Body zaehlen. Ein Verbindungsabbruch, ein clientseitiger Timeout oder
   ein geschlossener Browser-Kontext zaehlt nie -- gerade die beweisen
   nicht, dass mit dem Datensatz etwas nicht stimmt.
2. **Im selben Lauf haben andere Requests funktioniert.** Das ist der
   entscheidende Ausschluss fuer Netzwerk-, Auth- und Sessionprobleme: bei
   denen scheitert alles, nicht ausgerechnet immer derselbe Datensatz.
3. **Gleiche Fehlersignatur** (Status *und* ``detail``) ueber alle Vorfaelle.
4. **Mindestens N getrennte Laeufe** -- nicht N Versuche innerhalb eines Laufs.
5. **Zeitlich gespreizt**, damit eine mehrstuendige Stoerung nicht reicht.

Ausgenommen sind ausserdem HTTP 429 (Rate-Limit, regulaerer Zustand),
401/403 (Auth) und 404 (gehoert in die MISSING_REMOTE-Logik).

Eine Quarantaene ist nie endgueltig: jeder Eintrag traegt ``review_after``
und wird danach erneut geprueft -- einmal pro Lauf und bewusst am ENDE des
Laufs, damit ein langlaufender Timeout nie den Fortschritt blockiert.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from chatexporter.providers.chatgpt.common.io import atomic_write_json
from chatexporter.providers.chatgpt.common.time import now_iso

QUARANTINE_SCHEMA_VERSION = 1

#: Statuscodes, die nie zur Quarantaene fuehren duerfen.
NEVER_QUARANTINE_STATUS = frozenset({401, 403, 404, 429})


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def failure_signature(status: int | None, detail: str | None) -> str:
    return "%s|%s" % (status, (detail or "").strip().lower())


class QuarantineStore:
    """Persistente Liste unter ``<runtime>/status_registry/quarantine.json``.

    Die Datei ist bewusst menschenlesbar und von Hand editierbar: sie ist
    die einzige Stelle, an der festgehalten wird, dass ein Datensatz
    absichtlich nicht mehr abgerufen wird.
    """

    def __init__(self, raw_root: Path, config: Any | None = None, *,
                 path: Path | None = None, staging: Path | None = None):
        self.root = raw_root
        self.path = Path(path) if path is not None else raw_root / "quarantine.json"
        self.staging = Path(staging) if staging is not None else raw_root / ".staging"
        self.enabled = bool(getattr(config, "enabled", False))
        self.min_failed_runs = max(1, int(getattr(config, "min_failed_runs", 3)))
        self.min_age_hours = max(0, int(getattr(config, "min_age_hours", 24)))
        self.review_after_days = max(0, int(getattr(config, "review_after_days", 30)))
        self.data: dict[str, Any] = {
            "schema_version": QUARANTINE_SCHEMA_VERSION,
            "generated_at": None,
            "conversations": {},
            "files": {},
        }
        self._load()

    # -- Persistenz -------------------------------------------------------
    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            import json
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(loaded, dict):
            return
        if loaded.get("schema_version") != QUARANTINE_SCHEMA_VERSION:
            return
        for bucket in ("conversations", "files"):
            if isinstance(loaded.get(bucket), dict):
                self.data[bucket] = loaded[bucket]

    def save(self) -> None:
        self.data["generated_at"] = now_iso()
        atomic_write_json(self.path, self.data, staging_dir=self.staging)

    # -- Abfrage ----------------------------------------------------------
    def _bucket(self, kind: str) -> dict[str, Any]:
        return self.data["files"] if kind == "file" else self.data["conversations"]

    def entry(self, kind: str, identifier: str) -> dict[str, Any] | None:
        return self._bucket(kind).get(identifier)

    def is_quarantined(self, kind: str, identifier: str, *, now: datetime | None = None) -> bool:
        """True, solange der Eintrag aktiv ist (Review-Zeitpunkt noch nicht erreicht)."""
        if not self.enabled:
            return False
        entry = self.entry(kind, identifier)
        if not entry or not entry.get("quarantined"):
            return False
        review = _parse_iso(entry.get("review_after"))
        if review is None:
            return True
        current = now or datetime.now(timezone.utc)
        return current < review

    def due_for_review(self, kind: str, *, now: datetime | None = None) -> list[str]:
        if not self.enabled:
            return []
        current = now or datetime.now(timezone.utc)
        due = []
        for identifier, entry in self._bucket(kind).items():
            if not entry.get("quarantined"):
                continue
            review = _parse_iso(entry.get("review_after"))
            if review is not None and current >= review:
                due.append(identifier)
        return sorted(due)

    def active(self, kind: str) -> list[str]:
        return sorted(i for i in self._bucket(kind) if self._bucket(kind)[i].get("quarantined"))

    # -- Pflege -----------------------------------------------------------
    def record_failure(self, kind: str, identifier: str, *, status: int | None,
                       detail: str | None, run_id: str, endpoint: str | None = None,
                       elapsed_ms: float | None = None, request_id: str | None = None,
                       server_responded: bool, run_had_success: bool,
                       now: datetime | None = None) -> bool:
        """Verbucht einen Fehlversuch. Gibt True zurueck, wenn dadurch eine
        Quarantaene ausgeloest wurde.

        ``server_responded`` und ``run_had_success`` sind die beiden
        Sicherungen gegen Fehlklassifikation und werden vom Aufrufer aus dem
        tatsaechlichen Laufzustand gesetzt.
        """
        if not self.enabled:
            return False
        if status in NEVER_QUARANTINE_STATUS:
            return False
        if not server_responded or not run_had_success:
            return False

        current = now or datetime.now(timezone.utc)
        bucket = self._bucket(kind)
        signature = failure_signature(status, detail)
        entry = bucket.get(identifier)
        if entry is None or entry.get("signature") != signature:
            # Neuer Fall oder geaenderte Fehlersignatur -> Zaehlung beginnt neu.
            entry = {
                "signature": signature,
                "http_status": status,
                "detail": detail,
                "endpoint": endpoint,
                "first_seen": now_iso(),
                "last_seen": now_iso(),
                "failed_runs": [],
                "attempts": [],
                "quarantined": False,
            }
            bucket[identifier] = entry

        entry["last_seen"] = now_iso()
        entry["attempts"].append({
            "at": now_iso(),
            "run_id": run_id,
            "http_status": status,
            "detail": detail,
            "elapsed_ms": elapsed_ms,
            "request_id": request_id,
        })
        # Nur die letzten Vorfaelle behalten, damit die Datei lesbar bleibt.
        entry["attempts"] = entry["attempts"][-20:]
        if run_id not in entry["failed_runs"]:
            entry["failed_runs"].append(run_id)

        if entry.get("quarantined"):
            return False

        first = _parse_iso(entry.get("first_seen")) or current
        age_hours = (current - first).total_seconds() / 3600.0
        if len(entry["failed_runs"]) >= self.min_failed_runs and age_hours >= self.min_age_hours:
            entry["quarantined"] = True
            entry["quarantined_at"] = now_iso()
            entry["review_after"] = (
                current + timedelta(days=self.review_after_days)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            entry["reason"] = (
                "%d Laeufe mit identischer Serverantwort (%s) ueber %.1f Stunden"
                % (len(entry["failed_runs"]), signature, age_hours)
            )
            return True
        return False

    def clear(self, kind: str, identifier: str) -> bool:
        """Hebt eine Quarantaene auf (z. B. nach erfolgreichem Review-Versuch)."""
        bucket = self._bucket(kind)
        if identifier in bucket:
            del bucket[identifier]
            return True
        return False

    def summary(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "conversations": len(self.active("conversation")),
            "files": len(self.active("file")),
            "thresholds": {
                "min_failed_runs": self.min_failed_runs,
                "min_age_hours": self.min_age_hours,
                "review_after_days": self.review_after_days,
            },
        }
