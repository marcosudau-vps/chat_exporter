from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_bytes(path: Path, data: bytes, staging_dir: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage_root = staging_dir or path.parent
    stage_root.mkdir(parents=True, exist_ok=True)
    tmp = stage_root / f".{path.name}.{os.getpid()}.tmp"
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    # Windows: ein frisch geschriebenes Ziel kann kurzzeitig durch Virenscanner/
    # Indexer gesperrt sein. Ein kurzer Retry verhindert sporadische
    # PermissionError bei os.replace, ohne die Atomaritaet aufzugeben.
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


def atomic_write_json(path: Path, value: Any, *, staging_dir: Path | None = None, indent: int = 2) -> bytes:
    data = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=indent) + "\n").encode("utf-8")
    atomic_write_bytes(path, data, staging_dir=staging_dir)
    return data


def atomic_write_text(path: Path, text: str, *, staging_dir: Path | None = None) -> None:
    atomic_write_bytes(path, text.encode("utf-8"), staging_dir=staging_dir)
