from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from chatexporter.providers.chatgpt.common.hashing import canonical_json_bytes, sha256_bytes, sha256_file
from chatexporter.providers.chatgpt.common.io import atomic_write_json
from chatexporter.providers.chatgpt.common.time import now_iso
from .library import LibraryStore
from .status_store import FileIndex

INDEX_SCHEMA_VERSION = 1

#: Volle Pflichtfelder fuer ChatGPT-Eintraege (die Planung liest sie).
REQUIRED_ENTRY_FIELDS = (
    "json_complete",
    "files_complete",
    "acquisition_source",
    "file_unavailable_count",
    "source",
    # Detail-update_time beim Abruf: das Listing fuehrt update_time teils
    # verzoegert (575/3098 belegt, 2026-10-01) -- ohne dieses Feld wuerde ein
    # nachziehendes Listing als inhaltliche Aenderung missverstanden. Fehlt es
    # (aelterer Index), baut sich der Index selbst neu.
    "raw_update_time",
)

#: Mindestfelder jedes Eintrags, egal welche Quelle (Merge-Vertrag).
#: Die ID-Regel dazu steht in `validate_fragment`.
GENERIC_ENTRY_FIELDS = (
    "source",
    "kind",
    "relative_path",
)

FRAGMENT_SCHEMA_VERSION = 1


def _coverage(indexed: int, candidates: int) -> float:
    if candidates <= 0:
        return 100.0
    return round(100.0 * indexed / candidates, 1)


def _entry_from_envelope(path: Path, root: Path, envelope: dict[str, Any],
                         library: LibraryStore, source: str = "chatgpt") -> dict[str, Any]:
    summary = envelope.get("remote_summary") if isinstance(envelope.get("remote_summary"), dict) else {}
    raw = envelope.get("raw") if isinstance(envelope.get("raw"), dict) else {}
    acq = envelope.get("acquisition") if isinstance(envelope.get("acquisition"), dict) else {}
    refs = envelope.get("file_references") if isinstance(envelope.get("file_references"), list) else []
    expected_raw_hash = (envelope.get("integrity") or {}).get("raw_payload_sha256") if isinstance(envelope.get("integrity"), dict) else None
    actual_raw_hash = sha256_bytes(canonical_json_bytes(raw))
    states = [library.derived_state(ref) for ref in refs if isinstance(ref, dict)]
    materialized = sum(1 for st in states if st == "MATERIALIZED")
    unavailable = sum(1 for st in states if st == "UNAVAILABLE")
    # Rueckwaertskompatibel: aeltere Envelopes kennen json_/files_complete nicht.
    # json_complete faellt dann auf das alte "complete" zurueck; files_complete
    # wird aus dem tatsaechlichen Library-Zustand abgeleitet.
    json_complete = acq.get("json_complete")
    if json_complete is None:
        json_complete = bool(acq.get("complete"))
    files_complete = acq.get("files_complete")
    if files_complete is None:
        files_complete = (not refs) or ((materialized + unavailable) == len(refs))
    return {
        "conversation_id": envelope.get("conversation_id"),
        "source": source,
        "kind": "conversation",
        "relative_path": path.relative_to(root).as_posix(),
        "title": summary.get("title"),
        "create_time": summary.get("create_time"),
        "remote_updated_at": summary.get("update_time"),
        # update_time der Detailantwort = Stand des gespeicherten Inhalts.
        "raw_update_time": raw.get("update_time"),
        "is_archived": summary.get("is_archived"),
        "is_starred": summary.get("is_starred"),
        "pinned_time": summary.get("pinned_time"),
        "current_node": raw.get("current_node"),
        "message_node_count": len(raw.get("mapping", {})) if isinstance(raw.get("mapping"), dict) else 0,
        "fetch_complete": bool(json_complete) and bool(files_complete),
        "json_complete": bool(json_complete),
        "files_complete": bool(files_complete),
        "acquisition_source": acq.get("source") or "api",
        "raw_integrity_ok": bool(expected_raw_hash) and expected_raw_hash == actual_raw_hash,
        "file_reference_count": len(refs),
        "file_materialized_count": materialized,
        # Serverseitig endgueltig weg (HTTP 404). Bewusst eigenes Feld, damit
        # nicht verborgen bleibt, warum eine Conversation als dateivollstaendig
        # gilt, obwohl nicht alle Dateien vorliegen.
        "file_unavailable_count": unavailable,
        "file_sha256": sha256_file(path),
    }


