# Storage-Schema 2

> **Storage-Schema 2** bezeichnet das **Format des Datenbestands** (Verzeichnisaufbau,
> Dateien, Bezeichnungen, Regeln). Die Nummer ist eine eigene Zählung und hat
> **nichts mit der Programmversion** (z. B. `0.0.0.dev6`) zu tun. Schreibweise:
> in Texten „Storage-Schema 2“, in Dateinamen und Kennungen `storage-schema-2`,
> im Marker `storage_schema: 2`.

---

## Teil A – Übersicht

### Verzeichnisbaum

```text
<storage>/                                   ein Storage (Standard: ~/.chatexporter/storages/default)
├── .storage/                                Verwaltungsbereich: keine Quelldaten
│   ├── storage.yaml                         Marker: storage_schema, id, name, created_at (einmal geschrieben)
│   ├── config.yaml                          Storage-Konfiguration (gelesen)
│   ├── .env                                 Storage-Secrets (gelesen, optional)
│   ├── .config_backups/                     Sicherungen der config.yaml vor jeder Änderung
│   ├── state.yaml                           Gesamtsicht (nur geschrieben)
│   ├── logs/commands_<UTC>.jsonl            Befehlsprotokoll
│   ├── runs/sync_<UTC>.json                 Laufberichte (Laufbericht-Schema 4)
│   ├── status_registry/
│   │   ├── storage_index.json               Gesamtindex aller Quellen
│   │   ├── file_index.json                  Rückwärtsindex Datei → Konversation/Nachricht
│   │   ├── file_status.json                 Dateistatus (z. B. UNAVAILABLE nach HTTP 404)
│   │   └── quarantine.json                  ChatGPT-Quarantäne (nur wenn Einträge bestehen)
│   ├── tasks_sched.json                     lokaler State der geplanten Aufgaben (falls angelegt)
│   ├── OVERVIEW.md                          generierte Übersicht
│   ├── staging/                             Zwischenablage für atomares Schreiben (leere Ordner werden entfernt)
│   │   ├── conversations/ library/ runs/    ChatGPT
│   │   ├── opencode/ codex/ claude/         lokale Quellen
│   │   ├── exports/                         Exporter
│   │   └── index/<quelle>.fragment.json     Index-Fragmente
│   ├── lock                                 Sperre für schreibende Läufe
│   └── lock.json                            Inhaber der Sperre (nur während eines Laufs)
├── raw_storage/                             Quelldaten; enthält nur Quellen-Ordner
│   ├── chatgpt/
│   │   ├── conversations/<JJJJ>/<MM>/<TT>/<conversation_id>.json    Envelope je Konversation
│   │   └── library/
│   │       ├── files/<file_id>/             content.<ext> + metadata.json
│   │       └── audio/<file_id>/             Sprachaufnahmen (content.<ext> + metadata.json)
│   ├── opencode/sessions/<JJJJ>/<MM>/<TT>/<session_id>.json         Export je Sitzung
│   ├── codex/sessions/<JJJJ>/<MM>/<TT>/rollout-….jsonl              bytegetreue Spiegelung
│   └── claude/projects/<projektordner>/<session_id>.jsonl           bytegetreue Spiegelung (+ Artefakte)
└── exports/                                 Exporte (abgeleitet, jederzeit neu erzeugbar)
    ├── <format>/<quelle>/<JJJJ-MM>/<id>.<ext>
    └── manifests/export_<UTC>.json

Registry: HKCU\Software\ChatExporter\Storages\<id>\  Path, Name · Config\Current · State
```

### Wichtigste Fakten und Regeln

- **Storage** = autarke Dateninstanz mit eigenen Daten, eigenem Zustand, eigener
  Konfiguration und eigenem Registry-Bereich. Ein Programm kann mehrere Storages
  kennen; gewählt wird mit `--storage PFAD`, `CHATEXPORTER_STORAGE` oder `storage.root`.
- **Erkennung nur über den Marker:** `.storage/storage.yaml` mit
  `storage_schema: 2` und `id`. Ohne gültigen Marker wird ein Ordner nicht als
  Storage-Schema 2 behandelt.
- **Gelesen werden im Verwaltungsbereich** nur `storage.yaml`, `config.yaml`,
  `.env` und die Betriebsdateien (Index, Statusablage, Aufgaben-State).
  `state.yaml`, Logs und Laufberichte sind reine Ausgaben.
