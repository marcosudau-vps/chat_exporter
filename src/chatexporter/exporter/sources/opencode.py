"""OpenCode-Rohdaten (``raw_storage/opencode/sessions/**/<id>.json``) zur neutralen Ansicht.

Exportiert werden Benutzer- und Assistententexte. Interne Denkinhalte
(``reasoning``), Werkzeugaufrufe und Verwaltungsnachrichten (``idle``,
``model-switched``, ``system``, ``synthetic``, ``compaction``) gehoeren nicht
zur lesbaren Unterhaltung.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from . import ExportItem

SOURCE = "opencode"
SKIPPED_TYPES = {"idle", "model-switched", "system", "synthetic", "compaction"}


def _seconds(value: Any) -> float | None:
    """OpenCode zaehlt in Millisekunden."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value / 1000 if value > 10**11 else float(value)
    return None


def _user_text(message: dict[str, Any]) -> str:
    text = message.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    meta = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    shown = meta.get("displayText")
    return shown.strip() if isinstance(shown, str) else ""


def _assistant_text(message: dict[str, Any]) -> str:
    parts = message.get("content") if isinstance(message.get("content"), list) else []
    texts = [p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text"]
    return "\n\n".join(t.strip() for t in texts if isinstance(t, str) and t.strip())


def build_view(document: dict[str, Any], path: Path) -> dict[str, Any]:
    info = document.get("info") if isinstance(document.get("info"), dict) else {}
    times = info.get("time") if isinstance(info.get("time"), dict) else {}
    messages: list[dict[str, Any]] = []
    for message in document.get("messages") or []:
        if not isinstance(message, dict):
            continue
        kind = message.get("type") or "user"
        if kind in SKIPPED_TYPES:
            continue
        if kind == "assistant":
            text = _assistant_text(message)
            model = message.get("model") if isinstance(message.get("model"), dict) else {}
            author = model.get("id")
        else:
            text = _user_text(message)
            author = None
        if not text:
            continue
        msg_time = message.get("time") if isinstance(message.get("time"), dict) else {}
        messages.append({
            "id": message.get("id"),
            "role": "assistant" if kind == "assistant" else "user",
            "author_name": author,
            "recipient": None,
            "content_type": "text",
            "text": text,
            "create_time": _seconds(msg_time.get("created")),
            "attachments": [],
        })
    location = info.get("location") if isinstance(info.get("location"), dict) else {}
    return {
        "schema_version": 1,
        "source": SOURCE,
        "conversation_id": info.get("id") or path.stem,
        "title": info.get("title") or path.stem,
        "create_time": _seconds(times.get("created")),
        "update_time": _seconds(times.get("updated")),
        "is_archived": None,
        "is_starred": None,
        "messages": messages,
        "file_references": [],
        "textdocs": [],
        "meta": {"directory": location.get("directory"), "agent": info.get("agent")},
    }


def iter_items(raw_root: Path) -> Iterator[ExportItem]:
    folder = Path(raw_root) / SOURCE / "sessions"
    if not folder.is_dir():
        return
    for path in sorted(folder.rglob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            yield ExportItem(SOURCE, path, error=f"nicht lesbar: {exc}")
            continue
        if not isinstance(document, dict) or not isinstance(document.get("messages"), list):
            yield ExportItem(SOURCE, path, error="keine OpenCode-Session (Feld 'messages' fehlt)")
            continue
        yield ExportItem(SOURCE, path, view=build_view(document, path))
