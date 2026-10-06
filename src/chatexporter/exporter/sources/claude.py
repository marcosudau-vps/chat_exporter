"""Claude-Code-Rohdaten (``raw_storage/claude/projects/<projekt>/<sitzung>.jsonl``) zur neutralen Ansicht.

Exportiert werden die Hauptsitzungen (Dateien direkt im Projektordner, keine
Unteragenten unter ``<sitzung>/subagents/``) mit den Texten von Benutzer und
Assistent. Denkinhalte (``thinking``), Werkzeugaufrufe und -ergebnisse sowie
Nebenzweige (``isSidechain``) gehoeren nicht zur lesbaren Unterhaltung.
Notizen wie ``memory/*.md`` sind keine Sitzungen.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from . import ExportItem
from .codex import read_rows

SOURCE = "claude"


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
    texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "\n\n".join(t.strip() for t in texts if isinstance(t, str) and t.strip())


def build_view(rows: list[dict[str, Any]], path: Path) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    title = None
    first_time = last_time = None
    session_id = None
    cwd = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("timestamp"):
            first_time = first_time or row["timestamp"]
            last_time = row["timestamp"]
        session_id = session_id or row.get("sessionId")
        cwd = cwd or row.get("cwd")
        if row.get("type") == "custom-title" and row.get("customTitle"):
            title = str(row["customTitle"])
            continue
        if row.get("type") not in ("user", "assistant") or row.get("isSidechain") or row.get("isMeta"):
            continue
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        text = _text(message.get("content"))
        if not text:
            continue
        messages.append({
            "id": row.get("uuid"),
            "role": message.get("role") or row["type"],
            "author_name": message.get("model"),
            "recipient": None,
            "content_type": "text",
            "text": text,
            "create_time": _seconds(row.get("timestamp")),
            "attachments": [],
        })
    if not title:
        first_user = next((m["text"] for m in messages if m["role"] == "user"), "")
        title = first_user.strip().splitlines()[0][:100] if first_user.strip() else path.stem
    return {
        "schema_version": 1,
        "source": SOURCE,
        "conversation_id": str(session_id or path.stem),
        "title": title,
        "create_time": _seconds(first_time),
        "update_time": _seconds(last_time),
        "is_archived": None,
        "is_starred": None,
        "messages": messages,
        "file_references": [],
        "textdocs": [],
        "meta": {"project": path.parent.name, "cwd": cwd},
    }


def iter_items(raw_root: Path) -> Iterator[ExportItem]:
    folder = Path(raw_root) / SOURCE / "projects"
    if not folder.is_dir():
        return
    for project in sorted(p for p in folder.iterdir() if p.is_dir()):
        for path in sorted(project.glob("*.jsonl")):
            try:
                rows = read_rows(path)
            except (OSError, ValueError) as exc:
                yield ExportItem(SOURCE, path, error=f"nicht lesbar: {exc}")
                continue
            yield ExportItem(SOURCE, path, view=build_view(rows, path))
