"""Konfiguration des Raw Session Updaters.

Der Raw Session Updater liest aus der gemeinsamen ``config.yaml`` nur, was er selbst
braucht: die Ablagepfade (``storage``), die aktiven Quellen
(``raw_session_updater.sources``) und die Provider-Sektionen (``providers.<quelle>``), die
es unveraendert an die Provider weiterreicht.

Die Werte kommen aus der gemeinsamen Konfiguration (``chatexporter.config``;
Vorrang: CLI-Werte > Prozess-Umgebung > ``.env`` > config.yaml > Standard).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import chatexporter.config as shared_config

from .registry import KNOWN_SOURCES

CONFIG_ENV = "CHATEXPORTER_CONFIG"
CONFIG_NAME = "config.yaml"


def program_info() -> dict[str, Any]:
    """Welcher Programmstand laeuft gerade, von wo, mit welchem Python?

    Liegt der Code in ``site-packages``, ist er eine feste Kopie: spaetere
    Aenderungen am Codeordner wirken dann erst nach einer Neuinstallation.
    """
    import sys
    # Einzige Quelle der Versionsnummer (Paket-Metadaten koennen veralten, z. B. die einer
    # Entwicklungsinstallation, die PyInstaller ins gebaute Programm uebernimmt).
    from chatexporter.config.version import __version__ as version
    package_dir = Path(__file__).resolve().parents[1]
    return {"version": version, "code": str(package_dir), "python": sys.executable,
            "fixed_copy": "site-packages" in package_dir.parts}


def program_banner() -> list[str]:
    info = program_info()
    lines = [f"Programm:       chatexporter {info['version']} aus {info['code']}",
             f"Python:         {info['python']}"]
    if info["fixed_copy"]:
        lines.append("WARNUNG: feste Kopie in site-packages – Aenderungen am Codeordner wirken "
                     "erst nach Neuinstallation (empfohlen: workspace\\.venv mit pip install -e).")
    return lines


def is_code_folder(folder: Path) -> bool:
    """Versionsordner mit Code (``src/chatexporter``) enthalten keine gueltige
    Konfiguration; eine dort liegende config.yaml stammt aus aelteren Staenden."""
    return (folder / "src" / "chatexporter").is_dir()


def discover_config(explicit: Path | None = None, *, start: Path | None = None) -> Path:
    """Pfad der gemeinsamen config.yaml (siehe ``chatexporter.config``).

    ``start`` sucht im Entwicklungsbetrieb ab diesem Ordner aufwaerts (ohne
    Codeordner), sofern weder ein Pfad noch ``CHATEXPORTER_CONFIG`` gesetzt ist.
    """
    if explicit is None and start is not None and not os.environ.get(CONFIG_ENV):
        found = shared_config._discover(start)
        if found is not None:
            return found
    return shared_config.locate(explicit)


@dataclass(slots=True)
class RawSessionUpdaterConfig:
    config_file: Path | None
    #: Wurzel der Quelldaten: ``<store_root>/<quelle>/`` (``raw_storage``).
    store_root: Path
    #: Betriebsablage: Laeufe, Staging, Statusablage, Uebersicht. Keine Quelldaten.
    runtime_root: Path
    status_root: Path
    sources: tuple[str, ...] = KNOWN_SOURCES
    provider_sections: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def data_root(self) -> Path:
        return self.store_root.parent

    @property
    def runs_dir(self) -> Path:
        return self.runtime_root / "runs"

    @property
    def staging_root(self) -> Path:
        return self.runtime_root / "staging"

    @property
    def index_path(self) -> Path:
        return self.status_root / "storage_index.json"

    @property
    def file_index_path(self) -> Path:
        return self.status_root / "file_index.json"

    @property
    def overview_path(self) -> Path:
        return self.runtime_root / "OVERVIEW.md"

    def ensure_runtime_dirs(self) -> None:
        for path in (self.runs_dir, self.staging_root / "runs",
                     self.staging_root / "index", self.status_root):
            path.mkdir(parents=True, exist_ok=True)

    def provider_mapping(self, source: str) -> dict[str, Any]:
        """Vertrags-Mapping fuer einen Provider.

        Provider-spezifische Schluessel kommen aus ``providers.<quelle>``; die
        Ablagepfade setzt immer der Raw Session Updater (sie koennen nicht ueberschrieben
        werden).
        """
        mapping: dict[str, Any] = dict(self.provider_sections.get(source) or {})
        mapping.update({
            "source": source,
            "config_file": self.config_file,
            "data_root": self.data_root,
            "raw_root": self.store_root,
            "store_root": self.store_root,
            "runtime_root": self.runtime_root,
            "status_root": self.status_root,
        })
        return mapping


def _sources(value: Any) -> tuple[str, ...]:
    if value is None:
        return KNOWN_SOURCES
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, (list, tuple)):
        items = [str(part).strip() for part in value if str(part).strip()]
    else:
        raise ValueError("raw_session_updater.sources muss eine Liste sein")
    unknown = [item for item in items if item not in KNOWN_SOURCES]
    if unknown:
        raise ValueError(f"Unbekannte Quelle(n) in raw_session_updater.sources: {', '.join(unknown)} "
                         f"(bekannt: {', '.join(KNOWN_SOURCES)})")
    return tuple(dict.fromkeys(items))


def _without_none(section: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in section.items():
        if isinstance(value, Mapping):
            out[key] = _without_none(value)
        elif value is not None:
            out[key] = value
    return out


def load_updater_config(config_path: Path | None = None, *,
                        overrides: Mapping[str, Any] | None = None) -> RawSessionUpdaterConfig:
    """Laedt die Updater-Konfiguration aus der gemeinsamen Konfiguration."""
    loaded = shared_config.load(config_path)
    config_file = loaded.config_file
    storage = loaded.resolved.section("storage")
    section = loaded.resolved.section("raw_session_updater")
    providers = loaded.resolved.section("providers")
    path = lambda value: shared_config.resolve_path(loaded, value)  # noqa: E731

    data_root = path(storage.get("data_root"))
    default_store = data_root / "raw_storage" if data_root else loaded.base / "raw_storage"
    store_root = path(storage.get("raw_root")) or default_store
    runtime_root = path(storage.get("runtime_root"))
    status_root = path(storage.get("status_root"))
    sources = _sources(section.get("sources"))

    for key, value in (overrides or {}).items():
        if value is None:
            continue
        if key == "raw_root":
            store_root = Path(value).expanduser().resolve()
        elif key == "runtime_root":
            runtime_root = Path(value).expanduser().resolve()
        elif key == "status_root":
            status_root = Path(value).expanduser().resolve()
        elif key == "sources":
            sources = _sources(value)

    # Gleiche Regel wie beim ChatGPT-Provider: <storage>/.storage (Verwaltungsbereich des Storages).
    runtime_root = runtime_root or (data_root / ".storage" if data_root else store_root.parent / ".storage")
    status_root = status_root or runtime_root / "status_registry"
    # Nicht gesetzte Werte (None) weglassen: der Provider nimmt dann seinen eigenen Standard.
    sections = {name: _without_none(section) for name, section in providers.items()
                if isinstance(section, dict)} if isinstance(providers, dict) else {}
    return RawSessionUpdaterConfig(config_file=config_file, store_root=store_root,
                                   runtime_root=runtime_root, status_root=status_root,
                                   sources=sources, provider_sections=sections)
