from chatexporter.providers.chatgpt.sync.orchestrator import SyncOrchestrator
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository


class FakeConversationApi:
    def iter_scope(self, archived, limit=100):
        if not archived:
            yield {"id":"c1","title":"T","create_time":1789700000.0,"update_time":1,"is_archived":False,"is_starred":False,"pinned_time":None}

    def get_conversation(self,cid):
        return {"conversation_id":cid,"title":"T","create_time":1789700000.0,"update_time":1,"current_node":"u","mapping":{
            "root":{"id":"root","message":None,"parent":None,"children":["u"]},
            "u":{"id":"u","parent":"root","children":[],"message":{"id":"u","author":{"role":"user"},"content":{"content_type":"text","parts":["x"]},"metadata":{},"recipient":"all"}}
        }}

    def get_textdocs(self,cid):
        return []


class FakeFileApi:
    pass




def test_progress_reports_listing_plan_and_commit(tmp_path):
    messages=[]
    repo=RawRepository(tmp_path/'raw')
    orch=SyncOrchestrator(
        conversation_api=FakeConversationApi(),
        file_api=FakeFileApi(),
        repository=repo,
        fetch_files=False,
        progress=messages.append,
    )
    result=orch.run()
    assert result['stats']['fetched']==1
    assert any('Remote-Listing (full) wird geladen' in m for m in messages)
    assert any('Erstabruf' in m for m in messages), "auto ohne Bestand = Erstabruf"
    assert any('Sync-Plan:' in m for m in messages)
    assert any('FETCH c1' in m for m in messages)
    assert any('RAW COMMIT c1' in m for m in messages)
    assert any('Sync abgeschlossen' in m for m in messages)


class AttachmentConversationApi:
    def __init__(self, *, conversations=1, file_ids=None, events=None):
        self.conversations = conversations
        self.file_ids = list(file_ids or [])
        self.events = events if events is not None else []

    def iter_scope(self, archived, limit=100):
        if archived:
            return
        for i in range(self.conversations):
            yield {
                "id": f"c{i+1}",
                "title": f"T{i+1}",
                "create_time": 1789700000.0 + i,
                "update_time": i + 1,
                "is_archived": False,
                "is_starred": False,
                "pinned_time": None,
            }

    def get_conversation(self, cid):
        self.events.append(f"conv:{cid}")
        idx = int(cid[1:]) - 1
        attachments = []
        # For one-conversation tests all file ids belong to that conversation;
        # otherwise assign one deterministic file per conversation.
        ids = self.file_ids if self.conversations == 1 else [self.file_ids[idx]]
        for fid in ids:
            attachments.append({
                "id": fid,
                "name": f"{fid}.txt",
                "mime_type": "text/plain",
                "size": 3,
                "source": "local",
            })
        return {
            "conversation_id": cid,
            "title": cid,
            "create_time": 1789700000.0 + idx,
            "update_time": idx + 1,
            "current_node": "u",
            "mapping": {
                "root": {"id": "root", "message": None, "parent": None, "children": ["u"]},
                "u": {
                    "id": "u",
                    "parent": "root",
                    "children": [],
                    "message": {
                        "id": "u",
                        "author": {"role": "user"},
                        "content": {"content_type": "text", "parts": ["x"]},
                        "metadata": {"attachments": attachments},
                        "recipient": "all",
                    },
                },
            },
        }

    def get_textdocs(self, cid):
        return []


class WorkingFileApi:
    def __init__(self, events=None):
        self.events = events if events is not None else []

    def metadata(self, file_id):
        self.events.append(f"file:{file_id}:metadata")
        return {"id": file_id, "name": f"{file_id}.txt", "mime_type": "text/plain", "file_extension": "txt"}

    def download_ticket(self, file_id, *, gizmo_id=None):
        self.events.append(f"file:{file_id}:ticket")
        return {"download_url": f"https://files.invalid/{file_id}", "file_name": f"{file_id}.txt", "file_size_bytes": 3}

    def download_bytes(self, signed_url):
        self.events.append("file:bytes")
        return b"abc"


