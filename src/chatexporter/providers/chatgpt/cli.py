from __future__ import annotations

"""Kommandozeile des ChatGPT-Providers (``chatexporter-chatgpt``).

Eigenstaendig nutzbar wie die Kommandozeilen der anderen Provider: dieselben
fuenf Vertragsbefehle plus die ChatGPT-spezifischen Zusatzbefehle.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from chatexporter.providers.chatgpt import contract, operations
from chatexporter.providers.chatgpt.config.loader import discover_config, load_config

SOURCE = contract.SOURCE


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chatexporter-chatgpt",
        description="ChatGPT-Provider: Konversationen und Dateien ueber die ChatGPT-Weboberflaeche sichern")
    p.add_argument("--config", type=Path, default=None,
                   help="Gemeinsame config.yaml (Standard: CHATEXPORTER_CONFIG oder Suche ab Arbeitsordner)")
    p.add_argument("--raw-root", type=Path, default=None, help="Ueberschreibt storage.raw_root")
    sub = p.add_subparsers(dest="command", required=True, metavar="befehl")

    u = sub.add_parser("update", aliases=["sync"],
                       help="Neue/geaenderte Konversationen und Dateien laden (Einzellauf)")
    u.add_argument("--no-files", action="store_true", help="Keine Dateien/Anhaenge laden")
    u.add_argument("--non-interactive", action="store_true", help="Keine interaktive Anmeldung")
    u.add_argument("--listing-mode", choices=("auto", "full", "recent"), default=None,
                   help="auto (Standard) = recent, bei Bedarf full; full = komplettes Listing; recent = nur zuletzt geaenderte")

    sub.add_parser("recreate-index", help="Index-Fragment dieser Quelle erzeugen (Vertrag, schreibt Gesamtindex nicht)")
    ch = sub.add_parser("check-health", help="Ablage pruefen (read-only)")
    ch.add_argument("--deep", action="store_true", help="Auch Library-Inhalte hashen (langsamer)")
    ch.add_argument("--fail-on-warning", action="store_true", help="Auch bei Warnungen Exitcode 1")
    cl = sub.add_parser("cleanup", help="Definierte Reste entfernen (niemals Quelldaten)")
    cl.add_argument("--dry-run", action="store_true", help="Nur zaehlen, nichts entfernen")
    sub.add_parser("stats", help="Momentaufnahme dieser Quelle")

    sub.add_parser("rebuild-index", help="ChatGPT-Anteil des Gesamtindex direkt neu bauen")
    imp = sub.add_parser("import-data", help="OpenAI-Kontodatenexport importieren (als unvollstaendig markiert)")
    imp.add_argument("--source", required=True, type=Path,
                     help="Ordner mit conversations-*.json und den file_*/file-*-Dateien")
    imp.add_argument("--limit", type=int, default=None)
    imp.add_argument("--only-id", action="append", default=None)
    imp.add_argument("--overwrite-existing", action="store_true")
    imp.add_argument("--no-files", action="store_true")
    imp.add_argument("--report", type=Path, default=None)
    sub.add_parser("doctor", help="Aufgeloeste Konfiguration und Ablagezustand anzeigen")
    bs = sub.add_parser("browser-setup",
                        help="Browser und ChatGPT-Anmeldung einrichten/pruefen (interaktiv, laedt keine Chats)")
    bs.add_argument("--neu", dest="renew", action="store_true",
                    help="auch bei eingetragenem Profil neu suchen (Profilkopie, eigenes Profil, ...)")
    lg = sub.add_parser("login", help="ChatGPT-Anmeldung pruefen bzw. automatisch anmelden (laedt keine Chats)")
    lg.add_argument("--profil", dest="profile", type=Path, default=None,
                    help="eigenes Browser-Datenverzeichnis, z. B. leerer Testordner fuer einen Anmeldetest")
    lg.add_argument("--schrittweise", dest="step_by_step", action="store_true",
                    help="Browser sichtbar, vor jedem Anmeldeschritt anhalten und nachfragen")
    sub.add_parser("migrate-store", help="Statusablage und Datei-Referenzen nachziehen (idempotent)")
    ml = sub.add_parser("migrate-layout", help="Einmalig: flache Ablage -> raw_storage/chatgpt + runtime")
    ml.add_argument("--dry-run", action="store_true", help="Nur planen und zaehlen")
    sc = sub.add_parser("scenarios", help="Mutationstests gegen eine KOPIE des Bestands",
                        add_help=False)
    sc.add_argument("args", nargs=argparse.REMAINDER)
    return p


def _program_banner(config_file: Path | None) -> list[str]:
    """Welcher Programmstand laeuft mit welcher Config? (eigene Kopie; der
    Provider haengt nicht vom Raw Session Updater ab)."""
    import sys
    # Einzige Quelle der Versionsnummer (Paket-Metadaten koennen veralten, z. B. die einer
    # Entwicklungsinstallation, die PyInstaller ins gebaute Programm uebernimmt).
    from chatexporter.config.version import __version__ as version
    code = Path(__file__).resolve().parents[2]
    lines = [f"Programm:       chatexporter {version} aus {code}",
             f"Python:         {sys.executable}",
             f"Konfiguration:  {config_file or '(keine config.yaml gefunden – Defaults)'}"]
    if "site-packages" in code.parts:
        lines.append("WARNUNG: feste Kopie in site-packages – Aenderungen am Codeordner wirken "
                     "erst nach Neuinstallation.")
    return lines


def _print(report: Any) -> None:
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "scenarios":
        from chatexporter.providers.chatgpt.storage import scenarios
        return scenarios.main(args.args)

    config_file = discover_config(args.config)
    cfg = load_config(config_file, overrides={"raw_root": args.raw_root})
    say = lambda message: print(message, flush=True)  # noqa: E731

    if args.command in ("update", "sync"):
        for line in _program_banner(config_file):
            say(line)
        report, code = operations.sync(cfg, no_files=args.no_files,
                                       non_interactive=args.non_interactive,
                                       listing_mode=args.listing_mode, progress=say)
    elif args.command == "recreate-index":
        report, code = contract.recreate_index(cfg), 0
    elif args.command == "check-health":
        report = contract.check_storage_health(cfg, deep=args.deep)
        code = 0 if report.get("ok") else 1
        if code == 0 and args.fail_on_warning and report.get("warning_count"):
            code = 1
    elif args.command == "cleanup":
        report, code = contract.cleanup_storage(cfg, dry_run=args.dry_run), 0
    elif args.command == "stats":
        report, code = contract.state_n_stats(cfg), 0
    elif args.command == "rebuild-index":
        report, code = operations.rebuild_index(cfg)
    elif args.command == "import-data":
        report, code = operations.import_data(
            cfg, source=args.source, limit=args.limit, only_ids=args.only_id,
            overwrite_existing=args.overwrite_existing, no_files=args.no_files,
            report_path=args.report, progress=say)
    elif args.command == "doctor":
        report, code = operations.doctor(cfg, config_file=config_file)
    elif args.command == "login":
        report, code = operations.login(cfg, profile=args.profile, progress=say, step_by_step=args.step_by_step)
    elif args.command == "browser-setup":
        report, code = operations.browser_setup(cfg, renew=args.renew, progress=say)
    elif args.command == "migrate-store":
        report, code = operations.migrate_store(cfg)
    elif args.command == "migrate-layout":
        report, code = operations.migrate_layout(cfg, dry_run=args.dry_run, progress=say)
    else:  # pragma: no cover - argparse verhindert das
        return 2
    _print(report)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
