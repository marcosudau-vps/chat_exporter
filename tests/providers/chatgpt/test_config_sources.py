"""ChatGPT-Config: gemeinsame config.yaml, data_root und Sektion providers.chatgpt."""

from __future__ import annotations

from chatexporter.providers.chatgpt.config.loader import discover_config, load_config


def test_data_root_provides_defaults(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(f"storage:\n  data_root: {tmp_path / 'data'}\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.storage.raw_root == tmp_path / "data" / "raw_storage"
    assert cfg.storage.runtime_root == tmp_path / "data" / ".storage"
    assert cfg.browser.user_data_dir == tmp_path / "browser" / "profiles" / "edge", "Browser global"


def test_explicit_paths_beat_data_root(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(f"storage:\n  data_root: {tmp_path / 'data'}\n  raw_root: {tmp_path / 'other'}\n",
                 encoding="utf-8")
    cfg = load_config(p)
    assert cfg.storage.raw_root == tmp_path / "other"


def test_providers_chatgpt_section_preferred_over_top_level(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("sync:\n  listing_mode: full\n"
                 "providers:\n  chatgpt:\n    sync:\n      listing_mode: recent\n",
                 encoding="utf-8")
    assert load_config(p).sync.listing_mode == "recent"
    p.write_text("sync:\n  listing_mode: recent\n", encoding="utf-8")
    assert load_config(p).sync.listing_mode == "recent"


def test_discover_config_walks_up_and_env_wins(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("{}\n", encoding="utf-8")
    code = tmp_path / "ChatExporter_Gen4_pre-6" / "src"
    code.mkdir(parents=True)
    monkeypatch.delenv("CHATEXPORTER_CONFIG", raising=False)
    assert discover_config(start=code) == tmp_path / "config.yaml"
    other = tmp_path / "x.yaml"
    monkeypatch.setenv("CHATEXPORTER_CONFIG", str(other))
    assert discover_config(start=code) == other
    assert discover_config(tmp_path / "explicit.yaml") == tmp_path / "explicit.yaml"
