from __future__ import annotations
from collections.abc import Callable
from typing import Any
from chatexporter.providers.chatgpt.api.conversations import ConversationApi
from chatexporter.providers.chatgpt.storage.envelope import (
    remote_summary_from_listing, signature_changed, time_value, update_time_changed,
)


class DuplicateConversationError(RuntimeError):
    pass


def fetch_complete_listing(
    api: ConversationApi,
    *,
    limit: int = 100,
    progress: Callable[[str], None] | None = None,
) -> dict[str, dict[str, Any]]:
    emit = progress or (lambda _message: None)
    merged: dict[str, dict[str, Any]] = {}
    scopes = ((False, "active"), (True, "archived"))
    for archived, scope_name in scopes:
        emit(f"Listing {scope_name}: starte Abruf ...")
        scope_count = 0
        for item in api.iter_scope(archived=archived, limit=limit):
            cid = item.get("id")
            if not isinstance(cid, str) or not cid:
                continue
            summary = remote_summary_from_listing(item)
            if cid in merged:
                raise DuplicateConversationError(f"Conversation {cid} appeared in multiple listing scopes ({scope_name})")
            merged[cid] = summary
            scope_count += 1
        emit(f"Listing {scope_name}: {scope_count} Conversations gefunden.")
    return merged


#: Listing-Modi.
#: - `auto`   (Default): leerer Bestand -> `full`; sonst `recent`, und wenn
#:            dessen Aenderungsgrenze nicht sicher bestaetigt ist -> `full`.
#: - `full`   : beide Scopes komplett (gesamter Bestand).
#: - `recent` : nur die zuletzt geaenderten aktiven Conversations
#:              (order=updated); wechselt NIE selbst auf `full`.
LISTING_MODES = ("auto", "full", "recent")

#: Klassifikation eines Listing-Eintrags gegen den lokalen Index.
NEW = "new"            # lokal unbekannt
CONTENT = "content"    # update_time weicht ab -> Inhalt geaendert
META = "meta"          # update_time gleich, nur Titel/Stern/Pin/Archiv geaendert
SAME = "same"          # Signatur identisch
#: Bewusst nicht synchron gehalten (manueller Ausschluss/Quarantaene): wird nie
#: geladen und darf die Grenze deshalb weder bilden noch verletzen.
IGNORED = "ignored"


def classify(summary: dict[str, Any], local: dict[str, Any] | None) -> str:
    """Ordnet einen Listing-Eintrag ein (siehe NEW/CONTENT/META/SAME).

    Die Grenze zwischen geaenderten und unveraenderten Conversations haengt
    allein an ``update_time`` (danach sortiert der Server). Reine
    Metadaten-Aenderungen (``META``) werden geladen, verschieben die Grenze
    aber nicht, weil sie ``update_time`` nicht zwingend veraendern. Zeiten
    werden als Zeitpunkt verglichen, nicht als Text (die Schreibweise im
    Listing wechselt).
    """
    if local is None:
        return NEW
    from .planner import local_summary
    local_sig = local_summary(local)
    if update_time_changed(summary.get("update_time"), local_sig.get("update_time"),
                           local_sig.get("raw_update_time")):
        return CONTENT
    if signature_changed(summary, local_sig):
        return META
    return SAME


def _is_remote_change(summary: dict[str, Any], local: dict[str, Any] | None) -> bool:
    """Neu oder remote veraendert gegenueber dem lokalen Indexstand."""
    return classify(summary, local) != SAME


_timestamp = time_value


