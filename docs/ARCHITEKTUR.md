# Architektur

Stand: pre-6 (Ist-Zustand, durch Tests belegt).

## 1. Leitidee

Der ChatExporter ist kein reiner ChatGPT-Exporter mehr, sondern ein
**Raw Session Updater über mehrere Quellen**. ChatGPT ist eine Quelle unter vieren –
die umfangreichste, aber strukturell gleichrangig.

Daraus folgen drei Schichten mit klaren Zuständigkeiten, dazu Exporter und Zeitplanung als eigenständige Module. Die Verantwortung des
Raw Session Updaters und der Provider endet, sobald die Daten im Raw Storage
angekommen sind; alles danach (Exporte) gehört dem Exporter.

| Schicht | Paket | Zuständig für | Nicht zuständig für |
| --- | --- | --- | --- |
| Bedienschicht | `chatexporter.cli` | Menü, Befehle, Verteilung an Raw Session Updater/Provider | jede Fachlogik |
| Raw Session Updater | `chatexporter.raw_session_updater` | alle aktiven Quellen nacheinander aufrufen, Gesamtindex zusammenführen, Laufbericht schreiben, quellenübergreifende Prüfregeln, Übersicht | wie eine Quelle ihre Daten holt oder speichert |
| Konfiguration | `chatexporter.config` (auf Basis von `layered_config`) | einzige Stelle für Quellen, Vorrang, Standards, Vorlage der config.yaml, `config`-Befehle und Registry-Spiegel ([KONFIGURATION.md](KONFIGURATION.md)) | Fachlogik einer Schicht |
| Exporter | `chatexporter.exporter` | den Raw Storage aller Quellen **lesen** und daraus abgeleitete Exporte (Markdown, JSON) nach `exports/` schreiben; Details: [BEFEHLE.md](BEFEHLE.md) | Daten holen, den Raw Storage verändern, Index, Laufberichte |
| Zeitplanung | `chatexporter.task_scheduler` | ChatExporter-Befehle als Windows-Aufgaben planen (anlegen, anzeigen, ändern, löschen, pausieren); Details: [TASK_SCHEDULER.md](task_scheduler/TASK_SCHEDULER.md) | Quelldaten, Gesamtindex, wie ein Befehl arbeitet |
| Provider | `chatexporter.providers.<quelle>` | Daten einer Quelle holen, in `raw_storage/<quelle>/` ablegen, Fragment liefern, eigene Ablage prüfen/bereinigen | andere Quellen, Gesamtindex-Merge, Menü |

Der frühere Begriff „Wrapper“ ist durch **Raw Session Updater** ersetzt: Die Schicht
aktualisiert die Rohdaten (Sessions) aller Quellen, nicht eine technische Hülle.

### Kernprinzipien

```text
API-AUFRUF != ABRUF != ROHDATEN-ZUSAMMENSETZUNG != RAW STORAGE != TRANSFORMATION != EXPORT
```

Jeder dieser Schritte hat eine eigene Verantwortung (aus pre-5 übernommen,
auf die Schichten von pre-6 abgebildet):

| Schritt | Verantwortlich | Regel |
| --- | --- | --- |
| API-Aufruf, Abruf, Zusammensetzen der Rohdaten | Provider (z. B. ChatGPT: `api/`, `fetch/`) | dünn und zustandsarm; Abruf besitzt Paginierung, Zusammenführung, Wiederholungslogik |
| Raw Storage | Provider schreibt, Raw Session Updater führt den Gesamtindex | Source of Truth; Rohdaten nie still verändern; der Index ist jederzeit neu aufbaubar |
| Transformation, Export | Exporter | liest nur den Raw Storage, verändert ihn nie; Exportfehler berühren nie einen Raw Commit |

Die Verantwortung von Raw Session Updater und Providern endet, sobald die Daten
im Raw Storage angekommen sind. Dateien einer Konversation werden unmittelbar
nach ihr geladen, damit ein unterbrochener Lauf vollständige Datensätze
hinterlässt statt Konversationen ohne jede Datei.

