"""Atomares Schreiben und Zeitstempel fuer den Raw Session Updater.

Bewusst eigene Kopie (statt Import aus einem Provider): der Raw Session Updater haengt von
keinem Provider-Code ab.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def atomic_write_bytes(path: Path, data: bytes, staging_dir: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage_root = staging_dir or path.parent
    stage_root.mkdir(parents=True, exist_ok=True)
    tmp = stage_root / f".{path.name}.{os.getpid()}.tmp"
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    # Windows: Virenscanner/Indexer koennen das Ziel kurz sperren.
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


def atomic_write_json(path: Path, value: Any, *, staging_dir: Path | None = None,
                      indent: int = 2) -> bytes:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent) + "\n").encode("utf-8")
    atomic_write_bytes(path, data, staging_dir=staging_dir)
    return data


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
