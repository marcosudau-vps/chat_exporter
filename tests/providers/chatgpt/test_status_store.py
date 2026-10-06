"""Vertragstests fuer die Statusablage und die Datei-Zuordnung.

Zwei Beschluesse werden hier festgenagelt:

* Der Rohdaten-Speicher enthaelt nur, was tatsaechlich vorhanden ist.
  Nichtverfuegbarkeit liegt in der separaten Statusablage (nicht mehr als
  ``unavailable.json`` in der Library).
* Jede Datei ist ueber ``_local`` (Conversation/Message/Node) und einen
  Rueckwaertsindex eindeutig zuordenbar.
"""
from __future__ import annotations

import json

from chatexporter.providers.chatgpt.storage.library import LibraryStore
from chatexporter.providers.chatgpt.storage.status_store import FileStatusStore, resolve_status_root


class FakeFileApi:
    def metadata(self, file_id):
        return {"name": "x.txt", "mime_type": "text/plain", "size": 3}

    def download_ticket(self, file_id, *, gizmo_id=None):
        return {"download_url": "https://example.invalid/content", "file_name": "x.txt",
                "file_size_bytes": 3}

    def download_bytes(self, url):
        return b"abc"


def _ref(fid: str = "file_abc") -> dict:
    return {"id": fid, "kind": "attachment", "name": "x.txt",
            "node_id": "n1", "message_id": "m1"}


def test_resolve_status_root_defaults_next_to_raw_store(tmp_path):
    assert resolve_status_root(tmp_path / "raw") == tmp_path / "status_registry"
    assert resolve_status_root(tmp_path / "raw", tmp_path / "custom") == tmp_path / "custom"


def test_materialize_records_local_reference_and_reverse_index(tmp_path):
    lib = LibraryStore(tmp_path / "raw")
    lib.materialize(_ref(), FakeFileApi(), conversation_id="c1")

    meta = json.loads((tmp_path / "raw" / "library" / "files" / "file_abc" / "metadata.json")
                      .read_text(encoding="utf-8"))
    assert meta["_local"]["conversation_id"] == "c1"
    assert meta["_local"]["message_id"] == "m1"
    assert meta["_local"]["node_id"] == "n1"
    assert {"conversation_id": "c1", "message_id": "m1", "node_id": "n1"} in meta["_local"]["references"]
    # Rueckwaertsrichtung: Datei -> Conversation/Message.
    assert lib.file_index.references("file_abc") == [
        {"conversation_id": "c1", "message_id": "m1", "node_id": "n1"}]
    # Nichts wurde als "nicht verfuegbar" markiert.
    assert not (tmp_path / "raw" / "library" / "files" / "file_abc" / "unavailable.json").exists()


def test_unavailable_lives_in_status_registry_not_raw_store(tmp_path):
    lib = LibraryStore(tmp_path / "raw")
    lib.mark_unavailable(_ref("file_zzz"), status=404, detail="gone", conversation_id="c1")

    assert lib.is_unavailable("file_zzz")
    # Kein Marker im Rohdaten-Speicher.
    assert not (tmp_path / "raw" / "library" / "files" / "file_zzz" / "unavailable.json").exists()
    # Status liegt in der separaten Ablage.
    status = FileStatusStore(tmp_path / "status_registry")
    assert status.is_unavailable("file_zzz")
    record = status.get("file_zzz")
    assert record["http_status"] == 404
    assert record["source_refs"] == [
        {"conversation_id": "c1", "message_id": "m1", "node_id": "n1"}]


def test_legacy_marker_is_readable_and_can_be_migrated(tmp_path):
    legacy_dir = tmp_path / "raw" / "library" / "files" / "file_old"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "unavailable.json").write_text(
        json.dumps({"file_id": "file_old", "http_status": 404}), encoding="utf-8")

    lib = LibraryStore(tmp_path / "raw")
    # Rueckwaertskompatibel lesbar.
    assert lib.is_unavailable("file_old")

    # Migration (wie in `chatexporter migrate-store`).
    lib.status.mark_unavailable("file_old", status=404, detail=None)
    (legacy_dir / "unavailable.json").unlink()
    assert FileStatusStore(tmp_path / "status_registry").is_unavailable("file_old")
    assert not (legacy_dir / "unavailable.json").exists()


def test_register_reference_merges_multiple_conversations(tmp_path):
    lib = LibraryStore(tmp_path / "raw")
    lib.materialize(_ref(), FakeFileApi(), conversation_id="c1")
    other = {"id": "file_abc", "kind": "attachment", "node_id": "n2", "message_id": "m2"}
    lib.register_reference(other, conversation_id="c2")

    meta = json.loads((tmp_path / "raw" / "library" / "files" / "file_abc" / "metadata.json")
                      .read_text(encoding="utf-8"))
    refs = meta["_local"]["references"]
    assert {"conversation_id": "c1", "message_id": "m1", "node_id": "n1"} in refs
    assert {"conversation_id": "c2", "message_id": "m2", "node_id": "n2"} in refs
    assert meta["_local"]["conversation_id"] == "c1", "Hauptbezug bleibt der Erstfund"
    assert lib.file_index.references("file_abc")[0]["conversation_id"] == "c1"