## 2. Abhängigkeitsregeln

```text
chatexporter.cli ──► chatexporter.raw_session_updater
        │                    │  (lädt Provider nur per Modulpfad-String,
        │                    │   ruft nur die 5 Vertragsfunktionen)
        └──────────────► chatexporter.providers.*
```

1. `raw_session_updater` importiert keinen Provider- und keinen CLI-Code.
2. `providers.chatgpt` importiert nur aus sich selbst – weder Raw Session Updater, CLI noch
   andere Provider.
3. `providers.opencode|codex|claude` importieren gar nichts aus `chatexporter`
   (eigenständige Einzeldateien).
4. `exporter` importiert nur aus sich selbst (und der Konfiguration, Regel 7). Er kennt den Raw Storage nur über
   dessen Dateiformat ([ABLAGE_UND_FORMATE.md](ABLAGE_UND_FORMATE.md)), nicht über Provider-Code.
5. `task_scheduler` importiert nur aus sich selbst (und der Konfiguration, Regel 7). Das Script
   `tools/task_scheduler/scheduler_manager.py` lädt es per Dateipfad zur
   Laufzeit, nicht per Import.
6. Nur `cli` darf alle Seiten kennen.
7. **Ausnahme Konfiguration:** Alle Schichten außer den Einzeldatei-Providern
   lesen ihre Einstellungen über `chatexporter.config`. Dieses importiert nur
   sich selbst und die projektunabhängige Bibliothek `layered_config`, die
   ihrerseits nichts aus `chatexporter` kennt ([CONFIG_BIBLIOTHEK.md](CONFIG_BIBLIOTHEK.md)).
   Die Einzeldatei-Provider (OpenCode, Codex, Claude) bekommen ihren Abschnitt
   weiterhin über das Vertrags-Mapping.

Die Regeln prüft `tests/test_independence.py` per Quelltextanalyse (AST).
Außerdem darf die Paketwurzel nur die Schichten (`cli`,
`raw_session_updater`, `providers`, `exporter`, `task_scheduler`, `config`) enthalten.

### Bewusste Duplikate

Wo Raw Session Updater und ChatGPT-Provider dieselbe Logik brauchen, existiert sie in
beiden – statt eines gemeinsamen Moduls, das eine Kopplung wäre:

| Logik | Raw Session Updater | ChatGPT-Provider | Gleichlauf gesichert durch |
| --- | --- | --- | --- |
| Config-Suche, Quellen, Vorrang | – zentral in `chatexporter.config` (seit 2026-10-02 keine Kopien mehr) | – | `tests/config/`, `tests/layered_config/` |
| Ablagepfade aus `storage` | `raw_session_updater/config.py` | `providers/chatgpt/storage/layout.py` + `config/loader.py` | `test_updater_and_chatgpt_resolve_same_paths` |
| Fragment-Regeln | `raw_session_updater/fragments.py` | `providers/chatgpt/storage/index.py` | `test_updater_and_chatgpt_fragment_rules_are_identical` |
| Aufbereitung der ChatGPT-Konversation zur neutralen Ansicht (aktueller Pfad, sichtbarer Text) | `exporter/sources/chatgpt.py` | `providers/chatgpt/fetch/validator.py` prüft nur die Graph-Vollständigkeit; die Darstellung liegt allein im Exporter | `tests/exporter/test_exporter_sources_formats.py` |
| Atomares Schreiben, Zeitstempel | `raw_session_updater/_io.py` | `providers/chatgpt/common/` | – (trivial) |
| Laufbericht Schema 4 | `raw_session_updater/manifest.py` | `providers/chatgpt/operations.py` (Einzellauf) | beide per Test auf Schema 4 geprüft |

Die eigenständigen Einzeldatei-Provider bringen ihre Hilfsfunktionen ebenfalls
selbst mit (so waren sie schon in pre-5 gebaut).

