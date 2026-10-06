# Storage-Schema 1

> **Storage-Schema 1** bezeichnet das **Format des Datenbestands** (Verzeichnisaufbau,
> Dateien, Bezeichnungen, Regeln). Die Nummer ist eine eigene Zählung und hat
> **nichts mit der Programmversion** (z. B. `0.0.0.dev6`) zu tun. Schreibweise:
> in Texten „Storage-Schema 1“, in Dateinamen und Kennungen `storage-schema-1`.

---

## Teil A – Übersicht

### Verzeichnisbaum

```text
<datenordner>/                               storage.data_root (Standard: data, relativ zur config.yaml)
├── raw_storage/                             Quelldaten; enthält nur Quellen-Ordner
│   ├── chatgpt/
│   │   ├── conversations/<JJJJ>/<MM>/<TT>/<conversation_id>.json    Envelope je Konversation
│   │   └── library/
│   │       ├── files/<file_id>/             content.<ext> + metadata.json
│   │       └── audio/<file_id>/             Sprachaufnahmen (content.<ext> + metadata.json)
│   ├── opencode/sessions/<JJJJ>/<MM>/<TT>/<session_id>.json         Export je Sitzung
│   ├── codex/sessions/<JJJJ>/<MM>/<TT>/rollout-….jsonl              bytegetreue Spiegelung
│   └── claude/projects/<projektordner>/<session_id>.jsonl           bytegetreue Spiegelung (+ Artefakte)
├── runtime/                                 Betriebsablage: keine Quelldaten, jederzeit neu erzeugbar
│   ├── runs/sync_<UTC>.json                 Laufberichte (Laufbericht-Schema 4)
│   ├── status_registry/
│   │   ├── storage_index.json               Gesamtindex aller Quellen
│   │   ├── file_index.json                  Rückwärtsindex Datei → Konversation/Nachricht
│   │   ├── file_status.json                 Dateistatus (z. B. UNAVAILABLE nach HTTP 404)
│   │   └── quarantine.json                  ChatGPT-Quarantäne (nur wenn Einträge bestehen)
│   ├── .staging/                            Zwischenablage für atomares Schreiben
│   │   ├── conversations/ library/ runs/    ChatGPT
│   │   ├── opencode/ codex/ claude/         lokale Quellen
│   │   └── index/<quelle>.fragment.json     Index-Fragmente
│   ├── tasks_sched.json                     lokaler State der geplanten Aufgaben (falls angelegt)
│   ├── logs/commands_<UTC>.jsonl            Befehlsprotokoll – nur wenn logging.dir hierher zeigt
│   └── OVERVIEW.md                          generierte Übersicht
└── exports/                                 Exporte (abgeleitet, jederzeit neu erzeugbar)
    ├── <format>/<quelle>/<JJJJ-MM>/<id>.<ext>
    ├── manifests/export_<UTC>.json
    └── .staging/                            Zwischenablage des Exporters
```

### Wichtigste Fakten und Regeln

- **Erkennung:** Es gibt keinen Marker. Ein Datenordner hat Storage-Schema 1, wenn
  `runtime/` mit `runs/` oder `status_registry/` **und** `raw_storage/` vorhanden
  sind und **kein** Ordner `.storage/` existiert.
- **Keine Identität, keine eigene Konfiguration:** Der Datenordner hat weder ID
  noch Name noch Konfigurationsdatei. Alle Einstellungen stehen in der
  `config.yaml` des Programms; der Datenordner ist über `storage.data_root` gewählt.
- **Quelldaten sind unantastbar:** `raw_storage/<quelle>/` schreibt nur die
  jeweilige Quelle. Der Inhalt `raw` eines ChatGPT-Envelopes wird nie verändert.
- **Atomar:** Jede Datei wird erst in einer Zwischenablage (`.staging/`)
  vollständig geschrieben und dann per Umbenennen an ihren Platz gesetzt.
- **Betriebsablage ≠ Quelldaten:** Alles unter `runtime/` und `exports/` ist
  abgeleitet oder operativ und lässt sich neu erzeugen.
- **Gesamtindex:** ein Index für alle Quellen; Schlüssel ChatGPT = `conversation_id`,
  lokale Quellen = `<quelle>:<kind>:<id>`. Abdeckung (coverage) 100 % ist der Normalfall.
- **Keine Sperre:** Gleichzeitige Läufe auf demselben Datenordner werden nicht verhindert.
- **Zwischenablagen bleiben liegen:** Ordner unter `.staging/` werden nicht
  automatisch entfernt.
- **Kein Zustand im Datenordner** außer den Betriebsdateien; eine Gesamtsicht
  gibt es nur als `OVERVIEW.md`.

---

## Teil B – Vollständige Dokumentation

### 1. Begriffe

