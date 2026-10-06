from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import scheduler_manager as sm


TEST_FOLDER = r"\PythonTaskScheduler_AutoTestV2"
RUN_TIMEOUT_SECONDS = 20
STOP_TIMEOUT_SECONDS = 10


class TestFailure(RuntimeError):
    pass


class SkipTest(RuntimeError):
    pass


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise TestFailure(message)


def assert_equal(actual, expected, message: str) -> None:
    if actual != expected:
        raise TestFailure(f"{message}: erwartet={expected!r}, tatsächlich={actual!r}")


def wait_until(predicate, timeout: float, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def write_worker(path: Path) -> None:
    path.write_text(
        """from __future__ import annotations
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--marker')
parser.add_argument('--sleep', type=float, default=0)
parser.add_argument('--exit-code', type=int, default=0)
args = parser.parse_args()

if args.marker:
    marker = Path(args.marker)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(datetime.now().isoformat(), encoding='utf-8')

if args.sleep:
    time.sleep(args.sleep)

raise SystemExit(args.exit_code)
""",
        encoding="utf-8",
    )


def cleanup_test_folder(raw: sm.WindowsTaskScheduler) -> None:
    # This scheduler folder is exclusively reserved for this test suite.
    for item in raw.list_tasks(include_hidden=True):
        raw.delete_task(item.name, missing_ok=True)


def run_test(name: str, function, results: list[tuple[str, str, str]]) -> None:
    try:
        function()
    except SkipTest as exc:
        results.append((name, "SKIP", str(exc)))
        print(f"[SKIP] {name}: {exc}")
    except Exception as exc:
        results.append((name, "FAIL", str(exc)))
        print(f"[FAIL] {name}: {exc}")
    else:
        results.append((name, "PASS", ""))
        print(f"[PASS] {name}")


def trigger_of(raw: sm.WindowsTaskScheduler, name: str, index: int = 1):
    return raw.get_task(name).Definition.Triggers.Item(index)


def wait_finished(raw: sm.WindowsTaskScheduler, name: str, timeout: float = RUN_TIMEOUT_SECONDS) -> bool:
    return wait_until(lambda: raw.get_task_info(name).state != "running", timeout)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    if os.name != "nt":
        print("Dieses Testskript muss unter Windows ausgeführt werden.")
        return 2

    prefix = f"AUTO_{uuid.uuid4().hex[:8]}_"
    temp_dir = Path(tempfile.mkdtemp(prefix="task_scheduler_v2_test_"))
    project_root = temp_dir / "project"
    project_root.mkdir(parents=True)
    worker = temp_dir / "worker.py"
    write_worker(worker)

    global_state = temp_dir / "global" / "tasks_sched.json"
    local_state = project_root / "tasks_sched.json"
    owner = f"auto-{uuid.uuid4().hex[:8]}"

    results: list[tuple[str, str, str]] = []
    raw = sm.WindowsTaskScheduler(TEST_FOLDER)
    managed = sm.PyTaskManager(
        owner=owner,
        project_root=project_root,
        local_state_file=local_state,
        global_state_file=global_state,
        folder=TEST_FOLDER,
    )

    names = {
        "manual": prefix + "manual",
        "long": prefix + "long",
        "once": prefix + "once",
        "daily": prefix + "daily",
        "weekly": prefix + "weekly",
        "logon": prefix + "logon",
        "startup": prefix + "startup",
        "settings": prefix + "settings",
    }

    try:
        cleanup_test_folder(raw)

        # ------------------------------------------------------------------
        # Low-level Windows integration tests
        # ------------------------------------------------------------------
        def test_raw_create() -> None:
            marker = temp_dir / "raw_marker.txt"
            info = raw.create_python_task(
                names["manual"],
                worker,
                arguments=["--marker", str(marker)],
                description="V2 raw integration test",
            )
            assert_equal(info.name, names["manual"], "Falscher Scheduler-Name")
            assert_equal(info.action_count, 1, "Exec-Action fehlt")
            assert_true(raw.task_exists(names["manual"]), "task_exists() liefert False")

        run_test("RAW: Task anlegen + lesen", test_raw_create, results)

        def test_raw_execution_and_result() -> None:
            marker = temp_dir / "raw_marker.txt"
            marker.unlink(missing_ok=True)
            raw.run_task(names["manual"])
            assert_true(wait_until(marker.exists, RUN_TIMEOUT_SECONDS), "Markerdatei wurde nicht erzeugt")
            assert_true(wait_finished(raw, names["manual"]), "Task wurde nicht beendet")
            info = raw.get_task_info(names["manual"])
            assert_equal(info.last_result, 0, "Windows meldet keinen Exitcode 0")

        run_test("RAW: echte Ausführung + Exitcode", test_raw_execution_and_result, results)

        def test_raw_stop() -> None:
            raw.create_python_task(names["long"], worker, arguments=["--sleep", "60"])
            raw.run_task(names["long"])
            assert_true(
                wait_until(lambda: raw.get_task_info(names["long"]).state == "running", STOP_TIMEOUT_SECONDS),
                "Langläufer erreichte nicht 'running'",
            )
            raw.stop_task(names["long"])
            assert_true(
                wait_until(lambda: raw.get_task_info(names["long"]).state != "running", STOP_TIMEOUT_SECONDS),
                "Task wurde nicht gestoppt",
            )

        run_test("RAW: laufenden Task stoppen", test_raw_stop, results)

        def test_once_details() -> None:
            target = datetime.now().replace(microsecond=0) + timedelta(days=1, minutes=7)
            raw.create_python_task(names["once"], worker, trigger=sm.once(target))
            trigger = trigger_of(raw, names["once"])
            assert_equal(int(trigger.Type), sm.TASK_TRIGGER_TIME, "Falscher Once-Typ")
            assert_equal(str(trigger.StartBoundary), target.isoformat(timespec="seconds"), "Once StartBoundary falsch")

        run_test("RAW: Once-Trigger exakt validieren", test_once_details, results)

        def test_daily_details() -> None:
            raw.create_python_task(names["daily"], worker, trigger=sm.daily("10:30", every=2))
            trigger = trigger_of(raw, names["daily"])
            assert_equal(int(trigger.Type), sm.TASK_TRIGGER_DAILY, "Falscher Daily-Typ")
            assert_true(str(trigger.StartBoundary).endswith("T10:30:00"), "Daily Uhrzeit falsch")
            assert_equal(int(trigger.DaysInterval), 2, "DaysInterval falsch")
            assert_true(bool(trigger.Enabled), "Daily Trigger nicht aktiviert")

        run_test("RAW: Daily-Trigger exakt validieren", test_daily_details, results)

        def test_weekly_details() -> None:
            raw.create_python_task(
                names["weekly"],
                worker,
                trigger=sm.weekly("11:15", ["mo", "mi", "fr"], every=2),
            )
            trigger = trigger_of(raw, names["weekly"])
            expected_days = sm.WEEKDAY_BITS["mo"] | sm.WEEKDAY_BITS["mi"] | sm.WEEKDAY_BITS["fr"]
            assert_equal(int(trigger.Type), sm.TASK_TRIGGER_WEEKLY, "Falscher Weekly-Typ")
            assert_true(str(trigger.StartBoundary).endswith("T11:15:00"), "Weekly Uhrzeit falsch")
            assert_equal(int(trigger.WeeksInterval), 2, "WeeksInterval falsch")
            assert_equal(int(trigger.DaysOfWeek), expected_days, "DaysOfWeek falsch")

        run_test("RAW: Weekly-Trigger exakt validieren", test_weekly_details, results)

        def test_logon_details() -> None:
            spec = sm.logon(delay_seconds=5)
            raw.create_python_task(names["logon"], worker, trigger=spec)
            trigger = trigger_of(raw, names["logon"])
            assert_equal(int(trigger.Type), sm.TASK_TRIGGER_LOGON, "Falscher Logon-Typ")
            assert_equal(str(trigger.UserId).lower(), str(spec.user_id).lower(), "Logon UserId falsch")
            assert_equal(str(trigger.Delay), "PT5S", "Logon Delay falsch")

        run_test("RAW: Logon-Trigger für aktuellen Benutzer", test_logon_details, results)

        def test_startup_details() -> None:
            if not is_admin():
                raise SkipTest("Startup-/Boot-Trigger erfordert eine als Administrator gestartete Konsole.")
            raw.create_python_task(names["startup"], worker, trigger=sm.startup(delay_seconds=5))
            trigger = trigger_of(raw, names["startup"])
            assert_equal(int(trigger.Type), sm.TASK_TRIGGER_BOOT, "Falscher Startup-Typ")
            assert_equal(str(trigger.Delay), "PT5S", "Startup Delay falsch")

        run_test("RAW: Startup-Trigger exakt validieren", test_startup_details, results)

        def test_settings_details() -> None:
            raw.create_python_task(
                names["settings"],
                worker,
                hidden=True,
                start_when_available=False,
                allow_on_battery=False,
                wake_to_run=True,
                multiple_instances="queue",
                max_runtime_minutes=17,
                restart_interval_minutes=2,
                restart_count=3,
            )
            settings = raw.get_task(names["settings"]).Definition.Settings
            assert_true(bool(settings.Hidden), "Hidden falsch")
            assert_true(not bool(settings.StartWhenAvailable), "StartWhenAvailable falsch")
            assert_true(bool(settings.DisallowStartIfOnBatteries), "Battery-Setting falsch")
            assert_true(bool(settings.WakeToRun), "WakeToRun falsch")
            assert_equal(int(settings.MultipleInstances), sm.TASK_INSTANCES_QUEUE, "MultipleInstances falsch")
            assert_equal(str(settings.ExecutionTimeLimit), "PT17M", "ExecutionTimeLimit falsch")
            assert_equal(int(settings.RestartCount), 3, "RestartCount falsch")
            assert_equal(str(settings.RestartInterval), "PT2M", "RestartInterval falsch")

        run_test("RAW: TaskSettings exakt validieren", test_settings_details, results)

        # ------------------------------------------------------------------
        # Managed layer / persistent identity tests
        # ------------------------------------------------------------------
        managed_holder: dict[str, sm.ManagedTaskInfo] = {}

        def test_managed_create_and_state() -> None:
            info = managed.create_python_task(
                "Managed Marker",
                worker,
                slug="managed-marker",
                arguments=["--marker", str(temp_dir / "managed_marker.txt")],
                trigger=sm.daily("12:10"),
                description="Managed persistence test",
            )
            managed_holder["main"] = info
            assert_true(info.task_id.startswith("tsk_"), "Keine stabile tsk_-ID erzeugt")
            assert_equal(info.slug, "managed-marker", "Slug falsch")
            assert_equal(info.owner, owner, "Owner falsch")
            assert_true(raw.task_exists(info.task_id), "Windows Task mit task_id fehlt")
            assert_true(not raw.task_exists("Managed Marker"), "Anzeigename wurde fälschlich als Scheduler-Name verwendet")

            assert_true(global_state.exists(), "Global State wurde nicht angelegt")
            assert_true(local_state.exists(), "Local State wurde nicht angelegt")
            global_data = load_json(global_state)
            local_data = load_json(local_state)
            assert_true(info.task_id in global_data["tasks"], "Task fehlt im Global State")
            assert_true(info.task_id in local_data["tasks"], "Task fehlt im Local State")

            registration = raw.get_registration_metadata(info.task_id)
            assert_equal(registration["source"], sm.MANAGER_SOURCE, "RegistrationInfo.Source falsch")
            assert_true(registration["uri"].endswith(info.task_id), "RegistrationInfo.URI enthält task_id nicht")
            meta = registration["metadata"]
            assert_equal(meta["task_id"], info.task_id, "Windows-Metadaten task_id falsch")
            assert_equal(meta["slug"], "managed-marker", "Windows-Metadaten slug falsch")

        run_test("MANAGED: ID + Local/Global State + Windows-Metadaten", test_managed_create_and_state, results)

        def test_followup_process_resolution_and_run() -> None:
            info = managed_holder["main"]
            marker = temp_dir / "managed_marker.txt"
            marker.unlink(missing_ok=True)

            child_code = f"""
import scheduler_manager as sm
m = sm.PyTaskManager(
    owner={owner!r},
    project_root={str(project_root)!r},
    local_state_file={str(local_state)!r},
    global_state_file={str(global_state)!r},
    folder={TEST_FOLDER!r},
)
assert m.exists('managed-marker')
info = m.get('managed-marker')
print(info.task_id)
m.run('managed-marker')
"""
            completed = subprocess.run(
                [sys.executable, "-c", child_code],
                cwd=str(Path(__file__).resolve().parent),
                capture_output=True,
                text=True,
                timeout=RUN_TIMEOUT_SECONDS,
            )
            assert_equal(completed.returncode, 0, f"Separater Folgelauf fehlgeschlagen: {completed.stderr.strip()}")
            assert_true(info.task_id in completed.stdout, "Folgelauf löst andere ID auf")
            assert_true(wait_until(marker.exists, RUN_TIMEOUT_SECONDS), "Folgelauf konnte Task nicht starten")
            assert_true(
                wait_until(lambda: managed.get("managed-marker").state != "running", RUN_TIMEOUT_SECONDS),
                "Managed Task beendet sich nicht",
            )
            assert_equal(managed.get("managed-marker").last_result, 0, "Managed Task Exitcode ist nicht 0")

        run_test("MANAGED: neuer Python-Prozess erkennt + startet Task", test_followup_process_resolution_and_run, results)

        def test_update_reuses_identity() -> None:
            original = managed_holder["main"]
            updated = managed.create_python_task(
                "Managed Marker umbenannt",
                worker,
                slug="managed-marker",
                trigger=sm.weekly("13:20", ["di", "do"]),
            )
            assert_equal(updated.task_id, original.task_id, "Update hat neue task_id erzeugt")
            assert_equal(updated.name, "Managed Marker umbenannt", "Anzeigename wurde nicht aktualisiert")
            assert_equal(raw.get_task_info(updated.task_id).trigger_types, ["weekly"], "Trigger wurde nicht ersetzt")
            assert_equal(load_json(global_state)["tasks"][updated.task_id]["name"], "Managed Marker umbenannt", "Global State nicht aktualisiert")
            assert_equal(load_json(local_state)["tasks"][updated.task_id]["name"], "Managed Marker umbenannt", "Local State nicht aktualisiert")

        run_test("MANAGED: Update behält stabile Identität", test_update_reuses_identity, results)

        dict_holder: dict[str, sm.ManagedTaskInfo] = {}

        def test_dict_input_and_profile() -> None:
            info = managed.create(
                {
                    "name": "Dict Task",
                    "slug": "dict-task",
                    "script": str(worker),
                    "settings": {"hidden": True},
                },
                profile=sm.run_daily("14:25", every=3),
            )
            dict_holder["dict"] = info
            trigger = trigger_of(raw, info.task_id)
            assert_equal(int(trigger.Type), sm.TASK_TRIGGER_DAILY, "Profil wurde nicht in Daily übersetzt")
            assert_equal(int(trigger.DaysInterval), 3, "Profil every falsch")
            assert_true(bool(raw.get_task(info.task_id).Definition.Settings.Hidden), "Dict-Setting hidden nicht übernommen")

        run_test("RESOLVER: Dict + Profile", test_dict_input_and_profile, results)

        json_holder: dict[str, sm.ManagedTaskInfo] = {}

        def test_json_input() -> None:
            payload = json.dumps(
                {
                    "name": "JSON Task",
                    "slug": "json-task",
                    "script": str(worker),
                    "trigger": {"type": "weekly", "at": "15:35", "days": ["mo", "fr"], "every": 2},
                }
            )
            info = managed.create(payload)
            json_holder["json"] = info
            trigger = trigger_of(raw, info.task_id)
            assert_equal(int(trigger.Type), sm.TASK_TRIGGER_WEEKLY, "JSON Trigger-Typ falsch")
            assert_equal(int(trigger.WeeksInterval), 2, "JSON weeks interval falsch")
            expected = sm.WEEKDAY_BITS["mo"] | sm.WEEKDAY_BITS["fr"]
            assert_equal(int(trigger.DaysOfWeek), expected, "JSON Wochentage falsch")

        run_test("RESOLVER: JSON -> NormalizedTaskSpec -> Scheduler", test_json_input, results)

        keep_holder: dict[str, sm.ManagedTaskInfo] = {}

        def test_keep_running_profile() -> None:
            info = managed.create_python_task(
                "Keep Running",
                worker,
                slug="keep-running",
                profile=sm.always_keep_running(restart_interval_minutes=2, restart_count=4),
            )
            keep_holder["keep"] = info
            settings = raw.get_task(info.task_id).Definition.Settings
            assert_equal(int(settings.RestartCount), 4, "always_keep_running RestartCount falsch")
            assert_equal(str(settings.RestartInterval), "PT2M", "always_keep_running RestartInterval falsch")
            assert_equal(int(settings.MultipleInstances), sm.TASK_INSTANCES_IGNORE_NEW, "Profil MultipleInstances falsch")

        run_test("PROFILE: always_keep_running", test_keep_running_profile, results)

        def test_reconcile_healthy_and_changed() -> None:
            task_id = managed_holder["main"].task_id
            first = managed.reconcile()
            assert_true(task_id in first.healthy, "Unveränderter Task wird nicht als healthy erkannt")

            # Deliberately mutate Windows outside the managed layer.
            raw.disable_task(task_id)
            changed = managed.reconcile()
            assert_true(task_id in changed.changed, "Externe Änderung wurde nicht erkannt")

            repaired = managed.reconcile(repair=True)
            assert_true(task_id in repaired.repaired, "Fingerprint wurde nicht repariert")
            after = managed.reconcile()
            assert_true(task_id in after.healthy, "Task ist nach Repair nicht healthy")

            # Managed operation also refreshes the fingerprint itself.
            managed.enable(task_id)
            after_enable = managed.reconcile()
            assert_true(task_id in after_enable.healthy, "Managed enable erzeugt falschen changed-Status")

        run_test("RECONCILE: healthy + externe Änderung + Repair", test_reconcile_healthy_and_changed, results)

        def test_reconcile_recovers_lost_global_entry() -> None:
            task_id = dict_holder["dict"].task_id
            data = load_json(global_state)
            removed = data["tasks"].pop(task_id)
            global_state.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            assert_true(task_id in load_json(local_state)["tasks"], "Testvoraussetzung Local State fehlt")

            scan = managed.reconcile()
            assert_true(task_id in scan.orphaned, "Windows-Orphan wurde nicht erkannt")
            assert_true(task_id in scan.local_only, "Local-only Zustand wurde nicht erkannt")

            repaired = managed.reconcile(repair=True)
            assert_true(task_id in repaired.repaired, "Orphan wurde nicht repariert")
            assert_true(task_id in load_json(global_state)["tasks"], "Global State wurde nicht rekonstruiert")
            recovered = load_json(global_state)["tasks"][task_id]
            assert_equal(recovered["slug"], removed["slug"], "Rekonstruierter Slug stimmt nicht")

        run_test("RECONCILE: verlorenen Global State aus Windows rekonstruieren", test_reconcile_recovers_lost_global_entry, results)

        def test_module_facade() -> None:
            marker = temp_dir / "facade_marker.txt"
            kwargs = {
                "owner": owner,
                "project_root": project_root,
                "local_state_file": local_state,
                "global_state_file": global_state,
                "folder": TEST_FOLDER,
            }
            info = sm.create_python_task(
                "Facade Task",
                worker,
                slug="facade-task",
                arguments=["--marker", str(marker)],
                **kwargs,
            )
            assert_true(sm.task_exists("facade-task", **kwargs), "Facade task_exists fehlgeschlagen")
            sm.run_task("facade-task", **kwargs)
            assert_true(wait_until(marker.exists, RUN_TIMEOUT_SECONDS), "Facade run_task führte Task nicht aus")
            sm.disable_task("facade-task", **kwargs)
            assert_true(not sm.get_task_info("facade-task", **kwargs).enabled, "Facade disable fehlgeschlagen")
            sm.enable_task("facade-task", **kwargs)
            assert_true(sm.get_task_info("facade-task", **kwargs).enabled, "Facade enable fehlgeschlagen")
            assert_true(sm.delete_task("facade-task", **kwargs), "Facade delete fehlgeschlagen")
            assert_true(not raw.task_exists(info.task_id), "Facade Task blieb im Scheduler zurück")

        run_test("FACADE: einfache Modul-API persistent", test_module_facade, results)

        def test_delete_persistent_by_slug() -> None:
            task_id = managed_holder["main"].task_id
            assert_true(managed.delete("managed-marker"), "delete(slug) meldete False")
            assert_true(not raw.task_exists(task_id), "Windows Task blieb nach delete bestehen")
            assert_true(task_id not in load_json(global_state)["tasks"], "Global State blieb nach delete bestehen")
            assert_true(task_id not in load_json(local_state)["tasks"], "Local State blieb nach delete bestehen")
            assert_true(not managed.exists("managed-marker"), "exists(slug) ist nach delete True")
            assert_true(managed.delete("managed-marker", missing_ok=True) is False, "missing_ok sollte False liefern")

        run_test("MANAGED: per Slug löschen + beide States bereinigen", test_delete_persistent_by_slug, results)

        def test_delete_all_local() -> None:
            # Existing dict/json/keep tasks are all local to this test project.
            before = len(managed.registry.local_task_ids())
            assert_true(before >= 3, "Zu wenige lokale Tasks für delete_all_local Test")
            deleted = managed.delete_all_local()
            assert_equal(deleted, before, "delete_all_local Anzahl falsch")
            assert_equal(managed.registry.local_task_ids(), [], "Local State ist nicht leer")
            remaining_owner = [item for item in managed.list(owner=owner) if item.exists]
            assert_equal(remaining_owner, [], "Es blieben verwaltete Owner-Tasks im Scheduler")

        run_test("MANAGED: delete_all_local", test_delete_all_local, results)

        def test_state_backup_and_json_validity() -> None:
            # At this point state files have been rewritten multiple times, so backups should exist.
            assert_true(global_state.exists(), "Global State fehlt")
            assert_true(local_state.exists(), "Local State fehlt")
            assert_true(global_state.with_suffix(global_state.suffix + ".bak").exists(), "Global Backup fehlt")
            assert_true(local_state.with_suffix(local_state.suffix + ".bak").exists(), "Local Backup fehlt")
            assert_equal(load_json(global_state)["schema_version"], sm.STATE_SCHEMA_VERSION, "Global schema_version falsch")
            assert_equal(load_json(local_state)["schema_version"], sm.STATE_SCHEMA_VERSION, "Local schema_version falsch")

        run_test("STATE: atomare JSON-Dateien + Backups", test_state_backup_and_json_validity, results)

    finally:
        try:
            cleanup_test_folder(raw)
        except Exception as exc:
            print(f"[WARN] Task-Cleanup fehlgeschlagen: {exc}")

        try:
            if not raw.list_tasks(include_hidden=True):
                raw.delete_folder(TEST_FOLDER)
        except Exception as exc:
            print(f"[WARN] Testordner konnte nicht entfernt werden: {exc}")

        shutil.rmtree(temp_dir, ignore_errors=True)

    passed = sum(status == "PASS" for _, status, _ in results)
    failed = sum(status == "FAIL" for _, status, _ in results)
    skipped = sum(status == "SKIP" for _, status, _ in results)

    print("\n" + "=" * 76)
    print(f"Ergebnis: {passed} PASS | {failed} FAIL | {skipped} SKIP")
    print("=" * 76)

    if failed:
        print("\nFehlgeschlagene Tests:")
        for name, status, detail in results:
            if status == "FAIL":
                print(f" - {name}: {detail}")
        return 1

    if skipped:
        print("\nHinweis: Für den vollständigen Startup-Test PowerShell/Terminal")
        print("einmal als Administrator starten und das Skript erneut ausführen.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
