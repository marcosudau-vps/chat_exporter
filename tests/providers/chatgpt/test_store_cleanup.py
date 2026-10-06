from __future__ import annotations

from chatexporter.providers.chatgpt.cli import main
from chatexporter.providers.chatgpt.fetch.conversation_fetcher import FetchedConversation
from chatexporter.providers.chatgpt.fetch.validator import validate_conversation_graph
from chatexporter.providers.chatgpt.storage.envelope import build_envelope
from chatexporter.providers.chatgpt.storage.raw_repository import RawRepository


def test_migrate_store_removes_empty_dirs_and_staging_leftovers(tmp_path):
    root = tmp_path / "raw"
    RawRepository(root)

    empty = root / "library" / "files" / "file_empty_legacy"
    empty.mkdir(parents=True, exist_ok=True)

    leftover = root / ".staging" / "leftover.tmp"
    leftover.parent.mkdir(parents=True, exist_ok=True)
    leftover.write_text("x", encoding="utf-8")

    rc = main(["--raw-root", str(root), "migrate-store"])
    assert rc == 0
    assert not empty.exists()
    assert not leftover.exists()


def test_migrate_store_normalizes_legacy_acquisition_fields(tmp_path, simple_raw, summary):
    root = tmp_path / "raw"
    repo = RawRepository(root)
    fetched = FetchedConversation(raw=simple_raw, textdocs=[], file_references=[],
                                  tool_references=[], validation=validate_conversation_graph(simple_raw),
                                  supplemental_errors=[])
    env = build_envelope(summary, fetched)
    # Altformat nachstellen: nur `complete`, kein `json_complete`/`source`
    del env["acquisition"]["json_complete"]
    del env["acquisition"]["source"]
    repo.commit(env)

    rc = main(["--raw-root", str(root), "migrate-store"])
    assert rc == 0

    migrated = repo.load("c1")
    assert migrated["acquisition"]["json_complete"] is True
    assert migrated["acquisition"]["source"] == "api"
