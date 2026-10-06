"""Deinstallation: ``chatexporter uninstall [--yes] [--silent]``.

- Installiertes Programm: startet die Deinstallation des Installers
  (``unins000.exe`` im Programmordner). Sie entfernt alle eigenen
  Windows-Aufgaben, den Programmordner, den Startmenue-Eintrag und den
  Registry-Schluessel ``HKCU\\Software\\ChatExporter``.
- Start aus dem Quellcode: entfernt die Windows-Aufgaben aller bekannten
  Storages und den Registry-Schluessel; das Python-Paket selbst entfernt
  ``pip uninstall chatexporter-gen4``.
- ``--remove-tasks``: nur die Aufgaben aller bekannten Storages entfernen
  (so ruft der Installer den Befehl bei der Deinstallation auf).

Konfiguration, ``.env``, Daten und Protokolle (``~/.chatexporter`` bzw. der
konfigurierte Datenordner) werden **nie** geloescht.

Optionen: ``--yes`` ohne Rueckfrage; ``--silent`` Deinstallation ohne Fenster
(nur installiertes Programm).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

Say = Callable[[str], None]
Ask = Callable[[str], str]

REGISTRY_ROOT = r"Software\ChatExporter"
SILENT_ARGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")


def find_uninstaller(program_dir: Path) -> Path | None:
    found = sorted(program_dir.glob("unins*.exe"))
    return found[-1] if found else None


def delete_registry_tree(path: str = REGISTRY_ROOT) -> bool:
    """Loescht ``HKCU\\<path>`` samt Unterschluesseln. Rueckgabe: war vorhanden."""
    if sys.platform != "win32":
        return False
    import winreg

    def remove(key_path: str) -> None:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                remove(f"{key_path}\\{child}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)

    try:
        remove(path)
    except FileNotFoundError:
        return False
    return True


def _launch_detached(command: list[str]) -> None:
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(command, close_fds=True, creationflags=flags)


def _confirm(ask: Ask, prompt: str) -> bool:
    try:
        return ask(prompt).strip().lower() in ("j", "ja", "y", "yes")
    except EOFError:
        return False


def _data_hint(config: Path | None, say: Say) -> None:
    try:
        import chatexporter.config as shared_config
        loaded = shared_config.load(config)
        say(f"Erhalten bleiben: {loaded.config_file.parent} (Konfiguration, .env, Protokolle) und "
            f"{shared_config.resolve_path(loaded, loaded.get('storage.data_root'))} (Daten).")
    except Exception:  # noqa: BLE001  nur ein Hinweis
        say("Konfiguration, .env, Daten und Protokolle bleiben erhalten.")


def known_storages(config: Path | None) -> list[Path]:
    """Gewaehlter Storage und alle, die in der Registry vermerkt sind (``Storages\\<id>\\Path``)."""
    import chatexporter.config as shared_config
    roots: list[Path] = []
    try:
        roots.append(shared_config.storage_of(shared_config.load(config)).root)
    except Exception:  # noqa: BLE001
        pass
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, shared_config.REGISTRY_STORAGES_KEY) as key:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(key, name) as sub:
                            roots.append(Path(winreg.QueryValueEx(sub, "Path")[0]))
                    except OSError:
                        continue
        except OSError:
            pass
    out: list[Path] = []
    for root in roots:
        if root not in out:
            out.append(root)
    return out


def remove_all_tasks(config: Path | None, say: Say, service_factory: Callable[[Any], Any] | None = None) -> bool:
    """Aufgaben aller bekannten Storages entfernen. Rueckgabe: alles ok."""
    import chatexporter.config as shared_config
    from chatexporter.task_scheduler.config import TaskSetupError, load_config
    from chatexporter.task_scheduler.service import TaskService, TaskServiceError
    ok = True
    for root in known_storages(config):
        if shared_config.storage.detect(root)[0] != shared_config.storage.FORMAT_CURRENT:
            continue
        try:
            with shared_config.overrides([*shared_config.cli_overrides(), f"storage.root={root}"]):
                removed = (service_factory or TaskService)(load_config(config)).delete_all()
            say(f"Aufgaben von {root}: {', '.join(v['slug'] for v in removed) or 'keine'}")
        except (TaskSetupError, TaskServiceError) as exc:
            say(f"Aufgaben von {root} nicht entfernt: {exc}")
            ok = False
    return ok


def run_uninstall(argv: list[str], config: Path | None, *, say: Say = print, ask: Ask = input,
                  frozen: bool | None = None, program_dir: Path | None = None,
                  launch: Callable[[list[str]], None] = _launch_detached,
                  service_factory: Callable[[Any], Any] | None = None,
                  delete_registry: Callable[[], bool] = delete_registry_tree) -> int:
    if any(a in ("-h", "--help") for a in argv):
        say(__doc__.strip())
        return 0
    unknown = [a for a in argv if a not in ("--yes", "-y", "--silent", "--remove-tasks")]
    if unknown:
        say(f"Unbekannte Option: {' '.join(unknown)}")
        return 2
    yes = "--yes" in argv or "-y" in argv
    silent = "--silent" in argv
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if "--remove-tasks" in argv:
        # Vom Installer bei der Deinstallation aufgerufen: nur die Aufgaben aller Storages.
        return 0 if remove_all_tasks(config, say, service_factory) else 1

    if frozen:
        program_dir = program_dir or Path(sys.executable).parent
        uninstaller = find_uninstaller(program_dir)
        if uninstaller is None:
            say(f"Keine Deinstallation gefunden in {program_dir} (nicht ueber den Installer installiert?).")
            return 2
        # Ohne --silent fragt die Deinstallation selbst nach.
        if silent and not yes and not _confirm(ask, "ChatExporter jetzt deinstallieren? [j/N] "):
            say("Abgebrochen.")
            return 1
        _data_hint(config, say)
        launch([str(uninstaller), *(SILENT_ARGS if silent else ())])
        say(f"Deinstallation gestartet ({uninstaller.name}); dieses Fenster kann geschlossen werden.")
        return 0

    if not yes and not _confirm(ask, "Alle eigenen Windows-Aufgaben und den Registry-Schluessel "
                                     "HKCU\\Software\\ChatExporter entfernen? [j/N] "):
        say("Abgebrochen.")
        return 1
    code = 0 if remove_all_tasks(config, say, service_factory) else 1
    say("Registry-Schluessel entfernt." if delete_registry() else "Registry-Schluessel war nicht vorhanden.")
    _data_hint(config, say)
    say("Das Python-Paket entfernt: pip uninstall chatexporter-gen4")
    return code
