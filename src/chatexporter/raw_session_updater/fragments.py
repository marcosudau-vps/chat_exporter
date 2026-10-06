"""Index-Fragmente der Provider pruefen und zusammenfuehren.

Jeder Provider liefert mit ``recreate_index`` ein Fragment; der Raw Session Updater prueft
es streng (fail-closed) und fuehrt alle zum Gesamtindex zusammen. Die Regeln
sind Teil des Provider-Vertrags (docs/PROVIDER_CONTRACT.md).
"""

from __future__ import annotations

from typing import Any

FRAGMENT_SCHEMA_VERSION = 1
INDEX_SCHEMA_VERSION = 1
FILE_INDEX_SCHEMA_VERSION = 1


def coverage(indexed: int, candidates: int) -> float:
    if candidates <= 0:
        return 100.0
    return round(100.0 * indexed / candidates, 1)


def coverage_of(fragment: dict[str, Any]) -> float:
    """Coverage-Prozent eines Fragments (top-level oder verschachtelt)."""
    value = fragment.get("coverage_percent")
    if not isinstance(value, (int, float)):
        nested = fragment.get("coverage") or {}
        value = nested.get("percent") if isinstance(nested, dict) else None
    if not isinstance(value, (int, float)):
        raise ValueError("fragment coverage missing")
    return float(value)


def normalize_failed_files(fragment: dict[str, Any], source: str) -> list[dict[str, Any]]:
    """Vereinheitlicht `failed_files` zu `{source, file, error}`.

    Eintraege duerfen Strings (relativ zur Quellen-Wurzel) oder Objekte mit
    `file` (relativ zur Store-Wurzel, inkl. Quelle) sein.
    """
    out: list[dict[str, Any]] = []
    failed = fragment.get("failed_files") or []
    if not isinstance(failed, list):
        raise ValueError("fragment failed_files not a list")
    for item in failed:
        if isinstance(item, str):
            out.append({"source": source, "file": f"{source}/{item}", "error": "unparseable"})
        elif isinstance(item, dict) and isinstance(item.get("file"), str) and item["file"]:
            out.append({"source": item.get("source") or source,
                        "file": item["file"],
                        "error": item.get("error") or "unparseable"})
        else:
            raise ValueError("fragment failed_files entry invalid")
    return out


def validate_fragment(fragment: Any) -> dict[str, Any]:
    """Prueft ein Fragment streng. Ungueltig -> ValueError (fail-closed, kein Commit).

    ID-Regel je Eintrag: Schluessel ohne Doppelpunkt muessen dem ID-Feld
    (`conversation_id`/`session_id`/`record_id`) entsprechen. Schluessel MIT
    Doppelpunkt muessen mit `<quelle>:<kind>:` beginnen und tragen ihre
    Identitaet im Suffix (Datei-abbildende Provider); ein ID-Feld ist dann
    empfohlen, aber nicht Pflicht.
    """
    if not isinstance(fragment, dict):
        raise ValueError("fragment is not an object")
    if fragment.get("fragment_schema_version") != FRAGMENT_SCHEMA_VERSION:
        raise ValueError("fragment schema mismatch")
    source = fragment.get("source")
    if not isinstance(source, str) or not source:
        raise ValueError("fragment source missing")
    entries = fragment.get("entries")
    if not isinstance(entries, dict):
        raise ValueError("fragment entries missing")
    for key in ("candidates", "indexed", "failed_files"):
        if key not in fragment:
            raise ValueError(f"fragment meta missing: {key}")
    coverage_of(fragment)
    file_refs = fragment.get("file_refs", {})
    if not isinstance(file_refs, dict):
        raise ValueError("fragment file_refs missing")
    for cid, entry in entries.items():
        if not isinstance(cid, str) or not cid:
            raise ValueError("fragment entry key invalid")
        if not isinstance(entry, dict):
            raise ValueError(f"fragment entry not an object: {cid}")
        if entry.get("source") != source:
            raise ValueError(f"fragment entry source mismatch: {cid}")
        kind = entry.get("kind")
        if not isinstance(kind, str) or not kind:
            raise ValueError(f"fragment entry kind missing: {cid}")
        if not isinstance(entry.get("relative_path"), str) or not entry["relative_path"]:
            raise ValueError(f"fragment entry relative_path missing: {cid}")
        record_id = (entry.get("conversation_id") or entry.get("session_id")
                     or entry.get("record_id"))
        if ":" not in cid:
            if not isinstance(record_id, str) or record_id != cid:
                raise ValueError(f"fragment entry id mismatch: {cid}")
        else:
            if not cid.startswith(f"{source}:{kind}:"):
                raise ValueError(f"fragment entry key not namespaced: {cid}")
            if record_id is not None and not isinstance(record_id, str):
                raise ValueError(f"fragment entry id invalid: {cid}")
    normalize_failed_files(fragment, source)
    return fragment
