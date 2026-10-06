"""Zusammenfuehren der Ebenen: die spaetere (spezifischere) Ebene gewinnt."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .errors import ConfigError
from .schema import Schema
from .sources import Layer, unflatten


@dataclass
class Resolved:
    """Wirksame Konfiguration: Werte (flach und verschachtelt) und Herkunft je Wert."""

    values: dict[str, Any]
    origins: dict[str, str]
    details: dict[str, str] = field(default_factory=dict)

    @property
    def document(self) -> dict[str, Any]:
        return unflatten(self.values)

    def get(self, path: str, default: Any = None) -> Any:
        if path in self.values:
            return self.values[path]
        prefix = path + "."
        sub = {p[len(prefix):]: v for p, v in self.values.items() if p.startswith(prefix)}
        return unflatten(sub) if sub else default

    def origin(self, path: str) -> str | None:
        return self.origins.get(path)

    def section(self, path: str) -> dict[str, Any]:
        value = self.get(path, {})
        return value if isinstance(value, dict) else {}


def resolve(schema: Schema, layers: Iterable[Layer], *, strict: bool = False) -> Resolved:
    """Defaults des Schemas, darueber die Ebenen in gegebener Reihenfolge.

    Unbekannte Schluessel bleiben erhalten (``strict=False``), damit fremde
    oder kuenftige Abschnitte nicht verloren gehen; mit ``strict=True`` sind sie
    ein Fehler. Werte bekannter Einstellungen werden in deren Typ umgewandelt.
    """
    values: dict[str, Any] = schema.defaults()
    origins = {path: "default" for path in values}
    details: dict[str, str] = {}
    for layer in layers:
        for path, raw in layer.values.items():
            setting = schema.get(path)
            if setting is None:
                if schema.is_section(path):
                    raise ConfigError(f"{path} ist ein Abschnitt, kein einzelner Wert")
                if strict:
                    raise ConfigError(f"Unbekannte Einstellung: {path}")
                value = raw
            else:
                value = setting.coerce(raw)
            # Ein ganzer Wert ersetzt fruehere Unterwerte desselben Pfads.
            stale = [p for p in values if p.startswith(path + ".")]
            for p in stale:
                values.pop(p)
                origins.pop(p, None)
            values[path] = value
            origins[path] = layer.name
            if layer.detail:
                details[layer.name] = layer.detail
    return Resolved(values, origins, details)
