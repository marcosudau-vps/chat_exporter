"""Auswertung des Gesamttests (tools/chatgpt/live_testablauf.py) – ohne ChatGPT."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("live_testablauf", ROOT / "tools/chatgpt/live_testablauf.py")
live = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = live
_spec.loader.exec_module(live)


def test_login_json_is_read_from_the_end_of_the_output():
    out = ("Keine gueltige ChatGPT-Sitzung – automatische Anmeldung ...\n  Anmeldung: ...\n{\n"
           '  "ok": true,\n  "already_logged_in": false,\n  "auto_login": {"ok": true, "pages": ["chatgpt.com/"]}\n}\n')
    data = live.parse_login_json(out)
    assert data["ok"] is True and data["already_logged_in"] is False and data["auto_login"]["pages"] == ["chatgpt.com/"]
    assert live.parse_login_json("keine JSON-Ausgabe") is None


def test_deleted_ids_match_the_output_of_the_delete_probe(tmp_path, capsys):
    """Gegen die echte Ausgabe des Werkzeugs, nicht gegen eine nachgebaute."""
    spec = importlib.util.spec_from_file_location("probe_for_live", ROOT / "tools/chatgpt/local_delete_probe.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    from test_local_delete_probe import _storage
    storage = _storage(tmp_path, 7)
    probe.main(["--storage", str(storage), "--ausfuehren"])
    assert live.parse_deleted_ids(capsys.readouterr().out) == ["c6", "c3", "c0"]


def test_task_result_and_login_detection():
    assert live.parse_task_result("Status: Bereit\nLetztes Ergebnis: 0\n") == 0
    assert live.parse_task_result("Letztes Ergebnis: 267011") == live.TASK_NOT_RUN
    assert live.parse_task_result("nichts") is None
    assert not live.no_login("Keine gueltige ChatGPT-Sitzung – automatische Anmeldung ...")
    assert not live.no_login("Automatische Anmeldung nicht abgeschlossen: ...")
    assert live.no_login("DEV-MODUS AKTIV: hoechstens 5 Listing-Seiten je Bereich\nSync abgeschlossen")


def test_secrets_are_compared_but_never_returned(tmp_path):
    env = tmp_path / ".env"
    env.write_text("CHATGPT_PASSWORD=alt-wert-1\n# Kommentar\nCHATGPT_PASSWORD=neu-wert-2\nCHATGPT_USERNAME=n@example.org\n",
                   encoding="utf-8")
    values = live.read_dotenv(env)
    assert values["CHATGPT_PASSWORD"] == "neu-wert-2", "letzter Eintrag gewinnt (wie beim Programm)"
    found = live.find_secrets("Ausgabe mit neu-wert-2 darin", values)
    assert found == ["CHATGPT_PASSWORD"] and "neu-wert-2" not in " ".join(found)
    assert live.find_secrets("m***@example.org", values) == [], "maskierte Adresse ist kein Fund"


def test_test_configuration_is_valid_and_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "WORKSPACE", tmp_path)
    run = live.Run(tmp_path / "_testlauf" / "x", tmp_path / "bericht", {})
    live.write_config(run)
    from chatexporter.providers.chatgpt.config.loader import load_config
    cfg = load_config(run.config)
    assert cfg.dev_mode and cfg.dev_settings.listing_max_pages == 5 and cfg.dev_settings.conversation_fetches == 0
    assert cfg.sync.listing_limit == 5 and cfg.browser.cdp_port == 9333 and cfg.browser.leave_browser_running is False
    assert cfg.browser.user_data_dir == run.root / "profil"
    assert Path(cfg.storage.raw_root).parent == run.storage
    assert "CHATEXPORTER_CONFIG" in run.env and not [k for k in run.env if k.startswith("CHATEXPORTER_")
                                                      and k != "CHATEXPORTER_CONFIG"]
