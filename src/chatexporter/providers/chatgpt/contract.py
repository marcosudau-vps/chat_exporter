from __future__ import annotations

"""ChatGPT-Provider: die fuenf Vertragsfunktionen fuer die Quelle ``chatgpt``.

Vertrag (identisch fuer alle Provider, siehe docs/PROVIDER_CONTRACT.md):

- ``update(cfg, **optionen)``             -> Ergebnis ``{source, ok, stats, errors, ...}``
- ``recreate_index(cfg)``                 -> Index-Fragment (schreibt den Gesamtindex NICHT)
- ``check_storage_health(cfg, deep=)``    -> Pruefbericht ``{ok, ...}``
- ``cleanup_storage(cfg, dry_run=)``      -> Bereinigungsbericht
- ``state_n_stats(cfg)``                  -> Momentaufnahme

``cfg`` ist entweder eine :class:`AppConfig` (Direktaufruf) oder das
Vertrags-Mapping des Raw Session Updaters (``config_file``, ``raw_root``, ``runtime_root``,
...). Der Provider liest seine eigenen Einstellungen dann selbst aus
``config_file`` -- er haengt nicht vom Updater-Code ab.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from chatexporter.providers.chatgpt.api.client import ApiClient, RequestCounter
from chatexporter.providers.chatgpt.api.conversations import ConversationApi
from chatexporter.providers.chatgpt.api.files import FileApi
from chatexporter.providers.chatgpt.auth.browser_setup import open_browser
from chatexporter.providers.chatgpt.common.io import atomic_write_json
from chatexporter.providers.chatgpt.common.time import now_iso
from chatexporter.providers.chatgpt.config.loader import load_config
from chatexporter.providers.chatgpt.config.models import AppConfig
from chatexporter.providers.chatgpt.storage.integrity import verify_store
from chatexporter.providers.chatgpt.storage.layout import StoreLayout, resolve_store_layout
from chatexporter.providers.chatgpt.storage.quarantine import QuarantineStore
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.sync.exclusions import ManualExclusions
from chatexporter.providers.chatgpt.sync.orchestrator import SyncOrchestrator

SOURCE = "chatgpt"
CONTRACT_METHODS = ("update", "recreate_index", "check_storage_health",
                    "cleanup_storage", "state_n_stats")


# -- Konfiguration ------------------------------------------------------------

def app_config(cfg: AppConfig | Mapping[str, Any]) -> AppConfig:
    """AppConfig aus Direktaufruf oder Vertrags-Mapping des Raw Session Updaters.

    Im Mapping gewinnen die vom Raw Session Updater aufgeloesten Ablagepfade; alle
    ChatGPT-Einstellungen (Browser, API, Sync, Export) kommen aus
    ``config_file``.
    """
    if isinstance(cfg, AppConfig):
        return cfg
    if not isinstance(cfg, Mapping):
        raise TypeError("AppConfig oder Vertrags-Mapping erwartet")
    config_file = cfg.get("config_file")
    overrides = {key: cfg.get(key) for key in ("raw_root", "runtime_root", "status_root")}
    return load_config(Path(config_file) if config_file else None, overrides=overrides)


def open_layout(cfg: AppConfig) -> StoreLayout:
    return resolve_store_layout(cfg.storage, SOURCE)


def open_repository(cfg: AppConfig, layout: StoreLayout | None = None) -> tuple[RawRepository, StoreLayout]:
    layout = layout or open_layout(cfg)
    repo = RawRepository(
        layout.source_root, layout.status_root,
        index_path=layout.index_path, runs_dir=layout.runs_dir,
        staging_root=layout.staging_root, source=SOURCE,
    )
    return repo, layout


def open_quarantine(cfg: AppConfig, layout: StoreLayout) -> QuarantineStore:
    return QuarantineStore(layout.source_root, cfg.sync.quarantine,
                           path=layout.quarantine_path, staging=layout.staging_root)


def open_exclusions(cfg: AppConfig) -> ManualExclusions:
    return ManualExclusions(cfg.sync.manual_exclusions.conversations,
                            cfg.sync.manual_exclusions.files)


# -- update -------------------------------------------------------------------

def session_hint(identity: Any) -> str:
    """Welches Konto? Fuer die Konsole nur maskiert (nie volle E-Mail, nie Name)."""
    from chatexporter.providers.chatgpt.common.redaction import mask_email
    email = getattr(identity, "email", None)
    return mask_email(email) if email else "validierte Sitzung"


def reauthenticator(cfg: AppConfig, session: Any, *, interactive: bool, counter: Any = None,
                    say: Callable[[str], None] = lambda _m: None,
                    broker_factory: Callable[[], Any] | None = None) -> Callable[[], str]:
    """Neuanmeldung mitten im Lauf (fuer ``ApiClient(reauthenticate=...)``).

    Bei HTTP 401 wird die Sitzung im selben Browser neu geprueft (frischer Token aus
    ``/api/auth/session``); fehlt sie, folgt die automatische Anmeldung und – nur mit
    Interaktion – die Anmeldung von Hand. Der Broker entsteht erst beim ersten Bedarf.
    """
    broker: list[Any] = []

    def reauthenticate() -> str:
        if not broker:
            from chatexporter.providers.chatgpt.auth.browser_setup import auth_broker
            broker.append(broker_factory() if broker_factory
                          else auth_broker(cfg, session, counter=counter, say=say))
        say("ChatGPT meldet HTTP 401 (Sitzung abgelaufen) – Anmeldung wird erneuert ...")
        fresh = broker[0].acquire(interactive=interactive)
        say("Anmeldung erneuert, der Lauf geht weiter.")
        return fresh.access_token

    return reauthenticate


def run_sync(cfg: AppConfig, *, no_files: bool = False,
             non_interactive: bool = False, listing_mode: str | None = None,
             write_manifest: bool = False,
             progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Laedt neue/geaenderte Conversations + Dateien.

    Gibt den ausfuehrlichen ChatGPT-Laufbericht (Schema 3) zurueck.
    ``listing_mode`` (CLI) ueberschreibt ``sync.listing_mode`` aus der Config.
    """
    fetch_files = cfg.sync.fetch_files and not no_files
    say = progress or (lambda _m: None)
    # Zaehlt JEDE an ChatGPT gesendete Anfrage dieses Laufs (inkl. Anmeldung).
    counter = RequestCounter()
    dev = cfg.dev_mode
    if dev:
        from chatexporter.config.dev import DEV, banner
        DEV = cfg.dev_settings or DEV  # noqa: N806  eingestellte Werte (dev.*)
        say(banner(DEV))
    # Browser und Profil bestimmen (fest konfiguriert oder automatische Suche),
    # verbinden und ChatGPT-Anmeldung pruefen; jeder Versuch wird protokolliert.
    interactive = cfg.browser.interactive_reauth and not non_interactive
    edge, auth, browser_choice = open_browser(cfg, interactive=interactive, say=say, counter=counter)
    try:
        say(f"ChatGPT-Sitzung validiert: {session_hint(auth.identity)}")
        client = ApiClient(auth.context, auth.access_token, base_url=cfg.api.base_url,
                           timeout_ms=cfg.api.request_timeout_ms, counter=counter,
                           reauthenticate=reauthenticator(cfg, edge, interactive=interactive,
                                                          counter=counter, say=say))
        repo, layout = open_repository(cfg)
        say(f"RawStorage bereit: {repo.root} ({len(repo.index.conversations)} Conversations im Index)")
        conversation_api = ConversationApi(client)
        if dev:
            conversation_api.max_pages = DEV.listing_max_pages
            conversation_api.fetch_budget = DEV.conversation_fetches or None
        orchestrator = SyncOrchestrator(
            conversation_api=conversation_api,
            file_api=FileApi(client),
            repository=repo,
            listing_limit=cfg.sync.listing_limit,
            listing_mode=listing_mode or cfg.sync.listing_mode,
            recent_max_pages=min(cfg.sync.recent_max_pages, DEV.listing_max_pages) if dev
            else cfg.sync.recent_max_pages,
            recent_confirm_unchanged=cfg.sync.recent_confirm_unchanged,
            verify_boundary=cfg.sync.verify_boundary,
            verify_max_requests=cfg.sync.verify_max_requests,
            fetch_files=fetch_files,
            fetch_textdocs=cfg.sync.fetch_textdocs,
            retry_pending_files=cfg.sync.retry_pending_files,
            continue_on_error=cfg.sync.continue_on_error,
            max_errors_per_run=cfg.sync.max_errors_per_run,
            max_file_errors_per_run=cfg.sync.max_file_errors_per_run,
            rate_limit_wait_minutes=min(cfg.sync.rate_limit_wait_minutes, DEV.rate_limit_wait_minutes) if dev
            else cfg.sync.rate_limit_wait_minutes,
            max_rate_limit_cycles=cfg.sync.max_rate_limit_cycles,
            quarantine=open_quarantine(cfg, layout),
            exclusions=open_exclusions(cfg),
            progress=say,
            refill_minutes=DEV.refill_minutes if dev else None,
            partial_full_listing=dev,
        )
        # Laufbericht erst nach dem Lauf schreiben, damit die Anfragezaehlung
        # vollstaendig darin steht.
        report = orchestrator.run(write_manifest=False)
        report["requests"] = counter.as_dict()
        report["browser"] = browser_choice.as_dict()
        report["reauth"] = list(client.reauth_events)
        report["dev_mode"] = dev
        say(f"Anfragen an ChatGPT in diesem Lauf: {counter.total} "
            f"({', '.join(f'{k} {v}' for k, v in report['requests']['by_category'].items()) or '-'}).")
        if write_manifest:
            orchestrator.write_manifest(report)
        return report
    finally:
        edge.close()


