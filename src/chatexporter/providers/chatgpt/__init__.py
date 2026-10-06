"""ChatGPT-Provider.

Sichert Konversationen und Dateien ueber die ChatGPT-Weboberflaeche (Edge per
CDP, interne Backend-API). Eigenstaendig: haengt weder vom Raw Session Updater noch von
anderen Providern ab.

Vertragsfunktionen: ``update``, ``recreate_index``, ``check_storage_health``,
``cleanup_storage``, ``state_n_stats`` (siehe ``contract.py``).
Kommandozeile: ``main`` (``chatexporter-chatgpt``).

Die Funktionen werden erst beim ersten Zugriff geladen, damit ein Import von
Teilmodulen (z. B. ``storage``) nicht den Browser-Stack nachzieht.
"""

from __future__ import annotations

from typing import Any

SOURCE = "chatgpt"

_CONTRACT = ("update", "recreate_index", "check_storage_health",
             "cleanup_storage", "state_n_stats")

__all__ = ["SOURCE", "main", *_CONTRACT]


def __getattr__(name: str) -> Any:
    if name in _CONTRACT:
        from . import contract
        return getattr(contract, name)
    if name == "main":
        from .cli import main
        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
