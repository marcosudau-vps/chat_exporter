"""Konfigurationsquellen als flache Ebenen ``{punkt.pfad: wert}``."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .errors import ConfigError
from .schema import Schema


@dataclass
class Layer:
    """Eine Quelle: Name (fuer ``origin``), Werte, optional Herkunftsdetail (Datei)."""

    name: str
    values: dict[str, Any] = field(default_factory=dict)
    detail: str = ""


def flatten(document: Mapping[str, Any], schema: Schema, prefix: str = "") -> dict[str, Any]:
    """Verschachteltes Dokument -> ``{pfad: wert}``.

    Abschnitte werden aufgeloest; Einstellungen vom Typ ``dict``/``any`` bleiben
    als Ganzes erhalten. ``None`` an der Stelle eines Abschnitts (``providers:``
    ohne aktive Unterpunkte) bedeutet „leer“.
    """
    out: dict[str, Any] = {}
    for key, value in document.items():
        path = f"{prefix}{key}"
        setting = schema.get(path)
        if setting is not None and setting.type in ("dict", "any"):
            out[path] = value
        elif isinstance(value, Mapping):
            out.update(flatten(value, schema, path + "."))
        elif value is None and schema.is_section(path):
            continue
        else:
            out[path] = value
    return out


def unflatten(flat: Mapping[str, Any]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for path, value in flat.items():
        parts = path.split(".")
        node = root
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = value
    return root


def read_yaml(path: Path) -> dict[str, Any]:
    import yaml
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: kein gueltiges YAML ({exc})") from None
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"{path}: die Datei muss ein YAML-Objekt (Abschnitte) enthalten")
    return loaded


def yaml_layer(path: Path, schema: Schema, *, name: str = "config", document: Mapping[str, Any] | None = None) -> Layer:
    doc = read_yaml(path) if document is None else document
    return Layer(name, flatten(doc, schema), str(path))


def _text_value(value: str) -> Any:
    """Text aus Umgebung/CLI: strukturierte Werte (``[..]``, ``{..}``) parsen, sonst Text."""
    stripped = value.strip()
    if stripped[:1] in ("[", "{"):
        import yaml
        try:
            return yaml.safe_load(stripped)
        except yaml.YAMLError:
            return value
    return value


def environment_layer(environ: Mapping[str, str | None], schema: Schema, *, prefix: str, name: str,
                      exclude: Iterable[str] = ()) -> Layer:
    """Werte aus Umgebungsvariablen.

    Erkannt werden die in ``Setting.env`` genannten Namen und der generische Name
    ``<PREFIX>__<ABSCHNITT>__<SCHLUESSEL>`` (``__`` trennt die Pfadteile).
    """
    excluded = set(exclude)
    named = schema.env_names()
    values: dict[str, Any] = {}
    generic = f"{prefix}__"
    # Generische Namen zuerst, damit die ausdruecklich benannten gewinnen.
    for key, raw in environ.items():
        if raw is None or not key.upper().startswith(generic):
            continue
        path = key[len(generic):].lower().replace("__", ".")
        if path and path not in excluded:
            values[path] = _text_value(str(raw))
    for key, path in named.items():
        raw = environ.get(key)
        if raw is not None and path not in excluded:
            values[path] = _text_value(str(raw))
    return Layer(name, values)


def overrides_layer(items: Iterable[str] | Mapping[str, Any], *, name: str = "cli") -> Layer:
    """CLI-Werte ``pfad=wert`` (oder ein Mapping)."""
    values: dict[str, Any] = {}
    if isinstance(items, Mapping):
        for key, value in items.items():
            values[str(key)] = _text_value(value) if isinstance(value, str) else value
        return Layer(name, values)
    for item in items:
        if "=" not in item:
            raise ConfigError(f"CLI-Wert {item!r}: erwartet SCHLUESSEL=WERT")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigError(f"CLI-Wert {item!r}: Schluessel fehlt")
        values[key] = _text_value(value)
    return Layer(name, values)
