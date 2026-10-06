# Befehle

Alle Befehle werden mit dem Paket installiert (`pyproject.toml`,
`[project.scripts]`). Jeder Befehl akzeptiert `--config <datei>` und `-h`.

**Globale Optionen** vor dem Befehl (`chatexporter …`): `--config <datei>`,
`--storage <pfad>` (mit diesem Storage arbeiten) und `--set SCHLUESSEL=WERT`
(beliebig oft). `--set` überschreibt eine Einstellung nur für diesen Aufruf und
hat höchsten Vorrang, z. B.
`chatexporter --set providers.chatgpt.sync.listing_mode=full update`
([KONFIGURATION.md](KONFIGURATION.md)).

**Storage:** Jeder Befehl, der mit Daten arbeitet, prüft zuerst den gewählten
Storage. Ein leerer Ordner wird als Storage angelegt; ein Ordner im alten oder
unklaren Format, nach einer abgebrochenen Umstellung oder ein nicht leerer fremder
Ordner wird nicht angefasst (Exitcode `2`, mit Hinweis, z. B. auf
`chatexporter storage migrate`). Schreibende Befehle (`update`, `index`,
`cleanup`, `export` und schreibende Provider-Befehle) halten während des Laufs die
Sperre des Storages; läuft schon ein solcher Befehl, endet ein zweiter mit
Exitcode `2` und nennt den Inhaber. Nach jedem Befehl werden leere
Zwischenablagen entfernt und die Gesamtsicht `.storage/state.yaml` neu erzeugt.

## Exitcodes

| Code | Bedeutung |
| --- | --- |
| `0` | ok |
| `1` | abgeschlossen, aber mit fachlichen Fehlern/Warnungen (z. B. einzelne Konversation oder Datei fehlgeschlagen, Prüfung nicht ok) |
| `2` | abgebrochen oder Teilausfall (Quelle fehlgeschlagen, ungültiges Fragment, Konfigurationsfehler, Storage nicht im Storage-Schema 2 oder belegt) |
| `130` | mit Strg+C abgebrochen (nur im Befehlsprotokoll) |

## Befehlsprotokoll

Jeder Befehl wird nach dem Ende als **eine JSON-Zeile** protokolliert, egal
ob er über das Menü, `chatexporter …` oder einen Einzelbefehl
(`chatexporter-update`, `chatexporter-chatgpt`, …) gestartet wurde.

- **Ablage:** `logging.dir`, Standard `<storage>/.storage/logs/`; eine Datei je
  Zeitraum `logging.rotation` (`commands_<Beginn UTC>.jsonl`).
- **Aufräumen:** Dateien älter als `logging.retention` werden beim nächsten
  Befehl entfernt.
- **Nicht protokolliert** wird das Menü selbst, wohl aber jeder dort gewählte
  Punkt.
- **Kein Abbruch:** Ein Fehler beim Protokollieren bricht den Befehl nie ab;
  es erscheint nur ein Hinweis auf stderr.

| Feld | Inhalt |
| --- | --- |
| `timestamp`, `finished_at`, `duration_seconds` | Start, Ende (UTC) und Dauer |
| `command`, `program`, `argv` | ausgeführter Befehl, als Text und als Liste |
| `exit_code`, `interrupted` | Exitcode (`130` bei Strg+C) |
| `cwd`, `config_file`, `version`, `code_dir`, `python` | Umgebung: Arbeitsordner, Config, Programmstand |
| `summary` | Übersicht des Befehls (siehe unten) |

`summary` enthält die einfachen Felder des Abschlussberichts (z. B. `ok`,
`partial`, `run_manifest`), `totals` und je Quelle unter
`sources.<quelle>` dieselben Angaben wie die Konsolen-Zusammenfassung:

- `ok`, `sessions_new`, `sessions_changed`, `sessions_fetched`,
  `sessions_failed`, `files_materialized`, `requests_total`,
  `duration_seconds`
