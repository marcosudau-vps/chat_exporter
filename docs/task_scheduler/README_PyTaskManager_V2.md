# PyTaskManager V2

`PyTaskManager` ist eine verwaltete Schicht über dem Windows Task Scheduler. Die Windows-COM-API bleibt über `WindowsTaskScheduler` direkt zugänglich; die normale Modul-API verwaltet zusätzlich stabile IDs, Slugs, Owner und persistente State-Dateien.

## Installation

```powershell
py -m pip install pywin32
```

## Einfacher Python-Task

```python
import scheduler_manager as tasks

job = tasks.create_python_task(
    "Chat Export",
    r"P:\MeinProjekt\export.py",
    owner="chat-exporter",
    slug="nightly-export",
    trigger=tasks.daily("03:00"),
)

print(job.task_id)  # z. B. tsk_9b71d2af08b1
```

Danach kann der Task in einem späteren Programmlauf wieder über den lesbaren Slug angesprochen werden:

```python
tasks.run("nightly-export", owner="chat-exporter")
tasks.disable("nightly-export", owner="chat-exporter")
tasks.enable("nightly-export", owner="chat-exporter")
tasks.delete("nightly-export", owner="chat-exporter")
```

## Dict / JSON / Profile

```python
manager = tasks.manager(owner="chat-exporter", project_root=__file__)

manager.create({
    "name": "Export",
    "slug": "export",
    "script": r"P:\MeinProjekt\export.py",
    "trigger": {
        "type": "weekly",
        "at": "06:30",
        "days": ["mo", "mi", "fr"]
    }
})
```

Ein Profil liefert Defaults, die durch konkrete Werte überschrieben werden können:

```python
manager.create_python_task(
    "Export",
    r"P:\MeinProjekt\export.py",
    slug="export",
    profile=tasks.run_daily("06:00"),
)
```

Für fehlgeschlagene Tasks gibt es außerdem:

```python
profile=tasks.always_keep_running(
    restart_interval_minutes=2,
    restart_count=20,
)
```

Der Windows Task Scheduler startet dabei nur nach Fehlern neu; das Profil ist kein dauerhafter Service-Supervisor.

## Persistenz

Standardmäßig existieren zwei State-Ebenen:

- Local State: `<project_root>\tasks_sched.json`
- Global State: `%LOCALAPPDATA%\PyTaskManager\tasks_sched.json`

Der echte Windows-Task liegt standardmäßig in:

```text
\PyTaskManager\tsk_...
```

Der Anzeigename ist nicht die technische Identität. `task_id` bleibt beim Umbenennen erhalten.

Die Windows-Aufgabe trägt zusätzlich `RegistrationInfo.Source`, `URI` und JSON-Metadaten. Dadurch kann `reconcile(repair=True)` Registry-Einträge aus vorhandenen PyTaskManager-Aufgaben wiederherstellen.

## Reconcile

```python
result = tasks.reconcile(owner="chat-exporter")
print(result.as_dict())
```

Mögliche Zustände sind u. a. `healthy`, `missing`, `changed`, `orphaned`, `local_only`, `detached` und `conflicted`.

```python
result = tasks.reconcile(owner="chat-exporter", repair=True)
```

`repair=True` rekonstruiert bzw. synchronisiert Metadaten, löscht aber keine Tasks automatisch.

## Low-Level-Zugriff

Wenn keine Registry gewünscht ist:

```python
raw = tasks.WindowsTaskScheduler(r"\MeinOrdner")
raw.create_python_task(
    "Mein sichtbarer Windows-Name",
    r"P:\Scripts\job.py",
    trigger=tasks.daily("10:30"),
)
```

## Realtests

```powershell
py test_scheduler_manager.py
```

Die Tests erzeugen echte Windows Tasks in einem ausschließlich für Tests verwendeten Scheduler-Ordner, führen Python-Prozesse real aus und räumen anschließend wieder auf. Der Startup-/Boot-Trigger wird ohne Administratorrechte als `SKIP` gewertet.

Für den vollständigen Test inklusive Startup-Trigger PowerShell einmal als Administrator starten.
