from __future__ import annotations
from typing import Any

# Bestaetigte Pointer-Schemata im realen Bestand (Messung 2026-09-22 ueber
# 1036 produktive Conversations + 2902 Conversations eines Kontodatensatzes):
#   sediment://file_...      modern, Bilder/Dateien/Audio
#   file-service://file-...  aelter, ausschliesslich Bilder
_POINTER_SCHEMES = ("sediment://", "file-service://")

# Beide ID-Namensraeume kommen real vor. pre-4 akzeptierte nur "file_" und hat
# dadurch nachweislich Dateien uebersehen (99 Legacy-Bilder im Produktivbestand).
_ID_PREFIXES = ("file_", "file-")

#: Referenzarten, die als Sprach-/Audioaufnahme gelten und deshalb in einen
#: eigenen Library-Bereich wandern (siehe storage/library.py).
AUDIO_KINDS = frozenset({"audio_asset_pointer"})


def _file_id_from_asset_pointer(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    for scheme in _POINTER_SCHEMES:
        if value.startswith(scheme):
            candidate = value[len(scheme):].split("?", 1)[0].strip("/")
            if candidate.startswith(_ID_PREFIXES):
                return candidate
    return None


def _walk_asset_pointers(value: Any, node_id: str, found: dict[str, dict[str, Any]],
                         message_id: Any = None) -> None:
    """Sucht Asset-Pointer in BELIEBIGER Verschachtelungstiefe.

    Notwendig, weil Sprachaufnahmen aus dem Voice-Mode nicht flach im Part
    liegen: ein Part vom Typ ``real_time_user_audio_video_asset_pointer``
    enthaelt den eigentlichen Pointer erst eine Ebene tiefer unter
    ``audio_asset_pointer.asset_pointer``. pre-4 sah nur die oberste
    Part-Ebene und hat dadurch im Produktivbestand 233 WAV-Aufnahmen
    uebersehen.
    """
    if isinstance(value, dict):
        fid = _file_id_from_asset_pointer(value.get("asset_pointer"))
        if fid and fid not in found:
            content_type = value.get("content_type")
            kind = content_type if isinstance(content_type, str) and content_type else "image_asset_pointer"
            row: dict[str, Any] = {
                "id": fid,
                "kind": kind,
                "node_id": node_id,
                "message_id": message_id,
                "name": value.get("name"),
                "mime_type": value.get("mime_type"),
                "size": value.get("size_bytes") or value.get("size"),
                "width": value.get("width"),
                "height": value.get("height"),
            }
            fmt = value.get("format")
            if isinstance(fmt, str) and fmt:
                row["format"] = fmt
            found[fid] = row
        for child in value.values():
            _walk_asset_pointers(child, node_id, found, message_id)
    elif isinstance(value, list):
        for child in value:
            _walk_asset_pointers(child, node_id, found, message_id)


def extract_file_references(payload: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = payload.get("mapping") if isinstance(payload, dict) else None
    if not isinstance(mapping, dict):
        return []
    found: dict[str, dict[str, Any]] = {}
    for node_id, node in mapping.items():
        if not isinstance(node, dict):
            continue
        msg = node.get("message")
        if not isinstance(msg, dict):
            continue

        metadata = msg.get("metadata")
        attachments = metadata.get("attachments") if isinstance(metadata, dict) else None
        if isinstance(attachments, list):
            for attachment in attachments:
                if not isinstance(attachment, dict):
                    continue
                fid = attachment.get("id")
                if isinstance(fid, str) and fid.startswith(_ID_PREFIXES):
                    found.setdefault(fid, {
                        "id": fid,
                        "kind": "attachment",
                        "node_id": node_id,
                        "message_id": msg.get("id"),
                        "name": attachment.get("name"),
                        "mime_type": attachment.get("mime_type"),
                        "size": attachment.get("size"),
                        "source": attachment.get("source"),
                        "library_file_id": attachment.get("library_file_id"),
                        "is_big_paste": attachment.get("is_big_paste"),
                    })

        content = msg.get("content")
        if isinstance(content, dict):
            _walk_asset_pointers(content, node_id, found, msg.get("id"))
    return sorted(found.values(), key=lambda r: (str(r.get("id")), str(r.get("node_id"))))


def extract_tool_references(payload: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = payload.get("mapping") if isinstance(payload, dict) else None
    if not isinstance(mapping, dict):
        return []
    rows = []
    for node_id, node in mapping.items():
        msg = node.get("message") if isinstance(node, dict) else None
        if not isinstance(msg, dict):
            continue
        author = msg.get("author") if isinstance(msg.get("author"), dict) else {}
        role = author.get("role")
        recipient = msg.get("recipient")
        if role == "tool" or (isinstance(recipient, str) and recipient not in {"", "all", "none"}):
            rows.append({"node_id": node_id, "role": role, "recipient": recipient})
    return rows


def has_canvas_hint(payload: dict[str, Any]) -> bool:
    for ref in extract_tool_references(payload):
        recipient = str(ref.get("recipient") or "")
        if recipient.startswith("canmore."):
            return True
    return False


def is_audio_reference(ref: dict[str, Any]) -> bool:
    return str(ref.get("kind") or "") in AUDIO_KINDS
