"""Kommandozeile der Zeitplanung: ``chatexporter task <befehl>``.

    create   Aufgabe anlegen
    get      eine Aufgabe anzeigen
    list     alle Aufgaben anzeigen
    update   Aufgabe aendern (Befehl, Zeitplan, Einstellungen, Name)
    delete   Aufgabe loeschen (--all: alle eigenen Aufgaben)
    pause    Aufgabe pausieren (deaktivieren)
    resume   pausierte Aufgabe fortsetzen

Exitcodes: 0 ok, 1 fachlicher Fehler (Aufgabe fehlt/existiert, ungueltige
Eingabe), 2 Einrichtung (keine config.yaml, pywin32/Windows fehlt).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

from .config import TaskSetupError, load_config
from .service import (MULTIPLE_INSTANCES, SCHEDULABLE_COMMANDS, TaskService, TaskServiceError,
                      build_trigger)

COMMANDS = ("create", "get", "list", "update", "delete", "pause", "resume")


def _common() -> argparse.ArgumentParser:
    """Optionen, die vor und nach dem Befehl stehen duerfen (Vorrang: CLI > Env > config.yaml)."""
    parent = argparse.ArgumentParser(add_help=False)
    suppress = argparse.SUPPRESS
    parent.add_argument("--config", default=suppress, help="gemeinsame config.yaml")
    parent.add_argument("--folder", default=suppress, help="Ordner in der Windows-Aufgabenplanung")
    parent.add_argument("--owner", default=suppress, help="Eigentuemer-Kennung der Aufgaben")
    parent.add_argument("--state-file", default=suppress, help="lokale State-Datei (tasks_sched.json)")
    parent.add_argument("--global-state-file", default=suppress, help="globale State-Datei")
    parent.add_argument("--python", default=suppress, help="Python-Interpreter der geplanten Befehle")
    parent.add_argument("--json", action="store_true", default=suppress, help="Ausgabe als JSON")
    return parent


def _add_trigger_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("Zeitplan (genau ein Trigger)")
    group.add_argument("--daily", metavar="HH:MM", help="taeglich zu dieser Uhrzeit")
    group.add_argument("--weekly", metavar="HH:MM", help="woechentlich zu dieser Uhrzeit (mit --days)")
    group.add_argument("--once", metavar="'JJJJ-MM-TT HH:MM'", help="einmalig")
    group.add_argument("--logon", action="store_true", help="bei Anmeldung")
    group.add_argument("--startup", action="store_true", help="bei Systemstart (Administratorrechte noetig)")
    group.add_argument("--days", metavar="mo,mi,fr", help="Wochentage fuer --weekly")
    group.add_argument("--every", type=int, metavar="N", help="alle N Tage/Wochen")
    group.add_argument("--delay", type=int, metavar="SEK", help="Verzoegerung fuer --logon/--startup")


def _add_setting_options(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("Einstellungen (Standard: task_scheduler.defaults)")
    group.add_argument("--max-runtime", type=float, metavar="MIN", help="Zeitlimit je Lauf in Minuten")
    group.add_argument("--wake-to-run", action=argparse.BooleanOptionalAction, default=None,
                       help="Rechner dafuer aus dem Ruhezustand wecken")
    group.add_argument("--allow-on-battery", action=argparse.BooleanOptionalAction, default=None,
                       help="auch im Akkubetrieb starten")
    group.add_argument("--start-when-available", action=argparse.BooleanOptionalAction, default=None,
                       help="verpassten Lauf nachholen")
    group.add_argument("--hidden", action=argparse.BooleanOptionalAction, default=None,
                       help="Aufgabe in der Aufgabenplanung verbergen")
    group.add_argument("--multiple-instances", choices=MULTIPLE_INSTANCES,
                       help="Verhalten, wenn der vorige Lauf noch laeuft")


def build_parser(prog: str = "chatexporter task") -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(
        prog=prog, parents=[common],
        description="Chatexporter-Befehle als Windows-Aufgaben planen (Aufgabenplanung).")
    sub = parser.add_subparsers(dest="command", metavar="BEFEHL")
    command_help = f"Befehl der Aufgabe, z. B. \"update --source chatgpt\" (erlaubt: {', '.join(SCHEDULABLE_COMMANDS)})"

    create = sub.add_parser("create", parents=[common], help="Aufgabe anlegen")
    create.add_argument("name", help="Anzeigename; daraus wird der Kurzname (slug) gebildet")
    create.add_argument("--slug", help="Kurzname statt des aus dem Namen gebildeten")
    create.add_argument("--command", dest="task_command", help=command_help)
    create.add_argument("--description")
    create.add_argument("--paused", action="store_true", help="pausiert anlegen")
    _add_trigger_options(create)
    _add_setting_options(create)

    get = sub.add_parser("get", parents=[common], help="Aufgabe anzeigen")
    get.add_argument("ref", help="Kurzname, Name oder ID")

    sub.add_parser("list", parents=[common], help="alle Aufgaben anzeigen")

    update = sub.add_parser("update", parents=[common], help="Aufgabe aendern")
    update.add_argument("ref", help="Kurzname, Name oder ID")
    update.add_argument("--name", help="neuer Anzeigename (Kurzname und ID bleiben)")
    update.add_argument("--command", dest="task_command", help=command_help)
    update.add_argument("--description")
    _add_trigger_options(update)
    _add_setting_options(update)

    delete = sub.add_parser("delete", parents=[common], help="Aufgabe loeschen")
    delete.add_argument("ref", nargs="?", help="Kurzname, Name oder ID")
    delete.add_argument("--all", dest="delete_all", action="store_true",
                        help="alle Aufgaben dieses Eigentuemers loeschen (z. B. vor der Deinstallation)")
    delete.add_argument("-y", "--yes", action="store_true", help="ohne Rueckfrage")

    for name, text in (("pause", "Aufgabe pausieren"), ("resume", "Aufgabe fortsetzen")):
        child = sub.add_parser(name, parents=[common], help=text)
        child.add_argument("ref", help="Kurzname, Name oder ID")
    return parser


def _settings(args: argparse.Namespace) -> dict[str, Any]:
    return {"max_runtime_minutes": args.max_runtime, "wake_to_run": args.wake_to_run,
            "allow_on_battery": args.allow_on_battery,
            "start_when_available": args.start_when_available, "hidden": args.hidden,
            "multiple_instances": args.multiple_instances}


def _trigger(args: argparse.Namespace) -> dict[str, Any] | None:
    return build_trigger(daily=args.daily, weekly=args.weekly, once=args.once, logon=args.logon,
                         startup=args.startup, days=args.days, every=args.every, delay=args.delay)


def _show(view: dict[str, Any], say: Callable[[str], None]) -> None:
    rows = (("Name", view["name"]), ("Kurzname", view["slug"]), ("ID", view["task_id"]),
            ("Zustand", view["state"] if view["exists"] else "fehlt in der Aufgabenplanung"),
            ("Befehl", view["command"] or "(unbekannt)"), ("Zeitplan", view["trigger"]),
            ("Naechster Lauf", view["next_run"] or "-"), ("Letzter Lauf", view["last_run"] or "-"),
            ("Letztes Ergebnis", view["last_result"] if view["last_result"] is not None else "-"),
            ("Windows-Pfad", view["scheduler_path"]))
    for label, value in rows:
        say(f"{label + ':':18}{value}")


def _table(views: Sequence[dict[str, Any]], say: Callable[[str], None]) -> None:
    if not views:
        say("Keine Aufgaben gefunden.")
        return
    header = ("KURZNAME", "ZUSTAND", "ZEITPLAN", "NAECHSTER LAUF", "BEFEHL")
    rows = [(v["slug"], v["state"] if v["exists"] else "fehlt", v["trigger"],
             v["next_run"] or "-", v["command"] or "-") for v in views]
    widths = [max(len(str(r[i])) for r in [header, *rows]) for i in range(len(header))]
    for row in [header, *rows]:
        say("  ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)).rstrip())


def _emit_json(payload: Any, say: Callable[[str], None]) -> None:
    say(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def main(argv: Sequence[str] | None = None, *, prog: str = "chatexporter task",
         say: Callable[[str], None] = print, ask: Callable[[str], str] = input,
         service_factory: Callable[[Any], TaskService] = TaskService) -> int:
    args = build_parser(prog).parse_args(list(sys.argv[1:] if argv is None else argv))
    if not args.command:
        build_parser(prog).print_help()
        return 2
    as_json = getattr(args, "json", False)
    try:
        config = load_config(
            Path(args.config) if getattr(args, "config", None) else None,
            overrides={"folder": getattr(args, "folder", None), "owner": getattr(args, "owner", None),
                       "state_file": getattr(args, "state_file", None),
                       "global_state_file": getattr(args, "global_state_file", None),
                       "python": getattr(args, "python", None)})
        service = service_factory(config)

        if args.command == "create":
            view = service.create(args.name, slug=args.slug, command=args.task_command,
                                  trigger=_trigger(args), description=args.description,
                                  enabled=not args.paused, settings=_settings(args))
            if as_json:
                _emit_json(view, say)
            else:
                say(f"Aufgabe angelegt: {view['slug']} ({view['task_id']})")
                _show(view, say)
        elif args.command == "get":
            view = service.get(args.ref)
            _emit_json(view, say) if as_json else _show(view, say)
        elif args.command == "list":
            views = service.list()
            _emit_json(views, say) if as_json else _table(views, say)
        elif args.command == "update":
            view = service.update(args.ref, name=args.name, command=args.task_command,
                                  trigger=_trigger(args), description=args.description,
                                  settings=_settings(args))
            if as_json:
                _emit_json(view, say)
            else:
                say(f"Aufgabe geaendert: {view['slug']} ({view['task_id']})")
                _show(view, say)
        elif args.command == "delete" and args.delete_all:
            if args.ref:
                raise TaskServiceError("delete: entweder eine Aufgabe oder --all angeben")
            views = service.list()
            if not views:
                _emit_json({"deleted": []}, say) if as_json else say("Keine Aufgaben vorhanden.")
                return 0
            if not args.yes:
                try:
                    answer = ask(f"Alle {len(views)} Aufgaben ({', '.join(v['slug'] for v in views)}) "
                                 f"wirklich loeschen? [j/N] ")
                except EOFError:
                    answer = ""
                if answer.strip().lower() not in ("j", "ja", "y", "yes"):
                    say("Abgebrochen.")
                    return 1
            removed = service.delete_all()
            if as_json:
                _emit_json({"deleted": [v["task_id"] for v in removed]}, say)
            else:
                for view in removed:
                    say(f"Aufgabe geloescht: {view['slug']} ({view['task_id']})")
        elif args.command == "delete":
            if not args.ref:
                raise TaskServiceError("delete: Aufgabe (Kurzname, Name oder ID) oder --all angeben")
            view = service.get(args.ref)
            if not args.yes:
                try:
                    answer = ask(f"Aufgabe '{view['slug']}' ({view['task_id']}) wirklich loeschen? [j/N] ")
                except EOFError:
                    answer = ""
                if answer.strip().lower() not in ("j", "ja", "y", "yes"):
                    say("Abgebrochen.")
                    return 1
            service.delete(view["task_id"])
            if as_json:
                _emit_json({"deleted": view["task_id"], "slug": view["slug"]}, say)
            else:
                say(f"Aufgabe geloescht: {view['slug']} ({view['task_id']})")
        elif args.command in ("pause", "resume"):
            view = service.pause(args.ref) if args.command == "pause" else service.resume(args.ref)
            if as_json:
                _emit_json(view, say)
            else:
                verb = "pausiert" if args.command == "pause" else "fortgesetzt"
                say(f"Aufgabe {verb}: {view['slug']} (Zustand: {view['state']})")
        return 0
    except TaskSetupError as exc:
        print(f"FEHLER (Einrichtung): {exc}", file=sys.stderr)
        return 2
    except TaskServiceError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
