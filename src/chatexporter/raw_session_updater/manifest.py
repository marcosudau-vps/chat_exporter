"""Laufbericht (Run-Manifest, Schema 4): EINE Datei je Updater-Lauf."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ._io import atomic_write_json, now_iso
from .config import RawSessionUpdaterConfig

RUN_MANIFEST_SCHEMA_VERSION = 4

#: `requests_total` = an externe Dienste gesendete Anfragen (heute nur ChatGPT;
#: lokale Quellen melden keine und zaehlen mit 0).
TOTAL_KEYS = ("sessions_total", "sessions_fetched", "sessions_failed",
              "files_materialized", "files_failed", "requests_total")


def build_run_manifest(provider_results: dict[str, dict[str, Any]], *,
                       started: str, kind: str = "update") -> dict[str, Any]:
    """Fasst die Vertragsergebnisse aller Quellen zu einem Laufbericht zusammen."""
    sources: dict[str, Any] = {}
    totals = {key: 0 for key in TOTAL_KEYS}
    errors: list[dict[str, Any]] = []
    partial = False
    for source, result in provider_results.items():
        ok = bool(result.get("ok", False))
        if not ok:
            partial = True
        section = {"ok": ok, "stats": result.get("stats") or {},
                   "errors": list(result.get("errors") or [])}
        # Nachvollziehbarkeit je Quelle: wann, wie lange, was genau.
        for key in ("started_at", "finished_at", "duration_seconds", "items", "detail"):
            if result.get(key) is not None:
                section[key] = result[key]
        sources[source] = section
        for key in totals:
            totals[key] += int(section["stats"].get(key, 0) or 0)
        errors.extend(section["errors"])
    return {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "run_id": f"{kind}_{now_iso()}",
        "kind": kind,
        "started_at": started,
        "finished_at": now_iso(),
        "partial": partial,
        "sources": sources,
        "totals": totals,
        "errors": errors,
    }


def write_run_manifest(cfg: RawSessionUpdaterConfig, manifest: dict[str, Any]) -> Path:
    cfg.ensure_runtime_dirs()
    stamp = manifest["finished_at"].replace(":", "").replace("-", "")
    path = cfg.runs_dir / f"sync_{stamp}.json"
    atomic_write_json(path, manifest, staging_dir=cfg.staging_root / "runs")
    return path