def test_files_are_materialized_directly_after_each_conversation(tmp_path):
    events = []
    conv = AttachmentConversationApi(
        conversations=2,
        file_ids=["file_00000000000000000000000000000001", "file_00000000000000000000000000000002"],
        events=events,
    )
    files = WorkingFileApi(events)
    repo = RawRepository(tmp_path / "raw")
    messages = []
    orch = SyncOrchestrator(
        conversation_api=conv,
        file_api=files,
        repository=repo,
        fetch_files=True,
        max_errors_per_run=5,
        progress=messages.append,
    )
    result = orch.run()
    assert result["aborted"] is False
    # pre-5 kehrt zum urspruenglich geplanten Ablauf zurueck (Bauplan Abschnitt 18):
    # die Dateien einer Conversation werden unmittelbar nach ihr geladen, nicht
    # erst in einer zweiten Gesamtphase. Ein durch das Rate-Limit unterbrochener
    # Lauf hinterlaesst dadurch vollstaendige Datensaetze statt Conversations
    # ohne jede Datei.
    first_conv = events.index("conv:0") if "conv:0" in events else         next(i for i, e in enumerate(events) if e.startswith("conv:"))
    conv_positions = [i for i, e in enumerate(events) if e.startswith("conv:")]
    file_positions = [i for i, e in enumerate(events) if e.startswith("file:")]
    # Es muss mindestens eine Datei VOR der letzten Conversation geladen worden sein.
    assert min(file_positions) < max(conv_positions)
    assert result["stats"]["fetched"] == 2
    assert result["stats"]["files_materialized"] == 2


def test_file_queue_deduplicates_same_file_id_across_conversations(tmp_path):
    shared = "file_00000000000000000000000000000003"
    events = []
    conv = AttachmentConversationApi(conversations=2, file_ids=[shared, shared], events=events)
    files = WorkingFileApi(events)
    repo = RawRepository(tmp_path / "raw")
    result = SyncOrchestrator(
        conversation_api=conv,
        file_api=files,
        repository=repo,
        fetch_files=True,
    ).run()
    assert result["aborted"] is False
    # Die runweite Deduplizierung bleibt erhalten, obwohl es keine
    # Sammelphase mehr gibt: dieselbe Datei wird nur einmal geholt.
    assert sum(1 for e in events if e == f"file:{shared}:metadata") == 1
    assert result["stats"]["files_materialized"] == 1


def test_file_error_budget_aborts_without_one_extra_request(tmp_path):
    """Das Datei-Fehlerbudget stoppt den Lauf, ohne einen weiteren Request.

    Ab pre-5 hat die Dateischicht ein eigenes Budget. HTTP 404 zaehlt hier
    bewusst NICHT mehr mit (abgelaufene Anhaenge sind der Normalfall und
    haetten sonst jeden Lauf nach wenigen Chats beendet) -- deshalb prueft
    dieser Test mit HTTP 500.
    """
    from chatexporter.providers.chatgpt.api.client import ApiError

    file_ids = [f"file_{i:032x}" for i in range(1, 7)]
    conv = AttachmentConversationApi(conversations=1, file_ids=file_ids)

    class FailingFileApi:
        def __init__(self):
            self.calls = []
        def metadata(self, file_id):
            self.calls.append(file_id)
            raise ApiError(f"HTTP 500 for /backend-api/files/{file_id}", status=500, endpoint=f"/backend-api/files/{file_id}")

    files = FailingFileApi()
    repo = RawRepository(tmp_path / "raw")
    messages = []
    result = SyncOrchestrator(
        conversation_api=conv,
        file_api=files,
        repository=repo,
        fetch_files=True,
        max_errors_per_run=5,
        max_file_errors_per_run=5,
        progress=messages.append,
    ).run()
    assert result["aborted"] is True
    assert "error budget exhausted" in result["abort_reason"]
    assert len(files.calls) == 5
    assert result["stats"]["files_failed"] == 5
    assert len(result["stats"]["errors"]) == 5
    assert repo.get_path("c1") is not None


def test_closed_browser_transport_aborts_on_first_failure(tmp_path):
    from chatexporter.providers.chatgpt.api.client import ApiTransportClosedError

    file_ids = [f"file_{i:032x}" for i in range(10, 13)]
    conv = AttachmentConversationApi(conversations=1, file_ids=file_ids)

    class ClosedFileApi:
        def __init__(self):
            self.calls = 0
        def metadata(self, file_id):
            self.calls += 1
            raise ApiTransportClosedError("Browser-bound API request context was closed")

    files = ClosedFileApi()
    repo = RawRepository(tmp_path / "raw")
    result = SyncOrchestrator(
        conversation_api=conv,
        file_api=files,
        repository=repo,
        fetch_files=True,
        max_errors_per_run=5,
    ).run()
    assert result["aborted"] is True
    assert "request context is closed" in result["abort_reason"]
    assert files.calls == 1
    assert result["stats"]["files_failed"] == 1
    assert len(result["stats"]["errors"]) == 1
