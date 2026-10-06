"""Architekturregel: Raw Session Updater und Provider sind voneinander unabhängig.

- ``chatexporter.raw_session_updater``   importiert keinen Provider- und keinen CLI-Code
- ``providers.chatgpt``      importiert weder Raw Session Updater, CLI noch andere Provider
- ``providers.<einzeldatei>`` importieren gar nichts aus ``chatexporter``
- ``chatexporter.exporter`` importiert nur sich selbst (liest nur den Raw Storage)
- ``chatexporter.task_scheduler`` importiert nur sich selbst
- nur die Bedienschicht (``chatexporter.cli``) darf beide Seiten kennen

Provider werden vom Raw Session Updater ausschließlich per Modulpfad (String) geladen.
"""

from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "chatexporter"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return {name for name in found if name.startswith("chatexporter")}


def _violations(folder: Path, allowed_prefixes: tuple[str, ...]) -> list[str]:
    bad = []
    for path in sorted(folder.rglob("*.py")):
        for name in _imports(path):
            if not name.startswith(allowed_prefixes):
                bad.append(f"{path.relative_to(PKG)} -> {name}")
    return bad


def test_updater_does_not_import_providers_or_cli():
    assert _violations(PKG / "raw_session_updater", ("chatexporter.raw_session_updater", "chatexporter.config")) == []


def test_exporter_is_self_contained():
    assert _violations(PKG / "exporter", ("chatexporter.exporter", "chatexporter.config")) == []


def test_task_scheduler_is_self_contained():
    assert _violations(PKG / "task_scheduler", ("chatexporter.task_scheduler", "chatexporter.config")) == []


def test_chatgpt_provider_is_self_contained():
    assert _violations(PKG / "providers" / "chatgpt", ("chatexporter.providers.chatgpt", "chatexporter.config")) == []


def test_single_file_providers_import_nothing_from_package():
    for name in ("opencode.py", "codex.py", "claude.py"):
        assert _imports(PKG / "providers" / name) == set(), name


def test_top_level_contains_only_layers():
    entries = {p.name for p in PKG.iterdir() if not p.name.startswith("__pycache__")}
    assert entries == {"__init__.py", "__main__.py", "raw_session_updater", "cli", "providers",
                       "task_scheduler", "exporter", "config"}


def test_config_core_imports_only_itself_and_the_generic_library():
    assert _violations(PKG / "config", ("chatexporter.config",)) == []


def test_generic_config_library_knows_nothing_about_chatexporter():
    lib = PKG.parent / "layered_config"
    for path in sorted(lib.rglob("*.py")):
        assert _imports(path) == set(), path.name


def test_two_factor_library_knows_nothing_about_chatexporter():
    lib = PKG.parent / "two_factor_tools"
    for path in sorted(lib.rglob("*.py")):
        assert _imports(path) == set(), path.name


def test_two_factor_library_is_an_unchanged_copy():
    import hashlib
    digest = hashlib.sha256((PKG.parent / "two_factor_tools" / "core.py").read_bytes()).hexdigest()
    assert digest.startswith("3dec9b9b042eb7cf"), "core.py weicht vom Original der Two-Factor Tools V4 ab"
