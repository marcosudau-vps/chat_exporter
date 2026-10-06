"""Import eines OpenAI-Kontodatensatzes in den RawStorage.

Begriffswahl: "Export" bezeichnet im ChatExporter die Ausgaberichtung
(Renderer/Exportprofile). Der eingelesene Kontodatensatz heisst deshalb
durchgaengig **imported data**; im Envelope steht
``acquisition.source = "imported_data"``.

Warum importierte Daten bewusst als unvollstaendig gelten
----------------------------------------------------------
Der Kontodatensatz ist nachweislich reduziert (Forschungsakte
2026-09-22): keine Tool-Nodes, keine tool-internen Assistant-Turns, sechs
fehlende Message-Felder und rund 1,5 % fehlende sichtbare
Assistant-Antworten. Deshalb wird ``acquisition.json_complete`` auf
``False`` gesetzt. ``sync/planner.py`` plant solche Conversations dadurch
automatisch fuer den vollstaendigen API-Abruf ein -- ohne Sonderlogik.

Ohne diese Kennzeichnung wuerde der Incremental Sync die Conversation
dauerhaft ueberspringen und der reduzierte Stand waere still zum
kanonischen geworden.
"""
from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from chatexporter.providers.chatgpt.common.hashing import canonical_json_bytes, sha256_bytes
from chatexporter.providers.chatgpt.common.io import atomic_write_bytes, atomic_write_json
from chatexporter.providers.chatgpt.common.pathing import safe_component
from chatexporter.providers.chatgpt.common.time import now_iso
from chatexporter.providers.chatgpt.fetch.reference_extractor import (
    extract_file_references,
    extract_tool_references,
    is_audio_reference,
)
from chatexporter.providers.chatgpt.fetch.validator import validate_conversation_graph
from chatexporter.providers.chatgpt.storage.raw_repository import _date_bucket

IMPORT_SOURCE = "imported_data"
IMPORT_SOURCE_KIND = "openai_account_data_archive"
COMPLETENESS_CLASS = "reduced_import"

#: Belegt in der Forschungsakte 2026-09-22 (Feldmatrix + Node-Diff).
KNOWN_OMISSIONS = [
    "tool_nodes", "internal_assistant_turns",
    "message.recipient", "message.status", "message.end_turn",
    "message.weight", "message.update_time", "message.channel",
    "conversation.gizmo_id", "conversation.owner", "conversation.safe_urls",
    "conversation.blocked_urls", "conversation.moderation_results",
    "conversation.is_temporary_chat", "conversation.async_status",
    "conversation.conversation_origin",
    "textdocs", "children_order",
]

#: Muss zu storage.envelope.remote_summary_from_listing passen, damit der
#: Planner die Signatur korrekt vergleichen kann.
REMOTE_SUMMARY_KEYS = [
    "id", "title", "create_time", "update_time", "is_archived", "is_starred",
    "pinned_time", "gizmo_id", "workspace_id", "conversation_origin",
    "is_temporary_chat", "is_do_not_remember",
]

_SAFE_EXT = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