- `items_fetched`, `items_failed` (Anzahl der namentlich erfassten Einträge)
- bei ChatGPT außerdem `listing_mode`, `listing_effective`,
  gegebenenfalls `listing_escalation`, `abort_stage`

Bei Prüfungen kommen `error_count` und `warning_count` je Quelle hinzu. Die
vollständigen Listen der geholten Einträge stehen weiterhin im Laufbericht
(`run_manifest`).

## Menü: `chatexporter`

Ohne Argumente startet das Menü. Jeder Punkt führt genau den angezeigten
Befehl aus:

| Nr. | Punkt | Befehl |
| --- | --- | --- |
| 1 | Alle Quellen aktualisieren (ChatGPT-Listing laut Config, Standard `auto`) | `chatexporter update` |
| 2 | Alle Quellen aktualisieren – ChatGPT vollständig abgleichen | `chatexporter update --listing-mode full` |
| 3 | Eine Quelle aktualisieren … (bei ChatGPT Auswahl auto/recent/full) | `chatexporter update --source <quelle> [--listing-mode auto\|recent\|full]` |
| 4 | Gesamtindex neu aufbauen | `chatexporter index` |
| 5 | Alle Quellen prüfen | `chatexporter check` |
| 6 | Alle Quellen gründlich prüfen | `chatexporter check --deep` |
| 7 | Aufräumen – Probelauf | `chatexporter cleanup --dry-run` |
| 8 | Aufräumen – ausführen (mit Rückfrage) | `chatexporter cleanup` |
| 9 | Status und Übersicht | `chatexporter status` |
| 10 | Exporte erzeugen (Markdown und JSON, ohne Netz) | `chatexporter export` |
| 11 | ChatGPT: Diagnose | `chatexporter chatgpt doctor` |
| 12 | Zeitplanung: Aufgaben anzeigen | `chatexporter task list` |
| 13 | Zeitplanung: Aufgabe anlegen (täglich; fragt Name, Uhrzeit, Befehl) | `chatexporter task create <name> --daily <HH:MM> [--command "<befehl>"]` |
| 14 | Zeitplanung: Aufgabe pausieren (fragt die Aufgabe) | `chatexporter task pause <aufgabe>` |
| 15 | Zeitplanung: Aufgabe fortsetzen (fragt die Aufgabe) | `chatexporter task resume <aufgabe>` |
| 16 | Zeitplanung: Aufgabe löschen (mit Rückfrage) | `chatexporter task delete <aufgabe> --yes` |
| 17 | Konfiguration anzeigen (wirksame Werte und Herkunft) | `chatexporter config list` |
| 18 | Ablageorte anzeigen | `chatexporter config path` |
| 19 | Konfiguration neu laden (fehlende Datei anlegen) | `chatexporter config refresh` |
| 20 | Einrichtung (Browser/ChatGPT-Anmeldung, täglicher Abruf) | `chatexporter setup` |

Jeder Menüpunkt läuft als **eigener Prozess** (`python -m chatexporter …`).
So führt auch ein lange offenes Menü immer den aktuellen Code aus, und
Strg+C während eines Laufs beendet nur den Lauf, nicht das Menü.

`chatexporter --help` listet alle Befehle, `chatexporter --version` zeigt die
Version. `chatexporter --config <datei>` (ohne weiteren Befehl) öffnet das Menü
mit dieser Konfiguration.

## Raw Session Updater (alle aktiven Quellen)

Identisch als Einzelbefehl (`chatexporter-update`) oder als
`chatexporter update`.

### `chatexporter-update`

Aktualisiert alle aktiven Quellen (`raw_session_updater.sources`) nacheinander und schreibt
**einen** Laufbericht `.storage/runs/sync_<UTC>.json` (Schema 4).

