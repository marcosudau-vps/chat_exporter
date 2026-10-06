"""Codex-CLI-Rohdaten (``raw_storage/codex/sessions/**/rollout-*.jsonl``) zur neutralen Ansicht.

Eine Datei ist eine Sitzung (JSON Lines). Exportiert werden die Nachrichten mit
der Rolle ``user`` und ``assistant`` (``response_item`` vom Typ ``message``).
Entwickler-/Systemvorgaben, Denkinhalte (``reasoning``) und Werkzeugaufrufe
gehoeren nicht zur lesbaren Unterhaltung.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import ExportItem

SOURCE = "codex"
ROLES = ("user", "assistant")


def _seconds(value: Any) -> float | None:
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    texts = [item.get("text", "") for item in content
             if isinstance(item, dict) and item.get("type") in ("input_text", "output_text", "text")]
    return "\n\n".join(t.strip() for t in texts if isinstance(t, str) and t.strip())


def _title(messages: list[dict[str, Any]], fallback: str) -> str:
    for message in messages:
        if message["role"] == "user":
            first = message["text"].strip().splitlines()[0] if message["text"].strip() else ""
            if first:
                return first[:100]
    return fallback


def build_view(rows: list[dict[str, Any]], path: Path) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    messages: list[dict[str, Any]] = []
    last_time = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        last_time = row.get("timestamp") or last_time
        if row.get("type") == "session_meta" and not meta:
            meta = payload
            continue
        if row.get("type") != "response_item" or payload.get("type") != "message":
            continue
        role = payload.get("role")
        if role not in ROLES:
            continue
        text = _text(payload.get("content"))
        if not text:
            continue
        messages.append({
            "id": payload.get("id"),
            "role": role,
            "author_name": None,
            "recipient": None,
            "content_type": "text",
            "text": text,
            "create_time": _seconds(row.get("timestamp")),
            "attachments": [],
        })
    session_id = meta.get("id") or meta.get("session_id") or path.stem
    created = _seconds(meta.get("timestamp")) or (messages[0]["create_time"] if messages else None)
    return {
        "schema_version": 1,
        "source": SOURCE,
        "conversation_id": str(session_id),
        "title": _title(messages, path.stem),
        "create_time": created,
        "update_time": _seconds(last_time),
        "is_archived": None,
        "is_starred": None,
        "messages": messages,
        "file_references": [],
        "textdocs": [],
        "meta": {"cwd": meta.get("cwd"), "originator": meta.get("originator"),
                 "cli_version": meta.get("cli_version")},
    }


def read_rows(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except ValueError as exc:
                    raise ValueError(f"Zeile {number}: {exc}") from None
    return rows


def iter_items(raw_root: Path) -> Iterator[ExportItem]:
    folder = Path(raw_root) / SOURCE / "sessions"
    if not folder.is_dir():
        return
    for path in sorted(folder.rglob("*.jsonl")):
        try:
            rows = read_rows(path)
        except (OSError, ValueError) as exc:
            yield ExportItem(SOURCE, path, error=f"nicht lesbar: {exc}")
            continue
        yield ExportItem(SOURCE, path, view=build_view(rows, path))
