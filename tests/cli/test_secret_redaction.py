"""Secrets aus ``--set`` werden nie gespeichert (Befehlsprotokoll, state.yaml, Sperrdatei).

Befund Release-Check 2026-10-05: ``chatexporter --set providers.chatgpt.auth.password=… status``
schrieb den Wert im Klartext in ``.storage/logs/commands_*.jsonl`` und ``state.yaml``.
"""

from __future__ import annotations

import os
from pathlib import Path

from chatexporter.cli.main import main, redact_cli_args


def test_secret_values_in_set_are_hidden_in_every_form():
    shown = redact_cli_args(["--set", "providers.chatgpt.auth.password=GEHEIM-1",
                             "--set=providers.chatgpt.auth.totp_secret=GEHEIM-2",
                             "--set", "providers.chatgpt.sync.listing_mode=full", "update", "--source", "chatgpt"])
    assert shown == ["--set", "providers.chatgpt.auth.password=(verdeckt)",
                     "--set=providers.chatgpt.auth.totp_secret=(verdeckt)",
                     "--set", "providers.chatgpt.sync.listing_mode=full", "update", "--source", "chatgpt"]


def test_a_secret_passed_with_set_is_never_written_to_disk():
    home = Path(os.environ["CHATEXPORTER_HOME"])
    config_dir = Path(os.environ["CHATEXPORTER_CONFIG"]).parent
    code = main(["--set", "providers.chatgpt.auth.password=GEHEIM-XYZ-123", "config", "path"])
    assert code == 0
    written = [p for root in {home, config_dir} if root.exists() for p in root.rglob("*") if p.is_file()]
    assert any(p.name.startswith("commands_") for p in written), "Befehlsprotokoll wurde geschrieben"
    assert any(p.name == "state.yaml" for p in written), "state.yaml wurde geschrieben"
    leaks = [str(p) for p in written if b"GEHEIM-XYZ-123" in p.read_bytes()]
    assert leaks == []
