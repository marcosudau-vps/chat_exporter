"""Claude Code – eigenständiger Raw-Storage-Updater (Python >= 3.12).

Benötigt für config.yaml: pip install PyYAML (keine weiteren Pakete).

Eigenständig (installierter Befehl; config.yaml wie überall gesucht):
    chatexporter-claude update --dry-run
    chatexporter-claude update
    chatexporter-claude --config P:/Pfad/config.yaml update
    chatexporter-claude --source-root C:/Alternative update
    chatexporter-claude recreate-index | check-health | cleanup --dry-run | stats

Einbindung durch den Raw Session Updater (chatexporter.raw_session_updater):
    from chatexporter.providers.claude import (
        update, recreate_index, check_storage_health, cleanup_storage, state_n_stats
    )
    result = update({
        "raw_root": Path(".../raw_storage"),
        "runtime_root": Path(".../runtime"),
        "source_root": Path(".../.claude/projects"),
    })

Nur .claude/projects/ wird eingelesen; die Quelldateien werden bytegetreu und
atomar nach raw_storage/claude/projects/ gespiegelt. Kein eigener
persistenter Provider-Index; recreate_index() liefert nur ein Index-Fragment für den Raw Session Updater.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SOURCE = "claude"
SOURCE_SUBDIR = "projects"
DEFAULT_SOURCE_ROOT = Path.home() / ".claude"
DEFAULT_CONFIG_FILE = Path(__file__).resolve().parent / "config.yaml"
STALE_TMP_SECONDS = 24 * 60 * 60
UUID_AT_END = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$")


class ProviderError(RuntimeError):
    """Nicht fortsetzbarer Provider-/Strukturfehler (Exitcode 2)."""


@dataclass(frozen=True)
class Config:
    raw_root: Path
    runtime_root: Path
    source_root: Path = DEFAULT_SOURCE_ROOT
    max_retries: int = 2
    verify_unchanged: bool = False

    @property
    def source_data_root(self) -> Path:
        # Sowohl `~/.codex` / `~/.claude` als auch deren direkte
        # `sessions`-/`projects`-Unterordner als source_root akzeptieren.
        return self.source_root if self.source_root.name.lower() == SOURCE_SUBDIR else self.source_root / SOURCE_SUBDIR

    @property
    def raw_data_root(self) -> Path:
        return self.raw_root / SOURCE / SOURCE_SUBDIR

    @property
    def staging_root(self) -> Path:
        return self.runtime_root / "staging" / SOURCE


def _config(value: Config | Mapping[str, Any]) -> Config:
    if isinstance(value, Config):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("Config oder Mapping erwartet")
    if "data_root" in value:
        data_root = Path(value["data_root"]).expanduser().resolve()
        raw = Path(value.get("raw_root", data_root / "raw_storage"))
        runtime = Path(value.get("runtime_root", data_root / ".storage"))
    else:
        if "raw_root" not in value or "runtime_root" not in value:
            raise ValueError("'data_root' oder 'raw_root' und 'runtime_root' fehlen")
        raw = Path(value["raw_root"])
        runtime = Path(value["runtime_root"])
    source = value.get("source_root", DEFAULT_SOURCE_ROOT)
    return Config(
        raw_root=raw.expanduser().resolve(),
        runtime_root=runtime.expanduser().resolve(),
        source_root=Path(source).expanduser().resolve(),
        max_retries=max(0, int(value.get("max_retries", 2))),
        verify_unchanged=_as_bool(value.get("verify_unchanged", False)),
    )


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise ValueError("'verify_unchanged' muss true oder false sein")


def load_provider_config(config_file: str | Path = DEFAULT_CONFIG_FILE) -> dict[str, Any]:
    """Liest `storage` + `providers.claude` aus derselben gemeinsamen YAML.

    Relative Pfade beziehen sich ausschließlich auf das YAML-Verzeichnis.
    Das zurückgegebene Mapping kann direkt an alle fünf Methoden gehen.
    """
    try:
        import yaml
    except ImportError as exc:
        raise ProviderError("YAML-Unterstützung fehlt: python -m pip install PyYAML") from exc
    path = Path(config_file).expanduser().resolve()
    if not path.is_file():
        raise ProviderError(f"Konfiguration nicht gefunden: {path}")
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            document = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise ProviderError(f"Konfiguration nicht lesbar: {exc}") from exc
    if not isinstance(document, Mapping):
        raise ProviderError("config.yaml muss ein YAML-Objekt enthalten")
    storage = document.get("storage", {})
    providers = document.get("providers", {})
    if not isinstance(storage, Mapping) or not isinstance(providers, Mapping):
        raise ProviderError("'storage' und 'providers' müssen YAML-Objekte sein")
    provider = providers.get(SOURCE, {})
    if not isinstance(provider, Mapping):
        raise ProviderError(f"'providers.{SOURCE}' muss ein YAML-Objekt sein")

    result = {k: storage[k] for k in ("data_root", "raw_root", "runtime_root")
              if storage.get(k) is not None}
    result.update({k: provider[k] for k in ("source_root", "max_retries", "verify_unchanged")
                   if provider.get(k) is not None})
    for key in ("data_root", "raw_root", "runtime_root", "source_root"):
        if key in result:
            candidate = Path(result[key]).expanduser()
            result[key] = candidate if candidate.is_absolute() else (path.parent / candidate).resolve()
    if "data_root" not in result and not ("raw_root" in result and "runtime_root" in result):
        raise ProviderError("'storage.data_root' oder 'storage.raw_root' + 'storage.runtime_root' fehlen")
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_error(exc: Exception | str) -> str:
    value = str(exc)
    value = re.sub(r"(?i)Bearer\s+[^\s,;]+", "Bearer [REDACTED]", value)
    value = re.sub(r"(?i)(authorization|api[_-]?key|cookie|token|password)\s*[:=]\s*[^\s,;]+",
                   r"\1=[REDACTED]", value)
    value = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "[EMAIL]", value)
    value = re.sub(r"(https?://[^\s?#]+)\?[^\s#]+", r"\1?[REDACTED]", value)
    return value[:350]


def _regular_stat(path: Path) -> os.stat_result:
    current = path.lstat()
    if not stat.S_ISREG(current.st_mode):
        raise ValueError("Keine reguläre Datei (Symlinks werden nicht verfolgt)")
    return current


def _source_files(cfg: Config) -> tuple[list[Path], list[dict[str, str]]]:
    root = cfg.source_data_root
    if not root.is_dir():
        raise ProviderError(f"Quellordner nicht gefunden: {root}")
    files: list[Path] = []
    errors: list[dict[str, str]] = []

    def onerror(exc: OSError) -> None:
        errors.append({"file": str(exc.filename or root), "error": _safe_error(exc)})

    for parent, dirs, names in os.walk(root, followlinks=False, onerror=onerror):
        current = Path(parent)
        # Kein unbeabsichtigtes Kopieren von verlinkten externen Verzeichnissen.
        for dirname in list(dirs):
            candidate = current / dirname
            if candidate.is_symlink():
                dirs.remove(dirname)
                errors.append({"file": str(candidate), "error": "Symlink-Verzeichnis übersprungen"})
        for name in names:
            candidate = current / name
            # Codex: nur Sitzungs-JSONL sichern, keine eventuellen Hilfsdateien.
            if SOURCE == "codex" and candidate.suffix.lower() != ".jsonl":
                continue
            relative = candidate.relative_to(root)
            try:
                _regular_stat(candidate)
                _describe(relative)  # Provider-Profil schon vor dem Kopieren prüfen.
                files.append(candidate)
            except (OSError, ValueError) as exc:
                errors.append({"file": str(relative.as_posix()), "error": _safe_error(exc)})
    return sorted(files), errors


def _describe(relative: Path) -> dict[str, Any]:
    """Das einzige quellenspezifische Layoutprofil beider Filesystem-Updater."""
    parts = relative.parts
    if SOURCE == "codex":
        if (len(parts) != 4 or not re.fullmatch(r"\d{4}", parts[0])
                or not re.fullmatch(r"\d{2}", parts[1])
                or not re.fullmatch(r"\d{2}", parts[2])):
            raise ValueError("Codex-Sitzung erwartet: sessions/YYYY/MM/DD/<datei>.jsonl")
        try:
            date(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError as exc:
            raise ValueError("Ungültiger Datums-Bucket der Codex-Sitzung") from exc
        if relative.suffix.lower() != ".jsonl":
            raise ValueError("Nur JSONL-Dateien innerhalb von Codex/sessions werden gespiegelt")
        match = UUID_AT_END.search(relative.stem)
        return {"kind": "session", "session_id": match.group(1) if match else relative.stem,
                "session_role": "root", "date_bucket": "/".join(parts[:3])}

    # Claude: alle regulären Dateien innerhalb von projects/<projekt>/...
    # einschl. memory/, subagents/ und <session>/tool-results/ bytegetreu behalten.
    if len(parts) < 2 or not parts[0]:
        raise ValueError("Claude-Datei erwartet: projects/<projekt>/<relativer_pfad>")
    is_jsonl = relative.suffix.lower() == ".jsonl"
    is_subagent = "subagents" in parts[1:-1]
    is_main_session = len(parts) == 2 and is_jsonl
    is_session = is_main_session or (is_jsonl and is_subagent)
    return {
        "kind": "session" if is_session else "artifact",
        "session_id": relative.stem if is_session else None,
        "session_role": "subagent" if is_subagent and is_session else "root" if is_session else None,
        "project_folder": parts[0],
    }


def _file_signature(st: os.stat_result) -> tuple[int, int]:
    return (st.st_size, st.st_mtime_ns)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_jsonl(path: Path) -> tuple[int, dict[str, Any]]:
    """JSONL vollständig lesen; ungültige/abgeschnittene Zeilen verhindern Commit."""
    count = 0
    first: dict[str, Any] = {}
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Ungültige JSONL-Zeile {line_number}: {exc.msg}") from exc
            if not isinstance(data, dict):
                raise ValueError(f"JSONL-Zeile {line_number} ist kein Objekt")
            count += 1
            if count == 1:
                first = data
    if count == 0:
        raise ValueError("Leere JSONL-Sitzung")
    return count, first


def _needs_copy(source: Path, destination: Path, verify_unchanged: bool) -> str:
    """'new', 'changed' oder 'unchanged'; vergleicht zunächst stat-Daten."""
    current = _regular_stat(source)
    try:
        previous = _regular_stat(destination)
    except FileNotFoundError:
        return "new"
    if _file_signature(current) != _file_signature(previous):
        return "changed"
    if verify_unchanged and _sha256(source) != _sha256(destination):
        return "changed"
    return "unchanged"


def _atomic_copy(cfg: Config, source: Path, destination: Path, *, validate_jsonl: bool) -> None:
    """Snapshot kopieren, Stabilität prüfen, ggf. erneut versuchen, atomar committen."""
    cfg.staging_root.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(cfg.max_retries + 1):
        temporary: Path | None = None
        try:
            before = _regular_stat(source)
            with tempfile.NamedTemporaryFile(mode="wb", prefix=f"{SOURCE}_", suffix=".tmp",
                                             dir=cfg.staging_root, delete=False) as handle:
                temporary = Path(handle.name)
            # copy2 erhält Größe/mtime (ns), damit spätere Updates ohne weiteres
            # Manifest anhand der Quelldatei verglichen werden können.
            shutil.copy2(source, temporary, follow_symlinks=False)
            after = _regular_stat(source)
            staged = _regular_stat(temporary)
            if _file_signature(before) != _file_signature(after) or _file_signature(after) != _file_signature(staged):
                if attempt < cfg.max_retries:
                    time.sleep(0.1 * (attempt + 1))
                    continue
                raise ValueError("Quelldatei hat sich während des Kopierens verändert")
            if validate_jsonl:
                _validate_jsonl(temporary)
            # Der Inhalt des Staging-Snapshots liegt vollständig auf dem Datenträger,
            # bevor er unter dem Zielnamen sichtbar wird. (Hinweis: fsync braucht
            # unter Windows ein schreibbares Handle, daher "r+b" statt "rb".)
            with temporary.open("r+b") as handle:
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            temporary = None
            return
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    raise ProviderError("Unerwarteter Fehler beim Snapshot-Kopieren")


def _blank_stats() -> dict[str, int]:
    return {k: 0 for k in (
        "sessions_total", "sessions_new", "sessions_changed", "sessions_unchanged",
        "sessions_fetched", "sessions_failed", "files_materialized", "files_failed",
        "files_total", "files_new", "files_changed", "files_unchanged",
    )}


def update(config: Config | Mapping[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    """Dateibasiert inkrementell sichern; zurückgeben: {ok,stats,errors,exit_code}.

    Die Funktion schreibt absichtlich KEIN eigenes Run-Manifest/Globalindex –
    das übernimmt im eingebundenen Betrieb der Raw Session Updater.
    """
    cfg = _config(config)
    # Nicht versehentlich aus raw_storage zurück nach raw_storage spiegeln.
    source = cfg.source_data_root.resolve()
    raw = cfg.raw_root.resolve()
    if source == raw or raw in source.parents or source in raw.parents:
        raise ProviderError("Quellordner und Raw-Storage dürfen nicht ineinander liegen")
    files, scan_errors = _source_files(cfg)
    stats = _blank_stats()
    errors = list(scan_errors)
    stats["files_failed"] = len(scan_errors)
    # Nachvollziehbarkeit im Laufbericht: was wurde (bzw. wuerde bei dry_run)
    # gespeichert? Unveraenderte Dateien werden nicht aufgefuehrt.
    fetched: list[dict[str, str]] = []

    for src in files:
        rel = src.relative_to(cfg.source_data_root)
        meta = _describe(rel)
        is_session = meta["kind"] == "session"
        stats["sessions_total" if is_session else "files_total"] += 1
        dst = cfg.raw_data_root / rel
        try:
            action = _needs_copy(src, dst, cfg.verify_unchanged)
            if is_session:
                stats[f"sessions_{action}"] += 1
            else:
                stats[f"files_{action}"] += 1
            if action == "unchanged":
                continue
            if dry_run:
                fetched.append({"id": rel.as_posix(), "kind": meta["kind"], "action": action,
                                "dry_run": "true"})
                continue
            _atomic_copy(cfg, src, dst, validate_jsonl=(src.suffix.lower() == ".jsonl"))
            fetched.append({"id": rel.as_posix(), "kind": meta["kind"], "action": action})
            if is_session:
                stats["sessions_fetched"] += 1
            else:
                stats["files_materialized"] += 1
        except (OSError, ValueError, UnicodeError, OverflowError) as exc:
            stats["sessions_failed" if is_session else "files_failed"] += 1
            errors.append({"file": rel.as_posix(), "error": _safe_error(exc)})

    return {
        "source": SOURCE, "ok": not errors, "stats": stats,
        "errors": errors, "exit_code": 1 if errors else 0, "dry_run": dry_run,
        "items": {"fetched": fetched,
                  "failed": [{"id": e.get("file"), "error": e.get("error")} for e in errors]},
    }


def _scan_raw(cfg: Config) -> tuple[dict[str, dict[str, Any]], list[dict[str, str]]]:
    """Index und Health basieren ausschließlich auf bereits committed Raw-Dateien."""
    known: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []
    if not cfg.raw_data_root.exists():
        return known, errors

    def onerror(exc: OSError) -> None:
        errors.append({"file": str(exc.filename or cfg.raw_data_root), "error": _safe_error(exc)})

    for parent, dirs, names in os.walk(cfg.raw_data_root, followlinks=False, onerror=onerror):
        folder = Path(parent)
        for dirname in list(dirs):
            candidate = folder / dirname
            if candidate.is_symlink():
                dirs.remove(dirname)
                errors.append({"file": str(candidate), "error": "Symlink-Verzeichnis im Raw-Storage"})
        for name in sorted(names):
            path = folder / name
            relative = path.relative_to(cfg.raw_data_root)
            key = relative.as_posix()
            try:
                st = _regular_stat(path)
                meta = _describe(relative)
                count = None
                first: dict[str, Any] = {}
                if path.suffix.lower() == ".jsonl":
                    count, first = _validate_jsonl(path)
                known[key] = {
                    "path": path, "relative": relative, "meta": meta, "stat": st,
                    "sha256": _sha256(path), "record_count": count, "first": first,
                }
            except (OSError, ValueError, UnicodeError, OverflowError) as exc:
                errors.append({"file": f"{SOURCE}/{SOURCE_SUBDIR}/{key}", "error": _safe_error(exc)})
    return known, errors


def recreate_index(config: Config | Mapping[str, Any]) -> dict[str, Any]:
    """Liefert nur Provider-Fragment für den atomaren Merge durch den Raw Session Updater."""
    cfg = _config(config)
    known, errors = _scan_raw(cfg)
    entries: dict[str, Any] = {}
    for key, item in known.items():
        meta = item["meta"]
        st = item["stat"]
        relative_path = f"{SOURCE}/{SOURCE_SUBDIR}/{key}"
        entry: dict[str, Any] = {
            "source": SOURCE, "kind": meta["kind"],
            "relative_path": relative_path,
            "file_sha256": item["sha256"],
            "file_size": st.st_size,
            "file_mtime_ns": st.st_mtime_ns,
            "raw_integrity_ok": True,
            "acquisition_source": "filesystem_copy",
        }
        if meta["kind"] == "session":
            entry.update({
                "session_id": meta["session_id"],
                "session_role": meta["session_role"],
                "json_complete": True,
                "fetch_complete": True,
                "record_count": item["record_count"],
            })
            if SOURCE == "codex":
                entry["date_bucket"] = meta["date_bucket"]
                payload = item["first"].get("payload")
                if item["first"].get("type") == "session_meta" and isinstance(payload, dict):
                    if isinstance(payload.get("id"), str) and payload["id"]:
                        entry["session_id"] = payload["id"]
                    if payload.get("timestamp") is not None:
                        entry["create_time"] = payload["timestamp"]
                    if payload.get("cwd") is not None:
                        entry["original_cwd"] = payload["cwd"]
            else:
                entry["project_folder"] = meta["project_folder"]
                if item["first"].get("timestamp") is not None:
                    entry["create_time"] = item["first"]["timestamp"]
        else:
            entry["project_folder"] = meta["project_folder"]
        entries[f"{SOURCE}:{meta['kind']}:{key}"] = entry
    candidates = len(known) + len(errors)
    return {
        "fragment_schema_version": 1,
        "source": SOURCE, "generated_at": _utc_now(), "candidates": candidates,
        "indexed": len(known),
        "coverage_percent": round(100.0 * len(known) / candidates, 2) if candidates else 100.0,
        "failed_files": errors, "entries": entries, "file_refs": {},
        "coverage": {"percent": round(100.0 * len(known) / candidates, 2) if candidates else 100.0},
    }


def check_storage_health(config: Config | Mapping[str, Any]) -> dict[str, Any]:
    """Read-only: Layout, JSONL-Syntax, reguläre Dateien und Lesbarkeit prüfen."""
    cfg = _config(config)
    known, errors = _scan_raw(cfg)
    sessions = sum(item["meta"]["kind"] == "session" for item in known.values())
    return {
        "source": SOURCE, "ok": not errors,
        "stats": {"sessions_valid": sessions, "files_valid": len(known) - sessions,
                  "files_invalid": len(errors)},
        "errors": errors, "exit_code": 1 if errors else 0,
    }


def cleanup_storage(config: Config | Mapping[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    """Nur eigene Staging-*.tmp ab 24 h und leere Ordner; NIEMALS Raw-Dateien."""
    cfg = _config(config)
    removed: list[str] = []
    errors: list[dict[str, str]] = []
    now = time.time()
    if cfg.staging_root.exists():
        for path in cfg.staging_root.rglob("*.tmp"):
            try:
                st = path.lstat()
                if not stat.S_ISREG(st.st_mode) or now - st.st_mtime < STALE_TMP_SECONDS:
                    continue
                removed.append(str(path))
                if not dry_run:
                    path.unlink()
            except OSError as exc:
                errors.append({"file": str(path), "error": _safe_error(exc)})
    for root in (cfg.staging_root, cfg.raw_data_root):
        if root.exists():
            for folder in sorted((p for p in root.rglob("*") if p.is_dir() and not p.is_symlink()),
                                 key=lambda p: len(p.parts), reverse=True):
                try:
                    if not any(folder.iterdir()):
                        removed.append(str(folder))
                        if not dry_run:
                            folder.rmdir()
                except OSError as exc:
                    errors.append({"file": str(folder), "error": _safe_error(exc)})
    return {"source": SOURCE, "ok": not errors, "dry_run": dry_run,
            "candidates": len(removed), "paths": removed, "errors": errors,
            "exit_code": 1 if errors else 0}


def state_n_stats(config: Config | Mapping[str, Any]) -> dict[str, Any]:
    """Read-only Snapshot, ohne selbst OVERVIEW.md oder globale Indizes anzufassen."""
    cfg = _config(config)
    known, errors = _scan_raw(cfg)
    sessions = [item for item in known.values() if item["meta"]["kind"] == "session"]
    role_counts = {"root": 0, "subagent": 0}
    for item in sessions:
        role_counts[item["meta"]["session_role"]] += 1
    return {
        "source": SOURCE, "generated_at": _utc_now(),
        "sessions_total": len(sessions), "sessions_root": role_counts["root"],
        "sessions_child": role_counts["subagent"],
        "files_total": len(known) - len(sessions),
        "bytes_total": sum(item["stat"].st_size for item in known.values()),
        "files_invalid": len(errors), "ok": not errors, "errors": errors,
        "exit_code": 1 if errors else 0,
    }


def _atomic_write_bytes(cfg: Config, destination: Path, payload: bytes) -> None:
    cfg.staging_root.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=f"{SOURCE}_", suffix=".tmp",
                                         dir=cfg.staging_root, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _standalone_run_manifest(cfg: Config, report: dict[str, Any], started_at: str) -> Path:
    """Nur per CLI: Schema v4, eine Datei pro Standalone-Lauf."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    stats = report.get("stats") or _blank_stats()
    manifest = {
        "schema_version": 4, "run_id": stamp, "kind": "update",
        "started_at": started_at, "finished_at": _utc_now(),
        "partial": report.get("exit_code") == 2,
        "sources": {SOURCE: {"ok": report.get("ok", False), "stats": stats,
                             "errors": report.get("errors", [])}},
        "totals": {k: stats.get(k, 0) for k in (
            "sessions_total", "sessions_fetched", "sessions_failed",
            "files_materialized", "files_failed")},
        "errors": report.get("errors", []),
    }
    path = cfg.runtime_root / "runs" / f"sync_{stamp}.json"
    _atomic_write_bytes(cfg, path, json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Claude Code: inkrementeller Raw-Storage-Updater")
    parser.add_argument("--config", type=Path, help="YAML (Standard: config.yaml neben dem Skript)")
    parser.add_argument("--data-root", type=Path, help="Überschreibt storage.data_root")
    parser.add_argument("--source-root", type=Path, help="Überschreibt providers.claude.source_root")
    parser.add_argument("--retries", type=int, help="Maximale Wiederholungen bei aktiven Quelldateien")
    parser.add_argument("--verify-unchanged", action="store_true",
                        help="Auch bei gleicher Größe/mtime SHA-256 vergleichen (langsamer, robuster)")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("update", "recreate-index", "check-health", "cleanup", "stats"):
        p = sub.add_parser(command)
        if command in ("update", "cleanup"):
            p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        config_path = args.config if args.config is not None else DEFAULT_CONFIG_FILE
        if args.config is not None or config_path.is_file():
            values = load_provider_config(config_path)
        else:
            values = {}
        if args.data_root is not None:
            values.pop("raw_root", None)
            values.pop("runtime_root", None)
            values["data_root"] = args.data_root
        if args.source_root is not None:
            values["source_root"] = args.source_root
        if args.retries is not None:
            values["max_retries"] = args.retries
        if args.verify_unchanged:
            values["verify_unchanged"] = True
        cfg = _config(values)
    except (ProviderError, OSError, TypeError, ValueError) as exc:
        parser.error(_safe_error(exc))

    started_at = _utc_now()
    try:
        if args.command == "update":
            report = update(cfg, dry_run=args.dry_run)
            if not args.dry_run:
                report["run_manifest"] = str(_standalone_run_manifest(cfg, report, started_at))
        elif args.command == "recreate-index":
            report = recreate_index(cfg)
        elif args.command == "check-health":
            report = check_storage_health(cfg)
        elif args.command == "cleanup":
            report = cleanup_storage(cfg, dry_run=args.dry_run)
        else:
            report = state_n_stats(cfg)
    except (ProviderError, OSError, ValueError, UnicodeError) as exc:
        report = {"source": SOURCE, "ok": False,
                  "errors": [{"error": _safe_error(exc)}], "exit_code": 2}
        if args.command == "update" and not args.dry_run:
            try:
                report["run_manifest"] = str(_standalone_run_manifest(cfg, report, started_at))
            except OSError:
                pass
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return int(report.get("exit_code", 0))


if __name__ == "__main__":
    sys.exit(main())