def _scan_source(root: Path, source: str, library: LibraryStore
                 ) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]], int, list[str]]:
    """Scannt EINE Quelle. Liefert (Eintraege, File-Refs, Kandidaten, Fehlerdateien).

    Datensatz-Fehler (unlesbar, falsches Schema, fehlende ID) werden
    uebersprungen und als Dateipfade zurueckgegeben -- sie senken die Coverage,
    verhindern aber keinen Rebuild (siehe Provider-Vertrag).
    """
    entries: dict[str, dict[str, Any]] = {}
    file_refs: dict[str, list[dict[str, Any]]] = {}
    candidates = 0
    failed: list[str] = []
    conv_root = root / "conversations"
    if conv_root.exists():
        for path in sorted(conv_root.rglob("*.json")):
            candidates += 1
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
                if envelope.get("storage_schema_version") != 1:
                    raise ValueError("storage_schema_version != 1")
                cid = envelope.get("conversation_id")
                if not isinstance(cid, str) or not cid:
                    raise ValueError("missing conversation_id")
                entries[cid] = _entry_from_envelope(path, root, envelope, library, source)
                refs = envelope.get("file_references")
                if isinstance(refs, list):
                    for ref in refs:
                        if not isinstance(ref, dict):
                            continue
                        file_id = ref.get("id")
                        if not isinstance(file_id, str):
                            continue
                        row = {"conversation_id": cid, "message_id": ref.get("message_id"),
                               "node_id": ref.get("node_id")}
                        bucket = file_refs.setdefault(file_id, [])
                        if row not in bucket:
                            bucket.append(row)
            except Exception:
                failed.append(path.relative_to(root).as_posix())
                continue
    return entries, file_refs, candidates, failed


#: Lokal verlorene Conversations (Datei fehlt, Index verwies noch darauf), je Quelle. Eigene Datei
#: in der Statusablage, weil der Gesamtindex beim Zusammenfuehren aller Quellen neu geschrieben wird.
LOST_FILE = "lost_conversations.json"


