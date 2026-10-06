"""Aufgabenverwaltung: ChatExporter-Befehle als Windows-Aufgaben planen.

Eine Aufgabe ruft ``<python> -m chatexporter --config <config.yaml> --storage <storage> <befehl>``
auf (im gebauten Programm ``chatexporter.exe --config … --storage … <befehl>``). Jede
Aufgabe gehoert einem Storage (Eigentuemer ``chatexporter-<id>``). Die Windows-Seite (Aufgabenplanung, stabile IDs, State-Dateien) leistet
``scheduler_manager.py`` (PyTaskManager); hier liegt nur, was ChatExporter
dazu beitraegt: Befehlsaufbau, Standardwerte, Trigger-Eingaben, der
gespeicherte Plan (fuer ``update``) und die Ausgabeform.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping

from .backend import load_backend
from .config import TaskSchedulerConfig, TaskSetupError

#: Befehle, die geplant werden duerfen (Befehle der Bedienschicht ausser ``task`` selbst).
SCHEDULABLE_COMMANDS = ("update", "index", "check", "cleanup", "status", "export", "config",
                        "chatgpt", "opencode", "codex", "claude")

#: Schluessel unter ``metadata`` im State des PyTaskManagers.
RECORD_KEY = "chatexporter"

SETTING_KEYS = ("max_runtime_minutes", "start_when_available", "allow_on_battery",
                "wake_to_run", "multiple_instances", "hidden")
MULTIPLE_INSTANCES = ("parallel", "queue", "ignore_new", "stop_existing")

_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_DAYS = {"mo": "mo", "montag": "mo", "mon": "mo", "monday": "mo",
         "di": "di", "dienstag": "di", "tue": "di", "tues": "di", "tuesday": "di",
         "mi": "mi", "mittwoch": "mi", "wed": "mi", "wednesday": "mi",
         "do": "do", "donnerstag": "do", "thu": "do", "thur": "do", "thurs": "do", "thursday": "do",
         "fr": "fr", "freitag": "fr", "fri": "fr", "friday": "fr",
         "sa": "sa", "samstag": "sa", "sat": "sa", "saturday": "sa",
         "so": "so", "sonntag": "so", "sun": "so", "sunday": "so"}


class TaskServiceError(RuntimeError):
    """Fachlicher Fehler der Aufgabenverwaltung (Exitcode 1)."""


def _slug(text: str) -> str:
    """Kurzname wie im PyTaskManager (``_slugify``)."""
    import unicodedata
    value = str(text).strip().replace("ß", "ss")
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()[:80]


# -- Eingaben ----------------------------------------------------------------

def parse_command(value: str | list[str] | tuple[str, ...]) -> list[str]:
    """Befehl als Argumentliste. Erstes Wort muss ein planbarer Befehl sein."""
    if isinstance(value, str):
        import shlex
        # posix=False erhaelt Backslashes in Windows-Pfaden; Anfuehrungszeichen entfernen wir selbst.
        tokens = [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t
                  for t in shlex.split(value, posix=False)]
    else:
        tokens = [str(t) for t in value]
    if not tokens:
        raise TaskServiceError("Der Befehl ist leer.")
    if tokens[0] not in SCHEDULABLE_COMMANDS:
        raise TaskServiceError(f"Befehl nicht planbar: {tokens[0]!r} "
                               f"(erlaubt: {', '.join(SCHEDULABLE_COMMANDS)})")
    return tokens


def _check_time(value: str) -> str:
    match = _TIME.match(str(value).strip())
    if not match:
        raise TaskServiceError(f"Ungueltige Uhrzeit {value!r}; erwartet HH:MM, z. B. 03:00")
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def parse_days(value: str | list[str]) -> list[str]:
    items = [p.strip().lower() for p in (value.split(",") if isinstance(value, str) else value)
             if str(p).strip()]
    if not items:
        raise TaskServiceError("Wochentage fehlen (z. B. mo,mi,fr)")
    unknown = [i for i in items if i not in _DAYS]
    if unknown:
        raise TaskServiceError(f"Unbekannte Wochentage: {', '.join(unknown)} (erlaubt: mo di mi do fr sa so)")
    return list(dict.fromkeys(_DAYS[i] for i in items))


def build_trigger(*, daily: str | None = None, weekly: str | None = None, once: str | None = None,
                  logon: bool = False, startup: bool = False, days: str | list[str] | None = None,
                  every: int | None = None, delay: int | None = None) -> dict[str, Any] | None:
    """Trigger-Eingabe -> Mapping fuer den PyTaskManager; ``None`` wenn nichts angegeben."""
    chosen = [name for name, given in (("daily", daily), ("weekly", weekly), ("once", once),
                                       ("logon", logon), ("startup", startup)) if given]
    if len(chosen) > 1:
        raise TaskServiceError(f"Nur ein Trigger je Aufgabe: {', '.join(chosen)}")
    if not chosen:
        if days or every or delay:
            raise TaskServiceError("--days, --every und --delay brauchen einen Trigger "
                                   "(--daily, --weekly, --logon, --startup)")
        return None
    if every is not None and every < 1:
        raise TaskServiceError("--every muss mindestens 1 sein")
    if delay is not None and delay < 0:
        raise TaskServiceError("--delay darf nicht negativ sein")
    kind = chosen[0]
    if kind != "weekly" and days:
        raise TaskServiceError("--days gehoert nur zu --weekly")
    if kind in ("once",) and (every or delay):
        raise TaskServiceError("--every/--delay passen nicht zu --once")
    if kind in ("logon", "startup") and every:
        raise TaskServiceError("--every passt nicht zu --logon/--startup")
    if kind in ("daily", "weekly") and delay:
        raise TaskServiceError("--delay gehoert nur zu --logon/--startup")
    if kind == "daily":
        return {"type": "daily", "at": _check_time(daily), "every": every or 1}
    if kind == "weekly":
        return {"type": "weekly", "at": _check_time(weekly), "days": parse_days(days or []),
                "every": every or 1}
    if kind == "once":
        try:
            when = datetime.fromisoformat(str(once).strip())
        except ValueError:
            raise TaskServiceError(f"Ungueltiger Zeitpunkt {once!r}; erwartet JJJJ-MM-TT HH:MM") from None
        return {"type": "once", "when": when.strftime("%Y-%m-%d %H:%M")}
    return {"type": kind, "delay_seconds": delay or 0}


def normalize_trigger(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Prueft ein Trigger-Mapping (z. B. aus ``task_scheduler.defaults.trigger``)."""
    kind = str(spec.get("type") or "").strip().lower()
    if kind == "daily":
        return build_trigger(daily=spec.get("at"), every=int(spec.get("every") or 1))  # type: ignore[return-value]
    if kind == "weekly":
        return build_trigger(weekly=spec.get("at"), days=spec.get("days"),  # type: ignore[return-value]
                             every=int(spec.get("every") or 1))
    if kind == "once":
        return build_trigger(once=spec.get("when") or spec.get("at"))  # type: ignore[return-value]
    if kind in ("logon", "startup"):
        return build_trigger(**{kind: True}, delay=int(spec.get("delay_seconds") or 0))  # type: ignore[return-value]
    raise TaskServiceError(f"Unbekannter Trigger-Typ in den Standardwerten: {kind!r}")


