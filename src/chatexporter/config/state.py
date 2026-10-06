"""Zustand eines Storages: Werte in der Registry, ``state.yaml`` als Gesamtsicht.

Die Zustandswerte **leben in der Registry** (``HKCU\\Software\\ChatExporter\\
Storages\\<id>\\State``, je Wert ein Eintrag, Inhalt JSON). ``state.yaml`` im
Verwaltungsbereich des Storages wird daraus erzeugt und **nie gelesen**; sie
zeigt alles Relevante auf einen Blick: Identitaet, Zustand, wirksame
Konfiguration mit Herkunft (Secrets nur als „gesetzt/nicht gesetzt“) und Pfade.

Ohne Registry (andere Plattform oder ``CHATEXPORTER_REGISTRY_MIRROR=off``)
liegen die Werte nur im Speicher des Prozesses.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from .storage import Identity, Storage

STATE_FILE_HEADER = (
    "# ChatExporter – Zustand dieses Storages.\n"
    "# Vom Programm nach jedem Befehl neu erzeugt (Quelle: Registry). Wird nie gelesen;\n"
    "# Aenderungen hier haben keine Wirkung. Konfiguration aendern: config set / config-global set.\n"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class StateStore(Protocol):
    def read(self) -> dict[str, Any]: ...

    def update(self, values: Mapping[str, Any]) -> None: ...


class MemoryState:
    """Ablage ohne Registry (je Prozess; fuer Tests und andere Plattformen)."""

    _data: dict[str, dict[str, Any]] = {}

    def __init__(self, identity: Identity) -> None:
        self.values = self._data.setdefault(identity.id, {})

    def read(self) -> dict[str, Any]:
        return dict(self.values)

    def update(self, values: Mapping[str, Any]) -> None:
        self.values.update(values)


class RegistryState:
    """``HKCU\\<storage-key>\\State``: je Zustandswert ein Eintrag (JSON-Text)."""

    def __init__(self, storage_key: str) -> None:
        self.base_key = storage_key
        self.key = storage_key + r"\State"

    def read(self) -> dict[str, Any]:
        import winreg
        out: dict[str, Any] = {}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.key) as key:
                index = 0
                while True:
                    try:
                        name, raw, _kind = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        out[name] = json.loads(raw)
                    except (TypeError, ValueError):
                        out[name] = raw
        except FileNotFoundError:
            pass
        return out

    def update(self, values: Mapping[str, Any]) -> None:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.key, 0, winreg.KEY_SET_VALUE) as key:
            for name, value in values.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ,
                                  json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))

    def write_info(self, values: Mapping[str, str]) -> None:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.base_key, 0, winreg.KEY_SET_VALUE) as key:
            for name, value in values.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))


def registry_enabled() -> bool:
    flag = str(os.environ.get("CHATEXPORTER_REGISTRY_MIRROR", "on")).strip().lower()
    return sys.platform == "win32" and flag not in ("0", "off", "false", "no", "nein")


def store_for(identity: Identity) -> StateStore:
    if registry_enabled():
        from . import storage_key
        return RegistryState(storage_key(identity))
    return MemoryState(identity)


def record(storage: Storage, identity: Identity, values: Mapping[str, Any]) -> StateStore:
    """Zustandswerte setzen (und in der Registry Ort und Name des Storages vermerken)."""
    store = store_for(identity)
    store.update(values)
    if isinstance(store, RegistryState):
        store.write_info({"Path": str(storage.root), "Name": identity.name})
    return store


def _nest(flat: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path in sorted(flat):
        node = out
        parts = path.split(".")
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = node[part] = {}
            node = child
        node[parts[-1]] = flat[path]
    return out


def render(loaded: Any, storage: Storage, identity: Identity, state: Mapping[str, Any], *,
           version: str) -> str:
    """Inhalt von ``state.yaml``."""
    import yaml
    from .schema import SCHEMA
    secrets = SCHEMA.secrets()
    config: dict[str, Any] = {}
    for path in sorted(loaded.values):
        value = loaded.values[path]
        if path in secrets:
            value = "(gesetzt)" if value not in (None, "") else "(nicht gesetzt)"
        config[path] = {"value": value, "origin": loaded.origin(path)}
    document = {
        "generated_at": now_iso(),
        "storage": {**identity.as_dict(), "root": str(storage.root), "program_version": version},
        "state": _nest({k: v for k, v in state.items()}),
        "config": config,
        "config_files": {"global": str(loaded.config_file),
                         "storage": str(storage.config_file),
                         "storage_env_present": storage.env_file.is_file()},
        "paths": storage.paths(),
    }
    return STATE_FILE_HEADER + yaml.safe_dump(document, sort_keys=False, allow_unicode=True, default_flow_style=False)


def write_state_file(loaded: Any, storage: Storage, identity: Identity, *, version: str) -> Path:
    text = render(loaded, storage, identity, store_for(identity).read(), version=version)
    storage.meta.mkdir(parents=True, exist_ok=True)
    tmp = storage.state_file.with_name(f".state.yaml.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, storage.state_file)
    return storage.state_file
