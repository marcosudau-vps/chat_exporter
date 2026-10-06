"""Import eines Kontodatensatzes.

Wichtigste Eigenschaft: importierte Datensaetze muessen als unvollstaendig
erkennbar bleiben und vom Planner automatisch fuer den vollstaendigen
API-Abruf eingeplant werden.
"""
from __future__ import annotations

import json

from chatexporter.providers.chatgpt.importing import ImportedDataConverter, reconstruct_children
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.sync.models import SyncAction
from chatexporter.providers.chatgpt.sync.planner import build_plan


def _imported_conversation(cid: str, *, with_file: bool = False) -> dict:
    parts = ["hallo"]
    if with_file:
        parts = [{"content_type": "image_asset_pointer",
                   "asset_pointer": "sediment://file_img001"}]
    return {
        "conversation_id": cid, "id": cid, "title": "Ein Chat",
        "create_time": 1700000000.0, "update_time": 1700000100.0,
        "is_archived": False, "is_starred": None, "pinned_time": None,
        "current_node": "n2",
        # Wie im echten Datensatz: KEIN children-Feld.
        "mapping": {
            "n1": {"id": "n1", "message": None, "parent": None},
            "n2": {"id": "n2", "parent": "n1", "message": {
                "id": "m1", "author": {"role": "user"},
                "content": {"content_type": "multimodal_text" if with_file else "text",
                             "parts": parts},
                "create_time": 1700000050.0}},
        },
    }


def _write_source(tmp_path, convs, *, file_bytes: bytes | None = None):
    src = tmp_path / "2026_06_19_quelle"
    src.mkdir(parents=True, exist_ok=True)
    (src / "conversations-000.json").write_text(json.dumps(convs), encoding="utf-8")
    if file_bytes is not None:
        (src / "file_img001.dat").write_bytes(file_bytes)
        (src / "conversation_asset_file_names.json").write_text(
            json.dumps({"file_img001.dat": "bild.png"}), encoding="utf-8")
    return src


def test_children_are_reconstructed_deterministically():
    mapping = {
        "root": {"id": "root", "parent": None, "message": None},
        "b": {"id": "b", "parent": "root", "message": {"create_time": 20.0}},
        "a": {"id": "a", "parent": "root", "message": {"create_time": 10.0}},
    }
    out, count = reconstruct_children(mapping)
    assert count == 2
    # Nach create_time sortiert, nicht nach Einfuegereihenfolge.
    assert out["root"]["children"] == ["a", "b"]
    assert out["a"]["children"] == []


def test_import_marks_records_as_incomplete(tmp_path):
    src = _write_source(tmp_path, [_imported_conversation("c1")])
    raw_root = tmp_path / "raw"
    report = ImportedDataConverter(src, raw_root).run()
    assert report.conversations_written == 1

    envelope = json.loads(next((raw_root / "conversations").rglob("*.json")).read_text(encoding="utf-8"))
    acq = envelope["acquisition"]
    assert acq["complete"] is False
    assert acq["json_complete"] is False
    assert acq["source"] == "imported_data"
    assert acq["imported_data"]["completeness_class"] == "reduced_import"
    assert "tool_nodes" in acq["imported_data"]["known_omissions"]
    # children wurden ergaenzt, obwohl die Quelle sie nicht hatte
    assert envelope["raw"]["mapping"]["n1"]["children"] == ["n2"]


def test_planner_schedules_imported_records_for_full_fetch(tmp_path):
    src = _write_source(tmp_path, [_imported_conversation("c1")])
    raw_root = tmp_path / "raw"
    ImportedDataConverter(src, raw_root).run()

    repo = RawRepository(raw_root)
    assert repo.index.conversations["c1"]["acquisition_source"] == "imported_data"
    assert repo.index.conversations["c1"]["fetch_complete"] is False

    remote = {"c1": {"id": "c1", "title": "Ein Chat", "create_time": 1700000000.0,
                      "update_time": 1700000100.0, "is_archived": False,
                      "is_starred": None, "pinned_time": None}}
    plan = build_plan(remote, repo.index.conversations)
    assert plan[0].action == SyncAction.FETCH_FULL


def test_import_materializes_available_files(tmp_path):
    src = _write_source(tmp_path, [_imported_conversation("c1", with_file=True)],
                         file_bytes=b"PNGDATA")
    raw_root = tmp_path / "raw"
    report = ImportedDataConverter(src, raw_root).run()
    assert report.files_materialized == 1
    content = raw_root / "library" / "files" / "file_img001" / "content.png"
    assert content.read_bytes() == b"PNGDATA"
    meta = json.loads((content.parent / "metadata.json").read_text(encoding="utf-8"))
    assert meta["source"] == "imported_data"
    assert meta["bucket"] == "files"


def test_missing_file_is_reported_not_fatal(tmp_path):
    src = _write_source(tmp_path, [_imported_conversation("c1", with_file=True)])
    report = ImportedDataConverter(src, tmp_path / "raw").run()
    assert report.conversations_written == 1
    assert report.files_referenced_but_absent == 1
    assert "file_img001" in report.referenced_absent_sample


def test_existing_records_are_not_overwritten_by_default(tmp_path):
    src = _write_source(tmp_path, [_imported_conversation("c1")])
    raw_root = tmp_path / "raw"
    ImportedDataConverter(src, raw_root).run()
    second = ImportedDataConverter(src, raw_root).run()
    assert second.conversations_written == 0
    assert second.conversations_skipped_existing == 1


def test_index_rebuild_is_triggered(tmp_path):
    src = _write_source(tmp_path, [_imported_conversation("c1")])
    raw_root = tmp_path / "raw"
    ImportedDataConverter(src, raw_root).run()
    assert (raw_root / ".staging" / "index_dirty").exists()
