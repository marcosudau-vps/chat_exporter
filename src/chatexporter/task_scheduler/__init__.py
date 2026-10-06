"""Zeitplanung: ChatExporter-Befehle als Windows-Aufgaben automatisch ausfuehren.

Eigenstaendige Schicht neben dem Raw Session Updater und den Providern: sie
importiert nichts davon. Die Windows-Seite uebernimmt das Script
``tools/task_scheduler/scheduler_manager.py`` (PyTaskManager), das ``backend``
per Dateipfad laedt.

- ``config``   Abschnitt ``task_scheduler`` der gemeinsamen config.yaml
- ``backend``  laedt scheduler_manager.py
- ``service``  create / get / list / update / delete / pause / resume
- ``cli``      ``chatexporter task ...`` und ``chatexporter-task``
"""

from __future__ import annotations

from .config import TaskSchedulerConfig, TaskSetupError, load_config
from .service import TaskService, TaskServiceError

__all__ = ["TaskSchedulerConfig", "TaskService", "TaskServiceError", "TaskSetupError", "load_config"]
