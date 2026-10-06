from __future__ import annotations

"""Einmalige Ablage-Migration: flach -> Namespace + Runtime (`STORE-FIND-05`).

Idempotent: Ist das Zielbild bereits hergestellt, passiert nichts
(`migrated: False`). Mit ``dry_run`` wird nur geplant und gezaehlt.

Verschoben wird:
- ``conversations/YYYY-MM/*.json`` -> ``chatgpt/conversations/YYYY/MM/DD/*.json``
  (Bucket aus ``remote_summary.create_time``; Fallback ``unknown/``)
- ``library/`` -> ``chatgpt/library/``
- ``storage_index.json`` + ``runs/`` + ``.staging/`` + ``quarantine.json``
  -> ``.storage/`` (Index wird danach neu gebaut)
- ``status_registry/*`` -> ``.storage/status_registry/``

Inhalte werden nie veraendert, nur verschoben (Rename auf demselben Volume).
Danach: Index-Rebuild + ``file_index``-Rebuild.
"""

import json
from pathlib import Path
from typing import Any, Callable

from chatexporter.providers.chatgpt.storage.raw_repository import _date_bucket


def _move_file(src: Path, dest: Path, *, dry_run: bool) -> bool:
    if dry_run:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return False
    src.rename(dest)
    return True


def _move_dir(src: Path, dest_parent: Path, *, dry_run: bool) -> bool:
    if not src.exists():
        return False
    if dry_run:
        return True
    dest_parent.mkdir(parents=True, exist_ok=True)
    dest = dest_parent / src.name
    if dest.exists():
        for child in sorted(src.iterdir()):
            target = dest / child.name
            if child.is_dir() and target.exists():
                for sub in sorted(child.rglob("*")):
                    rel = sub.relative_to(child)
                    final = target / rel
                    if sub.is_dir():
                        final.mkdir(parents=True, exist_ok=True)
                    elif not final.exists():
                        final.parent.mkdir(parents=True, exist_ok=True)
                        sub.rename(final)
            elif not target.exists():
                child.rename(target)
        try:
            src.rmdir()
        except OSError:
            pass
        return True
    src.rename(dest)
    return True


def _bucket_for(path: Path) -> str:
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "unknown"
    summary = envelope.get("remote_summary") if isinstance(envelope, dict) else None
    create_time = summary.get("create_time") if isinstance(summary, dict) else None
    return _date_bucket(create_time)


def plan_layout_migration(store_root: Path, source: str = "chatgpt") -> dict[str, Any]:
    """Zaehlt, was zu tun waere (read-only)."""
    store = Path(store_root)
    target = store / source
    already = (target / "conversations").is_dir() and not (store / "conversations").exists()
    conv_files = sorted((store / "conversations").rglob("*.json")) if (store / "conversations").is_dir() else []
    return {
        "store_root": str(store),
        "source": source,
        "already_migrated": already,
        "legacy_conversations": len(conv_files),
        "legacy_library": (store / "library").is_dir(),
        "legacy_index": (store / "storage_index.json").is_file(),
        "legacy_runs": len(list((store / "runs").glob("*.json"))) if (store / "runs").is_dir() else 0,
        "legacy_staging": (store / ".staging").exists(),
        "legacy_quarantine": (store / "quarantine.json").is_file(),
        "legacy_status_registry": (store.parent / "status_registry").is_dir(),
    }


def migrate_layout(store_root: Path, source: str = "chatgpt", *,
                   dry_run: bool = False,
                   progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    say = progress or (lambda _m: None)
    store = Path(store_root)
    plan = plan_layout_migration(store, source)
    if plan["already_migrated"]:
        return {**plan, "migrated": False, "reason": "already-migrated"}
    if not plan["legacy_conversations"] and not plan["legacy_library"]:
        # Frisch: Struktur anlegen, nichts verschieben.
        if not dry_run:
            (store / source / "conversations").mkdir(parents=True, exist_ok=True)
            (store.parent / ".storage" / "runs").mkdir(parents=True, exist_ok=True)
            (store.parent / ".storage" / "status_registry").mkdir(parents=True, exist_ok=True)
            (store.parent / ".storage" / "staging").mkdir(parents=True, exist_ok=True)
        return {**plan, "migrated": True, "reason": "fresh-structure-created",
                "moved_conversations": 0}

    target = store / source
    runtime = store.parent / ".storage"
    moved_conversations = 0
    for path in sorted((store / "conversations").rglob("*.json")):
        bucket = _bucket_for(path)
        dest = target / "conversations" / bucket / path.name
        if _move_file(path, dest, dry_run=dry_run):
            moved_conversations += 1
    if not dry_run:
        # Leere Bucket-Reste entfernen.
        for bucket_dir in sorted((store / "conversations").rglob("*"), reverse=True):
            if bucket_dir.is_dir():
                try:
                    bucket_dir.rmdir()
                except OSError:
                    pass
        try:
            (store / "conversations").rmdir()
        except OSError:
            pass

    moved_library = _move_dir(store / "library", target, dry_run=dry_run)
    if not dry_run:
        (runtime / "runs").mkdir(parents=True, exist_ok=True)
        (runtime / "status_registry").mkdir(parents=True, exist_ok=True)
        (runtime / "staging").mkdir(parents=True, exist_ok=True)

    moved_runs = 0
    if (store / "runs").is_dir():
        for manifest in sorted((store / "runs").glob("*.json")):
            if _move_file(manifest, runtime / "runs" / manifest.name, dry_run=dry_run):
                moved_runs += 1
        if not dry_run:
            try:
                (store / "runs").rmdir()
            except OSError:
                pass

    moved_index = False
    if (store / "storage_index.json").is_file():
        if dry_run:
            moved_index = True
        else:
            dest = runtime / "status_registry" / "storage_index.json.previous-layout"
            dest.parent.mkdir(parents=True, exist_ok=True)
            (store / "storage_index.json").rename(dest)
            moved_index = True

    moved_status = _move_dir(store.parent / "status_registry", runtime, dry_run=dry_run)
    moved_staging = _move_dir(store / ".staging", runtime, dry_run=dry_run)
    moved_quarantine = False
    if (store / "quarantine.json").is_file():
        if dry_run:
            moved_quarantine = True
        else:
            dest = runtime / "status_registry" / "quarantine.json"
            if not dest.exists():
                (store / "quarantine.json").rename(dest)
                moved_quarantine = True

    say(f"Layout-Migration{' (dry-run)' if dry_run else ''}: "
        f"{moved_conversations} Conversations, Library={moved_library}, "
        f"Runs={moved_runs}, Status={moved_status}.")
    return {
        **plan,
        "migrated": not dry_run,
        "dry_run": dry_run,
        "moved_conversations": moved_conversations,
        "moved_library": moved_library,
        "moved_runs": moved_runs,
        "moved_index_archived": moved_index,
        "moved_status_registry": moved_status,
        "moved_staging": moved_staging,
        "moved_quarantine": moved_quarantine,
        "target": str(target / "conversations"),
        "runtime": str(runtime),
    }
