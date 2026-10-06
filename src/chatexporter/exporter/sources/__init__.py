"""Rohdatenquellen des Exporters.

Jede Quelle liefert die gespeicherten Gespraeche als **neutrale Ansicht**
(``view``: ``conversation_id``, ``title``, ``create_time``, ``messages`` …), die
die Ausgabeformate unabhaengig vom Rohformat der Quelle darstellen. Je Quelle
gibt es ein Modul mit ``iter_items`` (``chatgpt``, ``opencode``, ``codex``,
``claude``); eine neue Quelle kommt durch ein weiteres Modul hinzu.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator


@dataclass(slots=True)
class ExportItem:
    """Ein gespeichertes Gespraech: Rohdatei und neutrale Ansicht (oder Lesefehler)."""

    source: str
    path: Path
    view: dict[str, Any] | None = None
    error: str | None = None

    @property
    def item_id(self) -> str:
        if self.view and self.view.get("conversation_id"):
            return str(self.view["conversation_id"])
        return self.path.stem


def _reader(module: str) -> Callable[[Path], Iterator[ExportItem]]:
    def read(raw_root: Path) -> Iterator[ExportItem]:
        from importlib import import_module
        return import_module(f"{__name__}.{module}").iter_items(raw_root)
    return read


#: Quelle -> Funktion ``(raw_root) -> Iterator[ExportItem]``.
SOURCES: dict[str, Callable[[Path], Iterator[ExportItem]]] = {
    name: _reader(name) for name in ("chatgpt", "opencode", "codex", "claude")}


def iter_items(source: str, raw_root: Path) -> Iterator[ExportItem]:
    try:
        reader = SOURCES[source]
    except KeyError:
        raise ValueError(f"Keine Exportunterstuetzung fuer Quelle {source!r}") from None
    return reader(raw_root)
