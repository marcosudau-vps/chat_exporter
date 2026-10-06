from __future__ import annotations


class ConfigError(ValueError):
    """Ungueltige Konfiguration (unbekannter Schluessel, falscher Typ, kaputte Datei)."""
