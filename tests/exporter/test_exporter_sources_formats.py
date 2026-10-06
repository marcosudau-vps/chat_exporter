"""Rohdaten lesen, neutrale Ansicht und Ausgabeformate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chatexporter.exporter.formats import FORMATS, build_formats, month_bucket, render_markdown
from chatexporter.exporter.sources import iter_items
from chatexporter.exporter.sources.chatgpt import (build_conversation_view, content_to_text,
                                                   current_path_nodes)


def envelope(simple_raw, summary):
    return {"conversation_id": "c1", "remote_summary": summary, "raw": simple_raw,
            "file_references": [], "textdocs": []}


def store(raw_root: Path, env: dict, day="2026/09/26") -> Path:
    path = raw_root / "chatgpt" / "conversations" / day / f"{env['conversation_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(env), encoding="utf-8")
    return path


# -- neutrale Ansicht ---------------------------------------------------------

def test_view_basic_fields(simple_raw, summary):
    view = build_conversation_view(envelope(simple_raw, summary))
    assert view["source"] == "chatgpt" and view["conversation_id"] == "c1" and view["title"] == "Hello"
    assert [m["role"] for m in view["messages"]] == ["user", "assistant", "assistant"]
    assert [m["text"] for m in view["messages"]] == ["Hi", "Hello", "Short visible recap"]
    assert view["is_archived"] is False and view["is_starred"] is False


def test_view_keeps_reasoning_recap_but_not_thoughts(simple_raw, summary):
    simple_raw["mapping"]["u1"]["message"]["content"] = {
        "content_type": "thoughts", "parts": ["<REDACTED_INTERNAL_REASONING>"]}
    texts = [m["text"] for m in build_conversation_view(envelope(simple_raw, summary))["messages"]]
    assert "Short visible recap" in texts
    assert "<REDACTED_INTERNAL_REASONING>" not in texts


def test_current_path_selected_and_branches_ignored(simple_raw):
    simple_raw["mapping"]["u1"]["children"] = ["a1", "alt"]
    simple_raw["mapping"]["alt"] = {"id": "alt", "parent": "u1", "children": [], "message": {
        "id": "alt", "author": {"role": "assistant"}, "content": {"content_type": "text", "parts": ["alternate"]},
        "metadata": {}}}
    assert [n["id"] for n in current_path_nodes(simple_raw)] == ["root", "u1", "a1", "a2"]


def test_current_path_handles_broken_graphs(simple_raw):
    simple_raw["current_node"] = "missing"
    assert current_path_nodes(simple_raw) == []
    assert current_path_nodes({}) == []
    simple_raw["current_node"] = "a2"
    simple_raw["mapping"]["root"]["parent"] = "a2"          # Zyklus
    assert len(current_path_nodes(simple_raw)) == 4


def test_content_to_text_variants():
    assert content_to_text({"content_type": "text", "parts": ["a", "", {"text": "b"}]}) == "a\nb"
    assert content_to_text({"content_type": "text", "text": "direkt"}) == "direkt"
    assert content_to_text({"content_type": "thoughts", "parts": ["x"]}) == ""
    assert content_to_text({"parts": [{"asset_pointer": "sediment://file_1?x=2"}]}) == "[Image: file_1]"
    assert content_to_text({"parts": [{"content_type": "audio_transcription"}]}) == "[audio_transcription]"
    assert content_to_text(None) == ""
    assert content_to_text("roh") == "roh"


# -- Rohdaten lesen --------------------------------------------------------------

def test_iter_items_reads_envelopes_sorted(tmp_path, simple_raw, summary):
    second = envelope(dict(simple_raw), summary) | {"conversation_id": "a0"}
    store(tmp_path, envelope(simple_raw, summary))
    store(tmp_path, second, day="2026/01/02")
    items = list(iter_items("chatgpt", tmp_path))
    assert [i.path.stem for i in items] == ["a0", "c1"]
    assert all(i.view is not None and i.error is None for i in items)
    assert items[0].item_id == "a0"


def test_iter_items_reports_unreadable_files_without_stopping(tmp_path, simple_raw, summary):
    store(tmp_path, envelope(simple_raw, summary))
    broken = tmp_path / "chatgpt" / "conversations" / "2026" / "kaputt.json"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_text("{nicht json", encoding="utf-8")
    other = tmp_path / "chatgpt" / "conversations" / "2026" / "fremd.json"
    other.write_text(json.dumps({"hallo": 1}), encoding="utf-8")
    items = {i.path.stem: i for i in iter_items("chatgpt", tmp_path)}
    assert items["c1"].view is not None
    assert "nicht lesbar" in items["kaputt"].error and items["kaputt"].view is None
    assert "raw" in items["fremd"].error


def test_iter_items_without_data_is_empty(tmp_path):
    assert list(iter_items("chatgpt", tmp_path)) == []


def test_unknown_source_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Quelle"):
        iter_items("gibtesnicht", tmp_path)


# -- Formate -----------------------------------------------------------------------

def test_month_bucket():
    assert month_bucket(1789700000.0) == "2026-09"
    assert month_bucket("2026-01-15T10:00:00Z") == "2026-01"
    assert month_bucket(None) == "unknown" and month_bucket("kein datum") == "unknown"


def test_markdown_rendering(simple_raw, summary):
    view = build_conversation_view(envelope(simple_raw, summary))
    view["messages"][0]["attachments"] = [{"name": "a.txt"}, "ignoriert"]
    view["messages"][1]["recipient"] = "browser"
    text = render_markdown(view)
    assert text.startswith("# Hello\n")
    assert "- Conversation ID: `c1`" in text
    assert "## USER" in text and "## ASSISTANT → browser" in text
    assert "- Attachment: `a.txt`" in text
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_markdown_marks_empty_messages(simple_raw, summary):
    simple_raw["mapping"]["a1"]["message"]["content"] = {"content_type": "code", "parts": []}
    text = render_markdown(build_conversation_view(envelope(simple_raw, summary)))
    assert "_[code]_" in text


def test_formats_write_to_month_folders(tmp_path, simple_raw, summary):
    view = build_conversation_view(envelope(simple_raw, summary))
    md = FORMATS["markdown"].export(tmp_path, view)
    js = FORMATS["json"].export(tmp_path, view)
    assert md == tmp_path / "markdown" / "chatgpt" / "2026-09" / "c1.md"
    assert js == tmp_path / "json" / "chatgpt" / "2026-09" / "c1.json"
    assert "# Hello" in md.read_text(encoding="utf-8")
    assert json.loads(js.read_text(encoding="utf-8"))["conversation_id"] == "c1"
    assert not list((tmp_path).rglob("*.tmp")), "keine Reste im Zielordner"


def test_build_formats():
    assert [f.name for f in build_formats(["JSON", " markdown "])] == ["json", "markdown"]
    with pytest.raises(ValueError, match="Exportformat"):
        build_formats(["pdf"])