- **Konfiguration in Ebenen:** Standard < globale `config.yaml` < globale `.env`
  < Storage-`config.yaml` < Storage-`.env` < Umgebung < `--set`. Programm-, Orts-
  und Browser-Einstellungen gelten nur global.
- **Zustand lebt in der Registry** (`Storages\<id>\State`); `state.yaml` wird nach
  jedem Befehl daraus erzeugt und zeigt Identität, Zustand, wirksame
  Konfiguration mit Herkunft und alle Pfade. Secrets erscheinen nie.
- **Sperre:** höchstens ein schreibender Lauf je Storage (`.storage/lock`).
- **Atomar:** Jede Datei wird erst in `.storage/staging/` vollständig geschrieben
  und dann per Umbenennen an ihren Platz gesetzt; leere Zwischenablage-Ordner
  werden nach jedem Befehl entfernt.
- **Quelldaten sind unantastbar:** `raw_storage/<quelle>/` schreibt nur die
  jeweilige Quelle; der Inhalt `raw` eines ChatGPT-Envelopes wird nie verändert.
- **Aufgaben gehören einem Storage:** Befehl mit `--storage <storage>`,
  Eigentümer `chatexporter-<erste 8 Zeichen der ID>`.

---

## Teil B – Vollständige Dokumentation

### 1. Begriffe

| Begriff | Bedeutung |
| --- | --- |
| Storage | autarke Dateninstanz; Wurzelordner mit `.storage/`, `raw_storage/`, `exports/` |
| Standard-Storage | `~/.chatexporter/storages/default` |
| Verwaltungsbereich | `.storage/`: Marker, Konfiguration, Zustand, Protokolle, Betriebsdateien |
| Marker | `.storage/storage.yaml`: Kennzeichen des Formats und Identität |
| Storage-Konfiguration | `.storage/config.yaml` und `.storage/.env` |
| Globale Konfiguration | `config.yaml` und `.env` des Programms (z. B. `~/.chatexporter/`) |
| Zustand | Zustandswerte in der Registry (`Storages\<id>\State`) |
| Gesamtsicht | `.storage/state.yaml` |
| Sperre | `.storage/lock` (+ `lock.json`) |
| Raw Storage | `raw_storage/`: Quelldaten aller Quellen |
| Quelle | `chatgpt`, `opencode`, `codex`, `claude`; je Quelle ein Ordner in `raw_storage/` |
| Statusablage | `.storage/status_registry/` |
| Zwischenablage | `.storage/staging/` |
| Laufbericht | `.storage/runs/sync_<UTC>.json` |
| Envelope | Datei je ChatGPT-Konversation mit Rohdaten und abgeleiteten Angaben |
| Fragment | Index-Anteil einer Quelle |
| Exporte | `exports/`: aus dem Raw Storage erzeugte Markdown-/JSON-Dateien |

### 2. Erkennung und Anlage

| Fall | Bedingung | Verhalten |
| --- | --- | --- |
| Storage-Schema 2 | `.storage/storage.yaml` lesbar, `storage_schema: 2`, `id` vorhanden; kein Ordner `runtime/` | wird benutzt |
| leer | Ordner fehlt oder ist leer (nur Systemdateien wie `desktop.ini`, `Thumbs.db`) | wird beim ersten Gebrauch als Storage-Schema 2 angelegt (Marker, Storage-Konfiguration als Vorlage) |
| fremd | Ordner ist nicht leer, ohne `.storage/`, `runtime/`, `raw_storage/` | wird abgelehnt und nicht verändert (seit 2026-10-05) |
| Umstellung abgebrochen | `.storage/` ohne gültigen Marker, mit `runs/` oder `status_registry/`, dazu `raw_storage/`, ohne `runtime/` | wird von keinem Befehl verändert; `storage migrate` setzt die Umstellung fort |
| anderes | jeder andere Zustand | wird von keinem Befehl verändert; der Befehl endet mit Exitcode 2 und Begründung |

Fremde Dateien im Storage-Ordner (z. B. HTML-Betrachter, Notizen) sind erlaubt
und gehören nicht zum Format.

### 3. Marker `.storage/storage.yaml`

