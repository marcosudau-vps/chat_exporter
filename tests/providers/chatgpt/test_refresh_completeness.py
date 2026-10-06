"""Tests fuer die Neuberechnung von files_complete/complete (Bestandsdaten)."""
from __future__ import annotations

from chatexporter.providers.chatgpt.storage.envelope import refresh_acquisition_completeness


class FakeLibrary:
    def __init__(self, states):
        self._states = states

    def derived_state(self, ref):
        return self._states.get(ref.get("id"), "PENDING")


def _envelope(files_complete=True):
    return {
        "acquisition": {"json_complete": True, "files_complete": files_complete, "complete": files_complete},
        "file_references": [{"id": "file_a"}],
    }


def test_refresh_downgrades_stale_true_when_a_file_is_pending():
    env = _envelope(files_complete=True)
    assert refresh_acquisition_completeness(env, FakeLibrary({})) is True
    assert env["acquisition"]["files_complete"] is False
    assert env["acquisition"]["complete"] is False


def test_refresh_keeps_true_when_all_references_are_closed():
    env = _envelope(files_complete=True)
    assert refresh_acquisition_completeness(env, FakeLibrary({"file_a": "MATERIALIZED"})) is False
    assert env["acquisition"]["files_complete"] is True


def test_refresh_upgrades_false_when_files_are_now_available():
    env = _envelope(files_complete=False)
    assert refresh_acquisition_completeness(env, FakeLibrary({"file_a": "UNAVAILABLE"})) is True
    assert env["acquisition"]["files_complete"] is True
    assert env["acquisition"]["complete"] is True
