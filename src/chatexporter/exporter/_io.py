"""Atomares Schreiben fuer den Exporter.

Bewusst eigene Kopie (statt Import aus einem Provider oder dem Raw Session
Updater): der Exporter haengt von keiner anderen Schicht ab.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write_bytes(path: Path, data: bytes, staging_dir: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage_root = staging_dir or path.parent
    stage_root.mkdir(parents=True, exist_ok=True)
    tmp = stage_root / f".{path.name}.{os.getpid()}.tmp"
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    # Windows: ein frisch geschriebenes Ziel kann kurz durch Virenscanner/Indexer
    # gesperrt sein; ein kurzer Retry verhindert sporadische PermissionError.
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:  # WinError 5/32
            last_error = exc
            time.sleep(0.1 * (attempt + 1))
    if last_error is not None:
        raise last_error


def atomic_write_text(path: Path, text: str, *, staging_dir: Path | None = None) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), staging_dir=staging_dir)


def atomic_write_json(path: Path, value: Any, *, staging_dir: Path | None = None, indent: int = 2) -> None:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent) + "\n"
    atomic_write_bytes(path, payload.encode("utf-8"), staging_dir=staging_dir)
