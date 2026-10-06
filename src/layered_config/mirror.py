"""Spiegel des angewendeten Konfigurationszustands (nur schreibend).

Ein Spiegel bildet die wirksamen Werte nach jeder erfolgreich angewendeten
Konfiguration ab – nie vorher. Er wird nicht gelesen. ``RegistryMirror``
schreibt unter Windows nach ``HKEY_CURRENT_USER\\<key>``: je Einstellung ein
Wert (Name = Punkt-Pfad), Text unveraendert, alles andere als JSON. Werte, die
es nicht mehr gibt, werden entfernt, damit der Spiegel genau den Zustand zeigt.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol


class Mirror(Protocol):
    def write(self, values: Mapping[str, Any], meta: Mapping[str, str]) -> None: ...


class NullMirror:
    def write(self, values: Mapping[str, Any], meta: Mapping[str, str]) -> None:
        return None


class MemoryMirror:
    """Fuer Tests: haelt den zuletzt geschriebenen Zustand."""

    def __init__(self) -> None:
        self.values: dict[str, Any] | None = None
        self.meta: dict[str, str] | None = None
        self.writes = 0

    def write(self, values: Mapping[str, Any], meta: Mapping[str, str]) -> None:
        self.values = dict(values)
        self.meta = dict(meta)
        self.writes += 1


def encode(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class RegistryMirror:
    """Schreibt nach ``HKCU\\<values_key>``; Metadaten (Datei, Zeitpunkt) nach ``HKCU\\<meta_key>``."""

    def __init__(self, values_key: str, meta_key: str | None = None) -> None:
        self.values_key = values_key
        self.meta_key = meta_key

    @staticmethod
    def available() -> bool:
        return sys.platform == "win32"

    def write(self, values: Mapping[str, Any], meta: Mapping[str, str]) -> None:
        if not self.available():
            return
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.values_key, 0,
                                winreg.KEY_READ | winreg.KEY_WRITE) as key:
            existing: list[str] = []
            index = 0
            while True:
                try:
                    existing.append(winreg.EnumValue(key, index)[0])
                except OSError:
                    break
                index += 1
            for name, value in values.items():
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, encode(value))
            for name in existing:
                if name not in values:
                    try:
                        winreg.DeleteValue(key, name)
                    except OSError:
                        pass
        if self.meta_key:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.meta_key, 0, winreg.KEY_WRITE) as key:
                for name, value in meta.items():
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))

    def read_all(self) -> dict[str, str]:
        """Nur fuer Tests/Diagnose: der Spiegel wird von der Anwendung nicht gelesen."""
        if not self.available():
            return {}
        import winreg
        out: dict[str, str] = {}
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.values_key) as key:
                index = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, index)
                    except OSError:
                        break
                    out[name] = value
                    index += 1
        except OSError:
            return {}
        return out

    def delete_tree(self, root: str) -> None:
        """Nur fuer Tests: entfernt einen Testschluessel samt Unterschluesseln."""
        if not self.available():
            return
        import winreg

        def _delete(path: str) -> None:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ) as key:
                    children = []
                    index = 0
                    while True:
                        try:
                            children.append(winreg.EnumKey(key, index))
                        except OSError:
                            break
                        index += 1
                for child in children:
                    _delete(path + "\\" + child)
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except OSError:
                pass

        _delete(root)
