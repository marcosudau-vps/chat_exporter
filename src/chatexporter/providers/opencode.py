"""OpenCode v2 Raw-Storage-Updater (Python >= 3.12, PyYAML für YAML-Konfiguration).

Eigenständig (installierter Befehl; config.yaml wie überall gesucht):
    chatexporter-opencode update
    chatexporter-opencode --config C:/Pfad/config.yaml update
    chatexporter-opencode --data-root P:/Backup/data update --dry-run
    chatexporter-opencode recreate-index | check-health | cleanup --dry-run | stats

Einbindung durch den Raw Session Updater (chatexporter.raw_session_updater):
    from chatexporter.providers.opencode import (update, recreate_index, check_storage_health,
                                                 cleanup_storage, state_n_stats)
    cfg = {"raw_root": Path(".../raw_storage"),
           "runtime_root": Path(".../runtime"), "opencode_exe": "opencode"}
    result = update(cfg)

Die Session-Übersicht kommt aus der lokalen OpenCode-v2-SQLite-Datenbank
(READ ONLY, einschließlich Child-/Subagent-Sessions). Die Nutzdaten werden
AUSSCHLIESSLICH über `opencode session export <ID>` bezogen. Es gibt keine
zusätzliche provider-eigene Manifest-/Indexdatei; der Raw Session Updater merged das
Fragment von recreate_index() in seinen Gesamtindex.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SOURCE = "opencode"
SESSION_RE = re.compile(r"^ses_[A-Za-z0-9_-]+$")
STALE_TMP_SECONDS = 24 * 60 * 60
DEFAULT_CONFIG_FILE = Path(__file__).resolve().parent / "config.yaml"


class ProviderError(RuntimeError):
    """Fehler auf Provider-/Strukturebene (Exit 2)."""


@dataclass(frozen=True)
class Config:
    raw_root: Path
    runtime_root: Path
    opencode_exe: str = "opencode"
    db_path: Path | None = None
    cli_cwd: Path | None = None
    timeout: int = 180
    max_retries: int = 2

    @property
    def sessions_root(self) -> Path:
        return self.raw_root / SOURCE / "sessions"

    @property
    def staging_root(self) -> Path:
        return self.runtime_root / "staging" / SOURCE


def _config(value: Config | Mapping[str, Any]) -> Config:
    if isinstance(value, Config):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("Config oder Mapping mit raw_root/runtime_root erwartet")
    if "data_root" in value:
        root = Path(value["data_root"]).expanduser().resolve()
        raw = Path(value.get("raw_root", root / "raw_storage"))
        runtime = Path(value.get("runtime_root", root / ".storage"))
    else:
        if not ("raw_root" in value and "runtime_root" in value):
            raise ValueError("raw_root und runtime_root (alternativ data_root) fehlen")
        raw = Path(value["raw_root"])
        runtime = Path(value["runtime_root"])
    db = value.get("db_path")
    cwd = value.get("cli_cwd")
    return Config(
        raw_root=raw.expanduser().resolve(),
        runtime_root=runtime.expanduser().resolve(),
        opencode_exe=str(value.get("opencode_exe", "opencode")),
        db_path=Path(db).expanduser().resolve() if db else None,
        cli_cwd=Path(cwd).expanduser().resolve() if cwd else None,
        timeout=int(value.get("timeout", 180)),
        max_retries=max(0, int(value.get("max_retries", 2))),
    )


def load_provider_config(config_file: str | Path = DEFAULT_CONFIG_FILE) -> dict[str, Any]:
    """Liest die gemeinsame YAML und extrahiert nur Storage + OpenCode-Einstellungen.

    Relative Pfade werden relativ zum Verzeichnis der YAML-Datei interpretiert.
    Der Rückgabewert ist außerdem direkt für update(config) usw. nutzbar.
    """
    try:
        import yaml
    except ImportError as exc:
        raise ProviderError(
            "YAML-Konfiguration benötigt das kostenlose Paket PyYAML: pip install pyyaml"
        ) from exc

    path = Path(config_file).expanduser().resolve()
    if not path.is_file():
        raise ProviderError(f"Konfigurationsdatei nicht gefunden: {path}")
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            document = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ProviderError(f"Konfigurationsdatei kann nicht gelesen werden: {exc}") from exc

    if not isinstance(document, Mapping):
        raise ProviderError("config.yaml muss ein YAML-Objekt enthalten")
    storage = document.get("storage", {})
    providers = document.get("providers", {})
    if not isinstance(storage, Mapping) or not isinstance(providers, Mapping):
        raise ProviderError("'storage' und 'providers' müssen YAML-Objekte sein")
    opencode = providers.get(SOURCE, {})
    if not isinstance(opencode, Mapping):
        raise ProviderError("'providers.opencode' muss ein YAML-Objekt sein")

    # Kein versehentliches Überschreiben der Storage-Pfade durch Provider-Keys.
    result = {key: storage[key] for key in ("data_root", "raw_root", "runtime_root")
              if storage.get(key) is not None}
    result.update({key: opencode[key] for key in
                   ("opencode_exe", "db_path", "cli_cwd", "timeout", "max_retries")
                   if opencode.get(key) is not None})

    for key in ("data_root", "raw_root", "runtime_root", "db_path", "cli_cwd"):
        if key in result:
            value = Path(result[key]).expanduser()
            result[key] = value if value.is_absolute() else (path.parent / value).resolve()

    if "data_root" not in result and not ("raw_root" in result and "runtime_root" in result):
        raise ProviderError(
            "In 'storage' fehlt 'data_root' (alternativ: 'raw_root' und 'runtime_root')"
        )
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_error(exc: Exception | str) -> str:
    """Fehlertext für Reports/Manifeste kürzen und gängige Secrets verdecken."""
    value = str(exc)
    value = re.sub(r"(?i)Bearer\s+[^\s,;]+", "Bearer [REDACTED]", value)
    value = re.sub(r"(?i)(authorization|api[_-]?key|cookie|token|password)\s*[:=]\s*[^\s,;]+",
                   r"\1=[REDACTED]", value)
    value = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
                   "[EMAIL]", value)
    value = re.sub(r"(https?://[^\s?#]+)\?[^\s#]+", r"\1?[REDACTED]", value)
    return value[:350]


def _millis(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} fehlt oder ist kein Zeitstempel")
    result = int(value)
    if result <= 0:
        raise ValueError(f"{label} ist nicht positiv")
    return result


def _cli(cfg: Config, *args: str, cwd: Path | None = None) -> bytes:
    effective_cwd = cwd if cwd and cwd.is_dir() else cfg.cli_cwd
    try:
        p = subprocess.run(
            [cfg.opencode_exe, *args],
            cwd=str(effective_cwd) if effective_cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            shell=False,
            timeout=cfg.timeout,
            check=False,
        )
    except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired, OSError) as exc:
        raise ProviderError(f"OpenCode CLI konnte nicht ausgeführt werden: {exc}") from exc
    if p.returncode:
        # Keine Roh-CLI-Ausgabe inkl. potenzieller Nutzdaten in Run-Manifeste schreiben.
        msg = p.stderr.decode("utf-8", errors="replace").strip().splitlines()
        detail = _safe_error(msg[-1]) if msg else "ohne Fehlermeldung"
        raise ProviderError(f"CLI exit={p.returncode} bei {' '.join(args[:2])}: {detail}")
    return p.stdout


def _db_file(cfg: Config) -> Path:
    if cfg.db_path is not None:
        path = cfg.db_path
    else:
        result = _cli(cfg, "debug", "paths", "db").decode("utf-8-sig", errors="replace")
        lines = [x.strip().strip('"') for x in result.splitlines() if x.strip()]
        if not lines:
            raise ProviderError("`opencode debug paths db` gab keinen Pfad zurück")
        path = Path(lines[-1]).expanduser().resolve()
    if not path.is_file():
        raise ProviderError(f"OpenCode-Datenbank nicht gefunden: {path}")
    return path


def _db_connect(cfg: Config) -> sqlite3.Connection:
    # mode=ro: weder Sessions noch OpenCode-Datenbank verändern.
    db = _db_file(cfg)
    try:
        conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        return conn
    except sqlite3.Error as exc:
        raise ProviderError(f"OpenCode-Datenbank nicht lesbar: {exc}") from exc


#: Sitzungstabellen in Vorrangreihenfolge. Neuere OpenCode-Versionen fuehren
#: Sitzungen in `session_v2`; `session` bleibt dort als veralteter Rest stehen
#: (belegt 2026-10-01: v2 mit 54 statt 48 Sitzungen und aktuellem
#: time_updated, das zum Export passt).
SESSION_TABLES = ("session_v2", "session")


def _session_table(conn: sqlite3.Connection) -> str:
    existing = {str(row[0]) for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    for table in SESSION_TABLES:
        if table in existing:
            return table
    raise ProviderError("OpenCode-DB enthaelt keine Sitzungstabelle (session_v2/session)")


def _db_columns(conn: sqlite3.Connection, table: str = "session") -> set[str]:
    names = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    required = {"id", "title", "time_created", "time_updated", "project_id", "directory"}
    missing = required - names
    if missing:
        raise ProviderError(f"Unbekanntes OpenCode-v2-DB-Schema ({table}); Felder fehlen: {sorted(missing)}")
    return names


def _select_fields(columns: set[str]) -> str:
    optional = {"parent_id": "parentID", "time_archived": "archived"}
    core = ["id", "title", "time_created AS created", "time_updated AS updated",
            "project_id AS projectId", "directory"]
    core += [f"{col} AS {alias}" if col in columns else f"NULL AS {alias}"
             for col, alias in optional.items()]
    return ", ".join(core)


def _normalize_row(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    if not SESSION_RE.fullmatch(str(d["id"])):
        raise ProviderError(f"Ungültige Session-ID aus der OpenCode-Datenbank: {d['id']!r}")
    d["created"] = _millis(d["created"], "created")
    d["updated"] = _millis(d["updated"], "updated")
    return d


def _list_sessions(cfg: Config) -> list[dict[str, Any]]:
    # CLI `session list` zeigt in OpenCode v2 Root-Sessions; die read-only
    # DB-Abfrage erfasst auch Child-/Subagent-Sessions und archivierte Einträge.
    try:
        with closing(_db_connect(cfg)) as conn:
            table = _session_table(conn)
            fields = _select_fields(_db_columns(conn, table))
            rows = conn.execute(f"SELECT {fields} FROM {table} ORDER BY time_updated DESC").fetchall()
        return [_normalize_row(row) for row in rows]
    except sqlite3.Error as exc:
        raise ProviderError(f"Fehler beim Lesen der OpenCode-Sessions: {exc}") from exc


def _session_snapshot(cfg: Config, sid: str) -> dict[str, Any] | None:
    try:
        with closing(_db_connect(cfg)) as conn:
            table = _session_table(conn)
            fields = _select_fields(_db_columns(conn, table))
            row = conn.execute(f"SELECT {fields} FROM {table} WHERE id = ?", (sid,)).fetchone()
        return _normalize_row(row) if row else None
    except sqlite3.Error as exc:
        raise ProviderError(f"Session-Metadaten nicht lesbar ({sid}): {exc}") from exc


def _norm_dir(value: Any) -> str | None:
    """Verzeichnis vergleichbar machen: DB schreibt `P:/x`, der Export `P:\\x`."""
    if not isinstance(value, str) or not value:
        return None
    return value.replace("\\", "/").rstrip("/").casefold()


def _snapshot_signature(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (row.get("id"), row.get("updated"), row.get("created"), row.get("title"),
            row.get("projectId"), _norm_dir(row.get("directory")), row.get("parentID"),
            row.get("archived"))


def _info_signature(info: Mapping[str, Any]) -> tuple[Any, ...]:
    tm = info.get("time") or {}
    # Neuere Exporte fuehren das Verzeichnis unter info.location.directory.
    location = info.get("location") if isinstance(info.get("location"), Mapping) else {}
    directory = info.get("directory") or location.get("directory")
    return (info.get("id"), tm.get("updated"), tm.get("created"),
            info.get("title"), info.get("projectID"), _norm_dir(directory),
            info.get("parentID"), tm.get("archived"))


def _validate_export(blob: bytes, sid: str | None = None) -> dict[str, Any]:
    try:
        obj = json.loads(blob.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Export ist kein valides UTF-8-JSON: {exc}") from exc
    if not isinstance(obj, dict) or not isinstance(obj.get("info"), dict):
        raise ValueError("Export enthält kein info-Objekt")
    info = obj["info"]
    if not SESSION_RE.fullmatch(str(info.get("id", ""))):
        raise ValueError("Ungültige Session-ID im Export")
    if sid and info["id"] != sid:
        raise ValueError(f"CLI exportierte falsche Session: {info['id']} statt {sid}")
    if not isinstance(obj.get("messages"), list):
        raise ValueError("Export enthält keine messages-Liste")
    if not isinstance(info.get("time"), dict):
        raise ValueError("Export enthält kein info.time")
    _millis(info["time"].get("created"), "info.time.created")
    _millis(info["time"].get("updated"), "info.time.updated")
    return obj


def _file_for(cfg: Config, info: Mapping[str, Any]) -> Path:
    sid = str(info["id"])
    if not SESSION_RE.fullmatch(sid):
        raise ValueError(f"Unsichere Session-ID: {sid}")
    created = _millis(info["time"]["created"], "created")
    date = datetime.fromtimestamp(created / 1000, tz=timezone.utc)
    return cfg.sessions_root / date.strftime("%Y") / date.strftime("%m") / date.strftime("%d") / f"{sid}.json"


def _scan(cfg: Config) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Raw-Storage ist Source of Truth; kein gesondertes OpenCode-Manifest nötig."""
    known: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    if not cfg.sessions_root.exists():
        return known, errors
    for path in sorted(cfg.sessions_root.rglob("*.json")):
        rel = path.relative_to(cfg.raw_root).as_posix()
        try:
            raw = path.read_bytes()
            export = _validate_export(raw, path.stem)
            info = export["info"]
            sid = info["id"]
            if _file_for(cfg, info) != path:
                raise ValueError("Datei liegt nicht im Bucket ihres UTC-Erstellungsdatums")
            if sid in known:
                raise ValueError(f"Doppelte Session-ID (bereits in {known[sid]['relative_path']})")
            known[sid] = {
                "path": path, "relative_path": rel, "info": info,
                "sha256": hashlib.sha256(raw).hexdigest(),
                "message_count": len(export["messages"]),
            }
        except (OSError, ValueError, OverflowError) as exc:
            errors.append({"file": rel, "error": _safe_error(exc)})
    return known, errors


