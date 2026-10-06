from __future__ import annotations

import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from chatexporter.providers.chatgpt.api.files import FileApi
from chatexporter.providers.chatgpt.common.io import atomic_write_bytes, atomic_write_json
from chatexporter.providers.chatgpt.common.redaction import redact_secrets
from chatexporter.providers.chatgpt.common.hashing import sha256_bytes
from chatexporter.providers.chatgpt.common.time import now_iso
from chatexporter.providers.chatgpt.common.pathing import safe_component
from chatexporter.providers.chatgpt.fetch.reference_extractor import is_audio_reference
from .status_store import FileIndex, FileStatusStore, resolve_status_root

_SAFE_EXT = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


def _extension(metadata: dict[str, Any], ref: dict[str, Any]) -> str:
    # Sprachaufnahmen tragen ihr Format am Pointer ("format": "wav") und haben
    # oft weder Dateiname noch MIME-Typ -- sonst landeten sie alle als ".bin".
    fmt = ref.get("format")
    if isinstance(fmt, str) and fmt:
        candidate = fmt if fmt.startswith(".") else "." + fmt
        if _SAFE_EXT.match(candidate):
            return candidate.lower()
    ext = metadata.get("file_extension")
    if isinstance(ext, str):
        ext = ext if ext.startswith(".") else "." + ext
        if _SAFE_EXT.match(ext):
            return ext.lower()
    name = metadata.get("name") or ref.get("name")
    if isinstance(name, str):
        suffix = Path(name).suffix
        if _SAFE_EXT.match(suffix):
            return suffix.lower()
    mime = metadata.get("mime_type") or ref.get("mime_type")
    guessed = mimetypes.guess_extension(str(mime)) if mime else None
    return guessed if guessed and _SAFE_EXT.match(guessed) else ".bin"


def _local_block(conversation_id: str | None, ref: dict[str, Any]) -> dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "message_id": ref.get("message_id"),
        "node_id": ref.get("node_id"),
        "references": [
            {
                "conversation_id": conversation_id,
                "message_id": ref.get("message_id"),
                "node_id": ref.get("node_id"),
            }
        ],
    }


