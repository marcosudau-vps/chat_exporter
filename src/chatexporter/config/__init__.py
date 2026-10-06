"""Gemeinsame Konfiguration aller Schichten des ChatExporters.

Einzige Stelle, an der Konfigurationsquellen gefunden, zusammengefuehrt und
gespiegelt werden (Grundlage: das projektunabhaengige Paket ``layered_config``).
Die Schichten (Raw Session Updater, Provider, Exporter, Zeitplanung,
Bedienschicht) lesen ihre Werte ausschliesslich ueber ``load()``.

Vorrang (spezifischer gewinnt):

    Standardwerte < config.yaml < .env < <storage>/.storage/config.yaml < <storage>/.storage/.env
                  < Umgebung < CLI-Werte (--set SCHLUESSEL=WERT)

Der **Storage** (Datenbestand, ``storage.py``) ist eine zusaetzliche, spezifischere
Ebene: ``storage.root`` (bzw. ``--storage``) waehlt ihn; ein leerer Ordner wird beim
ersten Gebrauch als Storage angelegt, ein Ordner im alten Format bleibt unberuehrt
(siehe ``storage_status``). Fuer alle Schichten ist danach ``storage.data_root``
die Wurzel des Storages.

Die config.yaml wird gesucht: ``--config`` > ``CHATEXPORTER_CONFIG`` >
(nur beim Start aus dem Quellcode) Aufstieg ab dem Arbeitsordner, ohne
Codeordner > ``<home>/config.yaml``. ``<home>`` ist ``CHATEXPORTER_HOME`` oder
``~/.chatexporter``. Fehlt die Datei, wird die vollstaendige, auskommentierte
Vorlage angelegt (``create_config_file``).

Nach jedem erfolgreich angewendeten Laden oder Aendern wird der wirksame
Zustand gespiegelt (nur schreibend; ``CHATEXPORTER_REGISTRY_MIRROR=off`` schaltet
das ab): je Storage nach ``HKCU\\Software\\ChatExporter\\Storages\\<id>\\Config\\Current``,
ohne Storage (altes Format) wie frueher nach ``...\\ChatExporter\\config\\Current``.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from layered_config import ConfigError, ConfigManager, Loaded, RegistryMirror, Resolved, Scope

from . import storage as storage_mod
from .schema import SCHEMA
from .storage import Storage, StorageError

APP_NAME = "ChatExporter"
ENV_PREFIX = "CHATEXPORTER"
HOME_ENV = "CHATEXPORTER_HOME"
CONFIG_ENV = "CHATEXPORTER_CONFIG"
MIRROR_ENV = "CHATEXPORTER_REGISTRY_MIRROR"
CONFIG_NAME = "config.yaml"
DEFAULT_HOME = Path("~/.chatexporter")
REGISTRY_VALUES_KEY = r"Software\ChatExporter\config\Current"
REGISTRY_META_KEY = r"Software\ChatExporter\config"
REGISTRY_STORAGES_KEY = r"Software\ChatExporter\Storages"

#: Abschnitte, die frueher auf oberster Ebene standen und zu ChatGPT gehoeren.
LEGACY_CHATGPT_SECTIONS = ("browser", "api", "sync")

HEADER = [
    "=============================================================================",
    "ChatExporter – Konfiguration (config.yaml)",
    "=============================================================================",
    "Vollstaendige Vorlage: JEDE Einstellung steht als eigene auskommentierte Zeile.",
    "Zum Setzen das '# ' vor der Zeile (und ggf. vor den Abschnittszeilen darueber)",
    "entfernen oder `chatexporter config set SCHLUESSEL WERT` verwenden.",
    "Zeilen mit Standardwert zeigen den echten Standard; Zeilen mit dem Hinweis",
    "BEISPIEL zeigen ausgedachte Werte, die so nicht stimmen.",
    "Relative Pfade gelten relativ zu dieser Datei. Secrets nur in die .env.",
    "Vorrang: Standard < config.yaml < .env < Umgebung < --set SCHLUESSEL=WERT.",
]

STORAGE_HEADER = [
    "=============================================================================",
    "ChatExporter – Storage-Konfiguration (.storage/config.yaml)",
    "=============================================================================",
    "Gilt nur fuer diesen Storage und ist spezifischer als die globale config.yaml",
    "(~/.chatexporter/config.yaml): Werte hier gewinnen. Jede Zeile ist auskommentiert;",
    "zum Setzen '# ' entfernen oder `chatexporter config set SCHLUESSEL WERT` verwenden.",
    "Programm-, Browser- und Ortseinstellungen gelten nur global (config-global).",
    "Relative Pfade gelten relativ zum Storage-Ordner. Secrets nur in die .env daneben.",
    "Vorrang: Standard < global < Storage < Storage-.env < Umgebung < --set.",
]

_cli_overrides: list[str] = []


def home() -> Path:
    raw = os.environ.get(HOME_ENV)
    return Path(raw).expanduser() if raw else DEFAULT_HOME.expanduser()


def is_code_folder(folder: Path) -> bool:
    """Versionsordner mit Code (``src/chatexporter``) enthalten keine gueltige Konfiguration."""
    return (folder / "src" / "chatexporter").is_dir()


def running_from_source() -> bool:
    """``False`` im installierten (eingefrorenen) Programm."""
    return not getattr(sys, "frozen", False)


def _discover(start: Path | None = None) -> Path | None:
    """Entwicklungsbetrieb: erste config.yaml beim Aufstieg ab dem Arbeitsordner."""
    if not running_from_source():
        return None
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        candidate = folder / CONFIG_NAME
        if candidate.is_file() and not is_code_folder(folder):
            return candidate
    return None


def _preprocess(document: dict[str, Any]) -> dict[str, Any]:
    """Aeltere Aufbauten: ``browser``/``api``/``sync`` auf oberster Ebene gehoeren zu ChatGPT."""
    doc = dict(document)
    providers = doc.get("providers")
    providers = dict(providers) if isinstance(providers, dict) else {}
    chatgpt = providers.get("chatgpt")
    chatgpt = dict(chatgpt) if isinstance(chatgpt, dict) else {}
    moved = False
    for name in LEGACY_CHATGPT_SECTIONS:
        if isinstance(doc.get(name), dict):
            if not isinstance(chatgpt.get(name), dict):
                chatgpt[name] = doc[name]
            doc.pop(name)
            moved = True
    if moved:
        providers["chatgpt"] = chatgpt
        doc["providers"] = providers
    return doc


class _SwitchableRegistryMirror(RegistryMirror):
    def write(self, values, meta) -> None:  # noqa: ANN001
        if str(os.environ.get(MIRROR_ENV, "on")).strip().lower() in ("0", "off", "false", "no", "nein"):
            return
        super().write(values, meta)


def storage_root(resolved: Resolved, base: Path) -> Path:
    """Wurzel des gewaehlten Storages: ``storage.root``; ist es nicht gesetzt, gilt
    der aeltere Name ``storage.data_root``. Relativ zum Ordner der globalen config.yaml."""
    raw = resolved.get("storage.root")
    if resolved.origin("storage.root") == "default" and resolved.get("storage.data_root") not in (None, ""):
        raw = resolved.get("storage.data_root")
    path = Path(str(raw)).expanduser()
    return path if path.is_absolute() else (base / path).resolve()


def storage_key(identity: storage_mod.Identity) -> str:
    return rf"{REGISTRY_STORAGES_KEY}\{identity.id}"


def _scope(resolved: Resolved, base: Path) -> Scope | None:
    """Storage als zusaetzliche Ebene. Altes oder unklares Format: keine Ebene (nichts anlegen)."""
    storage = Storage(storage_root(resolved, base))
    fmt, _reason = storage_mod.detect(storage.root)
    if fmt not in (storage_mod.FORMAT_CURRENT, storage_mod.FORMAT_EMPTY):
        return None
    identity = storage_mod.ensure(storage)
    key = storage_key(identity)
    return Scope("storage", storage.config_file, storage.env_file, storage.root,
                 _SwitchableRegistryMirror(key + r"\Config\Current", key + r"\Config"),
                 tuple(STORAGE_HEADER))


_MANAGER = ConfigManager(
    SCHEMA, env_prefix=ENV_PREFIX, home=home, config_name=CONFIG_NAME, config_env=CONFIG_ENV,
    discover=_discover, env_file_setting="bootstrap.env_file",
    dotenv_exclude=("bootstrap.venv_path",),
    mirror=_SwitchableRegistryMirror(REGISTRY_VALUES_KEY, REGISTRY_META_KEY),
    header=HEADER, preprocess=_preprocess, scope=_scope)


def manager() -> ConfigManager:
    return _MANAGER


def set_cli_overrides(items: Iterable[str]) -> None:
    """CLI-Werte (``SCHLUESSEL=WERT``) fuer diesen Prozess; gelten bei jedem ``load()``."""
    global _cli_overrides
    _cli_overrides = list(items)


def cli_overrides() -> list[str]:
    return list(_cli_overrides)


@contextmanager
def overrides(items: Iterable[str]) -> Iterator[None]:
    previous = cli_overrides()
    set_cli_overrides(items)
    try:
        yield
    finally:
        set_cli_overrides(previous)


def locate(config_path: Path | str | None = None) -> Path:
    return _MANAGER.locate(config_path)


def load(config_path: Path | str | None = None, *, extra: Iterable[str] | Mapping[str, Any] = ()) -> Loaded:
    """Wirksame Konfiguration (legt eine fehlende config.yaml an, spiegelt den Zustand)."""
    items: list[str] | Mapping[str, Any]
    if isinstance(extra, Mapping):
        items = {**dict(_parse(_cli_overrides)), **dict(extra)}
    else:
        items = [*_cli_overrides, *extra]
    return apply_storage(_MANAGER.load(config_path, items))


def apply_storage(loaded: Loaded) -> Loaded:
    """Fuer alle Schichten: ``storage.data_root`` ist die Wurzel des gewaehlten Storages."""
    root = storage_root(loaded.resolved, loaded.base)
    loaded.resolved.values["storage.data_root"] = str(root)
    loaded.resolved.origins["storage.data_root"] = "storage.root"
    return loaded


def storage_of(loaded: Loaded) -> Storage:
    return Storage(storage_root(loaded.resolved, loaded.base))


def storage_status(loaded: Loaded) -> dict[str, Any]:
    """Format und Identitaet des gewaehlten Storages (ohne etwas zu veraendern)."""
    storage = storage_of(loaded)
    fmt, reason = storage_mod.detect(storage.root)
    identity = storage_mod.read_identity(storage) if fmt == storage_mod.FORMAT_CURRENT else None
    return {"storage": storage, "format": fmt, "reason": reason, "identity": identity}


def require_storage(loaded: Loaded) -> tuple[Storage, storage_mod.Identity]:
    """Storage fuer Befehle, die mit Daten arbeiten; sonst ``StorageError`` mit Erklaerung."""
    status = storage_status(loaded)
    if status["identity"] is None:
        storage_mod.ensure(status["storage"])   # wirft mit Erklaerung (altes/unklares Format)
        status = storage_status(loaded)
    return status["storage"], status["identity"]


def _parse(items: Iterable[str]) -> list[tuple[str, str]]:
    out = []
    for item in items:
        if "=" in item:
            key, value = item.split("=", 1)
            out.append((key.strip(), value))
    return out


def resolve_path(loaded: Loaded, value: Any, key: str | None = None) -> Path | None:
    """Pfadwert aufloesen: relativ zum Ordner der Datei, aus der ``key`` stammt
    (Storage-Ordner bzw. Ordner der globalen config.yaml)."""
    if value in (None, ""):
        return None
    path = Path(str(value)).expanduser()
    base = loaded.base_for(key) if key else loaded.base
    return path if path.is_absolute() else (base / path).resolve()


__all__ = ["CONFIG_ENV", "ConfigError", "HOME_ENV", "Loaded", "SCHEMA", "Storage", "StorageError",
           "apply_storage", "cli_overrides", "home", "is_code_folder", "load", "locate", "manager",
           "overrides", "require_storage", "resolve_path", "running_from_source", "set_cli_overrides",
           "storage_of", "storage_root", "storage_status"]