| Option | Wirkung |
| --- | --- |
| `--source <quelle>` | nur diese Quelle(n); mehrfach angebbar |
| `--listing-mode auto\|full\|recent` | ChatGPT-Listing für diesen Lauf (überschreibt `sync.listing_mode`, Default `auto`; siehe [CHATGPT.md](providers/CHATGPT.md), Abschnitt 4) |
| `--no-files` | ChatGPT: keine Dateien/Anhänge laden |
| `--non-interactive` | ChatGPT: keine interaktive Anmeldung |

Optionen, die eine Quelle nicht kennt, werden für diese Quelle ignoriert.

Nach jeder Quelle zeigt die Konsole eine Zusammenfassung:
`--- Quelle <name>: ok | neu …, geaendert …, gespeichert …, fehlgeschlagen …, Dateien neu …, Anfragen … | Dauer … s`.
Darunter stehen bis zu 10 gespeicherte Einträge und bis zu 10 Fehler
namentlich; der Laufbericht enthält alle (`sources.<quelle>.items`).

**Strg+C** beendet die gerade laufende Quelle. Sie wird im Laufbericht als
abgebrochen vermerkt (`detail.abort_stage: interrupted`), und der Raw Session Updater macht
mit der nächsten Quelle weiter. Der Laufbericht wird in jedem Fall
geschrieben. Um alles abzubrechen, Strg+C bei jeder weiteren Quelle erneut
drücken.

### `chatexporter-index`

Baut `status_registry/storage_index.json` und `file_index.json` aus den
Fragmenten aller aktiven Quellen neu auf. Fail-closed: bei einem ungültigen
Fragment oder doppelten IDs bleibt der alte Index unverändert (Exit 2).

### `chatexporter-check`

Read-only-Prüfung jeder Quelle plus quellenübergreifende Regel: `raw_storage/` enthält
nur Quellen-Ordner. Optionen: `--deep` (hasht Inhalte, langsamer),
`--source`.

### `chatexporter-cleanup`

Entfernt nur definierte Reste (leere Library-Ordner, Staging-`.tmp`), niemals
Quelldaten. `--dry-run` zählt nur. Option `--source`.

### `chatexporter-status`

Momentaufnahme aller Quellen und `.storage/OVERVIEW.md` (Tabelle je Quelle,
letzte zehn Laufberichte). Option `--source`.

## ChatGPT: `chatexporter-chatgpt` (= `chatexporter chatgpt`)

Globale Optionen vor dem Befehl: `--config`, `--raw-root`.

| Befehl | Zweck |
| --- | --- |
| `update` (Alias `sync`) | Einzellauf: neue/geänderte Konversationen + Dateien laden; schreibt einen Laufbericht (Schema 4, nur `chatgpt`). Optionen wie `chatexporter-update` (`--listing-mode`, `--no-files`, `--non-interactive`) |
| `recreate-index` | Index-Fragment dieser Quelle (Vertrag; schreibt den Gesamtindex nicht) |
| `check-health` | Ablage prüfen; `--deep`, `--fail-on-warning` |
| `cleanup` | definierte Reste entfernen; `--dry-run` |
| `stats` | Momentaufnahme |
| `rebuild-index` | ChatGPT-Anteil des Gesamtindex direkt neu bauen (Einträge anderer Quellen bleiben) |
| `import-data --source <ordner>` | OpenAI-Kontodatenexport importieren (als unvollständig markiert, wird beim nächsten Update über die API vervollständigt); `--limit`, `--only-id`, `--overwrite-existing`, `--no-files`, `--report` |
| `doctor` | aufgelöste Konfiguration und Zustand der Ablage |
| `browser-setup [--neu]` | Browser und ChatGPT-Anmeldung einrichten bzw. prüfen (interaktiv, lädt keine Chats): mit eingetragenem Profil nur Anmeldeprüfung, sonst oder mit `--neu` die Suche mit Profilkopie (siehe [providers/CHATGPT.md](providers/CHATGPT.md), Abschnitt 2); ein dafür gestarteter Browser wird danach geschlossen. Exitcode `1`, wenn kein Weg funktioniert |
| `login [--profil DIR] [--schrittweise]` | Anmeldung prüfen und bei Bedarf automatisch anmelden (E-Mail, Passwort, Einmalcode aus der `.env`; siehe [providers/CHATGPT.md](providers/CHATGPT.md), Abschnitt 2a); `--profil` nutzt ein eigenes, z. B. leeres Datenverzeichnis; `--schrittweise` zeigt das Browserfenster, meldet vor jedem Schritt, was erkannt wurde und was als Nächstes geschieht, und führt ihn erst nach ENTER aus (am Ende bleibt der Browser bis ENTER offen). Lädt keine Chats; ignoriert einen Sperrvermerk nach abgelehnten Zugangsdaten |
| `migrate-store` | Statusablage und Datei-Referenzen nachziehen (idempotent, kein Netz, `raw` bleibt unverändert) |
| `migrate-layout` | einmalig: flache Ablage → `raw_storage/chatgpt/` + `.storage/`; `--dry-run` |
| `scenarios` | Mutationstests gegen eine **Kopie** des Bestands: `--source <raw_root> --work <kopie>` oder `--root <kopie>`, `--scenario`, `--keep-copy` |

