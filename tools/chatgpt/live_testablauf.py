"""Gesamttest gegen echtes ChatGPT im Entwicklungsmodus – automatisch geprueft, wiederverwendbar.

Fuehrt den Testablauf aus ``docs/TESTABLAUF_ENTWICKLUNGSMODUS.md`` aus und prueft jedes Ergebnis selbst:

- **Teil A:** neues Profil mit automatischer Anmeldung -> Erstabruf (5 Seiten) -> Folgelauf ->
  drei Chats nur lokal loeschen -> Update laedt genau diese neu, ohne Anmeldung, gleiches Profil ->
  Kontrolllauf.
- **Teil B:** geplanter, unbeaufsichtigter Lauf (Windows-Aufgabe) mit weiterem neuen Profil;
  danach muss dieses Profil angemeldet sein.
- **Zusatz:** fremder Ordner wird kein Storage; Passwort ueber ``--set`` wird nirgends gespeichert.
- **Teil C** (nur mit ``--teil-c``, interaktiv): Profilkopie mit Schliessen und Wiederoeffnen des
  echten Browsers; die Kopie wird automatisch auf ihre Anmeldung geprueft.
- **Ueberall:** Kein Zugangsdatum aus der ``.env`` erscheint in einer Ausgabe oder Storage-Datei
  (Werte werden nur im Speicher verglichen, nie ausgegeben).

Alles laeuft mit eigener Test-Konfiguration unter ``workspace/_testlauf/<Zeitpunkt>/`` (eigener
Storage, eigene Profile, eigene Ports); der echte Bestand und ``workspace/config.yaml`` bleiben
unberuehrt. Am Ende wird aufgeraeumt (Test-Browser, Aufgabe, Testordner, Registry-Eintrag des
Test-Storages), ausser mit ``--behalten``. Bericht und Ausgaben:
``workspace/_dokumentation/60_ARBEITSDOKUMENTATION/<Datum>_testablauf_dev_<Uhrzeit>/``.

Aufruf (im Ordner ``workspace``):
    .\\.venv\\Scripts\\python.exe ChatExporter_Gen4_pre-6\\tools\\chatgpt\\live_testablauf.py
    ... --teil-c            zusaetzlich Profilkopie (Edge wird geschlossen und wieder geoeffnet)
    ... --nur-a             nur Teil A
    ... --behalten          Testordner usw. nicht aufraeumen

Exitcode 0, wenn keine Pruefung FEHLER meldet.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

CODE = Path(__file__).resolve().parents[2]            # ChatExporter_Gen4_pre-6
WORKSPACE = CODE.parent
VENV = WORKSPACE / ".venv" / "Scripts"
EXE = VENV / "chatexporter.exe"
PY = VENV / "python.exe"
ALLOWED_LOGIN_HOSTS = ("chatgpt.com", "auth.openai.com")
SECRET_KEYS = ("CHATGPT_USERNAME", "CHATGPT_PASSWORD", "CHATGPT_2FA_SECRET")
TASK_NOT_RUN, TASK_RUNNING = 267011, 267009
#: Registry-Spiegel der zuletzt geladenen globalen Konfiguration. Jeder Aufruf mit der
#: Test-Konfiguration schreibt ihn neu; er wird vorher gesichert und am Ende wiederhergestellt.
MIRROR_KEY = r"HKCU\Software\ChatExporter\config"


# -- Auswertung (auch einzeln getestet) ---------------------------------------------------------------

def parse_login_json(output: str) -> dict | None:
    """Das JSON am Ende der Ausgabe von ``chatgpt login``."""
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "{":
            try:
                return json.loads("\n".join(lines[i:]))
            except ValueError:
                continue
    return None


def parse_deleted_ids(output: str) -> list[str]:
    """IDs aus der Ausgabe von ``local_delete_probe.py --ausfuehren``."""
    return re.findall(r"^\s*loesche \([^)]*\): (\S+)", output, flags=re.M)


def parse_task_result(output: str) -> int | None:
    match = re.search(r"Letztes Ergebnis:\s+(-?\d+)", output)
    return int(match.group(1)) if match else None


def read_dotenv(path: Path) -> dict[str, str]:
    """Einfacher .env-Leser (letzter Eintrag gewinnt). Werte bleiben im Speicher."""
    values: dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if value:
                values[key.strip()] = value
    except OSError:
        pass
    return values


def find_secrets(text: str, secrets: dict[str, str]) -> list[str]:
    """Namen der Zugangsdaten, deren Wert im Text vorkommt (nie die Werte selbst)."""
    return [name for name, value in secrets.items() if len(value) >= 6 and value in text]


# -- Ablauf ------------------------------------------------------------------------------------------

class Run:
    def __init__(self, root: Path, report_dir: Path, secrets: dict[str, str]):
        self.root, self.report_dir, self.secrets = root, report_dir, secrets
        self.config = root / "config.yaml"
        self.storage = root / "storage"
        self.checks: list[tuple[str, str, str, str]] = []   # (Schritt, Pruefung, OK/FEHLER/HINWEIS, Detail)
        self.outputs: list[str] = []
        self.env = {**os.environ, "CHATEXPORTER_CONFIG": str(self.config), "PYTHONIOENCODING": "utf-8"}
        for key in [k for k in self.env if k.startswith("CHATEXPORTER_") and k != "CHATEXPORTER_CONFIG"]:
            del self.env[key]                                  # nur die Test-Konfiguration zaehlt
        self.counter = 0

    # Ausgabe ------------------------------------------------------------------------------------------
    def check(self, step: str, name: str, ok: bool | None, detail: str = "") -> bool:
        state = "OK" if ok else ("HINWEIS" if ok is None else "FEHLER")
        self.checks.append((step, name, state, detail))
        print(f"   [{state:7}] {name}" + (f" – {detail}" if detail else ""), flush=True)
        return bool(ok)

    def cmd(self, label: str, args: list[str], *, timeout: int = 1800, interactive: bool = False) -> tuple[int, str]:
        """Befehl ausfuehren; Ausgabe live zeigen und mitschreiben (bei interactive nicht mitschneiden)."""
        self.counter += 1
        shown = " ".join(str(a) for a in args)
        print(f"\n>> {shown}", flush=True)
        if interactive:
            code = subprocess.call([str(a) for a in args], env=self.env, cwd=WORKSPACE)
            self._save(label, f"> {shown}\n(interaktiv, Ausgabe nicht mitgeschnitten)\nExitcode {code}\n")
            return code, ""
        proc = subprocess.Popen([str(a) for a in args], env=self.env, cwd=WORKSPACE, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=None)
        chunks: list[bytes] = []
        start = time.monotonic()
        assert proc.stdout is not None
        while True:
            data = proc.stdout.read1(4096) if hasattr(proc.stdout, "read1") else proc.stdout.read(1)
            if not data:
                break
            chunks.append(data)
            sys.stdout.write(data.decode("utf-8", errors="replace"))
            sys.stdout.flush()
            if time.monotonic() - start > timeout:
                proc.kill()
                break
        code = proc.wait()
        text = b"".join(chunks).decode("utf-8", errors="replace")
        self.outputs.append(text)
        self._save(label, f"> {shown}\nExitcode {code}\n\n{text}")
        return code, text

    def _save(self, label: str, text: str) -> None:
        logs = self.report_dir / "ausgaben"
        logs.mkdir(parents=True, exist_ok=True)
        for name, value in self.secrets.items():                # niemals Zugangsdaten auf die Platte
            if len(value) >= 6:
                text = text.replace(value, f"<{name} VERDECKT>")
        (logs / f"{self.counter:02d}_{label}.txt").write_text(text, encoding="utf-8")

    # Hilfen ------------------------------------------------------------------------------------------
    def ce(self, label: str, *args: str, **kw) -> tuple[int, str]:
        return self.cmd(label, [EXE, *args], **kw)

    def latest_report(self) -> dict:
        runs = sorted((self.storage / ".storage" / "runs").glob("sync_*.json"))
        if not runs:
            return {}
        return json.loads(runs[-1].read_text(encoding="utf-8")).get("sources", {}).get("chatgpt", {})

    def storage_id(self) -> str | None:
        try:
            text = (self.storage / ".storage" / "storage.yaml").read_text(encoding="utf-8")
        except OSError:
            return None
        match = re.search(r"^id:\s*(\w+)", text, flags=re.M)
        return match.group(1) if match else None


def write_config(run: Run) -> None:
    run.root.mkdir(parents=True)
    root, env_file = str(run.root), str(WORKSPACE / ".env")
    run.config.write_text(f"""dev_mode: true