class StorageIndex:
    def __init__(self, root: Path, status_root: Path | None = None,
                 library: LibraryStore | None = None, *,
                 index_path: Path | None = None, source: str = "chatgpt",
                 staging_root: Path | None = None):
        self.root = Path(root)
        self.source = source
        self.library = library if library is not None else LibraryStore(root, status_root)
        self.status_root = self.library.status.root
        self.path = Path(index_path) if index_path is not None else self.root / "storage_index.json"
        staging_base = Path(staging_root) if staging_root is not None else self.root / ".staging"
        self.dirty_marker = staging_base / "index_dirty"
        self.dirty_staging = staging_base
        self.data: dict[str, Any] = {
            "schema_version": INDEX_SCHEMA_VERSION, "generated_at": None,
            "coverage": {"sources": {}, "percent": 100.0},
            "conversations": {},
        }

    @property
    def conversations(self) -> dict[str, dict[str, Any]]:
        """Nur Eintraege der EIGENEN Quelle (Planung/Exporte bleiben stabil)."""
        return self.entries_for(self.source)

    def entries_for(self, source: str) -> dict[str, dict[str, Any]]:
        convs = self.data.get("conversations")
        if not isinstance(convs, dict):
            return {}
        return {cid: e for cid, e in convs.items()
                if isinstance(e, dict) and e.get("source", "chatgpt") == source}

    def _all_entries(self) -> dict[str, dict[str, Any]]:
        convs = self.data.get("conversations")
        return convs if isinstance(convs, dict) else {}

    @property
    def coverage(self) -> dict[str, Any]:
        cov = self.data.get("coverage")
        return cov if isinstance(cov, dict) else {}

    def load_or_rebuild(self) -> "StorageIndex":
        if self.dirty_marker.exists():
            return self.rebuild()
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if loaded.get("schema_version") != INDEX_SCHEMA_VERSION or not isinstance(loaded.get("conversations"), dict):
                raise ValueError("index schema mismatch")
            self.data = loaded
            # Missing paths make the index stale; rebuild rather than trust it.
            # Geprueft werden nur Eintraege der eigenen Quelle: fremde Pfade
            # sind relativ zu IHRER Wurzel und hier nicht aufloesbar.
            own = {cid: e for cid, e in self._all_entries().items()
                   if e.get("source", "chatgpt") == self.source}
            missing = sorted(cid for cid, e in own.items()
                             if not (self.root / e.get("relative_path", "")).exists())
            if missing:
                # Lokal geloescht (z. B. von Hand): merken, damit der naechste Abruf sie neu laedt,
                # auch wenn er abbricht, bevor sie wieder da sind (``lost_entries``).
                self._remember_lost(missing)
                raise ValueError("index references missing files")
            # Ein Index aus einer aelteren Version kennt die neueren Felder
            # nicht. Ihn weiterzuverwenden waere stiller Datenverlust in der
            # Planung, deshalb lieber einmal neu bauen. ChatGPT-Eintraege
            # brauchen den vollen Feldsatz, fremde nur den generischen.
            for entry in self._all_entries().values():
                if not isinstance(entry, dict):
                    raise ValueError("index entry not an object")
                required = (REQUIRED_ENTRY_FIELDS
                            if entry.get("source", "chatgpt") == "chatgpt"
                            else GENERIC_ENTRY_FIELDS)
                if any(field not in entry for field in required):
                    raise ValueError("index entries predate current field set")
            return self
        except Exception:
            return self.rebuild()

    def build_fragment(self) -> dict[str, Any]:
        """Deterministischer Index-Anteil dieser Quelle (fuer den Merge durch den Raw Session Updater)."""
        entries, file_refs, candidates, failed = _scan_source(self.root, self.source, self.library)
        indexed = len(entries)
        return {
            "fragment_schema_version": FRAGMENT_SCHEMA_VERSION,
            "source": self.source,
            "generated_at": now_iso(),
            "candidates": candidates,
            "indexed": indexed,
            "coverage_percent": _coverage(indexed, candidates),
            "failed_files": sorted(failed),
            "entries": entries,
            "file_refs": file_refs,
        }

    def _apply_fragment(self, fragment: dict[str, Any]) -> None:
        validate_fragment(fragment)
        source = fragment["source"]
        # Eigene Eintraege ersetzen, fremde Quellen bleiben erhalten.
        merged = {cid: e for cid, e in self._all_entries().items()
                  if e.get("source", "chatgpt") != source}
        merged.update(fragment["entries"])
        old_sources = (self.data.get("coverage") or {}).get("sources") or {}
        coverage_sources = {k: v for k, v in old_sources.items() if k != source}
        coverage_sources[source] = {
            "indexed": fragment["indexed"],
            "candidates": fragment["candidates"],
            "percent": _coverage_of(fragment),
            "failed_files": normalize_failed_files(fragment, source),
        }
        numbered = [(b.get("indexed", 0), b.get("candidates", 0))
                    for b in coverage_sources.values()
                    if isinstance(b, dict)]
        indexed_total = sum(i for i, _c in numbered)
        candidates_total = sum(c for _i, c in numbered)
        self.data = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "generated_at": now_iso(),
            "coverage": {
                "sources": coverage_sources,
                "percent": _coverage(indexed_total, candidates_total),
            },
            "conversations": merged,
        }
        self.save()
        from .status_store import refresh_file_index_records
        index = FileIndex(self.status_root)
        index._load()
        index._data["files"] = refresh_file_index_records(
            index._data.get("files"), fragment.get("file_refs") or {}, source)
        index.save()
        self.dirty_marker.unlink(missing_ok=True)

    def rebuild(self) -> "StorageIndex":
        self._apply_fragment(self.build_fragment())
        return self

    def refresh_one(self, path: Path, envelope: dict[str, Any]) -> None:
        cid = envelope["conversation_id"]
        convs = self.data.get("conversations")
        if not isinstance(convs, dict):
            convs = self.data["conversations"] = {}
        convs[cid] = _entry_from_envelope(path, self.root, envelope, self.library, self.source)
        self.data["generated_at"] = now_iso()

    @property
    def lost_path(self) -> Path:
        return self.status_root / LOST_FILE

    def _read_lost(self) -> dict[str, list[str]]:
        try:
            data = json.loads(self.lost_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): [str(x) for x in v] for k, v in data.items() if isinstance(v, list)} \
            if isinstance(data, dict) else {}

    def _write_lost(self, data: dict[str, list[str]]) -> None:
        data = {k: sorted(set(v)) for k, v in data.items() if v}
        if not data:
            self.lost_path.unlink(missing_ok=True)
            return
        self.lost_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.lost_path, data, staging_dir=self.dirty_staging / "index")

    def _remember_lost(self, ids: list[str]) -> None:
        data = self._read_lost()
        data[self.source] = sorted(set(data.get(self.source, [])) | set(ids))
        self._write_lost(data)

    @property
    def lost_entries(self) -> list[str]:
        """Lokal verlorene Conversations dieser Quelle, die noch nicht wieder im Index stehen."""
        present = self.conversations
        return sorted(cid for cid in self._read_lost().get(self.source, []) if cid not in present)

    def settle_lost(self) -> None:
        """Wieder vorhandene aus der Verlustliste streichen (Datei verschwindet, wenn leer)."""
        data = self._read_lost()
        if self.source in data:
            data[self.source] = self.lost_entries
            self._write_lost(data)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.path, self.data, staging_dir=self.dirty_staging / "index")


