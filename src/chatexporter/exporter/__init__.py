"""Exporter: erzeugt lesbare Exporte (Markdown, JSON) aus dem Raw Storage.

Eigenstaendige Schicht neben Raw Session Updater, Providern und Zeitplanung.
Sie beginnt dort, wo deren Verantwortung endet: Sie liest ausschliesslich den
Raw Storage (``raw_storage/<quelle>/``), veraendert ihn nie und schreibt nur
abgeleitete Artefakte nach ``exports/``. Sie braucht weder Netz noch Anmeldung
und importiert weder den Raw Session Updater noch einen Provider.

- ``config``      Abschnitt ``exporter`` der gemeinsamen config.yaml
- ``sources``     Lesen der Rohdaten je Quelle und Aufbereitung zu einer neutralen Ansicht
- ``formats``     Ausgabeformate (Markdown, JSON)
- ``operations``  ``export``
- ``cli``         ``chatexporter export`` und ``chatexporter-export``
"""

from __future__ import annotations

from .config import ExporterConfig, load_exporter_config
from .operations import export

__all__ = ["ExporterConfig", "export", "load_exporter_config"]
