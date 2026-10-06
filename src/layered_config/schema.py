"""Beschreibung der Einstellungen eines Projekts und Typumwandlung."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from .errors import ConfigError

TYPES = ("str", "int", "float", "bool", "path", "list", "dict", "duration", "any")
_TRUE = {"1", "true", "yes", "on", "ja", "j", "y"}
_FALSE = {"0", "false", "no", "off", "nein", "n"}


@dataclass(frozen=True)
class Setting:
    """Eine Einstellung.

    ``path`` ist der Punkt-Pfad in der YAML-Datei (``storage.data_root``).
    ``default`` ``None`` heisst „kein Standardwert“; die Vorlage zeigt dann
    ``example`` (ein erkennbarer Beispielwert). ``env`` sind zusaetzliche,
    historisch gewachsene Umgebungsvariablen; jede Einstellung ist ausserdem
    ueber den generischen Namen ``<PREFIX>__<PFAD>`` erreichbar.
    ``secret``-Werte werden nie gespiegelt und in der Vorlage nur angedeutet.
    ``global_only``-Einstellungen gelten nur in der Grund-Config-Datei, nicht in
    einer zusaetzlichen Scope-Ebene (siehe ``ConfigManager(scope=...)``).
    """

    path: str
    default: Any = None
    type: str = "str"
    description: str = ""
    example: Any = None
    env: tuple[str, ...] = ()
    secret: bool = False
    choices: tuple[Any, ...] | None = None
    global_only: bool = False

    def __post_init__(self) -> None:
        if self.type not in TYPES:
            raise ValueError(f"{self.path}: unbekannter Typ {self.type!r}")

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(self.path.split("."))

    def coerce(self, value: Any) -> Any:
        """Wandelt einen Wert (auch Text aus Umgebung/CLI) in den Typ der Einstellung."""
        if value is None:
            return None
        kind = self.type
        try:
            if kind in ("str", "path"):
                if isinstance(value, (dict, list)):
                    raise TypeError("Text erwartet")
                out: Any = str(value)
            elif kind == "int":
                if isinstance(value, bool):
                    raise TypeError("Zahl erwartet")
                out = int(str(value).strip()) if not isinstance(value, int) else value
            elif kind == "float":
                if isinstance(value, bool):
                    raise TypeError("Zahl erwartet")
                out = float(value)
            elif kind == "bool":
                if isinstance(value, bool):
                    out = value
                elif isinstance(value, (int, float)) and value in (0, 1):
                    out = bool(value)
                else:
                    text = str(value).strip().lower()
                    if text in _TRUE:
                        out = True
                    elif text in _FALSE:
                        out = False
                    else:
                        raise ValueError("true/false erwartet")
            elif kind == "list":
                out = _as_list(value)
            elif kind == "dict":
                out = _as_dict(value)
            elif kind == "duration":
                if isinstance(value, bool):
                    raise TypeError("Dauer erwartet")
                out = value if isinstance(value, (int, float)) else str(value).strip()
            else:
                out = value
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{self.path}: ungueltiger Wert {value!r} ({exc})") from None
        if self.choices is not None:
            probe = out.lower() if isinstance(out, str) else out
            allowed = [c.lower() if isinstance(c, str) else c for c in self.choices]
            if probe not in allowed:
                raise ConfigError(f"{self.path}: {value!r} ist nicht erlaubt "
                                  f"(erlaubt: {', '.join(map(str, self.choices))})")
            out = self.choices[allowed.index(probe)]
        return out


def _parse_structured(text: str) -> Any:
    import yaml
    return yaml.safe_load(text)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("["):
            parsed = _parse_structured(text)
            if not isinstance(parsed, list):
                raise ValueError("Liste erwartet")
            return parsed
        return [part.strip() for part in text.split(",") if part.strip()]
    raise TypeError("Liste erwartet")


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip().startswith("{"):
        parsed = _parse_structured(value)
        if isinstance(parsed, dict):
            return parsed
    raise TypeError("Abschnitt/Objekt erwartet")


@dataclass
class Schema:
    """Alle Einstellungen eines Projekts in fester Reihenfolge."""

    settings: list[Setting]
    #: Beschreibung je Abschnitt (Pfad-Praefix), erscheint in der Vorlage.
    sections: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._by_path: dict[str, Setting] = {}
        for setting in self.settings:
            if setting.path in self._by_path:
                raise ValueError(f"doppelte Einstellung: {setting.path}")
            self._by_path[setting.path] = setting
        for setting in self.settings:
            for i in range(1, len(setting.parts)):
                prefix = ".".join(setting.parts[:i])
                if prefix in self._by_path:
                    raise ValueError(f"{prefix} ist Einstellung und Abschnitt zugleich")

    def __iter__(self):
        return iter(self.settings)

    def get(self, path: str) -> Setting | None:
        return self._by_path.get(path)

    def is_section(self, path: str) -> bool:
        prefix = path + "."
        return any(p.startswith(prefix) for p in self._by_path)

    def defaults(self) -> dict[str, Any]:
        return {s.path: _copy(s.default) for s in self.settings}

    def env_names(self) -> dict[str, str]:
        """Zusaetzliche Umgebungsvariablen -> Pfad."""
        out: dict[str, str] = {}
        for setting in self.settings:
            for name in setting.env:
                out[name] = setting.path
        return out

    def secrets(self) -> set[str]:
        return {s.path for s in self.settings if s.secret}

    def global_only(self) -> set[str]:
        return {s.path for s in self.settings if s.global_only}

    def scoped(self) -> "Schema":
        """Teilschema fuer eine Scope-Ebene (ohne ``global_only``-Einstellungen)."""
        keep = [s for s in self.settings if not s.global_only]
        prefixes = {".".join(s.parts[:i]) for s in keep for i in range(1, len(s.parts))}
        return Schema(keep, {k: v for k, v in self.sections.items() if k in prefixes})

    def paths(self) -> Iterable[str]:
        return self._by_path.keys()


def _copy(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.loads(json.dumps(value))
    return value
