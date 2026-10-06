"""Befehlsprotokoll: jeder ausgefuehrte Befehl als ein JSON-Datensatz.

- Ziel: ``logging.dir`` (Default ``<storage>/.storage/logs``), eine Datei je
  Zeitraum ``logging.rotation`` (Default ``24h``), Format JSON Lines
  (``commands_<Periodenbeginn UTC>.jsonl``).
- Aufraeumen: Dateien, deren Zeitraum laenger als ``logging.retention``
  (Default ``30d``; ``0`` = nie loeschen) zurueckliegt, werden entfernt.
- Dauerangaben: ``30s``, ``15m``, ``24h``, ``7d``, ``2w`` und Kombinationen
  wie ``1d12h``; eine reine Zahl bedeutet Sekunden.

Die Felder eines Datensatzes stehen in docs/BEFEHLE.md ("Befehlsprotokoll").
Das Protokoll ist Teil der Bedienschicht; es liest die Zusammenfassung aus dem
JSON-Bericht, den jeder Befehl am Ende ausgibt, und beim Update zusaetzlich aus
dem Laufbericht.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

LOG_PREFIX = "commands_"
LOG_SUFFIX = ".jsonl"
_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)


def parse_duration(value: Any) -> int:
    """Dauer in Sekunden: ``24h``, ``7d``, ``1d12h``, ``90`` (= Sekunden)."""
    if isinstance(value, bool):
        raise ValueError(f"Ungueltige Dauer: {value!r}")
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().lower().replace(" ", "")
    if text.isdigit():
        return int(text)
    parts = _DURATION_RE.findall(text)
    if not parts or "".join(n + u for n, u in parts) != text:
        raise ValueError(f"Ungueltige Dauer: {value!r} (erlaubt z. B. 30m, 24h, 7d, 1d12h)")
    return sum(int(n) * _UNITS[u] for n, u in parts)


@dataclass(slots=True)
class LogSettings:
    enabled: bool
    directory: Path
    rotation_seconds: int
    retention_seconds: int


def load_settings(config_file: Path | None) -> LogSettings:
    """Liest ``logging.*`` aus der gemeinsamen Konfiguration (Umgebung/CLI-Werte haben Vorrang)."""
    import chatexporter.config as shared_config
    loaded = shared_config.load(config_file)
    section = loaded.resolved.section("logging")
    enabled = bool(section.get("enabled", True))
    directory = shared_config.resolve_path(loaded, section.get("dir"), "logging.dir")
    if directory is None:
        if shared_config.storage_status(loaded)["identity"] is None:
            enabled = False      # alter/unklarer Ordner: nichts hineinschreiben
        directory = shared_config.storage_of(loaded).logs_dir
    rotation = parse_duration(section.get("rotation") or "24h")
    retention = parse_duration(section.get("retention") if section.get("retention") is not None else "30d")
    if rotation <= 0:
        raise ValueError("logging.rotation muss groesser als 0 sein")
    return LogSettings(enabled=enabled, directory=directory,
                       rotation_seconds=rotation, retention_seconds=max(0, retention))


def period_start(now: datetime, rotation_seconds: int) -> datetime:
    """Beginn des Zeitraums (UTC, an der Epoche ausgerichtet; 24h = Tagesgrenze UTC)."""
    stamp = int(now.timestamp())
    return datetime.fromtimestamp(stamp - stamp % rotation_seconds, tz=timezone.utc)


def log_file_for(settings: LogSettings, now: datetime) -> Path:
    start = period_start(now, settings.rotation_seconds)
    return settings.directory / f"{LOG_PREFIX}{start.strftime('%Y%m%dT%H%MZ')}{LOG_SUFFIX}"


def prune(settings: LogSettings, now: datetime) -> list[Path]:
    """Entfernt Logdateien, deren Zeitraum vor mehr als ``retention`` endete."""
    if settings.retention_seconds <= 0 or not settings.directory.is_dir():
        return []
    removed = []
    cutoff = now - timedelta(seconds=settings.retention_seconds)
    for path in settings.directory.glob(f"{LOG_PREFIX}*{LOG_SUFFIX}"):
        stem = path.name[len(LOG_PREFIX):-len(LOG_SUFFIX)]
        try:
            start = datetime.strptime(stem, "%Y%m%dT%H%MZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue  # fremde Datei: nie anfassen
        if start + timedelta(seconds=settings.rotation_seconds) < cutoff:
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                pass
    return removed


# -- Zusammenfassung aus Bericht und Laufbericht ------------------------------------

_SOURCE_FIELDS = ("sessions_total", "sessions_new", "sessions_changed", "sessions_unchanged",
                  "sessions_fetched", "sessions_failed", "files_materialized", "files_failed",
                  "requests_total", "verify_mismatches")


def _last_json_report(text: str) -> dict[str, Any] | None:
    """Der JSON-Bericht, den jeder Befehl am Ende ausgibt (letztes '{' am Zeilenanfang)."""
    lines = text.splitlines()
    for start in range(len(lines) - 1, -1, -1):
        if lines[start].startswith("{"):
            try:
                value = json.loads("\n".join(lines[start:]))
            except json.JSONDecodeError:
                continue
            return value if isinstance(value, dict) else None
    return None


def _scalars(value: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in value.items() if isinstance(v, (str, int, float, bool)) or v is None}


def summarize(report: dict[str, Any] | None) -> dict[str, Any]:
    """Felder der Uebersicht: Gesamtwerte und je Quelle dieselben Angaben wie
    die Konsolen-Zusammenfassung (beim Update aus dem Laufbericht)."""
    if not report:
        return {}
    summary: dict[str, Any] = _scalars(report)
    totals = report.get("totals")
    if isinstance(totals, dict):
        summary["totals"] = _scalars(totals)
    manifest_path = report.get("run_manifest")
    sources = report.get("sources")
    if isinstance(manifest_path, str) and Path(manifest_path).is_file():
        try:
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            sources = manifest.get("sources")
            summary.setdefault("partial", manifest.get("partial"))
        except (OSError, ValueError):
            pass
    if isinstance(sources, dict):
        per_source: dict[str, Any] = {}
        for name, section in sources.items():
            if not isinstance(section, dict):
                continue
            stats = section.get("stats") if isinstance(section.get("stats"), dict) else {}
            row: dict[str, Any] = {"ok": section.get("ok")}
            row.update({k: stats[k] for k in _SOURCE_FIELDS if k in stats})
            for key in ("duration_seconds", "error_count", "warning_count", "sessions_total",
                        "conversations", "dry_run", "error"):
                if key in section and key not in row:
                    row[key] = section[key]
            items = section.get("items")
            if isinstance(items, dict):
                row["items_fetched"] = len(items.get("fetched") or [])
                row["items_failed"] = len(items.get("failed") or [])
            detail = section.get("detail") if isinstance(section.get("detail"), dict) else {}
            listing = detail.get("listing") if isinstance(detail.get("listing"), dict) else {}
            if listing:
                row["listing_mode"] = listing.get("mode")
                row["listing_effective"] = listing.get("effective")
                if listing.get("escalation"):
                    row["listing_escalation"] = listing.get("escalation")
            if detail.get("abort_stage"):
                row["abort_stage"] = detail.get("abort_stage")
            per_source[name] = row
        summary["sources"] = per_source
    return summary


# -- Ausfuehren und protokollieren ----------------------------------------------------

class _Tee(io.TextIOBase):
    """Schreibt in die Konsole UND merkt sich die Ausgabe fuer die Auswertung."""

    def __init__(self, target: Any):
        self.target = target
        self.buffer_text = io.StringIO()

    def write(self, text: str) -> int:
        self.buffer_text.write(text)
        return self.target.write(text)

    def flush(self) -> None:
        self.target.flush()

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return getattr(self.target, "encoding", "utf-8")


def _config_from_argv(argv: list[str]) -> Path | None:
    for i, arg in enumerate(argv):
        if arg == "--config" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if arg.startswith("--config="):
            return Path(arg.split("=", 1)[1])
    return None


def run_logged(program: str, argv: list[str], run: Callable[[], int]) -> int:
    """Fuehrt ``run`` aus und schreibt danach einen Protokolldatensatz.

    Ein Fehler beim Protokollieren bricht nie den Befehl ab (nur Hinweis auf
    stderr). Strg+C wird mit Exitcode 130 protokolliert und weitergereicht.
    """
    from chatexporter.raw_session_updater.config import discover_config, program_info
    started = datetime.now(timezone.utc)
    clock = time.monotonic()
    tee = _Tee(sys.stdout)
    previous = sys.stdout
    sys.stdout = tee
    code: int | None = None
    interrupted = False
    try:
        code = int(run() or 0)
        return code
    except KeyboardInterrupt:
        interrupted = True
        code = 130
        raise
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
        raise
    finally:
        sys.stdout = previous
        try:
            config_file = discover_config(_config_from_argv(argv))
            settings = load_settings(config_file)
            if settings.enabled:
                now = datetime.now(timezone.utc)
                info = program_info()
                record = {
                    "timestamp": started.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "finished_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
                    "duration_seconds": round(time.monotonic() - clock, 1),
                    "command": " ".join([program, *argv]),
                    "program": program,
                    "argv": list(argv),
                    "exit_code": code,
                    "interrupted": interrupted,
                    "cwd": str(Path.cwd()),
                    "config_file": str(config_file) if config_file else None,
                    "version": info["version"],
                    "code_dir": info["code"],
                    "python": info["python"],
                    "summary": summarize(_last_json_report(tee.buffer_text.getvalue())),
                }
                settings.directory.mkdir(parents=True, exist_ok=True)
                with log_file_for(settings, now).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                prune(settings, now)
        except Exception as exc:  # noqa: BLE001 - Protokoll darf nie den Befehl kippen
            print(f"Hinweis: Befehlsprotokoll nicht geschrieben ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