def contract_stats(run_report: dict[str, Any]) -> dict[str, Any]:
    """Uebersetzt den ChatGPT-Laufbericht in die Vertragszaehler (1:1)."""
    stats = run_report.get("stats") or {}
    sessions = {
        "sessions_total": stats.get("remote_total", 0),
        "sessions_new": stats.get("new", 0),
        "sessions_changed": stats.get("changed", 0),
        "sessions_unchanged": stats.get("unchanged", 0),
        "sessions_missing_remote": stats.get("missing_remote", 0),
        "sessions_fetched": stats.get("fetched", 0),
        "sessions_failed": stats.get("fetch_failed", 0),
    }
    files = {k: stats.get(k, 0) for k in (
        "files_materialized", "files_cached", "files_failed",
        "files_unavailable", "file_refs_queued", "files_only_runs")}
    extra = {
        "quarantined_skipped": stats.get("quarantined_skipped", 0),
        "quarantined_new": stats.get("quarantined_new", 0),
        "excluded_skipped": stats.get("excluded_skipped", 0),
        "rate_limit_hits": stats.get("rate_limit_hits", 0),
        "verified_unchanged": stats.get("verified_unchanged", 0),
        "verify_mismatches": stats.get("verify_mismatches", 0),
        "verify_requests": stats.get("verify_requests", 0),
        # An ChatGPT gesendete Anfragen dieses Laufs (alle Kategorien).
        "requests_total": int((run_report.get("requests") or {}).get("total", 0) or 0),
    }
    return {**sessions, **files, **extra}


