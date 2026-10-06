"""Werkzeug fuer den Testablauf: Chats nur lokal loeschen (tools/chatgpt/local_delete_probe.py)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("local_delete_probe", ROOT / "tools/chatgpt/local_delete_probe.py")
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


def _storage(tmp_path: Path, n: int) -> Path:
    storage = tmp_path / "storage"
    conversations = {}
    for i in range(n):
        rel = f"conversations/2026/10/0{i % 9 + 1}/c{i}.json"
        path = storage / "raw_storage" / "chatgpt" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        conversations[f"c{i}"] = {"source": "chatgpt", "relative_path": rel,
                                  "remote_updated_at": f"2026-10-01T00:00:{i:02d}Z"}
    conversations["fremd"] = {"source": "codex", "relative_path": "x.json", "remote_updated_at": None}
    index = storage / ".storage" / "status_registry" / "storage_index.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({"conversations": conversations}), encoding="utf-8")
    return storage


def _remaining(storage: Path) -> set[str]:
    return {p.stem for p in (storage / "raw_storage" / "chatgpt").rglob("*.json")}


def test_picks_newest_middle_oldest_and_deletes_only_with_flag(tmp_path, capsys):
    storage = _storage(tmp_path, 7)
    assert probe.main(["--storage", str(storage)]) == 0
    assert _remaining(storage) == {f"c{i}" for i in range(7)}, "ohne --ausfuehren nichts geloescht"
    assert probe.main(["--storage", str(storage), "--ausfuehren"]) == 0
    assert _remaining(storage) == {"c1", "c2", "c4", "c5"}, "neuester c6, mittlerer c3, aeltester c0"
    out = capsys.readouterr().out
    assert "(neuester): c6" in out and "(aeltester): c0" in out


def test_refuses_large_storages(tmp_path, capsys):
    storage = _storage(tmp_path, 12)
    assert probe.main(["--storage", str(storage), "--max", "10", "--ausfuehren"]) == 2
    assert len(_remaining(storage)) == 12 and "Verweigert" in capsys.readouterr().out
