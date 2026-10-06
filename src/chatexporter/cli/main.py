"""Einstiegspunkt ``chatexporter``.

- ohne Argumente: menügeführte Bedienung (``menu.py``)
- ``chatexporter <updater-befehl> ...``: update | index | check | cleanup | status
- ``chatexporter <quelle> ...``: Kommandozeile des jeweiligen Providers
  (chatgpt | opencode | codex | claude)
- ``chatexporter export ...``: Exporte (Markdown/JSON) aus dem Raw Storage
- ``chatexporter task ...``: Zeitplanung (create | get | list | update | delete | pause | resume)
- ``chatexporter config ...``: Storage-Konfiguration (get | set | reset | refresh | path | list)
- ``chatexporter config-global ...``: globale Konfiguration (dieselben Befehle)
- ``chatexporter setup``: Ersteinrichtung (``setup.py``)
- ``chatexporter uninstall``: Deinstallation (``uninstall.py``)
- globale Optionen vor dem Befehl: ``--config DATEI``, ``--storage PFAD``,
  ``--set SCHLUESSEL=WERT`` (mehrfach)

Die Bedienschicht enthaelt keine Fachlogik; sie verteilt nur an Raw Session Updater,
Provider, Exporter, Zeitplanung und Konfiguration.
"""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path
from typing import Callable

import chatexporter.config as shared_config
import chatexporter.config.storage as storage_mod
from chatexporter import __version__
from chatexporter.config.cli import main as config_cli_main
from chatexporter.exporter.cli import main as export_cli_main
from chatexporter.raw_session_updater.cli import COMMANDS as UPDATER_COMMANDS
from chatexporter.raw_session_updater.cli import main as updater_main
from chatexporter.raw_session_updater.config import discover_config
from chatexporter.task_scheduler.cli import COMMANDS as TASK_COMMANDS  # noqa: F401
from chatexporter.task_scheduler.cli import main as task_cli_main

from . import storage_state
from .command_log import run_logged
from .continuation import after_update as continuation_after_update

#: Kommandozeilen der Provider (Modul, Funktion).
PROVIDER_CLIS: dict[str, tuple[str, str]] = {
    "chatgpt": ("chatexporter.providers.chatgpt.cli", "main"),
    "opencode": ("chatexporter.providers.opencode", "main"),
    "codex": ("chatexporter.providers.codex", "main"),
    "claude": ("chatexporter.providers.claude", "main"),
}

USAGE = f"""chatexporter {__version__} – Raw Session Updater über mehrere Quellen

Aufruf:
  chatexporter                         Menü
  chatexporter [--config DATEI] [--storage PFAD] [--set SCHLUESSEL=WERT ...] BEFEHL [OPTIONEN]

Raw Session Updater (alle aktiven Quellen):
  update    Alle Quellen aktualisieren            (--source, --listing-mode, --no-files, ...)
  index     Gesamtindex neu aufbauen
  check     Alle Quellen prüfen (read-only)       (--deep, --source)
  cleanup   Reste entfernen                 (--dry-run, --source)
  status    Momentaufnahme + OVERVIEW.md    (--source)

Exporte (aus dem Raw Storage, ohne Netz):
  export    Markdown und JSON erzeugen            (export json | export md; --source, --export-root)

Konfiguration:
  config         get | set | reset | refresh | path | list   – Storage-Konfiguration (chatexporter config -h)
  config-global  get | set | reset | refresh | path | list   – globale config.yaml

Zeitplanung (Windows-Aufgabenplanung):
  task      create | get | list | update | delete | pause | resume   (chatexporter task -h)

Storage (Datenbestand):
  storage        show | migrate   (Ort, Format, Zustand; altes Format umstellen)

Einrichtung:
  setup     Konfiguration, Browser/ChatGPT-Anmeldung, täglicher Abruf (fragt bei jedem Schritt)
  uninstall Deinstallieren: Aufgaben, Programm, Registry (--yes, --silent); Daten bleiben erhalten

Einzelne Quelle (eigene Kommandozeile des Providers):
  chatgpt   update | doctor | import-data | check-health | ... (chatexporter chatgpt -h)
  opencode | codex | claude   update | recreate-index | check-health | cleanup | stats

Hilfe zu einem Befehl: chatexporter BEFEHL -h
"""