def contract_result(run_report: dict[str, Any]) -> dict[str, Any]:
    """Vertragsergebnis aus dem ausfuehrlichen Laufbericht."""
    stats = run_report.get("stats") or {}
    aborted = bool(run_report.get("aborted", False))
    if aborted:
        exit_code = 2
    elif stats.get("fetch_failed") or stats.get("files_failed"):
        exit_code = 1
    else:
        exit_code = 0
    return {
        "source": SOURCE,
        "ok": not aborted,
        "started_at": run_report.get("started_at"),
        "finished_at": run_report.get("finished_at"),
        "stats": contract_stats(run_report),
        "errors": list(stats.get("errors", [])),
        "detail": {
            "aborted": aborted,
            "abort_stage": run_report.get("abort_stage"),
            "abort_reason": run_report.get("abort_reason"),
            "listing": run_report.get("listing"),
            "rate_limit": {k: (run_report.get("rate_limit") or {}).get(k)
                           for k in ("hits", "cycles", "waited_seconds", "stopped",
                                     "open_conversations", "estimated_full_at")},
            "plan_counts": run_report.get("plan_counts"),
            "verification": run_report.get("verification"),
            "requests": run_report.get("requests"),
            "browser": run_report.get("browser"),
            "dev_mode": bool(run_report.get("dev_mode")),
        },
        "items": run_report.get("items") or {"fetched": [], "files": [], "failed": []},
        "exit_code": exit_code,
    }


