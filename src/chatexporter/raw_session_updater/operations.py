"""Operationen des Raw Session Updaters ueber alle aktiven Quellen.

Jede Operation ruft die gleichnamige Vertragsfunktion aller aktiven Provider
auf und fuehrt die Ergebnisse zusammen. Rueckgabe jeweils ``(bericht, exitcode)``;
ausgegeben wird nichts (das macht die Bedienschicht).

Exitcodes: 0 = ok, 1 = Lauf ok mit Fehlern/Warnungen, 2 = Teilausfall/abgebrochen.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterable

from ._io import atomic_write_json, now_iso
from .config import RawSessionUpdaterConfig
from .fragments import (
    FILE_INDEX_SCHEMA_VERSION, INDEX_SCHEMA_VERSION, coverage, coverage_of,
    normalize_failed_files, validate_fragment,
)
from .manifest import build_run_manifest, write_run_manifest
from .registry import KNOWN_SOURCES, call

Progress = Callable[[str], None]


def _selected(cfg: RawSessionUpdaterConfig, sources: Iterable[str] | None) -> tuple[str, ...]:
    if not sources:
        return cfg.sources
    chosen = tuple(dict.fromkeys(sources))
    unknown = [s for s in chosen if s not in KNOWN_SOURCES]
    if unknown:
        raise ValueError(f"Unbekannte Quelle(n): {', '.join(unknown)} "
                         f"(bekannt: {', '.join(KNOWN_SOURCES)})")
    return chosen


def _error(source: str, stage: str, exc: Exception) -> dict[str, Any]:
    return {"source": source, "stage": stage, "error": f"{type(exc).__name__}: {exc}"}


#: So viele geholte Eintraege werden je Quelle in der Konsole namentlich
#: genannt; der Laufbericht enthaelt immer alle.
CONSOLE_ITEM_LIMIT = 10


def _say_source_summary(say: Progress, source: str, section: dict[str, Any]) -> None:
    """Eine Zusammenfassung je Quelle, damit die Konsole zeigt, was wo geschah."""
    stats = section.get("stats") or {}
    items = section.get("items") or {}
    state = "ok" if section.get("ok") else "NICHT ok"
    parts = [f"neu {stats.get('sessions_new', 0)}", f"geaendert {stats.get('sessions_changed', 0)}",
             f"gespeichert {stats.get('sessions_fetched', 0)}",
             f"fehlgeschlagen {stats.get('sessions_failed', 0)}",
             f"Dateien neu {stats.get('files_materialized', 0)}"]
    if stats.get("requests_total"):
        parts.append(f"Anfragen {stats['requests_total']}")
    say(f"--- Quelle {source}: {state} | {', '.join(parts)} | "
        f"Dauer {section.get('duration_seconds', 0)} s")
    fetched = items.get("fetched") or []
    for row in fetched[:CONSOLE_ITEM_LIMIT]:
        title = f" – {row['title']}" if row.get("title") else ""
        say(f"    gespeichert: {row.get('id')} ({row.get('action', '?')}){title}")
    if len(fetched) > CONSOLE_ITEM_LIMIT:
        say(f"    … und {len(fetched) - CONSOLE_ITEM_LIMIT} weitere (vollstaendig im Laufbericht)")
    failed = items.get("failed") or [
        {"id": e.get("session_id") or e.get("conversation_id") or e.get("file"),
         "error": e.get("error")} for e in section.get("errors") or []]
    for row in failed[:CONSOLE_ITEM_LIMIT]:
        say(f"    FEHLER: {row.get('id') or '-'}: {row.get('error')}")
    if len(failed) > CONSOLE_ITEM_LIMIT:
        say(f"    … und {len(failed) - CONSOLE_ITEM_LIMIT} weitere Fehler (vollstaendig im Laufbericht)")


# -- Alle Quellen aktualisieren -------------------------------------------------------

def update(cfg: RawSessionUpdaterConfig, *, sources: Iterable[str] | None = None,
           no_files: bool = False,
           non_interactive: bool = False, listing_mode: str | None = None,
           progress: Progress | None = None) -> tuple[dict[str, Any], int]:
    """Aktualisiert alle (oder die gewaehlten) Quellen; EIN Laufbericht."""
    say = progress or (lambda _m: None)
    started = now_iso()
    options = {"no_files": no_files,
               "non_interactive": non_interactive, "listing_mode": listing_mode,
               "progress": say}
    results: dict[str, dict[str, Any]] = {}
    for source in _selected(cfg, sources):
        say(f"=== Quelle {source}: Aktualisierung ===")
        source_started = now_iso()
        clock = time.monotonic()
        try:
            result = call(source, "update", cfg.provider_mapping(source), options)
            section = {
                "ok": bool(result.get("ok", False)),
                "stats": dict(result.get("stats") or {}),
                "errors": list(result.get("errors") or []),
                "detail": result.get("detail"),
                "items": result.get("items"),
            }
        except KeyboardInterrupt:
            # Strg+C beendet die laufende Quelle (wie beim ChatGPT-Provider,
            # der das intern abfaengt); der Laufbericht wird trotzdem
            # geschrieben und die naechste Quelle laeuft.
            section = {"ok": False, "stats": {},
                       "errors": [{"source": source, "stage": "update",
                                   "error": "Vom Nutzer abgebrochen (Strg+C)"}],
                       "detail": {"aborted": True, "abort_stage": "interrupted"}}
            say(f"Quelle {source}: vom Nutzer abgebrochen.")
        except Exception as exc:  # noqa: BLE001
            section = {"ok": False, "stats": {}, "errors": [_error(source, "update", exc)]}
            say(f"Quelle {source}: FEHLER {section['errors'][0]['error']}")
        section["started_at"] = source_started
        section["finished_at"] = now_iso()
        section["duration_seconds"] = round(time.monotonic() - clock, 1)
        results[source] = section
        _say_source_summary(say, source, section)
    manifest = build_run_manifest(results, started=started)
    run_path = write_run_manifest(cfg, manifest)
    manifest["run_manifest"] = str(run_path)
    totals = manifest["totals"]
    say(f"Update abgeschlossen: {totals['sessions_fetched']} Sessions geholt, "
        f"{totals['sessions_failed']} Fehler, {totals['files_materialized']} Dateien neu, "
        f"{totals['requests_total']} Anfragen an externe Dienste. Laufbericht: {run_path}")
    if manifest["partial"]:
        return manifest, 2
    if totals["sessions_failed"] or totals["files_failed"] or manifest["errors"]:
        return manifest, 1
    return manifest, 0


# -- Gesamtindex ------------------------------------------------------------------

def rebuild_index(cfg: RawSessionUpdaterConfig) -> tuple[dict[str, Any], int]:
    """Fragmente aller aktiven Quellen einsammeln, pruefen, atomar mergen.

    Fail-closed: ist ein Fragment fehlerhaft oder kollidieren IDs, bleibt der
    bisherige Gesamtindex unveraendert.
    """
    started = now_iso()
    cfg.ensure_runtime_dirs()
    fragments: dict[str, dict[str, Any]] = {}
    failed: dict[str, str] = {}
    for source in cfg.sources:
        try:
            fragments[source] = call(source, "recreate_index", cfg.provider_mapping(source))
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            failed[source] = f"{type(exc).__name__}: {exc}"
    for source, fragment in fragments.items():
        try:
            validate_fragment(fragment)
        except ValueError as exc:
            failed[source] = f"invalid fragment: {exc}"
    if failed:
        return {"ok": False, "started_at": started, "finished_at": now_iso(),
                "failed": failed, "committed": False}, 2

    merged_entries: dict[str, Any] = {}
    merged_refs: dict[str, list[dict[str, Any]]] = {}
    merged_ref_sources: dict[str, set[str]] = {}
    coverage_sources: dict[str, Any] = {}
    candidates_total = indexed_total = 0
    for source in cfg.sources:
        fragment = fragments[source]
        for cid, entry in fragment["entries"].items():
            if cid in merged_entries:
                return {"ok": False, "started_at": started, "finished_at": now_iso(),
                        "failed": {source: f"duplicate id across providers: {cid}"},
                        "committed": False}, 2
            merged_entries[cid] = entry
        for fid, refs in (fragment.get("file_refs") or {}).items():
            bucket = merged_refs.setdefault(fid, [])
            for row in refs or []:
                if row not in bucket:
                    bucket.append(row)
            merged_ref_sources.setdefault(fid, set()).add(source)
        candidates_total += int(fragment["candidates"])
        indexed_total += int(fragment["indexed"])
        coverage_sources[source] = {
            "indexed": fragment["indexed"], "candidates": fragment["candidates"],
            "percent": coverage_of(fragment),
            "failed_files": normalize_failed_files(fragment, source),
        }
    percent = coverage(indexed_total, candidates_total)
    document = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "coverage": {"sources": coverage_sources, "percent": percent},
        "conversations": merged_entries,
    }
    atomic_write_json(cfg.index_path, document, staging_dir=cfg.staging_root / "index")
    file_index = {
        "schema_version": FILE_INDEX_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "files": {fid: {"file_id": fid, "references": refs,
                        "sources": sorted(merged_ref_sources.get(fid, set()))}
                  for fid, refs in merged_refs.items()},
    }
    atomic_write_json(cfg.file_index_path, file_index, staging_dir=cfg.staging_root / "index")
    return {"ok": True, "started_at": started, "finished_at": now_iso(),
            "sources": list(cfg.sources), "entries": len(merged_entries),
            "coverage_percent": percent, "index_path": str(cfg.index_path),
            "committed": True}, 0


# -- Pruefung ---------------------------------------------------------------------

def check_health(cfg: RawSessionUpdaterConfig, *, deep: bool = False,
                 sources: Iterable[str] | None = None) -> tuple[dict[str, Any], int]:
    """Konsolidierter Pruefbericht aller Quellen + quellenübergreifende Regeln (read-only)."""
    reports: dict[str, Any] = {}
    ok = True
    for source in _selected(cfg, sources):
        try:
            report = call(source, "check_storage_health", cfg.provider_mapping(source),
                          {"deep": deep})
        except Exception as exc:  # noqa: BLE001
            report = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        reports[source] = report
        ok = ok and bool(report.get("ok", False))
    global_issues: list[dict[str, Any]] = []
    if cfg.store_root.is_dir():
        allowed = set(KNOWN_SOURCES)
        for entry in sorted(cfg.store_root.iterdir()):
            if entry.is_dir() and entry.name not in allowed and not entry.name.startswith("."):
                global_issues.append({"level": "WARNING", "code": "store.unexpected-source-dir",
                                      "message": "Unbekannter Ordner in raw_storage/",
                                      "context": {"name": entry.name}})
                ok = False
            elif entry.is_file():
                global_issues.append({"level": "WARNING", "code": "store.unexpected-root-file",
                                      "message": "Datei in raw_storage/-Wurzel (nur Quellen-Ordner erlaubt)",
                                      "context": {"name": entry.name}})
                ok = False
    return {"ok": ok, "sources": reports, "global_issues": global_issues}, 0 if ok else 1


# -- Bereinigung ------------------------------------------------------------------

def cleanup(cfg: RawSessionUpdaterConfig, *, dry_run: bool = False,
            sources: Iterable[str] | None = None) -> tuple[dict[str, Any], int]:
    """Bereinigt definierte Reste aller Quellen (niemals Quelldaten)."""
    reports: dict[str, Any] = {}
    code = 0
    for source in _selected(cfg, sources):
        try:
            reports[source] = call(source, "cleanup_storage", cfg.provider_mapping(source),
                                   {"dry_run": dry_run})
        except Exception as exc:  # noqa: BLE001
            reports[source] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            code = 2
    return {"ok": code == 0, "dry_run": dry_run, "sources": reports}, code


# -- Status / Uebersicht ----------------------------------------------------------

_OVERVIEW_TEMPLATE = """# Updater-Übersicht (generiert)

