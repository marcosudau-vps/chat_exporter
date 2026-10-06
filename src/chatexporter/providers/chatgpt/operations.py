from __future__ import annotations

"""ChatGPT-spezifische Einzeloperationen ausserhalb des Provider-Vertrags.

Jede Funktion liefert ``(bericht, exitcode)`` und gibt nichts selbst aus --
die Bedienschicht (``cli.py``) entscheidet ueber die Darstellung.
"""

import json
from pathlib import Path
from typing import Any, Callable

from chatexporter.providers.chatgpt.auth.edge_cdp import detect_edge_executable
from chatexporter.providers.chatgpt.common.io import atomic_write_json
from chatexporter.providers.chatgpt.common.time import now_iso
from chatexporter.providers.chatgpt.config.models import AppConfig
from chatexporter.providers.chatgpt.contract import (
    SOURCE, contract_result, open_exclusions, open_layout, open_quarantine,
    open_repository, run_sync,
)
from chatexporter.providers.chatgpt.storage.envelope import refresh_acquisition_completeness
from chatexporter.providers.chatgpt.storage.layout import StoreLayout
from chatexporter.providers.chatgpt.storage.migrate_layout import migrate_layout as _migrate_layout
from chatexporter.providers.chatgpt.storage.status_store import rebuild_file_index

#: Schema des Laufberichts in ``runtime/runs/``. Identisch mit dem Schema des
#: Raw Session Updaters, damit Einzel- und Gesamtlaeufe gemeinsam auswertbar bleiben.
RUN_MANIFEST_SCHEMA_VERSION = 4

Progress = Callable[[str], None]


# -- Laufbericht (Einzellauf) -----------------------------------------------------

def write_run_manifest(layout: StoreLayout, result: dict[str, Any], *,
                       started: str) -> tuple[dict[str, Any], Path]:
    """Schreibt den Laufbericht eines Einzellaufs (nur Quelle ``chatgpt``)."""
    stats = result.get("stats") or {}
    manifest = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "run_id": f"update_{now_iso()}",
        "kind": "update",
        "started_at": started,
        "finished_at": now_iso(),
        "partial": not result.get("ok", False),
        "sources": {SOURCE: {"ok": bool(result.get("ok", False)), "stats": stats,
                             "errors": result.get("errors", []),
                             "started_at": result.get("started_at") or started,
                             "finished_at": result.get("finished_at"),
                             "items": result.get("items"),
                             "detail": result.get("detail", {})}},
        "totals": {k: int(stats.get(k, 0) or 0) for k in (
            "sessions_total", "sessions_fetched", "sessions_failed",
            "files_materialized", "files_failed", "requests_total")},
        "errors": result.get("errors", []),
    }
    layout.ensure_runtime_dirs()
    staging = layout.staging_root / "runs"
    staging.mkdir(parents=True, exist_ok=True)
    stamp = manifest["finished_at"].replace(":", "").replace("-", "")
    path = layout.runs_dir / f"sync_{stamp}.json"
    atomic_write_json(path, manifest, staging_dir=staging)
    return manifest, path


def sync(cfg: AppConfig, *, no_files: bool = False,
         non_interactive: bool = False, listing_mode: str | None = None,
         progress: Progress | None = None) -> tuple[dict[str, Any], int]:
    """Einzellauf: ChatGPT aktualisieren und Laufbericht schreiben."""
    started = now_iso()
    report = run_sync(cfg, no_files=no_files,
                      non_interactive=non_interactive, listing_mode=listing_mode,
                      write_manifest=False, progress=progress)
    result = contract_result(report)
    _manifest, run_path = write_run_manifest(open_layout(cfg), result, started=started)
    stats = report.get("stats") or {}
    summary = {
        "aborted": report.get("aborted", False),
        "abort_stage": report.get("abort_stage"),
        "abort_reason": report.get("abort_reason"),
        "listing": report.get("listing"),
        "verification": report.get("verification"),
        "requests": report.get("requests"),
        "rate_limit_hits": stats.get("rate_limit_hits", 0),
        "rate_limit_cycles": (report.get("rate_limit") or {}).get("cycles", 0),
        "quarantined_new": stats.get("quarantined_new", 0),
        "quarantined_skipped": stats.get("quarantined_skipped", 0),
        "excluded_skipped": stats.get("excluded_skipped", 0),
        "remote_total": stats.get("remote_total", 0),
        "fetched": stats.get("fetched", 0),
        "unchanged": stats.get("unchanged", 0),
        "fetch_failed": stats.get("fetch_failed", 0),
        "files_materialized": stats.get("files_materialized", 0),
        "files_failed": stats.get("files_failed", 0),
        "errors_recorded": len(stats.get("errors", [])),
        "run_manifest": str(run_path),
        "manifest_schema": RUN_MANIFEST_SCHEMA_VERSION,
    }
    if report.get("aborted"):
        return summary, 2
    return summary, 1 if stats.get("fetch_failed") else 0


