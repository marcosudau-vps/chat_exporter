from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

#: HRESULT "Zugriff verweigert" (E_ACCESSDENIED), als vorzeichenbehaftete Zahl wie in pywintypes.
E_ACCESSDENIED = -2147024891


def access_denied(exc: BaseException) -> bool:
    """COM-Fehler mit E_ACCESSDENIED (direkt oder als scode in excepinfo)?
    Gemessen 2026-10-05: ``task create --startup`` ohne Adminrechte liefert
    ``(-2147352567, 'Ausnahmefehler aufgetreten.', (0, None, None, None, 0, -2147024891), None)``."""
    args = getattr(exc, "args", ()) or ()
    if args and args[0] == E_ACCESSDENIED:
        return True
    info = args[2] if len(args) > 2 else None
    return isinstance(info, tuple) and len(info) > 5 and info[5] == E_ACCESSDENIED


try:
    import pywintypes
    import win32com.client
except ImportError as exc:  # pragma: no cover - only relevant outside Windows / without pywin32
    pywintypes = None  # type: ignore[assignment]
    win32com = None  # type: ignore[assignment]
    _PYWIN32_IMPORT_ERROR = exc
else:
    _PYWIN32_IMPORT_ERROR = None


VERSION = "2.0.0"
MANAGER_SOURCE = "PyTaskManager"
STATE_SCHEMA_VERSION = 2
STATE_FILE_NAME = "tasks_sched.json"
DEFAULT_FOLDER = r"\PyTaskManager"

# Task Scheduler 2.0 constants
TASK_ACTION_EXEC = 0

TASK_TRIGGER_EVENT = 0
TASK_TRIGGER_TIME = 1
TASK_TRIGGER_DAILY = 2
TASK_TRIGGER_WEEKLY = 3
TASK_TRIGGER_MONTHLY = 4
TASK_TRIGGER_MONTHLY_DOW = 5
TASK_TRIGGER_IDLE = 6
TASK_TRIGGER_REGISTRATION = 7
TASK_TRIGGER_BOOT = 8
TASK_TRIGGER_LOGON = 9
TASK_TRIGGER_SESSION_STATE_CHANGE = 11

TASK_CREATE = 2
TASK_UPDATE = 4
TASK_CREATE_OR_UPDATE = TASK_CREATE | TASK_UPDATE

TASK_LOGON_INTERACTIVE_TOKEN = 3

TASK_RUNLEVEL_LUA = 0
TASK_RUNLEVEL_HIGHEST = 1

TASK_INSTANCES_PARALLEL = 0
TASK_INSTANCES_QUEUE = 1
TASK_INSTANCES_IGNORE_NEW = 2
TASK_INSTANCES_STOP_EXISTING = 3

TASK_STATE_UNKNOWN = 0
TASK_STATE_DISABLED = 1
TASK_STATE_QUEUED = 2
TASK_STATE_READY = 3
TASK_STATE_RUNNING = 4

TRIGGER_TYPE_NAMES = {
    TASK_TRIGGER_EVENT: "event",
    TASK_TRIGGER_TIME: "once",
    TASK_TRIGGER_DAILY: "daily",
    TASK_TRIGGER_WEEKLY: "weekly",
    TASK_TRIGGER_MONTHLY: "monthly",
    TASK_TRIGGER_MONTHLY_DOW: "monthly_weekday",
    TASK_TRIGGER_IDLE: "idle",
    TASK_TRIGGER_REGISTRATION: "registration",
    TASK_TRIGGER_BOOT: "startup",
    TASK_TRIGGER_LOGON: "logon",
    TASK_TRIGGER_SESSION_STATE_CHANGE: "session_state_change",
}

TASK_STATE_NAMES = {
    TASK_STATE_UNKNOWN: "unknown",
    TASK_STATE_DISABLED: "disabled",
    TASK_STATE_QUEUED: "queued",
    TASK_STATE_READY: "ready",
    TASK_STATE_RUNNING: "running",
}

MULTIPLE_INSTANCE_POLICIES = {
    "parallel": TASK_INSTANCES_PARALLEL,
    "queue": TASK_INSTANCES_QUEUE,
    "ignore_new": TASK_INSTANCES_IGNORE_NEW,
    "stop_existing": TASK_INSTANCES_STOP_EXISTING,
}

# Sunday=1, Monday=2, Tuesday=4, Wednesday=8, Thursday=16, Friday=32, Saturday=64
WEEKDAY_BITS = {
    "sun": 1,
    "sunday": 1,
    "so": 1,
    "sonntag": 1,
    "mon": 2,
    "monday": 2,
    "mo": 2,
    "montag": 2,
    "tue": 4,
    "tues": 4,
    "tuesday": 4,
    "di": 4,
    "dienstag": 4,
    "wed": 8,
    "wednesday": 8,
    "mi": 8,
    "mittwoch": 8,
    "thu": 16,
    "thur": 16,
    "thurs": 16,
    "thursday": 16,
    "do": 16,
    "donnerstag": 16,
    "fri": 32,
    "friday": 32,
    "fr": 32,
    "freitag": 32,
    "sat": 64,
    "saturday": 64,
    "sa": 64,
    "samstag": 64,
}


class TaskSchedulerError(RuntimeError):
    """Base exception for this module."""


class TaskNotFoundError(TaskSchedulerError):
    """Raised when a requested task does not exist."""


class TaskAlreadyExistsError(TaskSchedulerError):
    """Raised when overwrite=False and the task already exists."""


class StateFileError(TaskSchedulerError):
    """Raised when a persistent state file cannot be read or written safely."""


class AmbiguousTaskError(TaskSchedulerError):
    """Raised when a human-friendly reference matches more than one managed task."""


class TaskOwnershipError(TaskSchedulerError):
    """Raised when a registered scheduler task is not owned by PyTaskManager."""


@dataclass(frozen=True, slots=True)
class TriggerSpec:
    kind: str
    start_boundary: str | None = None
    days_interval: int | None = None
    weeks_interval: int | None = None
    days_of_week: int | None = None
    delay_seconds: int = 0
    user_id: str | None = None


@dataclass(frozen=True, slots=True)
class ExecActionSpec:
    executable: str
    arguments: str | tuple[str, ...] | None = None
    working_directory: str | None = None
    kind: str = "exec"


@dataclass(frozen=True, slots=True)
class TaskSettingsSpec:
    enabled: bool = True
    hidden: bool = False
    start_when_available: bool = True
    allow_on_battery: bool = True
    wake_to_run: bool = False
    multiple_instances: str = "ignore_new"
    max_runtime_minutes: int | float | None = None
    run_level: str = "limited"
    restart_interval_minutes: int | None = None
    restart_count: int = 0


@dataclass(frozen=True, slots=True)
class TaskProfile:
    name: str
    values: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class NormalizedTaskSpec:
    task_id: str
    owner: str
    slug: str
    name: str
    action: ExecActionSpec
    triggers: tuple[TriggerSpec, ...] = ()
    settings: TaskSettingsSpec = field(default_factory=TaskSettingsSpec)
    description: str = ""
    task_type: str = "exec"
    local_state_file: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TaskInfo:
    name: str
    path: str
    enabled: bool
    state: str
    last_run_time: Any
    next_run_time: Any
    last_result: int
    missed_runs: int
    description: str
    trigger_types: list[str] = field(default_factory=list)
    action_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ManagedTaskInfo:
    task_id: str
    owner: str
    slug: str
    name: str
    scheduler_path: str
    exists: bool
    state: str = "missing"
    enabled: bool | None = None
    last_run_time: Any = None
    next_run_time: Any = None
    last_result: int | None = None
    trigger_types: list[str] = field(default_factory=list)
    description: str = ""
    local_state_file: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReconcileResult:
    healthy: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    orphaned: list[str] = field(default_factory=list)
    local_only: list[str] = field(default_factory=list)
    detached: list[str] = field(default_factory=list)
    conflicted: list[str] = field(default_factory=list)
    repaired: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, list[str]]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Friendly trigger / profile helpers
# ---------------------------------------------------------------------------

def once(when: datetime | str) -> TriggerSpec:
    dt = _parse_datetime(when)
    return TriggerSpec(kind="once", start_boundary=_datetime_boundary(dt))