Hinweis: `doctor`, `stats` und `rebuild-index` öffnen die Ablage mit der
üblichen Index-Selbstheilung. Ein veralteter ChatGPT-Anteil des Gesamtindex
kann dabei neu geschrieben werden.

## Exporter: `chatexporter-export` (= `chatexporter export`)

Erzeugt Markdown und JSON aus dem Raw Storage **aller Quellen** (ChatGPT,
OpenCode, Codex, Claude Code), ohne Netz und ohne Anmeldung. Liest
`raw_storage/<quelle>/` nur und schreibt ausschließlich nach `exports/`
(`<format>/<quelle>/<JJJJ-MM>/<id>.md|json`) plus ein Manifest unter
`exports/manifests/`. Exportiert werden die Texte von Benutzer und Assistent;
interne Denkinhalte und Werkzeugaufrufe der lokalen Quellen gehören nicht dazu.

```powershell
chatexporter export            # Formate laut exporter.formats (Standard: beide)
chatexporter export json       # nur JSON
chatexporter export md         # nur Markdown
chatexporter export all --source codex
```
Jedes Gespräch wird in jedem Format neu geschrieben (idempotent). Ein Update
erzeugt keine Exporte mehr; `export` läuft als eigener Befehl oder als eigene
geplante Aufgabe.

| Option | Wirkung |
| --- | --- |
| `json` / `md` / `all` | Format als erstes Argument (`md` = Markdown) |
| `--format markdown\|json` | nur dieses Format (mehrfach angebbar; Standard `exporter.formats`) |
| `--source chatgpt\|opencode\|codex\|claude` | nur diese Quelle (mehrfach; Standard `exporter.sources` = alle) |
| `--export-root <ordner>` | überschreibt `exporter.root` |
| `--raw-root <ordner>` | überschreibt `storage.raw_root` |
| `--config <datei>` | gemeinsame config.yaml |

Exitcodes: `0` ok, `1` einzelne Gespräche oder Formate fehlgeschlagen (z. B.
nicht lesbare Rohdatei), `2` Konfigurationsfehler. Am Ende steht ein
JSON-Bericht (Gespräche, geschriebene Dateien, Fehler, Pfad des Manifests).

## Konfiguration: `chatexporter-config` (= `chatexporter config`) und `chatexporter config-global`

`config` ändert die **Storage**-Konfiguration (`<storage>/.storage/config.yaml`),
`config-global` die **globale** `config.yaml`; anzeigen zeigen beide den
wirksamen Wert mit Herkunft.

