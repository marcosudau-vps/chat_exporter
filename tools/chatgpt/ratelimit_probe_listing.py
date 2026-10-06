"""Rate-Limit-Vermessung des Listing-Endpunkts GET /backend-api/conversations.

Reine Messonde: sendet rohe Listing-Requests (limit=100, Offsets im gueltigen
Bereich) und protokolliert Status, Latenz, Body-Detail und Rate-Limit-Header.
Schreibt NICHTS in den Rohdatenbestand (keine Commits, keine Manifeste);
Ergebnis landet als Ledger (JSON) + Bericht (Markdown) im --out-Ordner.

Sicherheit:
- Ohne --live passiert nichts (nur Plan-Ausgabe, Exit 0).
- Stopp beim ersten 429 in der Burst-Phase, harte Obergrenze --max-requests.
- Abbruch bei 401/403 (Auth) und totem Transport. Strg+C sichert Teilergebnisse.

Beispiel:
    python tools\\chatgpt\\ratelimit_probe_listing.py --config ..\\config.yaml --live
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

INTERESTING_HEADERS = ("retry-after", "ratelimit-limit", "ratelimit-remaining",
                       "ratelimit-reset", "x-ratelimit-limit", "x-ratelimit-remaining",
                       "x-ratelimit-reset", "cf-chl-out")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_payload(payload: Any) -> Any:
    try:
        return json.loads(json.dumps(payload, default=str))
    except Exception:
        return str(payload)[:500]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Listing-Rate-Limit vermessen (nur lesen)")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--live", action="store_true",
                        help="Wirklich Requests senden. Ohne --live nur Plan ausgeben.")
    parser.add_argument("--max-requests", type=int, default=80,
                        help="Harte Obergrenze Burst-Phase (max 200).")
    parser.add_argument("--refill-interval", type=int, default=120,
                        help="Sekunden zwischen Refill-Probes.")
    parser.add_argument("--refill-probes", type=int, default=8,
                        help="Maximale Zahl Refill-Probes.")
    parser.add_argument("--paced", type=int, default=0, metavar="SEKUNDEN",
                        help="Getakteter Modus statt Burst: alle SEKUNDEN ein Probe-Request "
                             "(0 = Burst-Modus). Testet die dauerhaft tragbare Rate.")
    parser.add_argument("--paced-n", type=int, default=10,
                        help="Zahl der Probes im getakteten Modus.")
    parser.add_argument("--out", type=Path, default=None,
                        help="Zielordner (Default: daten_zur_analyse/ratelimit_listing_<UTC>).")
    args = parser.parse_args(argv)

    max_requests = min(max(1, args.max_requests), 200)
    if not args.live:
        print("DRY-RUN (kein --live): Es wuerde passieren:")
        print(f"  1. Health-Check: 1x GET /backend-api/conversations (muss 200 sein).")
        if args.paced > 0:
            print(f"  2. Getaktete Phase: {args.paced_n}x Listing-Page (limit=100) alle "
                  f"{args.paced}s, Stopp beim ersten Nicht-200.")
        else:
            print(f"  2. Burst-Phase: sequentielle Listing-Pages (limit=100, Offsets 0..2900")
            print(f"     zyklisch), ohne kuenstliche Pause, Stopp beim ersten Nicht-200")
            print(f"     oder bei {max_requests} Requests.")
        print(f"  3. Refill-Phase (nur nach 429): alle {args.refill_interval}s ein Probe-")
        print(f"     Request, max. {args.refill_probes}x, bis wieder 200 oder erschöpft.")
        print("Mit --live starten.")
        return 0

    out = args.out or Path("daten_zur_analyse") / f"ratelimit_listing_{_utcnow().replace(':','').replace('-','')}"
    out.mkdir(parents=True, exist_ok=True)
    ledger: list[dict[str, Any]] = []
    seq = 0

    def record(phase: str, offset: int, status: int | None, latency_ms: float,
               items: int | None, detail: Any, headers: dict[str, str],
               note: str = "") -> dict[str, Any]:
        nonlocal seq
        seq += 1
        row = {"seq": seq, "phase": phase, "t": _utcnow(), "offset": offset,
               "status": status, "latency_ms": round(latency_ms, 1),
               "items": items, "detail": detail,
               "headers": {k: v for k, v in headers.items()},
               "note": note}
        ledger.append(row)
        print(f"[{seq:3d}/{phase}] offset={offset:5d} status={status} "
              f"lat={latency_ms:7.1f}ms items={items} {detail or ''} {note}".rstrip(),
              flush=True)
        return row

    def flush(partial: bool = False):
        (out / "ledger.json").write_text(
            json.dumps({"partial": partial, "requests": ledger},
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

            def probe(offset: int) -> tuple[int | None, float, Any, dict, int | None, str]:
                """Ein roher Listing-Request. Gibt (status, latenz, detail, header, items, transportfehler) zurueck."""
                t0 = time.perf_counter()
                try:
                    resp = client.request("GET", "/backend-api/conversations",
                                          params={"offset": offset, "limit": 100})
                except ApiTransportClosedError as exc:
                    return None, 0.0, None, {}, None, f"transport-closed: {exc}"
                except Exception as exc:  # z. B. ECONNRESET, Timeout
                    return None, 0.0, None, {}, None, f"{type(exc).__name__}: {str(exc)[:200]}"
                latency = (time.perf_counter() - t0) * 1000.0
                try:
                    payload = resp.json()
                except Exception:
                    payload = None
                detail = payload.get("detail") if isinstance(payload, dict) else None
                items = len(payload.get("items")) if isinstance(payload, dict) and isinstance(payload.get("items"), list) else None
                headers = {k.lower(): v for k, v in (resp.headers or {}).items()
                           if k.lower() in INTERESTING_HEADERS}
                return resp.status, latency, detail, headers, items, ""

            # Phase 0: Health.
            status, lat, detail, headers, items, terr = probe(0)
            if terr or status != 200:
                record("health", 0, status, lat, items, detail, headers,
                       note=terr or "KEIN 200 -> Abbruch")
                flush(partial=True)
                print("Health-Check fehlgeschlagen, Abbruch ohne weitere Requests.")
                return 2
            record("health", 0, status, lat, items, detail, headers)

            # Phase 1: Burst (ohne Pause) oder getaktet (feste Abstände).
            paced = args.paced > 0
            phase = "paced" if paced else "burst"
            n_main = args.paced_n if paced else max_requests
            burst_429_at: int | None = None
            sent = 0
            offsets = [(i * 100) % 3000 for i in range(n_main)]
            for idx, offset in enumerate(offsets):
                if paced and idx > 0:
                    time.sleep(args.paced)
                sent += 1
                status, lat, detail, headers, items, terr = probe(offset)
                if terr:
                    record(phase, offset, status, lat, items, detail, headers,
                           note=f"{terr} -> Abbruch")
                    flush(partial=True)
                    print(f"Transportfehler in der {phase}-Phase, Abbruch.")
                    return 2
                if status == 401 or status == 403:
                    record(phase, offset, status, lat, items, detail, headers,
                           note="Auth-Problem -> Abbruch")
                    flush(partial=True)
                    print("401/403: Auth-Problem, kein Rate-Limit-Test. Abbruch.")
                    return 2
                record(phase, offset, status, lat, items, detail, headers,
                       note="STOP (erstes Nicht-200)" if status != 200 else "")
                if status != 200:
                    if status == 429:
                        burst_429_at = sent
                    break
            else:
                print(f"{phase}-Cap erreicht ({n_main} Requests, alle 200).")

            # Phase 2: Refill-Vermessung.
            if burst_429_at is not None:
                print(f"429 nach {burst_429_at} Burst-Requests. Starte Refill-Phase "
                      f"(alle {args.refill_interval}s, max. {args.refill_probes}x).", flush=True)
                recovered_at: int | None = None
                for i in range(args.refill_probes):
                    time.sleep(args.refill_interval)
                    status, lat, detail, headers, items, terr = probe(0)
                    if terr or status in (401, 403):
                        record("refill", 0, status, lat, items, detail, headers,
                               note=f"{terr or status} -> Abbruch")
                        flush(partial=True)
                        print("Abbruch in der Refill-Phase.")
                        return 2
                    record("refill", 0, status, lat, items, detail, headers)
                    if status == 200:
                        recovered_at = (i + 1) * args.refill_interval
                        break
                print("Refill-Ergebnis:",
                      f"wieder 200 nach ca. {recovered_at}s" if recovered_at is not None
                      else f"nach {args.refill_probes * args.refill_interval}s immer noch kein 200",
                      flush=True)
            else:
                time.sleep(min(args.refill_interval, 120))
                status, lat, detail, headers, items, terr = probe(0)
                record("confirm", 0, status, lat, items, detail, headers,
                       note=terr or "")
    except KeyboardInterrupt:
        print("\nAbgebrochen (Strg+C), sichere Teilergebnisse ...", flush=True)
        flush(partial=True)
        return 2
    flush(partial=False)
    _write_report(out, ledger, args.refill_interval)
    print(f"Fertig. Ledger + Bericht: {out}")
    return 0


def _write_report(out: Path, ledger: list[dict[str, Any]], interval: int) -> None:
    main = [r for r in ledger if r["phase"] in ("burst", "paced")]
    main_label = "getaktet" if any(r["phase"] == "paced" for r in main) else "Burst"
    refill = [r for r in ledger if r["phase"] == "refill"]
    first_bad = next((r for r in main if r["status"] != 200), None)
    ok_200 = [r for r in main if r["status"] == 200]
    lats = [r["latency_ms"] for r in ok_200]
    lines = [
        "# Listing-Rate-Limit: Messbericht",
        "",
        f"- Requests gesamt: {len(ledger)} ({main_label}: {len(main)}, Refill: {len(refill)})",
    ]
    if first_bad is None:
        lines.append(f"- {main_label}: alle {len(main)} Requests 200 → "
                     + ("getaktete Rate dauerhaft tragbar." if main_label == "getaktet"
                        else f"Kapazität > {len(main)} bei Burst-Tempo."))
    else:
        lines.append(f"- {main_label}: 429 nach {first_bad['seq'] - 1} erfolgreichen 200ern "
                     f"(erster Nicht-200 bei seq={first_bad['seq']}, Detail: {first_bad['detail']}).")
    if lats:
        lines.append(f"- Latenz 200er: min {min(lats)} ms, median {sorted(lats)[len(lats)//2]} ms, max {max(lats)} ms.")
    ok_refill = [r for r in refill if r["status"] == 200]
    if first_bad is not None:
        if ok_refill:
            n_fail = len(refill) - len(ok_refill)
            lines.append(f"- Refill: wieder 200 nach {n_fail} fehlgeschlagenen Probe(s) "
                         f"→ Erholung grob zwischen {n_fail * interval}s und {(n_fail + 1) * interval}s "
                         f"(exaktes Intervall siehe Ledger-Zeiten).")
        else:
            lines.append(f"- Refill: nach {len(refill)} Probes noch kein 200 → Erholung langsamer als Messfenster.")
    hdrs = {}
    for r in ledger:
        hdrs.update(r.get("headers") or {})
    lines.append(f"- Beobachtete Rate-Limit-Header: {hdrs if hdrs else 'keine'}")
    lines.append("")
    lines.append("Rohdaten: `ledger.json` (jeder Request mit Zeit, Offset, Status, Latenz, Detail).")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