def fetch_recent_listing(
    api: ConversationApi,
    *,
    local_index: dict[str, dict[str, Any]],
    limit: int = 100,
    max_pages: int = 3,
    confirm_unchanged: int = 3,
    ignore: Callable[[str], bool] | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Laedt nur die zuletzt geaenderten aktiven Conversations.

    Sortierung `order=updated` (neueste zuerst, wie der Browser); jede Seite
    kostet ein Listing-Token. Die **Aenderungsgrenze** ist der erste Eintrag,
    dessen ``update_time`` dem lokalen Stand entspricht. Sie gilt erst als
    bestaetigt, wenn

    1. ab ihr mindestens ``confirm_unchanged`` Eintraege (die Grenze
       eingeschlossen) mit unveraenderter ``update_time`` vorliegen (sonst wird
       die naechste Seite geholt) und
    2. in allen geholten Eintraegen NACH der Grenze kein neuer oder
       inhaltlich geaenderter Eintrag mehr auftaucht (Aenderungen muessen
       wegen der Sortierung einen zusammenhaengenden Anfang bilden) und
    3. die Sortierung tatsaechlich absteigend nach ``update_time`` ist und
    4. jede lokal bekannte aktive Conversation, die NEUER als die Grenze ist,
       auch im Listing vorkommt (sonst wurde sie archiviert/geloescht).

    Hoechstens ``max_pages`` Seiten. Rueckgabe ``(remote, info)``;
    ``info["boundary_reached"]`` ist nur bei bestaetigter Grenze True,
    ``info["reason"]`` nennt sonst den Grund (``cap_reached``,
    ``out_of_order_change``, ``order_violation``, ``recent_local_missing``).

    ``ignore(cid)``: bewusst nicht synchron gehaltene Conversations (manuell
    ausgeschlossen, Quarantaene). Sie werden gelistet und geplant (dort als
    EXCLUDED/QUARANTINED), bilden aber weder die Grenze noch verletzen sie sie.
    ``info["entries"]`` haelt fuer die Analyse jeden gelisteten Eintrag mit
    Position, Einstufung und beiden Zeitstempeln fest.
    """
    emit = progress or (lambda _message: None)
    is_ignored = ignore or (lambda _cid: False)
    merged: dict[str, dict[str, Any]] = {}
    kinds: dict[str, str] = {}
    entries: list[dict[str, Any]] = []
    pages = 0
    offset = 0
    boundary_id: str | None = None
    boundary_time: Any = None
    confirmed = 0
    out_of_order: list[str] = []
    order_violations: list[str] = []
    ignored: list[str] = []
    last_ts: float | None = None
    exhausted = False
    while pages < max_pages:
        page = api.list_page(offset=offset, limit=limit, order="updated")
        pages += 1
        items = [x for x in page["items"] if isinstance(x, dict)]
        page_changed = 0
        for item in items:
            cid = item.get("id")
            if not isinstance(cid, str) or not cid:
                continue
            # Verschiebt sich eine Conversation zwischen zwei Seitenabrufen
            # nach oben, taucht ein Nachbar doppelt auf: ersten Stand behalten.
            if cid in merged:
                continue
            summary = remote_summary_from_listing(item)
            local = local_index.get(cid)
            kind = IGNORED if is_ignored(cid) else classify(summary, local)
            merged[cid] = summary
            kinds[cid] = kind
            entries.append({"pos": len(entries) + 1, "id": cid, "kind": kind,
                            "remote_update_time": summary.get("update_time"),
                            "local_update_time": (local or {}).get("remote_updated_at"),
                            "local_detail_update_time": (local or {}).get("raw_update_time")})
            ts = _timestamp(summary.get("update_time"))
            if ts is not None:
                if last_ts is not None and ts > last_ts:
                    order_violations.append(cid)
                last_ts = ts
            if kind == IGNORED:
                ignored.append(cid)
                continue
            if kind != SAME:
                page_changed += 1
            if boundary_id is None:
                if kind in (SAME, META):
                    boundary_id, boundary_time = cid, summary.get("update_time")
                    confirmed = 1
            elif kind in (NEW, CONTENT):
                out_of_order.append(cid)
            else:
                confirmed += 1
        emit(f"Listing recent: Seite {pages} (offset {offset}): {len(items)} Eintraege, "
             f"{page_changed} neu/geaendert.")
        if len(items) < limit:
            exhausted = True
            break
        if out_of_order or order_violations:
            break
        if boundary_id is not None and confirmed >= confirm_unchanged:
            break
        offset += len(items)

    # Querprobe mit dem lokalen Bestand: alles lokal Aktive, das neuer als die
    # Grenze ist, muss im Listing vorkommen.
    missing_recent: list[str] = []
    boundary_ts = _timestamp(boundary_time)
    if boundary_ts is not None:
        for cid, entry in local_index.items():
            if cid in merged or entry.get("is_archived"):
                continue
            local_ts = _timestamp(entry.get("remote_updated_at"))
            if local_ts is not None and local_ts > boundary_ts:
                missing_recent.append(cid)

    if order_violations:
        reason = "order_violation"
    elif out_of_order:
        reason = "out_of_order_change"
    elif missing_recent:
        reason = "recent_local_missing"
    elif exhausted or (boundary_id is not None and confirmed >= confirm_unchanged):
        # Ende der Liste erreicht: alles gesehen, die Grenze ist trivial sicher.
        reason = None
    else:
        reason = "cap_reached"
    counts = {k: sum(1 for v in kinds.values() if v == k) for k in (NEW, CONTENT, META, SAME, IGNORED)}
    info = {
        "mode": "recent",
        "order": "updated",
        "limit": limit,
        "pages": pages,
        "max_pages": max_pages,
        "items": len(merged),
        "changed": counts[NEW] + counts[CONTENT] + counts[META],
        "counts": counts,
        "boundary_reached": reason is None,
        "boundary": {"conversation_id": boundary_id, "update_time": boundary_time,
                     "confirmed_unchanged": confirmed, "required": confirm_unchanged},
        "reason": reason,
        "anomalies": {"out_of_order_change": out_of_order[:20],
                      "order_violation": order_violations[:20],
                      "recent_local_missing": missing_recent[:20]},
        "ignored": ignored,
        "scopes": ["active"],
        # Diagnose: jeder gelistete Eintrag (Position, Einstufung, Zeiten).
        "entries": entries,
    }
    if reason is not None:
        emit(f"WARNUNG: Aenderungsgrenze nicht bestaetigt ({reason}). Es koennen "
             "Aenderungen fehlen -- ein Voll-Abruf (listing_mode full) ist noetig.")
    return merged, info
