"""Befehlsprotokoll: Dauerangaben, Rotation, Aufraeumen, Datensatzinhalt."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from chatexporter.cli import command_log as cl


@pytest.mark.parametrize("text,seconds", [
    ("30s", 30), ("15m", 900), ("24h", 86400), ("7d", 604800), ("2w", 1209600),
    ("1d12h", 129600), ("90", 90), (3600, 3600), (" 7D ", 604800),
])
def test_parse_duration(text, seconds):
    assert cl.parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "abc", "7x", "7d x", "d7", True])
def test_parse_duration_rejects_garbage(text):
    with pytest.raises(ValueError):
        cl.parse_duration(text)


def _settings(tmp_path, rotation="24h", retention="30d", enabled=True):
    return cl.LogSettings(enabled=enabled, directory=tmp_path / "logs",
                          rotation_seconds=cl.parse_duration(rotation),
                          retention_seconds=cl.parse_duration(retention))


def test_rotation_one_file_per_period(tmp_path):
    s = _settings(tmp_path, rotation="24h")
    a = datetime(2026, 10, 1, 0, 30, tzinfo=timezone.utc)
    b = datetime(2026, 10, 1, 23, 59, tzinfo=timezone.utc)
    c = datetime(2026, 10, 2, 0, 1, tzinfo=timezone.utc)
    assert cl.log_file_for(s, a) == cl.log_file_for(s, b)
    assert cl.log_file_for(s, a).name == "commands_20261001T0000Z.jsonl"
    assert cl.log_file_for(s, c).name == "commands_20261002T0000Z.jsonl"
    hourly = _settings(tmp_path, rotation="1h")
    assert cl.log_file_for(hourly, b).name == "commands_20261001T2300Z.jsonl"


def test_prune_removes_only_expired_own_files(tmp_path):
    s = _settings(tmp_path, rotation="24h", retention="7d")
    s.directory.mkdir()
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    old = s.directory / "commands_20261001T0000Z.jsonl"
    keep = s.directory / "commands_20261015T0000Z.jsonl"
    foreign = s.directory / "notizen.jsonl"
    for p in (old, keep, foreign):
        p.write_text("{}\n", encoding="utf-8")
    assert cl.prune(s, now) == [old]
    assert keep.exists() and foreign.exists()
    assert cl.prune(_settings(tmp_path, retention="0"), now) == [], "0 = nie loeschen"


def _config(tmp_path, logging_block):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"storage:\n  data_root: {tmp_path / 'data'}\n{logging_block}", encoding="utf-8")
    return cfg


def _records(directory):
    files = sorted(directory.glob("commands_*.jsonl"))
    return [json.loads(line) for f in files for line in f.read_text(encoding="utf-8").splitlines()]


def test_run_logged_writes_record_with_summary_fields(tmp_path, capsys):
    run_manifest = tmp_path / "sync_x.json"
    run_manifest.write_text(json.dumps({"partial": True, "sources": {
        "chatgpt": {"ok": True, "duration_seconds": 10.8,
                    "stats": {"sessions_new": 1, "sessions_changed": 5, "sessions_fetched": 6,
                              "sessions_failed": 0, "files_materialized": 2, "requests_total": 9},
                    "items": {"fetched": [{"id": "a"}] * 6, "failed": []},
                    "detail": {"listing": {"mode": "auto", "effective": "recent"}}},
        "opencode": {"ok": False, "duration_seconds": 1.0, "stats": {"sessions_failed": 3},
                     "items": {"fetched": [], "failed": [{"id": "s"}] * 3}}}}), encoding="utf-8")
    cfg = _config(tmp_path, "logging:\n  dir: logs\n  rotation: 7d\n")

    def run():
        print("Fortschritt ...")
        print(json.dumps({"run_manifest": str(run_manifest), "partial": True,
                          "totals": {"sessions_fetched": 6, "requests_total": 9}}, indent=2))
        return 2

    code = cl.run_logged("chatexporter", ["--config", str(cfg), "update"], run)
    assert code == 2
    assert "Fortschritt" in capsys.readouterr().out, "Konsole bekommt weiterhin alles"
    [rec] = _records(tmp_path / "logs")
    assert rec["command"] == f"chatexporter --config {cfg} update"
    assert rec["exit_code"] == 2 and rec["interrupted"] is False
    assert rec["timestamp"].endswith("Z") and rec["duration_seconds"] >= 0
    assert rec["config_file"] == str(cfg) and rec["version"]
    s = rec["summary"]
    assert s["partial"] is True and s["totals"] == {"sessions_fetched": 6, "requests_total": 9}
    assert s["sources"]["chatgpt"] == {
        "ok": True, "sessions_new": 1, "sessions_changed": 5, "sessions_fetched": 6,
        "sessions_failed": 0, "files_materialized": 2, "requests_total": 9,
        "duration_seconds": 10.8, "items_fetched": 6, "items_failed": 0,
        "listing_mode": "auto", "listing_effective": "recent"}
    assert s["sources"]["opencode"]["items_failed"] == 3


def test_interrupt_is_logged_and_reraised(tmp_path):
    cfg = _config(tmp_path, "logging:\n  dir: logs\n")

    def run():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        cl.run_logged("chatexporter", ["--config", str(cfg), "update"], run)
    [rec] = _records(tmp_path / "logs")
    assert rec["exit_code"] == 130 and rec["interrupted"] is True


def test_default_dir_is_the_storage_and_disable_works(tmp_path):
    cfg = _config(tmp_path, "")
    cl.run_logged("chatexporter", ["--config", str(cfg), "status"], lambda: 0)
    assert _records(tmp_path / "data" / ".storage" / "logs"), "Default: .storage/logs im Storage"
    off = tmp_path / "off"
    off.mkdir()
    cfg_off = off / "config.yaml"
    cfg_off.write_text(f"storage:\n  data_root: {off / 'data'}\nlogging:\n  enabled: false\n",
                       encoding="utf-8")
    cl.run_logged("chatexporter", ["--config", str(cfg_off), "status"], lambda: 0)
    assert not (off / "logs").exists()


def test_broken_logging_config_never_breaks_the_command(tmp_path, capsys):
    cfg = _config(tmp_path, "logging:\n  rotation: bald\n")
    assert cl.run_logged("chatexporter", ["--config", str(cfg), "status"], lambda: 0) == 0
    assert "Befehlsprotokoll nicht geschrieben" in capsys.readouterr().err


def test_entry_points_are_logged(tmp_path):
    from chatexporter.cli import main as main_mod
    cfg = _config(tmp_path, "logging:\n  dir: logs\nraw_session_updater:\n  sources: [chatgpt]\n")
    assert main_mod.check_main(["--config", str(cfg)]) == 0
    assert main_mod.main(["--config", str(cfg), "status"]) == 0
    records = _records(tmp_path / "logs")
    assert [r["program"] for r in records] == ["chatexporter-check", "chatexporter"]
    assert records[0]["summary"]["ok"] is True
    assert records[0]["summary"]["sources"]["chatgpt"]["ok"] is True
