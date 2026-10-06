# Release-Ablauf

1. Vollständige Tests, Abhängigkeitsprüfung und Dokumentationsprüfung müssen bestehen.
2. Version in `pyproject.toml` und `src/chatexporter/config/version.py` setzen,
   Release-Notizen aktualisieren und Paket neu installieren.
3. Änderungen über einen Pull Request nach `main` übernehmen.
4. Tag `v<VERSION>` auf dem geprüften Commit anlegen und pushen. Der Tag muss
   exakt zur Paketversion passen. Die Pipeline testet diesen Commit, baut
   den Installer und prüft Metadaten, Icons und Prüfsummen.
5. Die Pipeline erstellt einen **GitHub-Release-Entwurf** mit Installer,
   `SHA256SUMS.txt` und `BUILD.json`. Kandidaten sind als Prerelease markiert.
6. Genau diesen Installer herunterladen und Installation, Update,
   Deinstallation sowie Icons in einer frischen Windows-Umgebung prüfen.
7. Erst nach menschlicher Abnahme den Entwurf veröffentlichen.

Die Pipeline veröffentlicht keine Releases automatisch. Ein grüner Testlauf
allein ist keine finale Freigabe. Private Testarchive und Chatbestände gehören
nicht in Release-Anhänge. Eine Windows-Code-Signatur wird derzeit nicht erzeugt.