```yaml
# ChatExporter-Storage – Marker (storage_schema = Storage-Schema, nicht Programmversion). Nicht aendern.
storage_schema: 2
id: 97087dbd1ab44839b3a27577250407cb      # 32 Hex-Zeichen, zufällig, unveränderlich
name: default                              # Ordnername bei der Anlage
created_at: '2026-10-03T10:38:44Z'         # UTC
```

Wird einmal (atomar) geschrieben und danach nur gelesen. Die `id` ist der
Schlüssel des Registry-Bereichs und Teil des Eigentümers der Aufgaben.

### 4. Konfiguration

#### 4.1 Ebenen

```text
Standard < globale config.yaml < globale .env
        < .storage/config.yaml < .storage/.env
        < Umgebungsvariable < --set SCHLUESSEL=WERT
```

- Die Storage-`config.yaml` wird beim Anlegen als vollständige Vorlage erzeugt:
  jede zulässige Einstellung als auskommentierte Zeile, Standardwerte echt,
  sonst als `BEISPIEL` markiert.
- **Nur global** (in der Storage-Datei mit Hinweis ignoriert): `bootstrap.*`,
  `storage.root`, `storage.data_root`, `providers.chatgpt.browser.*`,
  `task_scheduler.python`, `task_scheduler.manager_script`,
  `task_scheduler.global_state_file`.
- Relative Pfade gelten relativ zum Ordner der Datei, aus der sie stammen
  (Storage-Werte relativ zum Storage-Ordner).
- Secrets nur in einer `.env` oder der Umgebung.
- `chatexporter config set|reset` ändern `.storage/config.yaml`,
  `chatexporter config-global set|reset` die globale Datei; vor jeder Änderung
  entsteht eine Sicherung in `.config_backups/` neben der Datei.

#### 4.2 Abgeleitete Orte

| Ort | Standard | abweichend einstellbar über |
| --- | --- | --- |
| Raw Storage | `<storage>/raw_storage` | `storage.raw_root` |
| Verwaltungsbereich | `<storage>/.storage` | `storage.runtime_root` |
| Statusablage | `<storage>/.storage/status_registry` | `storage.status_root` |
| Exporte | `<storage>/exports` | `exporter.root` |
| Befehlsprotokoll | `<storage>/.storage/logs` | `logging.dir` |
| Aufgaben-State | `<storage>/.storage/tasks_sched.json` | `task_scheduler.state_file` |
| Zwischenablage | `<storage>/.storage/staging` | – |

Abweichende Orte sind möglich, aber nicht empfohlen: Der Storage ist nur dann
autark, wenn alles unter seinem Ordner liegt.

### 5. Registry

```text
HKEY_CURRENT_USER\Software\ChatExporter\Storages\<id>\
    Path                  Ordner des Storages
    Name                  Name aus dem Marker
    Config\Current        Spiegel der wirksamen Konfiguration: je Einstellung ein Wert; ohne Secrets
    Config                config_file, scope_config_file, written_at
    State                 Zustandswerte: je Wert ein Eintrag, Inhalt JSON
```

- `Config\Current` wird nach jedem erfolgreich angewendeten Laden oder Ändern
  geschrieben, nie vorher, und nie gelesen.
- `State` wird gelesen und geschrieben (Quelle der Zustandswerte).

#### 5.1 Zustandswerte (`State`)

| Schlüssel | Bedeutung | aktualisiert |
| --- | --- | --- |
| `storage.id`, `.name`, `.storage_schema`, `.created_at`, `.root` | Identität und Ort | jeder Befehl |
| `storage.program_version` | Programmversion des letzten Befehls | jeder Befehl |
| `storage.last_command`, `.last_command_at`, `.last_command_exit` | letzter Befehl, Zeitpunkt, Exitcode | jeder Befehl |
| `storage.update_counter` | Anzahl der Updates | `update` |
| `storage.update_last`, `.update_last_result` | Zeitpunkt, Ergebnis (`ok` \| `teilweise` \| `fehler`) | `update` |
| `storage.update_next_scheduled_at` | nächster geplanter `update`-Lauf | `update`, `task`, `setup` |
| `storage.first_fetch.completed`, `.completed_at` | erster vollständiger Abruf aller aktiven Quellen | `update` |
| `storage.first_fetch.parts_completed`, `.parts_total` | Teilläufe bis dahin; `parts_total` ist eine Schätzung | `update` |
| `providers.<quelle>.enabled` | Quelle aktiv | jeder Befehl |
| `providers.<quelle>.update_last`, `.update_last_result` | letztes Update der Quelle | `update` |
| `providers.<quelle>.total_sessions`, `.total_files` | Bestand (Sitzungen/Konversationen; Dateien inkl. Artefakte) | jeder Befehl |

