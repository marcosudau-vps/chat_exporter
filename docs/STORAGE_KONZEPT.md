# Storage – Konzept

> **Status: BESCHLOSSEN UND UMGESETZT (2026-10-03).** Dieses Dokument hält
> Idee, Beschlüsse und Begründungen fest. Den Ist-Zustand beschreiben
> [KONFIGURATION.md](KONFIGURATION.md), [ABLAGE_UND_FORMATE.md](ABLAGE_UND_FORMATE.md)
> und [BEFEHLE.md](BEFEHLE.md); Stand der Umsetzung: Abschnitt 9.

## 1. Idee

Programm und Daten werden in der **Datenhaltung** getrennt (nicht unbedingt
physisch). Eine Programminstallation hat nicht mehr *den* Datenordner, sondern
kennt beliebig viele **Storages**. Der Storage im Home-Ordner `~/.chatexporter`
ist nur der **Standard-Storage**.

**Storage** (fester Begriff) = eine autarke Dateninstanz mit

- eigenen Daten (Rohdaten, Exporte),
- eigenem Zustand (State, Metadaten, Protokolle),
- eigener Konfiguration (inklusive eigener `.env`),
- eigenem Bereich in der Registry.

„Autark“ heißt: Ein Storage-Ordner enthält alles Fachliche, um ihn zu
verstehen, zu prüfen und weiterzuführen.

## 2. Bestandsaufnahme (Stand vor dem Umbau, pre-6)

| Was | Heute | Konfiguration |
| --- | --- | --- |
| Konfiguration | `<home>/config.yaml` (installiert `~/.chatexporter`), Entwicklung `workspace/config.yaml` | Suche: `--config` > `CHATEXPORTER_CONFIG` > Arbeitsordner (nur Quellcode) > Home |
| Secrets | `.env` neben der config.yaml | `bootstrap.env_file` |
| Datenordner | `<home>/data` | `storage.data_root` |
| Rohdaten | `<data>/raw_storage/<quelle>/` | `storage.raw_root` |
| Betriebsablage | `<data>/runtime/` (Laufberichte `runs/`, Statusablage `status_registry/`, `OVERVIEW.md`, Staging `.staging/`) | `storage.runtime_root`, `storage.status_root` |
| Exporte | `<data>/exports/` mit eigener `.staging/` | `exporter.root` |
| Befehlsprotokoll | `<home>/logs/` (Entwicklung: `data/runtime/logs`) | `logging.dir` |
| Aufgaben-State | lokal `<data>/runtime/tasks_sched.json`, global `%LOCALAPPDATA%\PyTaskManager\tasks_sched.json` | `task_scheduler.state_file`, `.global_state_file` |
| Browser-Profile | `<home>/browser/` (seit Nachtrag (8)) | – |
| Registry-Spiegel | `HKCU\Software\ChatExporter\config\Current` (nur schreibend) | – |

Befund: Konfiguration, Protokolle und Browser hängen am **Programm-Home**,
Daten und Betriebsablage am **Datenordner**. Zustand ist über viele Dateien
verteilt; eine zusammenfassende Sicht gibt es nur als `OVERVIEW.md`.

## 3. Beschlüsse (2026-10-03)

