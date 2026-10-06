"""Haertungstests: Verhalten unter realen Stoerungen.

Diese Tests beschreiben Situationen, die im Dauerbetrieb sicher auftreten
werden -- abgelaufene Dateien, Abbruch mitten im Lauf, Unterbrechung durch
den Nutzer. Sie sind bewusst als Verhaltensvertrag formuliert.
"""
from __future__ import annotations

import json

from chatexporter.providers.chatgpt.api.client import ApiError
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.sync.orchestrator import SyncOrchestrator


def _summary(cid: str) -> dict:
    return {"id": cid, "title": f"T {cid}", "create_time": 1.0, "update_time": 2.0,
            "is_archived": False, "is_starred": None, "pinned_time": None}


def _conversation_with_files(cid: str, file_ids: list[str]) -> dict:
    parts = [{"content_type": "image_asset_pointer",
               "asset_pointer": f"sediment://{fid}"} for fid in file_ids]
    return {"conversation_id": cid, "current_node": "n1",
            "mapping": {"n1": {"id": "n1", "parent": None, "children": [], "message": {
                "id": "m1", "author": {"role": "user"},
                "content": {"content_type": "multimodal_text", "parts": parts},
                "create_time": 1.0}}}}


class ConversationsWithFiles:
    def __init__(self, count: int, files_per_conversation: int):
        self.count = count
        self.files_per_conversation = files_per_conversation

    def iter_scope(self, *, archived: bool, limit: int = 100):
        if archived:
            return
        for i in range(self.count):
            yield _summary(f"c{i}")

    def get_conversation(self, conversation_id: str):
        idx = int(conversation_id[1:])
        ids = [f"file_{idx:02d}{j:030d}" for j in range(self.files_per_conversation)]
        return _conversation_with_files(conversation_id, ids)

    def get_textdocs(self, conversation_id: str):
        return []


class ExpiredFileApi:
    """Alle Dateien sind abgelaufen -- der reale Normalfall bei alten Chats."""

    def __init__(self):
        self.calls = 0

    def metadata(self, file_id: str):
        self.calls += 1
        raise ApiError(f"HTTP 404 for /backend-api/files/{file_id}",
                        status=404, endpoint="/backend-api/files/<id>",
                        payload={"detail": "File not found"})

    def download_ticket(self, file_id, *, gizmo_id=None): raise AssertionError("nicht erreichbar")
    def download_bytes(self, url): raise AssertionError("nicht erreichbar")


def test_expired_files_do_not_kill_the_run(tmp_path):
    """Abgelaufene Dateien sind normal und duerfen einen Lauf nicht beenden.

    Gemessen: von 1017 lokal referenzierten Datei-IDs lagen nur 12 % im
    Kontodatensatz vor -- ein erheblicher Teil ist serverseitig abgelaufen
    und liefert HTTP 404. Wuerden diese gegen das API-Fehlerbudget zaehlen,
    waere ein Lauf mit aktivierten Dateien nach wenigen Conversations
    beendet, obwohl die Conversations selbst einwandfrei laden.
    """
    conv = ConversationsWithFiles(count=10, files_per_conversation=3)
    repo = RawRepository(tmp_path / "raw")
    result = SyncOrchestrator(
        conversation_api=conv, file_api=ExpiredFileApi(), repository=repo,
        fetch_files=True, max_errors_per_run=5,
    ).run()

    assert result["aborted"] is False, (
        "Abgelaufene Dateien duerfen den Lauf nicht abbrechen")
    assert result["stats"]["fetched"] == 10, (
        "alle Conversations muessen trotz fehlender Dateien gespeichert werden")
    # HTTP 404 ist eine endgueltige Antwort, keine Stoerung: es zaehlt als
    # "nicht mehr verfuegbar" und nicht gegen ein Fehlerbudget.
    assert result["stats"]["files_unavailable"] == 30
    assert result["stats"]["files_failed"] == 0
    assert result["error_budget"]["api_errors_seen"] == 0


def test_conversation_is_committed_even_if_its_files_fail(tmp_path):
    """Bauplan Abschnitt 18: eine nicht verfuegbare Datei darf die
    Conversation nicht verwerfen."""
    conv = ConversationsWithFiles(count=1, files_per_conversation=2)
    repo = RawRepository(tmp_path / "raw")
    result = SyncOrchestrator(
        conversation_api=conv, file_api=ExpiredFileApi(), repository=repo,
        fetch_files=True,
    ).run()
    assert result["stats"]["fetched"] == 1
    envelope = repo.load("c0")
    assert envelope is not None
    assert envelope["acquisition"]["json_complete"] is True
    # Alle Anhaenge sind serverseitig endgueltig weg. Damit ist die Dateiebene
    # abschliessend geklaert -- es gibt nichts mehr zu holen. Wuerde sie
    # dauerhaft als unvollstaendig gelten, kaeme die Conversation bei JEDEM
    # Lauf erneut in den Plan, ohne jede Aussicht auf Erfolg.
    assert envelope["acquisition"]["files_complete"] is True
    # Nachvollziehbar bleibt es trotzdem: der Index weist die Zahl aus.
    fresh = RawRepository(tmp_path / "raw")
    assert fresh.index.conversations["c0"]["file_unavailable_count"] == 2
    assert fresh.index.conversations["c0"]["file_materialized_count"] == 0