# -- Index ------------------------------------------------------------------------

def rebuild_index(cfg: AppConfig) -> tuple[dict[str, Any], int]:
    """Baut den ChatGPT-Anteil des Gesamtindex direkt neu (fremde Quellen bleiben)."""
    repo, layout = open_repository(cfg)
    idx = repo.rebuild_index()
    return {"raw_root": str(repo.root), "source": layout.source,
            "conversations": len(idx.conversations),
            "coverage_percent": (idx.coverage or {}).get("percent", 100.0)}, 0


# -- Import eines OpenAI-Kontodatenexports ----------------------------------------

def import_data(cfg: AppConfig, *, source: Path, limit: int | None = None,
                only_ids: list[str] | None = None, overwrite_existing: bool = False,
                no_files: bool = False, report_path: Path | None = None,
                progress: Progress | None = None) -> tuple[dict[str, Any], int]:
    """Importiert einen Kontodatenexport als bewusst unvollstaendige Datensaetze."""
    from chatexporter.providers.chatgpt.importing import ImportedDataConverter
    say = progress or (lambda _m: None)
    _repo, layout = open_repository(cfg)
    converter = ImportedDataConverter(
        source_dir=source,
        raw_root=layout.source_root,
        overwrite_existing=overwrite_existing,
        materialize_files=not no_files,
        progress=lambda m: say("  " + m),
        staging_root=layout.staging_root,
    )
    report = converter.run(limit=limit, only_ids=only_ids)
    data = report.as_dict()
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        data["report_file"] = str(report_path)
    data["note"] = ("Importierte Datensaetze sind bewusst als unvollstaendig markiert "
                    "(json_complete=false) und werden vom naechsten Update automatisch "
                    "vollstaendig ueber die API nachgeladen. Der Index wird beim "
                    "naechsten Start neu aufgebaut.")
    return data, 1 if report.errors else 0


# -- Diagnose ---------------------------------------------------------------------

def doctor(cfg: AppConfig, *, config_file: Path | None = None) -> tuple[dict[str, Any], int]:
    """Aufgeloeste Konfiguration und Zustand der ChatGPT-Ablage (read-only)."""
    repo, layout = open_repository(cfg)
    quarantine = open_quarantine(cfg, layout)
    index = repo.index.conversations
    imported = sum(1 for e in index.values() if e.get("acquisition_source") == "imported_data")
    files_pending = sum(1 for e in index.values() if not e.get("files_complete", True))
    try:
        edge = str(detect_edge_executable(cfg.browser.edge_executable))
    except Exception as exc:
        edge = f"UNAVAILABLE: {exc}"
    return {
        "config_file": str(config_file) if config_file else None,
        "venv_path": str(cfg.bootstrap.venv_path),
        "env_file": str(cfg.bootstrap.env_file),
        "env_file_exists": cfg.bootstrap.env_file.is_file(),
        "edge_executable": edge,
        "cdp_endpoint": cfg.browser.cdp_endpoint,
        "edge_user_data_dir": str(cfg.browser.user_data_dir),
        "store_root": str(layout.store_root),
        "source": layout.source,
        "source_root": str(layout.source_root),
        "runtime_root": str(layout.runtime_root),
        "runs_dir": str(layout.runs_dir),
        "index_path": str(layout.index_path),
        "quarantine_path": str(layout.quarantine_path),
        "legacy_layout": layout.legacy,
        "status_root": str(repo.index.status_root),
        "status_registry": repo.index.library.status.summary(),
        "indexed_conversations": len(repo.index.conversations),
        "index_coverage": repo.index.coverage,
        "listing_mode": cfg.sync.listing_mode,
        "fetch_files": cfg.sync.fetch_files,
        "max_errors_per_run": cfg.sync.max_errors_per_run,
        "rate_limit_wait_minutes": cfg.sync.rate_limit_wait_minutes,
        "max_rate_limit_cycles": cfg.sync.max_rate_limit_cycles,
        "imported_conversations": imported,
        "conversations_with_pending_files": files_pending,
        "quarantine": quarantine.summary(),
        "manual_exclusions": open_exclusions(cfg).summary(),
    }, 0


# -- Einrichtung ------------------------------------------------------------------

