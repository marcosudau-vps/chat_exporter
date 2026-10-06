# Komplett-Test auf frischem Windows (Windows Sandbox)

Prüft ein gebautes Installationsprogramm auf einem frischen Windows ohne Python:

- Installation, Startmenü, Desktop-Verknüpfung samt Ziel und Icon, Programm-Icon,
  Eintrag und Icon unter „Apps“, PATH, Start ohne Python
- Home-Ordner und Storage, Befehl `chatgpt login --schrittweise`, Einstellung
  `browser.window`, verdeckte Secrets
- status, export, task list; Einrichtung mit täglicher Aufgabe; geplanter Lauf
  (Ergebnis 0)
- `task create --startup`: angelegt oder verständlich abgelehnt
- ChatGPT-Lauf ohne Anmeldung: Edge wird verborgen und ohne Synchronisierung
  gestartet, der Lauf endet geordnet
- Chrome for Testing: echter Download, Start, Fernsteuerung, Schließen
- Deinstallation einschließlich Desktop-Verknüpfung; der Datenordner bleibt

Aufruf aus dem Codeordner:

```powershell
python packaging\sandbox\run_sandbox_test.py --installer <Pfad>\ChatExporter-Setup-<Version>.exe
```

Voraussetzungen und Ablauf:
- Das Windows-Feature „Windows-Sandbox“ ist aktiv, und keine andere Sandbox ist
  offen.
- Die Sandbox startet sichtbar, arbeitet etwa 2–20 Minuten und fährt danach
  selbst herunter.
- Ergebnis: eine Zeile je Prüfung (`OK`/`FEHLER`) und die Einzelausgaben im
  Ordner `out/`. Exitcode 0 heißt keine Fehler.

Verwendet für die Release-Kandidaten ab 0.0.1rc1 (siehe [docs/RELEASE.md](../../docs/RELEASE.md)).
