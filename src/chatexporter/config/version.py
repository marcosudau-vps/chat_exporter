"""Versionsnummer des Programms – einzige Quelle im Code (dazu ``pyproject.toml`` fuer das Paket).

Liegt in ``chatexporter.config``, weil alle Schichten (auch Provider und Raw Session Updater,
siehe ``tests/test_independence.py``) diesen Kern importieren duerfen. Paket-Metadaten werden
bewusst nicht gelesen: die einer Entwicklungsinstallation koennen veralten und gelangen beim
Bauen ins Programm.
"""

__version__ = "0.0.1rc3"
