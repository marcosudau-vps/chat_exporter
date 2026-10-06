from __future__ import annotations
import os
import pytest


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path_factory, monkeypatch):
    """Tests duerfen NIE die echte config.yaml/.env oder den echten Bestand sehen.

    Die Config-Suche steigt vom Arbeitsordner auf und wuerde sonst die
    config.yaml des uebergeordneten workspace finden. Deshalb zeigt
    CHATEXPORTER_CONFIG hier auf eine nicht vorhandene Datei in einem
    Temp-Ordner, und alle uebrigen CHATEXPORTER_*-Variablen werden entfernt.
    Home-Verzeichnis und Registry-Spiegel werden ebenfalls umgelenkt bzw. abgeschaltet.
    """
    for name in list(os.environ):
        if name.startswith("CHATEXPORTER_"):
            monkeypatch.delenv(name, raising=False)
    isolated_dir = tmp_path_factory.mktemp("isolated_config")
    isolated = isolated_dir / "config.yaml"
    monkeypatch.setenv("CHATEXPORTER_CONFIG", str(isolated))
    # Nie das echte ~/.chatexporter und nie die echte Registry anfassen.
    monkeypatch.setenv("CHATEXPORTER_HOME", str(isolated_dir / "home"))
    monkeypatch.setenv("CHATEXPORTER_REGISTRY_MIRROR", "off")
    from chatexporter import config as shared_config
    shared_config.set_cli_overrides([])
    yield


@pytest.fixture
def simple_raw():
    return {
        "conversation_id": "c1",
        "title": "Hello",
        "create_time": 1789700000.0,
        "update_time": 1789700100.0,
        "current_node": "a2",
        "mapping": {
            "root": {"id": "root", "message": None, "parent": None, "children": ["u1"]},
            "u1": {"id": "u1", "parent": "root", "children": ["a1"], "message": {
                "id": "u1", "author": {"role": "user", "name": None}, "create_time": 1,
                "content": {"content_type": "text", "parts": ["Hi"]}, "metadata": {}, "recipient": "all"
            }},
            "a1": {"id": "a1", "parent": "u1", "children": ["a2"], "message": {
                "id": "a1", "author": {"role": "assistant", "name": None}, "create_time": 2,
                "content": {"content_type": "text", "parts": ["Hello"]}, "metadata": {}, "recipient": "all"
            }},
            "a2": {"id": "a2", "parent": "a1", "children": [], "message": {
                "id": "a2", "author": {"role": "assistant", "name": None}, "create_time": 3,
                "content": {"content_type": "reasoning_recap", "parts": ["Short visible recap"]}, "metadata": {}, "recipient": "all"
            }},
        },
    }


@pytest.fixture
def summary():
    return {
        "id": "c1", "title": "Hello", "create_time": 1789700000.0,
        "update_time": 1789700100.0, "is_archived": False,
        "is_starred": False, "pinned_time": None, "gizmo_id": None,
    }