def browser_setup(cfg: AppConfig, *, renew: bool = False, progress: Progress = print,
                  ask: Callable[[str], str] = input,
                  opener: Callable[..., Any] | None = None) -> tuple[dict[str, Any], int]:
    """Browser und ChatGPT-Anmeldung einrichten oder pruefen (interaktiv).

    Ohne ``renew`` wird ein eingetragenes Profil verwendet und nur die Anmeldung
    geprueft; mit ``renew`` (oder ohne eingetragenes Profil) laeuft die Suche mit
    Profilkopie, Anmeldung und Eintrag in die config.yaml. Laedt keine Chats.
    """
    from chatexporter.providers.chatgpt.api.client import RequestCounter
    from chatexporter.providers.chatgpt.auth.browser_setup import BrowserSetupError, open_browser
    if renew:
        cfg.browser.user_data_dir_configured = False
    counter = RequestCounter()
    try:
        session, _auth, choice = (opener or open_browser)(cfg, interactive=True, say=progress,
                                                           counter=counter, ask=ask)
    except BrowserSetupError as exc:
        return {"ok": False, "error": str(exc), "attempts": [a.as_dict() for a in exc.attempts],
                "requests": counter.as_dict()}, 1
    except Exception as exc:  # noqa: BLE001  z. B. fester Pfad ohne Anmeldung, Browser startet nicht
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "requests": counter.as_dict()}, 1
    try:
        # Einen fuer die Einrichtung gestarteten Browser wieder schliessen; einen
        # schon laufenden nur trennen.
        session.abandon() if getattr(session, "launched", False) else session.close()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "browser": choice.as_dict(), "requests": counter.as_dict()}, 0


def _mask_email(value: str | None) -> str | None:
    from chatexporter.providers.chatgpt.common.redaction import mask_email
    return mask_email(value)


def login(cfg: AppConfig, *, profile: Path | None = None, progress: Progress = print,
          session_factory: Callable[[Any], Any] | None = None, step_by_step: bool = False,
          ask: Callable[[str], str] = input) -> tuple[dict[str, Any], int]:
    """Anmeldung pruefen bzw. automatisch anmelden (``chatgpt login``); laedt keine Chats.

    Mit ``profile`` wird ein eigenes Datenverzeichnis verwendet (z. B. ein leerer
    Testordner, um die automatische Anmeldung von Grund auf zu pruefen). Ein
    Sperrvermerk nach abgelehnten Zugangsdaten wird hier bewusst ignoriert.

    ``step_by_step`` (``--schrittweise``): Browserfenster sichtbar, vor jedem Schritt
    Meldung und Bestaetigung; am Ende bleibt der Browser bis ENTER offen.
    """
    from chatexporter.providers.chatgpt.api.client import RequestCounter
    from chatexporter.providers.chatgpt.auth import browsers
    from chatexporter.providers.chatgpt.auth.browser_setup import auth_broker
    from chatexporter.providers.chatgpt.auth.edge_cdp import EdgeCdpSession, _cdp_endpoint_reachable
    browser = cfg.browser
    if profile is not None:
        browser.user_data_dir = Path(profile).expanduser().resolve()
        browser.user_data_dir_configured = True
        if _cdp_endpoint_reachable(browser.cdp_endpoint):
            free = browsers.find_free_port(browser.cdp_host, browser.cdp_port + 1)
            if free is None:
                return {"ok": False, "error": f"CDP-Port {browser.cdp_port} belegt, kein freier Port"}, 1
            browser.cdp_port = free
    counter = RequestCounter()
    report: dict[str, Any] = {"profile": str(browser.user_data_dir), "auto_login_enabled": cfg.auth.enabled,
                              "auto_login_mode": cfg.auth.auto_login}
    session = (session_factory or EdgeCdpSession)(browser).connect()
    confirm = None
    if step_by_step:
        show = getattr(session, "show_window", None)
        if callable(show):
            show()
        progress("Schrittweise Anmeldung: Das Browserfenster ist sichtbar; vor jedem Schritt wird gefragt.")

        def confirm(state: str, description: str) -> bool:
            progress(description)
            return ask("  ENTER = ausfuehren, a = abbrechen: ").strip().lower() not in ("a", "abbrechen")
    try:
        broker = auth_broker(cfg, session, counter=counter, say=progress, force_auto_login=True,
                             confirm=confirm)
        try:
            auth = broker.acquire(interactive=True)
        except Exception as exc:  # noqa: BLE001
            outcome = broker.auto_login_result
            report.update(ok=False, error=f"{type(exc).__name__}: {exc}",
                          auto_login=outcome.as_dict() if outcome else None, requests=counter.as_dict())
            return report, 1
        outcome = broker.auto_login_result
        report.update(ok=True, already_logged_in=outcome is None,
                      auto_login=outcome.as_dict() if outcome else None,
                      account=_mask_email(auth.identity.email), requests=counter.as_dict())
        return report, 0
    finally:
        if step_by_step:
            try:
                ask("Fertig. ENTER schliesst den Browser: ")
            except (EOFError, KeyboardInterrupt):
                pass
        try:
            session.abandon() if getattr(session, "launched", False) else session.close()
        except Exception:  # noqa: BLE001
            pass


# -- Wartung ----------------------------------------------------------------------