dev:
  listing_max_pages: 5
  conversation_fetches: 0
bootstrap:
  env_file: '{env_file}'
storage:
  root: '{root}\\storage'
raw_session_updater:
  sources: [chatgpt]
task_scheduler:
  continuation:
    enabled: false
providers:
  chatgpt:
    browser:
      user_data_dir: '{root}\\profil'
      cdp_port: 9333
      leave_browser_running: false
    sync:
      listing_limit: 5
""", encoding="utf-8")


def no_login(text: str) -> bool:
    """Keine Anmeldung in dieser Ausgabe (Meldungen: „Keine gueltige ChatGPT-Sitzung – automatische
    Anmeldung ...“, „Automatische Anmeldung nicht abgeschlossen“, Anmeldung von Hand)."""
    low = text.lower()
    return "automatische anmeldung" not in low and "keine gueltige chatgpt-sitzung" not in low


def part_a(run: Run, has_2fa: bool) -> bool:
    step = "1 Anmeldung"
    print("\n=== Teil A, Schritt 1: neues Profil, automatische Anmeldung ===")
    code, out = run.ce("login", "chatgpt", "login")
    data = parse_login_json(out) or {}
    auto = data.get("auto_login") or {}
    if not run.check(step, "chatgpt login erfolgreich", code == 0 and data.get("ok") is True,
                     f"Exitcode {code}, ok={data.get('ok')}"):
        return False
    run.check(step, "es war eine neue Anmeldung (leeres Profil)", data.get("already_logged_in") is False)
    run.check(step, "automatische Anmeldung erfolgreich", auto.get("ok") is True, auto.get("reason", ""))
    pages = auto.get("pages") or []
    foreign = [p for p in pages if not p.split("/")[0] in ALLOWED_LOGIN_HOSTS]
    run.check(step, "nur chatgpt.com und auth.openai.com besucht", bool(pages) and not foreign,
              ", ".join(sorted({p.split('/')[0] for p in pages})))
    if has_2fa:
        run.check(step, "Einmalcode genau einmal eingetragen", out.count("Einmalcode eingetragen") == 1,
                  f"{out.count('Einmalcode eingetragen')}x")
    code, out = run.ce("storage_show", "storage", "show")
    run.check(step, "Storage angelegt (Storage-Schema 2)", code == 0 and "storage-schema-2" in out)

    step = "2 Erstabruf"
    print("\n=== Teil A, Schritt 2: Speicher fuellen (5 Seiten je 5 Eintraege) ===")
    code, out = run.ce("update_1", "update")
    rep = run.latest_report()
    listing = (rep.get("detail") or {}).get("listing") or {}
    stats = rep.get("stats") or {}
    run.check(step, "update Exitcode 0", code == 0, f"Exitcode {code}")
    run.check(step, "Entwicklungsmodus mit 5 Seiten aktiv", "hoechstens 5 Listing-Seiten" in out)
    run.check(step, "keine erneute Anmeldung", no_login(out))
    run.check(step, "Erstabruf (full, initial)", listing.get("effective") == "full" and listing.get("escalation") == "initial",
              f"effective={listing.get('effective')}, escalation={listing.get('escalation')}")
    fetched = int(stats.get("sessions_fetched") or 0)
    if not run.check(step, "Konversationen geladen (1 bis 50)", 1 <= fetched <= 50, f"{fetched} geladen"):
        return False
    run.check(step, "keine fehlgeschlagenen Konversationen", int(stats.get("sessions_failed") or 0) == 0)

    step = "3 Folgelauf"
    print("\n=== Teil A, Schritt 3: Folgelauf ohne Aenderung ===")
    code, out = run.ce("update_2", "update")
    rep = run.latest_report()
    listing = (rep.get("detail") or {}).get("listing") or {}
    fetched = int((rep.get("stats") or {}).get("sessions_fetched") or 0)
    run.check(step, "update Exitcode 0", code == 0, f"Exitcode {code}")
    run.check(step, "sparsames Listing (recent)", listing.get("effective") == "recent", str(listing.get("effective")))
    run.check(step, "keine erneute Anmeldung", no_login(out))
    run.check(step, "nichts neu geladen", True if fetched == 0 else None,
              "0" if fetched == 0 else f"{fetched} geladen – zwischendurch auf ChatGPT geaenderte Chats?")

    step = "4 Lokal loeschen"
    print("\n=== Teil A, Schritt 4: drei Chats nur lokal loeschen ===")
    code, out = run.cmd("loeschen", [PY, CODE / "tools/chatgpt/local_delete_probe.py", "--storage", run.storage,
                                     "--ausfuehren"])
    deleted = parse_deleted_ids(out)
    if not run.check(step, "drei Rohdateien geloescht", code == 0 and len(deleted) == 3, ", ".join(deleted)):
        return False

    step = "5 Neu laden"
    print("\n=== Teil A, Schritt 5: Update nach dem lokalen Loeschen ===")
    code, out = run.ce("update_3", "update")
    rep = run.latest_report()
    listing = (rep.get("detail") or {}).get("listing") or {}
    got = {item.get("id") for item in (rep.get("items") or {}).get("fetched") or []}
    run.check(step, "update Exitcode 0", code == 0, f"Exitcode {code}")
    run.check(step, "Fehlen erkannt, Wechsel auf full", "fehlen lokal" in out and listing.get("escalation") == "local_files_missing",
              str(listing.get("escalation")))
    run.check(step, "genau die geloeschten Chats als fehlend gemeldet",
              sorted(listing.get("local_missing") or []) == sorted(deleted))
    run.check(step, "alle drei neu geladen (auch der aelteste)", set(deleted) <= got,
              f"{len(set(deleted) & got)} von 3")
    run.check(step, "keine erneute Anmeldung", no_login(out))
    run.check(step, "Verlustliste danach leer",
              not (run.storage / ".storage" / "status_registry" / "lost_conversations.json").exists())
    code, out = run.ce("check", "check")
    run.check(step, "check ohne Fehler", code == 0, f"Exitcode {code}")

    step = "6 Kontrolllauf"
    print("\n=== Teil A, Schritt 6: Kontrolllauf ===")
    code, out = run.ce("update_4", "update")
    listing = (run.latest_report().get("detail") or {}).get("listing") or {}
    run.check(step, "update Exitcode 0", code == 0, f"Exitcode {code}")
    run.check(step, "wieder sparsam (recent)", listing.get("effective") == "recent", str(listing.get("effective")))
    run.check(step, "keine erneute Anmeldung", no_login(out))
    return True


def part_b(run: Run) -> None:
    step = "7 Geplanter Lauf"
    print("\n=== Teil B: geplanter, unbeaufsichtigter Lauf mit automatischer Anmeldung ===")
    run.ce("profil_geplant", "config-global", "set", "providers.chatgpt.browser.user_data_dir",
           str(run.root / "profil_geplant"))
    run.ce("port_geplant", "config-global", "set", "providers.chatgpt.browser.cdp_port", "9334")
    when = (datetime.now() + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M")
    code, out = run.ce("task_create", "task", "create", "Testlauf-geplant", "--once", when,
                       "--command", "update --non-interactive")
    if not run.check(step, "Aufgabe angelegt", code == 0, f"Start {when}"):
        return
    print(f"   Warte auf den geplanten Lauf (Start {when}); den Rechner bitte nicht sperren ...", flush=True)
    result, deadline = None, time.monotonic() + 15 * 60
    while time.monotonic() < deadline:
        time.sleep(20)
        _code, out = run.ce("task_get", "task", "get", "testlauf-geplant")
        result = parse_task_result(out)
        if result not in (None, TASK_NOT_RUN, TASK_RUNNING) and "running" not in out.lower():
            break
    run.check(step, "geplanter Lauf mit Ergebnis 0", result == 0, f"Letztes Ergebnis {result}")
    code, out = run.ce("login_geplant", "chatgpt", "login")
    data = parse_login_json(out) or {}
    run.check(step, "neues Profil ist danach angemeldet (Anmeldung lief unbeaufsichtigt)",
              data.get("ok") is True and data.get("already_logged_in") is True,
              f"already_logged_in={data.get('already_logged_in')}")
    code, _out = run.ce("task_delete", "task", "delete", "testlauf-geplant", "--yes")
    run.check(step, "Aufgabe wieder entfernt", code == 0)


def extras(run: Run) -> None:
    step = "9 Zusatz"
    print("\n=== Zusatz: fremder Ordner, Passwort ueber --set ===")
    foreign = run.root / "fremd"
    foreign.mkdir()
    (foreign / "notiz.txt").write_text("x", encoding="utf-8")
    code, out = run.ce("fremder_ordner", "--storage", str(foreign), "status")
    run.check(step, "fremder Ordner abgelehnt, nichts angelegt",
              code == 2 and "nicht leer und kein Storage" in out and [p.name for p in foreign.iterdir()] == ["notiz.txt"],
              f"Exitcode {code}")
    marker = "TEST-GEHEIM-" + datetime.now().strftime("%H%M%S")
    run.ce("secret_set", "--set", f"providers.chatgpt.auth.password={marker}", "status")
    hits = [str(p.relative_to(run.storage)) for p in run.storage.rglob("*")
            if p.is_file() and p.suffix in (".jsonl", ".yaml", ".json") and marker.encode() in p.read_bytes()]
    run.check(step, "Passwort ueber --set nirgends gespeichert", not hits, ", ".join(hits) or "keine Fundstelle")


def part_c(run: Run) -> None:
    step = "8 Profilkopie"
    print("\n=== Teil C: Profilkopie mit geoeffnetem Browser ===")
    for kind in ("edge", "chrome"):
        if kind == "chrome" and input("\nAuch die Chrome-Kopie testen? (nur wenn Chrome mit ChatGPT-Anmeldung "
                                      "angezeigt wurde) [j/N] ").strip().lower() not in ("j", "ja"):
            break
        input(f"\nBitte {'Edge' if kind == 'edge' else 'Chrome'} mit einigen Tabs oeffnen und Wichtiges speichern. "
              f"Weiter mit ENTER ... ")
        if kind == "chrome":
            print("   Im Werkzeug die Edge-Kopie mit 'n' ablehnen und die Chrome-Kopie mit 'j' annehmen.")
        root = run.root / f"browser_{kind}"
        run.cmd(f"profilkopie_{kind}", [PY, CODE / "tools/chatgpt/browser_flow_lab.py", "--search",
                                        "--browser-root", root], interactive=True)
        copies = [p.parent for p in (root / "profiles").glob("*/chatexporter_copy.json")]
        if not run.check(step, f"{kind}: Kopie angelegt", bool(copies), ", ".join(p.name for p in copies)):
            continue
        reopened = input(f"Wurde {kind} mit Ihren vorherigen Tabs wieder geoeffnet? [j/n] ").strip().lower()
        run.check(step, f"{kind}: Browser mit Tabs wieder geoeffnet (Angabe des Benutzers)", reopened in ("j", "ja"))
        port = "9335" if kind == "edge" else "9336"
        run.ce(f"port_{kind}", "config-global", "set", "providers.chatgpt.browser.cdp_port", port)
        run.ce(f"art_{kind}", "config-global", "set", "providers.chatgpt.browser.kind", kind)
        code, out = run.ce(f"login_kopie_{kind}", "chatgpt", "login", "--profil", str(copies[0]))
        data = parse_login_json(out) or {}
        run.check(step, f"{kind}: Kopie traegt die ChatGPT-Anmeldung", data.get("already_logged_in") is True,
                  f"already_logged_in={data.get('already_logged_in')}")


def backup_mirror(report_dir: Path) -> Path | None:
    """Registry-Spiegel der echten Konfiguration sichern (``reg export``); None = gab es nicht."""
    report_dir.mkdir(parents=True, exist_ok=True)
    target = report_dir / "registry_spiegel_vorher.reg"
    done = subprocess.run(["reg", "export", MIRROR_KEY, str(target), "/y"], capture_output=True)
    return target if done.returncode == 0 and target.exists() else None


def restore_mirror(backup: Path | None) -> None:
    subprocess.run(["reg", "delete", MIRROR_KEY, "/f"], capture_output=True)
    if backup is not None:
        subprocess.run(["reg", "import", str(backup)], capture_output=True)


def cleanup(run: Run) -> None:
    print("\n=== Aufraeumen ===")
    marker = str(run.root).replace("'", "''")
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' or Name='chrome.exe'\" | "
          f"Where-Object {{ $_.CommandLine -like '*{marker}*' }} | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        print("   Hinweis: Test-Browser konnten nicht automatisch geschlossen werden.")
    run.ce("task_delete_rest", "task", "delete", "testlauf-geplant", "--yes")
    storage_id = run.storage_id()
    if storage_id:
        subprocess.run(["reg", "delete", rf"HKCU\Software\ChatExporter\Storages\{storage_id}", "/f"],
                       capture_output=True)
    time.sleep(2)
    import shutil
    shutil.rmtree(run.root, ignore_errors=True)
    print(f"   Testordner entfernt: {not run.root.exists()}; Registry-Eintrag {storage_id or '-'} entfernt.")


def write_report(run: Run, started: datetime, args: argparse.Namespace) -> Path:
    failed = [c for c in run.checks if c[2] == "FEHLER"]
    lines = [f"# Testablauf Entwicklungsmodus – {started:%Y-%m-%d %H:%M}", "",
             f"Programm: `{CODE.name}`, Version {_version()}; Skript `tools/chatgpt/live_testablauf.py`"
             f" (Teile: A{'' if args.nur_a else ', B, Zusatz'}{', C' if args.teil_c else ''}).", "",
             f"**Ergebnis: {sum(c[2] == 'OK' for c in run.checks)} OK, {len(failed)} FEHLER, "
             f"{sum(c[2] == 'HINWEIS' for c in run.checks)} HINWEIS.**", "",
             "| Schritt | Pruefung | Ergebnis | Detail |", "| --- | --- | --- | --- |"]
    lines += [f"| {s} | {n} | {r} | {d.replace('|', '/')} |" for s, n, r, d in run.checks]
    lines += ["", "Ausgaben je Befehl: `ausgaben/` (Zugangsdaten sind dort verdeckt, falls sie aufgetaucht waeren)."]
    report = run.report_dir / "BERICHT.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def _version() -> str:
    try:
        text = (CODE / "src/chatexporter/config/version.py").read_text(encoding="utf-8")
        return re.search(r'__version__ = "([^"]+)"', text).group(1)  # type: ignore[union-attr]
    except (OSError, AttributeError):
        return "?"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--teil-c", action="store_true", help="zusaetzlich Profilkopie (interaktiv)")
    parser.add_argument("--nur-a", action="store_true", help="nur Teil A")
    parser.add_argument("--behalten", action="store_true", help="Testordner, Registry usw. nicht aufraeumen")
    args = parser.parse_args(argv)
    if not EXE.is_file():
        print(f"Programm nicht gefunden: {EXE}")
        return 2
    secrets = {k: v for k, v in read_dotenv(WORKSPACE / ".env").items() if k in SECRET_KEYS}
    if not {"CHATGPT_USERNAME", "CHATGPT_PASSWORD"} <= set(secrets):
        print("In workspace\\.env fehlen CHATGPT_USERNAME und/oder CHATGPT_PASSWORD.")
        return 2
    started = datetime.now()
    root = WORKSPACE / "_testlauf" / started.strftime("%Y-%m-%d_%H-%M-%S")
    report_dir = (WORKSPACE / "_dokumentation" / "60_ARBEITSDOKUMENTATION"
                  / f"{started:%Y-%m-%d}_testablauf_dev_{started:%H%M%S}")
    run = Run(root, report_dir, secrets)
    mirror_backup = backup_mirror(report_dir)
    write_config(run)
    print(f"Testordner: {root}\nBericht:    {report_dir}")
    try:
        ok = part_a(run, has_2fa="CHATGPT_2FA_SECRET" in secrets
                    or "CHATGPT_2FA_REFERENCE" in read_dotenv(WORKSPACE / ".env"))
        if ok and not args.nur_a:
            part_b(run)
            extras(run)
        if ok and args.teil_c:
            part_c(run)
        leaked = sorted({name for text in run.outputs for name in find_secrets(text, secrets)})
        storage_texts = [p.read_bytes().decode("utf-8", errors="replace") for p in run.storage.rglob("*")
                         if p.is_file() and p.suffix in (".jsonl", ".yaml", ".json", ".md")] if run.storage.exists() else []
        leaked_files = sorted({name for text in storage_texts for name in find_secrets(text, secrets)})
        run.check("Gesamt", "keine Zugangsdaten in Ausgaben", not leaked, ", ".join(leaked) or "keine")
        run.check("Gesamt", "keine Zugangsdaten in Storage-Dateien", not leaked_files, ", ".join(leaked_files) or "keine")
    except KeyboardInterrupt:
        run.check("Gesamt", "Ablauf vollstaendig", False, "mit Strg+C abgebrochen")
    finally:
        report = write_report(run, started, args)
        if not args.behalten:
            cleanup(run)
        restore_mirror(mirror_backup)
        print("   Registry-Spiegel der echten Konfiguration wiederhergestellt"
              + ("" if mirror_backup else " (vorher nicht vorhanden – entfernt)") + ".")
    failed = sum(c[2] == "FEHLER" for c in run.checks)
    print(f"\nErgebnis: {sum(c[2] == 'OK' for c in run.checks)} OK, {failed} FEHLER. Bericht: {report}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