| Befehl | Zweck |
| --- | --- |
| `config get [SCHLUESSEL]` | wirksamer Wert und Herkunft; ohne Schlüssel alle |
| `config list` | alle wirksamen Werte mit Herkunft |
| `config set SCHLUESSEL WERT` | Wert dauerhaft in die Storage-config.yaml schreiben (geprüft, mit Sicherung); nur-globale Schlüssel werden mit Hinweis auf `config-global` abgelehnt |
| `config reset SCHLUESSEL` / `config reset --all` | Wert in der Storage-Datei auskommentieren / Storage-Datei auf die Vorlage zurücksetzen |
| `config-global set|reset …` | dasselbe für die globale config.yaml |
| `config refresh` | neu laden, fehlende Dateien anlegen, Registry-Spiegel neu schreiben |
| `config path` | Ablageorte: globale Dateien, Storage (Ort, Format, Dateien, `state.yaml`), Registry |

Optionen `--config`, `--json`. Exitcodes `0` ok, `1` unbekannter Schlüssel
oder ungültiger Wert, `2` Dateifehler. Einzelheiten: [KONFIGURATION.md](KONFIGURATION.md).

## OpenCode, Codex, Claude: `chatexporter-opencode|codex|claude`

Die eigenständigen Kommandozeilen dieser Provider. Die Bedienschicht übergibt
automatisch die gefundene `config.yaml` (`--config`), sofern keine angegeben ist.

| Befehl | Zweck |
| --- | --- |
| `update [--dry-run]` | Quelle spiegeln; ohne `--dry-run` wird ein Laufbericht (Schema 4, nur diese Quelle) geschrieben |
| `recreate-index` | Fragment dieser Quelle |
| `check-health` | Ablage prüfen |
| `cleanup [--dry-run]` | definierte Reste entfernen |
| `stats` | Momentaufnahme |

Globale Optionen: `--config`, `--data-root`; Codex/Claude zusätzlich
`--source-root`, `--retries`, `--verify-unchanged`; OpenCode zusätzlich
`--opencode-exe`, `--db-path`, `--cli-cwd`, `--timeout`, `--retries`.

## Zeitplanung: `chatexporter-task` (= `chatexporter task`)

Befehle automatisch ausführen lassen, z. B. täglich `update`: Aufgaben der
Windows-Aufgabenplanung anlegen und verwalten. Voraussetzungen, alle Optionen,
Konfiguration und Grenzen: [TASK_SCHEDULER.md](task_scheduler/TASK_SCHEDULER.md).

| Befehl | Zweck |
| --- | --- |
| `task create NAME` | Aufgabe anlegen (`--command`, `--daily`/`--weekly --days`/`--once`/`--logon`/`--startup`, `--paused`, Einstellungen) |
| `task get REF` | eine Aufgabe anzeigen |
| `task list` | alle Aufgaben anzeigen |
| `task update REF` | Befehl, Zeitplan, Name, Beschreibung oder Einstellungen ändern |
| `task delete REF` | Aufgabe löschen (`-y` ohne Rückfrage) |
| `task delete --all` | alle eigenen Aufgaben löschen (z. B. vor der Deinstallation; `-y` ohne Rückfrage) |
| `task pause REF` / `task resume REF` | deaktivieren / wieder aktivieren |

Globale Optionen: `--config`, `--folder`, `--owner`, `--state-file`,
`--global-state-file`, `--python`, `--json`. Exitcodes: `0` ok, `1` fachlicher
Fehler (Aufgabe fehlt oder existiert, ungültige Eingabe), `2` Einrichtung
(keine config.yaml, pywin32 oder Windows fehlt).

## Einrichtung: `chatexporter setup`

Ersteinrichtung, auch am Ende der Installation gedacht. Drei Schritte, jeder
mit Rückfrage:

1. **Konfiguration:** config.yaml finden oder als vollständige Vorlage anlegen;
   Datenordner und aktive Quellen anzeigen.
2. **Browser und ChatGPT-Anmeldung** (nur wenn `chatgpt` aktiv ist): ohne
   eingetragenes Profil `chatgpt browser-setup`; mit eingetragenem Profil Auswahl
   prüfen / neu einrichten (`--neu`) / überspringen.
3. **Zeitplan:** tägliche Aufgabe `taeglich` (`update --non-interactive`,
   Uhrzeit wählbar, Standard 03:00) anlegen bzw. die Uhrzeit ändern.

