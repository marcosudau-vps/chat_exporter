from __future__ import annotations
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from chatexporter.providers.chatgpt.api.client import ApiError, ApiTransportClosedError, RateLimitError
from chatexporter.providers.chatgpt.api.conversations import ConversationApi
from chatexporter.providers.chatgpt.api.files import FileApi
from chatexporter.providers.chatgpt.fetch.conversation_fetcher import ConversationFetcher
from chatexporter.providers.chatgpt.storage.envelope import build_envelope, refresh_acquisition_completeness
from chatexporter.providers.chatgpt.storage.library import LibraryStore
from chatexporter.providers.chatgpt.storage.quarantine import QuarantineStore
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.common.io import atomic_write_json, atomic_write_text
from chatexporter.providers.chatgpt.common.time import now_iso
from chatexporter.providers.chatgpt.common.redaction import compact_error_text, sanitize_reasoning_payload
from .listing import LISTING_MODES, fetch_complete_listing, fetch_recent_listing
from .exclusions import ManualExclusions
from .models import SyncAction, SyncStats
from .planner import build_plan

#: Gemessene Wiederauffuellrate des Conversation-Detail-Endpunkts
#: (Forschungsakte 2026-09-21, Regression ueber sieben reale Laeufe).
REFILL_REQUESTS_PER_MINUTE = 0.967
#: Gemessene Kapazitaet des Buckets.
BUCKET_CAPACITY = 210
#: Hoechstzahl erneuter Pruefungen quarantaenisierter Eintraege je Lauf.
#: Jeder Versuch ist ein echter Request; ohne Deckel wuerden viele faellige
#: Eintraege am Laufende das knappe Budget aufzehren.
MAX_QUARANTINE_REVIEWS_PER_RUN = 3
#: Listing-Resilienz: GET /backend-api/conversations hat ein eigenes, vom
#: Detail-Endpunkt unabhaengiges Kontingent. Am 2026-09-30 schlug das Listing
#: mit 429 fehl, obwohl der Detail-Bucket praktisch voll war (nur 5
#: Detail-Requests im Vorlauf). Transiente Listing-Fehler (ECONNRESET & Co.)
#: werden deshalb begrenzt wiederholt statt sofort abzubrechen.
LISTING_MAX_RETRIES = 3
#: Wartezeiten zwischen Listing-Wiederholungen in Sekunden.
LISTING_RETRY_DELAYS = (5.0, 15.0, 30.0)
#: Textmarker transienter Transportfehler (kleingeschrieben verglichen).
_TRANSIENT_LISTING_MARKERS = (
    "econnreset", "etimedout", "econnaborted", "econnrefused",
    "socket hang up", "network unreachable", "eai_again",
    "temporarily unavailable", "timeout", "timed out",
    "connection reset", "connection aborted",
)


class SyncAbort(RuntimeError):
    def __init__(self, reason: str, *, stage: str, fatal: bool = False):
        super().__init__(reason)
        self.reason = reason
        self.stage = stage
        self.fatal = fatal


class RateLimitReached(RuntimeError):
    """Signalisiert das Erreichen des Rate-Limits.

    Bewusst KEIN Fehler im Sinne des Fehlerbudgets: ein Rate-Limit ist ein
    regulaerer, erwartbarer Serverzustand bei groesseren Syncs.
    """

    def __init__(self, stage: str, conversation_id: str | None = None):
        super().__init__("rate limit reached")
        self.stage = stage
        self.conversation_id = conversation_id
        #: Noch nicht abgearbeitete Planeintraege, inklusive des blockierten.
        #: Wird von `_process_items` gesetzt. Ohne diese Liste wuerde nach der
        #: Wartezeit der komplette Zyklus von vorn beginnen und bereits
        #: geholte Conversations erneut abrufen -- also genau das knappe
        #: Budget verschwenden, das geschont werden soll.
        self.remaining: list[Any] = []


