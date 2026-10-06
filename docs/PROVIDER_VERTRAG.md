# Provider-Vertrag

Jede Quelle ist ein **Provider**: ein Python-Modul (oder Paket) unter
`chatexporter.providers`, das fünf Funktionen mit fester Aufrufform anbietet.
Der Raw Session Updater kennt Provider ausschließlich über diesen Vertrag
(`raw_session_updater/registry.py`).

Herkunft: Fortschreibung von `_dokumentation/20_KONZEPTE/PROVIDER_UND_WRAPPER_VERTRAG.md`
(„Wrapper“ heißt jetzt „Raw Session Updater“). Abweichungen vom dortigen Stand sind unten
vermerkt.

## 1. Die fünf Funktionen

| Funktion | Updater-Befehl | Garantien | Rückgabe |
| --- | --- | --- | --- |
| `update(cfg, **optionen)` | `chatexporter-update` | lädt neue/geänderte Daten **atomar** (Staging → Commit); schreibt Quelldaten nur unter `raw_storage/<quelle>/`; Datensatz-Fehler → nächster Datensatz | Ergebnis (Abschnitt 3) |
| `recreate_index(cfg)` | `chatexporter-index` | baut das Fragment **deterministisch** aus den Quelldaten; schreibt den Gesamtindex **nicht** | Fragment (Abschnitt 4) |
| `check_storage_health(cfg, deep=False)` | `chatexporter-check` | **read-only** | Bericht mit `ok: bool` |
| `cleanup_storage(cfg, dry_run=False)` | `chatexporter-cleanup` | entfernt nur definierte Reste, **niemals Quelldaten** | Bericht |
| `state_n_stats(cfg)` | `chatexporter-status` | Momentaufnahme, kein Netz | Snapshot, möglichst mit `sessions_total`, `files_*_distinct`, `index_coverage` |

Dazu bietet jeder Provider eine Kommandozeile `main(argv) -> int` (von der
Bedienschicht als `chatexporter-<quelle>` bereitgestellt).

Aufrufmodell: **sequenziell**, eine Quelle nach der anderen, Reihenfolge wie in
`raw_session_updater.sources`.

## 2. Eingabe: das Vertrags-Mapping

Der Raw Session Updater übergibt jedem Provider ein Mapping (`RawSessionUpdaterConfig.provider_mapping`):

| Schlüssel | Inhalt |
| --- | --- |
| `source` | Name der Quelle |
| `config_file` | Pfad der gemeinsamen config.yaml (oder `None`) |
| `data_root` | Wurzel des Storages (Elternordner von `raw_storage`) |
| `raw_root`, `store_root` | Wurzel der Quelldaten (`…/raw_storage`) |
| `runtime_root` | Verwaltungsbereich des Storages (`…/.storage`) |
| `status_root` | Statusablage (`…/.storage/status_registry`) |
| weitere | alle Schlüssel aus `providers.<quelle>` der config.yaml |

Die Pfadschlüssel setzt immer der Raw Session Updater; `providers.<quelle>` kann sie nicht
überschreiben.

**Optionen** (`**optionen` bei `update`): Der Raw Session Updater reicht `no_files`,
`non_interactive`, `listing_mode` und `progress` weiter, filtert
aber alles heraus, was die Funktion nicht deklariert. Ein schlanker Provider
implementiert nur, was er braucht (z. B. kennt nur ChatGPT `listing_mode`).

ChatGPT akzeptiert zusätzlich ein eigenes `AppConfig`-Objekt (Direktaufruf);
aus dem Mapping baut er es selbst über `config_file` (`contract.app_config`).

## 3. Ergebnis von `update`

```jsonc
{
  "source": "chatgpt",
  "ok": true,                      // false = Quelle fehlgeschlagen/abgebrochen
  "stats": {                       // Einheitsschema; Quelle ergänzt eigene Zähler
    "sessions_total": 0, "sessions_new": 0, "sessions_changed": 0,
    "sessions_unchanged": 0, "sessions_fetched": 0, "sessions_failed": 0,
    "files_materialized": 0, "files_failed": 0,
    "requests_total": 0            // optional: an externe Dienste gesendete Anfragen
  },
  "errors": [],                    // redigierte Fehlerzeilen
  "detail": {},                    // optional, quellenspezifisch (ChatGPT: Listing, Rate-Limit, Plan)
  "items": {                       // optional, empfohlen: WAS wurde gespeichert/was nicht
    "fetched": [{"id": "…", "kind": "session", "action": "new"}],
    "failed":  [{"id": "…", "error": "…"}]
  },
  "exit_code": 0                   // optional
}
```

