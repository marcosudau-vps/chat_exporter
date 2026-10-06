"""Konfiguration des Exporters (Abschnitt ``exporter`` der gemeinsamen Konfiguration).

Die Werte kommen aus ``chatexporter.config`` (Vorrang: CLI-Werte > Umgebung >
``.env`` > config.yaml > Standard); hier werden nur die Pfade abgeleitet und
Formate/Quellen geprueft.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import chatexporter.config as shared_config

#: Ausgabeformate und Quellen, fuer die ein Exporter existiert.
KNOWN_FORMATS = ("markdown", "json")
EXPORTABLE_SOURCES = ("chatgpt", "opencode", "codex", "claude")
#: Kurzformen auf der Kommandozeile.
FORMAT_ALIASES = {"md": "markdown", "markdown": "markdown", "json": "json"}


class ExporterConfigError(ValueError):
    """Ungueltige Exporter-Konfiguration (Exitcode 2)."""


def discover_config(explicit: Path | None = None) -> Path:
    return shared_config.locate(explicit)


@dataclass(slots=True)
class ExporterConfig:
    config_file: Path | None
    #: Wurzel der Quelldaten (``raw_storage``); wird nur gelesen.
    raw_root: Path
    #: Ziel der Exporte (``exports``).
    export_root: Path
    formats: tuple[str, ...] = KNOWN_FORMATS
    sources: tuple[str, ...] = EXPORTABLE_SOURCES
    #: Zwischenablage fuer atomares Schreiben (Standard: <storage>/.storage/staging/exports).
    staging_root: Path | None = None

    @property
    def manifests_dir(self) -> Path:
        return self.export_root / "manifests"

    @property
    def staging_dir(self) -> Path:
        return self.staging_root or self.export_root / ".staging"


def _names(value: Any, known: tuple[str, ...], what: str, aliases: Mapping[str, str] | None = None) -> tuple[str, ...]:
    if value is None:
        return known
    if isinstance(value, str):
        items = [part.strip().lower() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple)):
        items = [str(part).strip().lower() for part in value if str(part).strip()]
    else:
        raise ExporterConfigError(f"{what} muss eine Liste sein")
    if aliases:
        items = [aliases.get(item, item) for item in items]
    unknown = [item for item in items if item not in known]
    if unknown:
        raise ExporterConfigError(f"Unbekannte {what}: {', '.join(unknown)} (bekannt: {', '.join(known)})")
    return tuple(dict.fromkeys(items))


def load_exporter_config(config_path: Path | None = None, *,
                         overrides: Mapping[str, Any] | None = None) -> ExporterConfig:
    """Laedt die Exporter-Konfiguration aus der gemeinsamen Konfiguration."""
    try:
        loaded = shared_config.load(config_path)
    except shared_config.ConfigError as exc:
        raise ExporterConfigError(str(exc)) from None
    storage = loaded.resolved.section("storage")
    section = loaded.resolved.section("exporter")
    path = lambda value, key=None: shared_config.resolve_path(loaded, value, key)  # noqa: E731

    data_root = path(storage.get("data_root"))
    raw_root = path(storage.get("raw_root")) or (data_root / "raw_storage" if data_root
                                                 else loaded.base / "raw_storage")
    export_root = path(section.get("root"), "exporter.root") or (data_root / "exports" if data_root
                                                else raw_root.parent / "exports")
    formats = _names(section.get("formats"), KNOWN_FORMATS, "Exportformate", FORMAT_ALIASES)
    sources = _names(section.get("sources"), EXPORTABLE_SOURCES, "Exportquellen")

    for key, value in (overrides or {}).items():
        if value is None:
            continue
        if key == "raw_root":
            raw_root = Path(value).expanduser().resolve()
        elif key == "export_root":
            export_root = Path(value).expanduser().resolve()
        elif key == "formats":
            formats = _names(list(value), KNOWN_FORMATS, "Exportformate", FORMAT_ALIASES)
        elif key == "sources":
            sources = _names(list(value), EXPORTABLE_SOURCES, "Exportquellen")
    staging_root = (data_root / ".storage" / "staging" / "exports") if data_root else None
    return ExporterConfig(config_file=loaded.config_file, raw_root=raw_root, export_root=export_root,
                          formats=formats, sources=sources, staging_root=staging_root)
