"""Kommandozeile der Storages: ``chatexporter storage <befehl>``.

    show [--json]                        gewaehlter Storage: Ort, Format, Identitaet, Zustand, Pfade
    migrate [PFAD] [--dry-run] [--yes]   Datenordner im alten Format (pre-6) zum Storage umstellen
            [--fix-config]               dabei Einstellungen der globalen config.yaml entfernen,
                                         die noch in den alten Ordner ``runtime/`` zeigen

Die Migration arbeitet nur, wenn die Marker das alte Format eindeutig belegen
(``docs/STORAGE_KONZEPT.md``, Abschnitt 8); Rohdaten werden nicht angefasst.
Exitcodes: 0 ok, 1 abgebrochen/nicht moeglich, 2 Fehler.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

import chatexporter.config as shared_config
from chatexporter.config import state as state_mod
from chatexporter.config import storage as storage_mod

#: Einstellungen, die auf Orte im Verwaltungsbereich zeigen koennen.
PATH_KEYS = ("logging.dir", "storage.runtime_root", "storage.status_root", "task_scheduler.state_file")

Say = Callable[[str], None]


def build_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Storages (Datenbestaende) anzeigen und umstellen.")
    sub = parser.add_subparsers(dest="command", metavar="BEFEHL")
    show = sub.add_parser("show", help="gewaehlten Storage anzeigen")
    show.add_argument("--json", action="store_true")
    migrate = sub.add_parser("migrate", help="altes Format (pre-6) zum Storage umstellen")
    migrate.add_argument("path", nargs="?", type=Path, help="Ordner (Standard: der gewaehlte Storage)")
    migrate.add_argument("--dry-run", action="store_true", help="nur zeigen, was geschehen wuerde")
    migrate.add_argument("--yes", "-y", action="store_true", help="ohne Rueckfrage")
    migrate.add_argument("--fix-config", action="store_true",
                         help="Einstellungen entfernen, die in den alten Ordner runtime/ zeigen")
    return parser


def stale_settings(loaded: Any, root: Path) -> list[dict[str, Any]]:
    """Einstellungen, deren Pfad im alten Ordner ``<root>/runtime`` liegt."""
    legacy = (Path(root) / storage_mod.LEGACY_RUNTIME).resolve()
    out = []
    for key in PATH_KEYS:
        value = loaded.get(key)
        path = shared_config.resolve_path(loaded, value, key)
        if path is None:
            continue
        try:
            path.resolve().relative_to(legacy)
        except ValueError:
            continue
        out.append({"key": key, "value": value, "origin": loaded.origin(key)})
    return out


def _show(config: Path | None, as_json: bool, say: Say) -> int:
    loaded = shared_config.load(config)
    status = shared_config.storage_status(loaded)
    storage = status["storage"]
    identity = status["identity"]
    info: dict[str, Any] = {"root": str(storage.root), "format": status["format"], "reason": status["reason"],
                            "identity": identity.as_dict() if identity else None, "paths": storage.paths()}
    if identity is not None:
        info["state"] = state_mod.store_for(identity).read()
    if as_json:
        say(json.dumps(info, ensure_ascii=False, indent=2, default=str))
        return 0
    say(f"Storage:  {storage.root}")
    say(f"Format:   {status['format']} ({status['reason']}); Storage-Schema, nicht Programmversion")
    if identity is not None:
        say(f"ID:       {identity.id}   Name: {identity.name}   angelegt: {identity.created_at}")
        state = info["state"]
        for key in ("storage.update_counter", "storage.update_last", "storage.update_last_result",
                    "storage.update_next_scheduled_at", "storage.first_fetch.completed"):
            if key in state:
                say(f"  {key} = {state[key]}")
        say(f"Gesamtsicht: {storage.state_file}")
    elif status["format"] == storage_mod.FORMAT_LEGACY:
        say(f"Storage-Schema {storage_mod.LEGACY_STORAGE_SCHEMA} – umstellen auf Storage-Schema "
            f"{storage_mod.STORAGE_SCHEMA} mit: chatexporter storage migrate")
    elif status["format"] == storage_mod.FORMAT_INTERRUPTED:
        say("Umstellung abgebrochen – fortsetzen mit: chatexporter storage migrate")
    elif status["format"] == storage_mod.FORMAT_FOREIGN:
        say("Kein Storage: Ordner ist nicht leer. Einen leeren oder neuen Ordner waehlen (--storage PFAD).")
    return 0


def _migrate(args: argparse.Namespace, config: Path | None, say: Say, ask: Callable[[str], str]) -> int:
    loaded = shared_config.load(config)
    root = (args.path.expanduser().resolve() if args.path else shared_config.storage_of(loaded).root)
    fmt, reason = storage_mod.detect(root)
    say(f"Ordner: {root}")
    say(f"Format: {fmt} ({reason})")
    if fmt == storage_mod.FORMAT_CURRENT:
        say(f"Bereits Storage-Schema {storage_mod.STORAGE_SCHEMA} – nichts zu tun.")
        return 0
    if fmt not in (storage_mod.FORMAT_LEGACY, storage_mod.FORMAT_INTERRUPTED):
        say(f"Keine Migration: das Format ist nicht eindeutig Storage-Schema {storage_mod.LEGACY_STORAGE_SCHEMA}. "
            "Nichts wurde veraendert.")
        return 1
    if fmt == storage_mod.FORMAT_INTERRUPTED:
        say("Eine fruehere Umstellung wurde abgebrochen (oder der Marker ging verloren); sie wird fortgesetzt. "
            "Der Storage erhaelt dabei eine neue ID.")
    stale = stale_settings(loaded, root)
    for item in stale:
        say(f"Einstellung zeigt in den alten Ordner: {item['key']} = {item['value']} [{item['origin']}]")
    plan = storage_mod.migrate(root, dry_run=True)
    say("Geplante Schritte:")
    for step in plan["steps"]:
        say(f"  - {step}")
    if stale and not args.fix_config:
        say("Diese Einstellungen wuerden nach der Umstellung wieder einen Ordner runtime/ anlegen. "
            "Mit --fix-config entfernen (Sicherung der config.yaml wird angelegt) oder vorher selbst "
            "mit 'chatexporter config-global reset SCHLUESSEL' zuruecksetzen.")
        return 1
    unfixable = [item for item in stale if item["origin"] not in ("config",)]
    if unfixable:
        say("Nicht automatisch korrigierbar (Herkunft Umgebung/.env/--set): "
            + ", ".join(f"{i['key']} [{i['origin']}]" for i in unfixable))
        return 1
    if args.dry_run:
        say("Probelauf – nichts veraendert.")
        return 0
    if not args.yes:
        try:
            answer = ask("Jetzt umstellen? [j/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("j", "ja", "y", "yes"):
            say("Abgebrochen.")
            return 1
    for item in stale:
        shared_config.manager().reset(item["key"], explicit=config, target="base")
        say(f"Zurueckgesetzt in der globalen config.yaml: {item['key']}")
    result = storage_mod.migrate(root)
    say(f"Umgestellt: {root} hat jetzt Storage-Schema {storage_mod.STORAGE_SCHEMA} "
        f"(ID {result['identity']['id']}).")
    return 0


def main(argv: list[str], config: Path | None = None, *, prog: str = "chatexporter storage",
         say: Say = print, ask: Callable[[str], str] = input) -> int:
    args = build_parser(prog).parse_args(argv)
    try:
        if args.command in (None, "show"):
            return _show(config, getattr(args, "json", False), say)
        if args.command == "migrate":
            return _migrate(args, config, say, ask)
    except storage_mod.StorageError as exc:
        print(f"FEHLER (Storage): {exc}", file=sys.stderr)
        return 1
    except (shared_config.ConfigError, OSError) as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 2
    return 2