> Generiert: {generated_at} · Quelle: `chatexporter status` · Kein Source of Truth
> (jederzeit aus den Daten neu erzeugbar).

| Quelle | Sessions | Dateien (distinct: referenziert/materialisiert/unavailable) | Coverage |
| --- | ---: | --- | ---: |
{rows}

## Läufe (neueste zuerst)

{run_rows}
"""


def status(cfg: RawSessionUpdaterConfig, *, write_overview: bool = True,
           sources: Iterable[str] | None = None) -> tuple[dict[str, Any], int]:
    """Momentaufnahme aller Quellen + ``.storage/OVERVIEW.md``."""
    snapshots: dict[str, Any] = {}
    code = 0
    for source in _selected(cfg, sources):
        try:
            snapshots[source] = call(source, "state_n_stats", cfg.provider_mapping(source))
        except Exception as exc:  # noqa: BLE001
            snapshots[source] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            code = 1
    rows = []
    for source, snap in snapshots.items():
        sessions = snap.get("sessions_total", snap.get("conversations", 0))
        ref = snap.get("files_referenced_distinct",
                       snap.get("file_references", snap.get("files_total", 0)))
        mat = snap.get("files_materialized_distinct", snap.get("files_materialized", 0))
        una = snap.get("files_unavailable_distinct", snap.get("files_unavailable", 0))
        cov = (snap.get("index_coverage") or {}).get("percent", "–")
        rows.append(f"| {source} | {sessions} | {ref}/{mat}/{una} | {cov} % |")
    run_rows = []
    if cfg.runs_dir.exists():
        for manifest_path in sorted(cfg.runs_dir.glob("sync_*.json"), reverse=True)[:10]:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            totals = manifest.get("totals", {})
            run_rows.append(f"- `{manifest_path.name}` – v{manifest.get('schema_version')}, "
                            f"Quellen={','.join(sorted((manifest.get('sources') or {}).keys()))}, "
                            f"partial={manifest.get('partial')}, "
                            f"sessions_fetched={totals.get('sessions_fetched')}, "
                            f"files_materialized={totals.get('files_materialized')}, "
                            f"requests={totals.get('requests_total', '–')}")
    overview = _OVERVIEW_TEMPLATE.format(
        generated_at=now_iso(),
        rows="\n".join(rows) if rows else "| – | – | – | – |",
        run_rows="\n".join(run_rows) if run_rows else "Keine Läufe.")
    overview_path = None
    if write_overview:
        cfg.ensure_runtime_dirs()
        overview_path = cfg.overview_path
        overview_path.write_text(overview, encoding="utf-8")
    return {"ok": code == 0, "sources": snapshots,
            "overview_path": str(overview_path) if overview_path else None}, code