`items` macht im Laufbericht nachvollziehbar, was je Quelle genau geholt
wurde. Unveränderte Einträge werden nicht aufgeführt. Alle vier Provider
liefern es; ChatGPT zusätzlich `items.files` (neu geladene Dateien).

`sessions_*` ist generisch: bei ChatGPT = Konversation, bei OpenCode/Codex/
Claude = Sitzung. Wirft `update` eine Ausnahme, trägt der Raw Session Updater die Quelle
mit `ok: false` und der Fehlermeldung ein und macht mit der nächsten weiter.

## 4. Fragment von `recreate_index`

```jsonc
{
  "fragment_schema_version": 1,
  "source": "codex",
  "generated_at": "…",
  "candidates": 12,                // gefundene Datensätze
  "indexed": 12,                   // davon erfolgreich indexiert
  "coverage_percent": 100.0,
  "failed_files": [],              // Strings (relativ zur Quelle) oder {file, error, source}
  "entries": { "<schlüssel>": { "source": "codex", "kind": "session", "relative_path": "…", "…": "…" } },
  "file_refs": { "<file_id>": [ {"conversation_id": "…", "message_id": "…", "node_id": "…"} ] }
}
```

Regeln (`raw_session_updater/fragments.py`, fail-closed):

- Jeder Eintrag hat `source` (= Fragment-Quelle), `kind`, `relative_path`.
- Schlüssel **ohne** Doppelpunkt müssen dem ID-Feld entsprechen
  (`conversation_id`, `session_id` oder `record_id`) – so bei ChatGPT.
- Schlüssel **mit** Doppelpunkt beginnen mit `<quelle>:<kind>:` – so bei den
  dateiabbildenden Quellen.
- Ein ungültiges Fragment oder eine ID, die in zwei Quellen vorkommt, führt
  dazu, dass **nichts** geschrieben wird (Exit 2, alter Index bleibt).
- Datensatz-Fehler senken nur die Coverage (`failed_files`), sie verhindern
  den Merge nicht.

## 5. Exitcodes

`0` ok · `1` abgeschlossen mit fachlichen Fehlern · `2` abgebrochen/Teilausfall.
Gilt für Raw Session Updater und Provider-Kommandozeilen gleichermaßen.

## 6. Minimalvertrag für eine neue Quelle

1. Modul `src/chatexporter/providers/<quelle>.py` (oder Paket) mit den fünf
   Funktionen und `main(argv)`.
2. Quelldaten nur unter `<raw_root>/<quelle>/`, atomar über Staging
   (`<runtime_root>/staging/<quelle>/`).
3. Eine Zeile in `raw_session_updater/registry.py` → `PROVIDER_MODULES`.
4. Eine Zeile in `cli/main.py` → `PROVIDER_CLIS` und ein Einstiegspunkt in
   `pyproject.toml` (`chatexporter-<quelle>`).
5. Keine Imports aus `chatexporter.raw_session_updater`, `chatexporter.cli` oder anderen
   Providern (prüft `tests/test_independence.py`).

Rate-Limits, Fehlerbudgets und Quarantäne sind **kein** Vertragsbestandteil –
sie sind ChatGPT-spezifisch und bleiben dort.

## 7. Abweichungen gegenüber dem Konzeptdokument (Ist-Zustand)

- **Gesamtindex-Schreiber:** Das Konzept nennt den Updater-Merge als einzigen
  Schreiber von `storage_index.json`. Tatsächlich pflegt der ChatGPT-Provider
  seine eigenen Einträge dort auch **inkrementell** (während `update`,
  `rebuild-index`, Index-Selbstheilung); Einträge anderer Quellen lässt er
  dabei unverändert. `chatexporter-index` ist der vollständige,
  deterministische Neuaufbau über alle Quellen.
- **Schaltstelle:** Statt der Konstante `PROVIDERS` im Code bestimmt jetzt
  `raw_session_updater.sources` in der config.yaml, welche Quellen aktiv sind. Die direkte
  Provider-Kommandozeile (`chatexporter-chatgpt update`) läuft unabhängig davon.
