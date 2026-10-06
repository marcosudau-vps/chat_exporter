"""Export aus dem Raw Storage."""

from __future__ import annotations

from typing import Any, Callable, Iterable

from ._io import atomic_write_json, now_iso
from .config import ExporterConfig
from .formats import build_formats
from .sources import iter_items

Progress = Callable[[str], None]


def export(cfg: ExporterConfig, *, formats: Iterable[str] | None = None,
           sources: Iterable[str] | None = None,
           progress: Progress | None = None) -> tuple[dict[str, Any], int]:
    """Erzeugt Exporte (Markdown/JSON) aus dem Raw Storage, ohne Netz.

    Liest ``cfg.raw_root`` ausschliesslich lesend und schreibt nur nach
    ``cfg.export_root`` (inklusive Manifest unter ``manifests/``). Jede
    Konversation wird in jedem Format neu geschrieben (idempotent). Rueckgabe:
    ``(Bericht, Exitcode)``; Exitcode 1, sobald ein Gespraech oder Format
    fehlgeschlagen ist.
    """
    say = progress or (lambda _m: None)
    names = tuple(formats) if formats is not None else cfg.formats
    chosen_sources = tuple(sources) if sources is not None else cfg.sources
    chosen = build_formats(names)
    started = now_iso()
    conversations = 0
    outputs: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    by_source: dict[str, int] = {}

    for source in chosen_sources:
        by_source[source] = 0
        for item in iter_items(source, cfg.raw_root):
            if item.view is None:
                errors.append({"source": source, "conversation_id": item.item_id,
                               "path": str(item.path), "error": item.error})
                say(f"FEHLER {source} {item.path.name}: {item.error}")
                continue
            conversations += 1
            by_source[source] += 1
            for fmt in chosen:
                try:
                    target = fmt.export(cfg.export_root, item.view, cfg.staging_dir)
                    outputs.append({"source": source, "conversation_id": item.item_id,
                                    "format": fmt.name,
                                    "path": target.relative_to(cfg.export_root).as_posix()})
                except Exception as exc:  # noqa: BLE001  ein Fehler darf die uebrigen nicht stoppen
                    errors.append({"source": source, "conversation_id": item.item_id,
                                   "format": fmt.name, "error": f"{type(exc).__name__}: {exc}"})
                    say(f"FEHLER {source} {item.item_id} {fmt.name}: {type(exc).__name__}: {exc}")

    finished = now_iso()
    manifest = {
        "schema_version": 2,
        "started_at": started,
        "finished_at": finished,
        "sources": list(chosen_sources),
        "formats": list(names),
        "conversations": conversations,
        "conversations_by_source": by_source,
        "files_written": len(outputs),
        "failures": len(errors),
        "outputs": outputs,
        "errors": errors,
    }
    manifest_path = cfg.manifests_dir / f"export_{finished.replace(':', '').replace('-', '')}.json"
    atomic_write_json(manifest_path, manifest, staging_dir=cfg.staging_dir)
    report = {
        "sources": list(chosen_sources),
        "formats": list(names),
        "raw_root": str(cfg.raw_root),
        "export_root": str(cfg.export_root),
        "conversations": conversations,
        "files_written": len(outputs),
        "failures": len(errors),
        "manifest": str(manifest_path),
    }
    return report, 1 if errors else 0
