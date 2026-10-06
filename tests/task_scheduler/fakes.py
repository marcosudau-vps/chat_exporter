"""Ersatz fuer den PyTaskManager: gleiche Schnittstelle, kein Windows noetig."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


class FakeError(ValueError):
    pass


@dataclass
class FakeInfo:
    task_id: str
    owner: str
    slug: str
    name: str
    scheduler_path: str
    exists: bool = True
    state: str = "ready"
    enabled: bool | None = True
    last_run_time: Any = None
    next_run_time: Any = None
    last_result: int | None = 267011
    trigger_types: list[str] = field(default_factory=list)
    description: str = ""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class FakeManager:
    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}
        self.enabled: dict[str, bool] = {}
        self.payloads: list[dict[str, Any]] = []
        self._next = 0
        #: Aufgaben, deren Eintrag im globalen State fehlt (nur lokal + Windows).
        self.global_lost: set[str] = set()

    def create(self, payload: dict[str, Any], *, overwrite: bool = True) -> FakeInfo:
        self.payloads.append(payload)
        slug = _slug(payload.get("slug") or payload["name"])
        existing = next((e for e in self.entries.values()
                         if e["slug"] == slug and e["owner"] == payload["owner"]), None)
        if payload.get("task_id") and payload["task_id"] in self.entries:
            existing = self.entries[payload["task_id"]]
        if existing and not overwrite:
            raise FakeError(f"Managed Task existiert bereits: {payload['owner']}:{slug}")
        if existing:
            task_id = existing["task_id"]
        else:
            self._next += 1
            task_id = f"tsk_{self._next:012d}"
        self.entries[task_id] = {"task_id": task_id, "owner": payload["owner"], "slug": slug,
                                 "name": payload["name"], "metadata": payload.get("metadata") or {},
                                 "description": payload.get("description", "")}
        self.enabled[task_id] = bool(payload.get("enabled", True))
        return self._info(task_id)

    def resolve_entry(self, ref: str, *, owner: str | None = None) -> dict[str, Any]:
        for entry in self.entries.values():
            by_id = ref == entry["task_id"]
            by_name = ref in (entry["slug"], entry["name"]) and entry["task_id"] not in self.global_lost
            if by_id or by_name:
                return dict(entry)
        raise FakeError(f"Managed Task nicht gefunden: {ref}")

    def _info(self, task_id: str) -> FakeInfo:
        entry = self.entries[task_id]
        enabled = self.enabled[task_id]
        return FakeInfo(task_id=task_id, owner=entry["owner"], slug=entry["slug"], name=entry["name"],
                        scheduler_path=f"\\Fake\\{task_id}", enabled=enabled,
                        state="ready" if enabled else "disabled", description=entry["description"])

    def get(self, ref: str, *, owner: str | None = None) -> FakeInfo:
        return self._info(self.resolve_entry(ref)["task_id"])

    def list(self, *, owner: str | None = None, local_only: bool = False) -> list[FakeInfo]:
        return [self._info(task_id) for task_id in sorted(self.entries)
                if local_only or task_id not in self.global_lost]

    def enable(self, ref: str, *, owner: str | None = None) -> None:
        self.enabled[self.resolve_entry(ref)["task_id"]] = True

    def disable(self, ref: str, *, owner: str | None = None) -> None:
        self.enabled[self.resolve_entry(ref)["task_id"]] = False

    def delete(self, ref: str, *, owner: str | None = None) -> bool:
        task_id = self.resolve_entry(ref)["task_id"]
        del self.entries[task_id]
        del self.enabled[task_id]
        self.global_lost.discard(task_id)
        return True