Wiederholbar; nichts wird ohne Zustimmung geändert. Exitcode `1`, wenn der
Browser- oder Zeitplan-Schritt fehlschlägt. Gehört das Konsolenfenster nur
diesem Programm (Start über Installer oder Startmenü), wartet `setup` am Ende
auf Enter, damit die Zusammenfassung lesbar bleibt; ein unerwarteter Fehler wird
dann ebenfalls angezeigt, bevor sich das Fenster schließt.

## Storage: `chatexporter storage`

| Befehl | Zweck |
| --- | --- |
| `storage show [--json]` | gewählter Storage: Ort, Format (mit Begründung), Identität, wichtigste Zustandswerte, Pfade |
| `storage migrate [PFAD] [--dry-run] [--yes] [--fix-config]` | Storage-Schema 1 (Datenordner mit `runtime/`) auf Storage-Schema 2 umstellen |

`migrate` arbeitet nur, wenn die Marker Storage-Schema 1 eindeutig belegen oder
eine abgebrochene Umstellung erkennen lassen (sonst Exitcode `1`, nichts
verändert); eine abgebrochene Umstellung wird fortgesetzt. Schritte: `runtime/` → `.storage/`
umbenennen (atomar), Reste aus `.staging`-Ordnern nach `.storage/staging/`
einordnen (leere entfernen), zuletzt `storage.yaml` schreiben. Rohdaten werden
nicht angefasst. Zeigt eine Einstellung der globalen config.yaml noch in den
alten Ordner (z. B. `logging.dir: data/runtime/logs`), bricht `migrate` mit
Hinweis ab; `--fix-config` setzt solche Einstellungen vorher zurück (mit
Sicherung). `--dry-run` zeigt jeden Schritt, ohne etwas zu ändern.

## Deinstallation: `chatexporter uninstall`

- **Installiertes Programm:** startet die Deinstallation des Installers
  (`unins000.exe`): die Windows-Aufgaben aller bekannten Storages, Programmordner,
  Startmenü, PATH-Eintrag und Registry-Schlüssel `HKCU\Software\ChatExporter`
  werden entfernt. Ohne `--silent` fragt der Deinstallations-Assistent selbst nach.
- **Start aus dem Quellcode:** entfernt die Windows-Aufgaben aller bekannten
  Storages (gewählter Storage und alle in der Registry vermerkten) und den
  Registry-Schlüssel; das Paket selbst entfernt `pip uninstall chatexporter-gen4`.
- `uninstall --remove-tasks [--yes]`: nur die Aufgaben aller bekannten Storages
  entfernen (so ruft der Installer den Befehl bei der Deinstallation auf).

Konfiguration, `.env`, Daten und Protokolle werden **nie** gelöscht; der Befehl
nennt die Ordner. Optionen: `--yes` (ohne Rückfrage), `--silent` (ohne Fenster,
nur installiert). Exitcodes: `0` gestartet bzw. erledigt, `1` abgebrochen oder
Aufgaben nicht entfernbar, `2` keine Deinstallation gefunden / unbekannte Option.

## Werkzeuge außerhalb des Pakets

`tools/task_scheduler/scheduler_manager.py` ist die Grundlage der Zeitplanung
(siehe oben, nicht eigenständig aufzurufen; eigene CLI: `python
tools\task_scheduler\scheduler_manager.py -h`).
`tools/chatgpt/listing_params_probe.py` und
`tools/chatgpt/ratelimit_probe_listing.py` sind Messsonden für die Forschung
(echte Requests gegen ChatGPT, nur mit `--live`). Aufruf aus dem Codeordner:
`python tools\chatgpt\<datei>.py --config ..\config.yaml [--live]`.
`tools/chatgpt/browser_flow_lab.py` zeigt den Browser-/Profil-Ablauf Schritt
für Schritt (nur Entwicklung, siehe DEVELOPMENT_WORKSPACE.md).