## 3. Datenfluss

### Alle Quellen aktualisieren (`chatexporter-update`)

```text
load_updater_config(config.yaml)            raw_session_updater/config.py
  └─ für jede aktive Quelle (nacheinander, nie parallel):
       mapping = provider_mapping(quelle)   Pfade + config_file + providers.<quelle>
       ergebnis = <quelle>.update(mapping, **optionen)
                  (Optionen, die der Provider nicht kennt, werden herausgefiltert)
  └─ build_run_manifest(ergebnisse)          EIN Laufbericht .storage/runs/sync_<UTC>.json
```

Ein Fehler in einer Quelle stoppt nicht die anderen: Die Quelle wird im
Laufbericht als fehlgeschlagen markiert, der Lauf gilt als `partial`, Exitcode 2.

### Exporte (`chatexporter-export`)

```text
load_exporter_config(config.yaml)           exporter/config.py
  └─ für jede Exportquelle (chatgpt, opencode, codex, claude):
       sources.iter_items(raw_root)         liest raw_storage/<quelle>/… (nur lesend)
         └─ neutrale Ansicht je Gespräch    exporter/sources/<quelle>.py
       formats.<markdown|json>.export(…)    schreibt exports/<format>/<quelle>/<JJJJ-MM>/<id>.<endung>
  └─ Manifest                                exports/manifests/export_<UTC>.json
```

Der Exporter ändert den Raw Storage nie und braucht weder Netz noch Anmeldung.
Ein Fehler bei einem Gespräch oder Format stoppt die übrigen nicht (Exitcode 1).
Ein Update (`chatexporter-update`) erzeugt keine Exporte; wer sie aktuell halten
will, plant `export` als eigene Aufgabe ([TASK_SCHEDULER.md](task_scheduler/TASK_SCHEDULER.md)).

### Gesamtindex (`chatexporter-index`)

Jede aktive Quelle liefert mit `recreate_index` ein **Fragment**. Der Raw Session Updater
prüft alle Fragmente streng. Erst wenn alle gültig sind und keine ID doppelt
vorkommt, schreibt es `storage_index.json` und `file_index.json` atomar.
Andernfalls bleibt der bisherige Index unverändert (fail-closed).

### ChatGPT-Provider im Einzellauf (`chatexporter-chatgpt update`)

Wie im Updater-Lauf, aber nur ChatGPT. Der Provider schreibt dann selbst einen
Laufbericht im selben Schema 4 (nur Quelle `chatgpt`), damit Einzel- und
Gesamtläufe gemeinsam ausgewertet werden können.

## 4. Konfiguration und Ort der Dateien

Der Codeordner enthält keine Konfiguration. Alle Schichten lesen dieselbe
`config.yaml` über `chatexporter.config`. Gefunden wird sie in dieser
Reihenfolge: `--config`, dann `CHATEXPORTER_CONFIG`, dann (nur beim Start aus
dem Quellcode) die erste `config.yaml` beim Aufstieg ab dem Arbeitsordner,
sonst `~/.chatexporter/config.yaml`; fehlt sie, wird die vollständige Vorlage
angelegt. Die Einzeldatei-Provider erhalten ihren Abschnitt über das
Vertrags-Mapping bzw. den gefundenen Pfad von der Bedienschicht. Details:
[KONFIGURATION.md](KONFIGURATION.md).

**Storage:** Programm und Datenhaltung sind getrennt. Der gemeinsame
Config-Kern bestimmt den gewählten Storage (`chatexporter.config.storage`:
Pfade, Marker, Formaterkennung, Sperre, Migration) und gibt dessen Wurzel allen
Schichten als `storage.data_root`; die Storage-`config.yaml` ist eine
zusätzliche Ebene der Konfiguration (Scope-Ebene von `layered_config`). Die
Bedienschicht prüft vor jedem Befehl den Storage, sperrt ihn für schreibende
Befehle und erzeugt danach Zustand (Registry) und `state.yaml`
(`cli/storage_state.py`). Konzept und Beschlüsse:
[STORAGE_KONZEPT.md](STORAGE_KONZEPT.md).

