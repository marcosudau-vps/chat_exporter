"""Browser-Profile: Erkennung, ChatGPT-Cookies (nur Namen), Profilkopie."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from chatexporter.providers.chatgpt.auth import profiles
from chatexporter.providers.chatgpt.auth.profiles import BrowserProfile


def _cookies(profile_dir: Path, rows: list[tuple[str, str]]) -> Path:
    db = profile_dir / "Network" / "Cookies"
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, encrypted_value BLOB)")
        conn.executemany("INSERT INTO cookies VALUES (?, ?, ?)", [(h, n, b"GEHEIM") for h, n in rows])
    return db


def _user_data(tmp_path: Path) -> Path:
    root = tmp_path / "User Data"
    for name in ("Default", "Profile 1", "Profile 2"):
        (root / name).mkdir(parents=True)
        (root / name / "Preferences").write_text("{}", encoding="utf-8")
    (root / "System Profile").mkdir()                      # kein Benutzerprofil
    (root / "Local State").write_text(json.dumps({
        "os_crypt": {"encrypted_key": "SCHLUESSEL"},
        "profile": {"last_used": "Profile 2", "last_active_profiles": ["Default", "Profile 2"],
                    "info_cache": {"Default": {"name": "Privat"}, "Profile 1": {"name": "Arbeit"},
                                   "Profile 2": {"name": "Leer"}}}}), encoding="utf-8")
    _cookies(root / "Default", [(".chatgpt.com", "__Secure-next-auth.session-token"),
                                ("chatgpt.com", "oai-did"), (".google.com", "SID")])
    _cookies(root / "Profile 1", [("chatgpt.com", "oai-did")])
    _cookies(root / "Profile 2", [(".example.org", "x")])
    return root


def test_cookie_status_reads_names_only(tmp_path):
    root = _user_data(tmp_path)
    status, detail = profiles.chatgpt_cookie_status(root / "Default")
    assert status is True and "Sitzungs-Cookie" in detail and "GEHEIM" not in detail
    assert profiles.chatgpt_cookie_status(root / "Profile 1")[0] is False
    assert "kein Sitzungs-Cookie" in profiles.chatgpt_cookie_status(root / "Profile 1")[1]
    assert profiles.chatgpt_cookie_status(root / "Profile 2") == (False, "keine ChatGPT-Cookies")
    assert profiles.chatgpt_cookie_status(tmp_path / "fehlt") == (False, "keine Cookie-Datenbank")


def test_unreadable_cookies_are_unknown(tmp_path):
    folder = tmp_path / "kaputt" / "Network"
    folder.mkdir(parents=True)
    (folder / "Cookies").write_bytes(b"keine Datenbank")
    status, detail = profiles.chatgpt_cookie_status(tmp_path / "kaputt")
    assert status is None and "nicht lesbar" in detail


def test_list_profiles_names_and_order(tmp_path):
    root = _user_data(tmp_path)
    found = profiles.list_profiles("edge", root)
    assert [(p.directory, p.name, p.chatgpt) for p in found] == [
        ("Default", "Privat", True), ("Profile 1", "Arbeit", False), ("Profile 2", "Leer", False)]
    assert profiles.list_profiles("edge", tmp_path / "fehlt") == []
    assert found[0].label == "Microsoft Edge – Profil 'Privat' (Default)"


def test_copy_profile_is_complete_without_caches_and_selects_the_profile(tmp_path):
    root = _user_data(tmp_path)
    (root / "Profile 1" / "Cache" / "Cache_Data").mkdir(parents=True)
    (root / "Profile 1" / "Cache" / "Cache_Data" / "f_000001").write_bytes(b"x" * 100)
    (root / "Profile 1" / "Local Storage").mkdir()
    (root / "Profile 1" / "Local Storage" / "leveldb").write_text("daten", encoding="utf-8")
    (root / "Profile 1" / "LOCK").write_text("", encoding="utf-8")
    profile = BrowserProfile("edge", root, "Profile 1", "Arbeit", False)
    target = profiles.copy_target(tmp_path / "browser", profile, now=datetime(2026, 10, 3, 4, 54, 16))
    assert target == tmp_path / "browser" / "profiles" / "2026-10-03_04-54-16_Profile_1"
    said: list[str] = []
    assert profiles.copy_profile(profile, target, say=said.append, in_use=lambda p: False) == target
    assert (target / "Profile 1" / "Network" / "Cookies").is_file()
    assert (target / "Profile 1" / "Local Storage" / "leveldb").is_file()
    assert not (target / "Profile 1" / "Cache").exists() and not (target / "Profile 1" / "LOCK").exists()
    assert not (target / "Default").exists(), "nur das gewaehlte Profil"
    state = json.loads((target / "Local State").read_text(encoding="utf-8"))
    assert state["os_crypt"] == {"encrypted_key": "SCHLUESSEL"}, "Cookie-Schluessel unveraendert"
    assert state["profile"]["last_used"] == "Profile 1"
    assert list(state["profile"]["info_cache"]) == ["Profile 1"]
    assert json.loads((root / "Local State").read_text(encoding="utf-8"))["profile"]["last_used"] == "Profile 2", \
        "Original bleibt unveraendert"
    copies = profiles.existing_copies(tmp_path / "browser")
    assert [(p.name, info["name"], info["kind"]) for p, info in copies] == [
        ("2026-10-03_04-54-16_Profile_1", "Arbeit", "edge")]
    assert profiles.copy_of(copies, profile) == target
    assert profiles.copy_of(copies, BrowserProfile("chrome", root, "Profile 1", "x", True)) is None
    assert any("Kopie fertig" in s for s in said)
    # erneutes Kopieren ersetzt die Kopie vollstaendig
    (target / "alt.txt").write_text("alt", encoding="utf-8")
    profiles.copy_profile(profile, target, in_use=lambda p: False)
    assert not (target / "alt.txt").exists() and not target.with_name(target.name + ".partial").exists()


def test_copy_refuses_while_browser_is_open_and_leaves_nothing(tmp_path):
    root = _user_data(tmp_path)
    profile = BrowserProfile("chrome", root, "Default", "Privat", True)
    target = tmp_path / "browser" / "profiles" / "chrome-kopie-Default"
    with pytest.raises(RuntimeError, match="noch geoeffnet"):
        profiles.copy_profile(profile, target, in_use=lambda p: True)
    assert not target.exists()


def test_failed_copy_removes_the_partial_folder(tmp_path):
    root = _user_data(tmp_path)
    profile = BrowserProfile("edge", root, "Profile 9", "fehlt", None)
    target = tmp_path / "b" / "profiles" / "edge-kopie-Profile_9"
    with pytest.raises(OSError):
        profiles.copy_profile(profile, target, in_use=lambda p: False)
    assert not target.exists() and not target.with_name(target.name + ".partial").exists()
