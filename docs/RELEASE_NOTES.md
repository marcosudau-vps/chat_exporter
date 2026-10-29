# ChatExporter 0.0.1

Lokale Archivierung von ChatGPT, OpenCode,
Codex CLI und Claude Code; inkrementelle Aktualisierung, referenzierte
ChatGPT-Dateien, Markdown-/JSON-Exporte, Einrichtung und Windows-Zeitplanung.

Eigene Icons für Programm und Setup, Desktop- und Startmenü-Verknüpfungen
sowie die App-Liste in den Windows-Einstellungen. Das Setup arbeitet pro
Benutzer und bewahrt Daten und Konfiguration bei Update und Deinstallation.

Die festgelegten Build-/Test-Abhängigkeiten enthalten die Sicherheitsupdates
für certifi, filelock, Pillow und setuptools vom Oktober 2026.

Installer, Portable-ZIP, Python-Wheel und Quellpaket werden auf GitHub angeboten.
Die Versionsnummer wird automatisch im Release-Ablauf bestimmt. Vollständige
Tests, Builds und Upload-Prüfsummen gehen dem Versions-Tag voraus. Ein Prüflauf
veröffentlicht nichts; der Produktionsablauf benötigt menschliche Freigabe.
Version 0.0.1 wurde am 2026-10-29 auf GitHub veröffentlicht.

Bekannte Grenzen: Windows; geplante Läufe benötigen einen angemeldeten Benutzer.
ChatGPT benötigt einen Browser. Automatische Anmeldung unterstützt E-Mail/Passwort
mit optionalem TOTP, keine SSO-Anmeldung, Passkeys oder Captchas.
Chrome-Profilkopien sind noch nicht mit einem echten Konto bestätigt.
