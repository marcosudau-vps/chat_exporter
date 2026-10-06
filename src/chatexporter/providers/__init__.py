"""Quellen (Provider) des Raw Session Updaters.

Jeder Provider ist eigenständig: er hängt weder vom Raw Session Updater noch von anderen
Providern ab und bietet dieselben fünf Vertragsfunktionen
(``update``, ``recreate_index``, ``check_storage_health``, ``cleanup_storage``,
``state_n_stats``) sowie eine eigene Kommandozeile ``main``.

- ``chatgpt``   ChatGPT-Weboberfläche (Edge per CDP, Backend-API) – Paket
- ``opencode``  OpenCode v2 (lokale SQLite-DB + ``opencode session export``)
- ``codex``     Codex CLI (``~/.codex/sessions``)
- ``claude``    Claude Code (``~/.claude/projects``)
"""
