"""ChatExporter – Raw Session Updater über mehrere Quellen.

Aufbau (siehe README.md und docs/):

- ``chatexporter.cli``        Bedienschicht: Menü und Befehle
- ``chatexporter.raw_session_updater``    Raw Session Updater: ruft alle Quellen über den Vertrag auf
- ``chatexporter.providers``  Quellen: chatgpt, opencode, codex, claude
"""

from chatexporter.config.version import __version__  # noqa: E402,F401  einzige Quelle