| Begriff | Bedeutung |
| --- | --- |
| Datenordner | Wurzel des Datenbestands (`storage.data_root`) |
| Raw Storage | `raw_storage/`: Quelldaten aller Quellen |
| Quelle | `chatgpt`, `opencode`, `codex`, `claude`; je Quelle ein Ordner in `raw_storage/` |
| Betriebsablage | `runtime/`: Laufberichte, Statusablage, Zwischenablage, Übersicht |
| Statusablage | `runtime/status_registry/`: Gesamtindex, Dateiindex, Dateistatus, Quarantäne |
| Staging / Zwischenablage | `runtime/.staging/` und `exports/.staging/`: unfertige Dateien vor dem Umbenennen |
| Laufbericht | `runtime/runs/sync_<UTC>.json`: Ergebnis eines Laufs |
| Envelope | Datei je ChatGPT-Konversation mit Rohdaten und abgeleiteten Angaben |
| Fragment | Index-Anteil einer Quelle, aus dem der Gesamtindex zusammengesetzt wird |
| Exporte | `exports/`: aus dem Raw Storage erzeugte Markdown-/JSON-Dateien |

### 2. Erkennung

| Prüfung | Bedingung |
| --- | --- |
| Betriebsablage | `runtime/` ist ein Ordner und enthält `runs/` oder `status_registry/` |
| Quelldaten | `raw_storage/` ist ein Ordner |
| Ausschluss | `.storage/` existiert nicht |

Alle drei Bedingungen müssen zutreffen. Fremde Dateien im Datenordner (z. B.
HTML-Betrachter, Notizen) sind erlaubt und gehören nicht zum Format.

### 3. Ort und Konfiguration

| Einstellung (config.yaml des Programms) | Standard | Bedeutung |
| --- | --- | --- |
| `storage.data_root` | `data` (relativ zur config.yaml) | Datenordner |
| `storage.raw_root` | `<datenordner>/raw_storage` | abweichender Ort der Quelldaten |
| `storage.runtime_root` | `<datenordner>/runtime` | abweichender Ort der Betriebsablage |
| `storage.status_root` | `<runtime>/status_registry` | abweichender Ort der Statusablage |
| `exporter.root` | `<datenordner>/exports` | abweichender Ort der Exporte |
| `logging.dir` | `logs` (relativ zur config.yaml) | Befehlsprotokoll; liegt nur im Datenordner, wenn so eingestellt (z. B. `data/runtime/logs`) |
| `task_scheduler.state_file` | `<datenordner>/runtime/tasks_sched.json` | lokaler State der Aufgaben |

Secrets stehen in einer `.env` neben der config.yaml, nie im Datenordner.
Der Spiegel der wirksamen Konfiguration liegt in der Registry unter
`HKCU\Software\ChatExporter\config\Current` (nur geschrieben, ohne Secrets).

### 4. Raw Storage

#### 4.1 ChatGPT – Konversationen

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
mit `chatexporter-chatgpt migrate-store` neu berechnen.

#### 4.2 ChatGPT – Dateien

`library/files/<file_id>/` und `library/audio/<file_id>/` enthalten je
`content.<ext>` (die Datei) und `metadata.json`. In `metadata.json` steht unter
`_local` die Herkunft: `conversation_id`, `message_id`, `node_id`, `references[]`.

#### 4.3 Lokale Quellen

| Quelle | Pfad | Inhalt |
| --- | --- | --- |
| `opencode` | `opencode/sessions/<JJJJ>/<MM>/<TT>/<session_id>.json` | Ausgabe von `opencode session export <ID>` (inkl. Kind-/Subagent-Sitzungen) |
| `codex` | `codex/sessions/<JJJJ>/<MM>/<TT>/rollout-<zeit>-<id>.jsonl` | bytegetreue Spiegelung von `~/.codex/sessions` |
| `claude` | `claude/projects/<projektordner>/<session_id>.jsonl` und Artefakte | bytegetreue Spiegelung von `~/.claude/projects` |

Änderungen werden inkrementell erkannt (Größe/Änderungszeit, optional SHA-256).

### 5. Betriebsablage `runtime/`

#### 5.1 Gesamtindex `status_registry/storage_index.json`

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
`raw_integrity_ok`, `acquisition_source`. Coverage = `100 · indexed / candidates`
je Quelle und gesamt; jeder Abzug ist über `failed_files` begründet.

#### 5.2 Dateiindex `status_registry/file_index.json`

```jsonc
{ "schema_version": 1, "generated_at": "…",
  "files": { "<file_id>": { "file_id": "…", "sources": ["chatgpt"],
                            "references": [ { "conversation_id": "…", "message_id": "…", "node_id": "…" } ] } } }
```

#### 5.3 Dateistatus `status_registry/file_status.json`

```jsonc
{ "schema_version": 1, "generated_at": "…",
  "files": { "<file_id>": { "file_id": "…", "state": "UNAVAILABLE", "http_status": 404, "detail": "…",
                            "attempts": 1, "first_seen": "…", "last_seen": "…" } } }
```

#### 5.4 Quarantäne `status_registry/quarantine.json`

ChatGPT-Konversationen und -Dateien, die dauerhaft mit derselben
Fehlersignatur scheitern (Schema-Version 1). Aufnahme nur, wenn der Server
geantwortet hat, andere Anfragen im selben Lauf funktionierten, die Signatur
gleich bleibt, mehrere getrennte Läufe betroffen sind und die Vorfälle zeitlich
gespreizt liegen; nie bei 429, 401/403, 404. Jeder Eintrag hat `review_after`.

