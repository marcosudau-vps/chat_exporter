"""Anbindung an das Script ``tools/task_scheduler/scheduler_manager.py``.

Das Script (PyTaskManager, Windows-Aufgabenplanung ueber COM) liegt ausserhalb
des Pakets und wird hier nur per Dateipfad geladen, nicht kopiert.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from .config import TaskSetupError

MODULE_NAME = "chatexporter_scheduler_manager"


def load_backend(script: Path) -> ModuleType:
    """Laedt scheduler_manager.py (einmal je Prozess und Pfad)."""
    script = Path(script)
    cached = sys.modules.get(MODULE_NAME)
    if cached is not None and Path(getattr(cached, "__file__", "")).resolve() == script.resolve():
        return cached
    if sys.platform != "win32":
        raise TaskSetupError("Die Zeitplanung nutzt die Windows-Aufgabenplanung und laeuft nur unter Windows.")
    if not script.is_file():
        raise TaskSetupError(
            f"scheduler_manager.py nicht gefunden: {script}. Der Codeordner muss "
            f"tools/task_scheduler/ enthalten, oder task_scheduler.manager_script setzen.")
    spec = importlib.util.spec_from_file_location(MODULE_NAME, script)
    if spec is None or spec.loader is None:
        raise TaskSetupError(f"scheduler_manager.py nicht ladbar: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module  # noetig fuer dataclasses mit String-Annotationen
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(MODULE_NAME, None)
        raise TaskSetupError(f"scheduler_manager.py konnte nicht geladen werden: {exc}") from exc
    if getattr(module, "_PYWIN32_IMPORT_ERROR", None) is not None:
        sys.modules.pop(MODULE_NAME, None)
        raise TaskSetupError("pywin32 fehlt. Installation: pip install pywin32 "
                             "(oder pip install -e .[scheduler])")
    return module
