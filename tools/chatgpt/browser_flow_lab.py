"""Entwicklungswerkzeug: Browser-/Profil-Ablauf fuer ChatGPT Schritt fuer Schritt.

NUR fuer die Entwicklung (nicht Teil des Pakets, nicht im Installer). Zeigt
ausfuehrlich, was erkannt wird und was nicht, und haelt an jeder wichtigen
Stelle an, bis eine Taste (Enter) gedrueckt wird.

Stufen:
  1. Erkennung   – Konfiguration, installierte Browser (Programm, Version, Standard-
                   Datenverzeichnis, geoeffnet ja/nein), Profile mit ChatGPT-Cookie-
                   Status (nur Cookie-NAMEN, nie Werte), vorhandene Profilkopien,
                   Chrome for Testing, CDP-Port.
  2. Wege        – die Suchreihenfolge, wie sie der Lauf verwenden wuerde.
  3. Ablauf      – der echte Ablauf (``BrowserSetup``) mit allen Ereignissen:
                   Kopie anbieten/anlegen, Start, CDP, Anmeldepruefung, Wahl.
  4. Ergebnis    – Wahl, alle Versuche mit Gruenden, gesendete ChatGPT-Anfragen;
                   ein selbst gestarteter Browser wird wieder geschlossen.

Sicherheit / Sparsamkeit:
- Es werden nur Anmelde-Anfragen gesendet (typisch 1–2), keine Chats geladen.
- Die config.yaml wird NICHT veraendert, ausser mit ``--persist``.
- Tokens/Cookies werden nie ausgegeben.

Beispiele:
    python tools\\chatgpt\\browser_flow_lab.py --config ..\\config.yaml
    python tools\\chatgpt\\browser_flow_lab.py --search --browser-root %TEMP%\\lab_browser
    python tools\\chatgpt\\browser_flow_lab.py --detect-only --no-pause

Erweitern: neue Stufe als Funktion ``stage_xyz(lab)`` schreiben und in ``STAGES``
eintragen; zusaetzliche Haltepunkte ueber ``PAUSE_EVENTS`` (Ereignisnamen aus
``BrowserSetup.trace``) oder ``lab.pause("...")``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Direktstart (ohne Installation) ermoeglichen.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from chatexporter.providers.chatgpt.api.client import RequestCounter  # noqa: E402
from chatexporter.providers.chatgpt.auth import browsers, profiles  # noqa: E402
from chatexporter.providers.chatgpt.auth import chrome_for_testing as cft  # noqa: E402
from chatexporter.providers.chatgpt.auth.browser_setup import BrowserSetup, BrowserSetupError  # noqa: E402
from chatexporter.providers.chatgpt.auth.edge_cdp import EdgeCdpSession, _cdp_version  # noqa: E402
from chatexporter.providers.chatgpt.config.loader import load_config  # noqa: E402

#: Ereignisse aus ``BrowserSetup.trace``, bei denen angehalten wird.
PAUSE_EVENTS = {"candidates", "candidate", "skipped", "copy_offer", "copy_browser_closed", "copy_close_failed",
                "copy_cookie_check", "copy_done", "copy_browser_reopened", "launch", "connected", "auth_ok",
                "chosen", "failed", "configured", "login_state", "login_stopped"}

EVENT_TEXT = {
    "configured": "Fester Profilpfad aus der Konfiguration – keine Suche",
    "candidates": "Suchreihenfolge festgelegt",
    "candidate": "Naechster Weg wird versucht",
    "skipped": "Weg NICHT verwendet",
    "copy_offer": "Profilkopie wird angeboten",
    "copy_browser_closed": "Browser mit diesem Profil geschlossen (Restart Manager)",
    "copy_close_failed": "Browser liess sich nicht schliessen",
    "copy_browser_reopened": "Browser wieder geoeffnet",
    "login_state": "Automatische Anmeldung: neue Seite erkannt",
    "login_stopped": "Automatische Anmeldung beendet",
    "copy_cookie_check": "Cookie-Pruefung nach dem Schliessen",
    "copy_done": "Profilkopie angelegt",
    "launch": "Browser wird gestartet bzw. verbunden",
    "connected": "CDP-Verbindung steht",
    "auth_ok": "ChatGPT-Anmeldung gueltig",
    "chosen": "Weg gewaehlt",
    "failed": "Kein Weg hat funktioniert",
}


class LabAbort(KeyboardInterrupt):
    """Benutzer hat mit q abgebrochen."""


@dataclass
class Lab:
    args: argparse.Namespace
    cfg: Any = None
    counter: RequestCounter = field(default_factory=RequestCounter)
    sessions: list[Any] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)

    # -- Ausgabe ---------------------------------------------------------------------
    def head(self, title: str) -> None:
        print("\n" + "=" * 78 + f"\n {title}\n" + "=" * 78)

    def line(self, text: str = "", indent: int = 1) -> None:
        print("  " * indent + text)

    def pause(self, where: str) -> None:
        if self.args.no_pause:
            return
        try:
            answer = input(f"\n  ⏸  {where} – [Enter] weiter, q = abbrechen ")
        except EOFError:
            answer = ""
        if answer.strip().lower() == "q":
            raise LabAbort()

    def ask(self, prompt: str) -> str:
        print()
        return input(prompt)

    # -- Ereignisse aus BrowserSetup ----------------------------------------------------
    def trace(self, event: str, data: dict) -> None:
        print(f"\n  ▶ [{event}] {EVENT_TEXT.get(event, '')}")
        for key, value in data.items():
            if isinstance(value, list):
                print(f"      {key}:")
                for item in value:
                    print(f"        - {json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else item}")
            else:
                print(f"      {key}: {value}")
        if event in PAUSE_EVENTS:
            self.pause(EVENT_TEXT.get(event, event))

    def session_factory(self, config: Any) -> Any:
        session = EdgeCdpSession(config)
        self.sessions.append(session)
        return session

    def cleanup(self) -> None:
        for session in self.sessions:
            if getattr(session, "launched", False) and not self.args.keep_open:
                self.line(f"Schliesse selbst gestarteten Browser (Port {session.config.cdp_port}) ...")
                try:
                    session.abandon()
                except Exception as exc:  # noqa: BLE001
                    self.line(f"  Schliessen fehlgeschlagen: {type(exc).__name__}: {exc}")
            else:
                try:
                    session.close()
                except Exception:  # noqa: BLE001
                    pass


def _mark(value: bool | None) -> str:
    return {True: "JA", False: "nein", None: "unbekannt"}[value]


# -- Stufen ----------------------------------------------------------------------------------

def stage_config(lab: Lab) -> None:
    lab.head("1a. Konfiguration")
    cfg = load_config(Path(lab.args.config) if lab.args.config else None)
    if lab.args.search:
        cfg.browser.user_data_dir_configured = False
    if lab.args.browser_root:
        cfg.browser.browser_root = Path(lab.args.browser_root).expanduser().resolve()
    lab.cfg = cfg
    b = cfg.browser
    lab.line(f"config.yaml:            {cfg.config_file or '(keine)'}")
    lab.line(f"Entwicklungsmodus:      {cfg.dev_mode}")
    lab.line(f"Browser-Art (kind):     {b.kind}")
    lab.line(f"Programm (executable):  {b.executable or '(automatisch)'}")
    lab.line(f"Profil (user_data_dir): {b.user_data_dir}")
    lab.line(f"  fest konfiguriert:    {b.user_data_dir_configured}"
             + ("   (--search: Suche erzwungen)" if lab.args.search else ""))
    lab.line(f"Ablage (browser_root):  {b.browser_root}")
    lab.line(f"CDP:                    {b.cdp_endpoint}")
    lab.line(f"Download erlaubt:       {b.allow_download}")
    lab.line(f"Laeuft interaktiv:      {not lab.args.non_interactive}")
    lab.line(f"config.yaml aendern:    {'JA (--persist)' if lab.args.persist else 'nein'}")
    lab.pause("Konfiguration geprueft")


def stage_detect(lab: Lab) -> None:
    lab.head("1b. Installierte Browser und Profile")
    for kind in ("edge", "chrome"):
        label = browsers.LABELS[kind]
        exe = browsers.find_executable(kind)
        if exe is None:
            lab.line(f"{label}: NICHT gefunden (geprueft: "
                     + ", ".join(str(p) for p in browsers.common_executables(kind)) + ", App Paths)")
            continue
        version = browsers.browser_version(exe)
        data = browsers.default_user_data_dir(kind)
        lab.line(f"{label}: {exe}")
        lab.line(f"Version: {'.'.join(map(str, version)) if version else 'unbekannt'}", 2)
        if kind == "chrome" and version and version[0] >= browsers.CHROME_DEFAULT_PROFILE_CDP_LIMIT:
            lab.line(f"Hinweis: ab Version {browsers.CHROME_DEFAULT_PROFILE_CDP_LIMIT} keine Fernsteuerung "
                     "des Standard-Datenverzeichnisses – daher Kopie", 2)
        if data is None or not data.is_dir():
            lab.line(f"Standard-Datenverzeichnis: fehlt ({data})", 2)
            continue
        in_use = browsers.profile_in_use(data)
        lab.line(f"Standard-Datenverzeichnis: {data}", 2)
        lab.line(f"geoeffnet: {_mark(in_use)}" + ("  (Cookies einzelner Profile evtl. gesperrt)" if in_use else ""), 2)
        found = profiles.list_profiles(kind, data)
        if not found:
            lab.line("keine Profile gefunden", 2)
        for profile in found:
            lab.line(f"- {profile.directory:<10} '{profile.name}': ChatGPT-Sitzung {_mark(profile.chatgpt)}"
                     f" – {profile.detail}", 2)
    lab.pause("Browser und Profile erkannt")

    lab.head("1c. Profilkopien, Chrome for Testing, CDP-Port")
    root = lab.cfg.browser.browser_root
    copies = profiles.existing_copies(root)
    lab.line(f"Profilkopien unter {Path(root) / 'profiles'}: {len(copies)}")
    for path, info in copies:
        status, detail = profiles.chatgpt_cookie_status(path / str(info.get("directory", "Default")))
        lab.line(f"- {path.name}: Quelle {info.get('source')} ({info.get('name')}), kopiert {info.get('copied_at')}", 2)
        lab.line(f"ChatGPT-Sitzung in der Kopie: {_mark(status)} – {detail}", 3)
    installed = cft.installed_executable(root)
    lab.line(f"Chrome for Testing: {installed or 'nicht installiert (Download nur interaktiv nach Rueckfrage)'}")
    endpoint = lab.cfg.browser.cdp_endpoint
    version = _cdp_version(endpoint)
    if version:
        lab.line(f"CDP-Port {lab.cfg.browser.cdp_port}: BELEGT – {version.get('Browser')} "
                 "(die Suche weicht auf einen freien Port aus; ein fester Pfad verbindet sich damit)")
    else:
        lab.line(f"CDP-Port {lab.cfg.browser.cdp_port}: frei")
    lab.pause("Erkennung abgeschlossen")


def stage_candidates(lab: Lab) -> None:
    lab.head("2. Suchreihenfolge")
    if lab.cfg.browser.user_data_dir_configured:
        lab.line("Profil ist fest konfiguriert – der Lauf sucht NICHT, sondern verwendet:")
        lab.line(str(lab.cfg.browser.user_data_dir), 2)
        lab.line("(mit --search laesst sich die Suche trotzdem ausprobieren)")
    else:
        root = lab.cfg.browser.browser_root
        for i, line in enumerate(browsers.describe(browsers.build_candidates(
                root, installed_cft=cft.installed_executable(root))), 1):
            lab.line(f"{i}. {line}")
    lab.pause("Weiter mit dem echten Ablauf (startet ggf. einen Browser)")


def stage_run(lab: Lab) -> None:
    lab.head("3. Ablauf")
    from chatexporter.providers.chatgpt.auth.browser_setup import auth_broker
    cfg = lab.cfg

    def persist(values: dict[str, Any]) -> None:
        if lab.args.persist:
            import chatexporter.config as shared_config
            shared_config.manager().set_many(values, explicit=cfg.config_file)
            lab.line("In config.yaml eingetragen:")
        else:
            lab.line("WUERDE in config.yaml eintragen (ohne --persist nicht ausgefuehrt):")
        for key, value in values.items():
            lab.line(f"{key} = {value}", 2)

    setup = BrowserSetup(cfg, interactive=not lab.args.non_interactive,
                         say=lambda m: print(f"  │ {m}"), ask=lab.ask,
                         session_factory=lab.session_factory, persist=persist, trace=lab.trace,
                         broker_factory=lambda s: auth_broker(cfg, s, counter=lab.counter,
                                                              say=lambda m: print(f"  │ {m}"), trace=lab.trace))
    try:
        session, auth, choice = setup.open()
        lab.result = {"ok": True, "choice": choice.as_dict()}
    except BrowserSetupError as exc:
        lab.result = {"ok": False, "error": str(exc), "attempts": [a.as_dict() for a in exc.attempts]}
    except LabAbort:
        raise
    except Exception as exc:  # noqa: BLE001
        lab.result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def stage_summary(lab: Lab) -> None:
    lab.head("4. Ergebnis")
    result = lab.result
    if result.get("ok"):
        choice = result["choice"]
        lab.line(f"Verwendet: {browsers.LABELS.get(choice['kind'], choice['kind'])} – {choice['user_data_dir']}")
        lab.line(f"Programm: {choice['executable']}  CDP-Port: {choice['cdp_port']}  Modus: {choice['mode']}")
        attempts = choice.get("attempts", [])
    else:
        lab.line(f"FEHLGESCHLAGEN: {result.get('error')}")
        attempts = result.get("attempts", [])
    for attempt in attempts:
        lab.line(f"{'+' if attempt['ok'] else '-'} {attempt['label']}"
                 + (f": {attempt['reason']}" if attempt["reason"] else ""), 2)
    lab.line(f"Gesendete ChatGPT-Anfragen: {lab.counter.as_dict()}")


STAGES: list[tuple[str, Callable[[Lab], None]]] = [
    ("config", stage_config),
    ("detect", stage_detect),
    ("candidates", stage_candidates),
    ("run", stage_run),
    ("summary", stage_summary),
]


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", help="config.yaml (Standard: wie das Programm sie findet)")
    parser.add_argument("--no-pause", action="store_true", help="nicht anhalten")
    parser.add_argument("--detect-only", action="store_true", help="nur Stufe 1 (startet nichts)")
    parser.add_argument("--search", action="store_true", help="Suche auch bei fest konfiguriertem Profil")
    parser.add_argument("--browser-root", help="Ablage fuer Kopien/eigene Profile (z. B. ein Testordner)")
    parser.add_argument("--non-interactive", action="store_true",
                        help="wie ein geplanter Lauf: keine Rueckfragen, keine Anmeldung, keine Kopie")
    parser.add_argument("--persist", action="store_true", help="gewaehlten Weg in die config.yaml eintragen")
    parser.add_argument("--keep-open", action="store_true", help="selbst gestarteten Browser offen lassen")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    lab = Lab(args)
    stages = STAGES[:2] if args.detect_only else STAGES
    try:
        for _name, stage in stages:
            stage(lab)
    except (LabAbort, KeyboardInterrupt):
        print("\n  Abgebrochen.")
        lab.result = lab.result or {"ok": False, "error": "abgebrochen"}
    finally:
        lab.cleanup()
    if args.detect_only:
        return 0
    return 0 if lab.result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