def describe_trigger(spec: Mapping[str, Any] | None) -> str:
    if not spec:
        return "-"
    kind = spec.get("type")
    every = int(spec.get("every") or 1)
    if kind == "daily":
        return f"taeglich {spec.get('at')}" if every == 1 else f"alle {every} Tage {spec.get('at')}"
    if kind == "weekly":
        days = ",".join(spec.get("days") or [])
        prefix = "woechentlich" if every == 1 else f"alle {every} Wochen"
        return f"{prefix} {days} {spec.get('at')}"
    if kind == "once":
        return f"einmalig {spec.get('when')}"
    delay = int(spec.get("delay_seconds") or 0)
    label = {"logon": "bei Anmeldung", "startup": "bei Systemstart"}.get(str(kind), str(kind))
    return f"{label} (+{delay}s)" if delay else label


def _fmt_time(value: Any) -> str | None:
    if value is None:
        return None
    year = getattr(value, "year", None)
    if isinstance(year, int) and year < 2000:  # COM-Platzhalter "nie" (30.11.1999)
        return None
    if isinstance(value, datetime):
        # COM liefert Ortszeit, haengt aber UTC an: Zone weglassen.
        return value.replace(tzinfo=None).isoformat(timespec="seconds")
    return str(value)


# -- Dienst -----------------------------------------------------------------