def reconstruct_children(mapping: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Ergaenzt das im Kontodatensatz fehlende ``children``-Feld.

    Die Kind-Beziehung laesst sich aus den ``parent``-Zeigern vollstaendig
    rekonstruieren; die urspruengliche Reihenfolge der Geschwister nicht --
    sie ist im Datensatz nicht enthalten. Es wird deshalb deterministisch
    nach ``message.create_time`` und dann nach Node-ID sortiert. Vermerkt
    als ``children_order`` in ``known_omissions``.
    """
    kids: dict[str, list[str]] = {}
    for nid, node in mapping.items():
        if isinstance(node, dict) and node.get("parent") is not None:
            kids.setdefault(node["parent"], []).append(nid)

    def sort_key(nid: str):
        node = mapping.get(nid) or {}
        msg = node.get("message") if isinstance(node, dict) else None
        ct = msg.get("create_time") if isinstance(msg, dict) else None
        return (0, float(ct), nid) if isinstance(ct, (int, float)) else (1, 0.0, nid)

    out: dict[str, Any] = {}
    total = 0
    for nid, node in mapping.items():
        if not isinstance(node, dict):
            out[nid] = node
            continue
        new_node = dict(node)
        children = sorted(kids.get(nid, []), key=sort_key)
        new_node["children"] = children
        total += len(children)
        out[nid] = new_node
    return out, total


@dataclass
class ImportReport:
    conversations_written: int = 0
    conversations_skipped_existing: int = 0
    files_materialized: int = 0
    files_already_present: int = 0
    files_referenced_but_absent: int = 0
    audio_files_materialized: int = 0
    children_links_reconstructed: int = 0
    graph_incomplete: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)
    referenced_absent_sample: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        data = {k: v for k, v in self.__dict__.items() if k != "referenced_absent_sample"}
        data["referenced_absent_sample"] = self.referenced_absent_sample[:20]
        return data


class ImportedDataConverter:
    """Wandelt einen OpenAI-Kontodatensatz in RawStorage-Envelopes um."""

    def __init__(self, source_dir: Path, raw_root: Path, *,
                  overwrite_existing: bool = False, materialize_files: bool = True,
                  progress: Callable[[str], None] | None = None,
                  staging_root: Path | None = None):
        self.source_dir = Path(source_dir)
        self.raw_root = Path(raw_root)
        self.overwrite_existing = overwrite_existing
        self.materialize_files = materialize_files
        self.progress = progress or (lambda _m: None)

        self.conversations_root = self.raw_root / "conversations"
        self.library_root = self.raw_root / "library" / "files"
        self.audio_root = self.raw_root / "library" / "audio"
        self.staging = Path(staging_root) if staging_root is not None else self.raw_root / ".staging"
        self.report = ImportReport()

        self._asset_names: dict[str, str] = {}
        self._library_meta: dict[str, dict[str, Any]] = {}
        self._available_files: dict[str, Path] = {}
        self._data_as_of: str | None = None

    # -- Quelldaten -------------------------------------------------------
    @staticmethod
    def _strip_dat(name: str) -> str:
        return name[:-4] if name.endswith(".dat") else name

    def load_side_metadata(self) -> None:
        names_path = self.source_dir / "conversation_asset_file_names.json"
        if names_path.is_file():
            raw = json.loads(names_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for dat_name, original in raw.items():
                    self._asset_names[self._strip_dat(str(dat_name))] = str(original)

        lib_path = self.source_dir / "library_files.json"
        if lib_path.is_file():
            raw = json.loads(lib_path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                for entry in raw:
                    if isinstance(entry, dict) and isinstance(entry.get("file_id"), str):
                        self._library_meta[entry["file_id"]] = entry

        if self.source_dir.is_dir():
            for path in self.source_dir.iterdir():
                if path.is_file() and path.name.startswith(("file_", "file-")):
                    self._available_files[self._strip_dat(path.name)] = path

        m = re.search(r"(20\d{2})[_-](\d{2})[_-](\d{2})", self.source_dir.as_posix())
        if m:
            self._data_as_of = "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))

    def iter_imported_conversations(self) -> Iterator[tuple[str, dict[str, Any]]]:
        """Liefert (Quelldateiname, Conversation) stueckweise.

        Jede ``conversations-NNN.json`` wird einzeln geladen. Die grosse
        ``chat.html`` wird bewusst NICHT gelesen -- sie enthaelt denselben
        Bestand nochmals als eine einzige Zeile und ist damit redundant.
        """
        for path in sorted(self.source_dir.glob("conversations-*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for conv in data:
                    if isinstance(conv, dict):
                        yield path.name, conv
            del data

    # -- Envelope ---------------------------------------------------------
    def build_remote_summary(self, conv: dict[str, Any]) -> dict[str, Any]:
        source = dict(conv)
        source.setdefault("id", conv.get("conversation_id"))
        return {k: source.get(k) for k in REMOTE_SUMMARY_KEYS if k in source}

    def build_envelope(self, conv: dict[str, Any], source_file: str) -> dict[str, Any]:
        cid = conv.get("conversation_id") or conv.get("id")
        raw = dict(conv)
        children_count = 0
        if isinstance(raw.get("mapping"), dict):
            raw["mapping"], children_count = reconstruct_children(raw["mapping"])
        self.report.children_links_reconstructed += children_count

        validation = validate_conversation_graph(raw)
        if not validation.complete:
            self.report.graph_incomplete += 1

        file_refs = extract_file_references(raw)
        return {
            "storage_schema_version": 1,
            "provider": "chatgpt",
            "conversation_id": cid,
            "remote_summary": self.build_remote_summary(conv),
            "acquisition": {
                "fetched_at": now_iso(),
                # Beides bewusst false: der Datensatz ist reduziert, und die
                # Dateien sind hoechstens teilweise enthalten.
                "complete": False,
                "json_complete": False,
                "files_complete": False,
                "source": IMPORT_SOURCE,
                "source_endpoint": None,
                "imported_data": {
                    "imported_at": now_iso(),
                    "source_kind": IMPORT_SOURCE_KIND,
                    "source_file": source_file,
                    "source_dir": self.source_dir.as_posix(),
                    "data_as_of": self._data_as_of,
                    "completeness_class": COMPLETENESS_CLASS,
                    "known_omissions": list(KNOWN_OMISSIONS),
                    "children_reconstructed": True,
                    "children_links": children_count,
                },
                "current_node_resolved": validation.current_node_resolved,
                "dangling_parent_count": validation.dangling_parent_count,
                "root_count": validation.root_count,
                "node_count": validation.node_count,
                "warnings": validation.warnings,
                "supplemental_errors": [],
            },
            "raw": raw,
            "textdocs": [],
            "file_references": file_refs,
            "tool_references": extract_tool_references(raw),
            "integrity": {"raw_payload_sha256": sha256_bytes(canonical_json_bytes(raw))},
        }

    def target_path(self, envelope: dict[str, Any]) -> Path:
        summary = envelope.get("remote_summary") or {}
        bucket = _date_bucket(summary.get("create_time"))
        cid = safe_component(str(envelope["conversation_id"]), label="conversation_id")
        return self.conversations_root / bucket / ("%s.json" % cid)

    # -- Dateien ----------------------------------------------------------
    def _extension_for(self, file_id: str, ref: dict[str, Any]) -> str:
        fmt = ref.get("format")
        if isinstance(fmt, str) and fmt:
            candidate = fmt if fmt.startswith(".") else "." + fmt
            if _SAFE_EXT.match(candidate):
                return candidate.lower()
        meta = self._library_meta.get(file_id) or {}
        ext = meta.get("file_extension")
        if isinstance(ext, str):
            ext = ext if ext.startswith(".") else "." + ext
            if _SAFE_EXT.match(ext):
                return ext.lower()
        for name in (self._asset_names.get(file_id), meta.get("file_name"), ref.get("name")):
            if isinstance(name, str):
                suffix = Path(name).suffix
                if _SAFE_EXT.match(suffix):
                    return suffix.lower()
        mime = ref.get("mime_type") or meta.get("mime_type")
        guessed = mimetypes.guess_extension(str(mime)) if mime else None
        return guessed if guessed and _SAFE_EXT.match(guessed) else ".bin"

    def materialize_file(self, ref: dict[str, Any]) -> str:
        fid = ref.get("id")
        if not isinstance(fid, str):
            return "ABSENT"
        source = self._available_files.get(fid)
        if source is None:
            return "ABSENT"

        is_audio = is_audio_reference(ref)
        base = self.audio_root if is_audio else self.library_root
        target_dir = base / safe_component(fid, label="file_id")
        if (target_dir / "metadata.json").exists() and any(target_dir.glob("content.*")):
            return "ALREADY_PRESENT"

        content = source.read_bytes()
        content_path = target_dir / ("content%s" % self._extension_for(fid, ref))
        atomic_write_bytes(content_path, content, staging_dir=self.staging / "library")

        lib_meta = self._library_meta.get(fid)
        original_name = self._asset_names.get(fid) or (
            lib_meta.get("file_name") if isinstance(lib_meta, dict) else None)
        atomic_write_json(target_dir / "metadata.json", {
            "schema_version": 1,
            "file_id": fid,
            "materialized_at": now_iso(),
            "content_file": content_path.name,
            "content_sha256": sha256_bytes(content),
            "size": len(content),
            "kind": ref.get("kind"),
            "bucket": "audio" if is_audio else "files",
            "source": IMPORT_SOURCE,
            "imported_data": {
                "source_kind": IMPORT_SOURCE_KIND,
                "source_file_name": source.name,
                "original_file_name": original_name,
                "data_as_of": self._data_as_of,
            },
            "source_metadata": lib_meta,
            "download_metadata": {
                "file_name": original_name,
                "file_size_bytes": len(content),
                "download_url_persisted": False,
            },
        }, staging_dir=self.staging / "library")
        return "AUDIO" if is_audio else "MATERIALIZED"

    # -- Ablauf -----------------------------------------------------------
    def run(self, *, limit: int | None = None,
            only_ids: Iterable[str] | None = None) -> ImportReport:
        for d in (self.conversations_root, self.library_root, self.audio_root,
                  self.staging / "conversations", self.staging / "library"):
            d.mkdir(parents=True, exist_ok=True)

        self.load_side_metadata()
        self.progress("Datensatz: %d Dateien, %d Library-Eintraege, %d Namenszuordnungen"
                      % (len(self._available_files), len(self._library_meta), len(self._asset_names)))

        wanted = {str(i).strip() for i in only_ids if str(i).strip()} if only_ids else None
        processed = 0
        absent_ids: set[str] = set()

        for source_file, conv in self.iter_imported_conversations():
            cid = conv.get("conversation_id") or conv.get("id")
            if not isinstance(cid, str):
                continue
            if wanted is not None and cid not in wanted:
                continue
            if limit is not None and processed >= limit:
                break
            try:
                envelope = self.build_envelope(conv, source_file)
                target = self.target_path(envelope)
                if target.exists() and not self.overwrite_existing:
                    self.report.conversations_skipped_existing += 1
                    processed += 1
                    continue

                if self.materialize_files:
                    for ref in envelope.get("file_references") or []:
                        state = self.materialize_file(ref)
                        if state == "MATERIALIZED":
                            self.report.files_materialized += 1
                        elif state == "AUDIO":
                            self.report.files_materialized += 1
                            self.report.audio_files_materialized += 1
                        elif state == "ALREADY_PRESENT":
                            self.report.files_already_present += 1
                        else:
                            self.report.files_referenced_but_absent += 1
                            fid = ref.get("id")
                            if isinstance(fid, str) and fid not in absent_ids:
                                absent_ids.add(fid)
                                self.report.referenced_absent_sample.append(fid)

                atomic_write_json(target, envelope, staging_dir=self.staging / "conversations")
                self.report.conversations_written += 1
                processed += 1
                self.progress("[%d] %s -> %s (%d Nodes, %d File-Refs)"
                              % (processed, cid, target.relative_to(self.raw_root).as_posix(),
                                 envelope["acquisition"]["node_count"],
                                 len(envelope.get("file_references") or [])))
            except Exception as exc:
                self.report.errors.append({
                    "conversation_id": cid, "source_file": source_file,
                    "error": "%s: %s" % (type(exc).__name__, exc),
                })
                processed += 1

        # Index-Rebuild erzwingen: StorageIndex.load_or_rebuild() prueft genau
        # diese Markerdatei. So muss die Indexlogik nirgends dupliziert werden.
        marker = self.staging / "index_dirty"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("imported_data\n", encoding="utf-8")
        return self.report