def test_index_stays_consistent_after_completeness_refresh(tmp_path):
    """Nach dem Nachziehen von files_complete muss der Index zum Envelope passen."""
    conv = ConversationsWithFiles(count=1, files_per_conversation=1)
    repo = RawRepository(tmp_path / "raw")
    SyncOrchestrator(conversation_api=conv, file_api=ExpiredFileApi(),
                      repository=repo, fetch_files=True).run()

    fresh = RawRepository(tmp_path / "raw")
    entry = fresh.index.conversations["c0"]
    envelope = fresh.load("c0")
    assert entry["files_complete"] == envelope["acquisition"]["files_complete"]
    assert entry["json_complete"] == envelope["acquisition"]["json_complete"]
    assert entry["raw_integrity_ok"] is True, (
        "das Nachziehen darf den raw-Hash nicht ungueltig machen")


def test_keyboard_interrupt_still_writes_run_manifest(tmp_path):
    """Im Wartemodus laeuft ein Lauf stundenlang -- ein Abbruch durch den
    Nutzer ist der Normalfall und muss einen auswertbaren Bericht
    hinterlassen."""
    class InterruptingApi(ConversationsWithFiles):
        def get_conversation(self, conversation_id):
            if conversation_id == "c3":
                raise KeyboardInterrupt()
            return super().get_conversation(conversation_id)

    conv = InterruptingApi(count=10, files_per_conversation=0)
    repo = RawRepository(tmp_path / "raw")
    result = SyncOrchestrator(
        conversation_api=conv, file_api=ExpiredFileApi(), repository=repo,
        fetch_files=False,
    ).run()

    assert result["aborted"] is True
    assert result["abort_stage"] == "interrupted"
    assert result["stats"]["fetched"] == 3, "bereits geholte Daten bleiben erhalten"
    run_files = list((tmp_path / "raw" / "runs").glob("*.json"))
    assert len(run_files) == 1, "auch bei Abbruch muss ein Run-Manifest entstehen"
    manifest = json.loads(run_files[0].read_text(encoding="utf-8"))
    assert manifest["aborted"] is True


def test_quarantine_review_is_capped_per_run(tmp_path):
    """Jeder Review-Versuch ist ein echter Request. Bei vielen faelligen
    Eintraegen darf das nicht das Budget des Laufs aufzehren."""
    from chatexporter.providers.chatgpt.config.models import QuarantineConfig
    from chatexporter.providers.chatgpt.storage.quarantine import QuarantineStore

    store = QuarantineStore(tmp_path / "raw", QuarantineConfig(enabled=True))
    for i in range(20):
        store.data["conversations"][f"old{i}"] = {
            "quarantined": True, "review_after": "2000-01-01T00:00:00Z",
            "signature": "500|x", "failed_runs": ["a", "b", "c"],
        }

    attempted: list[str] = []

    class CountingApi(ConversationsWithFiles):
        def get_conversation(self, conversation_id):
            if conversation_id.startswith("old"):
                attempted.append(conversation_id)
                raise ApiError("HTTP 500", status=500, endpoint="/e",
                                payload={"detail": "Request timeout"})
            return super().get_conversation(conversation_id)

    repo = RawRepository(tmp_path / "raw")
    SyncOrchestrator(
        conversation_api=CountingApi(count=1, files_per_conversation=0),
        file_api=ExpiredFileApi(), repository=repo, fetch_files=False, quarantine=store,
    ).run()

    assert len(attempted) <= 3, (
        "hoechstens eine kleine feste Zahl an Review-Versuchen je Lauf, "
        f"tatsaechlich {len(attempted)}")


def test_index_from_older_version_is_rebuilt(tmp_path):
    """Ein Index einer aelteren Version darf nicht stillschweigend
    weiterverwendet werden.

    Realer Fall beim Wechsel pre-4 -> pre-5: der Index enthielt keines der
    neuen Felder. Der Planner haette `files_complete` ueberall auf den
    Default True gelesen und Conversations mit offenen Dateien nie
    eingeplant -- eine stille Luecke ohne jede Meldung.
    """
    conv = ConversationsWithFiles(count=2, files_per_conversation=0)
    repo = RawRepository(tmp_path / "raw")
    SyncOrchestrator(conversation_api=conv, file_api=ExpiredFileApi(),
                      repository=repo, fetch_files=False).run()

    index_path = tmp_path / "raw" / "storage_index.json"
    data = json.loads(index_path.read_text(encoding="utf-8"))
    # Zustand einer aelteren Version nachstellen: neue Felder entfernen,
    # Schemaversion bleibt gueltig.
    for entry in data["conversations"].values():
        for field in ("json_complete", "files_complete", "acquisition_source",
                      "file_unavailable_count"):
            entry.pop(field, None)
    index_path.write_text(json.dumps(data), encoding="utf-8")

    fresh = RawRepository(tmp_path / "raw")
    for entry in fresh.index.conversations.values():
        assert "files_complete" in entry, "veralteter Index muss neu gebaut werden"
        assert "acquisition_source" in entry
