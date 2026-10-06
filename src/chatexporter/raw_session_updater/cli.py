"""Kommandozeile des Raw Session Updaters.

Einzelbefehle (installiert ueber pyproject.toml):

    chatexporter-update    Alle Quellen aktualisieren (alle oder gewaehlte Quellen)
    chatexporter-index     Gesamtindex aus den Fragmenten neu aufbauen
    chatexporter-check     Alle Quellen pruefen (read-only)
    chatexporter-cleanup   Definierte Reste entfernen (niemals Quelldaten)
    chatexporter-status    Momentaufnahme + .storage/OVERVIEW.md

Dieselben Befehle stehen unter ``chatexporter <befehl>`` zur Verfuegung.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Any

from . import operations
from .config import load_updater_config, program_banner
from .registry import KNOWN_SOURCES

COMMANDS = ("update", "index", "check", "cleanup", "status")


def _common(parser: argparse.ArgumentParser, *, with_sources: bool = True) -> None:
    parser.add_argument("--config", type=Path, default=None,
                        help="Gemeinsame config.yaml (Standard: CHATEXPORTER_CONFIG oder Suche ab Arbeitsordner)")
    if with_sources:
        parser.add_argument("--source", action="append", choices=KNOWN_SOURCES, dest="sources",
                            help="Nur diese Quelle(n) (mehrfach angebbar; Standard: raw_session_updater.sources)")


def build_parser(prog: str = "chatexporter") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, description="Raw Session Updater ueber alle Quellen")
    sub = p.add_subparsers(dest="command", required=True, metavar="befehl")

    u = sub.add_parser("update", help="Alle Quellen aktualisieren (alle aktiven oder gewaehlte Quellen)")
    _common(u)
    u.add_argument("--no-files", action="store_true", help="ChatGPT: keine Dateien/Anhaenge laden")
    u.add_argument("--non-interactive", action="store_true", help="ChatGPT: keine interaktive Anmeldung")
    u.add_argument("--listing-mode", choices=("auto", "full", "recent"), default=None,
                   help="ChatGPT: auto (Standard) = recent, bei Bedarf full; full = komplett; recent = nur zuletzt geaenderte")

    i = sub.add_parser("index", help="Gesamtindex aus den Fragmenten aller Quellen neu aufbauen")
    _common(i, with_sources=False)

    c = sub.add_parser("check", help="Alle Quellen pruefen (read-only)")
    _common(c)
    c.add_argument("--deep", action="store_true", help="Gruendlich (hasht Inhalte, langsamer)")

    cl = sub.add_parser("cleanup", help="Definierte Reste entfernen (niemals Quelldaten)")
    _common(cl)
    cl.add_argument("--dry-run", action="store_true", help="Nur zaehlen, nichts entfernen")

    s = sub.add_parser("status", help="Momentaufnahme aller Quellen + .storage/OVERVIEW.md")
    _common(s)
    return p


def _print(report: Any) -> None:
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


def main(argv: list[str] | None = None, *, prog: str = "chatexporter",
         after_update: Callable[[dict[str, Any], Path | None], dict[str, Any]] | None = None) -> int:
    """``after_update`` (optional, von der Bedienschicht): wird nach einem Update mit dem
    Laufbericht aufgerufen; seine Rueckgabe erscheint im abschliessenden Bericht."""
    args = build_parser(prog).parse_args(argv)
    try:
        cfg = load_updater_config(args.config)
    except (ValueError, OSError) as exc:
        print(f"Konfigurationsfehler: {exc}", file=sys.stderr)
        return 2
    say = lambda message: print(message, flush=True)  # noqa: E731
    sources = getattr(args, "sources", None)
    if args.command == "update":
        # Vorab sichtbar machen, WELCHER Programmstand mit WELCHER Config laeuft.
        for line in program_banner():
            say(line)
        say(f"Konfiguration:  {cfg.config_file or '(keine config.yaml gefunden – Defaults)'}")
        manifest, code = operations.update(
            cfg, sources=sources, no_files=args.no_files,
            non_interactive=args.non_interactive, listing_mode=args.listing_mode,
            progress=say)
        report = {"run_manifest": manifest.get("run_manifest"),
                  "partial": manifest.get("partial"),
                  "totals": manifest.get("totals")}
        if after_update is not None:
            report.update(after_update(manifest, cfg.config_file) or {})
        _print(report)
        return code
    if args.command == "index":
        report, code = operations.rebuild_index(cfg)
    elif args.command == "check":
        report, code = operations.check_health(cfg, deep=args.deep, sources=sources)
    elif args.command == "cleanup":
        report, code = operations.cleanup(cfg, dry_run=args.dry_run, sources=sources)
    else:
        report, code = operations.status(cfg, sources=sources)
    _print(report)
    return code


def _single(command: str):
    def entry(argv: list[str] | None = None) -> int:
        rest = sys.argv[1:] if argv is None else argv
        return main([command, *rest], prog=f"chatexporter-{command}")
    entry.__name__ = f"{command}_main"
    entry.__doc__ = f"Einzelbefehl chatexporter-{command}."
    return entry


update_main = _single("update")
index_main = _single("index")
check_main = _single("check")
cleanup_main = _single("cleanup")
status_main = _single("status")


if __name__ == "__main__":
    raise SystemExit(main())
