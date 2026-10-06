# Ablage und Dateiformate

## 1. Storage

Ein **Storage** ist eine autarke Dateninstanz (Begriff:
[STORAGE_KONZEPT.md](STORAGE_KONZEPT.md); Ort und Auswahl:
[KONFIGURATION.md](KONFIGURATION.md)). Das Format ist als **Storage-Schema**
versioniert; dieses Programm arbeitet mit **Storage-Schema 2**. Vollständige,
eigenständige Beschreibung je Storage-Schema: [storage_schema/](storage_schema/README.md).

```text
<storage>/
├── raw_storage/                     nur Quellen-Ordner (quellenübergreifende Prüfregel)
│   ├── chatgpt/
│   │   ├── conversations/YYYY/MM/DD/<conversation_id>.json   Envelope je Konversation
│   │   └── library/
│   │       ├── files/<file_id>/     content.<ext> + metadata.json
│   │       └── audio/<file_id>/     Sprachaufnahmen
│   ├── opencode/sessions/…          OpenCode-Exporte
│   ├── codex/sessions/…             Spiegel von ~/.codex/sessions
│   └── claude/projects/…            Spiegel von ~/.claude/projects
├── .storage/                        Verwaltungsbereich, keine Quelldaten (früher „runtime/“)
│   ├── storage.yaml                 Marker: storage_schema, ID, Name, Anlagezeitpunkt (einmal geschrieben)
│   ├── config.yaml, .env            Storage-Konfiguration (gelesen)
│   ├── state.yaml                   Gesamtsicht aus der Registry (nur geschrieben)
│   ├── runs/sync_<UTC>.json         Laufberichte (Schema 4)
│   ├── staging/                     temporär (atomares Schreiben, Fragmente); leere Ordner werden entfernt
│   ├── lock, lock.json              Sperre für schreibende Läufe (lock.json nennt den Inhaber)
│   ├── status_registry/
│   │   ├── storage_index.json       Gesamtindex aller Quellen
│   │   ├── file_index.json          Rückwärtsindex Datei → Konversation/Nachricht
│   │   ├── file_status.json         Dateistatus (z. B. UNAVAILABLE nach HTTP 404)
│   │   └── quarantine.json          ChatGPT-Quarantäne (falls aktiviert)
│   ├── logs/commands_<UTC>.jsonl    Befehlsprotokoll (Standard logging.dir)
│   ├── tasks_sched.json             Zeitplanung: lokaler State der Aufgaben (task_scheduler.state_file)
│   └── OVERVIEW.md                  generierte Übersicht (kein Source of Truth)
└── exports/                         Exporter: <format>/<quelle>/<JJJJ-MM>/<id>, manifests/ (abgeleitet, jederzeit neu erzeugbar)
```

## 2. Dateieigentum

| Bereich | Schreibt | Regel |
| --- | --- | --- |
| `raw_storage/<quelle>/**` | nur diese Quelle, über Staging | Quelldaten, nie von anderen |
| `raw_storage/` (Wurzel) | niemand | nur Quellen-Ordner |
| `.storage/runs/sync_*.json` | Raw Session Updater (`update`) bzw. Provider im Einzellauf | ein File pro Lauf, Schema 4 |
| `status_registry/storage_index.json` | Raw Session Updater (`index`, vollständig) und ChatGPT (eigene Einträge, inkrementell) | atomar; fremde Einträge bleiben erhalten |
| `status_registry/file_index.json` | Raw Session Updater (`index`) und ChatGPT (inkrementell) | abgeleitet, rebuildbar |
| `status_registry/file_status.json`, `quarantine.json` | ChatGPT | operativer Status, kein Quelldatum |
| `.storage/OVERVIEW.md` | Raw Session Updater (`status`) | generiert |
| `.storage/tasks_sched.json` | Zeitplanung (`task …`, über den PyTaskManager) | State der geplanten Aufgaben mit gespeichertem Plan; atomar, mit `.bak`; kein Quelldatum. Das Gegenstück liegt global unter `%LOCALAPPDATA%\PyTaskManager\` |
| `.storage/storage.yaml` | Anlage bzw. `storage migrate` | einmal geschrieben; Marker der Formaterkennung |
| `.storage/state.yaml` | Bedienschicht nach jedem Befehl | aus der Registry erzeugt, nie gelesen |
| `exports/` | Exporter (`export`) | abgeleitete Artefakte; liest nur aus `raw_storage`, ändert ihn nie |

## 3. Gesamtindex `storage_index.json`

```jsonc
{
  "schema_version": 1,
  "generated_at": "…",
  "coverage": {
    "percent": 100.0,
    "sources": { "chatgpt": { "indexed": 3095, "candidates": 3095, "percent": 100.0, "failed_files": [] } }
  },
  "conversations": { "<schlüssel>": { "source": "chatgpt", "kind": "conversation", "relative_path": "…", "…": "…" } }
}
```

Coverage = `100 · indexed / candidates` je Quelle und gesamt. Normalfall 100,0;
jeder Abzug ist über `failed_files` begründet.

## 4. Laufbericht (Run-Manifest, Schema 4)

```jsonc
{
  "schema_version": 4,
  "run_id": "update_…", "kind": "update",
  "started_at": "…", "finished_at": "…",
  "partial": false,                        // true, sobald eine Quelle ok=false hat
  "sources": { "<quelle>": {
      "ok": true, "stats": { "sessions_*": 0, "files_*": 0 }, "errors": [],
      "started_at": "…", "finished_at": "…", "duration_seconds": 0.0,
      "items": { "fetched": [ {"id": "…", "kind": "…", "action": "new|changed|…"} ],
                 "failed": [ {"id": "…", "error": "…"} ] },
      "detail": {} } },
  "totals": { "sessions_total": 0, "sessions_fetched": 0, "sessions_failed": 0,
              "files_materialized": 0, "files_failed": 0,
              "requests_total": 0 },     // an externe Dienste gesendete Anfragen (heute nur ChatGPT)
  "errors": []
}
```

Beim ChatGPT-Abschnitt stehen unter `sources.chatgpt.detail` zusätzlich
`listing` (Modus, Grenze), `verification` (Grenzprüfung) und `requests`
(Anfragen je Kategorie). Siehe [CHATGPT.md](providers/CHATGPT.md), Abschnitt 4.

Laufberichte sind Provenienz, kein Source of Truth. Ältere Schema-3-Dateien
bleiben als Historie liegen.

## 5. ChatGPT-Envelope (`conversations/…/<id>.json`)

| Feld | Inhalt |
| --- | --- |
| `storage_schema_version` | `1` |
| `provider`, `conversation_id` | `chatgpt`, ID |
| `remote_summary` | Listing-Daten (Titel, Zeiten, Archiv-/Stern-Status, `gizmo_id`, …) |
| `acquisition` | `json_complete`, `files_complete`, `complete`, `source` (`api` \| `imported_data`), Zeitpunkt, Graph-Kennzahlen, Warnungen |
| `raw` | unveränderte API-Antwort (Nachrichtengraph) |
| `textdocs` | Canvas-Dokumente |
| `file_references`, `tool_references` | abgeleitete Verweise (mit `message_id`/`node_id`) |
| `integrity.raw_payload_sha256` | Hash über `raw` (kanonisches JSON) |

`raw` wird nie verändert; alle anderen Felder sind abgeleitet und können mit
`chatexporter-chatgpt migrate-store` neu berechnet werden.

Dateien in `library/` tragen in `metadata.json` unter `_local` ihre Herkunft
(`conversation_id`, `message_id`, `node_id`, `references[]`).