def _coverage_of(fragment: dict[str, Any]) -> float:
    """Coverage-Prozent eines Fragments (top-level oder verschachtelt)."""
    value = fragment.get("coverage_percent")
    if not isinstance(value, (int, float)):
        nested = fragment.get("coverage") or {}
        value = nested.get("percent") if isinstance(nested, dict) else None
    if not isinstance(value, (int, float)):
        raise ValueError("fragment coverage missing")
    return float(value)


def normalize_failed_files(fragment: dict[str, Any], source: str) -> list[dict[str, Any]]:
    """Vereinheitlicht `failed_files` zu `{source, file, error}`.

    Eintraege duerfen Strings (relativ zur Quellen-Wurzel, ChatGPT-Stil) oder
    Objekte mit `file` (relativ zur Store-Wurzel, inkl. Quelle) sein.
    """
    out: list[dict[str, Any]] = []
    failed = fragment.get("failed_files") or []
    if not isinstance(failed, list):
        raise ValueError("fragment failed_files not a list")
    for item in failed:
        if isinstance(item, str):
            out.append({"source": source, "file": f"{source}/{item}", "error": "unparseable"})
        elif isinstance(item, dict) and isinstance(item.get("file"), str) and item["file"]:
            out.append({"source": item.get("source") or source,
                        "file": item["file"],
                        "error": item.get("error") or "unparseable"})
        else:
            raise ValueError("fragment failed_files entry invalid")
    return out


def validate_fragment(fragment: Any) -> dict[str, Any]:
    """Prueft ein Fragment streng. Ungueltig -> ValueError (fail-closed, kein Commit).

    ID-Regel je Eintrag: Schlüssel ohne Doppelpunkt müssen dem ID-Feld
    (`conversation_id`/`session_id`/`record_id`) entsprechen (ChatGPT-Strenge).
    Schlüssel MIT Doppelpunkt müssen mit `<quelle>:<kind>:` beginnen und tragen
    ihre Identität im Suffix (Datei-abbildende Provider); ein ID-Feld ist dann
    empfohlen, aber nicht Pflicht.
    """
    if not isinstance(fragment, dict):
        raise ValueError("fragment is not an object")
    if fragment.get("fragment_schema_version") != FRAGMENT_SCHEMA_VERSION:
        raise ValueError("fragment schema mismatch")
    source = fragment.get("source")
    if not isinstance(source, str) or not source:
        raise ValueError("fragment source missing")
    entries = fragment.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("fragment entries missing")
    for key in ("candidates", "indexed", "failed_files"):
        if key not in fragment:
            raise ValueError(f"fragment meta missing: {key}")
    _coverage_of(fragment)
    file_refs = fragment.get("file_refs", {})
    if not isinstance(file_refs, dict):
        raise ValueError("fragment file_refs missing")
    for cid, entry in entries.items():
        if not isinstance(cid, str) or not cid:
            raise ValueError("fragment entry key invalid")
        if not isinstance(entry, dict):
            raise ValueError(f"fragment entry not an object: {cid}")
        if entry.get("source") != source:
            raise ValueError(f"fragment entry source mismatch: {cid}")
        kind = entry.get("kind")
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"fragment entry kind missing: {cid}")
        if not isinstance(entry.get("relative_path"), str) or not entry["relative_path"]:
            raise ValueError(f"fragment entry relative_path missing: {cid}")
        record_id = (entry.get("conversation_id") or entry.get("session_id")
                     or entry.get("record_id"))
        if ":" not in cid:
            if not isinstance(record_id, str) or record_id != cid:
                raise ValueError(f"fragment entry id mismatch: {cid}")
        else:
            if not cid.startswith(f"{source}:{kind}:"):
                raise ValueError(f"fragment entry key not namespaced: {cid}")
            if record_id is not None and not isinstance(record_id, str):
                raise ValueError(f"fragment entry id invalid: {cid}")
    normalize_failed_files(fragment, source)
    return fragment
