from __future__ import annotations

from typing import Any


class ManualExclusions:
    """Vom Nutzer nach manueller Pruefung ausgeschlossene Eintraege.

    Bewusst getrennt von der Quarantaene: Die Quarantaene sortiert automatisch
    und vorsichtig nach mehreren fehlgeschlagenen Laeufen aus. Manuelle
    Ausnahmen sind ein bewusster, sofort wirksamer und im ``reason``
    dokumentierter Ausschluss (z. B. eine Conversation, die dauerhaft HTTP 500
    liefert).

    Ausgeschlossene Conversations werden nicht abgerufen; ausgeschlossene
    Dateien gelten als abschliessend geklaert und blockieren ``files_complete``
    nicht.
    """

    def __init__(self, conversations: dict[str, str] | None = None,
                 files: dict[str, str] | None = None):
        self.conversations = {str(k): str(v or "") for k, v in (conversations or {}).items()}
        self.files = {str(k): str(v or "") for k, v in (files or {}).items()}

    def _table(self, kind: str) -> dict[str, str]:
        return self.conversations if kind == "conversation" else self.files

    def is_excluded(self, kind: str, identifier: Any) -> bool:
        return bool(identifier) and str(identifier) in self._table(kind)

    def reason(self, kind: str, identifier: Any) -> str | None:
        return self._table(kind).get(str(identifier))

    def summary(self) -> dict[str, int]:
        return {"conversations": len(self.conversations), "files": len(self.files)}