def daily(
    at: time | str,
    *,
    every: int = 1,
    start_date: date | datetime | str | None = None,
) -> TriggerSpec:
    if every < 1:
        raise ValueError("'every' muss mindestens 1 sein.")
    start = _combine_date_and_time(start_date, at)
    return TriggerSpec(kind="daily", start_boundary=_datetime_boundary(start), days_interval=every)


def weekly(
    at: time | str,
    days: str | Sequence[str],
    *,
    every: int = 1,
    start_date: date | datetime | str | None = None,
) -> TriggerSpec:
    if every < 1:
        raise ValueError("'every' muss mindestens 1 sein.")

    day_items = [days] if isinstance(days, str) else list(days)
    if not day_items:
        raise ValueError("Für weekly() muss mindestens ein Wochentag angegeben werden.")

    mask = 0
    for item in day_items:
        key = str(item).strip().lower()
        if key not in WEEKDAY_BITS:
            raise ValueError(f"Unbekannter Wochentag: {item!r}")
        mask |= WEEKDAY_BITS[key]

    start = _combine_date_and_time(start_date, at)
    return TriggerSpec(
        kind="weekly",
        start_boundary=_datetime_boundary(start),
        weeks_interval=every,
        days_of_week=mask,
    )


def logon(*, delay_seconds: int = 0, user_id: str | None = None) -> TriggerSpec:
    """Run when one user logs on. By default this is the current Windows user."""
    _validate_non_negative(delay_seconds, "delay_seconds")
    return TriggerSpec(kind="logon", delay_seconds=delay_seconds, user_id=user_id or _current_user_id())


def startup(*, delay_seconds: int = 0) -> TriggerSpec:
    _validate_non_negative(delay_seconds, "delay_seconds")
    return TriggerSpec(kind="startup", delay_seconds=delay_seconds)


def run_daily(
    at: time | str,
    *,
    every: int = 1,
    start_date: date | datetime | str | None = None,
) -> TaskProfile:
    return TaskProfile("run_daily", {"trigger": daily(at, every=every, start_date=start_date)})


def run_weekly(
    at: time | str,
    days: str | Sequence[str],
    *,
    every: int = 1,
    start_date: date | datetime | str | None = None,
) -> TaskProfile:
    return TaskProfile(
        "run_weekly",
        {"trigger": weekly(at, days, every=every, start_date=start_date)},
    )


def always_keep_running(
    *,
    restart_interval_minutes: int = 1,
    restart_count: int = 255,
) -> TaskProfile:
    """Retry a failed task aggressively.

    Windows Task Scheduler restarts only after a failure; this is not a service
    supervisor and does not restart a task that exits normally.
    """
    _validate_restart_settings(restart_interval_minutes, restart_count)
    return TaskProfile(
        "always_keep_running",
        {
            "settings": {
                "start_when_available": True,
                "multiple_instances": "ignore_new",
                "restart_interval_minutes": restart_interval_minutes,
                "restart_count": restart_count,
            }
        },
    )


# ---------------------------------------------------------------------------
# Parsing / normalization helpers
# ---------------------------------------------------------------------------

def _validate_non_negative(value: int, name: str) -> None:
    if value < 0:
        raise ValueError(f"'{name}' darf nicht negativ sein.")


def _validate_restart_settings(interval_minutes: int | None, count: int) -> None:
    if count < 0 or count > 255:
        raise ValueError("restart_count muss zwischen 0 und 255 liegen.")
    if count == 0:
        return
    if interval_minutes is None:
        raise ValueError("restart_interval_minutes wird benötigt, wenn restart_count > 0 ist.")
    if interval_minutes < 1 or interval_minutes > 31 * 24 * 60:
        raise ValueError("restart_interval_minutes muss zwischen 1 Minute und 31 Tagen liegen.")


def _parse_time(value: time | str) -> time:
    if isinstance(value, time):
        return value.replace(microsecond=0)
    text = str(value).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    raise ValueError(f"Ungültige Uhrzeit: {value!r}. Erwartet z. B. '10:30'.")


def _parse_date(value: date | datetime | str | None) -> date:
    if value is None:
        return date.today()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Ungültiges Datum: {value!r}. Erwartet wird 'YYYY-MM-DD'.") from exc


