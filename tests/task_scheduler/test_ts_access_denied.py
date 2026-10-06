"""task create ohne Adminrechte (z. B. --startup): verstaendliche Meldung statt rohem COM-Fehler."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("scheduler_manager_probe",
                                               ROOT / "tools/task_scheduler/scheduler_manager.py")
manager = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = manager          # Datenklassen im Modul brauchen den Eintrag
_spec.loader.exec_module(manager)


class ComError(Exception):
    pass


def test_access_denied_is_recognized_in_both_forms():
    measured = ComError(-2147352567, "Ausnahmefehler aufgetreten.", (0, None, None, None, 0, -2147024891), None)
    assert manager.access_denied(measured), "gemessen mit task create --startup ohne Adminrechte"
    assert manager.access_denied(ComError(-2147024891, "Zugriff verweigert", None, None))
    assert not manager.access_denied(ComError(-2147352567, "anderer Fehler", (0, None, None, None, 0, -1), None))
    assert not manager.access_denied(ValueError("kein COM-Fehler"))
