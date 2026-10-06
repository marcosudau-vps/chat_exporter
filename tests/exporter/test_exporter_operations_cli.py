"""Export aus dem Raw Storage: Ablauf, Manifest, Fehlerverhalten, Kommandozeile."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from chatexporter.exporter import cli, formats, operations
from chatexporter.exporter.config import load_exporter_config


def _store(raw_root: Path, simple_raw, summary, cid: str) -> Path:
    env = {"conversation_id": cid, "remote_summary": summary | {"id": cid}, "raw": simple_raw,
           "file_references": [], "textdocs": []}
    path = raw_root / "chatgpt" / "conversations" / "2026" / "09" / "26" / f"{cid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(env), encoding="utf-8")
    return path


@pytest.fixture
def setup(tmp_path, simple_raw, summary):
    data = tmp_path / "data"
    raw_root = data / "raw_storage"
    paths = [_store(raw_root, simple_raw, summary, cid) for cid in ("c1", "c2")]
    config = tmp_path / "config.yaml"
    config.write_text(f"storage:\n  data_root: {data.as_posix()}\n", encoding="utf-8")
    return tmp_path, config, paths


def _hashes(paths):
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def test_export_writes_all_formats_and_manifest(setup):
    tmp, config, _ = setup
    cfg = load_exporter_config(config)
    report, code = operations.export(cfg)
    assert code == 0 and report["conversations"] == 2 and report["files_written"] == 4
    assert report["failures"] == 0
    export_root = tmp / "data" / "exports"
    assert sorted(p.name for p in (export_root / "markdown" / "chatgpt" / "2026-09").glob("*.md")) == ["c1.md", "c2.md"]
    assert sorted(p.name for p in (export_root / "json" / "chatgpt" / "2026-09").glob("*.json")) == ["c1.json", "c2.json"]
    manifests = list((export_root / "manifests").glob("export_*.json"))
    assert len(manifests) == 1 and str(manifests[0]) == report["manifest"]
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2 and manifest["sources"] == ["chatgpt", "opencode", "codex", "claude"]
    assert manifest["conversations_by_source"] == {"chatgpt": 2, "opencode": 0, "codex": 0, "claude": 0}
    assert {o["path"] for o in manifest["outputs"]} >= {"markdown/chatgpt/2026-09/c1.md", "json/chatgpt/2026-09/c2.json"}


def test_export_never_modifies_the_raw_storage(setup):
    _, config, paths = setup
    before = _hashes(paths)
    operations.export(load_exporter_config(config))
    assert _hashes(paths) == before
    raw_root = paths[0].parents[5]
    assert sorted(p.name for p in raw_root.iterdir()) == ["chatgpt"], "keine neuen Dateien im Raw Storage"


def test_export_is_idempotent(setup):
    tmp, config, _ = setup
    cfg = load_exporter_config(config)
    operations.export(cfg)
    first = {p: p.read_bytes() for p in (tmp / "data" / "exports").rglob("*") if p.is_file()
             and "manifests" not in p.parts}
    operations.export(cfg)
    second = {p: p.read_bytes() for p in (tmp / "data" / "exports").rglob("*") if p.is_file()
              and "manifests" not in p.parts}
    assert first == second and len(first) == 4


def test_export_selected_format_only(setup):
    tmp, config, _ = setup
    report, code = operations.export(load_exporter_config(config), formats=["json"])
    assert code == 0 and report["files_written"] == 2
    assert (tmp / "data" / "exports" / "json").is_dir()
    assert not (tmp / "data" / "exports" / "markdown").exists()


def test_export_without_raw_data_is_ok(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(f"storage:\n  data_root: {(tmp_path / 'leer').as_posix()}\n", encoding="utf-8")
    report, code = operations.export(load_exporter_config(config))
    assert code == 0 and report["conversations"] == 0 and report["files_written"] == 0


def test_unreadable_files_are_reported_and_do_not_stop_the_export(setup):
    tmp, config, paths = setup
    (paths[0].parent / "kaputt.json").write_text("{kaputt", encoding="utf-8")
    messages = []
    report, code = operations.export(load_exporter_config(config), progress=messages.append)
    assert code == 1 and report["conversations"] == 2 and report["failures"] == 1
    assert any("kaputt.json" in m for m in messages)
    manifest = json.loads(Path(report["manifest"]).read_text(encoding="utf-8"))
    assert manifest["errors"][0]["path"].endswith("kaputt.json")


def test_failing_format_does_not_stop_the_others(setup, monkeypatch):
    tmp, config, _ = setup
    real = formats.FORMATS["markdown"]
    original = real._write

    def failing(target, view, staging):
        if view["conversation_id"] == "c1":
            raise OSError("Platte voll")
        original(target, view, staging)

    monkeypatch.setattr(real, "_write", failing)
    report, code = operations.export(load_exporter_config(config))
    assert code == 1 and report["failures"] == 1 and report["files_written"] == 3
    manifest = json.loads(Path(report["manifest"]).read_text(encoding="utf-8"))
    assert manifest["errors"] == [{"source": "chatgpt", "conversation_id": "c1", "format": "markdown",
                                   "error": "OSError: Platte voll"}]
    assert (tmp / "data" / "exports" / "json" / "chatgpt" / "2026-09" / "c1.json").exists()


# -- Kommandozeile ---------------------------------------------------------------------

def test_cli_exports_and_prints_report(setup, capsys):
    tmp, config, _ = setup
    assert cli.main(["--config", str(config)]) == 0
    out = capsys.readouterr().out
    report = json.loads(out[out.index("{"):])
    assert report["conversations"] == 2 and report["files_written"] == 4
    assert (tmp / "data" / "exports" / "markdown").is_dir()


def test_cli_options_override_the_config(setup, capsys):
    tmp, config, _ = setup
    target = tmp / "anderswo"
    assert cli.main(["--config", str(config), "--format", "json", "--source", "chatgpt",
                     "--export-root", str(target)]) == 0
    assert (target / "json" / "chatgpt" / "2026-09" / "c1.json").exists()
    assert not (target / "markdown").exists()


def test_cli_raw_root_override(tmp_path, simple_raw, summary, capsys):
    raw = tmp_path / "andere_roh"
    _store(raw, simple_raw, summary, "x1")
    config = tmp_path / "config.yaml"
    config.write_text("{}\n", encoding="utf-8")
    assert cli.main(["--config", str(config), "--raw-root", str(raw), "--export-root", str(tmp_path / "ex")]) == 0
    assert (tmp_path / "ex" / "json" / "chatgpt" / "2026-09" / "x1.json").exists()


def test_cli_exit_codes(setup, capsys):
    tmp, config, paths = setup
    (paths[0].parent / "kaputt.json").write_text("{kaputt", encoding="utf-8")
    assert cli.main(["--config", str(config)]) == 1
    bad = tmp / "bad.yaml"
    bad.write_text("exporter:\n  formats: [pdf]\n", encoding="utf-8")
    assert cli.main(["--config", str(bad)]) == 2
    assert "Konfigurationsfehler" in capsys.readouterr().err


def test_cli_rejects_unknown_format_choice(setup):
    _, config, _ = setup
    with pytest.raises(SystemExit) as exc:
        cli.main(["--config", str(config), "--format", "pdf"])
    assert exc.value.code == 2


def test_single_entry_point(setup, capsys, monkeypatch):
    _, config, _ = setup
    monkeypatch.setattr("sys.argv", ["chatexporter-export", "--config", str(config)])
    assert cli.export_main() == 0
