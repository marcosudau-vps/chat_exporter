from __future__ import annotations

"""Integritaets-/Konsistenzpruefung des Rohdatenbestands.

Bewusst **lesend**: Der Checker veraendert keine Daten. Er prueft quer ueber
Rohdaten-Speicher, Index, Statusablage und Library, ob die abgeleiteten
Strukturen zum tatsaechlichen Bestand passen und ob das Format eingehalten wird.

Motivation: Der Rohdatenbestand ist die Quelle der Wahrheit; Index und
Statusablage sind rebuildbare Beschleuniger. Genau deshalb muss man *pruefen*
koennen, dass sie konsistent sind -- ein stiller Drift wuerde sonst erst beim
naechsten Sync auffallen.

Ergebnis ist ein ``IntegrityReport``; ``ok`` ist genau dann wahr, wenn es
keine ``ERROR``-Befunde gibt. ``WARNING`` markiert rebuildbare/abgeleitete
Abweichungen (kein Datenverlust). Genutzt von ``chatexporter verify-store``.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chatexporter.providers.chatgpt.common.hashing import canonical_json_bytes, sha256_bytes, sha256_file
from chatexporter.providers.chatgpt.storage.envelope import files_complete_state
from chatexporter.providers.chatgpt.storage.index import REQUIRED_ENTRY_FIELDS, _entry_from_envelope
from chatexporter.providers.chatgpt.storage.library import LibraryStore
from chatexporter.providers.chatgpt.storage.raw_repository import _date_bucket
from chatexporter.providers.chatgpt.storage.status_store import FileIndex, resolve_status_root

#: Felder, die ein Envelope im aktuellen Format garantiert traegt.
ENVELOPE_REQUIRED_FIELDS = (
    "storage_schema_version",
    "provider",
    "conversation_id",
    "remote_summary",
    "acquisition",
    "raw",
    "file_references",
    "integrity",
)

#: Pflichtfelder im ``acquisition``-Block.
ACQUISITION_REQUIRED_FIELDS = (
    "json_complete",
    "files_complete",
    "complete",
    "source",
)

#: Index-Felder, die deterministisch aus dem Envelope ableitbar sind. Ein
#: abweichender Wert bedeutet: der Index ist stale (rebuildbar).
INDEX_DETERMINISTIC_FIELDS = (
    "relative_path",
    "title",
    "json_complete",
    "files_complete",
    "acquisition_source",
    "file_reference_count",
    "file_materialized_count",
    "file_unavailable_count",
    "file_sha256",
    "raw_integrity_ok",
)

#: Zaehler, die auch bei Wert 0 im Report stehen sollen (stabile Ausgabe).
_STABLE_COUNT_KEYS = (
    "conversation_files",
    "conversations_on_disk",
    "envelopes_unparseable",
    "duplicate_conversation_ids",
    "bucket_mismatch",
    "raw_integrity_failures",
    "index_entries_without_file",
    "files_without_index_entry",
    "index_stale_entries",
    "references_total",
    "references_materialized",
    "references_unavailable",
    "references_unsupported",
    "references_pending",
    "references_without_node_id",
    "references_total",
    "files_referenced_distinct",
    "files_materialized_distinct",
    "files_unavailable_distinct",
    "library_ready_dirs",
    "library_empty_dirs",
    "files_complete_drift",
    "complete_drift",
    "conversations_files_complete_false",
    "library_dirs",
    "library_orphans",
    "library_missing_metadata",
    "library_missing_content",
    "library_missing_local",
    "library_size_mismatch",
    "library_hash_mismatch",
    "file_status_unexpected_state",
    "file_index_missing_entries",
    "file_index_stale_entries",
    "file_index_extra_entries",
    "coverage_percent",
    "index_coverage_degraded",
    "staging_leftovers",
)


@dataclass(slots=True)
class Issue:
    level: str  # "ERROR" | "WARNING"
    code: str
    message: str
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "code": self.code, "message": self.message, "context": self.context}


@dataclass(slots=True)
class IntegrityReport:
    raw_root: Path
    status_root: Path
    counts: dict[str, int]
    issues: list[Issue]

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "ERROR"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "WARNING"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "raw_root": str(self.raw_root),
            "status_root": str(self.status_root),
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "counts": self.counts,
            "issues": [i.as_dict() for i in self.issues],
        }

    def summary(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
        }


def _add(issues: list[Issue], level: str, code: str, message: str, **context: Any) -> None:
    issues.append(Issue(level=level, code=code, message=message, context=context))


def _check_envelope_fields(env: dict[str, Any], issues: list[Issue], where: str) -> None:
    missing = [f for f in ENVELOPE_REQUIRED_FIELDS if f not in env]
    if missing:
        _add(issues, "ERROR", "envelope.missing-fields", "Envelope fehlen Pflichtfelder", path=where, missing=missing)
        return
    if env.get("storage_schema_version") != 1:
        _add(issues, "ERROR", "envelope.schema-version", "Unerwartete storage_schema_version",
             path=where, value=env.get("storage_schema_version"))
    if env.get("provider") != "chatgpt":
        _add(issues, "WARNING", "envelope.provider", "Unerwarteter provider", path=where, value=env.get("provider"))
    summary = env.get("remote_summary")
    if not isinstance(summary, dict):
        _add(issues, "ERROR", "envelope.remote-summary", "remote_summary ist kein Objekt", path=where)
    elif summary.get("id") != env.get("conversation_id"):
        _add(issues, "ERROR", "envelope.summary-id-mismatch", "remote_summary.id != conversation_id", path=where)
    acq = env.get("acquisition")
    if not isinstance(acq, dict):
        _add(issues, "ERROR", "envelope.acquisition", "acquisition ist kein Objekt", path=where)
    else:
        has_split = "json_complete" in acq and "files_complete" in acq
        has_legacy = "complete" in acq
        if not has_split and not has_legacy:
            _add(issues, "ERROR", "envelope.acquisition-fields",
                 "acquisition enthaelt weder complete noch json_complete/files_complete", path=where)
        elif not has_split:
            _add(issues, "INFO", "envelope.legacy-acquisition-fields",
                 "acquisition im Altformat (nur 'complete'); zulaessig, nicht migriert", path=where)
        if "source" not in acq:
            _add(issues, "INFO", "envelope.missing-source",
                 "acquisition.source fehlt (Alt-Envelope)", path=where)
    raw = env.get("raw")
    if not isinstance(raw, dict):
        _add(issues, "ERROR", "envelope.raw", "raw ist kein Objekt", path=where)
        return
    mapping = raw.get("mapping")
    if not isinstance(mapping, dict) or not mapping:
        _add(issues, "ERROR", "envelope.mapping", "raw.mapping fehlt/leer", path=where)
    elif raw.get("current_node") not in mapping:
        _add(issues, "WARNING", "envelope.current-node", "current_node nicht im mapping", path=where,
             current_node=raw.get("current_node"))


def verify_store(
    raw_root: Path,
    status_root: Path | None = None,
    *,
    deep: bool = False,
    exclusions: Any = None,
    quarantine: Any = None,
    source: str = "chatgpt",
    runtime_root: Path | None = None,
    index_path: Path | None = None,
) -> IntegrityReport:
    """Prueft den Rohdatenbestand read-only und liefert einen Report.

    Layout wird automatisch erkannt, mit derselben Regel wie
    `resolve_store_layout`: flaches Legacy-Layout (Quelle == Wurzel) nur, wenn
    `<raw_root>/conversations/` existiert und `<raw_root>/<source>/` nicht;
    sonst gilt der Provider-Vertrag (Quelle + Runtime) -- auch fuer einen
    frischen, leeren Bestand.
    """
    store = Path(raw_root)
    runtime = Path(runtime_root) if runtime_root is not None else store.parent / ".storage"
    legacy = (store / "conversations").is_dir() and not (store / source).is_dir()
    if not legacy:
        root = store / source
        resolved_status = Path(status_root) if status_root is not None else runtime / "status_registry"
        idx_path = Path(index_path) if index_path is not None else resolved_status / "storage_index.json"
    else:
        # Flaches Legacy-Layout: Quelle == Wurzel (Pfade alt, Regeln neu).
        root = store
        resolved_status = resolve_status_root(root, status_root)
        idx_path = Path(index_path) if index_path is not None else root / "storage_index.json"
    bucket_of = _date_bucket
    bucket_label = "<YYYY/MM/DD|unknown>"
    issues: list[Issue] = []
    counts: Counter[str] = Counter()

    # -- 1. Conversation-Dateien: vorhanden, parsebar, Namensschema ----------
    conv_root = root / "conversations"
    on_disk: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    if not conv_root.exists():
        _add(issues, "WARNING", "store.no-conversations", "conversations/ fehlt", path=str(conv_root))
    else:
        for path in sorted(conv_root.rglob("*.json")):
            counts["conversation_files"] += 1
            try:
                env = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                counts["envelopes_unparseable"] += 1
                _add(issues, "ERROR", "envelope.unparseable", "Envelope nicht lesbar",
                     path=path.relative_to(root).as_posix(), error=f"{type(exc).__name__}: {exc}")
                continue
            if not isinstance(env, dict):
                counts["envelopes_unparseable"] += 1
                _add(issues, "ERROR", "envelope.not-object", "Envelope ist kein Objekt",
                     path=path.relative_to(root).as_posix())
                continue
            rel = path.relative_to(root).as_posix()
            _check_envelope_fields(env, issues, rel)

            cid = env.get("conversation_id")
            if not isinstance(cid, str) or not cid:
                _add(issues, "ERROR", "envelope.missing-conversation-id", "conversation_id fehlt",
                     path=rel)
                continue
            if cid in on_disk:
                counts["duplicate_conversation_ids"] += 1
                _add(issues, "ERROR", "conversation.duplicate", "conversation_id mehrfach vorhanden",
                     conversation_id=cid, first=paths[cid].relative_to(root).as_posix(), second=rel)
            on_disk[cid] = env
            paths[cid] = path

            # Namensschema: <id>.json im erwarteten Bucket
            if path.name != f"{cid}.json":
                _add(issues, "ERROR", "naming.filename-mismatch", "Dateiname != conversation_id.json",
                     path=rel, conversation_id=cid)
            summary = env.get("remote_summary") if isinstance(env.get("remote_summary"), dict) else {}
            expected_bucket = bucket_of(summary.get("create_time"))
            actual_bucket = path.parent.relative_to(conv_root).as_posix()
            if actual_bucket != expected_bucket:
                counts["bucket_mismatch"] += 1
                _add(issues, "WARNING", "naming.bucket-mismatch", "Bucket passt nicht zu create_time",
                     path=rel, actual=actual_bucket,
                     expected=expected_bucket, schema=bucket_label)

            # Rohdaten-Integritaet
            raw = env.get("raw")
            integ = env.get("integrity") if isinstance(env.get("integrity"), dict) else {}
            expected_hash = integ.get("raw_payload_sha256")
            actual_hash = sha256_bytes(canonical_json_bytes(raw)) if isinstance(raw, dict) else None
            if not expected_hash or expected_hash != actual_hash:
                counts["raw_integrity_failures"] += 1
                _add(issues, "ERROR", "envelope.raw-integrity", "raw_payload_sha256 passt nicht zum Inhalt",
                     path=rel)

    counts["conversations_on_disk"] = len(on_disk)

    library = LibraryStore(root, status_root)

    # -- 2. Index: vorhanden, konsistent, deterministisch --------------------
    index_path = idx_path
    indexed: dict[str, dict[str, Any]] = {}
    if not index_path.exists():
        _add(issues, "WARNING", "index.missing", "Index fehlt (rebuildbar)", path=str(index_path))
    else:
        try:
            idx = json.loads(index_path.read_text(encoding="utf-8"))
            convs = idx.get("conversations")
            if not isinstance(convs, dict):
                raise ValueError("conversations fehlt")
            # Nur Einträge der eigenen Quelle prüfen; fremde gehören anderen
            # Wurzeln und werden von deren Health-Prüfung abgedeckt.
            indexed = {cid: e for cid, e in convs.items()
                       if isinstance(e, dict) and e.get("source", "chatgpt") == source}
        except Exception as exc:  # noqa: BLE001
            _add(issues, "ERROR", "index.corrupt", "Index nicht lesbar/konsistent",
                 path=str(index_path), error=f"{type(exc).__name__}: {exc}")
            indexed = {}

    try:
        coverage = (json.loads(index_path.read_text(encoding="utf-8")).get("coverage")
                    if index_path.exists() else None)
    except Exception:  # noqa: BLE001
        coverage = None
    if isinstance(coverage, dict):
        percent = coverage.get("percent")
        if isinstance(percent, (int, float)):
            counts["coverage_percent"] = percent
            if percent < 100:
                counts["index_coverage_degraded"] += 1
                _add(issues, "WARNING", "index.coverage-degraded",
                     "Index-Coverage unter 100 % (siehe failed_files)",
                     percent=percent)
        for src_name, block in (coverage.get("sources") or {}).items():
            for failed in (block or {}).get("failed_files", []) or []:
                if isinstance(failed, dict):
                    fsource = failed.get("source") or src_name
                    fpath = failed.get("file") or ""
                    ferr = failed.get("error") or "unparseable"
                else:
                    fsource, fpath, ferr = src_name, failed, "unparseable"
                if fsource != source:
                    # Fremde Quellen meldet deren eigene Health-Prüfung als
                    # Fehler; hier nur Sichtbarkeit.
                    _add(issues, "WARNING", "index.foreign-failed-file",
                         "Andere Quelle hat nicht indexierbare Dateien",
                         source=fsource, path=fpath, error=ferr)
                    continue
                counts["envelopes_unparseable"] += 1
                shown = fpath if str(fpath).startswith("conversations/") else f"conversations/{fpath}"
                _add(issues, "ERROR", "envelope.unparseable",
                     "Envelope nicht indexierbar (senkt Coverage)",
                     path=shown, source=fsource, error=ferr)

    if indexed:
        missing_fields = sorted({f for e in indexed.values() if isinstance(e, dict)
                                 for f in REQUIRED_ENTRY_FIELDS if f not in e})
        if missing_fields:
            _add(issues, "ERROR", "index.missing-entry-fields",
                 "Index-Eintraege kennen Pflichtfelder nicht", missing=missing_fields)
        for cid, entry in indexed.items():
            if cid not in on_disk:
                counts["index_entries_without_file"] += 1
                _add(issues, "ERROR", "index.entry-without-file", "Index verweist auf fehlende Conversation",
                     conversation_id=cid, relative_path=(entry or {}).get("relative_path"))
                continue
            rel_expected = paths[cid].relative_to(root).as_posix()
            if entry.get("relative_path") != rel_expected:
                _add(issues, "ERROR", "index.path-drift", "Index-Pfad != tatsaechlicher Pfad",
                     conversation_id=cid, index=(entry.get("relative_path")), actual=rel_expected)
            fresh = _entry_from_envelope(paths[cid], root, on_disk[cid], library, source)
            drift = [f for f in INDEX_DETERMINISTIC_FIELDS if entry.get(f) != fresh.get(f)]
            if drift:
                counts["index_stale_entries"] += 1
                _add(issues, "WARNING", "index.stale-entry", "Index-Eintrag weicht vom Envelope ab (rebuildbar)",
                     conversation_id=cid, fields=drift)
        for cid in on_disk:
            if cid not in indexed:
                counts["files_without_index_entry"] += 1
                _add(issues, "ERROR", "index.file-without-entry", "Conversation fehlt im Index",
                     conversation_id=cid)

    # -- 3. Dateireferenzen: Zustaende, Vollstaendigkeit ---------------------
    state_counts: Counter[str] = Counter()
    pending_ids: set[str] = set()
    referenced_ids: set[str] = set()
    for cid, env in on_disk.items():
        refs = env.get("file_references")
        refs_list = refs if isinstance(refs, list) else []
        for ref in refs_list:
            if not isinstance(ref, dict):
                _add(issues, "ERROR", "reference.not-object", "Dateireferenz ist kein Objekt",
                     conversation_id=cid)
                continue
            fid = ref.get("id")
            if not isinstance(fid, str) or not fid:
                _add(issues, "ERROR", "reference.missing-id", "Dateireferenz ohne id", conversation_id=cid)
                continue
            referenced_ids.add(fid)
            state = library.derived_state(ref)
            state_counts[state] += 1
            if state == "PENDING":
                pending_ids.add(fid)
            if ref.get("node_id") is None:
                counts["references_without_node_id"] += 1
                _add(issues, "WARNING", "reference.missing-node-id", "Dateireferenz ohne node_id",
                     conversation_id=cid, file_id=fid)

        acq = env.get("acquisition") if isinstance(env.get("acquisition"), dict) else {}
        expected_files_complete = files_complete_state(refs_list, library, quarantine, exclusions)
        json_ok = bool(acq.get("json_complete", acq.get("complete")))
        if bool(acq.get("files_complete")) != expected_files_complete:
            counts["files_complete_drift"] += 1
            _add(issues, "ERROR", "completeness.files-complete-drift",
                 "files_complete passt nicht zum tatsaechlichen Dateizustand",
                 conversation_id=cid, stored=acq.get("files_complete"), actual=expected_files_complete)
        expected_complete = json_ok and expected_files_complete
        if bool(acq.get("complete")) != expected_complete:
            counts["complete_drift"] += 1
            _add(issues, "ERROR", "completeness.complete-drift",
                 "complete != (json_complete and files_complete)",
                 conversation_id=cid, stored=acq.get("complete"), actual=expected_complete)
        if acq.get("files_complete") is False:
            counts["conversations_files_complete_false"] += 1

    counts["references_total"] = sum(state_counts.values())
    counts["references_materialized"] = state_counts.get("MATERIALIZED", 0)
    counts["references_unavailable"] = state_counts.get("UNAVAILABLE", 0)
    counts["references_unsupported"] = state_counts.get("UNSUPPORTED", 0)
    counts["references_pending"] = state_counts.get("PENDING", 0)
    counts["files_referenced_distinct"] = len(referenced_ids)

    # -- 4. Library-Verzeichnisse: Vollstaendigkeit, _local, Orphans ---------
    library_ready = 0
    for base_name in ("files", "audio"):
        base = root / "library" / base_name
        if not base.exists():
            continue
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            counts["library_dirs"] += 1
            fid = d.name
            meta_path = d / "metadata.json"
            contents = sorted(p for p in d.glob("content.*") if p.is_file())
            if fid not in referenced_ids:
                counts["library_orphans"] += 1
                _add(issues, "WARNING", "library.orphan", "Library-Eintrag ohne Dateireferenz",
                     file_id=fid, path=d.relative_to(root).as_posix())
            if not meta_path.exists() and not contents:
                # Rest des frueheren unavailable.json-Markers: Verzeichnis ohne
                # Inhalt. Harmlos, aber aufraeumbar -- kein Datenverlust.
                counts["library_empty_dirs"] += 1
                _add(issues, "WARNING", "library.empty-dir",
                     "Leeres Verzeichnis (Alt-Marker-Rest)", file_id=fid,
                     path=d.relative_to(root).as_posix())
                continue
            if not meta_path.exists():
                counts["library_missing_metadata"] += 1
                _add(issues, "ERROR", "library.metadata-missing", "metadata.json fehlt",
                     file_id=fid, path=d.relative_to(root).as_posix())
                continue
            if not contents:
                counts["library_missing_content"] += 1
                _add(issues, "ERROR", "library.content-missing", "content.* fehlt",
                     file_id=fid, path=d.relative_to(root).as_posix())
                continue
            library_ready += 1
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                _add(issues, "ERROR", "library.metadata-corrupt", "metadata.json nicht lesbar",
                     file_id=fid, error=f"{type(exc).__name__}: {exc}")
                continue
            if not isinstance(meta, dict):
                _add(issues, "ERROR", "library.metadata-not-object", "metadata.json ist kein Objekt", file_id=fid)
                continue
            local = meta.get("_local")
            if not isinstance(local, dict) or not local.get("conversation_id"):
                counts["library_missing_local"] += 1
                _add(issues, "WARNING", "library.missing-local", "metadata.json ohne _local.conversation_id",
                     file_id=fid)
            size = meta.get("size")
            if isinstance(size, int) and all(p.stat().st_size != size for p in contents):
                counts["library_size_mismatch"] += 1
                _add(issues, "ERROR", "library.size-mismatch", "Dateigroesse != metadata.size",
                     file_id=fid, expected=size, actual=[p.stat().st_size for p in contents])
            expected_sha = meta.get("content_sha256")
            if deep and isinstance(expected_sha, str):
                actual_shas = {p.stat().st_size: sha256_file(p) for p in contents}
                if expected_sha not in actual_shas.values():
                    counts["library_hash_mismatch"] += 1
                    _add(issues, "ERROR", "library.content-hash-mismatch", "content_sha256 passt nicht",
                         file_id=fid)

    counts["files_materialized_distinct"] = library_ready
    counts["library_ready_dirs"] = library_ready

    # -- 5. Statusablage: Zustaende + Rueckwaertsindex -----------------------
    file_status_path = resolved_status / "file_status.json"
    if file_status_path.exists():
        try:
            fs = json.loads(file_status_path.read_text(encoding="utf-8")).get("files")
            if not isinstance(fs, dict):
                raise ValueError("files fehlt")
            counts["files_unavailable_distinct"] = sum(
                1 for rec in fs.values() if isinstance(rec, dict) and rec.get("state") == "UNAVAILABLE")
            for fid, rec in fs.items():
                state = rec.get("state") if isinstance(rec, dict) else None
                if state != "UNAVAILABLE":
                    counts["file_status_unexpected_state"] += 1
                    _add(issues, "WARNING", "status.unexpected-state",
                         "file_status.json mit unerwartetem state", file_id=fid, state=state)
        except Exception as exc:  # noqa: BLE001
            _add(issues, "ERROR", "status.corrupt", "file_status.json nicht lesbar",
                 error=f"{type(exc).__name__}: {exc}")

    file_index_path = resolved_status / "file_index.json"
    if file_index_path.exists():
        try:
            stored = json.loads(file_index_path.read_text(encoding="utf-8")).get("files")
            if not isinstance(stored, dict):
                raise ValueError("files fehlt")
        except Exception as exc:  # noqa: BLE001
            _add(issues, "ERROR", "file-index.corrupt", "file_index.json nicht lesbar",
                 error=f"{type(exc).__name__}: {exc}")
        else:
            expected: dict[str, set[tuple]] = {}
            for cid, env in on_disk.items():
                for ref in env.get("file_references") or []:
                    if not isinstance(ref, dict):
                        continue
                    fid = ref.get("id")
                    if not isinstance(fid, str):
                        continue
                    expected.setdefault(fid, set()).add(
                        (cid, ref.get("message_id"), ref.get("node_id")))
            for fid, rows in expected.items():
                if fid not in stored:
                    counts["file_index_missing_entries"] += 1
                    _add(issues, "WARNING", "file-index.missing-entry",
                         "file_index.json kennt referenzierte Datei nicht (rebuildbar)", file_id=fid)
                    continue
                actual_rows = {(r.get("conversation_id"), r.get("message_id"), r.get("node_id"))
                               for r in (stored[fid].get("references") or []) if isinstance(r, dict)}
                if actual_rows != rows:
                    counts["file_index_stale_entries"] += 1
                    _add(issues, "WARNING", "file-index.stale-entry",
                         "file_index.json weicht von den Envelopes ab (rebuildbar)", file_id=fid)
            for fid, record in stored.items():
                if not isinstance(record, dict):
                    continue
                record_sources = record.get("sources")
                if isinstance(record_sources, list) and source not in record_sources:
                    continue  # fremde Quelle, deren Health-Prüfung zuständig ist
                if fid not in expected:
                    counts["file_index_extra_entries"] += 1
                    _add(issues, "WARNING", "file-index.extra-entry",
                         "file_index.json enthaelt nicht mehr referenzierte Datei (rebuildbar)", file_id=fid)
    elif (resolved_status).exists():
        _add(issues, "WARNING", "file-index.missing", "file_index.json fehlt (rebuildbar)",
             path=str(file_index_path))

    # -- 6. Runs / Staging-Reste --------------------------------------------
    # Staging liegt im neuen Layout unter .storage/staging, im flachen
    # Legacy-Layout unter <root>/.staging.
    staging_scan = runtime / "staging" if (store / source / "conversations").is_dir() else root / ".staging"
    runs_root = runtime / "runs" if (store / source / "conversations").is_dir() else root / "runs"
    if runs_root.exists():
        for manifest in sorted(runs_root.glob("sync_*.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                _add(issues, "WARNING", "run-manifest.unreadable", "Run-Manifest nicht lesbar",
                     path=manifest.name, error=f"{type(exc).__name__}: {exc}")
                continue
            if not isinstance(data, dict) or "schema_version" not in data:
                _add(issues, "WARNING", "run-manifest.schema", "Run-Manifest ohne schema_version",
                     path=manifest.name)

    staging = staging_scan
    if staging.exists():
        leftovers = [p for p in staging.rglob("*") if p.is_file() and p.suffix == ".tmp"]
        if leftovers:
            counts["staging_leftovers"] = len(leftovers)
            _add(issues, "WARNING", "store.staging-leftover", "Temporaere Dateien im Staging",
                 count=len(leftovers))

    counts["errors"] = sum(1 for i in issues if i.level == "ERROR")
    counts["warnings"] = sum(1 for i in issues if i.level == "WARNING")
    counts["infos"] = sum(1 for i in issues if i.level == "INFO")
    for key in _STABLE_COUNT_KEYS:
        counts.setdefault(key, 0)
    return IntegrityReport(raw_root=root, status_root=resolved_status, counts=dict(counts), issues=issues)
