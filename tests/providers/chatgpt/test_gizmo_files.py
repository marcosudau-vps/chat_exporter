"""Vertragstests fuer Gizmo-Dateien.

Gizmo-Dateien (use_case == "gizmo") liefern am generischen Download-Endpunkt
HTTP 403. Mit dem Kontext-Parameter ``gizmo_id`` antwortet er mit HTTP 200.
Der Download muss den Parameter mitschicken, wenn die Conversation eine
``gizmo_id`` traegt.
"""
from __future__ import annotations

from chatexporter.providers.chatgpt.api.files import FileApi
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.sync.orchestrator import SyncOrchestrator


class RecordingClient:
    def __init__(self):
        self.calls = []

    def get_json(self, path, *, params=None):
        self.calls.append((path, dict(params or {})))
        if path.endswith("/download"):
            return {"download_url": "https://example.invalid/content", "file_size_bytes": 3}
        return {"name": "x.txt", "mime_type": "text/plain", "size": 3}


def test_download_ticket_passes_gizmo_id():
    client = RecordingClient()
    FileApi(client).download_ticket("file_abc", gizmo_id="g-p-123")
    path, params = client.calls[-1]
    assert path == "/backend-api/files/file_abc/download"
    assert params == {"gizmo_id": "g-p-123"}


def test_download_ticket_without_gizmo_id_has_no_param():
    client = RecordingClient()
    FileApi(client).download_ticket("file_abc")
    _, params = client.calls[-1]
    assert params == {}


class RecordingFileApi:
    def __init__(self):
        self.gizmo_ids = []

    def metadata(self, file_id):
        return {"name": "x.txt", "mime_type": "text/plain", "size": 3}

    def download_ticket(self, file_id, *, gizmo_id=None):
        self.gizmo_ids.append(gizmo_id)
        return {"download_url": "https://example.invalid/content", "file_name": "x.txt",
                "file_size_bytes": 3}

    def download_bytes(self, url):
        return b"abc"


class GizmoConversations:
    """Eine Conversation mit gizmo_id und einer Datei."""

    def iter_scope(self, *, archived: bool, limit: int = 100):
        if archived:
            return
        yield {"id": "c1", "title": "T", "create_time": 1.0, "update_time": 2.0,
               "is_archived": False, "is_starred": None, "pinned_time": None,
               "gizmo_id": "g-p-123"}

    def get_conversation(self, conversation_id):
        return {"conversation_id": conversation_id, "current_node": "n1",
                "mapping": {"n1": {"id": "n1", "parent": None, "children": [], "message": {
                    "id": "m1", "author": {"role": "user"},
                    "content": {"content_type": "multimodal_text", "parts": [
                        {"content_type": "image_asset_pointer", "asset_pointer": "sediment://file_abc"}]},
                    "create_time": 1.0}}}}

    def get_textdocs(self, conversation_id):
        return []


def test_file_inline_pseudo_id_is_unsupported(tmp_path):
    from chatexporter.providers.chatgpt.storage.library import LibraryStore
    lib = LibraryStore(tmp_path / "raw")
    assert lib.derived_state({"id": "file-inline-libfile_abc"}) == "UNSUPPORTED"
    result = lib.materialize({"id": "file-inline-libfile_abc"}, None)
    assert result["state"] == "UNSUPPORTED"


def test_orchestrator_passes_gizmo_id_from_summary(tmp_path):
    repo = RawRepository(tmp_path / "raw")
    file_api = RecordingFileApi()
    SyncOrchestrator(conversation_api=GizmoConversations(), file_api=file_api,
                     repository=repo, fetch_files=True).run()
    assert file_api.gizmo_ids == ["g-p-123"], (
        "die gizmo_id der Conversation muss an den Download weitergereicht werden")
    # Herkunft muss gesetzt sein: _local mit Conversation- und Message-Id.
    meta_path = next((tmp_path / "raw" / "library" / "files").rglob("metadata.json"))
    import json
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["_local"]["conversation_id"] == "c1"
    assert meta["_local"]["message_id"] == "m1"
    assert meta["download_metadata"]["gizmo_id"] == "g-p-123"