### 6. Gesamtsicht `.storage/state.yaml`

Nach jedem Befehl auf dem Storage neu erzeugt (atomar), nie gelesen:

```yaml
# Kopfzeilen: vom Programm erzeugt, Quelle Registry, wird nie gelesen
generated_at: '…'
storage: { storage_schema: 2, id: …, name: …, created_at: …, root: …, program_version: … }
state:                     # Zustandswerte aus der Registry, verschachtelt
  storage: { … }
  providers: { chatgpt: { … }, opencode: { … }, codex: { … }, claude: { … } }
config:                    # jede Einstellung: wirksamer Wert und Herkunft
  <schlüssel>: { value: …, origin: default|config|.env|storage|storage .env|env|cli|storage.root }
config_files: { global: …, storage: …, storage_env_present: true|false }
paths: { root, meta, config_file, env_file, state_file, logs_dir, runs_dir, status_dir,
         tasks_state, staging, lock_file, raw_root, exports_root }
```

Secrets erscheinen nur als `(gesetzt)` bzw. `(nicht gesetzt)`.

### 7. Raw Storage

#### 7.1 ChatGPT – Konversationen

Pfad: `raw_storage/chatgpt/conversations/<JJJJ>/<MM>/<TT>/<conversation_id>.json`
(Datum = Erstellungsdatum der Konversation). Inhalt (Envelope):

| Feld | Inhalt |
| --- | --- |
| `storage_schema_version` | `1` – **Formatversion des Envelopes** (Name historisch; bezeichnet nicht das Storage-Schema) |
| `provider`, `conversation_id` | `chatgpt`, ID |
| `remote_summary` | Listing-Daten: Titel, Zeiten, Archiv-/Stern-Status, `gizmo_id`, … |
| `acquisition` | `json_complete`, `files_complete`, `complete`, `source` (`api` \| `imported_data`), Zeitpunkt, Graph-Kennzahlen, Warnungen |
| `raw` | unveränderte API-Antwort (Nachrichtengraph) |
| `textdocs` | Canvas-Dokumente |
| `file_references`, `tool_references` | abgeleitete Verweise mit `message_id`/`node_id` |
| `integrity.raw_payload_sha256` | SHA-256 über `raw` (kanonisches JSON) |

`raw` wird nie verändert; alle anderen Felder sind abgeleitet und lassen sich
mit `chatexporter chatgpt migrate-store` neu berechnen.

#### 7.2 ChatGPT – Dateien

`library/files/<file_id>/` und `library/audio/<file_id>/` enthalten je
`content.<ext>` und `metadata.json`; unter `_local` steht die Herkunft
(`conversation_id`, `message_id`, `node_id`, `references[]`).

#### 7.3 Lokale Quellen

| Quelle | Pfad | Inhalt |
| --- | --- | --- |
| `opencode` | `opencode/sessions/<JJJJ>/<MM>/<TT>/<session_id>.json` | Ausgabe von `opencode session export <ID>` (inkl. Kind-/Subagent-Sitzungen) |
| `codex` | `codex/sessions/<JJJJ>/<MM>/<TT>/rollout-<zeit>-<id>.jsonl` | bytegetreue Spiegelung von `~/.codex/sessions` |
| `claude` | `claude/projects/<projektordner>/<session_id>.jsonl` und Artefakte | bytegetreue Spiegelung von `~/.claude/projects` |

Änderungen werden inkrementell erkannt (Größe/Änderungszeit, optional SHA-256).

### 8. Betriebsdateien im Verwaltungsbereich

#### 8.1 Gesamtindex `status_registry/storage_index.json`

```jsonc
{
  "schema_version": 1,
  "generated_at": "…",
  "coverage": { "percent": 100.0,
                "sources": { "<quelle>": { "indexed": 0, "candidates": 0, "percent": 100.0, "failed_files": [] } } },
  "conversations": { "<schlüssel>": { "source": "…", "kind": "conversation|session|artifact",
                                      "relative_path": "…", "…": "…" } }
}
```

