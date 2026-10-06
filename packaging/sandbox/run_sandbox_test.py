"""Komplett-Test eines Installationsprogramms auf frischem Windows (Windows Sandbox).

Legt einen Arbeitsordner mit ``in/`` (Installer + ``sandbox_test.ps1``, nur lesbar) und
``out/`` (Ergebnisse) an, schreibt die Sandbox-Konfiguration, startet die Sandbox und wartet,
bis ``out/done.txt`` erscheint. Die Sandbox faehrt am Ende selbst herunter.

Voraussetzungen: Windows-Feature „Windows-Sandbox“; keine andere Sandbox geoeffnet (Windows
erlaubt nur eine). Netzwerk ist an (Download von Chrome for Testing wird mitgeprueft).

Beispiel:
    python packaging\\sandbox\\run_sandbox_test.py --installer ..\\_build\\0.0.1rc1\\installer\\ChatExporter-Setup-0.0.1rc1.exe

Exitcode 0, wenn keine Pruefung ``FEHLER`` meldet; 1 sonst; 2 bei Vorbedingungsfehlern.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "sandbox_test.ps1"

WSB = """<Configuration>
  <MappedFolders>
    <MappedFolder><HostFolder>{inp}</HostFolder><SandboxFolder>C:\\Test\\in</SandboxFolder><ReadOnly>true</ReadOnly></MappedFolder>
    <MappedFolder><HostFolder>{out}</HostFolder><SandboxFolder>C:\\Test\\out</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <Networking>Enable</Networking>
  <LogonCommand><Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\Test\\in\\sandbox_test.ps1</Command></LogonCommand>
</Configuration>
"""


def sandbox_running() -> bool:
    result = subprocess.run(["tasklist"], capture_output=True, text=True, errors="replace")
    return "windowssandbox" in result.stdout.lower()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=None, help="Arbeitsordner (Standard: neuer Temp-Ordner)")
    parser.add_argument("--timeout-minutes", type=int, default=30)
    args = parser.parse_args(argv)
    installer = args.installer.expanduser().resolve()
    if not installer.is_file():
        print(f"Installationsprogramm nicht gefunden: {installer}")
        return 2
    if sandbox_running():
        print("Es laeuft bereits eine Windows Sandbox – bitte zuerst schliessen.")
        return 2
    work = (args.work.expanduser().resolve() if args.work
            else Path(tempfile.mkdtemp(prefix="chatexporter_sandbox_")))
    inp, out = work / "in", work / "out"
    shutil.rmtree(out, ignore_errors=True)
    inp.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True)
    for old in inp.glob("ChatExporter-Setup-*.exe"):
        old.unlink()
    shutil.copy2(installer, inp / installer.name)
    shutil.copy2(SCRIPT, inp / SCRIPT.name)
    wsb = work / "chatexporter_test.wsb"
    wsb.write_text(WSB.format(inp=inp, out=out), encoding="utf-8")
    print(f"Arbeitsordner: {work}\nStarte Windows Sandbox mit {installer.name} ...", flush=True)
    os.startfile(wsb)  # type: ignore[attr-defined]  # nur Windows
    deadline = time.monotonic() + args.timeout_minutes * 60
    done = out / "done.txt"
    while time.monotonic() < deadline and not done.exists():
        time.sleep(10)
    results = out / "results.txt"
    if not results.exists():
        print("Keine Ergebnisse – Sandbox nicht gestartet oder Zeitlimit erreicht.")
        return 2
    text = results.read_text(encoding="utf-8-sig", errors="replace")
    print(text)
    if not done.exists():
        print("WARNUNG: Zeitlimit erreicht, Test nicht vollstaendig.")
        return 1
    failed = [line for line in text.splitlines() if line.startswith("FEHLER")]
    ok = [line for line in text.splitlines() if line.startswith("OK")]
    print(f"Ergebnis: {len(ok)} OK, {len(failed)} FEHLER. Einzelausgaben: {out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