| Nr. | Thema | Beschluss |
| --- | --- | --- |
| F1 | Ort des Standard-Storages | `~/.chatexporter/storages/default` |
| F2 | Konfiguration | Die `config.yaml` im Storage ist eine **zusätzliche, spezifischere Ebene** der normalen Hierarchie; die `config.yaml` im Home liefert die Grundwerte. Im Storage werden nur `config.yaml` und `.env` gelesen (dort kann der Benutzer etwas eingeben); Zustands- und Protokolldateien sind reine Ausgaben |
| F3 | Staging | je Storage in `.storage/staging/`; leere Ordner werden nach Gebrauch entfernt |
| F4 | Browser-Profil | **global** (`~/.chatexporter/browser/`), nicht im Storage. An einer Lösung mit Token/Cookie wird getrennt gearbeitet |
| F5 | Entstehung, Übernahme | kein `storage create` (vorerst der Standard-Storage bzw. ein per Pfad gewählter); **Migrationsbefehl** für das alte Layout, Erkennung nur über eindeutige Marker |
| F6 | State | Die Werte **leben in der Registry** (Bereich des Storages); `state.yaml` wird daraus erzeugt und nie gelesen (Sonderfall Wiederherstellung später). `state.yaml` enthält **alles** Relevante: Basisinformationen, aufgelöste Konfiguration, Metadaten, Zustand – für den Blick von außen |
| F7 | Automatische Anmeldung | damals separat entwickelt; seit 2026-10-05 übernommen: Zugangsdaten aus der globalen oder der Storage-`.env` bzw. der Umgebung (nie aus einer config.yaml), Sperrvermerk in `.storage/auth/auto_login_block.json`, Browser bleibt global (F4) |
| F8 | Gleichzeitige Läufe | verschiedene Storages ja; je Storage höchstens ein schreibender Lauf (`.storage/lock`) |
| F9 | Namen | `config.yaml` in beiden Ebenen. `config set/reset` ändern die Storage-`config.yaml`; neu `config-global set/reset/…` für `~/.chatexporter/config.yaml` |

Auslegung (vom Assistenten festgelegt, Einspruch möglich):

- „Nur `config.yaml` und `.env` werden gelesen“ gilt für Informations- und
  Protokolldateien (`state.yaml`, Logs). Betriebsdateien (Index, Statusablage,
  Aufgaben-State) liest das Programm weiter – ohne sie kein Update. Zusätzlich
  wird `.storage/storage.yaml` gelesen: der einmal geschriebene **Marker** mit
  Storage-Schema (`storage_schema`) und Storage-ID (Schlüssel des Registry-Bereichs).
- Browser-Einstellungen (`providers.chatgpt.browser.*`) und
  Programm-Einstellungen (`bootstrap.*`, `storage.root`,
  `task_scheduler.python/manager_script/global_state_file`) sind **nur global**;
  in einer Storage-`config.yaml` werden sie mit Hinweis ignoriert.

## 4. Aufbau

```text
~/.chatexporter/                         Programm-Home
├── config.yaml                          globale Konfiguration (Grundwerte, Browser, Programm)
├── .env                                 globale Secrets/Overrides
├── browser/                             Browser-Profile (global, F4)
└── storages/default/                    Standard-Storage (F1)
    ├── .storage/                        Verwaltungsbereich (bisher „runtime“)
    │   ├── storage.yaml                 Marker: storage_schema, ID, Name, Anlagezeitpunkt (einmal geschrieben)
    │   ├── config.yaml                  Storage-Konfiguration (gelesen)
    │   ├── .env                         Storage-Secrets (gelesen)
    │   ├── state.yaml                   Gesamtsicht, aus der Registry erzeugt (nur geschrieben)
    │   ├── logs/                        Befehlsprotokoll dieses Storages
    │   ├── runs/                        Laufberichte (Update-Protokolle)
    │   ├── status_registry/             Statusablage, Gesamtindex
    │   ├── tasks_sched.json             Aufgaben-State dieses Storages
    │   ├── OVERVIEW.md                  Übersicht
    │   ├── staging/                     Zwischenablage (leere Ordner werden entfernt, F3)
    │   └── lock                         Sperre für schreibende Läufe (F8)
    ├── raw_storage/<quelle>/            Rohdaten
    └── exports/                         Exporte (abgeleitet)
```

Ein Storage kann auch anderswo liegen (`--storage PFAD`).

## 5. Konfiguration

Vorrang (spezifischer gewinnt):

```text
Standard < ~/.chatexporter/config.yaml < ~/.chatexporter/.env
        < <storage>/.storage/config.yaml < <storage>/.storage/.env
        < Umgebung < --set SCHLUESSEL=WERT
```

- Auswahl des Storages: `--storage PFAD` > `CHATEXPORTER_STORAGE` > `storage.root`
  der globalen Konfiguration (Standard `storages/default`, relativ zum Home).
