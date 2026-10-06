from __future__ import annotations
import re
from pathlib import Path

_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_-]+$")


def safe_component(value: str, *, label: str = "identifier") -> str:
    if not isinstance(value, str) or not value or not _SAFE_COMPONENT.fullmatch(value):
        raise ValueError(f"Unsafe {label}: {value!r}")
    return value