## 5. Wichtige Designentscheidungen

| Entscheidung | Begründung |
| --- | --- |
| Provider werden lazy per Modulpfad geladen | Ein defekter oder schwerer Provider (Browser-Stack) verhindert nicht den Start des Raw Session Updaters; der Raw Session Updater braucht keinen Provider-Import |
| Vertrags-Mapping statt Config-Objekt | Alle Provider erhalten dieselbe Eingabe; ChatGPT liest seine eigenen Einstellungen selbst aus `config_file` |
| Ablagepfade setzt immer der Raw Session Updater | Kein Provider kann versehentlich außerhalb von `raw_storage/<quelle>/` landen; `providers.<quelle>` kann `raw_root` usw. nicht überschreiben |
| Sequenziell, nie parallel | Rate-Limits, Staging-Kollisionen, Nachvollziehbarkeit |
| Duplikate statt gemeinsamer Hilfsmodule | Unabhängigkeit von Raw Session Updater und Provider hat Vorrang; Gleichlauf per Test |
| `chatgpt/__init__.py` lädt Vertragsfunktionen erst beim Zugriff | Import von Teilmodulen (z. B. `storage`) zieht nicht den Browser-Stack nach |
| Zeitplanung lädt `scheduler_manager.py` per Dateipfad und kopiert es nicht | Das Script bleibt die einzige Quelle der Windows-Logik und ist unabhängig davon testbar; ChatExporter hängt nur an seiner Schnittstelle (`PyTaskManager`) |
| Zeitplanung speichert den Plan (Befehl, Trigger, Einstellungen) im State der Aufgabe | `task update` kann die Aufgabe damit vollständig und identisch neu aufbauen |
| Automatische Fortsetzung liegt in der Bedienschicht (`cli/continuation.py`) | Nur die Bedienschicht darf Raw Session Updater und Zeitplanung kennen; der Updater meldet nur den Limit-Stopp im Laufbericht, die Bedienschicht plant daraus die Aufgabe |
| Exporter liest den Raw Storage direkt über dessen Dateiformat, nicht über einen Provider | Die Verantwortung der Provider endet im Raw Storage; der Exporter bleibt von Netz, Anmeldung und Provider-Code unabhängig und kann später Quellen mit eigenem Rohformat per Adapter (`exporter/sources/<quelle>.py`) aufnehmen |
| Menü übersetzt nur in Befehle | Menü und Befehlszeile verhalten sich garantiert gleich |
| Storage-Wurzel wird zentral als `storage.data_root` an alle Schichten gegeben | Die Schichten bleiben unabhängig voneinander und kennen nur ihre Pfade; der Storage-Umbau war additiv (nur `runtime` → `.storage`, `.staging` → `staging`) |
| Formaterkennung nur über eindeutige Marker, sonst nichts anfassen | Datenintegrität: ein unklarer Ordner wird nie verändert; Umstellung nur über `storage migrate` |
| Zustand lebt in der Registry, `state.yaml` wird nur geschrieben | Beschluss F6: Werte zentral und inkrementell änderbar, die Datei ist die Sicht von außen |

## 6. Grenzen (Ist-Zustand)

- Der Raw Session Updater validiert nur, was er selbst merged (Fragmente, Laufberichte);
  die fachliche Prüfung der Quelldaten liegt beim jeweiligen Provider.
- Relative Pfade in `providers.<quelle>` (z. B. `source_root`) reicht der
  Raw Session Updater unverändert weiter; absolute Pfade sind empfohlen.
- `raw_session_updater.sources` steuert, welche Quellen `update`, `index`, `check`,
  `cleanup` und `status` ohne `--source` bearbeiten. Der Gesamtindex enthält
  nur die aktiven Quellen.
