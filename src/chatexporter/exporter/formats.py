"""Ausgabeformate des Exporters: Markdown und JSON.

Ein Format stellt die neutrale Ansicht eines Gespraechs dar und schreibt sie
nach ``<export_root>/<format>/<quelle>/<JJJJ-MM>/<id>.<endung>``. Formate lesen nur die
Ansicht, nie den Raw Storage, und veraendern nichts ausser ihrer Zieldatei.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ._io import atomic_write_json, atomic_write_text


def month_bucket(value: Any) -> str:
    """Monatsordner ``JJJJ-MM`` aus einem Zeitwert (Unix-Sekunden oder ISO-Text), sonst ``unknown``."""
    try:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
            return f"{dt.year:04d}-{dt.month:02d}"
        if isinstance(value, str) and value:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return f"{dt.year:04d}-{dt.month:02d}"
    except Exception:  # noqa: BLE001  unlesbare Zeitangaben landen in "unknown"
        pass
    return "unknown"


def render_markdown(view: dict[str, Any]) -> str:
    lines = [f"# {view['title']}", ""]
    if view.get("source"):
        lines.append(f"- Source: `{view['source']}`")
    lines += [
        f"- Conversation ID: `{view['conversation_id']}`",
        f"- Created: `{view.get('create_time')}`",
        f"- Updated: `{view.get('update_time')}`",
    ]
    # Archiv-/Stern-Status gibt es nur bei Quellen, die ihn kennen (ChatGPT).
    for label, key in (("Archived", "is_archived"), ("Starred", "is_starred")):
        if view.get(key) is not None:
            lines.append(f"- {label}: `{view.get(key)}`")
    for key, value in (view.get("meta") or {}).items():
        if value:
            lines.append(f"- {key}: `{value}`")
    lines.append("")
    for msg in view["messages"]:
        role = str(msg.get("role") or "unknown").upper()
        recipient = msg.get("recipient")
        suffix = f" → {recipient}" if recipient and recipient not in {"all", "none"} else ""
        lines += [f"## {role}{suffix}", ""]
        text = str(msg.get("text") or "").strip()
        lines += [text if text else f"_[{msg.get('content_type') or 'empty'}]_", ""]
        attachments = msg.get("attachments") or []
        for attachment in attachments:
            if isinstance(attachment, dict):
                lines.append(f"- Attachment: `{attachment.get('name') or attachment.get('id') or 'unknown'}`")
        if attachments:
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _safe(name: Any) -> str:
    """Dateiname ohne unter Windows verbotene Zeichen."""
    text = str(name)
    for ch in '<>:"/|?*' + chr(92):
        text = text.replace(ch, "_")
    return text.strip(" .") or "unbenannt"


class Format:
    """Ein Ausgabeformat: Name, Dateiendung und Schreibfunktion."""

    def __init__(self, name: str, suffix: str, write: Callable[[Path, dict[str, Any], Path], None]):
        self.name = name
        self.suffix = suffix
        self._write = write

    def target(self, export_root: Path, view: dict[str, Any]) -> Path:
        month = month_bucket(view.get("create_time"))
        source = view.get("source") or "unknown"
        return export_root / self.name / source / month / f"{_safe(view['conversation_id'])}.{self.suffix}"

    def export(self, export_root: Path, view: dict[str, Any], staging_dir: Path | None = None) -> Path:
        target = self.target(export_root, view)
        self._write(target, view, staging_dir or export_root / ".staging")
        return target


def _write_markdown(target: Path, view: dict[str, Any], staging: Path) -> None:
    atomic_write_text(target, render_markdown(view), staging_dir=staging)


def _write_json(target: Path, view: dict[str, Any], staging: Path) -> None:
    atomic_write_json(target, view, staging_dir=staging)


FORMATS: dict[str, Format] = {
    "markdown": Format("markdown", "md", _write_markdown),
    "json": Format("json", "json", _write_json),
}


def build_formats(names: list[str] | tuple[str, ...]) -> list[Format]:
    out: list[Format] = []
    for name in names:
        key = name.strip().lower()
        if key not in FORMATS:
            raise ValueError(f"Unbekanntes Exportformat: {name}")
        out.append(FORMATS[key])
    return out
