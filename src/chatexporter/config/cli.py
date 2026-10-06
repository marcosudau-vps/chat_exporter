"""Kommandozeile der Konfiguration.

``chatexporter config <befehl>`` aendert die **Storage**-Konfiguration
(``<storage>/.storage/config.yaml``), ``chatexporter config-global <befehl>``
die globale ``config.yaml`` (Grundwerte, Browser, Programm). Anzeigen
(``get``/``list``) zeigen in beiden Faellen den wirksamen Wert mit Herkunft.

    get [SCHLUESSEL]       wirksamer Wert und Herkunft (ohne Schluessel: alle)
    set SCHLUESSEL WERT    Wert dauerhaft in die Datei dieser Ebene schreiben
    reset SCHLUESSEL       Wert entfernen (es gilt wieder die naechste Ebene bzw. der Standard)
    reset --all            Datei dieser Ebene durch die vollstaendige Vorlage ersetzen
    refresh                neu laden, fehlende Dateien anlegen, Spiegel neu schreiben
    path                   wo liegen die Dateien, der Storage und der Registry-Bereich

Exitcodes: 0 ok, 1 unbekannter Schluessel oder ungueltiger Wert, 2 Datei-/Ladefehler.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from layered_config import ConfigError
from layered_config.template import dump_value

from . import (CONFIG_ENV, HOME_ENV, REGISTRY_VALUES_KEY, SCHEMA, apply_storage, cli_overrides, home,
               manager, storage_key, storage_of, storage_status)

#: Ebene je Befehl: Storage (``config``) oder global (``config-global``).
SCOPES = {"storage": ("scope", "storage"), "global": ("base", "config")}

COMMANDS = ("get", "set", "reset", "refresh", "path", "list")


def build_parser(prog: str = "chatexporter config") -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, default=argparse.SUPPRESS,
                        help="config.yaml statt der automatisch gefundenen")
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="Ausgabe als JSON")
    parser = argparse.ArgumentParser(prog=prog, parents=[common],
                                     description="Konfiguration anzeigen und dauerhaft aendern.")
    sub = parser.add_subparsers(dest="command", metavar="BEFEHL")
    get = sub.add_parser("get", parents=[common], help="wirksamen Wert anzeigen (ohne Schluessel: alle)")
    get.add_argument("key", nargs="?", help="Schluessel, z. B. providers.chatgpt.sync.listing_mode")
    sub.add_parser("list", parents=[common], help="alle wirksamen Werte mit Herkunft")
    set_ = sub.add_parser("set", parents=[common], help="Wert in die config.yaml schreiben")
    set_.add_argument("key")
    set_.add_argument("value", help="Wert; Listen als a,b oder [a, b], Objekte als {a: 1}")
    reset = sub.add_parser("reset", parents=[common], help="Wert auf den Standard zuruecksetzen")
    reset.add_argument("key", nargs="?")
    reset.add_argument("--all", action="store_true", help="ganze Datei durch die Vorlage ersetzen")
    reset.add_argument("-y", "--yes", action="store_true", help="ohne Rueckfrage (bei --all)")
    sub.add_parser("refresh", parents=[common], help="neu laden, fehlende Datei anlegen, Spiegel schreiben")
    sub.add_parser("path", parents=[common], help="Ablageorte anzeigen")
    return parser


SECRET_SHOWN = "<gesetzt – wird nicht angezeigt>"


def _secrets() -> set[str]:
    return SCHEMA.secrets()


def _mask(key: str, value: Any, secrets: set[str] | None = None) -> Any:
    """Secrets nie ausgeben (auch nicht in Abschnitten)."""
    secrets = _secrets() if secrets is None else secrets
    if isinstance(value, dict):
        return {k: _mask(f"{key}.{k}" if key else k, v, secrets) for k, v in value.items()}
    if key in secrets and value not in (None, ""):
        return SECRET_SHOWN
    return value


def _row(loaded, key: str) -> dict[str, Any]:
    return {"key": key, "value": _mask(key, loaded.values.get(key)), "origin": loaded.origin(key)}


def _show(value: Any) -> str:
    return dump_value(value) if value is not None else "(nicht gesetzt)"


def _registry(loaded) -> str:
    identity = storage_status(loaded)["identity"]
    key = storage_key(identity) + r"\Config\Current" if identity is not None else REGISTRY_VALUES_KEY
    return "HKEY_CURRENT_USER\\" + key


def _target_file(loaded, scope: str) -> Path:
    if scope == "global":
        return loaded.config_file
    if loaded.scope is None:
        raise ConfigError("Kein benutzbarer Storage (altes oder unklares Format?) – globale Werte "
                          "aendert 'chatexporter config-global'")
    return loaded.scope.config_file


def main(argv: list[str] | None = None, *, prog: str = "chatexporter config",
         say: Callable[[str], None] = print, ask: Callable[[str], str] = input, scope: str = "storage") -> int:
    args = build_parser(prog).parse_args(list(sys.argv[1:] if argv is None else argv))
    command = args.command or "list"
    explicit = getattr(args, "config", None)
    as_json = getattr(args, "json", False)
    target, layer = SCOPES[scope]
    mgr = manager()

    def load():
        return apply_storage(mgr.load(explicit, cli_overrides()))
    try:
        if command == "path":
            loaded = load()
            storage = storage_of(loaded)
            info = {"config_file": str(loaded.config_file), "env_file": str(loaded.env_file) if loaded.env_file else None,
                    "home": str(home()), "home_env": HOME_ENV, "config_env": CONFIG_ENV,
                    "storage": str(storage.root), "storage_format": storage_status(loaded)["format"],
                    "storage_config_file": str(storage.config_file), "storage_env_file": str(storage.env_file),
                    "state_file": str(storage.state_file), "registry": _registry(loaded)}
            if as_json:
                say(json.dumps(info, ensure_ascii=False, indent=2))
            else:
                for key, value in info.items():
                    say(f"{key + ':':14}{value}")
            return 0
        if command in ("list", "get") and not getattr(args, "key", None):
            loaded = load()
            rows = [_row(loaded, key) for key in sorted(loaded.values)]
            if as_json:
                say(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
            else:
                say(f"# {loaded.config_file}")
                for row in rows:
                    say(f"{row['key']} = {_show(row['value'])}    [{row['origin']}]")
            return 0
        if command == "get":
            loaded = load()
            key = args.key
            if key not in loaded.values:
                section = loaded.get(key)
                if section is None:
                    raise ConfigError(f"Unbekannte Einstellung: {key}")
                payload: Any = {"key": key, "value": _mask(key, section), "origin": "abschnitt"}
            else:
                payload = _row(loaded, key)
            if as_json:
                say(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            else:
                say(_show(payload["value"]))
                say(f"(Herkunft: {payload['origin']})")
            return 0
        if command == "set":
            setting = SCHEMA.get(args.key)
            if scope == "storage" and setting is not None and setting.global_only:
                raise ConfigError(f"{args.key} gilt nur global: chatexporter config-global set {args.key} …")
            loaded = apply_storage(mgr.set(args.key, args.value, explicit=explicit, target=target))
            row = _row(loaded, args.key)
            if as_json:
                say(json.dumps(row, ensure_ascii=False, indent=2, default=str))
            else:
                say(f"Gesetzt in {_target_file(loaded, scope)}: {args.key} = {_show(row['value'])}")
                if row["origin"] != layer:
                    say(f"Hinweis: wirksam ist der Wert aus '{row['origin']}' (hat Vorrang vor dieser Datei).")
            return 0
        if command == "reset":
            if args.all:
                path = _target_file(load(), scope)
                if not args.yes:
                    try:
                        answer = ask(f"{path} durch die vollstaendige Vorlage ersetzen (Sicherung wird angelegt)? [j/N] ")
                    except EOFError:
                        answer = ""
                    if answer.strip().lower() not in ("j", "ja", "y", "yes"):
                        say("Abgebrochen.")
                        return 1
                mgr.reset(None, explicit=explicit, target=target)
                say(f"Zurueckgesetzt: {path} (Sicherung unter .config_backups/)")
                return 0
            if not args.key:
                say("Bitte einen Schluessel oder --all angeben.")
                return 1
            loaded = apply_storage(mgr.reset(args.key, explicit=explicit, target=target))
            row = _row(loaded, args.key) if args.key in loaded.values else {"key": args.key, "value": None, "origin": None}
            if as_json:
                say(json.dumps(row, ensure_ascii=False, indent=2, default=str))
            else:
                say(f"Zurueckgesetzt: {args.key} = {_show(row['value'])} [{row['origin']}]")
            return 0
        if command == "refresh":
            loaded = apply_storage(mgr.refresh(explicit, cli_overrides()))
            origins: dict[str, int] = {}
            for origin in loaded.resolved.origins.values():
                origins[origin] = origins.get(origin, 0) + 1
            info = {"config_file": str(loaded.config_file), "created": loaded.created,
                    "storage_config_file": str(loaded.scope.config_file) if loaded.scope else None,
                    "settings": len(loaded.values), "origins": origins, "registry": _registry(loaded)}
            if as_json:
                say(json.dumps(info, ensure_ascii=False, indent=2))
            else:
                say(f"Neu geladen: {loaded.config_file}" + (" (Vorlage neu angelegt)" if loaded.created else ""))
                say("Herkunft: " + ", ".join(f"{k} {v}" for k, v in sorted(origins.items())))
            return 0
    except ConfigError as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"FEHLER (Datei): {exc}", file=sys.stderr)
        return 2
    return 2


def known_keys() -> list[str]:
    return [setting.path for setting in SCHEMA]


if __name__ == "__main__":
    raise SystemExit(main())