- Relative Pfade in der Storage-`config.yaml` gelten relativ zum Storage-Ordner.
- `config set|reset` → Storage-`config.yaml`; `config-global set|reset` → globale
  `config.yaml`; `config get|list` zeigen den wirksamen Wert mit Herkunft (Ebene).
- Fehlt die Storage-`config.yaml`, wird sie als vollständige, auskommentierte
  Vorlage (nur Storage-taugliche Schlüssel) angelegt.

## 6. Registry und State (F6)

```text
HKCU\Software\ChatExporter\Storages\<storage-id>\
    Path, Name                           wo der Storage liegt
    Config\Current                       Spiegel der wirksamen Konfiguration (nur schreibend, ohne Secrets)
    State                                Zustandswerte (gelesen und geschrieben; Quelle von state.yaml)
```

`state.yaml` (nur geschrieben, nach jedem Befehl auf dem Storage neu erzeugt):

- `storage`: ID, Name, Storage-Schema, Pfad, angelegt am, Programmversion
- `state`: alle Zustandswerte aus der Registry (Abschnitt 7)
- `config`: wirksame Konfiguration mit Herkunft je Schlüssel, Secrets nur als „gesetzt ja/nein“
- `paths`: alle aufgelösten Ablageorte

Secrets erscheinen weder in der Registry noch in `state.yaml` noch in Protokollen.

## 7. Zustandswerte

| Schlüssel | Bedeutung | aktualisiert bei |
| --- | --- | --- |
| `storage.storage_schema`, `.created_at`, `.id`, `.name` | Identität (auch in `storage.yaml`) | Anlage/Migration (gespiegelt bei jedem Befehl) |
| `storage.root`, `.program_version` | Ort des Storages, Programmversion des letzten Befehls | jedem Befehl |
| `storage.last_command`, `.last_command_at`, `.last_command_exit` | letzter Befehl (Werte geheimer Schlüssel aus `--set` verdeckt), Zeitpunkt, Exitcode | jedem Befehl |
| `storage.update_counter` | Anzahl Updates | jedem `update` |
| `storage.update_last`, `.update_last_result` | Zeitpunkt und Ergebnis des letzten Updates | jedem `update` |
| `storage.update_next_scheduled_at` | nächster geplanter Lauf (aus der Windows-Aufgabe) | Aufgabe angelegt/geändert, `update` |
| `storage.first_fetch.completed`, `.completed_at` | erster vollständiger Abruf aller aktiven Quellen | `update` |
| `storage.first_fetch.parts_completed`, `.parts_total` | Teilläufe bis dahin; `parts_total` ist eine **Schätzung** | `update` mit Rate-Limit-Stopp |
| `providers.<quelle>.enabled` | aktiv (Konfiguration, zur Übersicht gespiegelt) | jedem Befehl |
| `providers.<quelle>.update_last`, `.update_last_result` | letztes Update der Quelle | `update` |
| `providers.<quelle>.total_sessions`, `.total_files` | Bestand | `update`, `status`, `index` |

`storage.update_daily_enabled/_time` sind Konfiguration (Soll) und stehen in
`state.yaml` im Abschnitt `config`; der Ist-Zustand ist `update_next_scheduled_at`.
Eigene Zustandswerte zur automatischen Anmeldung gibt es nicht; ihr Ergebnis steht im Laufbericht.

## 8. Formaterkennung und Migration (F5)

| Format | Marker (alle müssen zutreffen) |
| --- | --- |
| **Storage-Schema 2** | `.storage/storage.yaml` lesbar, mit `storage_schema: 2` und `id` |
| **Storage-Schema 1** | kein `.storage/`; `runtime/` vorhanden mit `runs/` oder `status_registry/`; `raw_storage/` vorhanden |
| **Umstellung abgebrochen** | `.storage/` ohne gültige `storage.yaml`, aber mit `runs/` oder `status_registry/`; `raw_storage/` vorhanden; kein `runtime/` |
| **leer** | Ordner fehlt oder ist leer (nur Systemdateien wie `desktop.ini`, `Thumbs.db`) |
| **fremd** | Ordner ist nicht leer, enthält aber keinen der Ordner `.storage/`, `runtime/`, `raw_storage/` |
| **unklar** | alles andere (z. B. `.storage/` ohne gültige `storage.yaml` und ohne Betriebsdaten, oder `.storage/` **und** `runtime/`) → Abbruch mit Erklärung, nichts wird verändert |

