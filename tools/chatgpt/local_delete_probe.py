"""Testablauf: Chats NUR LOKAL im Storage loeschen (nie auf der ChatGPT-Webseite).

Waehlt aus dem Gesamtindex eines (kleinen Test-)Storages Konversationen aus – den
neuesten, einen mittleren und den aeltesten Chat (nach ``remote_updated_at``) – und
loescht deren Rohdatei unter ``raw_storage/chatgpt/``. Der naechste ``update`` muss
sie erkennen und neu laden (``docs/TESTABLAUF_ENTWICKLUNGSMODUS.md``).

Sicherheit:
- ohne ``--ausfuehren`` nur Anzeige (nichts wird geloescht);
- verweigert Storages mit mehr als ``--max`` ChatGPT-Konversationen (Standard 200),
  damit nie ein echter Bestand getroffen wird;
- loescht nur Dateien innerhalb von ``<storage>/raw_storage/chatgpt/``.

Beispiel:
    python tools\\chatgpt\\local_delete_probe.py --storage ..\\_testlauf\\storage
    python tools\\chatgpt\\local_delete_probe.py --storage ..\\_testlauf\\storage --ausfuehren
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def _time(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return 0.0


def pick(entries: dict[str, dict], count: int = 3) -> list[tuple[str, str]]:
    """(id, Rolle): neuester, aeltester und gleichmaessig verteilte dazwischen."""
    ordered = sorted(entries, key=lambda cid: _time(entries[cid].get("remote_updated_at")), reverse=True)
    if not ordered:
        return []
    count = max(1, min(count, len(ordered)))
    if count == 1:
        return [(ordered[0], "neuester")]
    positions = sorted({round(i * (len(ordered) - 1) / (count - 1)) for i in range(count)})
    roles = {0: "neuester", len(ordered) - 1: "aeltester"}
    return [(ordered[p], roles.get(p, f"Position {p + 1} von {len(ordered)}")) for p in positions]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--storage", type=Path, required=True, help="Storage-Ordner des Tests")
    parser.add_argument("--anzahl", type=int, default=3, help="wie viele Chats (Standard 3)")
    parser.add_argument("--max", type=int, default=200, help="Schutz: groessere Storages werden verweigert")
    parser.add_argument("--ausfuehren", action="store_true", help="wirklich loeschen (sonst nur Anzeige)")
    args = parser.parse_args(argv)
    storage = args.storage.expanduser().resolve()
    index_file = storage / ".storage" / "status_registry" / "storage_index.json"
    source_root = (storage / "raw_storage" / "chatgpt").resolve()
    try:
        data = json.loads(index_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Kein lesbarer Gesamtindex: {index_file} ({type(exc).__name__})")
        return 2
    entries = {cid: e for cid, e in (data.get("conversations") or {}).items()
               if isinstance(e, dict) and e.get("source", "chatgpt") == "chatgpt"}
    print(f"Storage: {storage} – {len(entries)} ChatGPT-Konversationen im Index")
    if len(entries) > args.max:
        print(f"Verweigert: mehr als {args.max} Konversationen – das ist kein kleiner Test-Storage.")
        return 2
    chosen = pick(entries, args.anzahl)
    removed = 0
    for cid, role in chosen:
        target = (source_root / str(entries[cid].get("relative_path") or "")).resolve()
        if source_root not in target.parents or not target.is_file():
            print(f"  uebersprungen ({role}): {cid} – Datei fehlt oder liegt ausserhalb von {source_root}")
            continue
        print(f"  {'loesche' if args.ausfuehren else 'wuerde loeschen'} ({role}): {cid}  "
              f"[{entries[cid].get('remote_updated_at')}]  {target.relative_to(storage)}")
        if args.ausfuehren:
            target.unlink()
            removed += 1
    if not args.ausfuehren:
        print("Nur Anzeige – nichts geloescht. Mit --ausfuehren wirklich loeschen.")
    else:
        print(f"{removed} Datei(en) geloescht. Der naechste 'update' muss genau diese neu laden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
