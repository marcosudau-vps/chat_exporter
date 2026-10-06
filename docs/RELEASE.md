# Automatische Releases auf GitHub

EXE, portables Programm, Python-Wheel und Quellpaket werden auf GitHub bereitgestellt.
Es gibt keine Veröffentlichung auf PyPI. Twine wird ausschließlich zur lokalen
Prüfung der Paketmetadaten verwendet.

## Start und Versionsnummer

```powershell
python packaging/release.py                # Patch-Prüflauf ohne Tag
python packaging/release.py --minor        # Minor-Prüflauf
python packaging/release.py --major        # Major-Prüflauf
python packaging/release.py --publish      # GitHub-Release und Tag nach Abnahme
```

`--minor` und `--major` sind gegenseitig ausgeschlossen. Die Flags lassen sich
mit `--publish` kombinieren. In GitHub Actions dieselben Optionen über
**Automatic release → Run workflow → bump / dry_run** auswählen.

Ausgangspunkt ist der höchste stabile Versions-Tag `vMAJOR.MINOR.PATCH`.
Kandidaten-Tags wie `v0.0.1rc3` und vorbereitete Branches zählen nicht.
Ohne stabiles Release gilt `0.0.0`; der erste Patch-Schritt ergibt `0.0.1`.

| Auswahl | Ausgehend von 1.2.9 |
| --- | --- |
| Standard / Patch | 1.2.10 |
| `--minor` | 1.3.0 |
| `--major` | 2.0.0 |

Die Version wird in einem eigenständigen Release-Snapshot automatisch in
`pyproject.toml`, `src/chatexporter/config/version.py`, README, Changelog und
Release-Notizen gesetzt. Dieser Snapshot wird unter `release/run-<Laufnummer>`
gespeichert und exakt dieser Commit gebaut, getestet und später getaggt.
Die Entwicklungsfassung auf `main` wird dadurch nicht vorzeitig zum Release.

## Reihenfolge und Fehlerfälle

1. Version berechnen und Snapshot vorbereiten; **kein Versions-Tag**.
2. Gesamte Windows-Testsuite einschließlich lokaler Edge-Browsertests,
   Versions-/Dokumentationsprüfung und Abhängigkeitsprüfung ausführen.
3. Windows-Programm und Installer bauen, 12 Smoke-Tests ausführen. Wheel und
   Quellpaket bauen; Version, Metadaten und mitgeliefertes Scheduler-Werkzeug prüfen.
4. Alle Artefakte mit Versionsnummern und Prüfsummen als GitHub-Build-Artefakt speichern.
5. Ein Prüflauf (`dry_run=true`, Standard) endet hier. Er erzeugt weder Release
   noch Versions-Tag und zählt die letzte stabile Version nicht hoch.
6. Für einen echten Release-Start ist die menschliche Freigabe der GitHub-Umgebung
   `release` erforderlich. Vorher genau den bereitgestellten Installer einschließlich
   Installation, Update, Deinstallation und Icons auf frischem Windows prüfen.
7. GitHub-Entwurf mit allen Dateien hochladen und sämtliche GitHub-Upload-Prüfsummen
   mit den lokalen Dateien vergleichen. Erst danach den Versions-Tag erstellen.
   Danach den vollständig geprüften Entwurf öffentlich schalten. Falls dieser
   letzte API-Schritt ausfällt, bleiben Dateien und Tag für die Wiederholung erhalten.

Misslingt ein Test, Bau oder Upload-Abgleich, entsteht kein Versions-Tag.
Bei einem Fehler in der Finalisierung **denselben Lauf über „Re-run failed jobs“**
fortsetzen; erfolgreich gebaute Dateien werden wiederverwendet. Kein neuer
Versionsschritt, keine Tag-Änderung und kein Überschreiben anderer Release-Dateien.
Externe Änderungen eines bestehenden Tags/Entwurfs werden abgelehnt.
Release-Läufe sind serialisiert; laufende Veröffentlichungen werden nicht abgebrochen.

Alle herunterladbaren Dateinamen enthalten die Version: Installer, Portable-ZIP,
Wheel, Quellpaket, Build-Bericht, Release-Notizen, Prüfsummen und Testbericht.
Im installierten Programm und innerhalb des Portable-ZIP bleibt der Launcher
`chatexporter.exe`, damit vorhandene Verknüpfungen und Aufgaben stabil bleiben.

Die endgültige Veröffentlichung erfolgt nach Freigabe der `release`-Umgebung.
Eine Übernahme in den Product-Stand benötigt gesonderte menschliche Abnahme.
Eine Windows-Code-Signatur wird nicht erzeugt.