def _after_update(manifest: dict, config_file: Path | None) -> dict:
    """Nach jedem Update: Zustand des Storages vermerken, Fortsetzung planen oder aufraeumen."""
    storage_state.record_update(manifest, config_file)
    return continuation_after_update(manifest, config_file, say=lambda line: print(line, flush=True))


def _provider_main(source: str) -> Callable[[list[str]], int]:
    module_name, func = PROVIDER_CLIS[source]
    return getattr(import_module(module_name), func)


def run_provider(source: str, argv: list[str], config: Path | None = None) -> int:
    """Startet die Kommandozeile eines Providers mit der gemeinsamen config.yaml.

    Die eigenstaendigen Provider suchen ihre config.yaml sonst neben ihrem
    Modul; deshalb wird der gefundene Pfad explizit uebergeben.
    """
    args = list(argv)
    if "--config" not in args and not any(a.startswith("--config=") for a in args):
        found = discover_config(config)
        if found is not None:
            args = ["--config", str(found), *args]
    return int(_provider_main(source)(args) or 0)


def dispatch(argv: list[str], config: Path | None = None) -> int:
    """Fuehrt einen Befehl aus (von Kommandozeile und Menue genutzt)."""
    if not argv:
        print(USAGE)
        return 2
    command, rest = argv[0], list(argv[1:])
    if command in UPDATER_COMMANDS:
        if config is not None and "--config" not in rest:
            rest = [*rest, "--config", str(config)]
        return updater_main([command, *rest], after_update=_after_update)
    if command in PROVIDER_CLIS:
        return run_provider(command, rest, config)
    if command == "export":
        if config is not None and "--config" not in rest:
            rest = [*rest, "--config", str(config)]
        return export_cli_main(rest, prog="chatexporter export")
    if command in ("config", "config-global"):
        if config is not None and "--config" not in rest:
            rest = ["--config", str(config), *rest]
        return config_cli_main(rest, prog=f"chatexporter {command}",
                               scope="global" if command == "config-global" else "storage")
    if command == "task":
        if config is not None and "--config" not in rest:
            rest = ["--config", str(config), *rest]
        return task_cli_main(rest, prog="chatexporter task")
    if command == "setup":
        from .setup import run_setup
        return run_setup(rest, config)
    if command == "storage":
        from .storage_cli import main as storage_cli_main
        return storage_cli_main(rest, config)
    if command == "uninstall":
        from .uninstall import run_uninstall
        return run_uninstall(rest, config)
    print(f"Unbekannter Befehl: {command}\n", file=sys.stderr)
    print(USAGE)
    return 2


#: Befehle, die auch ohne benutzbaren Storage laufen (Konfiguration, Storage-Verwaltung, Deinstallation).
STORAGE_FREE = frozenset({"config", "config-global", "storage", "uninstall", "-h", "--help", "help",
                          "-V", "--version", "version", "menu"})


def check_storage(command: str, config: Path | None) -> int | None:
    """Vor jedem Befehl, der mit Daten arbeitet: Storage benutzbar? Sonst Exitcode 2.

    Ein leerer Ordner wird dabei als Storage angelegt; ein Ordner im alten oder
    unklaren Format wird nicht angefasst (Hinweis auf ``storage migrate``).
    """
    if command in STORAGE_FREE:
        return None
    try:
        shared_config.require_storage(shared_config.load(config))
    except shared_config.StorageError as exc:
        print(f"FEHLER (Storage): {exc}", file=sys.stderr)
        return 2
    except (shared_config.ConfigError, OSError):
        return None          # meldet der Befehl selbst
    return None


#: Befehle des Raw Session Updaters, die schreiben (Sperre je Storage).
LOCKED_COMMANDS = frozenset({"update", "index", "cleanup", "export"})
#: Unterbefehle der Provider, die den Storage nicht veraendern (ohne Sperre).
READONLY_PROVIDER_COMMANDS = frozenset({"check-health", "stats", "doctor", "browser-setup", "recreate-index",
                                        "scenarios"})
#: Optionen der Provider-Kommandozeilen, auf die ein Wert folgt.
_VALUE_OPTIONS = frozenset({"--config", "--raw-root", "--data-root", "--source-root", "--opencode-exe",
                            "--db-path", "--cli-cwd", "--timeout", "--retries"})


