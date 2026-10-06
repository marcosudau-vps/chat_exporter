from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from chatexporter.providers.chatgpt.common.hashing import sha256_bytes
from chatexporter.providers.chatgpt.fetch.conversation_fetcher import FetchedConversation
from chatexporter.providers.chatgpt.fetch.validator import validate_conversation_graph
from chatexporter.providers.chatgpt.storage.envelope import build_envelope
from chatexporter.providers.chatgpt.storage.library import LibraryStore
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository
from chatexporter.providers.chatgpt.storage.status_store import FileStatusStore, rebuild_file_index, resolve_status_root

def _load_runner():
    from chatexporter.providers.chatgpt.storage import scenarios
    return scenarios


def _raw(cid: str):
    return {
        "conversation_id": cid,
        "title": cid,
        "current_node": "a1",
        "mapping": {
            "root": {"id": "root", "message": None, "parent": None, "children": ["u1"]},
            "u1": {"id": "u1", "parent": "root", "children": ["a1"], "message": {
                "id": "u1", "author": {"role": "user"}, "create_time": 1,
                "content": {"content_type": "text", "parts": ["hi"]}, "metadata": {}, "recipient": "all"}},
            "a1": {"id": "a1", "parent": "u1", "children": [], "message": {
                "id": "a1", "author": {"role": "assistant"}, "create_time": 2,
                "content": {"content_type": "text", "parts": ["yo"]}, "metadata": {}, "recipient": "all"}},
        },
    }


def _ref(fid: str):
    return {"id": fid, "kind": "attachment", "node_id": "a1", "message_id": "a1", "size": 5}


def _envelope(cid: str, refs, library):
    raw = _raw(cid)
    summary = {"id": cid, "title": cid, "create_time": 1789700000.0, "update_time": 1789700100.0,
               "is_archived": False, "is_starred": False, "pinned_time": None, "gizmo_id": None}
    fetched = FetchedConversation(raw=raw, textdocs=[], file_references=refs, tool_references=[],
                                  validation=validate_conversation_graph(raw), supplemental_errors=[])
    return build_envelope(summary, fetched, library=library)


def _build_store(tmp_path: Path) -> Path:
    root = tmp_path / "raw"
    repo = RawRepository(root)
    library = LibraryStore(root)

    d = root / "library" / "files" / "file_aaa"
    d.mkdir(parents=True, exist_ok=True)
    (d / "content.txt").write_bytes(b"hello")
    (d / "metadata.json").write_text(json.dumps({
        "schema_version": 1, "file_id": "file_aaa", "content_file": "content.txt",
        "content_sha256": sha256_bytes(b"hello"), "size": 5,
        "_local": {"conversation_id": "c1", "message_id": "a1", "node_id": "a1",
                   "references": [{"conversation_id": "c1", "message_id": "a1", "node_id": "a1"}]},
    }), encoding="utf-8")

    status = FileStatusStore(resolve_status_root(root))
    status.mark_unavailable("file_bbb", status=404, detail="gone", ref=_ref("file_bbb"), conversation_id="c2")

    repo.commit(_envelope("c1", [_ref("file_aaa")], library))
    repo.commit(_envelope("c2", [_ref("file_bbb")], library))
    rebuild_file_index(repo, repo.index.status_root)
    return root


def test_scenario_runner_all_pass_on_healthy_store(tmp_path):
    root = _build_store(tmp_path)
    runner = _load_runner()
    assert runner.run_scenarios(root, None) == 0
