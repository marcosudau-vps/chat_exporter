"""Datei-Namensraeume und verschachtelte Asset-Pointer.

pre-4 hat zwei Klassen von Dateien still uebersehen (gemessen 2026-09-22
ueber 1036 produktive Conversations):

* 233 Sprachaufnahmen, weil der Pointer bei
  ``real_time_user_audio_video_asset_pointer`` eine Ebene tiefer liegt
* 99 aeltere Bilder mit ``file-service://``-Schema und ``file-``-Praefix
"""
from __future__ import annotations

from chatexporter.providers.chatgpt.fetch.reference_extractor import (
    extract_file_references,
    is_audio_reference,
)
from chatexporter.providers.chatgpt.storage.library import LibraryStore


def _payload(part: dict) -> dict:
    return {"mapping": {"n1": {"id": "n1", "parent": None, "children": [], "message": {
        "id": "m1", "author": {"role": "user"},
        "content": {"content_type": "multimodal_text", "parts": [part]},
        "create_time": 1.0}}}}


def test_modern_sediment_pointer_is_found():
    refs = extract_file_references(_payload({
        "content_type": "image_asset_pointer",
        "asset_pointer": "sediment://file_abc123",
    }))
    assert [r["id"] for r in refs] == ["file_abc123"]


def test_legacy_file_service_pointer_is_found():
    """Von pre-4 ignoriert: anderes Schema UND anderes ID-Praefix."""
    refs = extract_file_references(_payload({
        "content_type": "image_asset_pointer",
        "asset_pointer": "file-service://file-XyZ789",
    }))
    assert [r["id"] for r in refs] == ["file-XyZ789"]


def test_nested_voice_mode_audio_pointer_is_found():
    """Der Fall, der pre-4 233 Sprachaufnahmen gekostet hat."""
    refs = extract_file_references(_payload({
        "content_type": "real_time_user_audio_video_asset_pointer",
        "audio_start_timestamp": 12.5,
        "audio_asset_pointer": {
            "content_type": "audio_asset_pointer",
            "asset_pointer": "sediment://file_audio001",
            "format": "wav",
            "size_bytes": 968204,
        },
    }))
    assert len(refs) == 1
    ref = refs[0]
    assert ref["id"] == "file_audio001"
    assert ref["kind"] == "audio_asset_pointer"
    assert ref["format"] == "wav"
    assert ref["size"] == 968204
    assert is_audio_reference(ref) is True


def test_audio_and_normal_files_use_separate_buckets(tmp_path):
    store = LibraryStore(tmp_path)
    audio_ref = {"id": "file_audio001", "kind": "audio_asset_pointer", "format": "wav"}
    image_ref = {"id": "file_img001", "kind": "image_asset_pointer"}
    assert store.file_dir("file_audio001", audio_ref).parent.name == "audio"
    assert store.file_dir("file_img001", image_ref).parent.name == "files"


def test_legacy_prefix_is_no_longer_unsupported(tmp_path):
    """pre-4 stufte 'file-' pauschal als UNSUPPORTED ein und lud es nie."""
    store = LibraryStore(tmp_path)
    assert store.derived_state({"id": "file-XyZ789"}) == "PENDING"
    assert store.derived_state({"id": "file_abc123"}) == "PENDING"
    assert store.derived_state({"id": "something-else"}) == "UNSUPPORTED"


def test_audio_extension_comes_from_format(tmp_path):
    """Sprachaufnahmen haben oft weder Dateiname noch MIME-Typ -- ohne die
    Format-Auswertung landeten sie alle als '.bin'."""
    from chatexporter.providers.chatgpt.storage.library import _extension
    assert _extension({}, {"format": "wav", "kind": "audio_asset_pointer"}) == ".wav"
    assert _extension({}, {"id": "x"}) == ".bin"
