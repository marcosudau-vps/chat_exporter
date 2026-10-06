"""Export aller Quellen (OpenCode, Codex, Claude) und die Befehle ``export json`` / ``export md``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chatexporter.exporter import cli
from chatexporter.exporter.formats import render_markdown
from chatexporter.exporter.sources import iter_items

MS = 1789700000000   # 2026-09 in Millisekunden


def _opencode(raw: Path) -> Path:
    path = raw / "opencode" / "sessions" / "2026" / "09" / "26" / "ses_1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "info": {"id": "ses_1", "title": "OpenCode-Titel", "time": {"created": MS, "updated": MS + 5000},
                 "agent": "build", "location": {"directory": "P:/Projekt"}},
        "messages": [
            {"id": "m1", "time": {"created": MS}, "text": "Frage?"},
            {"id": "m2", "time": {"created": MS + 1}, "type": "assistant", "model": {"id": "modell-x"},
             "content": [{"type": "reasoning", "text": "intern"}, {"type": "tool", "name": "read"},
                         {"type": "text", "text": "Antwort."}]},
            {"id": "m3", "type": "idle", "time": {"created": MS + 2}},
            {"id": "m4", "type": "system", "text": "System", "time": {"created": MS + 3}},
            {"id": "m5", "metadata": {"displayText": "Nur Anzeige"}, "time": {"created": MS + 4}},
        ]}), encoding="utf-8")
    return path


def _jsonl(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _codex(raw: Path) -> Path:
    return _jsonl(raw / "codex" / "sessions" / "2026" / "09" / "26" / "rollout-x.jsonl", [
        {"timestamp": "2026-09-26T10:00:00Z", "type": "session_meta",
         "payload": {"id": "sess-codex", "timestamp": "2026-09-26T10:00:00Z", "cwd": "C:/repo"}},
        {"timestamp": "2026-09-26T10:00:01Z", "type": "response_item",
         "payload": {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": "Vorgabe"}]}},
        {"timestamp": "2026-09-26T10:00:02Z", "type": "response_item",
         "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Baue X\nDetails"}]}},
        {"timestamp": "2026-09-26T10:00:03Z", "type": "response_item", "payload": {"type": "reasoning", "summary": []}},
        {"timestamp": "2026-09-26T10:00:04Z", "type": "response_item",
         "payload": {"type": "function_call", "name": "shell"}},
        {"timestamp": "2026-09-26T10:00:05Z", "type": "response_item",
         "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Fertig."}]}},
        {"timestamp": "2026-09-26T10:05:00Z", "type": "event_msg", "payload": {"type": "task_complete"}},
    ])


def _claude(raw: Path) -> Path:
    project = raw / "claude" / "projects" / "C--repo"
    (project / "memory").mkdir(parents=True, exist_ok=True)
    (project / "memory" / "MEMORY.md").write_text("keine Sitzung", encoding="utf-8")
    _jsonl(project / "sess-claude" / "subagents" / "agent-1.jsonl", [{"type": "user", "message": {"content": "x"}}])
    return _jsonl(project / "sess-claude.jsonl", [
        {"type": "user", "sessionId": "sess-claude", "timestamp": "2026-09-26T08:00:00Z", "cwd": "C:/repo",
         "uuid": "u1", "message": {"role": "user", "content": "Hallo Claude"}},
        {"type": "assistant", "timestamp": "2026-09-26T08:00:05Z", "uuid": "a1",
         "message": {"role": "assistant", "model": "claude-x",
                     "content": [{"type": "thinking", "thinking": "intern"}, {"type": "tool_use", "name": "Bash"},
                                 {"type": "text", "text": "Hallo zurueck"}]}},
        {"type": "user", "timestamp": "2026-09-26T08:00:06Z", "uuid": "u2",
         "message": {"role": "user", "content": [{"type": "tool_result", "content": "ausgabe"}]}},
        {"type": "assistant", "isSidechain": True, "timestamp": "2026-09-26T08:00:07Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "Nebenzweig"}]}},
        {"type": "custom-title", "customTitle": "Eigener Titel", "sessionId": "sess-claude"},
        {"type": "summary", "timestamp": "2026-09-26T09:00:00Z"},
    ])


def test_opencode_view(tmp_path):
    _opencode(tmp_path)
    [item] = list(iter_items("opencode", tmp_path))
    view = item.view
    assert view["source"] == "opencode" and view["conversation_id"] == "ses_1"
    assert view["title"] == "OpenCode-Titel" and view["create_time"] == MS / 1000
    assert [(m["role"], m["text"]) for m in view["messages"]] == \
        [("user", "Frage?"), ("assistant", "Antwort."), ("user", "Nur Anzeige")]
    assert view["messages"][1]["author_name"] == "modell-x"
    assert view["is_archived"] is None and view["meta"]["directory"] == "P:/Projekt"


def test_codex_view(tmp_path):
    _codex(tmp_path)
    [item] = list(iter_items("codex", tmp_path))
    view = item.view
    assert view["conversation_id"] == "sess-codex" and view["title"] == "Baue X"
    assert [(m["role"], m["text"]) for m in view["messages"]] == \
        [("user", "Baue X\nDetails"), ("assistant", "Fertig.")]
    assert view["update_time"] > view["create_time"] and view["meta"]["cwd"] == "C:/repo"


def test_claude_view_skips_subagents_notes_tools_and_sidechains(tmp_path):
    _claude(tmp_path)
    items = list(iter_items("claude", tmp_path))
    assert [i.path.name for i in items] == ["sess-claude.jsonl"]
    view = items[0].view
    assert view["title"] == "Eigener Titel" and view["conversation_id"] == "sess-claude"
    assert [(m["role"], m["text"]) for m in view["messages"]] == \
        [("user", "Hallo Claude"), ("assistant", "Hallo zurueck")]
    assert view["meta"] == {"project": "C--repo", "cwd": "C:/repo"}


def test_unreadable_jsonl_is_reported(tmp_path):
    path = tmp_path / "codex" / "sessions" / "kaputt.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"ok": 1}\n{kaputt\n', encoding="utf-8")
    [item] = list(iter_items("codex", tmp_path))
    assert item.view is None and "Zeile 2" in item.error


def test_markdown_without_archive_flags_shows_source_and_meta(tmp_path):
    _claude(tmp_path)
    text = render_markdown(next(iter_items("claude", tmp_path)).view)
    assert "- Source: `claude`" in text and "- cwd: `C:/repo`" in text
    assert "Archived" not in text and "## ASSISTANT" in text


@pytest.fixture
def workspace(tmp_path, simple_raw, summary):
    raw = tmp_path / "data" / "raw_storage"
    chatgpt = raw / "chatgpt" / "conversations" / "2026" / "09" / "26" / "c1.json"
    chatgpt.parent.mkdir(parents=True)
    chatgpt.write_text(json.dumps({"conversation_id": "c1", "remote_summary": summary, "raw": simple_raw}),
                       encoding="utf-8")
    _opencode(raw), _codex(raw), _claude(raw)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"storage:\n  data_root: {(tmp_path / 'data').as_posix()}\n", encoding="utf-8")
    return tmp_path, cfg


def test_export_covers_all_sources_by_default(workspace, capsys):
    tmp, cfg = workspace
    assert cli.main(["--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    report = json.loads(out[out.index("{"):])
    assert report["sources"] == ["chatgpt", "opencode", "codex", "claude"]
    assert report["conversations"] == 4 and report["files_written"] == 8
    exports = tmp / "data" / "exports"
    assert {p.parent.parent.name for p in (exports / "markdown").rglob("*.md")} == \
        {"chatgpt", "opencode", "codex", "claude"}


@pytest.mark.parametrize("what,present,absent", [("json", "json", "markdown"), ("md", "markdown", "json"),
                                                  ("markdown", "markdown", "json")])
def test_export_json_and_md_commands(workspace, capsys, what, present, absent):
    tmp, cfg = workspace
    assert cli.main([what, "--config", str(cfg)]) == 0
    exports = tmp / "data" / "exports"
    assert len(list((exports / present).rglob("*.*"))) == 4
    assert not (exports / absent).exists()


def test_export_all_and_source_filter(workspace, capsys):
    tmp, cfg = workspace
    assert cli.main(["all", "--source", "codex", "--config", str(cfg)]) == 0
    exports = tmp / "data" / "exports"
    assert [p.name for p in (exports / "json").rglob("*.json")] == ["sess-codex.json"]
    assert [p.name for p in (exports / "markdown").rglob("*.md")] == ["sess-codex.md"]


def test_export_through_the_main_command(workspace, capsys):
    from chatexporter.cli import main as main_mod
    tmp, cfg = workspace
    from chatexporter.config.storage import Storage, new_identity, write_identity
    storage = Storage(tmp / "data")
    write_identity(storage, new_identity(storage))     # Bestand ist ein Storage (Marker)
    assert main_mod.main(["--config", str(cfg), "export", "md", "--source", "opencode"]) == 0
    assert not (storage.staging / "exports").exists(), "leere Zwischenablage wird entfernt"
    assert [p.name for p in (tmp / "data" / "exports" / "markdown").rglob("*.md")] == ["ses_1.md"]
