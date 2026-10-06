"""Zustandswerte des Storages sammeln und ``state.yaml`` erzeugen.

Liegt in der Bedienschicht, weil nur sie Raw Session Updater (Laufbericht,
Gesamtindex), Zeitplanung und Konfiguration zugleich kennen darf. Wirft nie:
Zustand ist Information, ein Fehler hier darf keinen Befehl scheitern lassen.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import chatexporter.config as shared_config
from chatexporter import __version__
from chatexporter.config import state as state_mod
from chatexporter.raw_session_updater.registry import KNOWN_SOURCES

#: Befehle, nach denen der naechste geplante Lauf neu gelesen wird.
SCHEDULE_COMMANDS = frozenset({"update", "task", "setup"})


def _usable(config: Path | None):
    loaded = shared_config.load(config)
    status = shared_config.storage_status(loaded)
    if status["identity"] is None:
        return None
    return loaded, status["storage"], status["identity"]


def base_values(loaded: Any, storage: Any, identity: Any, command: str, exit_code: int | None,
                line: str | None = None) -> dict[str, Any]:
    sources = loaded.get("raw_session_updater.sources") or []
    values: dict[str, Any] = {
        "storage.id": identity.id, "storage.name": identity.name, "storage.storage_schema": identity.storage_schema,
        "storage.created_at": identity.created_at, "storage.root": str(storage.root),
        "storage.program_version": __version__,
        "storage.last_command": line or command, "storage.last_command_at": state_mod.now_iso(),
        "storage.last_command_exit": exit_code,
    }
    for source in KNOWN_SOURCES:
        values[f"providers.{source}.enabled"] = source in sources
    return values


def index_totals(storage: Any) -> dict[str, Any]:
    """Bestand je Quelle aus dem Gesamtindex (Betriebsdatei des Storages)."""
    path = storage.status_dir / "storage_index.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8")).get("conversations") or {}
    except (OSError, ValueError):
        return {}
    sessions: dict[str, int] = {}
    files: dict[str, int] = {}
    for entry in entries.values():
        source = str(entry.get("source") or "unbekannt")
        if entry.get("kind", "session") in ("session", "conversation"):
            sessions[source] = sessions.get(source, 0) + 1
        else:                                   # z. B. Artefakte von Claude Code zaehlen als Dateien
            files[source] = files.get(source, 0) + 1
        files[source] = files.get(source, 0) + int(entry.get("file_materialized_count") or 0)
    out: dict[str, Any] = {}
    for source in sorted(set(sessions) | set(files)):
        out[f"providers.{source}.total_sessions"] = sessions.get(source, 0)
        out[f"providers.{source}.total_files"] = files.get(source, 0)
    return out


def update_values(manifest: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, Any]:
    """Zustand nach einem ``update`` (Zaehler, Ergebnis, Bestand, erster vollstaendiger Abruf)."""
    finished = manifest.get("finished_at") or state_mod.now_iso()
    sources = manifest.get("sources") or {}
    all_ok = bool(sources) and all(section.get("ok") for section in sources.values())
    values: dict[str, Any] = {
        "storage.update_counter": int(previous.get("storage.update_counter") or 0) + 1,
        "storage.update_last": finished,
        "storage.update_last_result": "ok" if all_ok and not manifest.get("partial") else
        ("teilweise" if any(s.get("ok") for s in sources.values()) else "fehler"),
    }
    stopped_open = 0
    fetched = 0
    complete = all_ok and not manifest.get("partial")
    for source, section in sources.items():
        detail = section.get("detail") if isinstance(section.get("detail"), dict) else {}
        limit = detail.get("rate_limit") if isinstance(detail.get("rate_limit"), dict) else {}
        stats = section.get("stats") if isinstance(section.get("stats"), dict) else {}
        values[f"providers.{source}.update_last"] = section.get("finished_at") or finished
        values[f"providers.{source}.update_last_result"] = "ok" if section.get("ok") else "fehler"
        if "sessions_total" in stats:
            values[f"providers.{source}.total_sessions"] = stats["sessions_total"]
        if "files_total" in stats:
            values[f"providers.{source}.total_files"] = stats["files_total"]
        if limit.get("stopped") or detail.get("aborted"):
            complete = False
        if limit.get("stopped"):
            stopped_open += int(limit.get("open_conversations") or 0)
            fetched += int(stats.get("sessions_fetched") or stats.get("fetched") or 0)
    if not previous.get("storage.first_fetch.completed"):
        parts = int(previous.get("storage.first_fetch.parts_completed") or 0) + 1
        values["storage.first_fetch.parts_completed"] = parts
        values["storage.first_fetch.completed"] = complete
        if complete:
            values["storage.first_fetch.completed_at"] = finished
            values["storage.first_fetch.parts_total"] = parts
        elif stopped_open and fetched:
            # Schaetzung: so viele weitere Teillaeufe wie dieser Lauf geschafft hat
            values["storage.first_fetch.parts_total"] = parts + math.ceil(stopped_open / fetched)
    return values


def next_scheduled(config: Path | None, service_factory: Any = None) -> str | None:
    """Naechster geplanter ``update``-Lauf dieses Storages (aus der Windows-Aufgabenplanung)."""
    from chatexporter.task_scheduler.config import load_config
    from chatexporter.task_scheduler.service import TaskService
    service = (service_factory or TaskService)(load_config(config))
    times = sorted(view["next_run"] for view in service.list()
                   if view.get("next_run") and str(view.get("command") or "").startswith("update")
                   and view.get("enabled") is not False)
    return times[0] if times else None


def record_update(manifest: Mapping[str, Any], config: Path | None) -> None:
    try:
        usable = _usable(config)
        if usable is None:
            return
        _loaded, storage, identity = usable
        previous = state_mod.store_for(identity).read()
        state_mod.record(storage, identity, update_values(manifest, previous))
    except Exception:  # noqa: BLE001
        pass


def after_command(config: Path | None, command: str, exit_code: int | None, *, line: str | None = None,
                  service_factory: Any = None) -> Path | None:
    """Nach jedem Befehl: Grundwerte und ggf. Bestand/Zeitplan aktualisieren, ``state.yaml`` schreiben."""
    try:
        usable = _usable(config)
        if usable is None:
            return None
        loaded, storage, identity = usable
        values = base_values(loaded, storage, identity, command, exit_code, line)
        previous = state_mod.store_for(identity).read()
        for key, value in index_totals(storage).items():
            if command != "update" or key not in previous:
                values[key] = value
        if command in SCHEDULE_COMMANDS:
            try:
                values["storage.update_next_scheduled_at"] = next_scheduled(config, service_factory)
            except Exception:  # noqa: BLE001  ohne pywin32/Windows: Wert bleibt, wie er war
                pass
        state_mod.record(storage, identity, values)
        return state_mod.write_state_file(loaded, storage, identity, version=__version__)
    except Exception:  # noqa: BLE001
        return None
