"""Listing-Parameter-Semantik vermessen (read-only).

Prueft, was die Query-Parameter des Listing-Endpunkts
GET /backend-api/conversations wirklich steuern – insbesondere ob
`order=updated` eine verlaessliche Neueste-zuerst-Sortierung liefert, mit der
man statt des Voll-Listings nur die ersten Seiten abrufen muss.

Reine Messonde: keine Commits, keine Manifeste. Ergebnis als Ledger (JSON) in
--out (Default: daten_zur_analyse/listing_params_<UTC>).

Sicherheit: ohne --live passiert nichts (nur Plan, Exit 0). Mit --live maximal
len(MATRIX) Requests (aktuell 10), Abbruch bei Auth-/Transportproblemen
(ausser bei als fehler-erwartet markierten Proben).

Beispiel:
    python tools\\chatgpt\\listing_params_probe.py --config ..\\config.yaml --live
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Direktstart (ohne Installation) ermoeglichen.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from chatexporter.providers.chatgpt.api.client import ApiTransportClosedError  # noqa: E402
from chatexporter.providers.chatgpt.auth.broker import AuthBroker  # noqa: E402
from chatexporter.providers.chatgpt.auth.edge_cdp import EdgeCdpSession  # noqa: E402
from chatexporter.providers.chatgpt.api.client import ApiClient  # noqa: E402
from chatexporter.providers.chatgpt.config.loader import load_config  # noqa: E402

# (Name, Params, Fehler-ok?)
MATRIX: list[tuple[str, dict[str, Any], bool]] = [
    ("active_default_20", {"offset": 0, "limit": 20}, False),
    ("active_order_updated_20", {"offset": 0, "limit": 20, "order": "updated"}, False),
    ("active_order_updated_20_p2", {"offset": 20, "limit": 20, "order": "updated"}, False),
    ("browser_exact", {"exclude_conversation_origin": "tpp", "expand": "false",
                       "hide_snorlax": "false", "is_archived": "false",
                       "is_starred": "false", "limit": 20, "order": "updated",
                       "offset": 60}, False),
    ("active_order_updated_100", {"offset": 0, "limit": 100, "order": "updated"}, False),
    ("archived_order_updated_20", {"is_archived": "true", "offset": 0, "limit": 20,
                                   "order": "updated"}, False),
    ("archived_default_20", {"is_archived": "true", "offset": 0, "limit": 20}, False),
    ("active_order_updated_20_repeat", {"offset": 0, "limit": 20, "order": "updated"}, False),
    ("active_order_created_20", {"offset": 0, "limit": 20, "order": "created"}, True),
    ("active_order_bogus_20", {"offset": 0, "limit": 20, "order": "doesnotexist"}, True),
    # Origin-Partition (Browser fragt tpp / nicht-tpp getrennt ab). Erst im
    # Idle-Rerun mit freiem Kontingent ausführen; unser Standard-Listing sendet
    # keinen Origin-Parameter – Abgleich der Totals klärt Vollständigkeit.
    ("tpp_origin_20", {"conversation_origin": "tpp", "limit": 20, "order": "updated",
                       "offset": 0}, False),
    ("exclude_tpp_20", {"exclude_conversation_origin": "tpp", "limit": 20,
                        "order": "updated", "offset": 0}, False),
]

SUMMARY_FIELDS = ("id", "title", "create_time", "update_time", "is_archived",
                  "is_starred", "pinned_time", "gizmo_id")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _summarize(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"_raw_type": type(item).__name__}
    return {k: item.get(k) for k in SUMMARY_FIELDS}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Listing-Parameter vermessen (nur lesen)")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--live", action="store_true",
                        help="Wirklich Requests senden. Ohne --live nur Plan ausgeben.")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--only", type=str, default=None, metavar="NAME,...",
                        help="Nur diese Proben aus MATRIX ausführen (Reihenfolge wie angegeben). "
                             "Spart Tokens, z. B. --only active_order_updated_20,active_default_20")
    args = parser.parse_args(argv)

    selected = MATRIX
    if args.only:
        wanted = [n.strip() for n in args.only.split(",") if n.strip()]
        known = {name for name, _, _ in MATRIX}
        unknown = [n for n in wanted if n not in known]
        if unknown:
            parser.error(f"unbekannte Proben: {unknown} (bekannt: {sorted(known)})")
        selected = [(n, p, e) for n, p, e in MATRIX if n in wanted]
        selected.sort(key=lambda row: wanted.index(row[0]))

    if not args.live:
        print("DRY-RUN (kein --live): Es wuerden genau diese "
              f"{len(selected)} Requests gesendet:")
        for name, params, expect_error in selected:
            flag = " (Fehler erwartet/ok)" if expect_error else ""
            print(f"  - {name}: {params}{flag}")
        print("Mit --live starten.")
        return 0

    out = args.out or Path("daten_zur_analyse") / f"listing_params_{_utcnow().replace(':','').replace('-','')}"
    out.mkdir(parents=True, exist_ok=True)
    ledger: list[dict[str, Any]] = []

    def flush(partial: bool = False):
        (out / "ledger.json").write_text(
            json.dumps({"partial": partial, "probes": ledger},
                       indent=2, ensure_ascii=False), encoding="utf-8")

    cfg = load_config(args.config)
    try:
        with EdgeCdpSession(cfg.browser) as edge:
            auth = AuthBroker(edge, cfg.api.base_url, cfg.api.request_timeout_ms).acquire(
                interactive=False)
            print(f"Session ok: {auth.identity.email or auth.identity.user_id or '?'}",
                  flush=True)
            client = ApiClient(auth.context, auth.access_token,
                               base_url=cfg.api.base_url,
                               timeout_ms=cfg.api.request_timeout_ms)
            for name, params, expect_error in selected:
                t0 = time.perf_counter()
                try:
                    resp = client.request("GET", "/backend-api/conversations", params=params)
                except ApiTransportClosedError as exc:
                    print(f"[{name}] TRANSPORT-CLOSED, Abbruch.")
                    flush(partial=True)
                    return 2
                except Exception as exc:  # ECONNRESET, Timeout, ...
                    ledger.append({"name": name, "params": params, "t": _utcnow(),
                                   "transport_error": f"{type(exc).__name__}: {str(exc)[:200]}",
                                   "expect_error": expect_error})
                    print(f"[{name}] Transportfehler ({type(exc).__name__}), Abbruch.",
                          flush=True)
                    flush(partial=True)
                    return 2
                latency = (time.perf_counter() - t0) * 1000.0
                try:
                    payload = resp.json()
                except Exception:
                    payload = None
                row: dict[str, Any] = {
                    "name": name, "params": params, "t": _utcnow(),
                    "status": resp.status, "latency_ms": round(latency, 1),
                    "expect_error": expect_error,
                }
                if isinstance(payload, dict):
                    row["total"] = payload.get("total")
                    row["top_keys"] = sorted(payload.keys())
                    items = payload.get("items")
                    if isinstance(items, list):
                        row["item_count"] = len(items)
                        row["items"] = [_summarize(i) for i in items]
                    else:
                        row["detail"] = payload.get("detail")
                else:
                    row["payload_type"] = type(payload).__name__
                ledger.append(row)
                info = (f"items={row.get('item_count')} total={row.get('total')}"
                        if resp.status == 200 else f"detail={row.get('detail')}")
                print(f"[{name}] status={resp.status} lat={latency:.0f}ms {info}",
                      flush=True)
                if resp.status in (401, 403) and not expect_error:
                    print("Auth-Problem, Abbruch.", flush=True)
                    flush(partial=True)
                    return 2
    except KeyboardInterrupt:
        print("\nAbgebrochen (Strg+C), sichere Teilergebnisse ...", flush=True)
        flush(partial=True)
        return 2
    flush(partial=False)
    print(f"Fertig ({len(ledger)} Proben). Ledger: {out / 'ledger.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
