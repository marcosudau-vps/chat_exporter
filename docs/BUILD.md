# Windows-Programm und Installer bauen

Voraussetzungen: Windows, Python 3.12.10, die festgelegten Abhängigkeiten aus
`requirements-ci.lock` und Inno Setup 6.7.3. Zuerst die Installation aus der
[README](../README.md) durchführen. Nach Versionsänderungen das Paket neu
installieren, damit die eingebauten Distributionsmetadaten übereinstimmen.

```powershell
.\.venv\Scripts\python.exe packaging/ci/check.py
.\.venv\Scripts\python.exe packaging/build.py --out _build
.\.venv\Scripts\python.exe packaging/ci/artifacts.py --build _build --out dist/release --commit (git rev-parse HEAD)
```

PyInstaller erzeugt einen Ordner-Build, Inno Setup den Installer pro Benutzer.
Der Smoke-Test prüft Hilfe, Version, isolierte Konfiguration und eine pausierte
Testaufgabe (anlegen, anzeigen, entfernen). Er verwendet keine eigenen Daten.
Das Icon entsteht aus `assets/IconChatExporter.png` in sieben ICO-Größen.
Programm, Setup, Verknüpfungen und App-Liste verwenden es. Ein Terminalfenster
kann weiterhin das Icon seines Terminalprofils zeigen.

Die Artefaktprüfung verlangt einen Installer, richtige Paketmetadaten,
bestandene Smoke-Tests, passende Prüfsummen und identische Iconressourcen in
beiden EXE-Dateien. Das Bündel enthält Installer, `SHA256SUMS.txt`, `BUILD.json`
mit Commit/Version/Abhängigkeitsnachweis und Release-Notizen.

Der manuell startbare Workflow **Windows installer** prüft den festgelegten
SHA-256 des offiziellen Inno-Downloads. Der lokale Bau darf den Installer
überspringen; die Artefaktprüfung akzeptiert das nicht als Release-Bündel.
