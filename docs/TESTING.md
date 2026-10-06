# Tests

Die vollständige aktive Suite läuft unter Windows mit Microsoft Edge. Die
Browsertests verwenden eine lokale Nachbildung auf `127.0.0.1`, keine echten
ChatGPT-Zugangsdaten. CI lehnt übersprungene Tests ab.

```powershell
.\.venv\Scripts\python.exe -m pytest --junitxml=test-results.xml
.\.venv\Scripts\python.exe packaging/ci/check.py --junit test-results.xml
.\.venv\Scripts\python.exe -m pip_audit -r requirements-ci.lock --disable-pip --no-deps
```

CI prüft Version, installierte Paketmetadaten, Dokumentationslinks, die gesamte
Testsuite und bekannte Schwachstellen der festgelegten Abhängigkeiten. Ein
Release-Bau wird zusätzlich mit Smoke-Tests und Prüfung der PE-Icons abgesichert.
Installer separat in einer frischen Umgebung prüfen:
[Windows Sandbox](../packaging/sandbox/README.md).

Echte Anmeldung, Profilkopie und Kontoabruf bleiben manuelle Prüfungen:
[Live-Checkliste](LIVE_TEST_CHECKLIST.md).
