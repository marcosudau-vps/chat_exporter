"""layered_config – wiederverwendbare, geschichtete Konfiguration.

Projektunabhaengige Grundlage (kein Bezug auf ChatExporter): ein Projekt
beschreibt seine Einstellungen einmal als ``Schema`` und bekommt dafuer

- Zusammenfuehren aller Quellen, die spezifischere gewinnt
  (Defaults < Config-Datei < .env < [Scope-Datei < Scope-.env] < Prozess-Umgebung < CLI-Werte),
  optional mit einer zusaetzlichen Scope-Ebene (z. B. je Datenbestand),
- Typpruefung und Umwandlung (Text aus Umgebung/CLI -> int/bool/Liste ...),
- Herkunft jedes Werts (``origin``),
- eine vollstaendige, auskommentierte Vorlage der Config-Datei,
- Setzen/Zuruecksetzen einzelner Werte direkt in der YAML-Datei
  (Kommentare und Aufbau bleiben erhalten),
- einen Spiegel des angewendeten Zustands (z. B. Windows-Registry, nur schreibend).

Einstieg: ``ConfigManager`` (siehe ``manager.py``). Abhaengigkeiten: PyYAML,
optional python-dotenv; die Registry nur unter Windows (``winreg``).
"""

from __future__ import annotations

from .errors import ConfigError
from .manager import ConfigManager, Loaded, Scope
from .mirror import MemoryMirror, Mirror, NullMirror, RegistryMirror
from .resolver import Resolved, resolve
from .schema import Schema, Setting
from .sources import Layer

__all__ = ["ConfigError", "ConfigManager", "Layer", "Loaded", "MemoryMirror", "Mirror",
           "NullMirror", "RegistryMirror", "Resolved", "Schema", "Scope", "Setting", "resolve"]

__version__ = "0.1.0"
