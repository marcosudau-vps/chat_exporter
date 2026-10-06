from __future__ import annotations
from typing import Any
from chatexporter.providers.chatgpt.storage.envelope import signature_changed
from .models import PlanItem, SyncAction


def local_summary(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "update_time": entry.get("remote_updated_at"),
        # Detailzeit des gespeicherten Stands (siehe envelope.update_time_changed).
        "raw_update_time": entry.get("raw_update_time"),
        "title": entry.get("title"),
        "is_archived": entry.get("is_archived"),
        "is_starred": entry.get("is_starred"),
        "pinned_time": entry.get("pinned_time"),
    }


#: Bearbeitungsreihenfolge. Bewusst so gewaehlt, dass zuerst echte Luecken
#: geschlossen werden: eine Conversation ohne jede lokale Kopie ist dringender
#: als eine, von der bereits ein (importierter oder unvollstaendiger) Stand
#: vorliegt. Bei knappem Request-Budget entscheidet das ueber den Nutzen eines
#: abgebrochenen Laufs.
_REASON_PRIORITY = {
    "new": 0,
    "signature_changed": 1,
    "local_incomplete_or_integrity_failed": 2,
    "files_missing": 3,
}


def plan_sort_key(item: PlanItem) -> tuple[int, str]:
    return (_REASON_PRIORITY.get(item.reason, 9), item.conversation_id)


def build_plan(remote: dict[str, dict[str, Any]], local_index: dict[str, dict[str, Any]],
                quarantine: Any = None, exclusions: Any = None,
                *, partial_listing: bool = False) -> list[PlanItem]:
    plan: list[PlanItem] = []
    for cid, summary in remote.items():
        local = local_index.get(cid)
        if exclusions is not None and exclusions.is_excluded("conversation", cid):
            plan.append(PlanItem(cid, SyncAction.EXCLUDED, summary, "manually_excluded"))
        elif quarantine is not None and quarantine.is_quarantined("conversation", cid):
            plan.append(PlanItem(cid, SyncAction.QUARANTINED, summary, "quarantined"))
        elif local is None:
            plan.append(PlanItem(cid, SyncAction.FETCH_FULL, summary, "new"))
        elif not local.get("raw_integrity_ok", True):
            plan.append(PlanItem(cid, SyncAction.FETCH_FULL, summary, "local_incomplete_or_integrity_failed"))
        elif signature_changed(summary, local_summary(local)):
            plan.append(PlanItem(cid, SyncAction.FETCH_FULL, summary, "signature_changed"))
        elif not local.get("json_complete", local.get("fetch_complete", True)):
            plan.append(PlanItem(cid, SyncAction.FETCH_FULL, summary, "local_incomplete_or_integrity_failed"))
        elif not local.get("files_complete", True):
            # JSON steht, nur Dateien fehlen -> der teure Conversation-Abruf
            # waere reine Budgetverschwendung.
            plan.append(PlanItem(cid, SyncAction.FETCH_FILES_ONLY, summary, "files_missing"))
        else:
            plan.append(PlanItem(cid, SyncAction.SKIP, summary, "signature_unchanged"))
    # Ein Teil-Listing (listing_mode recent) sagt nichts ueber fehlende
    # Conversations aus: nicht gelistet heisst dort nur "nicht kuerzlich
    # geaendert", nicht "remote verschwunden".
    for cid in ([] if partial_listing else sorted(set(local_index) - set(remote))):
        plan.append(PlanItem(cid, SyncAction.MISSING_REMOTE, None, "absent_from_active_and_archived"))
    plan.sort(key=plan_sort_key)
    return plan