def _parse_datetime(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    text = str(value).strip()
    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError(f"Ungültiger Zeitpunkt: {value!r}. Erwartet z. B. '2026-10-01 10:30'.")


def _combine_date_and_time(
    day_value: date | datetime | str | None,
    time_value: time | str,
) -> datetime:
    return datetime.combine(_parse_date(day_value), _parse_time(time_value))


def _datetime_boundary(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat(timespec="seconds")


def _seconds_to_duration(seconds: int) -> str:
    _validate_non_negative(seconds, "seconds")
    if seconds == 0:
        return "PT0S"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    result = "PT"
    if hours:
        result += f"{hours}H"
    if minutes:
        result += f"{minutes}M"
    if secs:
        result += f"{secs}S"
    return result


def _minutes_to_duration(minutes: int | float | None) -> str:
    if minutes is None:
        return "PT0S"
    if minutes < 0:
        raise ValueError("max_runtime_minutes darf nicht negativ sein.")
    return _seconds_to_duration(int(round(minutes * 60)))


def _normalize_folder_path(folder: str | None) -> str:
    folder = (folder or DEFAULT_FOLDER).strip()
    if not folder:
        return "\\"
    folder = folder.replace("/", "\\")
    if not folder.startswith("\\"):
        folder = "\\" + folder
    while "\\\\" in folder:
        folder = folder.replace("\\\\", "\\")
    if len(folder) > 1:
        folder = folder.rstrip("\\")
    return folder


def _format_arguments(arguments: str | Sequence[Any] | None) -> str:
    if arguments is None:
        return ""
    if isinstance(arguments, str):
        return arguments
    return subprocess.list2cmdline([str(item) for item in arguments])


def _normalize_triggers(trigger: TriggerSpec | Sequence[TriggerSpec] | None) -> list[TriggerSpec]:
    if trigger is None:
        return []
    if isinstance(trigger, TriggerSpec):
        return [trigger]
    result = list(trigger)
    if not all(isinstance(item, TriggerSpec) for item in result):
        raise TypeError("trigger muss TriggerSpec, eine Liste daraus oder None sein.")
    return result


def _current_user_id() -> str:
    if os.name == "nt":
        try:
            import win32api
            import win32con

            value = win32api.GetUserNameEx(win32con.NameSamCompatible)
            if value:
                return str(value)
        except Exception:
            pass

    username = os.environ.get("USERNAME") or getpass.getuser()
    domain = os.environ.get("USERDOMAIN") or os.environ.get("COMPUTERNAME")
    if domain and "\\" not in username:
        return f"{domain}\\{username}"
    return username


def _slugify(value: str, *, fallback: str = "task") -> str:
    text = str(value).strip().replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return (text or fallback)[:80]


def _new_task_id() -> str:
    return f"tsk_{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _default_global_state_file() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / MANAGER_SOURCE / STATE_FILE_NAME
    return Path.home() / "AppData" / "Local" / MANAGER_SOURCE / STATE_FILE_NAME


def _fingerprint_xml(xml: str) -> str:
    return hashlib.sha256(xml.encode("utf-8")).hexdigest()


def _deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(result[key], value)  # type: ignore[arg-type]
        else:
            result[key] = value
    return result


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, TriggerSpec):
        return asdict(value)
    if isinstance(value, TaskProfile):
        return {"name": value.name, "values": _json_safe(dict(value.values))}
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return str(value)


# ---------------------------------------------------------------------------
# Safe persistent state files
# ---------------------------------------------------------------------------

@contextmanager
def _state_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(lock_path, "a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:  # pragma: no cover - test convenience outside Windows
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class JsonStateStore:
    def __init__(self, path: str | os.PathLike[str], *, kind: str, defaults: Mapping[str, Any]) -> None:
        self.path = Path(path).expanduser().resolve()
        self.kind = kind
        self.defaults = dict(defaults)

    @property
    def backup_path(self) -> Path:
        return self.path.with_suffix(self.path.suffix + ".bak")

    def load(self) -> dict[str, Any]:
        with _state_lock(self.path):
            return self._load_unlocked()

    def save(self, data: Mapping[str, Any]) -> None:
        with _state_lock(self.path):
            self._save_unlocked(dict(data))

    def mutate(self, mutator) -> dict[str, Any]:
        with _state_lock(self.path):
            data = self._load_unlocked()
            mutator(data)
            self._save_unlocked(data)
            return data

    def _load_unlocked(self) -> dict[str, Any]:
        if not self.path.exists():
            return json.loads(json.dumps(self.defaults))
        try:
            return self._read_json(self.path)
        except Exception as main_exc:
            if self.backup_path.exists():
                try:
                    return self._read_json(self.backup_path)
                except Exception:
                    pass
            raise StateFileError(f"State-Datei ist beschädigt: {self.path}: {main_exc}") from main_exc

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Root muss ein JSON-Objekt sein.")
        return data

    def _save_unlocked(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data.setdefault("schema_version", STATE_SCHEMA_VERSION)
        data.setdefault("kind", self.kind)
        data["updated_at"] = _now_iso()

        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            if self.path.exists():
                shutil.copy2(self.path, self.backup_path)
            os.replace(tmp, self.path)
        except Exception as exc:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise StateFileError(f"State-Datei konnte nicht sicher gespeichert werden: {self.path}: {exc}") from exc


class TaskRegistry:
    def __init__(
        self,
        *,
        owner: str,
        project_root: Path,
        global_state_file: str | os.PathLike[str] | None = None,
        local_state_file: str | os.PathLike[str] | bool | None = None,
    ) -> None:
        self.owner = _slugify(owner, fallback="default")
        self.project_root = project_root.resolve()
        self.global_store = JsonStateStore(
            global_state_file or _default_global_state_file(),
            kind="global",
            defaults={
                "schema_version": STATE_SCHEMA_VERSION,
                "kind": "global",
                "manager": MANAGER_SOURCE,
                "tasks": {},
            },
        )

        if local_state_file is False:
            self.local_store: JsonStateStore | None = None
        else:
            local_path = Path(local_state_file) if local_state_file else self.project_root / STATE_FILE_NAME
            self.local_store = JsonStateStore(
                local_path,
                kind="local",
                defaults={
                    "schema_version": STATE_SCHEMA_VERSION,
                    "kind": "local",
                    "manager": MANAGER_SOURCE,
                    "project_root": str(self.project_root),
                    "default_owner": self.owner,
                    "tasks": {},
                },
            )

    @property
    def local_path(self) -> str | None:
        return str(self.local_store.path) if self.local_store else None

    def global_data(self) -> dict[str, Any]:
        return self.global_store.load()

    def local_data(self) -> dict[str, Any]:
        if self.local_store is None:
            return {"tasks": {}}
        return self.local_store.load()

    def find_by_id(self, task_id: str) -> dict[str, Any] | None:
        return self.global_data().get("tasks", {}).get(task_id)

    def find(self, *, owner: str, slug: str, folder: str | None = None) -> dict[str, Any] | None:
        owner_key = _slugify(owner, fallback="default")
        slug_key = _slugify(slug)
        folder_key = _normalize_folder_path(folder) if folder else None
        matches = [
            dict(entry)
            for entry in self.global_data().get("tasks", {}).values()
            if entry.get("owner") == owner_key
            and entry.get("slug") == slug_key
            and (folder_key is None or _normalize_folder_path(entry.get("folder")) == folder_key)
        ]
        if len(matches) > 1:
            raise AmbiguousTaskError(f"Mehrere Registry-Einträge passen zu {owner_key}:{slug_key}.")
        return matches[0] if matches else None

    def upsert(self, entry: Mapping[str, Any]) -> None:
        item = dict(entry)
        task_id = str(item["task_id"])

        def update_global(data: MutableMapping[str, Any]) -> None:
            data.setdefault("tasks", {})[task_id] = item

        self.global_store.mutate(update_global)

        local_path = item.get("local_state_file")
        if local_path:
            local_store = self._store_for_local_path(local_path, owner=item.get("owner"))

            def update_local(data: MutableMapping[str, Any]) -> None:
                data.setdefault("tasks", {})[task_id] = item

            local_store.mutate(update_local)

    def remove(self, task_id: str, *, entry: Mapping[str, Any] | None = None) -> bool:
        existing = dict(entry or self.find_by_id(task_id) or {})
        removed = False

        def delete_global(data: MutableMapping[str, Any]) -> None:
            nonlocal removed
            if task_id in data.setdefault("tasks", {}):
                removed = True
                del data["tasks"][task_id]

        self.global_store.mutate(delete_global)

        local_path = existing.get("local_state_file")
        if local_path:
            store = self._store_for_local_path(local_path, owner=existing.get("owner"))

            def delete_local(data: MutableMapping[str, Any]) -> None:
                nonlocal removed
                if task_id in data.setdefault("tasks", {}):
                    removed = True
                    del data["tasks"][task_id]

            store.mutate(delete_local)
        elif self.local_store is not None:
            def delete_current_local(data: MutableMapping[str, Any]) -> None:
                nonlocal removed
                if task_id in data.setdefault("tasks", {}):
                    removed = True
                    del data["tasks"][task_id]

            self.local_store.mutate(delete_current_local)

        return removed

    def local_task_ids(self) -> list[str]:
        return list(self.local_data().get("tasks", {}).keys())

    def local_contains(self, path: str, task_id: str) -> bool:
        try:
            store = self._store_for_local_path(path)
            return task_id in store.load().get("tasks", {})
        except Exception:
            return False

    def adopt_into_local(self, entry: Mapping[str, Any]) -> None:
        local_path = entry.get("local_state_file")
        if not local_path:
            return
        store = self._store_for_local_path(local_path, owner=entry.get("owner"))

        def update_local(data: MutableMapping[str, Any]) -> None:
            data.setdefault("tasks", {})[entry["task_id"]] = dict(entry)

        store.mutate(update_local)

    def _store_for_local_path(self, path: str | os.PathLike[str], owner: str | None = None) -> JsonStateStore:
        local_path = Path(path).expanduser().resolve()
        return JsonStateStore(
            local_path,
            kind="local",
            defaults={
                "schema_version": STATE_SCHEMA_VERSION,
                "kind": "local",
                "manager": MANAGER_SOURCE,
                "project_root": str(local_path.parent),
                "default_owner": _slugify(owner or self.owner, fallback="default"),
                "tasks": {},
            },
        )


# ---------------------------------------------------------------------------
# Input resolver -> one canonical NormalizedTaskSpec
# ---------------------------------------------------------------------------

class TaskResolver:
    def __init__(self, *, default_owner: str, local_state_file: str | None) -> None:
        self.default_owner = _slugify(default_owner, fallback="default")
        self.local_state_file = local_state_file

    def resolve(
        self,
        source: NormalizedTaskSpec | Mapping[str, Any] | str,
        *,
        profile: TaskProfile | Mapping[str, Any] | None = None,
        overrides: Mapping[str, Any] | None = None,
    ) -> NormalizedTaskSpec:
        if isinstance(source, NormalizedTaskSpec):
            data = source.as_dict()
        elif isinstance(source, Mapping):
            data = dict(source)
        elif isinstance(source, str):
            text = source.strip()
            if not text.startswith("{"):
                raise ValueError("String-Eingabe für create() muss ein JSON-Objekt sein.")
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("JSON-Eingabe muss ein Objekt enthalten.")
            data = parsed
        else:
            raise TypeError("source muss NormalizedTaskSpec, Dict oder JSON-String sein.")

        merged: dict[str, Any] = {}
        if profile is not None:
            profile_values = dict(profile.values) if isinstance(profile, TaskProfile) else dict(profile)
            merged = _deep_merge(merged, profile_values)
        merged = _deep_merge(merged, data)
        if overrides:
            merged = _deep_merge(merged, overrides)

        name = str(merged.get("name") or "").strip()
        if not name:
            raise ValueError("'name' fehlt.")

        owner = _slugify(str(merged.get("owner") or self.default_owner), fallback="default")
        slug = _slugify(str(merged.get("slug") or name))
        task_id = str(merged.get("task_id") or "").strip()

        action, task_type = self._resolve_action(merged)
        triggers = tuple(self._resolve_trigger_input(merged.get("trigger", merged.get("triggers"))))
        settings = self._resolve_settings(merged)
        description = str(merged.get("description") or "")
        metadata = merged.get("metadata") if isinstance(merged.get("metadata"), Mapping) else {}

        return NormalizedTaskSpec(
            task_id=task_id,
            owner=owner,
            slug=slug,
            name=name,
            action=action,
            triggers=triggers,
            settings=settings,
            description=description,
            task_type=task_type,
            local_state_file=str(merged.get("local_state_file") or self.local_state_file) if (merged.get("local_state_file") or self.local_state_file) else None,
            metadata=dict(metadata),
        )

    @staticmethod
    def _resolve_action(data: Mapping[str, Any]) -> tuple[ExecActionSpec, str]:
        script = data.get("script")
        executable = data.get("executable")
        arguments = data.get("arguments")
        working_directory = data.get("working_directory")

        if script is not None:
            script_path = Path(script).expanduser().resolve()
            if not script_path.exists():
                raise FileNotFoundError(f"Python-Skript nicht gefunden: {script_path}")
            python_path = Path(data.get("python_executable") or sys.executable).expanduser().resolve()
            if not python_path.exists():
                raise FileNotFoundError(f"Python-Interpreter nicht gefunden: {python_path}")

            if isinstance(arguments, str):
                full_arguments: str | tuple[str, ...] = (
                    f'{subprocess.list2cmdline([str(script_path)])} {arguments}'.strip()
                )
            else:
                full_arguments = tuple([str(script_path), *[str(x) for x in (arguments or [])]])
            workdir = str(Path(working_directory).expanduser().resolve()) if working_directory else str(script_path.parent)
            return ExecActionSpec(str(python_path), full_arguments, workdir), "python"

        if executable is None:
            raise ValueError("Es wird entweder 'script' oder 'executable' benötigt.")
        executable_str = str(executable).strip()
        if not executable_str:
            raise ValueError("'executable' darf nicht leer sein.")

        if isinstance(arguments, str) or arguments is None:
            normalized_args: str | tuple[str, ...] | None = arguments
        else:
            normalized_args = tuple(str(x) for x in arguments)
        workdir = str(Path(working_directory).expanduser().resolve()) if working_directory else None
        return ExecActionSpec(executable_str, normalized_args, workdir), "exec"

    @staticmethod
    def _resolve_settings(data: Mapping[str, Any]) -> TaskSettingsSpec:
        nested = dict(data.get("settings") or {}) if isinstance(data.get("settings"), Mapping) else {}
        keys = {
            "enabled",
            "hidden",
            "start_when_available",
            "allow_on_battery",
            "wake_to_run",
            "multiple_instances",
            "max_runtime_minutes",
            "run_level",
            "restart_interval_minutes",
            "restart_count",
        }
        for key in keys:
            if key in data:
                nested[key] = data[key]

        settings = TaskSettingsSpec(**nested)
        if settings.multiple_instances not in MULTIPLE_INSTANCE_POLICIES:
            raise ValueError(f"multiple_instances muss einer von {', '.join(MULTIPLE_INSTANCE_POLICIES)} sein.")
        if settings.run_level not in {"limited", "highest"}:
            raise ValueError("run_level muss 'limited' oder 'highest' sein.")
        _validate_restart_settings(settings.restart_interval_minutes, settings.restart_count)
        return settings

    def _resolve_trigger_input(self, value: Any) -> list[TriggerSpec]:
        if value is None:
            return []
        if isinstance(value, TriggerSpec):
            return [value]
        if isinstance(value, Mapping):
            return [self._trigger_from_mapping(value)]
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            result: list[TriggerSpec] = []
            for item in value:
                if isinstance(item, TriggerSpec):
                    result.append(item)
                elif isinstance(item, Mapping):
                    result.append(self._trigger_from_mapping(item))
                else:
                    raise TypeError(f"Ungültiger Trigger: {item!r}")
            return result
        raise TypeError("trigger muss TriggerSpec, Dict, Liste oder None sein.")

    @staticmethod
    def _trigger_from_mapping(data: Mapping[str, Any]) -> TriggerSpec:
        kind = str(data.get("type") or data.get("kind") or "").strip().lower()
        if kind == "once":
            when = data.get("when") or data.get("at") or data.get("start_boundary")
            if when is None:
                raise ValueError("once-Trigger benötigt 'when'.")
            return once(when)
        if kind == "daily":
            at = data.get("at")
            if at is None:
                boundary = data.get("start_boundary")
                if boundary:
                    return TriggerSpec(kind="daily", start_boundary=str(boundary), days_interval=int(data.get("every") or data.get("days_interval") or 1))
                raise ValueError("daily-Trigger benötigt 'at'.")
            return daily(at, every=int(data.get("every") or data.get("days_interval") or 1), start_date=data.get("start_date"))
        if kind == "weekly":
            at = data.get("at")
            days = data.get("days")
            if at is None or days is None:
                boundary = data.get("start_boundary")
                bits = data.get("days_of_week")
                if boundary and bits:
                    return TriggerSpec(
                        kind="weekly",
                        start_boundary=str(boundary),
                        weeks_interval=int(data.get("every") or data.get("weeks_interval") or 1),
                        days_of_week=int(bits),
                    )
                raise ValueError("weekly-Trigger benötigt 'at' und 'days'.")
            return weekly(at, days, every=int(data.get("every") or data.get("weeks_interval") or 1), start_date=data.get("start_date"))
        if kind == "logon":
            return logon(delay_seconds=int(data.get("delay_seconds") or 0), user_id=data.get("user_id"))
        if kind == "startup":
            return startup(delay_seconds=int(data.get("delay_seconds") or 0))
        raise ValueError(f"Nicht unterstützter Trigger-Typ: {kind!r}")


# ---------------------------------------------------------------------------
# Low-level Windows Task Scheduler wrapper
# ---------------------------------------------------------------------------

class WindowsTaskScheduler:
    """Low-level wrapper around the Windows Task Scheduler 2.0 COM API."""

    def __init__(self, folder: str = DEFAULT_FOLDER) -> None:
        if os.name != "nt":
            raise TaskSchedulerError("WindowsTaskScheduler kann nur unter Windows verwendet werden.")
        if _PYWIN32_IMPORT_ERROR is not None:
            raise TaskSchedulerError("pywin32 fehlt. Installation: py -m pip install pywin32") from _PYWIN32_IMPORT_ERROR

        self.folder_path = _normalize_folder_path(folder)
        self.service = win32com.client.Dispatch("Schedule.Service")
        self.service.Connect()
        self.folder = self.ensure_folder(self.folder_path)

    def ensure_folder(self, folder: str | None = None):
        path = _normalize_folder_path(folder or self.folder_path)
        if path == "\\":
            return self.service.GetFolder("\\")
        try:
            return self.service.GetFolder(path)
        except pywintypes.com_error:
            pass

        current = self.service.GetFolder("\\")
        current_path = ""
        for part in [p for p in path.split("\\") if p]:
            current_path += "\\" + part
            try:
                current = self.service.GetFolder(current_path)
            except pywintypes.com_error:
                current = current.CreateFolder(part)
        return current

    def delete_folder(self, folder: str | None = None) -> None:
        path = _normalize_folder_path(folder or self.folder_path)
        if path == "\\":
            raise TaskSchedulerError("Der Root-Ordner des Task Schedulers darf nicht gelöscht werden.")
        parent_path, _, folder_name = path.rpartition("\\")
        parent = self.service.GetFolder(parent_path or "\\")
        parent.DeleteFolder(folder_name, 0)

    def create_task(
        self,
        name: str,
        executable: str | os.PathLike[str],
        *,
        arguments: str | Sequence[Any] | None = None,
        working_directory: str | os.PathLike[str] | None = None,
        trigger: TriggerSpec | Sequence[TriggerSpec] | None = None,
        description: str = "",
        enabled: bool = True,
        hidden: bool = False,
        start_when_available: bool = True,
        allow_on_battery: bool = True,
        wake_to_run: bool = False,
        multiple_instances: str = "ignore_new",
        max_runtime_minutes: int | float | None = None,
        run_level: str = "limited",
        restart_interval_minutes: int | None = None,
        restart_count: int = 0,
        overwrite: bool = True,
        registration_source: str | None = None,
        registration_uri: str | None = None,
        registration_documentation: str | None = None,
    ) -> TaskInfo:
        task_name = self._validate_task_name(name)
        executable_str = str(executable)
        if not executable_str.strip():
            raise ValueError("executable darf nicht leer sein.")

        policy_key = multiple_instances.strip().lower()
        if policy_key not in MULTIPLE_INSTANCE_POLICIES:
            raise ValueError(f"multiple_instances muss einer von {', '.join(MULTIPLE_INSTANCE_POLICIES)} sein.")
        run_level_key = run_level.strip().lower()
        if run_level_key not in {"limited", "highest"}:
            raise ValueError("run_level muss 'limited' oder 'highest' sein.")
        _validate_restart_settings(restart_interval_minutes, restart_count)

        if not overwrite and self.task_exists(task_name):
            raise TaskAlreadyExistsError(f"Task existiert bereits: {task_name}")

        definition = self.service.NewTask(0)
        registration = definition.RegistrationInfo
        registration.Author = getpass.getuser()
        registration.Description = description
        if registration_source:
            registration.Source = registration_source
        if registration_uri:
            registration.URI = registration_uri
        if registration_documentation:
            registration.Documentation = registration_documentation

        principal = definition.Principal
        principal.LogonType = TASK_LOGON_INTERACTIVE_TOKEN
        principal.RunLevel = TASK_RUNLEVEL_HIGHEST if run_level_key == "highest" else TASK_RUNLEVEL_LUA

        settings = definition.Settings
        settings.Enabled = bool(enabled)
        settings.Hidden = bool(hidden)
        settings.AllowDemandStart = True
        settings.StartWhenAvailable = bool(start_when_available)
        settings.DisallowStartIfOnBatteries = not bool(allow_on_battery)
        settings.StopIfGoingOnBatteries = False
        settings.WakeToRun = bool(wake_to_run)
        settings.ExecutionTimeLimit = _minutes_to_duration(max_runtime_minutes)
        settings.MultipleInstances = MULTIPLE_INSTANCE_POLICIES[policy_key]
        if restart_count > 0:
            settings.RestartInterval = _seconds_to_duration(int(restart_interval_minutes or 0) * 60)
            settings.RestartCount = int(restart_count)
        else:
            settings.RestartCount = 0

        for spec in _normalize_triggers(trigger):
            self._apply_trigger(definition, spec)

        action = definition.Actions.Create(TASK_ACTION_EXEC)
        action.Path = executable_str
        action.Arguments = _format_arguments(arguments)
        if working_directory is not None:
            action.WorkingDirectory = str(working_directory)

        flags = TASK_CREATE_OR_UPDATE if overwrite else TASK_CREATE
        try:
            self.folder.RegisterTaskDefinition(
                task_name,
                definition,
                flags,
                None,
                None,
                TASK_LOGON_INTERACTIVE_TOKEN,
            )
        except pywintypes.com_error as exc:
            if access_denied(exc):
                raise TaskSchedulerError(
                    f"Task konnte nicht registriert werden: {task_name}. Windows verweigert den Zugriff "
                    "(0x80070005): Diese Aufgabe braucht Administratorrechte, z. B. der Start beim "
                    "Hochfahren (--startup). Ohne Administratorrechte '--logon' (bei Anmeldung) verwenden "
                    "oder die Eingabeaufforderung als Administrator starten.") from exc
            raise TaskSchedulerError(f"Task konnte nicht registriert werden: {task_name}. {exc}") from exc

        return self.get_task_info(task_name)

    def create_python_task(
        self,
        name: str,
        script: str | os.PathLike[str],
        *,
        arguments: str | Sequence[Any] | None = None,
        python_executable: str | os.PathLike[str] | None = None,
        working_directory: str | os.PathLike[str] | None = None,
        **kwargs: Any,
    ) -> TaskInfo:
        script_path = Path(script).expanduser().resolve()
        python_path = Path(python_executable or sys.executable).expanduser().resolve()
        if not script_path.exists():
            raise FileNotFoundError(f"Python-Skript nicht gefunden: {script_path}")
        if not python_path.exists():
            raise FileNotFoundError(f"Python-Interpreter nicht gefunden: {python_path}")

        if isinstance(arguments, str):
            full_arguments: str | Sequence[Any] = f'{subprocess.list2cmdline([str(script_path)])} {arguments}'.strip()
        else:
            full_arguments = [str(script_path), *(arguments or [])]
        workdir = Path(working_directory).expanduser().resolve() if working_directory else script_path.parent

        return self.create_task(
            name,
            str(python_path),
            arguments=full_arguments,
            working_directory=str(workdir),
            **kwargs,
        )

    def task_exists(self, name: str) -> bool:
        task_name = self._validate_task_name(name)
        try:
            self.folder.GetTask(task_name)
            return True
        except pywintypes.com_error:
            return False

    def get_task(self, name: str):
        task_name = self._validate_task_name(name)
        try:
            return self.folder.GetTask(task_name)
        except pywintypes.com_error as exc:
            raise TaskNotFoundError(f"Task nicht gefunden: {task_name}") from exc

    def get_task_info(self, name: str) -> TaskInfo:
        task = self.get_task(name)
        definition = task.Definition
        trigger_types = [
            TRIGGER_TYPE_NAMES.get(int(definition.Triggers.Item(i).Type), f"type_{definition.Triggers.Item(i).Type}")
            for i in range(1, definition.Triggers.Count + 1)
        ]
        return TaskInfo(
            name=task.Name,
            path=task.Path,
            enabled=bool(task.Enabled),
            state=TASK_STATE_NAMES.get(int(task.State), f"state_{task.State}"),
            last_run_time=task.LastRunTime,
            next_run_time=task.NextRunTime,
            last_result=int(task.LastTaskResult),
            missed_runs=int(task.NumberOfMissedRuns),
            description=str(definition.RegistrationInfo.Description or ""),
            trigger_types=trigger_types,
            action_count=int(definition.Actions.Count),
        )

    def list_tasks(self, *, include_hidden: bool = True) -> list[TaskInfo]:
        tasks = self.folder.GetTasks(1 if include_hidden else 0)
        return [self.get_task_info(tasks.Item(i).Name) for i in range(1, tasks.Count + 1)]

    def delete_task(self, name: str, *, missing_ok: bool = False) -> bool:
        task_name = self._validate_task_name(name)
        if not self.task_exists(task_name):
            if missing_ok:
                return False
            raise TaskNotFoundError(f"Task nicht gefunden: {task_name}")
        self.folder.DeleteTask(task_name, 0)
        return True

    def run_task(self, name: str):
        return self.get_task(name).Run("")

    def stop_task(self, name: str) -> None:
        self.get_task(name).Stop(0)

    def enable_task(self, name: str) -> None:
        self.get_task(name).Enabled = True

    def disable_task(self, name: str) -> None:
        self.get_task(name).Enabled = False

    def fingerprint(self, name: str) -> str:
        return _fingerprint_xml(str(self.get_task(name).Xml))

    def get_registration_metadata(self, name: str) -> dict[str, Any]:
        task = self.get_task(name)
        info = task.Definition.RegistrationInfo
        documentation = str(info.Documentation or "")
        parsed: dict[str, Any] = {}
        if documentation:
            try:
                value = json.loads(documentation)
                if isinstance(value, dict):
                    parsed = value
            except json.JSONDecodeError:
                parsed = {}
        return {
            "source": str(info.Source or ""),
            "uri": str(info.URI or ""),
            "documentation": documentation,
            "metadata": parsed,
        }

    def _apply_trigger(self, definition, spec: TriggerSpec) -> None:
        kind = spec.kind.strip().lower()
        if kind == "once":
            trigger_obj = definition.Triggers.Create(TASK_TRIGGER_TIME)
            trigger_obj.StartBoundary = self._require_boundary(spec)
        elif kind == "daily":
            trigger_obj = definition.Triggers.Create(TASK_TRIGGER_DAILY)
            trigger_obj.StartBoundary = self._require_boundary(spec)
            trigger_obj.DaysInterval = int(spec.days_interval or 1)
        elif kind == "weekly":
            trigger_obj = definition.Triggers.Create(TASK_TRIGGER_WEEKLY)
            trigger_obj.StartBoundary = self._require_boundary(spec)
            trigger_obj.WeeksInterval = int(spec.weeks_interval or 1)
            trigger_obj.DaysOfWeek = int(spec.days_of_week or 0)
            if trigger_obj.DaysOfWeek == 0:
                raise ValueError("weekly-Trigger enthält keine Wochentage.")
        elif kind == "logon":
            trigger_obj = definition.Triggers.Create(TASK_TRIGGER_LOGON)
            trigger_obj.UserId = spec.user_id or _current_user_id()
            if spec.delay_seconds:
                trigger_obj.Delay = _seconds_to_duration(spec.delay_seconds)
        elif kind == "startup":
            trigger_obj = definition.Triggers.Create(TASK_TRIGGER_BOOT)
            if spec.delay_seconds:
                trigger_obj.Delay = _seconds_to_duration(spec.delay_seconds)
        else:
            raise ValueError(f"Nicht unterstützter Trigger-Typ: {spec.kind!r}")
        trigger_obj.Enabled = True

    @staticmethod
    def _require_boundary(spec: TriggerSpec) -> str:
        if not spec.start_boundary:
            raise ValueError(f"Trigger {spec.kind!r} benötigt eine StartBoundary.")
        return spec.start_boundary

    @staticmethod
    def _validate_task_name(name: str) -> str:
        task_name = str(name).strip()
        if not task_name:
            raise ValueError("Task-Name darf nicht leer sein.")
        if "\\" in task_name or "/" in task_name:
            raise ValueError("Task-Name darf keinen Pfad enthalten. Dafür 'folder=' verwenden.")
        return task_name


# ---------------------------------------------------------------------------
# High-level managed task layer
# ---------------------------------------------------------------------------

class PyTaskManager:
    """Managed layer: normalize inputs, persist identity, and control Windows tasks."""

    def __init__(
        self,
        *,
        owner: str | None = None,
        project_root: str | os.PathLike[str] | None = None,
        local_state_file: str | os.PathLike[str] | bool | None = None,
        global_state_file: str | os.PathLike[str] | None = None,
        folder: str = DEFAULT_FOLDER,
    ) -> None:
        self.project_root = Path(project_root or Path.cwd()).expanduser().resolve()
        self.owner = _slugify(owner or self.project_root.name, fallback="default")
        self.scheduler = WindowsTaskScheduler(folder)
        self.registry = TaskRegistry(
            owner=self.owner,
            project_root=self.project_root,
            global_state_file=global_state_file,
            local_state_file=local_state_file,
        )
        self.resolver = TaskResolver(default_owner=self.owner, local_state_file=self.registry.local_path)

    def create(
        self,
        source: NormalizedTaskSpec | Mapping[str, Any] | str,
        *,
        profile: TaskProfile | Mapping[str, Any] | None = None,
        overwrite: bool = True,
        **overrides: Any,
    ) -> ManagedTaskInfo:
        spec = self.resolver.resolve(source, profile=profile, overrides=overrides or None)
        return self._create_normalized(spec, overwrite=overwrite)

    def create_task(
        self,
        name: str,
        executable: str | os.PathLike[str],
        *,
        slug: str | None = None,
        owner: str | None = None,
        profile: TaskProfile | Mapping[str, Any] | None = None,
        overwrite: bool = True,
        **kwargs: Any,
    ) -> ManagedTaskInfo:
        data = {"name": name, "executable": str(executable), **kwargs}
        if slug is not None:
            data["slug"] = slug
        if owner is not None:
            data["owner"] = owner
        return self.create(data, profile=profile, overwrite=overwrite)

    def create_python_task(
        self,
        name: str,
        script: str | os.PathLike[str],
        *,
        slug: str | None = None,
        owner: str | None = None,
        profile: TaskProfile | Mapping[str, Any] | None = None,
        overwrite: bool = True,
        **kwargs: Any,
    ) -> ManagedTaskInfo:
        data = {"name": name, "script": str(script), **kwargs}
        if slug is not None:
            data["slug"] = slug
        if owner is not None:
            data["owner"] = owner
        return self.create(data, profile=profile, overwrite=overwrite)

    def _create_normalized(self, spec: NormalizedTaskSpec, *, overwrite: bool) -> ManagedTaskInfo:
        existing = self.registry.find(owner=spec.owner, slug=spec.slug, folder=self.scheduler.folder_path)
        if spec.task_id:
            by_id = self.registry.find_by_id(spec.task_id)
            if by_id:
                existing = by_id

        if existing and not overwrite:
            raise TaskAlreadyExistsError(f"Managed Task existiert bereits: {spec.owner}:{spec.slug}")

        task_id = str(existing.get("task_id")) if existing else (spec.task_id or _new_task_id())
        spec = replace(spec, task_id=task_id)
        created_at = str(existing.get("created_at")) if existing else _now_iso()

        if self.scheduler.task_exists(task_id):
            registration = self.scheduler.get_registration_metadata(task_id)
            if registration.get("source") != MANAGER_SOURCE:
                raise TaskOwnershipError(
                    f"Scheduler-Name {task_id} ist bereits durch einen fremden Task belegt."
                )

        registration_metadata = {
            "manager": MANAGER_SOURCE,
            "manager_version": VERSION,
            "task_id": spec.task_id,
            "owner": spec.owner,
            "slug": spec.slug,
            "name": spec.name,
            "local_state_file": spec.local_state_file,
            "task_type": spec.task_type,
            "created_at": created_at,
            "folder": self.scheduler.folder_path,
        }

        settings = spec.settings
        raw_info = self.scheduler.create_task(
            spec.task_id,
            spec.action.executable,
            arguments=spec.action.arguments,
            working_directory=spec.action.working_directory,
            trigger=list(spec.triggers),
            description=spec.description or spec.name,
            enabled=settings.enabled,
            hidden=settings.hidden,
            start_when_available=settings.start_when_available,
            allow_on_battery=settings.allow_on_battery,
            wake_to_run=settings.wake_to_run,
            multiple_instances=settings.multiple_instances,
            max_runtime_minutes=settings.max_runtime_minutes,
            run_level=settings.run_level,
            restart_interval_minutes=settings.restart_interval_minutes,
            restart_count=settings.restart_count,
            overwrite=True,
            registration_source=MANAGER_SOURCE,
            registration_uri=f"pytaskmanager://task/{spec.task_id}",
            registration_documentation=json.dumps(registration_metadata, ensure_ascii=False, sort_keys=True),
        )

        fingerprint = self.scheduler.fingerprint(spec.task_id)
        entry = {
            "task_id": spec.task_id,
            "owner": spec.owner,
            "slug": spec.slug,
            "name": spec.name,
            "task_type": spec.task_type,
            "scheduler_name": spec.task_id,
            "scheduler_path": raw_info.path,
            "folder": self.scheduler.folder_path,
            "description": spec.description,
            "local_state_file": spec.local_state_file,
            "created_at": created_at,
            "updated_at": _now_iso(),
            "fingerprint": fingerprint,
            "metadata": _json_safe(dict(spec.metadata)),
        }
        self.registry.upsert(entry)
        return self._managed_info(entry)

    def resolve_entry(self, ref: Any, *, owner: str | None = None) -> dict[str, Any]:
        global_tasks = self.registry.global_data().get("tasks", {})
        local_tasks = self.registry.local_data().get("tasks", {})
        owner_key = _slugify(owner or self.owner, fallback="default")

        if isinstance(ref, ManagedTaskInfo):
            ref = ref.task_id
        if isinstance(ref, Mapping):
            if ref.get("task_id"):
                ref = str(ref["task_id"])
            elif ref.get("slug"):
                owner_key = _slugify(str(ref.get("owner") or owner_key), fallback="default")
                ref = str(ref["slug"])
            else:
                raise ValueError("Task-Referenz-Dict benötigt task_id oder slug.")

        key = str(ref).strip()
        if not key:
            raise ValueError("Task-Referenz darf nicht leer sein.")

        if key in global_tasks and _normalize_folder_path(global_tasks[key].get("folder")) == self.scheduler.folder_path:
            return dict(global_tasks[key])
        if key in local_tasks and _normalize_folder_path(local_tasks[key].get("folder")) == self.scheduler.folder_path:
            return dict(local_tasks[key])

        matches = [
            dict(entry)
            for entry in global_tasks.values()
            if _normalize_folder_path(entry.get("folder")) == self.scheduler.folder_path
            and entry.get("owner") == owner_key
            and (entry.get("slug") == _slugify(key) or entry.get("name") == key)
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise AmbiguousTaskError(f"Mehrere Tasks passen zu {key!r}; bitte task_id verwenden.")

        discovered = self._discover_scheduler_managed().get(key)
        if discovered:
            return discovered

        raise TaskNotFoundError(f"Managed Task nicht gefunden: {key}")

    def exists(self, ref: Any, *, owner: str | None = None) -> bool:
        try:
            entry = self.resolve_entry(ref, owner=owner)
        except TaskNotFoundError:
            return False
        return self.scheduler.task_exists(entry["task_id"])

    def get(self, ref: Any, *, owner: str | None = None) -> ManagedTaskInfo:
        entry = self.resolve_entry(ref, owner=owner)
        return self._managed_info(entry)

    def list(self, *, owner: str | None = None, local_only: bool = False) -> list[ManagedTaskInfo]:
        owner_key = _slugify(owner, fallback="default") if owner else None
        data = self.registry.local_data() if local_only else self.registry.global_data()
        entries = []
        for entry in data.get("tasks", {}).values():
            if _normalize_folder_path(entry.get("folder")) != self.scheduler.folder_path:
                continue
            if owner_key is None or entry.get("owner") == owner_key:
                entries.append(self._managed_info(dict(entry)))
        return sorted(entries, key=lambda item: (item.owner, item.slug, item.task_id))

    def run(self, ref: Any, *, owner: str | None = None):
        entry = self.resolve_entry(ref, owner=owner)
        self._assert_owned_scheduler_task(entry)
        return self.scheduler.run_task(entry["task_id"])

    def stop(self, ref: Any, *, owner: str | None = None) -> None:
        entry = self.resolve_entry(ref, owner=owner)
        self._assert_owned_scheduler_task(entry)
        self.scheduler.stop_task(entry["task_id"])

    def enable(self, ref: Any, *, owner: str | None = None) -> None:
        entry = self.resolve_entry(ref, owner=owner)
        self._assert_owned_scheduler_task(entry)
        self.scheduler.enable_task(entry["task_id"])
        self._refresh_entry_fingerprint(entry)

    def disable(self, ref: Any, *, owner: str | None = None) -> None:
        entry = self.resolve_entry(ref, owner=owner)
        self._assert_owned_scheduler_task(entry)
        self.scheduler.disable_task(entry["task_id"])
        self._refresh_entry_fingerprint(entry)

    def delete(self, ref: Any, *, owner: str | None = None, missing_ok: bool = False) -> bool:
        try:
            entry = self.resolve_entry(ref, owner=owner)
        except TaskNotFoundError:
            if missing_ok:
                return False
            raise

        task_id = entry["task_id"]
        scheduler_removed = False
        if self.scheduler.task_exists(task_id):
            self._assert_owned_scheduler_task(entry)
            scheduler_removed = self.scheduler.delete_task(task_id, missing_ok=True)
        registry_removed = self.registry.remove(task_id, entry=entry)
        return scheduler_removed or registry_removed

    def delete_all_local(self) -> int:
        count = 0
        for task_id in list(self.registry.local_task_ids()):
            if self.delete(task_id, missing_ok=True):
                count += 1
        return count

    def reconcile(self, *, repair: bool = False) -> ReconcileResult:
        result = ReconcileResult()
        global_data = self.registry.global_data()
        global_tasks: dict[str, dict[str, Any]] = {
            key: dict(value)
            for key, value in global_data.get("tasks", {}).items()
            if _normalize_folder_path(value.get("folder")) == self.scheduler.folder_path
        }
        local_tasks = {
            key: value
            for key, value in self.registry.local_data().get("tasks", {}).items()
            if _normalize_folder_path(value.get("folder")) == self.scheduler.folder_path
        }
        discovered = self._discover_scheduler_managed()

        for task_id, entry in global_tasks.items():
            scheduler_entry = discovered.get(task_id)
            if scheduler_entry is None:
                if self.scheduler.task_exists(task_id):
                    result.conflicted.append(task_id)
                else:
                    result.missing.append(task_id)
                continue
            if entry.get("fingerprint") != scheduler_entry.get("fingerprint"):
                result.changed.append(task_id)
            else:
                result.healthy.append(task_id)

            local_path = entry.get("local_state_file")
            if local_path and not self.registry.local_contains(str(local_path), task_id):
                result.detached.append(task_id)

        for task_id in discovered.keys() - global_tasks.keys():
            result.orphaned.append(task_id)

        for task_id in local_tasks.keys() - global_tasks.keys():
            result.local_only.append(task_id)

        if repair:
            for task_id in result.changed:
                entry = global_tasks[task_id]
                entry["fingerprint"] = discovered[task_id]["fingerprint"]
                entry["updated_at"] = _now_iso()
                self.registry.upsert(entry)
                result.repaired.append(task_id)

            for task_id in result.orphaned:
                entry = discovered[task_id]
                self.registry.upsert(entry)
                result.repaired.append(task_id)

            for task_id in result.local_only:
                local_entry = dict(local_tasks[task_id])
                if task_id in discovered:
                    local_entry["fingerprint"] = discovered[task_id]["fingerprint"]
                    local_entry["updated_at"] = _now_iso()
                    self.registry.upsert(local_entry)
                    result.repaired.append(task_id)

            for task_id in result.detached:
                entry = global_tasks[task_id]
                self.registry.adopt_into_local(entry)
                if task_id not in result.repaired:
                    result.repaired.append(task_id)

        result.repaired = list(dict.fromkeys(result.repaired))
        return result

    def _assert_owned_scheduler_task(self, entry: Mapping[str, Any]) -> None:
        task_id = str(entry["task_id"])
        if not self.scheduler.task_exists(task_id):
            raise TaskNotFoundError(f"Windows Task fehlt: {task_id}")
        registration = self.scheduler.get_registration_metadata(task_id)
        if registration.get("source") != MANAGER_SOURCE:
            raise TaskOwnershipError(
                f"Scheduler-Task {task_id} existiert, ist aber nicht als {MANAGER_SOURCE}-Task markiert."
            )

    def _managed_info(self, entry: Mapping[str, Any]) -> ManagedTaskInfo:
        task_id = str(entry["task_id"])
        if self.scheduler.task_exists(task_id):
            raw = self.scheduler.get_task_info(task_id)
            return ManagedTaskInfo(
                task_id=task_id,
                owner=str(entry.get("owner") or ""),
                slug=str(entry.get("slug") or ""),
                name=str(entry.get("name") or task_id),
                scheduler_path=raw.path,
                exists=True,
                state=raw.state,
                enabled=raw.enabled,
                last_run_time=raw.last_run_time,
                next_run_time=raw.next_run_time,
                last_result=raw.last_result,
                trigger_types=raw.trigger_types,
                description=raw.description,
                local_state_file=entry.get("local_state_file"),
            )
        return ManagedTaskInfo(
            task_id=task_id,
            owner=str(entry.get("owner") or ""),
            slug=str(entry.get("slug") or ""),
            name=str(entry.get("name") or task_id),
            scheduler_path=str(entry.get("scheduler_path") or f"{self.scheduler.folder_path}\\{task_id}"),
            exists=False,
            local_state_file=entry.get("local_state_file"),
            description=str(entry.get("description") or ""),
        )

    def _refresh_entry_fingerprint(self, entry: Mapping[str, Any]) -> None:
        updated = dict(entry)
        updated["fingerprint"] = self.scheduler.fingerprint(updated["task_id"])
        updated["updated_at"] = _now_iso()
        self.registry.upsert(updated)

    def _discover_scheduler_managed(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for raw in self.scheduler.list_tasks(include_hidden=True):
            try:
                registration = self.scheduler.get_registration_metadata(raw.name)
            except Exception:
                continue
            if registration.get("source") != MANAGER_SOURCE:
                continue
            meta = registration.get("metadata") or {}
            task_id = str(meta.get("task_id") or raw.name)
            if not task_id.startswith("tsk_"):
                continue
            entry = {
                "task_id": task_id,
                "owner": _slugify(str(meta.get("owner") or "recovered"), fallback="recovered"),
                "slug": _slugify(str(meta.get("slug") or meta.get("name") or task_id)),
                "name": str(meta.get("name") or task_id),
                "task_type": str(meta.get("task_type") or "unknown"),
                "scheduler_name": raw.name,
                "scheduler_path": raw.path,
                "folder": self.scheduler.folder_path,
                "description": raw.description,
                "local_state_file": meta.get("local_state_file"),
                "created_at": str(meta.get("created_at") or _now_iso()),
                "updated_at": _now_iso(),
                "fingerprint": self.scheduler.fingerprint(raw.name),
                "metadata": {},
            }
            result[task_id] = entry
        return result


# ---------------------------------------------------------------------------
# Simple module-level facade
# ---------------------------------------------------------------------------

def scheduler(folder: str = DEFAULT_FOLDER) -> WindowsTaskScheduler:
    """Return the low-level Windows scheduler wrapper."""
    return WindowsTaskScheduler(folder)


def manager(
    *,
    owner: str | None = None,
    project_root: str | os.PathLike[str] | None = None,
    local_state_file: str | os.PathLike[str] | bool | None = None,
    global_state_file: str | os.PathLike[str] | None = None,
    folder: str = DEFAULT_FOLDER,
) -> PyTaskManager:
    return PyTaskManager(
        owner=owner,
        project_root=project_root,
        local_state_file=local_state_file,
        global_state_file=global_state_file,
        folder=folder,
    )


def create(
    source: NormalizedTaskSpec | Mapping[str, Any] | str,
    *,
    profile: TaskProfile | Mapping[str, Any] | None = None,
    overwrite: bool = True,
    owner: str | None = None,
    project_root: str | os.PathLike[str] | None = None,
    local_state_file: str | os.PathLike[str] | bool | None = None,
    global_state_file: str | os.PathLike[str] | None = None,
    folder: str = DEFAULT_FOLDER,
    **overrides: Any,
) -> ManagedTaskInfo:
    return manager(
        owner=owner,
        project_root=project_root,
        local_state_file=local_state_file,
        global_state_file=global_state_file,
        folder=folder,
    ).create(source, profile=profile, overwrite=overwrite, **overrides)


def create_task(
    name: str,
    executable: str | os.PathLike[str],
    *,
    owner: str | None = None,
    project_root: str | os.PathLike[str] | None = None,
    local_state_file: str | os.PathLike[str] | bool | None = None,
    global_state_file: str | os.PathLike[str] | None = None,
    folder: str = DEFAULT_FOLDER,
    **kwargs: Any,
) -> ManagedTaskInfo:
    return manager(
        owner=owner,
        project_root=project_root,
        local_state_file=local_state_file,
        global_state_file=global_state_file,
        folder=folder,
    ).create_task(name, executable, **kwargs)


def create_python_task(
    name: str,
    script: str | os.PathLike[str],
    *,
    owner: str | None = None,
    project_root: str | os.PathLike[str] | None = None,
    local_state_file: str | os.PathLike[str] | bool | None = None,
    global_state_file: str | os.PathLike[str] | None = None,
    folder: str = DEFAULT_FOLDER,
    **kwargs: Any,
) -> ManagedTaskInfo:
    return manager(
        owner=owner,
        project_root=project_root,
        local_state_file=local_state_file,
        global_state_file=global_state_file,
        folder=folder,
    ).create_python_task(name, script, **kwargs)


def task_exists(ref: Any, **manager_kwargs: Any) -> bool:
    return manager(**manager_kwargs).exists(ref)


def get_task_info(ref: Any, **manager_kwargs: Any) -> ManagedTaskInfo:
    return manager(**manager_kwargs).get(ref)


def list_tasks(**manager_kwargs: Any) -> list[ManagedTaskInfo]:
    owner_filter = manager_kwargs.get("owner")
    return manager(**manager_kwargs).list(owner=owner_filter)


def delete_task(ref: Any, *, missing_ok: bool = False, **manager_kwargs: Any) -> bool:
    return manager(**manager_kwargs).delete(ref, missing_ok=missing_ok)


def run_task(ref: Any, **manager_kwargs: Any):
    return manager(**manager_kwargs).run(ref)


def stop_task(ref: Any, **manager_kwargs: Any) -> None:
    manager(**manager_kwargs).stop(ref)


def enable_task(ref: Any, **manager_kwargs: Any) -> None:
    manager(**manager_kwargs).enable(ref)


def disable_task(ref: Any, **manager_kwargs: Any) -> None:
    manager(**manager_kwargs).disable(ref)


def reconcile(*, repair: bool = False, **manager_kwargs: Any) -> ReconcileResult:
    return manager(**manager_kwargs).reconcile(repair=repair)


# Short, readable aliases for application code.
def exists(ref: Any, **manager_kwargs: Any) -> bool:
    return task_exists(ref, **manager_kwargs)


def get(ref: Any, **manager_kwargs: Any) -> ManagedTaskInfo:
    return get_task_info(ref, **manager_kwargs)


def run(ref: Any, **manager_kwargs: Any):
    return run_task(ref, **manager_kwargs)


def stop(ref: Any, **manager_kwargs: Any) -> None:
    stop_task(ref, **manager_kwargs)


def enable(ref: Any, **manager_kwargs: Any) -> None:
    enable_task(ref, **manager_kwargs)


def disable(ref: Any, **manager_kwargs: Any) -> None:
    disable_task(ref, **manager_kwargs)


def delete(ref: Any, *, missing_ok: bool = False, **manager_kwargs: Any) -> bool:
    return delete_task(ref, missing_ok=missing_ok, **manager_kwargs)


def managed_tasks(*, local_only: bool = False, **manager_kwargs: Any) -> list[ManagedTaskInfo]:
    owner_filter = manager_kwargs.get("owner")
    return manager(**manager_kwargs).list(owner=owner_filter, local_only=local_only)


def delete_all_local(**manager_kwargs: Any) -> int:
    return manager(**manager_kwargs).delete_all_local()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_info(info: ManagedTaskInfo) -> None:
    for key, value in info.as_dict().items():
        print(f"{key:18}: {value}")


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PyTaskManager - verwaltete Windows Scheduled Tasks.")
    parser.add_argument("--folder", default=DEFAULT_FOLDER)
    parser.add_argument("--owner")
    parser.add_argument("--project-root")
    parser.add_argument("--global-state")
    parser.add_argument("--local-state")
    parser.add_argument("--no-local-state", action="store_true")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list")
    reconcile_parser = sub.add_parser("reconcile")
    reconcile_parser.add_argument("--repair", action="store_true")

    for command in ("info", "run", "stop", "enable", "disable", "delete"):
        child = sub.add_parser(command)
        child.add_argument("ref")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_cli_parser()
    args = parser.parse_args(argv)
    command = args.command or "list"
    local_state: str | bool | None = False if args.no_local_state else args.local_state

    try:
        managed = PyTaskManager(
            owner=args.owner,
            project_root=args.project_root,
            local_state_file=local_state,
            global_state_file=args.global_state,
            folder=args.folder,
        )

        if command == "list":
            items = managed.list()
            if not items:
                print("Keine verwalteten Tasks gefunden.")
                return 0
            for item in items:
                print(f"{item.task_id:18} {item.owner:18} {item.slug:24} {item.state:10} {item.name}")
            return 0

        if command == "reconcile":
            result = managed.reconcile(repair=args.repair)
            print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
            return 0

        if command == "info":
            _print_info(managed.get(args.ref))
        elif command == "run":
            managed.run(args.ref)
            print(f"Gestartet: {args.ref}")
        elif command == "stop":
            managed.stop(args.ref)
            print(f"Gestoppt: {args.ref}")
        elif command == "enable":
            managed.enable(args.ref)
            print(f"Aktiviert: {args.ref}")
        elif command == "disable":
            managed.disable(args.ref)
            print(f"Deaktiviert: {args.ref}")
        elif command == "delete":
            managed.delete(args.ref)
            print(f"Gelöscht: {args.ref}")
        return 0
    except Exception as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