def needs_lock(command: str, rest: list[str]) -> bool:
    if command in LOCKED_COMMANDS:
        return True
    if command not in PROVIDER_CLIS:
        return False
    skip = False
    for arg in rest:
        if skip:
            skip = False
            continue
        if arg in _VALUE_OPTIONS:
            skip = True
            continue
        if arg.startswith("-"):
            continue
        return arg not in READONLY_PROVIDER_COMMANDS
    return False


#: Befehle ohne Nacharbeit am Storage (Hilfe, Version, Menue, Deinstallation).
NO_AFTERWORK = frozenset({"-h", "--help", "help", "-V", "--version", "version", "menu", "uninstall"})


def after_command(config: Path | None, command: str = "", exit_code: int | None = None,
                  line: str | None = None) -> None:
    """Nach jedem Befehl auf einem Storage: leere Zwischenablagen entfernen, Zustand und
    ``state.yaml`` aktualisieren. Wirft nie."""
    try:
        status = shared_config.storage_status(shared_config.load(config))
        if status["identity"] is not None:
            storage_mod.cleanup_staging(status["storage"])
            storage_state.after_command(config, command, exit_code, line=line)
    except Exception:  # noqa: BLE001
        pass


def _guarded(command: str, rest: list[str], config: Path | None, program: str, argv: list[str],
             run: Callable[[], int]) -> int:
    """Storage pruefen, bei schreibenden Befehlen sperren, ausfuehren, protokollieren, aufraeumen.

    Gespeichert wird nur die verdeckte Befehlszeile (``redact_cli_args``): keine Secrets in
    Befehlsprotokoll, Sperrdatei, Registry oder ``state.yaml``."""
    argv = redact_cli_args(argv)
    blocked = check_storage(command, config)
    if blocked is not None:
        return blocked
    code: int | None = None
    try:
        if not needs_lock(command, rest):
            code = run_logged(program, argv, run)
            return code
        storage = shared_config.storage_of(shared_config.load(config))
        try:
            with storage_mod.storage_lock(storage, " ".join([program, *argv])):
                code = run_logged(program, argv, run)
                return code
        except storage_mod.StorageBusy as exc:
            print(f"FEHLER (Storage belegt): {exc}", file=sys.stderr)
            code = 2
            return code
    finally:
        if command not in NO_AFTERWORK:
            after_command(config, command, code, " ".join([program, *argv]))


def split_global_options(args: list[str]) -> tuple[Path | None, list[str], list[str]]:
    """Globale Optionen vor dem Befehl: ``--config DATEI``, ``--storage PFAD`` (= ``--set
    storage.root=PFAD``) und ``--set SCHLUESSEL=WERT`` (mehrfach).

    Rueckgabe: (config, CLI-Werte, uebrige Argumente).
    """
    config: Path | None = None
    sets: list[str] = []
    rest = list(args)
    while rest:
        if rest[0] == "--config" and len(rest) >= 2:
            config = Path(rest[1])
            rest = rest[2:]
        elif rest[0].startswith("--config="):
            config = Path(rest[0].split("=", 1)[1])
            rest = rest[1:]
        elif rest[0] == "--storage" and len(rest) >= 2:
            sets.append(f"storage.root={Path(rest[1]).expanduser().resolve()}")
            rest = rest[2:]
        elif rest[0].startswith("--storage="):
            sets.append(f"storage.root={Path(rest[0].split('=', 1)[1]).expanduser().resolve()}")
            rest = rest[1:]
        elif rest[0] == "--set" and len(rest) >= 2:
            sets.append(rest[1])
            rest = rest[2:]
        elif rest[0].startswith("--set="):
            sets.append(rest[0].split("=", 1)[1])
            rest = rest[1:]
        else:
            break
    return config, sets, rest


#: Ersatz fuer den Wert eines geheimen Schluessels in gespeicherten Befehlszeilen.
REDACTED = "(verdeckt)"


