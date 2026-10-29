# Entwicklung nach dem ersten Release

Seit v0.0.1 wird die Codehistorie über Git verwaltet. Ein Checkout ist die aktive
Codebasis; weitere pre-X-Verzeichnisse sind nicht erforderlich. Historische
Entwicklungsstände können als lokales Archiv erhalten bleiben.

Änderungen auf einem Branch entwickeln, passende Tests und die gesamte aktive
Suite ausführen und per Pull Request nach main übernehmen. Die Dokumentation
nach erfolgreicher Prüfung nachziehen. main trägt den aktuellen Quellstand;
veröffentlichte Versionen sind durch unveränderte Release-Tags identifiziert.
Neue fachliche Änderungen werden im Abschnitt Unreleased des Changelogs erfasst.

Daten, Konfiguration, Secrets, Browserprofile und Betriebslogs liegen außerhalb
des Code-Repositories. Git ersetzt keine Sicherung dieser Daten. Build- und
Testdateien sind erzeugte Artefakte; für Releases die ausgelieferten Pakete und
ihre Prüfbelege aufbewahren. Quellcodeänderungen nicht durch Kopieren kompletter
Workspace-Verzeichnisse versionieren.

Der [Release-Ablauf](RELEASE.md) berechnet Patch/Minor/Major aus dem letzten
stabilen Tag, baut und prüft einen eigenen Snapshot und erstellt den neuen Tag
erst bei der abschließenden Veröffentlichung. Eine gesonderte Product-Ablage
ist ein Übernahmeziel und kein zweiter Entwicklungscheckout.

Einrichtung: [README](../README.md). Prüfungen: [Tests](TESTING.md).
