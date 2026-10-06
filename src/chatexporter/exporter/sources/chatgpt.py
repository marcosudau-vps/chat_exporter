"""ChatGPT-Rohdaten lesen und zur neutralen Ansicht aufbereiten.

Liest die Envelopes unter ``raw_storage/chatgpt/conversations/**/<id>.json``
(Format: docs/ABLAGE_UND_FORMATE.md, Abschnitt 5). Die Datei wird nur gelesen.
Die Aufbereitung des Nachrichtengraphen (aktueller Pfad, sichtbarer Text,
ohne interne Denkinhalte) stammt aus dem frueheren ChatGPT-Provider und ist
hier bewusst als eigene Kopie gefuehrt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from . import ExportItem

SOURCE = "chatgpt"
INTERNAL_CONTENT_TYPES = {"thoughts", "reasoning", "raw_cot"}


def current_path_nodes(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Knoten vom Wurzelknoten bis ``current_node`` (der aktuell sichtbare Verlauf)."""
    mapping = raw.get("mapping")
    current = raw.get("current_node")
    if not isinstance(mapping, dict) or current not in mapping:
        return []
    ids: list[str] = []
    seen: set[str] = set()
    node_id = current
    while isinstance(node_id, str) and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        ids.append(node_id)
        node = mapping[node_id]
        node_id = node.get("parent") if isinstance(node, dict) else None
    ids.reverse()
    return [mapping[i] for i in ids if isinstance(mapping[i], dict)]


def _image_text(pointer: str) -> str:
    return f"[Image: {pointer[len('sediment://'):].split('?', 1)[0]}]"


def _part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return ""
    if isinstance(part.get("text"), str):
        return part["text"]
    pointer = part.get("asset_pointer")
    if isinstance(pointer, str) and pointer.startswith("sediment://"):
        return _image_text(pointer)
    ctype = part.get("content_type")
    if ctype:
        return f"[{ctype}]"
    return ""


def content_to_text(content: Any) -> str:
    if not isinstance(content, dict):
        return str(content) if content is not None else ""
    ctype = str(content.get("content_type") or "")
    if ctype in INTERNAL_CONTENT_TYPES:
        return ""
    if isinstance(content.get("text"), str):
        return content["text"]
    parts = content.get("parts")
    if isinstance(parts, list):
        return "\n".join(x for x in (_part_text(p) for p in parts) if x)
    pointer = content.get("asset_pointer")
    if isinstance(pointer, str) and pointer.startswith("sediment://"):
        return _image_text(pointer)
    return ""


def build_conversation_view(envelope: dict[str, Any]) -> dict[str, Any]:
    """Neutrale Ansicht einer gespeicherten ChatGPT-Konversation."""
    raw = envelope.get("raw") if isinstance(envelope.get("raw"), dict) else {}
    messages: list[dict[str, Any]] = []
    for node in current_path_nodes(raw):
        msg = node.get("message")
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        ctype = content.get("content_type") if isinstance(content, dict) else None
        if ctype in INTERNAL_CONTENT_TYPES:
            continue
        author = msg.get("author") if isinstance(msg.get("author"), dict) else {}
        attachments = msg.get("metadata", {}).get("attachments", []) if isinstance(msg.get("metadata"), dict) else []
        messages.append({
            "id": msg.get("id") or node.get("id"),
            "role": author.get("role") or "unknown",
            "author_name": author.get("name"),
            "recipient": msg.get("recipient"),
            "content_type": ctype,
            "text": content_to_text(content),
            "create_time": msg.get("create_time"),
            "attachments": attachments if isinstance(attachments, list) else [],
        })
    summary = envelope.get("remote_summary") if isinstance(envelope.get("remote_summary"), dict) else {}
    return {
        "schema_version": 1,
        "source": SOURCE,
        "conversation_id": envelope.get("conversation_id"),
        "title": summary.get("title") or raw.get("title") or "Untitled conversation",
        "create_time": summary.get("create_time") or raw.get("create_time"),
        "update_time": summary.get("update_time") or raw.get("update_time"),
        "is_archived": summary.get("is_archived"),
        "is_starred": summary.get("is_starred"),
        "messages": messages,
        "file_references": envelope.get("file_references", []),
        "textdocs": envelope.get("textdocs", []),
    }


def iter_items(raw_root: Path) -> Iterator[ExportItem]:
    """Alle gespeicherten Konversationen, nach Pfad sortiert."""
    folder = Path(raw_root) / SOURCE / "conversations"
    if not folder.is_dir():
        return
    for path in sorted(folder.rglob("*.json")):
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            yield ExportItem(SOURCE, path, error=f"nicht lesbar: {exc}")
            continue
        if not isinstance(envelope, dict) or not isinstance(envelope.get("raw"), dict):
            yield ExportItem(SOURCE, path, error="kein ChatGPT-Envelope (Feld 'raw' fehlt)")
            continue
        yield ExportItem(SOURCE, path, view=build_conversation_view(envelope))
