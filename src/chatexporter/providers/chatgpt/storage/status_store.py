from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chatexporter.providers.chatgpt.common.io import atomic_write_json
from chatexporter.providers.chatgpt.common.time import now_iso

#: Der Rohdaten-Speicher enthaelt nur, was tatsaechlich vorhanden ist. Fehler-,
#: Abwesenheits- und Zuordnungsinformationen liegen bewusst AUSSERHALB in einer
#: eigenen Statusablage. Damit bleibt der Rohdatenbestand ein reiner, portabler
#: Datenbestand und weist nicht staendig auf Dinge hin, die nicht da sind.
FILE_STATUS_SCHEMA_VERSION = 1
FILE_INDEX_SCHEMA_VERSION = 1


def resolve_status_root(raw_root: Path, configured: Path | None = None) -> Path:
    """Statusablage neben (nicht innerhalb) dem Rohdaten-Speicher."""
    if configured is not None:
        return Path(configured)
    return Path(raw_root).parent / "status_registry"


def resolve_runtime_root(raw_root: Path, configured: Path | None = None) -> Path:
    """Betriebsablage neben dem Rohdaten-Speicher (keine Quelldaten).

    ``raw_root`` ist die Store-Wurzel (``.../raw_storage``); die Runtime liegt
    als ``.../runtime`` daneben. Explizite Konfiguration gewinnt.
    """
    if configured is not None:
        return Path(configured)
    return Path(raw_root).parent / ".storage"


class FileStatusStore:
    """Haelt den Abrufstatus je Datei (z. B. UNAVAILABLE/HTTP 404).

    Bewusst kein Bestandteil des Rohdaten-Speichers: die Datei selbst existiert
    dort schlicht nicht, wenn sie nicht abrufbar war. Der Grund wird hier
    festgehalten und ist jederzeit verwerfbar/rebuildbar -- ein Verlust dieser
    Ablage ist kein Datenverlust.
    """

    def __init__(self, status_root: Path):
        self.root = Path(status_root)
        self.path = self.root / "file_status.json"
        self.staging = self.root / ".staging"
        self._data: dict[str, Any] | None = None

    def _load(self) -> None:
        if self._data is not None:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data.get("files"), dict):
                raise ValueError("file_status schema mismatch")
            self._data = data
        except Exception:
            self._data = {
                "schema_version": FILE_STATUS_SCHEMA_VERSION,
                "generated_at": None,
                "files": {},
            }

    @property
    def files(self) -> dict[str, Any]:
        self._load()
        return self._data["files"]

    def get(self, file_id: str) -> dict[str, Any] | None:
        record = self.files.get(file_id)
        return record if isinstance(record, dict) else None

    def state(self, file_id: str) -> str | None:
        record = self.get(file_id)
        state = record.get("state") if record else None
        return state if isinstance(state, str) else None

    def is_unavailable(self, file_id: str) -> bool:
        return self.state(file_id) == "UNAVAILABLE"

    def mark_unavailable(self, file_id: str, *, status: int | None,
                         detail: str | None, ref: dict[str, Any] | None = None,
                         conversation_id: str | None = None,
                         save: bool = True) -> None:
        self._load()
        observed = now_iso()
        record = self.get(file_id) or {}
        record.setdefault("first_seen", observed)
        record["file_id"] = file_id
        record["state"] = "UNAVAILABLE"
        record["http_status"] = status
        record["detail"] = detail
        record["last_seen"] = observed
        record["attempts"] = int(record.get("attempts", 0)) + 1
        if ref is not None:
            if record.get("kind") is None:
                record["kind"] = ref.get("kind")
            if record.get("name") is None:
                record["name"] = ref.get("name")
        self._merge_reference(record, conversation_id,
                              ref.get("message_id") if ref else None,
                              ref.get("node_id") if ref else None)
        self.files[file_id] = record
        if save:
            self.save()

    def _merge_reference(self, record: dict[str, Any], conversation_id: str | None,
                         message_id: Any, node_id: Any) -> None:
        if not conversation_id:
            return
        refs = record.setdefault("source_refs", [])
        row = {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "node_id": node_id,
        }
        if row not in refs:
            refs.append(row)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.files.values():
            state = record.get("state") if isinstance(record, dict) else None
            key = state if isinstance(state, str) else "UNKNOWN"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def save(self) -> None:
        self._load()
        self._data["generated_at"] = now_iso()
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, self._data, staging_dir=self.staging)


