from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from chatexporter.providers.chatgpt.common.io import atomic_write_json, atomic_write_text
from chatexporter.providers.chatgpt.common.pathing import safe_component
from .index import StorageIndex
from .library import LibraryStore


def _month_bucket(value: Any) -> str:
    """Monats-Bucket (legacy: Export-Gruppierung, Altbestand)."""
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
            return f"{dt.year:04d}-{dt.month:02d}"
        if isinstance(value, str) and value:
            normalized = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            return f"{dt.year:04d}-{dt.month:02d}"
    except Exception:
        pass
    return "unknown"


def _date_bucket(value: Any) -> str:
    """Tag-Bucket ``YYYY/MM/DD`` aus create_time (ChatGPT-Quellenprofil).

    Empfehlung pro Quelle, kein globaler Zwang (siehe Provider-Vertrag,
    Abschnitt Ablage). Fallback: ``unknown``.
    """
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
            return f"{dt.year:04d}/{dt.month:02d}/{dt.day:02d}"
        if isinstance(value, str) and value:
            normalized = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            return f"{dt.year:04d}/{dt.month:02d}/{dt.day:02d}"
    except Exception:
        pass
    return "unknown"


class RawRepository:
    """Quellen-Repository: ``root`` ist die Wurzel EINER Quelle.

    Legacy/Tests: ``root`` enthaelt direkt ``conversations/`` + ``library/``.
    Produktion: ``root`` ist ``<store>/raw_storage/<quelle>/``; Index-, Runs-
    und Staging-Pfade zeigen in die Runtime und werden explizit uebergeben.
    """

    def __init__(self, root: Path, status_root: Path | None = None,
                 *, index_path: Path | None = None, runs_dir: Path | None = None,
                 staging_root: Path | None = None, source: str = "chatgpt"):
        self.root = Path(root)
        self.source = source
        self.status_root = status_root
        self.conversations_root = self.root / "conversations"
        staging_base = Path(staging_root) if staging_root is not None else self.root / ".staging"
        self.staging = staging_base / "conversations"
        self.runs_dir = Path(runs_dir) if runs_dir is not None else self.root / "runs"
        self.staging_runs = staging_base / "runs"
        self.root.mkdir(parents=True, exist_ok=True)
        self.conversations_root.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)
        # Eine gemeinsame Library-/Statusinstanz, damit Schreibzugriffe (z. B.
        # "nicht verfuegbar") und Lesezugriffe (Index/Completeness) denselben
        # Zustand sehen und nicht an getrennten Caches auseinanderlaufen.
        self.library = LibraryStore(
            self.root, status_root,
            staging_root=staging_base / "library" if staging_root is not None else None)
        self.index = StorageIndex(
            self.root, status_root, library=self.library,
            index_path=index_path, source=source,
            staging_root=staging_base).load_or_rebuild()

    def target_path(self, envelope: dict[str, Any]) -> Path:
        summary = envelope.get("remote_summary") or {}
        bucket = _date_bucket(summary.get("create_time"))
        cid = safe_component(str(envelope["conversation_id"]), label="conversation_id")
        return self.conversations_root / bucket / f"{cid}.json"

    def commit(self, envelope: dict[str, Any]) -> Path:
        target = self.target_path(envelope)
        old_entry = self.index.conversations.get(envelope["conversation_id"])
        old_path = self.root / old_entry["relative_path"] if old_entry and old_entry.get("relative_path") else None
        # Marker makes a crash between raw replace and index save detectable.
        atomic_write_text(self.index.dirty_marker, envelope["conversation_id"] + "\n", staging_dir=self.index.dirty_staging)
        atomic_write_json(target, envelope, staging_dir=self.staging)
        if old_path and old_path != target and old_path.exists():
            old_path.unlink()
        self.index.refresh_one(target, envelope)
        self.index.save()
        self.index.dirty_marker.unlink(missing_ok=True)
        return target

    def get_path(self, conversation_id: str) -> Path | None:
        entry = self.index.conversations.get(conversation_id)
        if not entry:
            return None
        p = self.root / entry.get("relative_path", "")
        return p if p.exists() else None

    def load(self, conversation_id: str) -> dict[str, Any] | None:
        path = self.get_path(conversation_id)
        return json.loads(path.read_text(encoding="utf-8")) if path else None

    def iter_envelopes(self) -> Iterator[tuple[Path, dict[str, Any]]]:
        for cid in sorted(self.index.conversations):
            path = self.get_path(cid)
            if path:
                try:
                    yield path, json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue

    def rebuild_index(self) -> StorageIndex:
        self.index = StorageIndex(
            self.root, self.status_root, library=self.library,
            index_path=self.index.path, source=self.source,
            staging_root=self.index.dirty_staging).rebuild()
        return self.index