Schlüssel: ChatGPT `<conversation_id>`, lokale Quellen `<quelle>:<kind>:<id>`.
ChatGPT-Einträge tragen zusätzlich u. a. `title`, `create_time`,
`remote_updated_at`, `is_archived`, `json_complete`, `files_complete`,
`file_reference_count`, `file_materialized_count`, `file_sha256`,
`raw_integrity_ok`, `acquisition_source`. Coverage = `100 · indexed / candidates`.

#### 8.2 Dateiindex `status_registry/file_index.json`

```jsonc
{ "schema_version": 1, "generated_at": "…",
  "files": { "<file_id>": { "file_id": "…", "sources": ["chatgpt"],
                            "references": [ { "conversation_id": "…", "message_id": "…", "node_id": "…" } ] } } }
```

#### 8.3 Dateistatus `status_registry/file_status.json`

```jsonc
{ "schema_version": 1, "generated_at": "…",
  "files": { "<file_id>": { "file_id": "…", "state": "UNAVAILABLE", "http_status": 404, "detail": "…",
                            "attempts": 1, "first_seen": "…", "last_seen": "…" } } }
```

#### 8.4 Quarantäne `status_registry/quarantine.json`

ChatGPT-Konversationen und -Dateien, die dauerhaft mit derselben
Fehlersignatur scheitern (Schema-Version 1). Aufnahme nur, wenn der Server
geantwortet hat, andere Anfragen im selben Lauf funktionierten, die Signatur
gleich bleibt, mehrere getrennte Läufe betroffen sind und die Vorfälle zeitlich
gespreizt liegen; nie bei 429, 401/403, 404. Jeder Eintrag hat `review_after`.

#### 8.5 Laufbericht `runs/sync_<UTC>.json` (Laufbericht-Schema 4)

```jsonc
{
  "schema_version": 4, "run_id": "…", "kind": "update",
  "started_at": "…", "finished_at": "…",
  "partial": false,
  "sources": { "<quelle>": {
      "ok": true, "stats": { "sessions_*": 0, "files_*": 0 }, "errors": [],
      "started_at": "…", "finished_at": "…", "duration_seconds": 0.0,
      "items": { "fetched": [ { "id": "…", "kind": "…", "action": "new|changed|…" } ],
                 "failed":  [ { "id": "…", "error": "…" } ] },
      "detail": {} } },
  "totals": { "sessions_total": 0, "sessions_fetched": 0, "sessions_failed": 0,
              "files_materialized": 0, "files_failed": 0, "requests_total": 0 },
  "errors": []
}
```

Bei ChatGPT stehen unter `detail` zusätzlich `listing`, `verification`,
`requests`, `rate_limit` (`stopped`, `open_conversations`, `estimated_full_at`),
`browser` und `dev_mode`. Laufberichte sind Herkunftsnachweis.

#### 8.6 Index-Fragment `staging/index/<quelle>.fragment.json`

```jsonc
{ "fragment_schema_version": 1, "source": "…", "generated_at": "…",
  "candidates": 0, "indexed": 0, "coverage_percent": 100.0, "failed_files": [],
  "entries": { "<schlüssel>": { "…": "…" } }, "file_refs": {} }
```

#### 8.7 Aufgaben-State `tasks_sched.json`

Lokaler State des PyTaskManagers (`schema_version` 2, `kind: local`,
`default_owner`, `project_root`, `tasks{<task_id>: …}`) mit gespeichertem Plan
je Aufgabe unter `metadata.chatexporter` (Befehl, Zeitplan, Einstellungen,
`config_file`, `storage`). Atomar geschrieben, Vorgänger als `.bak`.
Gegenstück global unter `%LOCALAPPDATA%\PyTaskManager\tasks_sched.json`.
Eine Aufgabe ruft `chatexporter … --config <config.yaml> --storage <storage> <befehl>`
auf; Eigentümer `chatexporter-<erste 8 Zeichen der Storage-ID>`.

#### 8.8 Befehlsprotokoll `logs/commands_<UTC>.jsonl`

Eine JSON-Zeile je Befehl: `timestamp`, `finished_at`, `duration_seconds`,
`command`, `program`, `argv`, `exit_code`, `interrupted`, `cwd`, `config_file`,
`version`, `code_dir`, `python`, `summary`. Eine Datei je Zeitraum
`logging.rotation`; ältere als `logging.retention` werden entfernt.