def _atomic_write(cfg: Config, destination: Path, payload: bytes) -> None:
    cfg.staging_root.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix="opencode_", suffix=".tmp",
                                         dir=cfg.staging_root, delete=False) as out:
            tmp = Path(out.name)
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, destination)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def _blank_stats() -> dict[str, int]:
    return {key: 0 for key in (
        "sessions_total", "sessions_new", "sessions_changed", "sessions_unchanged",
        "sessions_fetched", "sessions_failed", "files_materialized", "files_failed"
    )}


def update(config: Config | Mapping[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    """Änderungen erkennen, nur betroffene Sessions via CLI exportieren.

    Ergebnis: {ok, stats, errors, exit_code}; kein globaler Index-/Manifest-Write.
    Der Stand wird ausschließlich aus den gesicherten Rohdateien abgeleitet.
    """
    cfg = _config(config)
    # Pfad einmalig über CLI auflösen, nicht erneut für jede einzelne Session.
    cfg = replace(cfg, db_path=_db_file(cfg))
    sessions = _list_sessions(cfg)
    known, scan_errors = _scan(cfg)
    stats = _blank_stats()
    stats["sessions_total"] = len(sessions)
    errors: list[dict[str, str]] = list(scan_errors)
    # Korruption ist kein Grund, unbeteiligte Sessions nicht zu sichern.
    stats["files_failed"] = len(scan_errors)
    # Nachvollziehbarkeit im Laufbericht: welche Sessions wurden gespeichert?
    fetched: list[dict[str, str]] = []

    for current in sessions:
        sid = current["id"]
        existing = known.get(sid)
        action = "new" if existing is None else (
            "unchanged" if _snapshot_signature(current) == _info_signature(existing["info"])
            else "changed"
        )
        if action == "unchanged":
            stats["sessions_unchanged"] += 1
            continue
        stats[f"sessions_{action}"] += 1
        if dry_run:
            fetched.append({"id": sid, "kind": "session", "action": action, "dry_run": "true"})
            continue
        try:
            # Aktive Sessions können sich während des CLI-Exports verändern.
            # In diesem Fall noch einmal exportieren; niemals ein erkennbar
            # veraltetes JSON als neuen Sicherungsstand committen.
            snapshot = current
            for attempt in range(cfg.max_retries + 1):
                directory = Path(snapshot["directory"]) if snapshot.get("directory") else None
                data = _cli(cfg, "session", "export", sid, cwd=directory)
                obj = _validate_export(data, sid)
                after = _session_snapshot(cfg, sid)
                if after is None:
                    raise ValueError("Session wurde während des Exports entfernt")
                if (_snapshot_signature(snapshot) == _snapshot_signature(after)
                        and _info_signature(obj["info"]) == _snapshot_signature(after)):
                    break
                snapshot = after
                if attempt == cfg.max_retries:
                    raise ValueError("Session wurde während des Exports verändert (Retry-Limit)")
            dest = _file_for(cfg, obj["info"])
            # Das Erstellungsdatum ist der stabile Bucket-Schlüssel. Eine
            # unerwartete Änderung NICHT stillschweigend durch Löschen kaschieren.
            previous_path = existing["path"] if existing else None
            if previous_path and previous_path != dest:
                raise ValueError("Erstellungsdatum/Bucket der Session hat sich unerwartet geändert")
            _atomic_write(cfg, dest, data)
            stats["sessions_fetched"] += 1
            fetched.append({"id": sid, "kind": "session", "action": action,
                            "title": str(obj["info"].get("title") or "")[:120]})
        except (ProviderError, ValueError, OSError, OverflowError) as exc:
            stats["sessions_failed"] += 1
            errors.append({"session_id": sid, "error": _safe_error(exc)})

    # Ein anfänglich beschädigter Datensatz kann im selben Lauf repariert worden
    # sein. Health-Fehler deshalb am Ende aus dem tatsächlichen Bestand ableiten.
    _, remaining_scan_errors = _scan(cfg) if not dry_run else (known, scan_errors)
    stats["files_failed"] = len(remaining_scan_errors)
    errors = [e for e in errors if "file" not in e] + remaining_scan_errors
    return {"source": SOURCE, "ok": not errors, "stats": stats, "errors": errors,
            "exit_code": 1 if errors else 0, "dry_run": dry_run,
            "items": {"fetched": fetched,
                      "failed": [{"id": e.get("session_id") or e.get("file"), "error": e.get("error")}
                                 for e in errors]}}


def recreate_index(config: Config | Mapping[str, Any]) -> dict[str, Any]:
    """Rebuildbares Provider-Fragment; der Raw Session Updater übernimmt den globalen Merge."""
    cfg = _config(config)
    known, errors = _scan(cfg)
    entries: dict[str, Any] = {}
    for sid, item in known.items():
        info = item["info"]
        tm = info["time"]
        entries[f"{SOURCE}:session:{sid}"] = {
            "source": SOURCE, "kind": "session", "session_id": sid,
            "relative_path": item["relative_path"], "title": info.get("title"),
            "create_time": tm["created"], "remote_updated_at": tm["updated"],
            "project_id": info.get("projectID"), "parent_session_id": info.get("parentID"),
            "archived_at": tm.get("archived"), "message_count": item["message_count"],
            "file_sha256": item["sha256"], "raw_integrity_ok": True,
            "json_complete": True, "fetch_complete": True,
            "acquisition_source": "opencode_cli",
        }
    candidates = len(known) + len(errors)
    return {
        "fragment_schema_version": 1,
        "source": SOURCE, "generated_at": _utc_now(), "candidates": candidates,
        "indexed": len(known), "coverage_percent": round(100 * len(known) / candidates, 2) if candidates else 100.0,
        "failed_files": errors, "entries": entries, "file_refs": {},
        "coverage": {"percent": round(100 * len(known) / candidates, 2) if candidates else 100.0},
    }


def check_storage_health(config: Config | Mapping[str, Any]) -> dict[str, Any]:
    """Read-only; prüft Bucket, JSON-Struktur, IDs und Duplikate."""
    cfg = _config(config)
    known, errors = _scan(cfg)
    return {
        "source": SOURCE, "ok": not errors,
        "stats": {"sessions_valid": len(known), "files_invalid": len(errors)},
        "errors": errors, "exit_code": 1 if errors else 0,
    }


def cleanup_storage(config: Config | Mapping[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    """Nur eigene alte *.tmp (>=24 h) und leere Session-Buckets entfernen."""
    cfg = _config(config)
    removed: list[str] = []
    now = datetime.now(timezone.utc).timestamp()
    if cfg.staging_root.exists():
        for path in cfg.staging_root.rglob("*.tmp"):
            try:
                if not path.is_file() or now - path.stat().st_mtime < STALE_TMP_SECONDS:
                    continue
                removed.append(str(path))
                if not dry_run:
                    path.unlink()
            except OSError as exc:
                return {"source": SOURCE, "ok": False, "errors": [_safe_error(exc)], "exit_code": 1}
    # Leere Ordner: nur unter dem Namespace dieses Providers, niemals Rohdateien.
    for root in (cfg.staging_root, cfg.sessions_root):
        if root.exists():
            for directory in sorted((p for p in root.rglob("*") if p.is_dir()),
                                    key=lambda p: len(p.parts), reverse=True):
                if not any(directory.iterdir()):
                    removed.append(str(directory))
                    if not dry_run:
                        directory.rmdir()
    return {"source": SOURCE, "ok": True, "dry_run": dry_run,
            "candidates": len(removed), "paths": removed, "exit_code": 0}


def state_n_stats(config: Config | Mapping[str, Any]) -> dict[str, Any]:
    """Read-only Snapshot. OVERVIEW.md erzeugt ausschließlich der Raw Session Updater."""
    cfg = _config(config)
    known, errors = _scan(cfg)
    root_count = sum(not item["info"].get("parentID") for item in known.values())
    archived = sum(item["info"].get("time", {}).get("archived") is not None
                   for item in known.values())
    return {
        "source": SOURCE, "generated_at": _utc_now(), "sessions_total": len(known),
        "sessions_root": root_count, "sessions_child": len(known) - root_count,
        "sessions_archived": archived, "files_invalid": len(errors),
        "bytes_total": sum(item["path"].stat().st_size for item in known.values()),
        "ok": not errors, "errors": errors, "exit_code": 1 if errors else 0,
    }


def _standalone_run_manifest(cfg: Config, report: dict[str, Any],
                             started_at: str) -> Path:
    """Nur beim direkten CLI-Aufruf; importierter Provider schreibt kein Run-File."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    stats = report.get("stats", _blank_stats())
    manifest = {
        "schema_version": 4, "run_id": stamp, "kind": "update",
        "started_at": started_at, "finished_at": _utc_now(),
        "partial": report.get("exit_code") == 2,
        "sources": {SOURCE: {"ok": report.get("ok", False),
                             "stats": stats, "errors": report.get("errors", [])}},
        "totals": {k: stats.get(k, 0) for k in
                   ("sessions_total", "sessions_fetched", "sessions_failed",
                    "files_materialized", "files_failed")},
        "errors": report.get("errors", []),
    }
    out = cfg.runtime_root / "runs" / f"sync_{stamp}.json"
    _atomic_write(cfg, out, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenCode v2 - inkrementeller Raw-Storage-Updater")
    parser.add_argument("--config", type=Path,
                        help="Gemeinsame YAML-Konfiguration (Standard: config.yaml neben dem Skript)")
    parser.add_argument("--data-root", type=Path,
                        help="Optionaler Override für den Datenordner aus config.yaml")
    parser.add_argument("--opencode-exe", help="Optionaler Override für OpenCode-Binary/CLI")
    parser.add_argument("--db-path", type=Path, help="Optionaler Pfad zur OpenCode-DB")
    parser.add_argument("--cli-cwd", type=Path, help="Fallback-Arbeitsordner der CLI")
    parser.add_argument("--timeout", type=int)
    parser.add_argument("--retries", type=int)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("update", "recreate-index", "check-health", "cleanup", "stats"):
        cmd = sub.add_parser(name)
        if name in ("update", "cleanup"):
            cmd.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        config_path = args.config if args.config is not None else DEFAULT_CONFIG_FILE
        if args.config is not None or config_path.is_file():
            values = load_provider_config(config_path)
        else:
            values = {}
        # CLI-Parameter haben Vorrang vor der YAML-Konfiguration.
        if args.data_root is not None:
            values.pop("raw_root", None)
            values.pop("runtime_root", None)
            values["data_root"] = args.data_root
        for option, value in (
            ("opencode_exe", args.opencode_exe), ("db_path", args.db_path),
            ("cli_cwd", args.cli_cwd), ("timeout", args.timeout),
            ("max_retries", args.retries),
        ):
            if value is not None:
                values[option] = value
        cfg = _config(values)
    except (ProviderError, TypeError, ValueError, OSError) as exc:
        parser.error(_safe_error(exc))
    started = _utc_now()
    try:
        if args.command == "update":
            report = update(cfg, dry_run=args.dry_run)
            if not args.dry_run:
                report["run_manifest"] = str(_standalone_run_manifest(cfg, report, started))
        elif args.command == "recreate-index":
            report = recreate_index(cfg)
        elif args.command == "check-health":
            report = check_storage_health(cfg)
        elif args.command == "cleanup":
            report = cleanup_storage(cfg, dry_run=args.dry_run)
        else:
            report = state_n_stats(cfg)
    except (ProviderError, OSError, ValueError, sqlite3.Error) as exc:
        report = {"source": SOURCE, "ok": False, "errors": [{"error": _safe_error(exc)}],
                  "exit_code": 2}
        if args.command == "update" and not args.dry_run:
            try:
                report["run_manifest"] = str(_standalone_run_manifest(cfg, report, started))
            except OSError:
                pass
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return int(report.get("exit_code", 0))


if __name__ == "__main__":
    sys.exit(main())
