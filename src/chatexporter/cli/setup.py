"""Ersteinrichtung: ``chatexporter setup`` (auch am Ende der Installation).

1. Konfiguration: config.yaml finden oder als vollstaendige Vorlage anlegen,
   Datenordner und aktive Quellen anzeigen.
2. ChatGPT (wenn aktiv): Browser und Anmeldung einrichten oder pruefen
   (``chatexporter chatgpt browser-setup``; Profilkopie nur nach Bestaetigung).
3. Zeitplan: taeglichen Abruf als Windows-Aufgabe anbieten.

Jeder Schritt fragt vorher; nichts wird ohne Zustimmung geaendert. Gehoert
das Konsolenfenster nur diesem Programm (Start ueber Installer oder Startmenue),
wartet es am Ende auf Enter, damit die Zusammenfassung lesbar bleibt. Liegt in
der Bedienschicht, weil nur sie Provider und Zeitplanung zusammen kennt.
"""

from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path
from typing import Callable

import chatexporter.config as shared_config

Say = Callable[[str], None]
Ask = Callable[[str], str]

DAILY_SLUG = "taeglich"
DAILY_NAME = "Taeglicher Abruf"
DEFAULT_TIME = "03:00"
_TIME = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _ask(ask: Ask, prompt: str) -> str:
    try:
        return ask(prompt).strip()
    except EOFError:
        return ""


def _config_step(config: Path | None, say: Say) -> shared_config.Loaded:
    loaded = shared_config.load(config)
    data_root = shared_config.resolve_path(loaded, loaded.get("storage.data_root"))
    say(f"Konfiguration:  {loaded.config_file}")
    say(f"Storage:        {data_root}")
    say(f"Quellen:        {', '.join(loaded.get('raw_session_updater.sources') or []) or '(keine)'}")
    return loaded


def _browser_step(loaded: shared_config.Loaded, config: Path | None, say: Say, ask: Ask,
                  provider: Callable[[str, list[str], Path | None], int]) -> str:
    if "chatgpt" not in (loaded.get("raw_session_updater.sources") or []):
        return "uebersprungen (ChatGPT nicht aktiv)"
    current = loaded.get("providers.chatgpt.browser.user_data_dir")
    if current:
        say(f"Browser-Profil fuer ChatGPT: {current}")
        answer = _ask(ask, "[p]ruefen, [n]eu einrichten oder [u]eberspringen? [p] ").lower()
        if answer.startswith("u"):
            return "uebersprungen"
        args = ["browser-setup", "--neu"] if answer.startswith("n") else ["browser-setup"]
    else:
        say("Fuer ChatGPT wird ein Browser mit Ihrer Anmeldung gebraucht. Gesucht werden Edge/Chrome-Profile")
        say("mit ChatGPT-Anmeldung (davon wird nach Rueckfrage eine Kopie angelegt), sonst ein eigenes Profil.")
        if _ask(ask, "Browser und ChatGPT-Anmeldung jetzt einrichten? [J/n] ").lower() in ("n", "nein", "no"):
            return "uebersprungen"
        args = ["browser-setup"]
    code = provider("chatgpt", args, config)
    return "ok" if code == 0 else f"fehlgeschlagen (Exitcode {code})"


def _task_step(config: Path | None, say: Say, ask: Ask, service_factory: Callable[[object], object]) -> str:
    from chatexporter.task_scheduler.config import TaskSetupError, load_config
    from chatexporter.task_scheduler.service import TaskServiceError, build_trigger
    try:
        service = service_factory(load_config(config))
        try:
            service.get(DAILY_SLUG)
            exists = True
        except TaskServiceError:
            exists = False
    except TaskSetupError as exc:
        return f"fehlgeschlagen ({exc})"
    if exists:
        prompt = f"Taegliche Aufgabe '{DAILY_SLUG}' besteht. Neue Uhrzeit HH:MM (leer = unveraendert): "
    else:
        prompt = f"Taeglichen Abruf als Windows-Aufgabe einrichten? Uhrzeit HH:MM [{DEFAULT_TIME}], n = nein: "
    while True:
        answer = _ask(ask, prompt).lower()
        if answer in ("n", "nein", "no") or (not answer and exists):
            return "unveraendert" if exists else "nicht eingerichtet"
        answer = answer or DEFAULT_TIME
        if _TIME.match(answer):
            break
        say("Bitte HH:MM angeben, z. B. 03:00.")
    try:
        trigger = build_trigger(daily=answer)
        view = (service.update(DAILY_SLUG, trigger=trigger) if exists
                else service.create(DAILY_NAME, slug=DAILY_SLUG, trigger=trigger))
    except (TaskSetupError, TaskServiceError) as exc:
        return f"fehlgeschlagen ({exc})"
    say(f"   Aufgabe '{view['slug']}': {view['trigger']}, Befehl '{view['command']}', "
        f"naechster Lauf {view['next_run'] or '-'}")
    return str(view["trigger"])


def owns_console() -> bool:
    """Gehoert das Konsolenfenster nur diesem Prozess? Dann schliesst Windows es
    mit dem Programmende (Start per Doppelklick, Startmenue oder Installer)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        processes = (ctypes.c_uint32 * 4)()
        return ctypes.windll.kernel32.GetConsoleProcessList(processes, 4) == 1
    except Exception:  # noqa: BLE001
        return False


def run_setup(argv: list[str], config: Path | None, *, say: Say = print, ask: Ask = input,
              provider: Callable[[str, list[str], Path | None], int] | None = None,
              service_factory: Callable[[object], object] | None = None,
              own_console: Callable[[], bool] = owns_console) -> int:
    try:
        code = _run_steps(argv, config, say=say, ask=ask, provider=provider, service_factory=service_factory)
    except Exception as exc:  # noqa: BLE001  im eigenen Fenster sonst unlesbar
        say(traceback.format_exc().rstrip())
        say(f"\nFEHLER bei der Einrichtung: {type(exc).__name__}: {exc}")
        code = 1
    if own_console():
        _ask(ask, "\n[Enter] schliesst dieses Fenster ")
    return code


def _run_steps(argv: list[str], config: Path | None, *, say: Say, ask: Ask,
               provider: Callable[[str, list[str], Path | None], int] | None,
               service_factory: Callable[[object], object] | None) -> int:
    if any(a in ("-h", "--help") for a in argv):
        say(__doc__.strip())
        return 0
    if argv:
        say(f"Unbekannte Option: {' '.join(argv)}")
        return 2
    if provider is None:
        from .main import run_provider as provider
    if service_factory is None:
        from chatexporter.task_scheduler.service import TaskService as service_factory
    say("=" * 70)
    say("ChatExporter – Einrichtung")
    say("=" * 70)
    say("\n1. Konfiguration")
    loaded = _config_step(config, say)
    config = config or loaded.config_file
    say("\n2. Browser und ChatGPT-Anmeldung")
    browser = _browser_step(loaded, config, say, ask, provider)
    say(f"   -> {browser}")
    say("\n3. Zeitplan")
    schedule = _task_step(config, say, ask, service_factory)
    say(f"   -> {schedule}")
    say("\nFertig. Start mit 'chatexporter' (Menue) oder 'chatexporter update'.")
    say("Diese Einrichtung laesst sich jederzeit mit 'chatexporter setup' wiederholen.")
    return 1 if "fehlgeschlagen" in browser + schedule else 0
