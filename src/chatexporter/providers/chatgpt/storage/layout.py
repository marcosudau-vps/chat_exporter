from __future__ import annotations

"""Ablage-Layout: Store-Wurzel, Quellen-Root, Runtime.

Zwei Zustaende:

- **Legacy** (flach): ``<store>/conversations/``, ``<store>/library/``,
  Index/Runs/Staging unter ``<store>/``; Status als Geschwister
  (``<store>/../status_registry/``). Wird von `migrate-layout` abgeloest,
  bleibt aber lesbar (Auto-Erkennung).
- **Neu** (Provider-Vertrag): ``<store>/<quelle>/`` mit Quelldaten,
  ``<store>/../.storage/`` mit Laeufen, Staging, Statusablage, Uebersicht.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class StoreLayout:
    store_root: Path
    source: str
    source_root: Path
    runtime_root: Path
    status_root: Path
    runs_dir: Path
    staging_root: Path
    index_path: Path
    quarantine_path: Path
    legacy: bool

    def ensure_runtime_dirs(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.staging_root.mkdir(parents=True, exist_ok=True)
        for area in ("conversations", "index", "library", "runs"):
            (self.staging_root / area).mkdir(parents=True, exist_ok=True)
        self.status_root.mkdir(parents=True, exist_ok=True)


def resolve_store_layout(storage_cfg: Any, source: str = "chatgpt") -> StoreLayout:
    """Loest das Layout auf. Namespace gewinnt; flach nur als Legacy-Fallback.

    Neu, sobald `<store>/<quelle>/` existiert (oder gar keine Conversations
    irgendwo liegen = frisch). Flach-legacy nur, wenn `conversations/` direkt
    unter `<store>/` liegt und kein Namespace-Ordner existiert.
    """
    store = Path(storage_cfg.raw_root)
    namespaced = store / source
    if (store / "conversations").is_dir() and not namespaced.is_dir():
        status = Path(storage_cfg.status_root) if storage_cfg.status_root else store.parent / "status_registry"
        return StoreLayout(
            store_root=store, source=source, source_root=store,
            runtime_root=store.parent / "runtime", status_root=status,
            runs_dir=store / "runs", staging_root=store / ".staging",
            index_path=store / "storage_index.json",
            quarantine_path=store / "quarantine.json",
            legacy=True,
        )
    runtime = Path(storage_cfg.runtime_root) if storage_cfg.runtime_root else store.parent / ".storage"
    status = Path(storage_cfg.status_root) if storage_cfg.status_root else runtime / "status_registry"
    return StoreLayout(
        store_root=store, source=source, source_root=namespaced,
        runtime_root=runtime, status_root=status,
        runs_dir=runtime / "runs", staging_root=runtime / "staging",
        index_path=status / "storage_index.json",
        quarantine_path=status / "quarantine.json",
        legacy=False,
    )
