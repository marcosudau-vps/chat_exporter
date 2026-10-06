"""OpenCode: neue DB-Tabelle session_v2 und neues Exportformat (location).

Regression zum Lauf vom 2026-09-30: alle 48 Sessions scheiterten mit "Session
wurde waehrend des Exports veraendert (Retry-Limit)", weil der Export das
Verzeichnis nur noch unter info.location.directory fuehrt (Windows-Schreibweise)
und die alte Tabelle `session` veraltete Zeitstempel hatte.
"""

from __future__ import annotations

import json
import sqlite3

from chatexporter.providers import opencode as oc

COLUMNS = ("id TEXT, title TEXT, time_created INTEGER, time_updated INTEGER, "
           "project_id TEXT, directory TEXT, parent_id TEXT, time_archived INTEGER")


def _db(tmp_path):
    path = tmp_path / "opencode.db"
    with sqlite3.connect(path) as conn:
        conn.execute(f"CREATE TABLE session ({COLUMNS})")
        conn.execute(f"CREATE TABLE session_v2 ({COLUMNS})")
        # Alte Tabelle: nur eine Session, veralteter Zeitstempel.
        conn.execute("INSERT INTO session VALUES ('ses_a', 'A', 1790000000000, 1790000001000, "
                     "'global', 'P:/Projekt/a', NULL, NULL)")
        conn.executemany("INSERT INTO session_v2 VALUES (?, ?, ?, ?, 'global', ?, NULL, NULL)", [
            ("ses_a", "A", 1790000000000, 1790000009000, "P:/Projekt/a"),
            ("ses_b", "B", 1790000100000, 1790000100500, "P:/Projekt/b"),
        ])
    return path


def _cfg(tmp_path, db):
    return oc._config({"raw_root": tmp_path / "raw", "runtime_root": tmp_path / "runtime",
                       "db_path": db})


def _export(sid, created, updated, directory):
    # Neues Format: kein info.directory, sondern location.directory mit "\".
    return json.dumps({
        "info": {"id": sid, "title": sid[-1].upper(), "projectID": "global",
                 "location": {"directory": directory.replace("/", "\\")},
                 "time": {"created": created, "updated": updated}},
        "messages": [],
    }).encode("utf-8")


def test_prefers_session_v2_table(tmp_path):
    cfg = _cfg(tmp_path, _db(tmp_path))
    rows = {r["id"]: r for r in oc._list_sessions(cfg)}
    assert set(rows) == {"ses_a", "ses_b"}, "session_v2 enthaelt mehr Sessions"
    assert rows["ses_a"]["updated"] == 1790000009000, "aktueller Zeitstempel aus v2"


def test_info_signature_reads_location_and_normalizes_path():
    info = {"id": "ses_a", "title": "A", "projectID": "global",
            "location": {"directory": "P:\\Projekt\\a\\"},
            "time": {"created": 1, "updated": 2}}
    row = {"id": "ses_a", "updated": 2, "created": 1, "title": "A", "projectId": "global",
           "directory": "P:/Projekt/a", "parentID": None, "archived": None}
    assert oc._info_signature(info) == oc._snapshot_signature(row)


def test_update_succeeds_with_new_export_format(tmp_path, monkeypatch):
    db = _db(tmp_path)
    exports = {"ses_a": _export("ses_a", 1790000000000, 1790000009000, "P:/Projekt/a"),
               "ses_b": _export("ses_b", 1790000100000, 1790000100500, "P:/Projekt/b")}

    def fake_cli(cfg, *args, cwd=None):
        assert args[:2] == ("session", "export")
        return exports[args[2]]

    monkeypatch.setattr(oc, "_cli", fake_cli)
    result = oc.update(_cfg(tmp_path, db))
    assert result["ok"] is True, result["errors"]
    assert result["stats"]["sessions_fetched"] == 2 and result["stats"]["sessions_failed"] == 0
    assert sorted(i["id"] for i in result["items"]["fetched"]) == ["ses_a", "ses_b"]
    again = oc.update(_cfg(tmp_path, db))
    assert again["stats"]["sessions_unchanged"] == 2, "gespeicherter Stand gilt als aktuell"
    assert again["items"]["fetched"] == []
