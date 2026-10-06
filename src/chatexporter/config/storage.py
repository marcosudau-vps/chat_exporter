"""Storage: eine autarke Dateninstanz (Daten, Zustand, Konfiguration, Registry-Bereich).

Aufbau (siehe ``docs/STORAGE_KONZEPT.md``)::

    <storage>/
    ├── .storage/              Verwaltungsbereich (frueher „runtime“)
    │   ├── storage.yaml       Marker: Format-Version, ID, Name, Anlagezeitpunkt (einmal geschrieben)
    │   ├── config.yaml        Storage-Konfiguration (gelesen)
    │   ├── .env               Storage-Secrets (gelesen)
    │   ├── state.yaml         Gesamtsicht (nur geschrieben)
    │   ├── logs/ runs/ status_registry/ tasks_sched.json OVERVIEW.md
    │   ├── staging/           Zwischenablage (leere Ordner werden entfernt)
    │   └── lock               Sperre fuer schreibende Laeufe
    ├── raw_storage/<quelle>/
    └── exports/

Formaterkennung nur ueber eindeutige Marker (``detect``); veraendert wird ein
Ordner nur, wenn er leer oder bereits ein Storage ist (``ensure``).

Versionierung: Das Format eines Storages heisst **Storage-Schema** und hat eine
eigene Nummer, die nichts mit der Programmversion zu tun hat. Storage-Schema 1
ist der Datenordner mit ``runtime/`` (ohne Marker, an seinen Ordnern erkannt);
Storage-Schema 2 ist dieser Aufbau mit ``.storage/`` und dem Marker
``storage_schema: 2``. Dokumentation je Storage-Schema: ``docs/storage_schema/``.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

#: Storage-Schema, das dieses Programm schreibt und liest (nicht die Programmversion).
STORAGE_SCHEMA = 2
#: Storage-Schema des aelteren Datenordners mit ``runtime/`` (nur ueber ``storage migrate``).
LEGACY_STORAGE_SCHEMA = 1
META_DIR = ".storage"
MARKER = "storage.yaml"
LEGACY_RUNTIME = "runtime"
RAW_DIR = "raw_storage"

FORMAT_CURRENT = f"storage-schema-{STORAGE_SCHEMA}"
FORMAT_LEGACY = f"storage-schema-{LEGACY_STORAGE_SCHEMA}"
FORMAT_EMPTY = "leer"
FORMAT_UNCLEAR = "unklar"
#: Nicht leerer Ordner ohne jedes Storage-Kennzeichen (z. B. versehentlich „Dokumente“ gewaehlt).
FORMAT_FOREIGN = "fremd"
#: ``.storage/`` ohne Marker, aber mit Betriebsdaten und ``raw_storage/``: eine Umstellung wurde
#: zwischen „runtime/ umbenennen“ und „Marker schreiben“ abgebrochen (oder der Marker ging verloren).
FORMAT_INTERRUPTED = "umstellung-abgebrochen"

#: Dateien, die Windows/macOS in jeden Ordner legen; sie machen einen Ordner nicht „fremd“.
IGNORABLE_FILES = frozenset({"desktop.ini", "thumbs.db", ".ds_store"})


class StorageError(RuntimeError):
    """Storage ist in einem Format, mit dem nicht gearbeitet werden darf."""


class StorageBusy(StorageError):
    """Ein anderer schreibender Lauf haelt die Sperre dieses Storages."""


@dataclass(frozen=True)
class Storage:
    root: Path

    @property
    def meta(self) -> Path:
        return self.root / META_DIR

    @property
    def marker(self) -> Path:
        return self.meta / MARKER

    @property
    def config_file(self) -> Path:
        return self.meta / "config.yaml"

    @property
    def env_file(self) -> Path:
        return self.meta / ".env"

    @property
    def state_file(self) -> Path:
        return self.meta / "state.yaml"

    @property
    def logs_dir(self) -> Path:
        return self.meta / "logs"

    @property
    def runs_dir(self) -> Path:
        return self.meta / "runs"

    @property
    def status_dir(self) -> Path:
        return self.meta / "status_registry"

    @property
    def tasks_state(self) -> Path:
        return self.meta / "tasks_sched.json"

    @property
    def staging(self) -> Path:
        return self.meta / "staging"

    @property
    def lock_file(self) -> Path:
        return self.meta / "lock"

    @property
    def raw_root(self) -> Path:
        return self.root / RAW_DIR

    @property
    def exports_root(self) -> Path:
        return self.root / "exports"

    def paths(self) -> dict[str, str]:
        return {name: str(getattr(self, name)) for name in (
            "root", "meta", "config_file", "env_file", "state_file", "logs_dir", "runs_dir", "status_dir",
            "tasks_state", "staging", "lock_file", "raw_root", "exports_root")}


@dataclass(frozen=True)
class Identity:
    id: str
    name: str
    storage_schema: int
    created_at: str

    def as_dict(self) -> dict[str, object]:
        return {"storage_schema": self.storage_schema, "id": self.id, "name": self.name,
                "created_at": self.created_at}


def read_identity(storage: Storage) -> Identity | None:
    """Marker lesen; ``None``, wenn er fehlt oder ungueltig ist."""
    import yaml
    try:
        data = yaml.safe_load(storage.marker.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return None
    if not isinstance(data, dict) or not data.get("id") or not isinstance(data.get("storage_schema"), int):
        return None
    return Identity(str(data["id"]), str(data.get("name") or storage.root.name), int(data["storage_schema"]),
                    str(data.get("created_at") or ""))


def detect(root: Path) -> tuple[str, str]:
    """(Format, Begruendung). Nur eindeutige Marker zaehlen."""
    root = Path(root)
    meta, legacy, raw = root / META_DIR, root / LEGACY_RUNTIME, root / RAW_DIR
    if meta.exists():
        identity = read_identity(Storage(root))
        if legacy.is_dir():
            return FORMAT_UNCLEAR, f"{META_DIR}/ und {LEGACY_RUNTIME}/ zugleich vorhanden"
        if identity is None:
            markers = [name for name in ("runs", "status_registry") if (meta / name).is_dir()]
            if markers and raw.is_dir():
                return FORMAT_INTERRUPTED, (f"{META_DIR}/ ({', '.join(markers)}) und {RAW_DIR}/, aber ohne {MARKER}: "
                                            "Umstellung abgebrochen oder Marker verloren")
            return FORMAT_UNCLEAR, f"{META_DIR}/ ohne gueltige {MARKER}"
        if identity.storage_schema != STORAGE_SCHEMA:
            return FORMAT_UNCLEAR, (f"Storage-Schema {identity.storage_schema} "
                                    f"(dieses Programm kennt Storage-Schema {STORAGE_SCHEMA})")
        return FORMAT_CURRENT, f"{META_DIR}/{MARKER} mit storage_schema {identity.storage_schema}"
    if legacy.is_dir():
        markers = [name for name in ("runs", "status_registry") if (legacy / name).is_dir()]
        if markers and raw.is_dir():
            return FORMAT_LEGACY, f"{LEGACY_RUNTIME}/ ({', '.join(markers)}) und {RAW_DIR}/ ohne {META_DIR}/"
        return FORMAT_UNCLEAR, f"{LEGACY_RUNTIME}/ ohne die erwarteten Marker"
    if raw.is_dir():
        return FORMAT_UNCLEAR, f"{RAW_DIR}/ ohne {META_DIR}/ und ohne {LEGACY_RUNTIME}/"
    content = sorted(p.name for p in root.iterdir() if p.name.lower() not in IGNORABLE_FILES) \
        if root.is_dir() else []
    if content:
        shown = ", ".join(content[:3]) + (" …" if len(content) > 3 else "")
        return FORMAT_FOREIGN, f"Ordner ist nicht leer und kein Storage (enthaelt {shown})"
    return FORMAT_EMPTY, "Ordner fehlt oder ist leer"


def new_identity(storage: Storage) -> Identity:
    return Identity(uuid.uuid4().hex, storage.root.name, STORAGE_SCHEMA,
                    datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))


def write_identity(storage: Storage, identity: Identity) -> None:
    import yaml
    storage.meta.mkdir(parents=True, exist_ok=True)
    text = ("# ChatExporter-Storage – Marker (storage_schema = Storage-Schema, nicht Programmversion). Nicht aendern.\n"
            + yaml.safe_dump(identity.as_dict(), sort_keys=False, allow_unicode=True))
    tmp = storage.marker.with_name(f".{MARKER}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, storage.marker)


def ensure(storage: Storage) -> Identity:
    """Storage benutzbar machen: leer -> anlegen, v1 -> Identitaet lesen, sonst ``StorageError``."""
    fmt, reason = detect(storage.root)
    if fmt == FORMAT_CURRENT:
        return read_identity(storage)  # type: ignore[return-value]
    if fmt == FORMAT_EMPTY:
        identity = new_identity(storage)
        write_identity(storage, identity)
        return identity
    if fmt == FORMAT_LEGACY:
        raise StorageError(f"{storage.root} hat Storage-Schema {LEGACY_STORAGE_SCHEMA} ({reason}). "
                           f"Umstellen mit: chatexporter storage migrate")
    if fmt == FORMAT_INTERRUPTED:
        raise StorageError(f"{storage.root}: {reason}. Fortsetzen mit: chatexporter storage migrate; "
                           "nichts wurde veraendert")
    if fmt == FORMAT_FOREIGN:
        raise StorageError(f"{storage.root}: {reason}. Bitte einen leeren oder neuen Ordner als Storage "
                           "waehlen; nichts wurde veraendert")
    raise StorageError(f"{storage.root} ist kein eindeutig erkennbarer Storage ({reason}); "
                       "nichts wurde veraendert")


@contextmanager
def storage_lock(storage: Storage, holder: str):
    """Hoechstens ein schreibender Lauf je Storage (``.storage/lock``).

    Die Sperre haelt das Betriebssystem (wird auch bei einem Absturz frei);
    ``lock.json`` daneben nennt den Inhaber, solange der Lauf dauert.
    """
    storage.meta.mkdir(parents=True, exist_ok=True)
    info_file = storage.meta / "lock.json"
    handle = open(storage.lock_file, "a+b")
    try:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        try:
            info = json.loads(info_file.read_text(encoding="utf-8"))
            who = f"{info.get('command')} (PID {info.get('pid')}, seit {info.get('since')})"
        except (OSError, ValueError):
            who = "ein anderer Lauf"
        raise StorageBusy(f"{storage.root} wird gerade benutzt: {who}") from None
    try:
        info_file.write_text(json.dumps({
            "pid": os.getpid(), "command": holder,
            "since": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }, ensure_ascii=False), encoding="utf-8")
        yield
    finally:
        try:
            info_file.unlink()
        except OSError:
            pass
        try:
            handle.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        handle.close()


def cleanup_staging(storage: Storage) -> int:
    """Leere Zwischenablage-Ordner des Storages entfernen (``staging/`` und ``status_registry/.staging``)."""
    return prune_empty_dirs(storage.staging) + prune_empty_dirs(storage.status_dir / ".staging")


def _merge_move(source: Path, target: Path, steps: list[str], *, dry_run: bool) -> None:
    """``source`` nach ``target`` verschieben; existiert ``target``, Inhalt einzeln einordnen."""
    if not source.exists():
        return
    if not target.exists():
        steps.append(f"verschieben: {source} -> {target}")
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
        return
    for child in sorted(source.iterdir()):
        _merge_move(child, target / child.name, steps, dry_run=dry_run)
    steps.append(f"entfernen (leer): {source}")
    if not dry_run:
        prune_empty_dirs(source)


def migrate(root: Path, *, dry_run: bool = False) -> dict[str, object]:
    """Storage-Schema 1 (Datenordner mit ``runtime/``) auf Storage-Schema 2 umstellen.

    Schritte (nur bei eindeutigem Format, Rohdaten bleiben unberuehrt):
    1. ``runtime/`` -> ``.storage/`` (Umbenennen im selben Ordner, atomar)
    2. ``.storage/.staging/`` -> ``.storage/staging/``, ``exports/.staging/`` ->
       ``.storage/staging/exports/`` (Reste werden eingeordnet, leere Ordner entfernt)
    3. ``.storage/storage.yaml`` schreiben (erst danach gilt der Ordner als Storage-Schema 2)

    Fortsetzbar: Wurde nach Schritt 1 abgebrochen (``FORMAT_INTERRUPTED``), setzt ein
    erneuter Aufruf mit Schritt 2 fort. Jeder Schritt ist wiederholbar.
    """
    storage = Storage(Path(root))
    fmt, reason = detect(storage.root)
    if fmt == FORMAT_CURRENT:
        return {"ok": True, "changed": False, "format": fmt, "steps": [],
                "message": f"bereits Storage-Schema {STORAGE_SCHEMA}"}
    if fmt not in (FORMAT_LEGACY, FORMAT_INTERRUPTED):
        raise StorageError(f"{storage.root}: keine Migration moeglich – Format {fmt} ({reason}); nichts veraendert")
    steps: list[str] = []
    legacy = storage.root / LEGACY_RUNTIME
    if fmt == FORMAT_LEGACY:
        steps.append(f"umbenennen: {legacy} -> {storage.meta}")
        if not dry_run:
            os.replace(legacy, storage.meta)
        meta = storage.meta if not dry_run else legacy
    else:
        steps.append(f"fortsetzen: {legacy} ist bereits in {storage.meta} umbenannt")
        meta = storage.meta
    _merge_move(meta / ".staging", (meta / "staging") if not dry_run else storage.staging, steps, dry_run=dry_run)
    _merge_move(storage.root / "exports" / ".staging", storage.staging / "exports", steps, dry_run=dry_run)
    identity = new_identity(storage)
    steps.append(f"Marker schreiben: {storage.marker}" + ("" if dry_run else f" (id {identity.id})"))
    if not dry_run:
        cleanup_staging(storage)
        write_identity(storage, identity)
    return {"ok": True, "changed": not dry_run, "format": fmt, "dry_run": dry_run, "steps": steps,
            "identity": identity.as_dict() if not dry_run else None}


def prune_empty_dirs(folder: Path, *, keep_root: bool = False) -> int:
    """Leere Unterordner (von unten nach oben) entfernen. Rueckgabe: Anzahl entfernter Ordner."""
    folder = Path(folder)
    if not folder.is_dir():
        return 0
    removed = 0
    for current, dirs, files in os.walk(folder, topdown=False):
        path = Path(current)
        if path == folder and keep_root:
            continue
        try:
            if not any(path.iterdir()):
                path.rmdir()
                removed += 1
        except OSError:
            continue
    return removed
