"""Verzeichnis der Provider (Quellen) und Aufruf ihrer Vertragsfunktionen.

Der Raw Session Updater kennt Provider nur ueber den Modulpfad und die fuenf
Vertragsfunktionen. Geladen wird erst beim Aufruf (lazy), damit ein defekter
Provider den Raw Session Updater nicht am Start hindert. Neue Quelle einbinden = Modul unter
``providers/`` anlegen + EINE Zeile in ``PROVIDER_MODULES``.
"""

from __future__ import annotations

import inspect
from importlib import import_module
from typing import Any, Mapping

PROVIDER_MODULES: dict[str, str] = {
    "chatgpt": "chatexporter.providers.chatgpt",
    "opencode": "chatexporter.providers.opencode",
    "codex": "chatexporter.providers.codex",
    "claude": "chatexporter.providers.claude",
}

KNOWN_SOURCES: tuple[str, ...] = tuple(PROVIDER_MODULES)

CONTRACT_METHODS: tuple[str, ...] = (
    "update", "recreate_index", "check_storage_health", "cleanup_storage", "state_n_stats",
)


def provider_module(source: str) -> Any:
    try:
        dotted = PROVIDER_MODULES[source]
    except KeyError:
        raise ValueError(f"unbekannter Provider: {source}") from None
    return import_module(dotted)


def call(source: str, method: str, mapping: Mapping[str, Any],
         kwargs: Mapping[str, Any] | None = None) -> Any:
    """Ruft eine Vertragsfunktion auf.

    Optionen, die die Funktion nicht deklariert, werden herausgefiltert:
    schlanke Provider implementieren nur, was sie brauchen (z. B. kennt nur
    ChatGPT ``listing_mode``).
    """
    if method not in CONTRACT_METHODS:
        raise ValueError(f"keine Vertragsfunktion: {method}")
    fn = getattr(provider_module(source), method)
    options = dict(kwargs or {})
    try:
        params = inspect.signature(fn).parameters
        if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
            options = {k: v for k, v in options.items() if k in params}
    except (TypeError, ValueError):
        pass
    return fn(dict(mapping), **options)
