"""Neuanmeldung mitten im Lauf live pruefen (read-only, wenige Anfragen).

Ablauf: Sitzung im angegebenen Browserprofil pruefen (2 Anfragen), dann EINE
Listing-Anfrage (limit=1) absichtlich mit einem ungueltigen Token senden. Erwartet:
HTTP 401 -> Anmeldung wird ueber den Browser erneuert (2 Anfragen) -> dieselbe
Anfrage einmal wiederholt -> HTTP 200. Insgesamt 6 Anfragen, keine Commits,
keine Manifeste. Tokens erscheinen in keiner Ausgabe.

Sicherheit: ohne --live passiert nichts (nur Plan, Exit 0).

Beispiel:
    python tools\\chatgpt\\reauth_check.py --config ..\\config.yaml --profil ..\\_login_test_profil4 --live
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Direktstart (ohne Installation) ermoeglichen.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from chatexporter.providers.chatgpt.api.client import ApiClient, RequestCounter  # noqa: E402
from chatexporter.providers.chatgpt.api.conversations import ConversationApi  # noqa: E402
from chatexporter.providers.chatgpt.auth.browser_setup import auth_broker  # noqa: E402
from chatexporter.providers.chatgpt.auth.edge_cdp import EdgeCdpSession  # noqa: E402
from chatexporter.providers.chatgpt.config.loader import load_config  # noqa: E402
from chatexporter.providers.chatgpt.contract import reauthenticator  # noqa: E402

#: Absichtlich ungueltiger Token (kein Geheimnis), um ein echtes HTTP 401 auszuloesen.
INVALID_TOKEN = "ungueltig-fuer-reauth-check"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--profil", dest="profile", type=Path, default=None,
                        help="Browser-Datenverzeichnis mit gueltiger ChatGPT-Anmeldung")
    parser.add_argument("--live", action="store_true", help="wirklich ausfuehren (sonst nur Plan)")
    args = parser.parse_args()
    print("Plan: Sitzung pruefen (2 Anfragen), Listing limit=1 mit ungueltigem Token -> 401 -> "
          "Erneuerung (2 Anfragen) -> Wiederholung (1 Anfrage).", flush=True)
    if not args.live:
        print("Ohne --live: nichts ausgefuehrt.")
        return 0
    cfg = load_config(args.config)
    if args.profile is not None:
        cfg.browser.user_data_dir = args.profile.expanduser().resolve()
        cfg.browser.user_data_dir_configured = True
    counter = RequestCounter()
    session = EdgeCdpSession(cfg.browser).connect()
    try:
        auth = auth_broker(cfg, session, counter=counter).acquire(interactive=False)
        print(f"Sitzung gueltig (Anfragen bisher: {counter.total}).", flush=True)
        client = ApiClient(auth.context, INVALID_TOKEN, base_url=cfg.api.base_url, counter=counter,
                           reauthenticate=reauthenticator(cfg, session, interactive=False,
                                                          counter=counter, say=print))
        page = ConversationApi(client).list_page(offset=0, limit=1)
        result = {"ok": True, "listing_items": len(page.get("items") or []),
                  "token_renewed": client.access_token not in (INVALID_TOKEN,),
                  "reauth": client.reauth_events, "requests": counter.as_dict()}
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300],
                  "requests": counter.as_dict()}
    finally:
        try:
            session.abandon() if session.launched else session.close()
        except Exception:  # noqa: BLE001
            pass
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
