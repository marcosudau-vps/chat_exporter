# ChatExporter

[![CI](https://github.com/marcosudau-vps/chat_exporter/actions/workflows/ci.yml/badge.svg)](https://github.com/marcosudau-vps/chat_exporter/actions/workflows/ci.yml)

ChatExporter archiviert Gespräche aus ChatGPT, OpenCode, Codex CLI und Claude Code.
Er aktualisiert lokale Rohdaten inkrementell, lädt referenzierte ChatGPT-Dateien
und erzeugt Markdown- und JSON-Exporte. Bedienung über Menü oder Befehle, mit
Einrichtung und Zeitplanung über die Windows-Aufgabenplanung.

Aktueller Quellstand: **0.0.1**. Veröffentlichung wird über den Release-Ablauf vorbereitet.
Windows 10/11; das installierte Programm benötigt kein Python. Das Setup arbeitet
pro Benutzer und erstellt Desktop- und Startmenü-Verknüpfungen mit dem App-Icon.

- [Installation und Alltag](docs/GETTING_STARTED.md)
- [Befehle](docs/BEFEHLE.md), [Konfiguration](docs/KONFIGURATION.md)
- [Bekannte Einschränkungen](docs/BEKANNTE_EINSCHRAENKUNGEN.md)
- [Architektur](docs/ARCHITEKTUR.md), [Storage](docs/STORAGE_KONZEPT.md)
- [Tests](docs/TESTING.md), [Bauen](docs/BUILD.md), [Release-Ablauf](docs/RELEASE.md)
- [Sicherheit](docs/SECURITY.md), [Beiträge](docs/CONTRIBUTING.md)

## Aus dem Quellcode starten

Python 3.12 oder neuer; der Release-Bau verwendet Python 3.12.10 auf Windows.

```powershell
git clone https://github.com/marcosudau-vps/chat_exporter.git
cd chat_exporter
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-ci.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\chatexporter.exe --help
```

Die bearbeitbare Installation verwendet den Quellbaum einschließlich des
Werkzeugs für die Windows-Aufgabenplanung unter `tools/`. Sie ist der vorgesehene
Weg für den Start aus dem Quellcode. Das fertige Windows-Programm enthält dieses
Werkzeug bereits.

Ohne eigenen Pfad verwendet das Programm `~/.chatexporter`. Für Versuche ein
eigenes `CHATEXPORTER_HOME` setzen. Zugangsdaten gehören in eine lokale `.env`
oder die Umgebung. Vorlagen: `config.example.yaml` und `.env.example`.
Chatdaten, Browserprofile und Zugangsdaten niemals committen.

## Lizenz

[MIT](LICENSE), Copyright 2026 marcosudau-vps. Abhängigkeiten behalten ihre
eigenen Lizenzen; siehe [Drittanbieter](docs/THIRD_PARTY.md).

## Releases

Installer, Portable-ZIP und Python-Wheel stehen in den GitHub-Releases bereit.
Die [automatische Release-Verwaltung](docs/RELEASE.md) erhöht standardmäßig Patch,
mit `--minor` Minor oder mit `--major` Major. Prüfläufe erzeugen keinen Tag.
Versionierte Python-Wheels lassen sich unter Windows mit Python ≥ 3.12 installieren:

```powershell
python -m pip install ".\chatexporter_gen4-<Version>-py3-none-any.whl[scheduler,autologin]"
```

Der Paketquellcode wird derzeit ausschließlich auf GitHub veröffentlicht.
