"""Automatische Fortsetzung nach einem Rate-Limit-Stopp.

Endet ein Update regulaer am Rate-Limit (typisch beim Erstabruf: nach rund 200
Konversationen ist das Kontingent leer), plant die Bedienschicht eine einmalige
Windows-Aufgabe, die das Update nach dem geschaetzten Wiederauffuellen
fortsetzt. Diese Fortsetzung landet wieder hier: Ist erneut ein Limit erreicht,
wird sie neu terminiert; ist alles geladen, wird die Aufgabe entfernt. So laeuft
der Abruf ohne Zutun weiter, bis alle Daten da sind.

Liegt in der Bedienschicht, weil nur sie Raw Session Updater und Zeitplanung
kennen darf. Ein Fehler hier bricht das Update nie ab; er wird gemeldet und im
Befehlsprotokoll vermerkt.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

SLUG_PREFIX = "fortsetzung"

Say = Callable[[str], None]


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def decide(manifest: dict[str, Any], *, margin_minutes: int, now: datetime | None = None,
           fixed_delay_minutes: int | None = None) -> dict[str, dict[str, Any]]:
    """Was je Quelle zu tun ist: ``schedule`` (mit Zeitpunkt), ``finish`` oder nichts.

    - ``schedule``: Lauf endete regulaer am Rate-Limit (``detail.rate_limit.stopped``).
    - ``finish``: Quelle ok, nicht abgebrochen, kein Limit-Stopp -> eine evtl.
      vorhandene Fortsetzung ist erledigt.
    - Abbrueche und Fehler aendern nichts (eine geplante Fortsetzung bleibt).
    """
    now = now or datetime.now(timezone.utc)
    out: dict[str, dict[str, Any]] = {}
    for source, section in (manifest.get("sources") or {}).items():
        detail = section.get("detail") if isinstance(section.get("detail"), dict) else {}
        limit = detail.get("rate_limit") if isinstance(detail.get("rate_limit"), dict) else {}
        if limit.get("stopped"):
            full_at = _parse_utc(limit.get("estimated_full_at")) or now
            when = max(full_at, now) + timedelta(minutes=max(0, margin_minutes))
            if fixed_delay_minutes is not None:      # Entwicklungsmodus: feste kurze Pause
                when = now + timedelta(minutes=fixed_delay_minutes)
            out[source] = {"action": "schedule", "at_utc": when,
                           "open_conversations": limit.get("open_conversations")}
        elif section.get("ok") and not detail.get("aborted"):
            out[source] = {"action": "finish"}
    return out


def _local_minute(when_utc: datetime) -> str:
    return when_utc.astimezone().strftime("%Y-%m-%d %H:%M")


def _command_for(source: str, template: str) -> str:
    if source == "chatgpt":
        return template
    return f"update --source {source} --non-interactive"


def after_update(manifest: dict[str, Any], config_file: Path | None, *, say: Say = print,
                 service_factory: Callable[[Any], Any] | None = None,
                 now: datetime | None = None) -> dict[str, Any]:
    """Nach einem Update: Fortsetzung planen oder aufraeumen. Gibt eine kurze Zusammenfassung zurueck."""
    try:
        import chatexporter.config as shared_config
        loaded = shared_config.load(config_file)
        section = loaded.resolved.section("task_scheduler").get("continuation") or {}
        if not section.get("enabled", True):
            return {"continuation": "aus"}
        fixed = None
        if loaded.get("dev_mode"):
            from chatexporter.config.dev import from_values
            fixed = from_values(loaded.get).continuation_delay_minutes
        decisions = decide(manifest, margin_minutes=int(section.get("margin_minutes") or 0), now=now,
                           fixed_delay_minutes=fixed)
        if not decisions:
            return {}
        from chatexporter.task_scheduler.config import load_config
        from chatexporter.task_scheduler.service import TaskService, TaskServiceError, build_trigger
        service = (service_factory or TaskService)(load_config(config_file))
        summary: dict[str, Any] = {}
        for source, decision in decisions.items():
            slug = f"{SLUG_PREFIX}-{source}"
            existing = None
            try:
                existing = service.get(slug)
            except TaskServiceError:
                existing = None
            if decision["action"] == "schedule":
                trigger = build_trigger(once=_local_minute(decision["at_utc"]))
                command = _command_for(source, str(section.get("command") or ""))
                if existing:
                    service.update(slug, trigger=trigger, command=command)
                    if existing.get("enabled") is False:
                        service.resume(slug)
                else:
                    service.create(f"Fortsetzung {source}", slug=slug, command=command, trigger=trigger,
                                   description=f"ChatExporter: Abruf von {source} nach dem Rate-Limit fortsetzen")
                at = _local_minute(decision["at_utc"])
                open_count = decision.get("open_conversations")
                say(f"Fortsetzung geplant: {source} am {at} (Aufgabe '{slug}'"
                    + (f", {open_count} Konversationen offen)" if open_count is not None else ")"))
                summary[f"continuation_{source}"] = f"geplant {at}"
            elif existing:
                service.delete(slug)
                say(f"Abruf von {source} vollstaendig: Fortsetzungsaufgabe '{slug}' entfernt.")
                summary[f"continuation_{source}"] = "abgeschlossen"
        return summary
    except Exception as exc:  # noqa: BLE001  die Fortsetzung darf das Update nie scheitern lassen
        message = f"{type(exc).__name__}: {exc}"
        say(f"Hinweis: automatische Fortsetzung nicht geplant ({message})")
        return {"continuation_error": message}