- Leer → wird beim ersten Gebrauch mit Storage-Schema 2 angelegt.
- Fremd → wird abgelehnt, nichts angelegt (Entscheidung 2026-10-05; vorher wurde
  ein solcher Ordner zum Storage gemacht). Fremde Dateien **in** einem bestehenden
  Storage bleiben erlaubt.
- Umstellung abgebrochen → jeder Befehl verweigert mit Hinweis; `storage migrate`
  setzt fort (Staging einordnen, Marker schreiben; neue ID).
- Alt → jeder Befehl verweigert mit Hinweis auf `chatexporter storage migrate`.
- `storage migrate [--dry-run]`: benennt `runtime/` in `.storage/` um (gleiches
  Laufwerk, atomar), verlegt Reste aus `.staging`-Ordnern nach
  `.storage/staging/` (leere werden entfernt), schreibt `storage.yaml` zuletzt
  (erst dann gilt der Ordner als Storage-Schema 2). Rohdaten werden nicht angefasst.
  Der Probelauf zeigt jeden Schritt. Bricht die Umstellung nach dem Umbenennen ab,
  setzt ein erneuter Aufruf fort; jeder Schritt ist wiederholbar.
- Ältere Ordner (z. B. `~/.chat_exporter/data`) verschiebt der Benutzer selbst
  an den gewünschten Ort und migriert ihn dann.

## 9. Bauplan

| Phase | Inhalt | Stand |
| --- | --- | --- |
| A | `layered_config`: zusätzliche Ebene „Scope“ (Datei + `.env`), nur-global-Einstellungen, Bearbeiten je Ebene, Spiegel je Scope | umgesetzt (`layered_config.Scope`, Tests `test_lc_scope.py`) |
| B | `chatexporter.storage`: Storage-Objekt mit allen Pfaden, Marker, Formaterkennung, Auswahl (`--storage`, `CHATEXPORTER_STORAGE`, `storage.root`); alle Schichten beziehen Pfade daraus | umgesetzt (`chatexporter/config/storage.py`; Formaterkennung, Anlage, `--storage`; Schutz alter Ordner) |
| C | Staging nach `.storage/staging/` mit Aufräumen; Sperre `.storage/lock` | umgesetzt (Aufräumen nach jedem Befehl; Sperre mit `lock.json`) |
| D | Registry je Storage (Spiegel, State), `state.yaml`, Zustandswerte aus Updates | umgesetzt (`config/state.py`, `cli/storage_state.py`) |
| E | Aufgaben je Storage (Eigentümer, `--storage` im Befehl), `uninstall` über alle bekannten Storages, `config-global` | umgesetzt (`--storage` und Eigentümer je Storage; `uninstall --remove-tasks`; `config-global`) |
| F | `storage migrate` / `storage show`; Test mit Kopien echter Bestände | umgesetzt; Probe auf einer Kopie erfolgreich; Entwicklungsbestand am 2026-10-03 nach ZIP-Sicherung umgestellt |
| G | Doku als Ist-Zustand, Installer, Build | Doku nachgezogen; Installer neu gebaut |

## 10. Versionierung (Storage-Schema)

Beschluss vom 2026-10-03: Das Format des Datenbestands ist als **Storage-Schema**
versioniert, mit eigener Zählung, die nie mit der Programmversion verwechselt
werden darf (Schreibweise „Storage-Schema N“, `storage-schema-N`,
`storage_schema: N`). Storage-Schema 1 ist der Datenordner mit `runtime/`,
Storage-Schema 2 der hier beschriebene Aufbau. Je Storage-Schema gibt es ein
eigenständiges Dokument unter [storage_schema/](storage_schema/README.md); vor jeder
Umstellung wird der Bestand im alten Storage-Schema als ZIP unter
`workspace/.archiv/storage_schema/` gesichert.
