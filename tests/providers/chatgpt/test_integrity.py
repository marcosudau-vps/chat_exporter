from __future__ import annotations

import json
from pathlib import Path

from chatexporter.providers.chatgpt.common.hashing import sha256_bytes
from chatexporter.providers.chatgpt.fetch.conversation_fetcher import FetchedConversation
from chatexporter.providers.chatgpt.fetch.validator import validate_conversation_graph
from chatexporter.providers.chatgpt.storage.envelope import build_envelope
from chatexporter.providers.chatgpt.storage.integrity import verify_store
from chatexporter.providers.chatgpt.storage.library import LibraryStore
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.storage.status_store import rebuild_file_index

FILE_ID = "file_abcdef"


def _ref(fid: str = FILE_ID, **overrides):
    row = {"id": fid, "kind": "attachment", "node_id": "u1", "message_id": "u1",
           "name": "a.txt", "mime_type": "text/plain", "size": 5}
    row.update(overrides)
    return row


def _env(raw, summary, refs, library=None):
    fetched = FetchedConversation(raw=raw, textdocs=[], file_references=refs,
                                  tool_references=[], validation=validate_conversation_graph(raw),
                                  supplemental_errors=[])
    return build_envelope(summary, fetched, library=library)


def _materialize(root: Path, fid: str, data: bytes = b"hello", conversation_id: str = "c1"):
    d = root / "library" / "files" / fid
    d.mkdir(parents=True, exist_ok=True)
    (d / "content.txt").write_bytes(data)
    meta = {
        "schema_version": 1,
        "file_id": fid,
        "content_file": "content.txt",
        "content_sha256": sha256_bytes(data),
        "size": len(data),
        "_local": {
            "conversation_id": conversation_id,
            "message_id": "u1",
            "node_id": "u1",
            "references": [{"conversation_id": conversation_id, "message_id": "u1", "node_id": "u1"}],
        },
    }
    (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return d


def _make_store(tmp_path, simple_raw, summary, *, with_file=True, refs=None):
    root = tmp_path / "raw"
    repo = RawRepository(root)
    if with_file:
        _materialize(root, FILE_ID, b"hello", summary.get("id", "c1"))
    library = LibraryStore(root)
    if refs is None:
        refs = [_ref()] if with_file else []
    envelope = _env(simple_raw, summary, refs, library=library)
    repo.commit(envelope)
    rebuild_file_index(repo, repo.index.status_root)
    return root, repo


def _conv_path(root: Path) -> Path:
    return next((root / "conversations").rglob("*.json"))


def test_clean_store_has_no_errors_or_warnings(tmp_path, simple_raw, summary):
    root, _ = _make_store(tmp_path, simple_raw, summary)
    report = verify_store(root)
    assert report.ok
    assert report.errors == []
    assert report.warnings == []
    assert report.counts["conversations_on_disk"] == 1
    assert report.counts["references_materialized"] == 1
    assert report.counts["references_pending"] == 0
    assert report.counts["conversations_files_complete_false"] == 0


def test_missing_index_is_a_warning_not_an_error(tmp_path, simple_raw, summary):
    root, _ = _make_store(tmp_path, simple_raw, summary)
    (root / "storage_index.json").unlink()
    report = verify_store(root)
    assert report.ok
    assert any(i.code == "index.missing" for i in report.warnings)


def test_corrupt_index_is_an_error(tmp_path, simple_raw, summary):
    root, _ = _make_store(tmp_path, simple_raw, summary)
    (root / "storage_index.json").write_text("{bad", encoding="utf-8")
    report = verify_store(root)
    assert not report.ok
    assert any(i.code == "index.corrupt" for i in report.errors)


def test_index_entry_without_file_is_an_error(tmp_path, simple_raw, summary):
    root, _ = _make_store(tmp_path, simple_raw, summary)
    _conv_path(root).unlink()
    report = verify_store(root)
    assert not report.ok
    assert any(i.code == "index.entry-without-file" for i in report.errors)


def test_tampered_raw_payload_is_an_error(tmp_path, simple_raw, summary):
    root, _ = _make_store(tmp_path, simple_raw, summary)
    path = _conv_path(root)
    env = json.loads(path.read_text(encoding="utf-8"))
    env["raw"]["title"] = "tampered"
    path.write_text(json.dumps(env), encoding="utf-8")
    report = verify_store(root)
    assert not report.ok
    assert any(i.code == "envelope.raw-integrity" for i in report.errors)


def test_deleted_library_content_causes_files_complete_drift(tmp_path, simple_raw, summary):
    root, _ = _make_store(tmp_path, simple_raw, summary)
    (root / "library" / "files" / FILE_ID / "content.txt").unlink()
    report = verify_store(root)
    assert not report.ok
    assert any(i.code == "library.content-missing" for i in report.errors)
    assert any(i.code == "completeness.files-complete-drift" for i in report.errors)


def test_missing_local_block_is_a_warning(tmp_path, simple_raw, summary):
    root, _ = _make_store(tmp_path, simple_raw, summary)
    meta_path = root / "library" / "files" / FILE_ID / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.pop("_local")
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    report = verify_store(root)
    assert any(i.code == "library.missing-local" for i in report.warnings)


def test_orphan_library_entry_is_a_warning(tmp_path, simple_raw, summary):
    root, _ = _make_store(tmp_path, simple_raw, summary)
    _materialize(root, "file_orphan", b"xxx", "c1")
    report = verify_store(root)
    assert report.ok
    assert any(i.code == "library.orphan" for i in report.warnings)


def test_wrong_month_bucket_is_reported(tmp_path, simple_raw, summary):
    root, _ = _make_store(tmp_path, simple_raw, summary)
    path = _conv_path(root)
    wrong = path.parent.parent / "1900-01"
    wrong.mkdir(parents=True, exist_ok=True)
    path.rename(wrong / path.name)
    report = verify_store(root)
    assert any(i.code == "naming.bucket-mismatch" for i in report.warnings)


def test_deep_hash_check_detects_same_size_tampering(tmp_path, simple_raw, summary):
    root, _ = _make_store(tmp_path, simple_raw, summary)
    content = root / "library" / "files" / FILE_ID / "content.txt"
    content.write_bytes(b"HELLO")  # same size, different content
    shallow = verify_store(root)
    assert shallow.ok  # size still matches, no shallow error
    deep = verify_store(root, deep=True)
    assert not deep.ok
    assert any(i.code == "library.content-hash-mismatch" for i in deep.errors)


def test_stale_file_index_is_a_warning(tmp_path, simple_raw, summary):
    root, _ = _make_store(tmp_path, simple_raw, summary)
    status_root = root.parent / "status_registry"
    file_index = status_root / "file_index.json"
    data = json.loads(file_index.read_text(encoding="utf-8"))
    data["files"] = {}
    file_index.write_text(json.dumps(data), encoding="utf-8")
    report = verify_store(root)
    assert report.ok
    assert any(i.code == "file-index.missing-entry" for i in report.warnings)


def test_unsupported_reference_is_not_pending(tmp_path, simple_raw, summary):
    root, _ = _make_store(tmp_path, simple_raw, summary, with_file=False,
                          refs=[_ref("file-inline-libfile_xyz")])
    report = verify_store(root)
    assert report.ok
    assert report.counts["references_unsupported"] == 1
    assert report.counts["references_pending"] == 0