#### 8.9 `OVERVIEW.md`

Von `status` erzeugte Bestandsübersicht je Quelle.

#### 8.10 Zwischenablage `staging/`

Unterordner je Schreibbereich (`conversations`, `library`, `runs`, `index`,
`opencode`, `codex`, `claude`, `exports`). Eine Datei liegt hier nur, bis sie
vollständig geschrieben ist. Nach jedem Befehl werden leere Ordner in
`staging/` und `status_registry/.staging/` entfernt; Reste (`*.tmp`) entfernt `cleanup`.

#### 8.11 Sperre `lock` / `lock.json`

`lock` wird während eines schreibenden Befehls (`update`, `index`, `cleanup`,
`export`, schreibende Provider-Befehle) vom Betriebssystem exklusiv gesperrt
(wird auch bei einem Absturz frei). `lock.json` nennt währenddessen den
Inhaber (`pid`, `command`, `since`) und wird danach entfernt. Ein zweiter
schreibender Befehl endet mit Exitcode 2 und nennt den Inhaber.

### 9. Exporte `exports/`

- `exports/<format>/<quelle>/<JJJJ-MM>/<id>.md|json` – je Gespräch und Format eine Datei.
- `exports/manifests/export_<UTC>.json` – Export-Manifest (`schema_version` 2,
  `started_at`, `finished_at`, `formats`, `outputs`, `processor_runs`,
  `errors`, `failures`).

Exporte lesen nur den Raw Storage, ändern ihn nie und lassen sich jederzeit neu
erzeugen. Dateien anderer Aufbauten im Ordner `exports/` gehören nicht zum Format.

### 10. Dateieigentum

| Bereich | Schreibt | Regel |
| --- | --- | --- |
| `.storage/storage.yaml` | Anlage des Storages | einmal; danach nur gelesen |
| `.storage/config.yaml` | Benutzer, `config set/reset` | gelesen; Sicherung vor Änderung |
| `.storage/.env` | Benutzer | gelesen |
| `.storage/state.yaml` | Bedienschicht nach jedem Befehl | aus der Registry erzeugt, nie gelesen |
| `.storage/logs/` | Befehlsprotokoll | nur geschrieben |
| `raw_storage/<quelle>/**` | nur diese Quelle, über die Zwischenablage | Quelldaten |
| `raw_storage/` (Wurzel) | niemand | nur Quellen-Ordner |
| `.storage/runs/` | Raw Session Updater (`update`), Provider im Einzellauf | eine Datei je Lauf |
| `status_registry/storage_index.json` | Raw Session Updater (`index`), ChatGPT (eigene Einträge) | atomar; fremde Einträge bleiben erhalten |
| `status_registry/file_index.json` | Raw Session Updater (`index`), ChatGPT (inkrementell) | abgeleitet |
| `status_registry/file_status.json`, `quarantine.json` | ChatGPT | operativer Status |
| `.storage/OVERVIEW.md` | Raw Session Updater (`status`) | generiert |
| `.storage/tasks_sched.json` | Zeitplanung | operativer State |
| `.storage/lock`, `lock.json` | Bedienschicht | nur während schreibender Befehle |
| `exports/` | Exporter | abgeleitet |

### 11. Schreibregeln und Integrität

1. Jede Datei: vollständig in die Zwischenablage schreiben, `fsync`, dann per
   Umbenennen ersetzen; Zwischenablage und Ziel liegen im selben Storage (selbes Laufwerk).
2. Quelldaten werden nie still verändert; abgeleitete Felder sind als solche gekennzeichnet.
3. Inkrementelle Läufe sind idempotent.
4. Ein Index-Neuaufbau (`index`) setzt den Gesamtindex aus den Fragmenten aller
   aktiven Quellen zusammen und prüft doppelte Schlüssel.
5. Ein Ordner, der nicht eindeutig Storage-Schema 2 oder leer ist, wird nicht verändert.

### 12. Gleichzeitigkeit

- Je Storage höchstens ein schreibender Befehl; lesende Befehle (`check`,
  `status`, Anzeigen) laufen ohne Sperre.
- Verschiedene Storages können gleichzeitig bearbeitet werden.
