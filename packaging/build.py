"""Gebautes Programm und (falls Inno Setup vorhanden) Installer erzeugen.

    python packaging\\build.py                 # Programm + Installer
    python packaging\\build.py --no-installer  # nur Programm
    python packaging\\build.py --out D:\\build  # anderer Zielordner

Standard-Zielordner: ``<workspace>/_build/<version>/`` (ausserhalb des
Codeordners; NICHT ``product/``). Darin:

- ``dist/ChatExporter/``     gebautes Programm (``chatexporter.exe`` + ``_internal/``)
- ``installer/``             ``ChatExporter-Setup-<version>.exe`` (Inno Setup)
- ``build_report.json``      Version, Groesse, Pruefsummen, Smoke-Test

Nach dem Bau laeuft ein Smoke-Test des Programms mit einem leeren Home-Ordner
(kein Netz): Hilfe-/Info-Befehle und ein echter Aufgaben-Durchlauf (anlegen
pausiert, anzeigen, loeschen) in einem eigenen Ordner ``ChatExporterBuildTest``
der Windows-Aufgabenplanung, der danach wieder entfernt wird (``--no-task-test``
schaltet das ab).
Voraussetzung: PyInstaller in der Python-Umgebung (``pip install pyinstaller``),
fuer den Installer Inno Setup 6 (``ISCC.exe``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from chatexporter import __version__  # noqa: E402

ISCC_CANDIDATES = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
]


def find_iscc() -> Path | None:
    found = shutil.which("ISCC.exe") or shutil.which("iscc")
    if found:
        return Path(found)
    return next((p for p in ISCC_CANDIDATES if p.is_file()), None)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def build_program(out: Path) -> Path:
    from make_icon import make_icon

    make_icon(ROOT / "assets" / "IconChatExporter.png", ROOT / "assets" / "IconChatExporter.ico")
    work = out / "work"
    dist = out / "dist"
    if (dist / "ChatExporter").exists():
        shutil.rmtree(dist / "ChatExporter")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--workpath", str(work), "--distpath", str(dist), str(ROOT / "packaging" / "chatexporter.spec")]
    print("> " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)
    exe = dist / "ChatExporter" / "chatexporter.exe"
    if not exe.is_file():
        raise SystemExit(f"Build ohne Ergebnis: {exe} fehlt")
    return exe


TEST_FOLDER = "\\ChatExporterBuildTest"


def _remove_test_folder() -> None:
    """Leeren Testordner der Aufgabenplanung entfernen (best effort)."""
    try:
        import win32com.client
        service = win32com.client.Dispatch("Schedule.Service")
        service.Connect()
        service.GetFolder("\\").DeleteFolder(TEST_FOLDER.strip("\\"), 0)
    except Exception as exc:  # noqa: BLE001
        print(f"  Hinweis: Testordner {TEST_FOLDER} nicht entfernt ({exc})")


def smoke_test(exe: Path, *, task_test: bool = True) -> list[dict]:
    """Programm in einem leeren Home starten (kein Netz, keine echten Daten)."""
    results = []
    with tempfile.TemporaryDirectory(prefix="chatexporter_smoke_") as home:
        env = {**os.environ, "CHATEXPORTER_HOME": home, "CHATEXPORTER_REGISTRY_MIRROR": "off",
               "PYTHONIOENCODING": "utf-8"}
        env.pop("CHATEXPORTER_CONFIG", None)
        checks = [(["--version"], __version__), (["--help"], "Einrichtung"),
                  (["config", "path"], home), (["task", "-h"], "create"),
                  (["chatgpt", "-h"], "browser-setup"), (["setup", "-h"], "Ersteinrichtung"),
                  (["uninstall", "-h"], "Deinstallation"), (["storage", "show"], "storage-schema-2")]
        if task_test:
            scope = ["--folder", TEST_FOLDER, "--owner", "buildtest"]
            checks += [(["task", "create", "Buildtest", "--paused", "--once", "2099-01-01 00:00",
                         "--command", "status", *scope], "Aufgabe angelegt"),
                       (["task", "get", "buildtest", *scope], "buildtest"),
                       (["task", "delete", "buildtest", "--yes", *scope], "geloescht")]
        for args, expect in checks:
            proc = subprocess.run([str(exe), *args], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", env=env, timeout=120, cwd=home)
            output = proc.stdout + proc.stderr
            ok = proc.returncode == 0 and expect in output
            results.append({"args": args, "exit": proc.returncode, "ok": ok,
                            "tail": output.strip().splitlines()[-3:] if not ok else []})
            print(f"  {'ok ' if ok else 'FEHLER'} chatexporter {' '.join(args)} (Exitcode {proc.returncode})")
        if task_test:
            _remove_test_folder()
        created = Path(home) / "config.yaml"
        results.append({"args": ["<config.yaml angelegt>"], "ok": created.is_file()})
        print(f"  {'ok ' if created.is_file() else 'FEHLER'} config.yaml im leeren Home angelegt")
    return results


def build_installer(iscc: Path, out: Path, program: Path) -> Path:
    target = out / "installer"
    target.mkdir(parents=True, exist_ok=True)
    cmd = [str(iscc), f"/DAppVersion={__version__}", f"/DSourceDir={program}", f"/O{target}",
           str(ROOT / "packaging" / "installer" / "chatexporter.iss")]
    print("> " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=ROOT)
    found = sorted(target.glob("ChatExporter-Setup-*.exe"))
    if not found:
        raise SystemExit("Installer wurde nicht erzeugt")
    return found[-1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ChatExporter bauen")
    parser.add_argument("--out", type=Path, default=ROOT.parent / "_build" / __version__)
    parser.add_argument("--no-installer", action="store_true")
    parser.add_argument("--skip-build", action="store_true", help="vorhandenes Programm nur testen/verpacken")
    parser.add_argument("--no-task-test", action="store_true",
                        help="Smoke-Test ohne Aufgaben-Durchlauf in der Windows-Aufgabenplanung")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"version": __version__, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "python": sys.version.split()[0]}
    exe = out / "dist" / "ChatExporter" / "chatexporter.exe" if args.skip_build else build_program(out)
    program = exe.parent
    report["program"] = {"path": str(program), "size_mb": round(folder_size(program) / 1e6, 1),
                         "exe_sha256": sha256(exe)}
    print("\nSmoke-Test:")
    report["smoke_test"] = smoke_test(exe, task_test=not args.no_task_test)
    ok = all(r["ok"] for r in report["smoke_test"])
    if not args.no_installer:
        iscc = find_iscc()
        if iscc is None:
            report["installer"] = {"skipped": "Inno Setup 6 (ISCC.exe) nicht gefunden"}
            print("\nInstaller uebersprungen: Inno Setup 6 (ISCC.exe) nicht gefunden.")
        elif ok:
            setup = build_installer(iscc, out, program)
            report["installer"] = {"path": str(setup), "size_mb": round(setup.stat().st_size / 1e6, 1),
                                   "sha256": sha256(setup)}
    (out / "build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nBericht: {out / 'build_report.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
