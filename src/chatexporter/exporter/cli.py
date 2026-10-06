"""Kommandozeile des Exporters: ``chatexporter export`` / ``chatexporter-export``.

    chatexporter export [json|md|all] [--source QUELLE]... [--format markdown|json]...
                        [--export-root ORDNER] [--raw-root ORDNER] [--config DATEI]

    chatexporter export json     nur JSON
    chatexporter export md       nur Markdown
    chatexporter export          Formate laut exporter.formats

Exitcodes: 0 ok, 1 einzelne Gespraeche oder Formate fehlgeschlagen,
2 Konfigurationsfehler.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import (EXPORTABLE_SOURCES, FORMAT_ALIASES, KNOWN_FORMATS, ExporterConfigError,
                     load_exporter_config)
from .operations import export


def build_parser(prog: str = "chatexporter export") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Exporte (Markdown/JSON) aus dem Raw Storage erzeugen (ohne Netz, "
                    "liest den Raw Storage nur und schreibt nach exports/).")
    parser.add_argument("what", nargs="?", choices=("json", "md", "markdown", "all"), default=None,
                        help="json, md (= markdown) oder all; ohne Angabe: Formate laut exporter.formats")
    parser.add_argument("--config", type=Path, default=None,
                        help="Gemeinsame config.yaml (Standard: CHATEXPORTER_CONFIG oder Suche ab Arbeitsordner)")
    parser.add_argument("--format", action="append", choices=KNOWN_FORMATS, dest="formats",
                        help="nur dieses Format (mehrfach angebbar; Standard: exporter.formats)")
    parser.add_argument("--source", action="append", choices=EXPORTABLE_SOURCES, dest="sources",
                        help="nur diese Quelle (mehrfach angebbar; Standard: exporter.sources)")
    parser.add_argument("--export-root", type=Path, default=None, help="Ueberschreibt exporter.root")
    parser.add_argument("--raw-root", type=Path, default=None, help="Ueberschreibt storage.raw_root")
    return parser


def main(argv: list[str] | None = None, *, prog: str = "chatexporter export") -> int:
    args = build_parser(prog).parse_args(argv)
    try:
        cfg = load_exporter_config(args.config, overrides={"raw_root": args.raw_root,
                                                           "export_root": args.export_root})
        formats = args.formats
        if args.what == "all":
            formats = list(KNOWN_FORMATS)
        elif args.what:
            formats = [FORMAT_ALIASES[args.what]]
        report, code = export(cfg, formats=formats, sources=args.sources,
                              progress=lambda message: print(message, flush=True))
    except (ExporterConfigError, ValueError, OSError) as exc:
        print(f"Konfigurationsfehler: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return code


def export_main(argv: list[str] | None = None) -> int:
    """Einzelbefehl chatexporter-export."""
    return main(sys.argv[1:] if argv is None else argv, prog="chatexporter-export")


if __name__ == "__main__":
    raise SystemExit(main())