class TaskService:
    """Legt ChatExporter-Aufgaben an und verwaltet sie.

    ``manager`` ist ein ``PyTaskManager``; ohne Angabe wird er beim ersten
    Zugriff aus ``scheduler_manager.py`` erzeugt (so brauchen Hilfe und
    Eingabepruefung weder Windows noch pywin32).
    """

    def __init__(self, config: TaskSchedulerConfig, *, manager: Any = None) -> None:
        self.config = config
        self._manager = manager
        self._backend: Any = None

    # Zugriff auf den PyTaskManager ------------------------------------------
    @property
    def manager(self) -> Any:
        if self._manager is None:
            self._backend = load_backend(self.config.manager_script)
            cfg = self.config
            try:
                self._manager = self._backend.PyTaskManager(
                    owner=cfg.owner, project_root=cfg.base, local_state_file=cfg.local_state_file,
                    global_state_file=cfg.global_state_file, folder=cfg.folder)
            except self._backend.TaskSchedulerError as exc:
                raise TaskSetupError(str(exc)) from exc
        return self._manager

    def _call(self, func, *args, **kwargs):
        """Ruft den PyTaskManager auf und uebersetzt seine Fehler."""
        _ = self.manager  # laedt das Backend, falls noetig
        errors: tuple[type[BaseException], ...] = (ValueError, TypeError)
        if self._backend is not None:
            errors += (self._backend.TaskSchedulerError,)
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as exc:
            raise TaskSetupError(str(exc)) from exc
        except errors as exc:
            raise TaskServiceError(str(exc)) from exc

    def _resolve(self, ref: str) -> dict[str, Any]:
        """Eintrag zu Kurzname, Name oder ID.

        Der PyTaskManager sucht Kurz- und Anzeigenamen nur im globalen State
        (``%LOCALAPPDATA%\\PyTaskManager``). Fehlt dort ein Eintrag (Datei geloescht
        oder zurueckgesetzt), steht die Aufgabe aber noch im lokalen State und in
        Windows; dann wird sie ueber den lokalen State gefunden.
        """
        try:
            return self._call(self.manager.resolve_entry, ref, owner=self.config.owner)
        except TaskServiceError:
            for info in self._local_infos():
                if ref in (info.task_id, info.slug, info.name) or info.slug == _slug(ref):
                    return self._call(self.manager.resolve_entry, info.task_id, owner=self.config.owner)
            raise

    def _local_infos(self) -> list[Any]:
        try:
            return list(self._call(self.manager.list, owner=self.config.owner, local_only=True))
        except TaskServiceError:   # z. B. aelterer Manager ohne local_only
            return []

    # Plan -----------------------------------------------------------------
    def _settings(self, given: Mapping[str, Any] | None, base: Mapping[str, Any] | None = None) -> dict[str, Any]:
        merged = {key: self.config.defaults.get(key) for key in SETTING_KEYS
                  if self.config.defaults.get(key) is not None}
        merged.update({k: v for k, v in (base or {}).items() if k in SETTING_KEYS})
        for key, value in (given or {}).items():
            if key not in SETTING_KEYS:
                raise TaskServiceError(f"Unbekannte Einstellung: {key}")
            if value is not None:
                merged[key] = value
        if merged.get("multiple_instances", "ignore_new") not in MULTIPLE_INSTANCES:
            raise TaskServiceError(f"multiple_instances muss einer von {', '.join(MULTIPLE_INSTANCES)} sein")
        runtime = merged.get("max_runtime_minutes")
        if runtime is not None and float(runtime) <= 0:
            raise TaskServiceError("max_runtime_minutes muss groesser als 0 sein")
        return merged

    def _payload(self, *, name: str, slug: str | None, record: Mapping[str, Any],
                 enabled: bool, task_id: str | None = None) -> dict[str, Any]:
        cfg = self.config
        command = list(record["command"])
        data: dict[str, Any] = {
            "name": name,
            "owner": cfg.owner,
            "executable": str(cfg.python),
            "arguments": [*cfg.launcher_args, "--config", str(cfg.config_file),
                          *(["--storage", str(cfg.storage_root)] if cfg.storage_root else []), *command],
            "working_directory": str(cfg.base),
            "trigger": dict(record["trigger"]),
            "description": record.get("description") or f"ChatExporter: {' '.join(command)}",
            "metadata": {RECORD_KEY: dict(record)},
            "enabled": enabled,
            **record.get("settings", {}),
        }
        if slug:
            data["slug"] = slug
        if task_id:
            data["task_id"] = task_id
        return data

    # Befehle ----------------------------------------------------------------
    def create(self, name: str, *, slug: str | None = None, command: str | list[str] | None = None,
               trigger: Mapping[str, Any] | None = None, description: str | None = None,
               enabled: bool = True, settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise TaskServiceError("Der Name der Aufgabe fehlt.")
        defaults = self.config.defaults
        record = {
            "command": parse_command(command if command is not None else defaults["command"]),
            "trigger": dict(trigger) if trigger else normalize_trigger(defaults["trigger"]),
            "description": description if description is not None else str(defaults.get("description") or ""),
            "settings": self._settings(settings),
            "config_file": str(self.config.config_file),
            "storage": str(self.config.storage_root) if self.config.storage_root else None,
        }
        payload = self._payload(name=name, slug=slug, record=record, enabled=enabled)
        info = self._call(self.manager.create, payload, overwrite=False)
        return self._view(info.task_id)

    def get(self, ref: str) -> dict[str, Any]:
        return self._view(self._resolve(ref)["task_id"])

    def list(self) -> list[dict[str, Any]]:
        """Alle Aufgaben dieses Eigentuemers aus globalem UND lokalem State."""
        ids: list[str] = []
        for info in [*self._call(self.manager.list, owner=self.config.owner), *self._local_infos()]:
            if info.task_id not in ids:
                ids.append(info.task_id)
        return [self._view(task_id) for task_id in ids]

    def update(self, ref: str, *, name: str | None = None, command: str | list[str] | None = None,
               trigger: Mapping[str, Any] | None = None, description: str | None = None,
               settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
        entry = self._resolve(ref)
        old = (entry.get("metadata") or {}).get(RECORD_KEY)
        if not old:
            raise TaskServiceError(
                f"Aufgabe {entry.get('slug')!r} hat keinen gespeicherten Plan (nicht mit chatexporter "
                f"angelegt oder State verloren); bitte loeschen und neu anlegen.")
        record = {
            "command": parse_command(command) if command is not None else list(old["command"]),
            "trigger": dict(trigger) if trigger else dict(old["trigger"]),
            "description": description if description is not None else old.get("description", ""),
            "settings": self._settings(settings, base=old.get("settings")),
            "config_file": str(self.config.config_file),
            "storage": str(self.config.storage_root) if self.config.storage_root else None,
        }
        info = self._call(self.manager.get, entry["task_id"], owner=self.config.owner)
        enabled = bool(info.enabled) if info.exists and info.enabled is not None else True
        payload = self._payload(name=(name or "").strip() or str(entry.get("name") or entry["slug"]),
                                slug=str(entry["slug"]), record=record, enabled=enabled,
                                task_id=str(entry["task_id"]))
        updated = self._call(self.manager.create, payload, overwrite=True)
        return self._view(updated.task_id)

    def delete(self, ref: str) -> dict[str, Any]:
        """Loescht die Aufgabe (Windows und State). Rueckgabe: die geloeschte Aufgabe."""
        view = self.get(ref)
        self._call(self.manager.delete, view["task_id"], owner=self.config.owner)
        return view

    def delete_all(self) -> list[dict[str, Any]]:
        """Loescht alle Aufgaben dieses Eigentuemers (z. B. bei der Deinstallation)."""
        removed = []
        for view in self.list():
            self._call(self.manager.delete, view["task_id"], owner=self.config.owner)
            removed.append(view)
        return removed

    def pause(self, ref: str) -> dict[str, Any]:
        entry = self._resolve(ref)
        self._call(self.manager.disable, entry["task_id"], owner=self.config.owner)
        return self._view(entry["task_id"])

    def resume(self, ref: str) -> dict[str, Any]:
        entry = self._resolve(ref)
        self._call(self.manager.enable, entry["task_id"], owner=self.config.owner)
        return self._view(entry["task_id"])

    # Ausgabe ------------------------------------------------------------------
    def _view(self, task_id: str) -> dict[str, Any]:
        entry = self._call(self.manager.resolve_entry, task_id, owner=self.config.owner)
        info = self._call(self.manager.get, task_id, owner=self.config.owner)
        record = (entry.get("metadata") or {}).get(RECORD_KEY) or {}
        command = record.get("command")
        return {
            "task_id": info.task_id,
            "slug": info.slug,
            "name": info.name,
            "owner": info.owner,
            "state": info.state,
            "enabled": info.enabled,
            "exists": info.exists,
            "trigger": describe_trigger(record.get("trigger")),
            "trigger_spec": record.get("trigger"),
            "command": " ".join(command) if command else None,
            "next_run": _fmt_time(info.next_run_time),
            "last_run": _fmt_time(info.last_run_time),
            "last_result": info.last_result,
            "description": info.description,
            "settings": record.get("settings"),
            "scheduler_path": info.scheduler_path,
        }