class FileIndex:
    """Rueckwaertsindex: Datei -> Conversations/Messages/Notes.

    Die Vorwaertsrichtung (Conversation -> Dateien) steht im Envelope, die
    Rueckwaertsrichtung hier. Beides zusammen macht die Zuordnung beidseitig
    aufloesbar. Rebuildbar aus den Envelopes, daher außerhalb des Rohdaten-
    Speichers.
    """

    def __init__(self, status_root: Path):
        self.root = Path(status_root)
        self.path = self.root / "file_index.json"
        self.staging = self.root / ".staging"
        self._data: dict[str, Any] | None = None

    def _load(self) -> None:
        if self._data is not None:
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data.get("files"), dict):
                raise ValueError("file_index schema mismatch")
            self._data = data
        except Exception:
            self._data = {
                "schema_version": FILE_INDEX_SCHEMA_VERSION,
                "generated_at": None,
                "files": {},
            }

    @property
    def files(self) -> dict[str, Any]:
        self._load()
        return self._data["files"]

    def references(self, file_id: str) -> list[dict[str, Any]]:
        record = self.files.get(file_id)
        refs = record.get("references") if isinstance(record, dict) else None
        return refs if isinstance(refs, list) else []

    def add(self, file_id: str, *, conversation_id: str | None,
            message_id: Any = None, node_id: Any = None,
            save: bool = True) -> dict[str, Any]:
        self._load()
        record = self.files.get(file_id)
        if not isinstance(record, dict):
            record = {"file_id": file_id, "references": []}
        refs = record.setdefault("references", [])
        row = {
            "conversation_id": conversation_id,
            "message_id": message_id,
            "node_id": node_id,
        }
        if conversation_id and row not in refs:
            refs.append(row)
        self.files[file_id] = record
        if save:
            self.save()
        return row

    def save(self) -> None:
        self._load()
        self._data["generated_at"] = now_iso()
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, self._data, staging_dir=self.staging)


def refresh_file_index_records(existing: Any, new_refs: dict[str, list[dict[str, Any]]],
                               source: str) -> dict[str, Any]:
    """Eigene Records ersetzen, fremde Quellen bleiben erhalten.

    Records ohne `sources`-Feld stammen aus der Zeit vor der Konsolidierung
    und zaehlen als eigene. Geteilte Datei-IDs ueber Quellen hinweg sind ein
    dokumentierter Grenzfall (praktisch provider-namespaced).
    """
    result: dict[str, Any] = {}
    for fid, rec in (existing or {}).items():
        if not isinstance(rec, dict):
            continue
        sources = rec.get("sources") or [source]
        if set(sources) <= {source} and fid not in (new_refs or {}):
            continue
        result[fid] = {"file_id": fid,
                       "references": list(rec.get("references") or []),
                       "sources": sorted(set(sources))}
    for fid, refs in (new_refs or {}).items():
        old_sources = (result.get(fid, {}).get("sources")) or [source]
        result[fid] = {"file_id": fid, "references": list(refs or []),
                       "sources": sorted(set(old_sources) | {source})}
    return result


def rebuild_file_index(repository: Any, status_root: Path, *,
                       source: str = "chatgpt") -> FileIndex:
    """Baut den Rueckwaertsindex aus allen Conversation-Envelopes neu.

    Records fremder Quellen bleiben erhalten (siehe
    `refresh_file_index_records`).
    """
    index = FileIndex(status_root)
    index._load()
    collected: dict[str, list[dict[str, Any]]] = {}
    for _path, envelope in repository.iter_envelopes():
        conversation_id = envelope.get("conversation_id")
        refs = envelope.get("file_references")
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            file_id = ref.get("id")
            if not isinstance(file_id, str):
                continue
            row = {
                "conversation_id": conversation_id,
                "message_id": ref.get("message_id"),
                "node_id": ref.get("node_id"),
            }
            bucket = collected.setdefault(file_id, [])
            if row not in bucket:
                bucket.append(row)
    index._data["files"] = refresh_file_index_records(
        index._data.get("files"), collected, source)
    index.save()
    return index