#### 5.5 Laufbericht `runs/sync_<UTC>.json` (Laufbericht-Schema 4)

```jsonc
{
  "schema_version": 4, "run_id": "…", "kind": "update",
  "started_at": "…", "finished_at": "…",
  "partial": false,                              // true, sobald eine Quelle ok=false hat
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
`requests`, `rate_limit` (`stopped`, `open_conversations`, `estimated_full_at`)
und `browser`. Laufberichte sind Herkunftsnachweis, nicht Quelle der Wahrheit.

#### 5.6 Index-Fragment `.staging/index/<quelle>.fragment.json`

```jsonc
{ "fragment_schema_version": 1, "source": "…", "generated_at": "…",
  "candidates": 0, "indexed": 0, "coverage_percent": 100.0, "failed_files": [],
  "entries": { "<schlüssel>": { "…": "…" } }, "file_refs": {} }
```

#### 5.7 Aufgaben-State `tasks_sched.json`

Lokaler State des PyTaskManagers (`schema_version` 2, `kind: local`,
`default_owner`, `project_root`, `tasks{<task_id>: …}`) mit gespeichertem Plan
je Aufgabe unter `metadata.chatexporter` (Befehl, Zeitplan, Einstellungen).
Atomar geschrieben, Vorgänger als `.bak`. Gegenstück global unter
`%LOCALAPPDATA%\PyTaskManager\tasks_sched.json`.

#### 5.8 Befehlsprotokoll `logs/commands_<UTC>.jsonl` (falls hier abgelegt)

Eine JSON-Zeile je Befehl: `timestamp`, `finished_at`, `duration_seconds`,
`command`, `program`, `argv`, `exit_code`, `interrupted`, `cwd`, `config_file`,
`version`, `code_dir`, `python`, `summary`. Eine Datei je Zeitraum
`logging.rotation`; ältere als `logging.retention` werden entfernt.

#### 5.9 `OVERVIEW.md`

Von `status` erzeugte Bestandsübersicht je Quelle; keine Quelle der Wahrheit.

#### 5.10 Zwischenablage `.staging/`

Unterordner je Schreibbereich (`conversations`, `library`, `runs`, `index`,
`opencode`, `codex`, `claude`). Eine Datei liegt hier nur, bis sie vollständig
geschrieben ist; Reste (`*.tmp`) entfernt `cleanup`. Leere Ordner bleiben stehen.

### 6. Exporte `exports/`

- `exports/<format>/<quelle>/<JJJJ-MM>/<id>.md|json` – je Gespräch und Format eine Datei.
- `exports/manifests/export_<UTC>.json` – Export-Manifest (`schema_version` 2,
  `started_at`, `finished_at`, `formats`, `outputs`, `processor_runs`,
  `errors`, `failures`).
- `exports/.staging/` – Zwischenablage des Exporters.

Exporte sind abgeleitet: Sie lesen nur den Raw Storage, ändern ihn nie und
lassen sich jederzeit neu erzeugen. Dateien anderer Aufbauten im Ordner
`exports/` gehören nicht zum Format.

### 7. Dateieigentum

| Bereich | Schreibt | Regel |
| --- | --- | --- |
| `raw_storage/<quelle>/**` | nur diese Quelle, über die Zwischenablage | Quelldaten |
| `raw_storage/` (Wurzel) | niemand | nur Quellen-Ordner |
| `runtime/runs/` | Raw Session Updater (`update`), Provider im Einzellauf | eine Datei je Lauf |
| `status_registry/storage_index.json` | Raw Session Updater (`index`), ChatGPT (eigene Einträge) | atomar; fremde Einträge bleiben erhalten |
| `status_registry/file_index.json` | Raw Session Updater (`index`), ChatGPT (inkrementell) | abgeleitet |
| `status_registry/file_status.json`, `quarantine.json` | ChatGPT | operativer Status |
| `runtime/OVERVIEW.md` | Raw Session Updater (`status`) | generiert |
| `runtime/tasks_sched.json` | Zeitplanung | operativer State |
| `exports/` | Exporter | abgeleitet |

### 8. Schreibregeln und Integrität

1. Jede Datei: vollständig in die Zwischenablage schreiben, `fsync`, dann per
   Umbenennen ersetzen. Eine halb geschriebene Datei gibt es am Zielort nie.
2. Quelldaten werden nie still verändert; abgeleitete Felder sind als solche gekennzeichnet.
3. Inkrementelle Läufe sind idempotent.
4. Ein Index-Neuaufbau (`index`) setzt den Gesamtindex aus den Fragmenten aller
   aktiven Quellen zusammen und prüft doppelte Schlüssel.

### 9. Gleichzeitigkeit und Grenzen

- Es gibt keine Sperre; zwei schreibende Läufe auf demselben Datenordner
  werden nicht verhindert.
- Der Datenordner trägt keine Kennung; welcher Datenbestand gemeint ist,
  ergibt sich nur aus `storage.data_root`.
- Zustand (letzter Lauf, Bestand) ist nur aus Laufberichten, Index und
  `OVERVIEW.md` ablesbar.
