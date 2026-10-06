"""Raw Session Updater ueber alle Quellen (frueher "Wrapper").

Der Raw Session Updater ruft die Provider ueber ihren Vertrag auf (``registry``), fuehrt
Index-Fragmente zum Gesamtindex zusammen (``fragments``), schreibt je Lauf
einen Laufbericht (``manifest``) und erzeugt die Uebersicht. Es haengt von
keinem Provider-Code ab -- Provider werden nur ueber ihren Modulpfad geladen.
"""

from __future__ import annotations

from .config import RawSessionUpdaterConfig, discover_config, load_updater_config
from .operations import check_health, cleanup, rebuild_index, status, update
from .registry import CONTRACT_METHODS, KNOWN_SOURCES, PROVIDER_MODULES

__all__ = [
    "RawSessionUpdaterConfig", "discover_config", "load_updater_config",
    "update", "rebuild_index", "check_health", "cleanup", "status",
    "CONTRACT_METHODS", "KNOWN_SOURCES", "PROVIDER_MODULES",
]