class LibraryStore:
    """Ablage der Dateianhaenge.

    Zwei Bereiche nebeneinander:

        library/files/<file_id>/   normale Anhaenge, Bilder, Dokumente
        library/audio/<file_id>/   Sprachaufnahmen aus dem Voice-Mode

    Die Zuordnung ergibt sich aus ``kind`` der Referenz (siehe
    ``fetch/reference_extractor.is_audio_reference``). Fuer Lesezugriffe
    werden beide Bereiche geprueft, damit ein bereits abgelegter Bestand
    auch dann gefunden wird, wenn sich die Einordnung spaeter aendert.

    Der Rohdaten-Speicher enthaelt nur die tatsaechlich vorhandenen Dateien.
    Abwesenheit/Fehler (z. B. HTTP 404) liegen in der separaten Statusablage
    (``storage/status_store.py``) -- nicht mehr als ``unavailable.json`` in der
    Library. Jede Datei traegt in ``metadata.json`` unter ``_local`` den Bezug
    zu ihrer Conversation/Message.
    """

    def __init__(self, raw_root: Path, status_root: Path | None = None,
                 staging_root: Path | None = None):
        self.root = raw_root / "library" / "files"
        self.audio_root = raw_root / "library" / "audio"
        self.staging = Path(staging_root) if staging_root is not None else raw_root / ".staging" / "library"
        self.status = FileStatusStore(resolve_status_root(raw_root, status_root))
        self.file_index = FileIndex(self.status.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.audio_root.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)

    def bucket_root(self, ref: dict[str, Any] | None) -> Path:
        return self.audio_root if ref is not None and is_audio_reference(ref) else self.root

    def file_dir(self, file_id: str, ref: dict[str, Any] | None = None) -> Path:
        return self.bucket_root(ref) / safe_component(file_id, label="file_id")

    def _existing_dir(self, file_id: str) -> Path | None:
        """Findet einen bereits abgelegten Eintrag in beiden Bereichen."""
        component = safe_component(file_id, label="file_id")
        for base in (self.root, self.audio_root):
            candidate = base / component
            if candidate.is_dir():
                return candidate
        return None

    def metadata_path(self, file_id: str, ref: dict[str, Any] | None = None) -> Path:
        existing = self._existing_dir(file_id)
        if existing is not None:
            return existing / "metadata.json"
        return self.file_dir(file_id, ref) / "metadata.json"

    def content_paths(self, file_id: str) -> list[Path]:
        d = self._existing_dir(file_id)
        return sorted(p for p in d.glob("content.*") if p.is_file()) if d else []

    def is_materialized(self, file_id: str) -> bool:
        paths = self.content_paths(file_id)
        if not paths or not self.metadata_path(file_id).exists():
            return False
        meta = None
        try:
            meta = json.loads(self.metadata_path(file_id).read_text(encoding="utf-8"))
        except Exception:
            pass
        expected = None
        if isinstance(meta, dict):
            for candidate in (meta.get("size"), meta.get("file_size_bytes")):
                if isinstance(candidate, int) and candidate >= 0:
                    expected = candidate
                    break
        return any(expected is None or p.stat().st_size == expected for p in paths)

    # -- Status (ausserhalb des Rohdaten-Speichers) ----------------------
    def _legacy_unavailable_path(self, file_id: str,
                                 ref: dict[str, Any] | None = None) -> Path:
        """Pfad des frueheren Markers im Rohdaten-Speicher (nur noch lesend).

        Wird von der Migration entfernt. Neue Eintraege entstehen dort nicht
        mehr -- Abwesenheit gehoert nicht in den Rohdatenbestand.
        """
        existing = self._existing_dir(file_id)
        base = existing if existing is not None else self.file_dir(file_id, ref)
        return base / "unavailable.json"

    def is_unavailable(self, file_id: str) -> bool:
        if self.status.is_unavailable(file_id):
            return True
        # Rueckwaertskompatibel, bis die Migration gelaufen ist.
        return self._legacy_unavailable_path(file_id).exists()

    def mark_unavailable(self, ref: dict[str, Any], *, status: int | None,
                         detail: str | None, conversation_id: str | None = None) -> None:
        """Haelt fest, dass eine Datei serverseitig endgueltig nicht mehr
        existiert (HTTP 404).

        Das ist keine Stoerung, sondern eine definitive Antwort: alte
        Anhaenge laufen serverseitig ab. Ohne diese Markierung wuerde die
        zugehoerige Conversation dauerhaft als dateiunvollstaendig gelten und
        bei JEDEM Lauf erneut eingeplant werden -- ein Dauerverbrauch des
        knappen Request-Budgets ohne jede Aussicht auf Erfolg.

        Der Eintrag landet in der Statusablage, nicht im Rohdaten-Speicher.
        """
        fid = ref.get("id")
        if not isinstance(fid, str):
            return
        self.status.mark_unavailable(fid, status=status, detail=detail, ref=ref,
                                      conversation_id=conversation_id)
        # Etwaigen Altmarker im Rohdaten-Speicher entfernen.
        self._legacy_unavailable_path(fid, ref).unlink(missing_ok=True)

    def register_reference(self, ref: dict[str, Any], *,
                           conversation_id: str | None = None,
                           update_index: bool = True) -> None:
        """Haelt fest, dass eine Datei in einer Conversation/Message
        referenziert wird -- auch ohne (erneuten) Download.

        Fuellt den Rueckwaertsindex (Datei -> Conversations/Messages) und
        ergaenzt die ``_local``-Felder einer bereits materialisierten Datei.
        ``update_index=False`` beim Massen-Backfill, wenn der Index bereits
        gesammelt neu gebaut wurde.
        """
        fid = ref.get("id")
        if not isinstance(fid, str) or not fid.startswith(("file_", "file-")):
            return
        if update_index:
            self.file_index.add(fid, conversation_id=conversation_id,
                                message_id=ref.get("message_id"), node_id=ref.get("node_id"))
        path = self.metadata_path(fid, ref)
        if not path.exists():
            return
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(meta, dict):
            return
        local = meta.get("_local")
        if not isinstance(local, dict):
            local = {}
        if not local.get("conversation_id"):
            local["conversation_id"] = conversation_id
        if not local.get("message_id"):
            local["message_id"] = ref.get("message_id")
        if not local.get("node_id"):
            local["node_id"] = ref.get("node_id")
        refs = local.setdefault("references", [])
        row = {
            "conversation_id": conversation_id,
            "message_id": ref.get("message_id"),
            "node_id": ref.get("node_id"),
        }
        # Vorhandenen Eintrag zusammenfuehren statt doppelt anzulegen: aeltere
        # Eintraege kannten den Message-Bezug noch nicht.
        for existing in refs:
            if (existing.get("conversation_id") == conversation_id
                    and existing.get("node_id") == ref.get("node_id")):
                if not existing.get("message_id"):
                    existing["message_id"] = ref.get("message_id")
                break
        else:
            if conversation_id:
                refs.append(row)
        meta["_local"] = local
        atomic_write_json(path, meta, staging_dir=self.staging)

    def derived_state(self, ref: dict[str, Any]) -> str:
        fid = ref.get("id")
        # Beide Namensraeume sind real: "file_" (modern) und "file-" (aelter).
        # pre-4 kannte nur "file_" und stufte den Rest als UNSUPPORTED ein --
        # diese Dateien wurden nie geladen und nie gemeldet. "file-inline-..."
        # ist dagegen ein Pseudo-Eintrag ohne echten Dateidownload.
        if not isinstance(fid, str) or not fid.startswith(("file_", "file-")) or             fid.startswith("file-inline-"):
            return "UNSUPPORTED"
        if self.is_materialized(fid):
            return "MATERIALIZED"
        return "UNAVAILABLE" if self.is_unavailable(fid) else "PENDING"

    def materialize(self, ref: dict[str, Any], api: FileApi, *,
                    conversation_id: str | None = None,
                    gizmo_id: str | None = None) -> dict[str, Any]:
        fid = ref.get("id")
        if not isinstance(fid, str) or not fid.startswith(("file_", "file-")) or                 fid.startswith("file-inline-"):
            return {"id": fid, "state": "UNSUPPORTED", "error": "unsupported_or_missing_file_id"}
        if self.is_materialized(fid):
            self.register_reference(ref, conversation_id=conversation_id)
            return {"id": fid, "state": "MATERIALIZED", "cached": True}
        metadata = redact_secrets(api.metadata(fid))
        ticket = api.download_ticket(fid, gizmo_id=gizmo_id)
        signed_url = ticket["download_url"]
        content = api.download_bytes(signed_url)
        expected_size = ticket.get("file_size_bytes")
        if isinstance(expected_size, int) and expected_size >= 0 and len(content) != expected_size:
            raise IOError(f"Downloaded byte count mismatch for {fid}: got {len(content)}, expected {expected_size}")
        target_dir = self.file_dir(fid, ref)
        target_dir.mkdir(parents=True, exist_ok=True)
        ext = _extension(metadata, ref)
        content_path = target_dir / f"content{ext}"
        atomic_write_bytes(content_path, content, staging_dir=self.staging)
        meta_doc = {
            "schema_version": 1,
            "file_id": fid,
            "materialized_at": now_iso(),
            "content_file": content_path.name,
            "content_sha256": sha256_bytes(content),
            "size": len(content),
            "kind": ref.get("kind"),
            "bucket": "audio" if is_audio_reference(ref) else "files",
            "_local": _local_block(conversation_id, ref),
            "source_metadata": metadata,
            "download_metadata": {
                "file_name": ticket.get("file_name"),
                "file_size_bytes": ticket.get("file_size_bytes"),
                "download_url_persisted": False,
                "gizmo_id": gizmo_id,
            },
        }
        atomic_write_json(target_dir / "metadata.json", meta_doc, staging_dir=self.staging)
        self.register_reference(ref, conversation_id=conversation_id)
        return {"id": fid, "state": "MATERIALIZED", "cached": False, "bytes": len(content), "path": str(content_path)}