class SyncOrchestrator:
    def __init__(self, *, conversation_api: ConversationApi, file_api: FileApi,
                 repository: RawRepository,
                 listing_limit: int = 100, listing_mode: str = "auto",
                 recent_max_pages: int = 3, recent_confirm_unchanged: int = 3,
                 verify_boundary: bool = True, verify_max_requests: int = 0,
                 fetch_files: bool = True,
                 fetch_textdocs: bool = True, retry_pending_files: bool = True,
                 continue_on_error: bool = True, max_errors_per_run: int = 5,
                 max_file_errors_per_run: int = 50,
                 rate_limit_wait_minutes: int = 0, max_rate_limit_cycles: int = 0,
                 quarantine: QuarantineStore | None = None,
                 exclusions: ManualExclusions | None = None,
                 progress: Callable[[str], None] | None = None,
                 sleep: Callable[[float], None] | None = None,
                 refill_minutes: float | None = None, partial_full_listing: bool = False):
        self.conversation_api = conversation_api
        self.file_api = file_api
        self.repository = repository
        self.library = getattr(repository, "library", None) or LibraryStore(
            repository.root, status_root=getattr(repository, "status_root", None))
        self.quarantine = quarantine or QuarantineStore(repository.root)
        self.exclusions = exclusions or ManualExclusions()
        self.listing_limit = listing_limit
        if listing_mode not in LISTING_MODES:
            raise ValueError(f"unknown listing_mode: {listing_mode!r}")
        self.listing_mode = listing_mode
        self.recent_max_pages = max(1, int(recent_max_pages))
        self.recent_confirm_unchanged = max(1, int(recent_confirm_unchanged))
        #: Grenzpruefung auf Turn-Ebene (siehe `_verify_boundary`).
        self.verify_boundary = bool(verify_boundary)
        #: Obergrenze Detailabrufe der Grenzpruefung je Lauf (0 = unbegrenzt;
        #: ein Rate-Limit beendet sie ohnehin).
        self.verify_max_requests = max(0, int(verify_max_requests))
        self._verification: dict[str, Any] = {"enabled": self.verify_boundary}
        #: Kennzahlen des letzten Listings (Modus, Seiten, Grenze gefunden).
        self._listing_info: dict[str, Any] = {"mode": listing_mode}
        self.fetch_files = fetch_files
        self.retry_pending_files = retry_pending_files
        self.continue_on_error = continue_on_error
        self.max_errors_per_run = max(1, int(max_errors_per_run))
        self.max_file_errors_per_run = max(1, int(max_file_errors_per_run))
        self.rate_limit_wait_minutes = max(0, int(rate_limit_wait_minutes))
        self.max_rate_limit_cycles = max(0, int(max_rate_limit_cycles))
        self.fetcher = ConversationFetcher(conversation_api, fetch_textdocs=fetch_textdocs)
        self.progress = progress or (lambda _message: None)
        self.sleep = sleep or time.sleep
        #: Entwicklungsmodus: geschaetzte Auffuellzeit statt der gemessenen ...
        self.refill_minutes = refill_minutes
        #: ... und ein (gekuerztes) Voll-Listing gilt als Teil-Listing.
        self.partial_full_listing = partial_full_listing
        self._api_error_count = 0
        self._file_error_count = 0
        self._run_id = now_iso()
        # Beleg dafuer, dass Netzwerk/Session in diesem Lauf funktioniert haben.
        # Ohne mindestens einen Erfolg wird nichts quarantaenisiert.
        self._run_had_success = False
        self._seen_file_ids: set[str] = set()
        #: Nachvollziehbarkeit im Laufbericht: was wurde gespeichert/was nicht.
        self._items: dict[str, list[dict[str, Any]]] = {"fetched": [], "files": [], "failed": []}

    # ------------------------------------------------------------------
    # Rate-Limit
    # ------------------------------------------------------------------
    @staticmethod
    def _is_rate_limit(exc: Exception) -> bool:
        """Prueft Status UND Antwortbody, nicht nur die Fehlerklasse.

        Die Klasse allein waere ein zu schwaches Kriterium: sie koennte an
        anderer Stelle versehentlich gesetzt werden. Ein Rate-Limit fuehrt
        dazu, dass ein Fehler NICHT gegen das Fehlerbudget zaehlt -- diese
        Ausnahme muss an den tatsaechlichen Serverdaten haengen. Ein HTTP 429
        mit abweichendem ``detail`` kann eine andere Ursache haben und wird
        bewusst wie ein normaler Fehler behandelt.
        """
        if not isinstance(exc, ApiError):
            return False
        return RateLimitError.matches(exc.status, exc.payload)

    def _estimate_full_at(self, now: datetime) -> datetime:
        """Grobe Schaetzung, wann das Budget wieder voll ist.

        Beim Erreichen des Limits ist der Bucket praktisch leer; bei der
        gemessenen Rate dauert eine volle Auffuellung rund 3,6 Stunden.
        Die Aussage soll nur sinngemaess vermitteln, ab wann sich ein
        vollstaendiger Durchlauf wieder lohnt.
        """
        minutes = self.refill_minutes or BUCKET_CAPACITY / REFILL_REQUESTS_PER_MINUTE
        return now + timedelta(minutes=minutes)

    def _counts_for_report(self, stats: SyncStats) -> tuple[int, int, int, int]:
        index = self.repository.index.conversations
        chats_done = sum(1 for e in index.values() if e.get("json_complete", e.get("fetch_complete")))
        # Bei einem Teil-Listing (recent) ist remote_total nur eine Teilmenge.
        chats_total = (stats.remote_total if self.effective_listing == "full" else 0) or len(index)
        files_total = sum(int(e.get("file_reference_count") or 0) for e in index.values())
        files_done = sum(int(e.get("file_materialized_count") or 0) for e in index.values())
        return chats_done, chats_total, files_done, files_total

    def _emit_rate_limit_block(self, stats: SyncStats, stage: str,
                                conversation_id: str | None, waiting_minutes: int) -> None:
        now = datetime.now(timezone.utc)
        chats_done, chats_total, files_done, files_total = self._counts_for_report(stats)
        full_at = self._estimate_full_at(now)
        resume_at = now + timedelta(minutes=waiting_minutes) if waiting_minutes else None

        self.progress("")
        self.progress("[LIMIT ERREICHT]      %s" % now.strftime("%d.%m.%Y, %H:%M"))
        self.progress("[CHATS]               %d von %d" % (chats_done, chats_total))
        self.progress("[FILES]               %d von %d" % (files_done, files_total))
        self.progress("[LIMIT WIEDER VOLL]   %s (geschaetzt)" % full_at.strftime("%d.%m.%Y, %H:%M"))
        if resume_at is not None:
            self.progress("[WARTE]               %d Minuten, weiter ab %s"
                          % (waiting_minutes, resume_at.strftime("%d.%m.%Y, %H:%M")))
        self.progress("")

        stats.rate_limit_hits += 1
        stats.rate_limit_events.append({
            "at": now_iso(),
            "stage": stage,
            "conversation_id": conversation_id,
            "conversations_done": chats_done,
            "conversations_total": chats_total,
            "files_done": files_done,
            "files_total": files_total,
            "estimated_full_at": full_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "waited_minutes": waiting_minutes,
            "resumed": bool(waiting_minutes),
        })

    @staticmethod
    def _is_transient_listing_error(exc: Exception) -> bool:
        """Transportfehler beim Listing, bei denen ein Retry sinnvoll ist.
        Fatal bleibt fatal: geschlossener Browser, Auth-Verlust und SyncAbort
        werden nie wiederholt."""
        if isinstance(exc, (ApiTransportClosedError, SyncAbort)):
            return False
        if isinstance(exc, ApiError):
            return exc.status not in (401, 403)
        return any(m in str(exc).lower() for m in _TRANSIENT_LISTING_MARKERS)

    def _retry_listing_or_raise(self, exc: Exception, attempt: int) -> None:
        """Protokolliert einen transienten Listing-Fehler und wartet.
        Wirft den Originalfehler, wenn die Versuche erschoepft sind."""
        if attempt >= LISTING_MAX_RETRIES:
            raise exc
        delay = LISTING_RETRY_DELAYS[min(attempt, len(LISTING_RETRY_DELAYS) - 1)]
        self.progress("Listing-Fehler (%s), erneuter Versuch %d/%d in %ds ..."
                      % (compact_error_text(exc), attempt + 1,
                         LISTING_MAX_RETRIES, int(delay)))
        self.sleep(delay)

    def _wait_for_listing_rate_limit(self, stats: SyncStats, listing_cycles: int) -> bool:
        """Behandelt 429 beim Listing als regulaeres Ereignis (kein Budget).
        True = warten und Listing wiederholen, False = regulaeres Laufende."""
        wait = self.rate_limit_wait_minutes
        cycles_exhausted = (self.max_rate_limit_cycles and listing_cycles >= self.max_rate_limit_cycles)
        if wait <= 0 or cycles_exhausted:
            self._emit_rate_limit_block(stats, "listing", None, 0)
            if cycles_exhausted:
                self.progress("Maximale Anzahl Wartezyklen erreicht (%d)."
                              % self.max_rate_limit_cycles)
            self.progress("Lauf wird regulär beendet (Rate-Limit beim Listing, keine Daten geladen).")
            return False
        self._emit_rate_limit_block(stats, "listing", None, wait)
        stats.rate_limit_wait_seconds += wait * 60
        self.sleep(wait * 60)
        return True

    @property
    def effective_listing(self) -> str:
        """Tatsaechlich verwendetes Listing (`full`/`recent`), auch im Modus auto."""
        return self._listing_info.get("effective", self.listing_mode)

    def _is_known_unsynced(self, conversation_id: str) -> bool:
        """Bewusst nie geladen: manuell ausgeschlossen oder in Quarantaene."""
        return (self.exclusions.is_excluded("conversation", conversation_id)
                or self.quarantine.is_quarantined("conversation", conversation_id))

    def _recent_listing(self) -> tuple[dict[str, Any], dict[str, Any]]:
        self.progress("Remote-Listing (recent, order=updated) wird geladen ...")
        remote, info = fetch_recent_listing(
            self.conversation_api,
            local_index=self.repository.index.conversations,
            limit=self.listing_limit, max_pages=self.recent_max_pages,
            confirm_unchanged=self.recent_confirm_unchanged,
            ignore=self._is_known_unsynced,
            progress=self.progress,
        )
        if info.get("ignored"):
            self.progress("Listing recent: %d bewusst nicht synchronisierte Conversation(s) "
                          "(manuell ausgeschlossen/Quarantaene) fuer die Grenze ignoriert."
                          % len(info["ignored"]))
        self._run_had_success = True
        self.progress(f"Remote-Listing (recent) abgeschlossen: {len(remote)} Conversations, "
                      f"{info['changed']} neu/geaendert, {info['pages']} Seite(n), "
                      f"Grenze {'bestaetigt' if info['boundary_reached'] else 'NICHT bestaetigt'}.")
        return remote, info

    def _full_listing(self) -> dict[str, Any]:
        self.progress("Remote-Listing (full) wird geladen ...")
        remote = fetch_complete_listing(
            self.conversation_api, limit=self.listing_limit, progress=self.progress
        )
        self._run_had_success = True
        self.progress(f"Remote-Listing abgeschlossen: {len(remote)} Conversations insgesamt.")
        return remote

    def _fetch_listing(self) -> dict[str, Any]:
        """Ein Listing gemaess Modus; setzt ``self._listing_info``.

        ``auto``: ohne lokalen Bestand Erstabruf (full); sonst recent, und wenn
        dessen Aenderungsgrenze nicht bestaetigt ist, im selben Lauf full.
        """
        if self.listing_mode == "recent":
            remote, info = self._recent_listing()
            if not info["boundary_reached"]:
                self._log_anomalies(info)
            self._listing_info = {**info, "effective": "recent"}
            return remote
        if self.listing_mode == "full":
            remote = self._full_listing()
            self._listing_info = {"mode": "full", "effective": "full", "items": len(remote)}
            return remote
        # auto
        if not self.repository.index.conversations:
            self.progress("Listing-Modus auto: kein lokaler Bestand -> Erstabruf (full).")
            remote = self._full_listing()
            self._listing_info = {"mode": "auto", "effective": "full", "escalation": "initial",
                                  "items": len(remote)}
            return remote
        lost = list(getattr(self.repository.index, "lost_entries", None) or [])
        if lost:
            # Lokal geloeschte Conversations koennen hinter der Aenderungsgrenze liegen; recent
            # saehe sie nie wieder. Ein Voll-Listing findet sie (als "neu") und laedt sie neu.
            self.progress(f"Listing-Modus auto: {len(lost)} Conversation(s) fehlen lokal (Dateien "
                          "geloescht) -> full, damit sie neu geladen werden.")
            remote = self._full_listing()
            self._listing_info = {"mode": "auto", "effective": "full", "escalation": "local_files_missing",
                                  "items": len(remote), "local_missing": lost[:20]}
            return remote
        remote, info = self._recent_listing()
        if info["boundary_reached"]:
            self._listing_info = {**info, "mode": "auto", "effective": "recent"}
            return remote
        self.progress(f"Listing-Modus auto: Aenderungsgrenze nicht bestaetigt "
                      f"({info['reason']}) -> Wechsel auf full.")
        self._log_anomalies(info)
        # Diagnose SOFORT festhalten: bricht der Voll-Abruf ab (Strg+C,
        # Rate-Limit), steht der Grund trotzdem im Laufbericht.
        self._listing_info = {"mode": "auto", "effective": "full", "escalation": info["reason"],
                              "full_completed": False, "recent": info}
        remote = self._full_listing()
        self._listing_info = {"mode": "auto", "effective": "full", "escalation": info["reason"],
                              "full_completed": True, "items": len(remote), "recent": info}
        return remote

    def _log_anomalies(self, info: dict[str, Any]) -> None:
        """Welche Eintraege haben die Grenze verletzt? (Konsole; Details im Bericht)"""
        by_id = {e["id"]: e for e in info.get("entries") or []}
        for reason, ids in (info.get("anomalies") or {}).items():
            for cid in ids[:10]:
                entry = by_id.get(cid, {})
                self.progress("  Grenzverletzung %s: %s (Position %s, %s, remote %s, lokal %s)"
                              % (reason, cid, entry.get("pos", "?"), entry.get("kind", "?"),
                                 entry.get("remote_update_time"), entry.get("local_update_time")))

    def _load_listing(self, stats: SyncStats) -> tuple[dict[str, Any], bool]:
        """Laedt das Remote-Listing mit Retry-Politik.
        Gibt (remote, rate_limited_end) zurueck: rate_limited_end=True bedeutet
        regulaeres Laufende wegen Rate-Limit (kein Abbruch, keine Daten)."""
        listing_cycles = 0
        transient_attempt = 0
        while True:
            try:
                return self._fetch_listing(), False
            except (KeyboardInterrupt, SyncAbort, ApiTransportClosedError):
                raise
            except ApiError as exc:
                if self._is_rate_limit(exc):
                    listing_cycles += 1
                    if self._wait_for_listing_rate_limit(stats, listing_cycles):
                        continue
                    return {}, True
                if exc.status in (401, 403):
                    raise SyncAbort(
                        f"Core API request returned HTTP {exc.status}; authentication/session must be revalidated",
                        stage="listing")
                self._retry_listing_or_raise(exc, transient_attempt)
                transient_attempt += 1
                continue
            except Exception as exc:
                if not self._is_transient_listing_error(exc):
                    raise
                self._retry_listing_or_raise(exc, transient_attempt)
                transient_attempt += 1
                continue

    # ------------------------------------------------------------------
    # Lauf
    # ------------------------------------------------------------------
    def run(self, *, write_manifest: bool = True) -> dict[str, Any]:
        started = now_iso()
        stats = SyncStats()
        aborted = False
        abort_reason: str | None = None
        abort_stage: str | None = None
        plan: list[Any] = []
        cycle = 0

        fetch_rate_limited = False
        listing_rate_limited = False
        open_after_limit: int | None = None
        try:
            remote, listing_rate_limited = self._load_listing(stats)
            stats.remote_total = len(remote)
            plan = [] if listing_rate_limited else build_plan(
                remote, self.repository.index.conversations, self.quarantine,
                self.exclusions, partial_listing=self.effective_listing == "recent" or self.partial_full_listing)
            if not listing_rate_limited:
                self._log_plan(plan)

            pending = [i for i in plan
                       if i.action in (SyncAction.FETCH_FULL, SyncAction.FETCH_FILES_ONLY)]
            for item in plan:
                if item.action == SyncAction.MISSING_REMOTE:
                    stats.missing_remote += 1
                elif item.action == SyncAction.QUARANTINED:
                    stats.quarantined_skipped += 1
                elif item.action == SyncAction.EXCLUDED:
                    stats.excluded_skipped += 1
                elif item.action == SyncAction.SKIP:
                    stats.unchanged += 1

            # Hauptschleife mit optionalen Wartezyklen.
            while pending:
                cycle += 1
                if cycle > 1:
                    self.progress("--- Zyklus %d: %d Conversations offen ---" % (cycle, len(pending)))
                try:
                    remaining = self._process_items(pending, stats, cycle, len(pending))
                except RateLimitReached as hit:
                    # Nur die noch NICHT abgearbeiteten Eintraege wiederholen.
                    remaining = hit.remaining
                    wait = self.rate_limit_wait_minutes
                    cycles_exhausted = (
                        self.max_rate_limit_cycles and cycle >= self.max_rate_limit_cycles
                    )
                    if wait <= 0 or cycles_exhausted:
                        self._emit_rate_limit_block(stats, hit.stage, hit.conversation_id, 0)
                        if cycles_exhausted:
                            self.progress("Maximale Anzahl Wartezyklen erreicht (%d)."
                                          % self.max_rate_limit_cycles)
                        self.progress("Lauf wird regulaer beendet. %d Conversations bleiben offen."
                                      % len(remaining))
                        fetch_rate_limited = True
                        open_after_limit = len(remaining)
                        break
                    self._emit_rate_limit_block(stats, hit.stage, hit.conversation_id, wait)
                    stats.rate_limit_wait_seconds += wait * 60
                    self.sleep(wait * 60)
                    pending = remaining
                    continue
                pending = remaining

            if not listing_rate_limited and not fetch_rate_limited:
                # Nach einem Rate-Limit keine weiteren Requests (Grenzpruefung
                # und Quarantaene-Review wuerden sofort wieder abrufen).
                self._verify_boundary(remote, plan, stats)
                self._review_quarantine(stats)

        except KeyboardInterrupt:
            # Im Wartemodus laeuft ein Lauf stundenlang; ein Abbruch durch den
            # Nutzer ist dort der Normalfall und muss einen auswertbaren
            # Bericht hinterlassen. Bereits committete Daten bleiben gueltig.
            aborted = True
            abort_stage = "interrupted"
            abort_reason = "Vom Nutzer abgebrochen (Strg+C)"
            self.progress("")
            self.progress("Abbruch durch Nutzer. Bereits gespeicherte Daten bleiben erhalten.")
        except SyncAbort as exc:
            aborted = True
            abort_reason = exc.reason
            abort_stage = exc.stage
            self.progress(f"SYNC ABGEBROCHEN ({exc.stage}): {exc.reason}")
        except Exception as exc:
            aborted = True
            abort_stage = "bootstrap_or_listing"
            abort_reason = compact_error_text(exc)
            stats.errors.append({"stage": abort_stage, "error": abort_reason})
            self.progress(f"SYNC ABGEBROCHEN ({abort_stage}): {abort_reason}")

        if self.quarantine.enabled:
            self.quarantine.save()
        settle = getattr(self.repository.index, "settle_lost", None)
        if callable(settle):
            try:
                settle()                     # wieder geladene aus der Verlustliste streichen
            except OSError:
                pass

        # Fuer eine automatische Fortsetzung: Lauf endete regulaer am Rate-Limit
        # und es ist noch Arbeit offen (beim Listing-Limit ist die Menge unbekannt).
        self._rate_limit_stop = {
            "stopped": bool((fetch_rate_limited or listing_rate_limited) and not aborted),
            "stage": "listing" if listing_rate_limited else ("fetch" if fetch_rate_limited else None),
            "open_conversations": open_after_limit,
            "estimated_full_at": (stats.rate_limit_events[-1]["estimated_full_at"]
                                  if stats.rate_limit_events else None),
        }
        manifest = self._build_manifest(started, stats, aborted, abort_stage, abort_reason, plan, cycle)
        run_path = self.write_manifest(manifest) if write_manifest else None
        if run_path is None:
            manifest["run_manifest"] = None
        self._log_summary(stats, aborted, run_path)
        return manifest

    def write_manifest(self, manifest: dict[str, Any]) -> Path:
        """Schreibt den ausfuehrlichen Laufbericht (Schema 3) atomar."""
        runs_dir = getattr(self.repository, "runs_dir", self.repository.root / "runs")
        runs_dir.mkdir(parents=True, exist_ok=True)
        staging_runs = getattr(self.repository, "staging_runs",
                               self.repository.root / ".staging" / "runs")
        run_path = runs_dir / f"sync_{manifest['finished_at'].replace(':','').replace('-','')}.json"
        manifest["run_manifest"] = str(run_path)
        atomic_write_json(run_path, manifest, staging_dir=staging_runs)
        return run_path

    # ------------------------------------------------------------------
    def _log_plan(self, plan: list[Any]) -> None:
        counts: dict[str, int] = {}
        for item in plan:
            counts[item.action.name] = counts.get(item.action.name, 0) + 1
        self.progress("Sync-Plan: " + ", ".join(
            "%d %s" % (n, name) for name, n in sorted(counts.items())))
        self.progress(
            "Reihenfolge: neue Conversations zuerst, danach geaenderte, "
            "unvollstaendige und zuletzt reine Datei-Nachlaeufe."
        )
        if self.fetch_files:
            self.progress("Dateien werden unmittelbar nach der jeweiligen Conversation geladen.")

    def _process_items(self, items: list[Any], stats: SyncStats,
                        cycle: int, total: int) -> list[Any]:
        """Arbeitet den Plan ab. Gibt die noch offenen Eintraege zurueck."""
        for position, item in enumerate(items, start=1):
            if self.quarantine.is_quarantined("conversation", item.conversation_id):
                stats.quarantined_skipped += 1
                continue
            label = "[Zyklus %d] [%d/%d]" % (cycle, position, total) if cycle > 1 \
                else "[%d/%d]" % (position, total)
            try:
                if item.action == SyncAction.FETCH_FILES_ONLY:
                    self.progress("%s FILES %s (%s)" % (label, item.conversation_id, item.reason))
                    self._files_only(item, stats)
                    stats.files_only_runs += 1
                else:
                    self.progress("%s FETCH %s (%s)" % (label, item.conversation_id, item.reason or "changed"))
                    self._fetch_and_commit(item, stats, label)
            except RateLimitReached as hit:
                # Der blockierte Eintrag wurde nicht committet und muss deshalb
                # erneut versucht werden; alles davor ist fertig.
                hit.remaining = items[position - 1:]
                raise
            except SyncAbort:
                raise
            except Exception as exc:
                stats.fetch_failed += 1
                self._items["failed"].append({"id": item.conversation_id, "kind": "conversation",
                                              "action": item.reason,
                                              "error": compact_error_text(exc)})
                self._record_api_error(stats, stage="fetch_or_commit", exc=exc,
                                        extra={"conversation_id": item.conversation_id},
                                        core_request=True,
                                        identifier=item.conversation_id,
                                        quarantine_kind="conversation")
        return []

    def _fetch_and_commit(self, item: Any, stats: SyncStats, label: str,
                          original: dict[str, Any] | None = None) -> None:
        """Laedt und speichert eine Conversation. ``original`` = bereits
        geladene Detailantwort (dann kein erneuter Abruf)."""
        if item.reason == "new":
            stats.new += 1
        else:
            stats.changed += 1
        try:
            fetched, envelope = self._fetch_envelope(item, original)
        except MemoryError:
            # ERR-SYNC-MEMORY (Lauf 20260924T214820Z, 2x, spaeter fehlerfrei geladen): Speicher
            # aufraeumen und genau einmal wiederholen. Noch vor dem Commit, also ohne Doppelzaehlung.
            import gc
            gc.collect()
            self.progress("%s Speicher knapp (MemoryError) bei %s -- ein neuer Versuch nach dem Aufraeumen"
                          % (label, item.conversation_id))
            fetched, envelope = self._fetch_envelope(item, original)
        path = self.repository.commit(envelope)
        stats.fetched += 1
        self._items["fetched"].append({
            "id": item.conversation_id, "kind": "conversation", "action": item.reason,
            "title": str((item.remote_summary or {}).get("title") or "")[:120],
            "update_time": (item.remote_summary or {}).get("update_time"),
        })
        self.progress("%s RAW COMMIT %s (%d Nodes, %d File-Refs)"
                      % (label, item.conversation_id, fetched.validation.node_count,
                         len(envelope.get("file_references", []))))

        if self.fetch_files:
            gizmo_id = (item.remote_summary or {}).get("gizmo_id")
            self._materialize_for(item.conversation_id, envelope.get("file_references", []),
                                   stats, label, gizmo_id=gizmo_id)
            # Nach dem Dateilauf den Vollstaendigkeitsstand nachziehen.
            self._refresh_completeness(item.conversation_id)

    def _fetch_envelope(self, item: Any, original: dict[str, Any] | None) -> tuple[Any, dict[str, Any]]:
        """Conversation laden (oder aus ``original`` aufbauen) und den Umschlag erzeugen, ohne zu speichern."""
        try:
            fetched = (self.fetcher.build(item.conversation_id, original) if original is not None
                       else self.fetcher.fetch(item.conversation_id))
        except Exception as exc:
            if self._is_rate_limit(exc):
                raise RateLimitReached("fetch_or_commit", item.conversation_id) from None
            raise
        self._run_had_success = True
        envelope = build_envelope(item.remote_summary or {}, fetched,
                                  library=self.library, quarantine=self.quarantine)
        return fetched, envelope

    def _files_only(self, item: Any, stats: SyncStats) -> None:
        envelope = self.repository.load(item.conversation_id)
        if not envelope:
            return
        gizmo_id = (envelope.get("remote_summary") or {}).get("gizmo_id")
        self._materialize_for(item.conversation_id, envelope.get("file_references", []),
                               stats, "[FILES]", gizmo_id=gizmo_id)
        self._refresh_completeness(item.conversation_id)

    def _materialize_for(self, conversation_id: str, refs: Any,
                          stats: SyncStats, label: str,
                          gizmo_id: str | None = None) -> None:
        if not isinstance(refs, list):
            return
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            fid = ref.get("id")
            if not isinstance(fid, str) or not fid.startswith(("file_", "file-")) or                     fid.startswith("file-inline-"):
                continue
            if self.quarantine.is_quarantined("file", fid):
                stats.quarantined_skipped += 1
                continue
            if self.exclusions.is_excluded("file", fid):
                stats.excluded_skipped += 1
                continue
            # Zuordnung auch dann festhalten, wenn die Datei bereits vorliegt
            # oder in diesem Lauf schon einmal gesehen wurde: eine Datei kann in
            # mehreren Conversations/Teilgespraechen referenziert werden.
            self.library.register_reference(ref, conversation_id=conversation_id)
            if fid in self._seen_file_ids:
                continue
            self._seen_file_ids.add(fid)
            if self.library.is_materialized(fid):
                stats.files_cached += 1
                continue
            try:
                result = self.library.materialize(ref, self.file_api,
                                                  conversation_id=conversation_id,
                                                  gizmo_id=gizmo_id)
                if result.get("state") == "MATERIALIZED":
                    if result.get("cached"):
                        stats.files_cached += 1
                    else:
                        stats.files_materialized += 1
                        self._items["files"].append({"id": fid, "kind": "file",
                                                     "conversation_id": conversation_id,
                                                     "bytes": result.get("bytes", 0)})
                        self._run_had_success = True
                        self.progress("%s FILE %s (%s Bytes)"
                                      % (label, fid, result.get("bytes", 0)))
            except Exception as exc:
                if self._is_rate_limit(exc):
                    raise RateLimitReached("file_materialization", conversation_id) from None
                status = exc.status if isinstance(exc, ApiError) else None
                if status == 404:
                    # Endgueltige Antwort, keine Stoerung: alte Anhaenge laufen
                    # serverseitig ab. Einmal vermerken, danach nie wieder
                    # anfragen -- sonst bliebe die Conversation dauerhaft
                    # dateiunvollstaendig und wuerde jeden Lauf erneut Budget
                    # kosten, ohne jede Aussicht auf Erfolg.
                    detail = RateLimitError.detail_of(exc.payload) if isinstance(exc, ApiError) else None
                    self.library.mark_unavailable(ref, status=status, detail=detail,
                                                  conversation_id=conversation_id)
                    stats.files_unavailable += 1
                    self.progress("%s FILE %s nicht mehr verfuegbar (HTTP 404) -- vermerkt"
                                  % (label, fid))
                    continue
                stats.files_failed += 1
                self._record_file_error(stats, exc=exc, file_id=fid,
                                         conversation_id=conversation_id)

    def _refresh_completeness(self, conversation_id: str) -> None:
        """Aktualisiert files_complete/complete im gespeicherten Envelope."""
        path = self.repository.get_path(conversation_id)
        envelope = self.repository.load(conversation_id)
        if not path or not envelope:
            return
        acq = envelope.get("acquisition")
        if not isinstance(acq, dict):
            return
        if not refresh_acquisition_completeness(envelope, self.library, self.quarantine,
                                                self.exclusions):
            return
        # Gleiche Crash-Sicherung wie RawRepository.commit(): der Marker macht
        # einen Absturz zwischen Envelope-Schreiben und Index-Speichern
        # erkennbar und erzwingt beim naechsten Start einen Index-Rebuild.
        # Ohne ihn entstuende ein stiller Index-Drift, den nichts bemerkt.
        marker = self.repository.index.dirty_marker
        atomic_write_text(marker, conversation_id + "\n",
                           staging_dir=self.repository.index.dirty_staging)
        atomic_write_json(path, envelope, staging_dir=self.repository.staging)
        self.repository.index.refresh_one(path, envelope)
        self.repository.index.save()
        marker.unlink(missing_ok=True)

    @staticmethod
    def _content_fingerprint(raw: Any) -> tuple[Any, ...] | None:
        """Inhaltlicher Stand einer Conversation auf Turn-Ebene.

        Aktueller Knoten (letzter Turn), Menge aller Knoten-IDs (damit auch
        Turn-Anzahl) und ``update_time`` aus der Detailantwort. Bewusst kein
        Hash ueber das ganze JSON: fluechtige Felder wuerden sonst Fehlalarme
        erzeugen.
        """
        if not isinstance(raw, dict):
            return None
        mapping = raw.get("mapping") if isinstance(raw.get("mapping"), dict) else {}
        return (raw.get("current_node"), tuple(sorted(mapping)), raw.get("update_time"))

    def _verify_boundary(self, remote: dict[str, Any], plan: list[Any],
                         stats: SyncStats) -> None:
        """Grenzpruefung auf Turn-Ebene.

        Das Listing liefert nur Metadaten (``mapping``/``current_node`` sind
        dort ``null``); ob ``update_time`` als Aenderungskriterium traegt,
        laesst sich nur per Detailabruf belegen. Geprueft werden die als
        unveraendert eingestuften Conversations in Listing-Reihenfolge, also
        beginnend direkt an der Aenderungsgrenze -- so lange, bis
        ``recent_confirm_unchanged`` Conversations IN FOLGE inhaltlich
        unveraendert sind. Jede Abweichung wird sofort aus der bereits
        geladenen Detailantwort gespeichert (kein zweiter Abruf) und setzt die
        Folge zurueck; es wird dann einfach die naechste Conversation geprueft.

        Stimmt ``update_time`` (Normalfall), kostet das genau
        ``recent_confirm_unchanged`` Detailabrufe. Ende sonst durch Rate-Limit,
        ``verify_max_requests`` oder fehlende weitere Kandidaten.
        """
        required = self.recent_confirm_unchanged
        result: dict[str, Any] = {"enabled": self.verify_boundary, "required": required,
                                  "checked": 0, "matched": 0, "mismatches": 0,
                                  "consecutive_ok": 0, "confirmed": False,
                                  "requests": 0, "stopped": None, "checked_ids": []}
        self._verification = result
        if not self.verify_boundary:
            return
        skipped = {item.conversation_id: item for item in plan
                   if item.action == SyncAction.SKIP}
        candidates = [cid for cid in remote if cid in skipped]
        if not candidates:
            result["stopped"] = "no_candidates"
            return
        self.progress("Grenzpruefung: pruefe unveraenderte Conversations an der Aenderungsgrenze "
                      "auf Turn-Ebene, bis %d in Folge bestaetigt sind." % required)
        consecutive = 0
        for cid in candidates:
            if consecutive >= required:
                break
            if self.verify_max_requests and result["requests"] >= self.verify_max_requests:
                result["stopped"] = "max_requests"
                break
            local = self.repository.load(cid)
            if not local:
                continue
            result["requests"] += 1
            stats.verify_requests += 1
            try:
                original = self.conversation_api.get_conversation(cid)
            except Exception as exc:  # noqa: BLE001
                if self._is_rate_limit(exc):
                    result["stopped"] = "rate_limit"
                    self.progress("Grenzpruefung wegen Rate-Limit beendet.")
                    break
                # Nicht pruefbar -> die Folge gilt als unterbrochen.
                consecutive = 0
                self.progress("Grenzpruefung: %s nicht pruefbar (%s)." % (cid, compact_error_text(exc)))
                continue
            self._run_had_success = True
            result["checked"] += 1
            result["checked_ids"].append(cid)
            before = self._content_fingerprint(local.get("raw"))
            after = self._content_fingerprint(sanitize_reasoning_payload(original))
            if before == after:
                consecutive += 1
                result["matched"] += 1
                stats.verified_unchanged += 1
                continue
            consecutive = 0
            result["mismatches"] += 1
            stats.verify_mismatches += 1
            stats.unchanged -= 1  # war als SKIP gezaehlt, wird jetzt gespeichert
            stats.verify_events.append({
                "at": now_iso(), "conversation_id": cid,
                "local_current_node": before[0] if before else None,
                "remote_current_node": after[0] if after else None,
                "local_nodes": len(before[1]) if before else None,
                "remote_nodes": len(after[1]) if after else None,
                "local_update_time": before[2] if before else None,
                "remote_update_time": after[2] if after else None,
            })
            self.progress("WARNUNG Grenzpruefung: %s ist inhaltlich geaendert, obwohl das Listing "
                          "keine Aenderung zeigte -- wird gespeichert, naechste Conversation "
                          "wird zusaetzlich geprueft." % cid)
            item = skipped[cid]
            item.action = SyncAction.FETCH_FULL
            item.reason = "verify_mismatch"
            try:
                self._fetch_and_commit(item, stats, "[GRENZPRUEFUNG]", original=original)
            except RateLimitReached:
                result["stopped"] = "rate_limit"
                self.progress("Grenzpruefung wegen Rate-Limit beendet.")
                break
            except SyncAbort:
                raise
            except Exception as exc:  # noqa: BLE001
                stats.fetch_failed += 1
                self._record_api_error(stats, stage="verify_refetch", exc=exc,
                                       extra={"conversation_id": cid}, core_request=True)
        result["consecutive_ok"] = consecutive
        result["confirmed"] = consecutive >= required
        if not result["confirmed"] and result["stopped"] is None:
            result["stopped"] = "candidates_exhausted"
        if result["mismatches"]:
            self.progress("Grenzpruefung: %d Abweichung(en) gefunden und gespeichert; "
                          "Grenze %s." % (result["mismatches"],
                                          "abgesichert" if result["confirmed"] else "NICHT abgesichert"))

    def _review_quarantine(self, stats: SyncStats) -> None:
        """Erneuter Versuch faelliger Eintraege -- bewusst am ENDE des Laufs,
        damit ein langlaufender Timeout nie den Fortschritt blockiert."""
        if not self.quarantine.enabled:
            return
        due = self.quarantine.due_for_review("conversation")
        if not due:
            return
        capped = due[:MAX_QUARANTINE_REVIEWS_PER_RUN]
        self.progress("Quarantaene-Review: %d faellig, davon %d in diesem Lauf geprueft."
                      % (len(due), len(capped)))
        for cid in capped:
            try:
                self.fetcher.fetch(cid)
            except Exception as exc:
                if self._is_rate_limit(exc):
                    self.progress("Quarantaene-Review wegen Rate-Limit abgebrochen.")
                    return
                self.progress("Quarantaene-Review: %s weiterhin fehlerhaft." % cid)
                continue
            self.quarantine.clear("conversation", cid)
            stats.quarantine_reviews += 1
            stats.quarantine_events.append({
                "at": now_iso(), "action": "released", "kind": "conversation", "id": cid,
            })
            self.progress("Quarantaene aufgehoben: %s (Abruf wieder moeglich)." % cid)

    # ------------------------------------------------------------------
    def _record_file_error(self, stats: SyncStats, *, exc: Exception, file_id: str,
                            conversation_id: str) -> None:
        """Dateifehler laufen in ein eigenes, groesszuegigeres Budget.

        Ein Chat mit mehreren defekten Anhaengen darf nicht den gesamten Lauf
        beenden, solange die Conversations selbst sauber laden. Mit dem
        gemeinsamen 5er-Budget waere ein Lauf mit aktivierten Dateien nach
        wenigen Chats vorbei.
        """
        self._file_error_count += 1
        error_text = compact_error_text(exc)
        row: dict[str, Any] = {
            "file_id": file_id, "conversation_id": conversation_id,
            "stage": "file_materialization", "error": error_text,
            "file_error_number": self._file_error_count,
        }
        status = None
        detail = None
        if isinstance(exc, ApiError):
            status = exc.status
            row["http_status"] = status
            row["endpoint"] = exc.endpoint
            detail = RateLimitError.detail_of(exc.payload)
        stats.errors.append(row)
        self.progress("FILE-ERROR %d/%d %s: %s"
                      % (self._file_error_count, self.max_file_errors_per_run,
                         file_id, error_text))

        if isinstance(exc, ApiError) and not isinstance(exc, ApiTransportClosedError):
            newly = self.quarantine.record_failure(
                "file", file_id, status=status, detail=detail, run_id=self._run_id,
                endpoint=exc.endpoint, server_responded=status is not None,
                run_had_success=self._run_had_success)
            if newly:
                stats.quarantined_new += 1
                stats.quarantine_events.append({
                    "at": now_iso(), "action": "quarantined", "kind": "file",
                    "id": file_id, "http_status": status, "detail": detail})

        if isinstance(exc, ApiTransportClosedError):
            raise SyncAbort(
                "Browser/CDP request context is closed; further API requests would only fail",
                stage="file_materialization", fatal=True)
        if self._file_error_count >= self.max_file_errors_per_run:
            raise SyncAbort(
                f"File error budget exhausted ({self._file_error_count}/{self.max_file_errors_per_run})",
                stage="file_materialization")

    def _record_api_error(self, stats: SyncStats, *, stage: str, exc: Exception,
                           extra: dict[str, Any] | None = None, core_request: bool,
                           identifier: str | None = None,
                           quarantine_kind: str | None = None) -> None:
        self._api_error_count += 1
        error_text = compact_error_text(exc)
        row = dict(extra or {})
        row.update({"stage": stage, "error": error_text, "error_number": self._api_error_count})
        status = None
        detail = None
        if isinstance(exc, ApiError):
            status = exc.status
            row["http_status"] = status
            row["endpoint"] = exc.endpoint
            detail = RateLimitError.detail_of(exc.payload)
        stats.errors.append(row)
        self.progress(f"ERROR {self._api_error_count}/{self.max_errors_per_run} [{stage}] {error_text}")

        # Quarantaene nur bei echter Serverantwort und nur, wenn im selben Lauf
        # nachweislich etwas funktioniert hat.
        if quarantine_kind and identifier and isinstance(exc, ApiError) \
                and not isinstance(exc, ApiTransportClosedError):
            newly = self.quarantine.record_failure(
                quarantine_kind, identifier, status=status, detail=detail,
                run_id=self._run_id, endpoint=exc.endpoint,
                server_responded=status is not None,
                run_had_success=self._run_had_success,
            )
            if newly:
                stats.quarantined_new += 1
                stats.quarantine_events.append({
                    "at": now_iso(), "action": "quarantined", "kind": quarantine_kind,
                    "id": identifier, "http_status": status, "detail": detail,
                })
                self.progress("[QUARANTAENE] %s %s dauerhaft fehlerhaft -- kuenftige Laeufe "
                              "ueberspringen diesen Eintrag." % (quarantine_kind, identifier))

        if isinstance(exc, ApiTransportClosedError):
            raise SyncAbort("Browser/CDP request context is closed; further API requests would only fail",
                             stage=stage, fatal=True)
        if core_request and isinstance(exc, ApiError) and exc.status in {401, 403}:
            raise SyncAbort(f"Core API request returned HTTP {exc.status}; authentication/session must be revalidated",
                             stage=stage, fatal=True)
        if not self.continue_on_error:
            raise SyncAbort("continue_on_error=false: first API error stops the run", stage=stage)
        if self._api_error_count >= self.max_errors_per_run:
            raise SyncAbort(f"API error budget exhausted ({self._api_error_count}/{self.max_errors_per_run})",
                             stage=stage)

    def _build_manifest(self, started: str, stats: SyncStats, aborted: bool,
                         abort_stage: str | None, abort_reason: str | None,
                         plan: list[Any], cycles: int) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in plan:
            counts[item.action.name] = counts.get(item.action.name, 0) + 1
        return {
            "schema_version": 3,
            "started_at": started,
            "finished_at": now_iso(),
            "aborted": aborted,
            "abort_stage": abort_stage,
            "abort_reason": abort_reason,
            "error_budget": {
                "max_errors_per_run": self.max_errors_per_run,
                "api_errors_seen": self._api_error_count,
                "max_file_errors_per_run": self.max_file_errors_per_run,
                "file_errors_seen": self._file_error_count,
            },
            "rate_limit": {
                "wait_minutes": self.rate_limit_wait_minutes,
                "cycles": cycles,
                "hits": stats.rate_limit_hits,
                "waited_seconds": stats.rate_limit_wait_seconds,
                "events": stats.rate_limit_events,
                **getattr(self, "_rate_limit_stop", {"stopped": False}),
            },
            "quarantine": {
                **self.quarantine.summary(),
                "newly_quarantined": stats.quarantined_new,
                "skipped": stats.quarantined_skipped,
                "released": stats.quarantine_reviews,
                "events": stats.quarantine_events,
            },
            "exclusions": {
                **self.exclusions.summary(),
                "skipped": stats.excluded_skipped,
            },
            "listing": dict(self._listing_info),
            "verification": dict(self._verification),
            "items": {k: list(v) for k, v in self._items.items()},
            "stats": asdict(stats),
            "plan_counts": counts,
        }

    def _log_summary(self, stats: SyncStats, aborted: bool, run_path: Path | None) -> None:
        prefix = "Sync beendet (abgebrochen)" if aborted else "Sync abgeschlossen"
        report = f"Run-Report: {run_path}" if run_path is not None else "Run-Report: (folgt separat)"
        self.progress(
            f"{prefix}: {stats.fetched} Conversations committed, "
            f"{stats.files_materialized} Files neu, {stats.files_cached} bereits vorhanden, "
            f"{stats.fetch_failed} Fetch-Fehler, {stats.files_failed} File-Fehler, "
            f"{stats.rate_limit_hits} Rate-Limit-Treffer, "
            f"{stats.quarantined_skipped} uebersprungen (Quarantaene), "
            f"{stats.excluded_skipped} uebersprungen (manuelle Ausnahmen), "
            f"Grenzpruefung {stats.verified_unchanged} bestaetigt / "
            f"{stats.verify_mismatches} Abweichungen ({stats.verify_requests} Detailabrufe). "
            f"{report}"
        )
