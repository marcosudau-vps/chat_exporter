"""Menügeführte Bedienung (``chatexporter`` ohne Argumente).

Jeder Menüpunkt wird in denselben Befehl übersetzt, den man auch direkt
eingeben kann (siehe Anzeige "Befehl: ..."). Das Menü enthält keine eigene
Logik.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from chatexporter.raw_session_updater.config import load_updater_config, program_banner
from chatexporter.raw_session_updater.registry import KNOWN_SOURCES

Input = Callable[[str], str]
Output = Callable[[str], None]


@dataclass(frozen=True)
class MenuItem:
    key: str
    label: str
    argv: tuple[str, ...] = ()
    confirm: str | None = None
    #: Sonderpunkt, der vor der Ausfuehrung nachfragt (z. B. Quelle waehlen).
    special: str | None = None


GROUPS: tuple[tuple[str, tuple[MenuItem, ...]], ...] = (
    ("Raw Session Updater (alle aktiven Quellen)", (
        MenuItem("1", "Alle Quellen aktualisieren (ChatGPT-Listing laut Config, Standard auto)",
                 ("update",)),
        MenuItem("2", "Alle Quellen aktualisieren – ChatGPT vollständig abgleichen (full)",
                 ("update", "--listing-mode", "full")),
        MenuItem("3", "Eine Quelle aktualisieren …", special="single-source"),
        MenuItem("4", "Gesamtindex neu aufbauen", ("index",)),
        MenuItem("5", "Alle Quellen prüfen", ("check",)),
        MenuItem("6", "Alle Quellen gründlich prüfen (langsam)", ("check", "--deep")),
        MenuItem("7", "Aufräumen – Probelauf", ("cleanup", "--dry-run")),
        MenuItem("8", "Aufräumen – ausführen", ("cleanup",),
                 confirm="Definierte Reste (leere Ordner, Staging-Dateien) wirklich entfernen?"),
        MenuItem("9", "Status und Übersicht", ("status",)),
    )),
    ("Exporter (aus dem Raw Storage, ohne Netz)", (
        MenuItem("10", "Exporte erzeugen (Markdown und JSON)", ("export",)),
    )),
    ("ChatGPT", (
        MenuItem("11", "Diagnose (Konfiguration und Ablage)", ("chatgpt", "doctor")),
    )),
    ("Zeitplanung (Windows-Aufgabenplanung)", (
        MenuItem("12", "Aufgaben anzeigen", ("task", "list")),
        MenuItem("13", "Aufgabe anlegen (täglich) …", special="task-create"),
        MenuItem("14", "Aufgabe pausieren …", special="task-pause"),
        MenuItem("15", "Aufgabe fortsetzen …", special="task-resume"),
        MenuItem("16", "Aufgabe löschen …", special="task-delete"),
    )),
    ("Konfiguration", (
        MenuItem("17", "Konfiguration anzeigen (wirksame Werte und Herkunft)", ("config", "list")),
        MenuItem("18", "Ablageorte anzeigen (config.yaml, .env, Home, Registry)", ("config", "path")),
        MenuItem("19", "Konfiguration neu laden (fehlende Datei anlegen)", ("config", "refresh")),
        MenuItem("20", "Einrichtung (Browser/ChatGPT-Anmeldung, täglicher Abruf)", ("setup",)),
    )),
)

ITEMS: dict[str, MenuItem] = {item.key: item for _title, items in GROUPS for item in items}


def _header(config: Path | None) -> list[str]:
    title = "ChatExporter – Raw Session Updater"
    lines = ["", title, "=" * len(title)]
    try:
        cfg = load_updater_config(config)
    except Exception as exc:  # noqa: BLE001
        lines.append(f"Konfiguration: FEHLER {exc}")
        return lines
    lines.extend(program_banner())
    lines.append(f"Konfiguration:  {cfg.config_file or '(keine config.yaml gefunden – Defaults)'}")
    lines.append(f"Datenordner:    {cfg.data_root}")
    lines.append(f"Aktive Quellen: {', '.join(cfg.sources)}")
    return lines


def _ask_yes(prompt: str, ask: Input) -> bool:
    return ask(f"{prompt} [j/N] ").strip().lower() in ("j", "ja", "y", "yes")


def _single_source(ask: Input, say: Output) -> tuple[str, ...] | None:
    say("Quelle wählen:")
    for number, source in enumerate(KNOWN_SOURCES, start=1):
        say(f"  {number}  {source}")
    choice = ask("Quelle (Nummer, leer = zurück): ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(KNOWN_SOURCES):
        return None
    source = KNOWN_SOURCES[int(choice) - 1]
    argv: tuple[str, ...] = ("update", "--source", source)
    if source == "chatgpt":
        say("Listing:")
        say("  1  auto – sparsam, bei Bedarf automatisch vollständig (Standard)")
        say("  2  recent – nur zuletzt geänderte, nie vollständig")
        say("  3  full – gesamter Bestand")
        mode = ask("Auswahl [1]: ").strip() or "1"
        argv += ("--listing-mode", {"2": "recent", "3": "full"}.get(mode, "auto"))
    return argv


def _task_create(ask: Input, say: Output) -> tuple[str, ...] | None:
    name = ask("Name der Aufgabe (leer = zurück): ").strip()
    if not name:
        return None
    at = ask("Uhrzeit täglich HH:MM [03:00]: ").strip() or "03:00"
    command = ask("Befehl [update --non-interactive]: ").strip()
    argv: tuple[str, ...] = ("task", "create", name, "--daily", at)
    if command:
        argv += ("--command", command)
    return argv


def _task_ref(action: str, ask: Input, say: Output) -> tuple[str, ...] | None:
    ref = ask("Aufgabe (Kurzname oder ID, leer = zurück): ").strip()
    if not ref:
        return None
    if action == "delete":
        if not _ask_yes(f"Aufgabe '{ref}' wirklich löschen?", ask):
            say("Abgebrochen.")
            return None
        return ("task", "delete", ref, "--yes")
    return ("task", action, ref)


def run_in_subprocess(argv: list[str], config: Path | None) -> int:
    """Führt einen Befehl in einem eigenen Prozess aus.

    Ein lange offenes Menü würde sonst die beim Start geladenen Module weiter
    verwenden und spätere Codeänderungen nicht sehen. Strg+C erreicht unter
    Windows Menü und Befehl gleichzeitig; der Befehl behandelt es selbst
    (laufende Quelle abbrechen), das Menü wartet nur weiter auf sein Ende.
    """
    import subprocess
    import sys
    # Gebautes Programm (chatexporter.exe) ruft sich selbst auf, Python das Modul.
    cmd = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "chatexporter"]
    if config is not None:
        cmd += ["--config", str(config)]
    import chatexporter.config as shared_config
    for item in shared_config.cli_overrides():
        cmd += ["--set", item]
    proc = subprocess.Popen([*cmd, *argv])
    while True:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            continue


def run_menu(*, config: Path | None = None, ask: Input = input, say: Output = print,
             dispatch: Callable[[list[str], Path | None], int] | None = None) -> int:
    """Zeigt das Menü, bis "0" oder Eingabeende. Rückgabe: letzter Exitcode."""
    if dispatch is None:
        dispatch = run_in_subprocess
    last = 0
    while True:
        for line in _header(config):
            say(line)
        for title, items in GROUPS:
            say("")
            say(title)
            for item in items:
                say(f"  {item.key:>2}  {item.label}")
        say("")
        say("   0  Beenden")
        try:
            choice = ask("Auswahl: ").strip()
        except EOFError:
            return last
        if choice in ("0", "q", ""):
            return last
        item = ITEMS.get(choice)
        if item is None:
            say(f"Unbekannte Auswahl: {choice}")
            continue
        try:
            if item.special == "single-source":
                argv = _single_source(ask, say)
            elif item.special == "task-create":
                argv = _task_create(ask, say)
            elif item.special and item.special.startswith("task-"):
                argv = _task_ref(item.special[len("task-"):], ask, say)
            else:
                argv = item.argv
            if argv is None:
                continue
            if item.confirm and not _ask_yes(item.confirm, ask):
                say("Abgebrochen.")
                continue
            shown = " ".join(argv)
            say(f"Befehl: chatexporter {shown}")
            say("")
            last = dispatch(list(argv), config)
            say("")
            say(f"Fertig (Exitcode {last}).")
            ask("Enter für das Menü ...")
        except EOFError:
            return last