def redact_cli_args(args: list[str]) -> list[str]:
    """Befehlszeile zum Speichern (Befehlsprotokoll, ``state.yaml``/Registry, Sperrdatei):
    Werte geheimer Schluessel in ``--set SCHLUESSEL=WERT`` / ``--set=SCHLUESSEL=WERT`` verdecken."""
    secrets = shared_config.SCHEMA.secrets()

    def hide(item: str) -> str:
        key, sep, _value = item.partition("=")
        return f"{key}{sep}{REDACTED}" if sep and key.strip() in secrets else item

    shown: list[str] = []
    after_set = False
    for arg in args:
        if after_set:
            shown.append(hide(arg))
            after_set = False
        elif arg == "--set":
            shown.append(arg)
            after_set = True
        elif arg.startswith("--set="):
            shown.append("--set=" + hide(arg[len("--set="):]))
        else:
            shown.append(arg)
    return shown


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    config, sets, args = split_global_options(raw)
    # CLI-Werte gelten fuer alle Schichten dieses Prozesses (hoechster Vorrang).
    shared_config.set_cli_overrides(sets)
    if not args or args[0] == "menu":
        # Das Menue selbst wird nicht protokolliert; jeder gewaehlte Punkt
        # laeuft als eigener Prozess ueber main() und wird dort protokolliert.
        from .menu import run_menu
        return run_menu(config=config)

    def run() -> int:
        if args[0] in ("-h", "--help", "help"):
            print(USAGE)
            return 0
        if args[0] in ("-V", "--version", "version"):
            print(__version__)
            return 0
        return dispatch(args, config)

    return _guarded(args[0], args[1:], config, "chatexporter", raw, run)


def _provider_entry(source: str) -> Callable[[list[str] | None], int]:
    def entry(argv: list[str] | None = None) -> int:
        args = list(sys.argv[1:] if argv is None else argv)
        return _guarded(source, args, _explicit_config(args), f"chatexporter-{source}", args,
                        lambda: run_provider(source, args))
    entry.__name__ = f"{source}_main"
    entry.__doc__ = f"Einzelbefehl chatexporter-{source}."
    return entry


chatgpt_main = _provider_entry("chatgpt")
opencode_main = _provider_entry("opencode")
codex_main = _provider_entry("codex")
claude_main = _provider_entry("claude")


def _updater_entry(command: str) -> Callable[[list[str] | None], int]:
    def entry(argv: list[str] | None = None) -> int:
        args = list(sys.argv[1:] if argv is None else argv)
        return _guarded(command, args, _explicit_config(args), f"chatexporter-{command}", args,
                        lambda: updater_main([command, *args], prog=f"chatexporter-{command}",
                                             after_update=_after_update))
    entry.__name__ = f"{command}_main"
    entry.__doc__ = f"Einzelbefehl chatexporter-{command} (protokolliert)."
    return entry


def _explicit_config(args: list[str]) -> Path | None:
    for i, arg in enumerate(args):
        if arg == "--config" and i + 1 < len(args):
            return Path(args[i + 1])
        if arg.startswith("--config="):
            return Path(arg.split("=", 1)[1])
    return None


def export_main(argv: list[str] | None = None) -> int:
    """Einzelbefehl chatexporter-export (protokolliert)."""
    args = list(sys.argv[1:] if argv is None else argv)
    return _guarded("export", args, _explicit_config(args), "chatexporter-export", args,
                    lambda: export_cli_main(args, prog="chatexporter-export"))


def config_main(argv: list[str] | None = None) -> int:
    """Einzelbefehl chatexporter-config (protokolliert)."""
    args = list(sys.argv[1:] if argv is None else argv)
    return _guarded("config", args, _explicit_config(args), "chatexporter-config", args,
                    lambda: config_cli_main(args, prog="chatexporter-config"))


def task_main(argv: list[str] | None = None) -> int:
    """Einzelbefehl chatexporter-task (protokolliert)."""
    args = list(sys.argv[1:] if argv is None else argv)
    return _guarded("task", args, _explicit_config(args), "chatexporter-task", args,
                    lambda: task_cli_main(args, prog="chatexporter-task"))


update_main = _updater_entry("update")
index_main = _updater_entry("index")
check_main = _updater_entry("check")
cleanup_main = _updater_entry("cleanup")
status_main = _updater_entry("status")


if __name__ == "__main__":
    raise SystemExit(main())