def update(cfg: AppConfig | Mapping[str, Any], *, no_files: bool = False,
           non_interactive: bool = False,
           listing_mode: str | None = None,
           progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Vertragsfunktion: Quelle aktualisieren, Vertragsergebnis liefern."""
    report = run_sync(app_config(cfg), no_files=no_files,
                      non_interactive=non_interactive, listing_mode=listing_mode,
                      progress=progress)
    return contract_result(report)


# -- recreate_index (Fragment) --------------------------------------------------

def recreate_index(cfg: AppConfig | Mapping[str, Any]) -> dict[str, Any]:
    """Baut das deterministische Index-Fragment; schreibt den Gesamtindex NICHT."""
    repo, layout = open_repository(app_config(cfg))
    fragment = repo.index.build_fragment()
    staging = layout.staging_root / "index"
    staging.mkdir(parents=True, exist_ok=True)
    atomic_write_json(staging / f"{SOURCE}.fragment.json", fragment, staging_dir=staging)
    return fragment


# -- check_storage_health ---------------------------------------------------------

def check_storage_health(cfg: AppConfig | Mapping[str, Any], *, deep: bool = False) -> dict[str, Any]:
    """Read-only Konsistenz-/Integritaetspruefung dieser Quelle."""
    app = app_config(cfg)
    layout = open_layout(app)
    report = verify_store(
        layout.store_root,
        layout.status_root,
        deep=deep,
        exclusions=open_exclusions(app),
        quarantine=open_quarantine(app, layout),
        source=SOURCE,
        runtime_root=layout.runtime_root,
        index_path=layout.index_path,
    )
    return report.as_dict()


# -- cleanup_storage --------------------------------------------------------------

def cleanup_storage(cfg: AppConfig | Mapping[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    """Entfernt nur definierte Reste (leere Library-Verzeichnisse, Staging-`.tmp`).

    Niemals Quelldaten. Mit ``dry_run`` wird nur gezaehlt/berichtet.
    """
    layout = open_layout(app_config(cfg))
    removed_dirs: list[str] = []
    removed_tmp: list[str] = []
    for base in (layout.source_root / "library" / "files",
                 layout.source_root / "library" / "audio"):
        if not base.exists():
            continue
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            if any(d.glob("content.*")) or (d / "metadata.json").exists():
                continue
            removed_dirs.append(d.relative_to(layout.store_root).as_posix())
            if not dry_run:
                try:
                    d.rmdir()
                except OSError:
                    removed_dirs.pop()
    if layout.staging_root.exists():
        for tmp in sorted(layout.staging_root.rglob("*.tmp")):
            removed_tmp.append(tmp.relative_to(layout.store_root.parent).as_posix()
                               if tmp.is_relative_to(layout.store_root.parent)
                               else str(tmp))
            if not dry_run:
                try:
                    tmp.unlink()
                except OSError:
                    removed_tmp.pop()
    return {
        "source": SOURCE,
        "dry_run": dry_run,
        "empty_library_dirs_removed": len(removed_dirs),
        "staging_leftovers_removed": len(removed_tmp),
        "empty_library_dirs": removed_dirs,
        "staging_leftovers": removed_tmp,
    }


# -- state_n_stats ----------------------------------------------------------------

def state_n_stats(cfg: AppConfig | Mapping[str, Any]) -> dict[str, Any]:
    """Read-only Momentaufnahme dieser Quelle (kein Netz)."""
    repo, layout = open_repository(app_config(cfg))
    index = repo.index.conversations
    refs_total = sum(int(e.get("file_reference_count") or 0) for e in index.values())
    materialized = sum(int(e.get("file_materialized_count") or 0) for e in index.values())
    unavailable = sum(int(e.get("file_unavailable_count") or 0) for e in index.values())
    files_incomplete = sum(1 for e in index.values() if not e.get("files_complete", True))
    referenced_distinct = len(repo.library.file_index.files)
    unavailable_distinct = int(repo.library.status.summary().get("UNAVAILABLE", 0))
    materialized_distinct = 0
    for base in (repo.root / "library" / "files", repo.root / "library" / "audio"):
        if not base.exists():
            continue
        for d in base.iterdir():
            if d.is_dir() and (d / "metadata.json").exists() and any(d.glob("content.*")):
                materialized_distinct += 1
    return {
        "source": SOURCE,
        "generated_at": now_iso(),
        "store_root": str(layout.store_root),
        "source_root": str(layout.source_root),
        "conversations": len(index),
        "sessions_total": len(index),
        "files_complete_false": files_incomplete,
        "file_references": refs_total,
        "files_materialized": materialized,
        "files_unavailable": unavailable,
        "files_referenced_distinct": referenced_distinct,
        "files_materialized_distinct": materialized_distinct,
        "files_unavailable_distinct": unavailable_distinct,
        "status_registry": repo.library.status.summary(),
        "index_coverage": repo.index.coverage,
    }
