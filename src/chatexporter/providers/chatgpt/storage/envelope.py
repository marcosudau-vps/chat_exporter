from __future__ import annotations
from typing import Any
from chatexporter.providers.chatgpt.common.hashing import canonical_json_bytes, sha256_bytes
from chatexporter.providers.chatgpt.common.time import now_iso
from chatexporter.providers.chatgpt.fetch.conversation_fetcher import FetchedConversation

SIGNATURE_FIELDS = ("update_time", "title", "is_archived", "is_starred", "pinned_time")


def remote_summary_from_listing(item: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "id", "title", "create_time", "update_time", "is_archived", "is_starred",
        "pinned_time", "gizmo_id", "workspace_id", "conversation_origin",
        "is_temporary_chat", "is_do_not_remember",
    ]
    return {k: item.get(k) for k in keys if k in item}


def signature(summary: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(summary.get(k) for k in SIGNATURE_FIELDS)


def time_value(value: Any) -> float | None:
    """Zeitstempel als Zahl (Sekunden), egal ob Zahl oder ISO-Text.

    Das Listing liefert ISO-Text in wechselnder Schreibweise (mit und ohne
    Nachkommastellen, ``Z`` oder ``+00:00``). Verglichen wird deshalb der
    Zeitpunkt, nicht der Text.
    """
    from datetime import datetime
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def same_time(a: Any, b: Any) -> bool:
    """Gleicher Zeitpunkt (auf die Mikrosekunde), unabhaengig von der Schreibweise."""
    if a == b:
        return True
    ta, tb = time_value(a), time_value(b)
    return ta is not None and tb is not None and round(ta, 6) == round(tb, 6)


def update_time_changed(remote: Any, local_listing: Any, local_detail: Any = None) -> bool:
    """Ist die Conversation laut Listing NEUER als unser gespeicherter Stand?

    Das Listing fuehrt ``update_time`` teils verzoegert: beim Abruf lag die
    Listing-Zeit bei 575 von 3098 Conversations VOR der Detailzeit (nie
    danach), Abstand meist < 1 min, vereinzelt Wochen. Zieht das Listing
    spaeter nach, ist das KEINE Aenderung -- der gespeicherte Inhalt hat
    diesen Stand bereits. Massgeblich ist deshalb der juengere der beiden
    gespeicherten Werte (Listing- und Detailzeit beim letzten Abruf).
    """
    if same_time(remote, local_listing) or (local_detail is not None
                                            and same_time(remote, local_detail)):
        return False
    remote_ts = time_value(remote)
    known = [t for t in (time_value(local_listing), time_value(local_detail)) if t is not None]
    if remote_ts is None or not known:
        return True  # nicht beurteilbar -> vorsichtshalber als Aenderung werten
    return round(remote_ts, 6) > round(max(known), 6)


def signature_changed(summary: dict[str, Any], local_summary: dict[str, Any]) -> bool:
    """Weicht die Listing-Signatur vom lokalen Stand ab? Zeitfelder werden als
    Zeitpunkt verglichen (siehe :func:`time_value`); ``update_time`` zusaetzlich
    gegen die Detailzeit des gespeicherten Stands (``raw_update_time``)."""
    for key in SIGNATURE_FIELDS:
        a, b = summary.get(key), local_summary.get(key)
        if key == "update_time":
            if update_time_changed(a, b, local_summary.get("raw_update_time")):
                return True
        elif key == "pinned_time":
            if not same_time(a, b):
                return True
        elif a != b:
            return True
    return False


def files_complete_state(file_references: list[dict[str, Any]] | None,
                          library: Any = None,
                          quarantine: Any = None,
                          exclusions: Any = None) -> bool:
    """Sind alle Dateien einer Conversation abschliessend geklaert?

    Eine Conversation ohne Dateiverweise ist per Definition sofort fertig.
    Quarantaenisierte und manuell ausgeschlossene Dateien zaehlen bewusst NICHT
    gegen die Vollstaendigkeit -- sonst koennte eine einzelne dauerhaft tote
    Datei die Conversation fuer immer unfertig halten.
    """
    refs = file_references or []
    if not refs:
        return True
    if library is None:
        return False
    for ref in refs:
        fid = ref.get("id")
        if exclusions is not None and isinstance(fid, str) and                 exclusions.is_excluded("file", fid):
            continue
        if quarantine is not None and isinstance(fid, str) and                 quarantine.is_quarantined("file", fid):
            continue
        state = library.derived_state(ref)
        # UNAVAILABLE = serverseitig endgueltig weg, UNSUPPORTED = kein
        # ladbarer Referenztyp. Beides ist abschliessend geklaert und darf
        # die Conversation nicht dauerhaft unfertig halten.
        if state not in ("MATERIALIZED", "UNAVAILABLE", "UNSUPPORTED"):
            return False
    return True


def refresh_acquisition_completeness(envelope: dict[str, Any], library: Any,
                                     quarantine: Any = None,
                                     exclusions: Any = None) -> bool:
    """Berechnet ``files_complete``/``complete`` im Envelope neu.

    Liefert ``True``, wenn sich etwas geaendert hat. Notwendig fuer
    Bestandsdaten: Wird die Dateireferenzliste nachtraeglich erweitert
    (Renormalisierung), bleibt ein frueher gesetztes ``files_complete=true``
    sonst faelschlich stehen und der Planner ueberspringt die Conversation.
    """
    acq = envelope.get("acquisition")
    if not isinstance(acq, dict):
        return False
    files_ok = files_complete_state(envelope.get("file_references"), library, quarantine, exclusions)
    json_ok = bool(acq.get("json_complete", acq.get("complete")))
    complete = json_ok and files_ok
    if acq.get("files_complete") == files_ok and acq.get("complete") == complete:
        return False
    acq["files_complete"] = files_ok
    acq["complete"] = complete
    return True


def build_envelope(summary: dict[str, Any], fetched: FetchedConversation,
                    *, library: Any = None, quarantine: Any = None) -> dict[str, Any]:
    raw_hash = sha256_bytes(canonical_json_bytes(fetched.raw))
    json_complete = bool(fetched.validation.complete)
    files_complete = files_complete_state(fetched.file_references, library, quarantine)
    return {
        "storage_schema_version": 1,
        "provider": "chatgpt",
        "conversation_id": summary.get("id") or fetched.raw.get("conversation_id"),
        "remote_summary": dict(summary),
        "acquisition": {
            "fetched_at": now_iso(),
            # "complete" gilt weiterhin als Gesamtaussage und ist nur dann wahr,
            # wenn sowohl der Graph als auch die Dateien vollstaendig sind.
            "complete": json_complete and files_complete,
            "json_complete": json_complete,
            "files_complete": files_complete,
            "source": "api",
            "source_endpoint": "GET /backend-api/conversation/<id>",
            "current_node_resolved": fetched.validation.current_node_resolved,
            "dangling_parent_count": fetched.validation.dangling_parent_count,
            "root_count": fetched.validation.root_count,
            "node_count": fetched.validation.node_count,
            "warnings": fetched.validation.warnings,
            "supplemental_errors": fetched.supplemental_errors,
        },
        "raw": fetched.raw,
        "textdocs": fetched.textdocs,
        "file_references": fetched.file_references,
        "tool_references": fetched.tool_references,
        "integrity": {"raw_payload_sha256": raw_hash},
    }