def migrate_store(cfg: AppConfig) -> tuple[dict[str, Any], int]:
    """Statusablage/Referenzen nachziehen (idempotent, kein Netz, `raw` unveraendert)."""
    from chatexporter.providers.chatgpt.fetch.reference_extractor import extract_file_references
    repo, layout = open_repository(cfg)
    library = repo.index.library
    migrated = 0
    library_root = repo.root / "library"
    if library_root.exists():
        for marker in sorted(library_root.rglob("unavailable.json")):
            try:
                data = json.loads(marker.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            if not isinstance(data, dict):
                data = {}
            fid = data.get("file_id") or marker.parent.name
            library.status.mark_unavailable(
                fid, status=data.get("http_status"), detail=data.get("detail"),
                save=False)
            marker.unlink(missing_ok=True)
            migrated += 1
        library.status.save()

    # Dateireferenzen lokal aus dem gespeicherten Graphen neu ableiten:
    # aeltere Envelopes kennen den Message-Bezug noch nicht.
    renormalized = 0
    for path, envelope in repo.iter_envelopes():
        raw = envelope.get("raw")
        if not isinstance(raw, dict):
            continue
        new_refs = extract_file_references(raw)
        if envelope.get("file_references") != new_refs:
            envelope["file_references"] = new_refs
            atomic_write_json(path, envelope, staging_dir=repo.staging)
            renormalized += 1

    # files_complete/complete neu berechnen: nach der Renormalisierung kann ein
    # frueher gesetztes files_complete=true veraltet sein.
    refreshed = 0
    for path, envelope in repo.iter_envelopes():
        if refresh_acquisition_completeness(envelope, library):
            atomic_write_json(path, envelope, staging_dir=repo.staging)
            refreshed += 1

    # Alt-Envelopes an das aktuelle acquisition-Format angleichen (rein
    # additiv): `json_complete` nur, wenn `complete` wahr ist; fehlendes
    # `source` bedeutet API-Pfad (der Importeur setzt immer "imported_data").
    normalized = 0
    for path, envelope in repo.iter_envelopes():
        acq = envelope.get("acquisition")
        if not isinstance(acq, dict):
            continue
        changed = False
        if "json_complete" not in acq and acq.get("complete") is True:
            acq["json_complete"] = True
            changed = True
        if "source" not in acq:
            acq["source"] = "api"
            changed = True
        if changed:
            atomic_write_json(path, envelope, staging_dir=repo.staging)
            normalized += 1

    if renormalized or refreshed or normalized:
        repo.rebuild_index()

    rebuild_file_index(repo, library.status.root)
    backfilled = 0
    for _path, envelope in repo.iter_envelopes():
        cid = envelope.get("conversation_id")
        refs = envelope.get("file_references")
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if isinstance(ref, dict):
                library.register_reference(ref, conversation_id=cid, update_index=False)
                backfilled += 1

    # Verwaltungsreste ohne Informationsgehalt: leere Bibliotheksverzeichnisse
    # und liegengebliebene Staging-Temporaerdateien.
    empty_dirs_removed = 0
    for base in (repo.root / "library" / "files", repo.root / "library" / "audio"):
        if not base.exists():
            continue
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            if any(d.glob("content.*")) or (d / "metadata.json").exists():
                continue
            try:
                d.rmdir()
                empty_dirs_removed += 1
            except OSError:
                pass
    staging_leftovers_removed = 0
    if layout.staging_root.exists():
        for tmp in sorted(layout.staging_root.rglob("*.tmp")):
            try:
                tmp.unlink()
                staging_leftovers_removed += 1
            except OSError:
                pass

    return {
        "raw_root": str(repo.root),
        "status_root": str(library.status.root),
        "unavailable_markers_migrated": migrated,
        "envelopes_renormalized": renormalized,
        "completeness_refreshed": refreshed,
        "acquisition_normalized": normalized,
        "references_registered": backfilled,
        "empty_library_dirs_removed": empty_dirs_removed,
        "staging_leftovers_removed": staging_leftovers_removed,
        "file_status": library.status.summary(),
    }, 0


def migrate_layout(cfg: AppConfig, *, dry_run: bool = False,
                   progress: Progress | None = None) -> tuple[dict[str, Any], int]:
    """Einmalig: flache Ablage -> ``raw_storage/chatgpt/`` + ``runtime/`` (idempotent)."""
    report = _migrate_layout(cfg.storage.raw_root, SOURCE, dry_run=dry_run,
                             progress=progress or (lambda _m: None))
    if report.get("migrated") and not dry_run:
        repo, layout = open_repository(cfg)
        idx = repo.rebuild_index()
        report["index_rebuilt"] = len(idx.conversations)
        report["coverage_percent"] = (idx.coverage or {}).get("percent", 100.0)
        report["index_path"] = str(layout.index_path)
    return report, 0
